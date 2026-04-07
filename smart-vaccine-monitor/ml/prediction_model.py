"""GradientBoosting-based prediction model for ETA to CRITICAL status."""

import os
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
import joblib
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.prediction_model")

MODEL_PATH = os.path.join("ml", "models", "prediction_model.joblib")


class PredictionModel:
    """Wraps scikit-learn GradientBoostingClassifier for CRITICAL status prediction.

    Features: [temp_internal, exposure_minutes, vvm_damage, risk_score, temp_trend_5min]
    Target: will_reach_critical_in_10min (bool)
    """

    def __init__(self):
        """Initialize the prediction model, loading or training as needed."""
        self.model: GradientBoostingClassifier = None
        self._load_or_train()

    def _load_or_train(self) -> None:
        """Load a saved model or train a new one on synthetic data."""
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

        if os.path.exists(MODEL_PATH):
            try:
                self.model = joblib.load(MODEL_PATH)
                logger.info(f"Prediction model loaded from {MODEL_PATH}")
                return
            except Exception as e:
                logger.warning(f"Failed to load prediction model: {e}. Retraining...")

        self._train_on_synthetic_data()

    def _train_on_synthetic_data(self) -> None:
        """Train on synthetic cold-chain scenario data."""
        logger.info("Training prediction model on synthetic data...")

        rng = np.random.RandomState(42)
        n_samples = 500

        # Scenario 1: Normal operation (no risk) — 200 samples
        n_normal = 200
        temp_normal = rng.normal(5.0, 1.0, n_normal)
        exposure_normal = rng.randint(0, 5, n_normal).astype(float)
        vvm_normal = rng.uniform(0.0, 0.1, n_normal)
        risk_normal = rng.uniform(0, 25, n_normal)
        trend_normal = rng.normal(0, 0.1, n_normal)
        labels_normal = np.zeros(n_normal)

        # Scenario 2: Warming trend (risk escalating) — 150 samples
        n_warming = 150
        temp_warming = rng.uniform(7.0, 12.0, n_warming)
        exposure_warming = rng.randint(5, 30, n_warming).astype(float)
        vvm_warming = rng.uniform(0.1, 0.5, n_warming)
        risk_warming = rng.uniform(30, 65, n_warming)
        trend_warming = rng.uniform(0.2, 1.0, n_warming)
        labels_warming = np.where(risk_warming > 55, 1, 0)

        # Scenario 3: Critical breach — 150 samples
        n_critical = 150
        temp_critical = rng.uniform(10.0, 18.0, n_critical)
        exposure_critical = rng.randint(15, 60, n_critical).astype(float)
        vvm_critical = rng.uniform(0.3, 0.9, n_critical)
        risk_critical = rng.uniform(55, 95, n_critical)
        trend_critical = rng.uniform(0.5, 2.0, n_critical)
        labels_critical = np.where(risk_critical > 60, 1, 0)

        # Combine all scenarios
        X = np.column_stack([
            np.concatenate([temp_normal, temp_warming, temp_critical]),
            np.concatenate([exposure_normal, exposure_warming, exposure_critical]),
            np.concatenate([vvm_normal, vvm_warming, vvm_critical]),
            np.concatenate([risk_normal, risk_warming, risk_critical]),
            np.concatenate([trend_normal, trend_warming, trend_critical]),
        ])
        y = np.concatenate([labels_normal, labels_warming, labels_critical])

        self.model = GradientBoostingClassifier(
            n_estimators=100,
            random_state=42,
            max_depth=4,
            learning_rate=0.1,
        )
        self.model.fit(X, y)

        joblib.dump(self.model, MODEL_PATH)
        logger.info(f"Prediction model trained on {n_samples} samples and saved to {MODEL_PATH}")

    def predict_eta(
        self,
        temp_internal: float,
        exposure_minutes: int,
        vvm_damage: float,
        risk_score: float,
        temp_trend_5min: float,
    ) -> int | None:
        """Predict estimated minutes until CRITICAL status is reached.

        Args:
            temp_internal: Current internal temperature.
            exposure_minutes: Cumulative exposure time.
            vvm_damage: Current VVM damage score.
            risk_score: Current risk score (0-100).
            temp_trend_5min: Temperature trend over last 5 minutes.

        Returns:
            Estimated minutes to CRITICAL, or None if already CRITICAL
            or no risk of reaching CRITICAL.
        """
        # If already CRITICAL, return None
        if risk_score >= 70:
            return None

        try:
            features = np.array([[
                temp_internal, float(exposure_minutes),
                vvm_damage, risk_score, temp_trend_5min
            ]])

            # Get probability of reaching critical
            proba = self.model.predict_proba(features)

            # Find the probability of the positive class (will reach critical)
            if proba.shape[1] >= 2:
                critical_prob = proba[0][1]
            else:
                critical_prob = proba[0][0]

            if critical_prob < 0.1:
                return None  # Very unlikely to reach critical

            # Estimate ETA based on probability and current risk trend
            # Higher probability = shorter ETA
            # Scale: prob 1.0 → ~2 min, prob 0.1 → ~60 min
            if critical_prob > 0:
                remaining_risk = 70 - risk_score
                rate = max(0.1, temp_trend_5min * 5 + critical_prob * 10)
                eta_minutes = max(1, int(remaining_risk / rate))
                eta_minutes = min(120, eta_minutes)  # Cap at 2 hours

                logger.debug(
                    f"ETA prediction: prob={critical_prob:.2f}, "
                    f"risk_remaining={remaining_risk:.1f}, eta={eta_minutes} min"
                )
                return eta_minutes
            return None

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return None


# Global singleton instance
prediction_model = PredictionModel()

# Temperature trend buffer for computing 5-minute trend
_temp_history: list[float] = []


def get_temp_trend(temp_internal: float) -> float:
    """Compute temperature trend over the last 5 readings.

    Args:
        temp_internal: Current temperature reading.

    Returns:
        Rate of temperature change (positive = warming).
    """
    _temp_history.append(temp_internal)
    if len(_temp_history) > 5:
        _temp_history.pop(0)

    if len(_temp_history) < 2:
        return 0.0

    # Simple linear trend: difference between newest and oldest
    trend = (_temp_history[-1] - _temp_history[0]) / len(_temp_history)
    return round(trend, 4)
