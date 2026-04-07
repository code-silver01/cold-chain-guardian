"""IsolationForest-based anomaly detection for sensor readings."""

import os
import numpy as np
from sklearn.ensemble import IsolationForest
import joblib
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.anomaly_detector")

MODEL_PATH = os.path.join("ml", "models", "anomaly_model.joblib")


class AnomalyDetector:
    """Wraps scikit-learn IsolationForest for real-time anomaly detection.

    Features used: [temp_internal, temp_external, humidity, deviation_from_baseline]
    """

    def __init__(self):
        """Initialize the anomaly detector, loading or training the model."""
        self.model: IsolationForest = None
        self._load_or_train()

    def _load_or_train(self) -> None:
        """Load a saved model or train a new one on synthetic data."""
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

        if os.path.exists(MODEL_PATH):
            try:
                self.model = joblib.load(MODEL_PATH)
                logger.info(f"Anomaly detection model loaded from {MODEL_PATH}")
                return
            except Exception as e:
                logger.warning(f"Failed to load anomaly model: {e}. Retraining...")

        self._train_on_synthetic_data()

    def _train_on_synthetic_data(self) -> None:
        """Train on 100 synthetic 'normal' cold-chain samples."""
        logger.info("Training anomaly detection model on synthetic data...")

        rng = np.random.RandomState(42)

        # Generate 100 normal readings
        # Normal operation: temp_internal around 4-6°C, external 20-25°C, humidity 40-60%
        n_samples = 100
        temp_internal = rng.normal(loc=5.0, scale=0.8, size=n_samples)
        temp_external = rng.normal(loc=22.0, scale=3.0, size=n_samples)
        humidity = rng.normal(loc=50.0, scale=5.0, size=n_samples)
        deviation = np.abs(temp_internal - 5.0) / 0.8  # deviation in std units

        X_train = np.column_stack([temp_internal, temp_external, humidity, deviation])

        self.model = IsolationForest(
            contamination=0.05,
            random_state=42,
            n_estimators=100,
        )
        self.model.fit(X_train)

        # Save the trained model
        joblib.dump(self.model, MODEL_PATH)
        logger.info(f"Anomaly detection model trained and saved to {MODEL_PATH}")

    def predict(self, temp_internal: float, temp_external: float,
                humidity: float, deviation_from_baseline: float) -> bool:
        """Predict whether a reading is anomalous.

        Args:
            temp_internal: Internal temperature in Celsius.
            temp_external: External temperature in Celsius.
            humidity: Relative humidity percentage.
            deviation_from_baseline: Standard deviations from baseline mean.

        Returns:
            True if the reading is anomalous, False otherwise.
        """
        try:
            features = np.array([[temp_internal, temp_external, humidity, deviation_from_baseline]])
            prediction = self.model.predict(features)
            is_anomaly = prediction[0] == -1
            if is_anomaly:
                logger.info(
                    f"ANOMALY DETECTED: temp={temp_internal:.1f}°C, "
                    f"ext={temp_external:.1f}°C, humidity={humidity:.1f}%, "
                    f"deviation={deviation_from_baseline:.2f}σ"
                )
            return is_anomaly
        except Exception as e:
            logger.error(f"Anomaly prediction failed: {e}")
            return False

    def retrain(self, X: np.ndarray) -> None:
        """Retrain the model on new data.

        Args:
            X: Feature matrix with columns [temp_internal, temp_external, humidity, deviation].
        """
        try:
            self.model = IsolationForest(
                contamination=0.05,
                random_state=42,
                n_estimators=100,
            )
            self.model.fit(X)
            joblib.dump(self.model, MODEL_PATH)
            logger.info(f"Anomaly model retrained on {X.shape[0]} samples")
        except Exception as e:
            logger.error(f"Anomaly model retraining failed: {e}")


# Global singleton instance
anomaly_detector = AnomalyDetector()
