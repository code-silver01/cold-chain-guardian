"""Processing pipeline — orchestrates all processing stages per reading."""

from datetime import datetime
from typing import Optional
from models.schemas import SensorDataInput, ProcessedReading
from processing.baseline import baseline_learner
from processing.exposure import exposure_tracker
from processing.vvm import vvm_model
from processing.risk_engine import compute_risk_score
from ml.anomaly_detector import anomaly_detector
from ml.prediction_model import prediction_model, get_temp_trend
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.pipeline")


async def process_reading(sensor_data: SensorDataInput) -> ProcessedReading:
    """Run the complete processing pipeline on a single sensor reading.

    Pipeline stages:
      1. Update rolling baseline temperature statistics
      2. Run anomaly detection via IsolationForest
      3. Update exposure tracker (time outside safe range)
      4. Update VVM damage model (Arrhenius equation)
      5. Compute composite risk score and status
      6. Predict ETA to CRITICAL status

    Args:
        sensor_data: Validated sensor data input.

    Returns:
        ProcessedReading with all computed fields.
    """
    timestamp = sensor_data.timestamp or datetime.utcnow().isoformat()
    temp_internal = sensor_data.temp_internal
    temp_external = sensor_data.temp_external
    humidity = sensor_data.humidity

    logger.debug(
        f"Processing reading: temp_int={temp_internal:.1f}°C, "
        f"temp_ext={temp_external:.1f}°C, humidity={humidity:.1f}%"
    )

    # Stage 1: Update baseline
    baseline_learner.update(temp_internal)
    baseline_mean = baseline_learner.mean
    baseline_std = baseline_learner.std
    deviation = baseline_learner.deviation

    # Stage 2: Anomaly detection
    is_anomaly = anomaly_detector.predict(
        temp_internal=temp_internal,
        temp_external=temp_external,
        humidity=humidity,
        deviation_from_baseline=deviation,
    )

    # Stage 3: Exposure tracking
    exposure_minutes = exposure_tracker.update(temp_internal)

    # Stage 4: VVM damage (each reading ≈ 1 minute = 1/60 hour)
    vvm_damage = vvm_model.update(temp_internal, delta_time_hours=1.0 / 60.0)
    potency_percent = vvm_model.potency_percent

    # Stage 5: Risk score computation
    risk_score, status = compute_risk_score(
        temp_internal=temp_internal,
        baseline_mean=baseline_mean,
        baseline_std=baseline_std,
        exposure_minutes=exposure_minutes,
        vvm_damage=vvm_damage,
        is_anomaly=is_anomaly,
    )

    # Stage 6: ETA prediction
    temp_trend = get_temp_trend(temp_internal)
    eta_to_critical: Optional[int] = prediction_model.predict_eta(
        temp_internal=temp_internal,
        exposure_minutes=exposure_minutes,
        vvm_damage=vvm_damage,
        risk_score=risk_score,
        temp_trend_5min=temp_trend,
    )

    processed = ProcessedReading(
        timestamp=timestamp,
        temp_internal=temp_internal,
        temp_external=temp_external,
        humidity=humidity,
        risk_score=risk_score,
        status=status,
        vvm_damage=round(vvm_damage, 6),
        exposure_minutes=exposure_minutes,
        is_anomaly=is_anomaly,
        potency_percent=round(potency_percent, 2),
        eta_to_critical=eta_to_critical,
    )

    logger.info(
        f"Pipeline complete: status={status}, risk={risk_score:.1f}, "
        f"vvm={vvm_damage:.6f}, potency={potency_percent:.1f}%, "
        f"exposure={exposure_minutes}min, anomaly={is_anomaly}, "
        f"eta={eta_to_critical}"
    )

    return processed
