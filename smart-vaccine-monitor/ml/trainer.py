"""Avishkar Model Retrainer — regenerates the 3 pre-trained .pkl files.

This retrains Avishkar's models using the exact feature sets and
physics-based synthetic data generator from Avishkar models/Scripts/.

Usage:
    python -m ml.trainer            # regenerate all 3 models
    python -m ml.trainer --data     # only regenerate synthetic CSV data

Model → Algorithm → Features
  Model 1 : IsolationForest  → [temp, humidity, temp_delta, unsafe_mins]
  Model 2 : RandomForest     → [temp, temp_delta, humidity, unsafe_mins, damage, anomaly_flag]
  Model 3 : LinearRegression → [damage, temp, unsafe_mins]

Outputs: anomaly_model.pkl, predictor_model.pkl, potency_model.pkl
in the 'Avishkar models/' directory (the paths avishkar_adapter.py loads).
"""

import os
import sys
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, r2_score
import joblib
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.trainer")

# ── Output paths (must match avishkar_adapter.py) ──────────────────────────
_BASE_DIR = os.path.join("Avishkar models")
ANOMALY_MODEL_PATH = os.path.join(_BASE_DIR, "anomaly_model.pkl")
PREDICTOR_MODEL_PATH = os.path.join(_BASE_DIR, "predictor_model.pkl")
POTENCY_MODEL_PATH = os.path.join(_BASE_DIR, "potency_model.pkl")

# ── Training-data constants (must match avishkar_adapter.py / generate_synthetic_data.py) ──
SAFE_MIN = 2.0
SAFE_MAX = 8.0
DAMAGE_K = 0.08
POTENCY_K = 0.693


# ──────────────────────────────────────────────────────────────────────────
# Synthetic data generation (ported from Avishkar models/Scripts/)
# ──────────────────────────────────────────────────────────────────────────

def _gen_stable(rng):
    temp = rng.normal(5.0, 0.4)
    temp = np.clip(temp, SAFE_MIN + 0.1, SAFE_MAX - 0.5)
    hum = rng.normal(50, 5)
    return float(temp), float(hum)


def _gen_door_open(step, rng):
    peak = rng.uniform(8.5, 11)
    rise = int(rng.integers(3, 6))
    fall = int(rng.integers(10, 18))
    if step <= rise:
        temp = 5.0 + (peak - 5.0) * (step / rise)
    else:
        decay = (step - rise) / fall
        temp = peak * np.exp(-1.5 * decay) + 4.5 * (1 - np.exp(-1.5 * decay))
    hum = rng.normal(72, 6)
    return float(np.clip(temp, SAFE_MIN - 1, 20)), float(hum)


def _gen_power_failure(step, rng):
    rate = rng.uniform(0.30, 0.55)
    temp = 5.0 + rate * step + rng.normal(0, 0.2)
    hum = rng.normal(55, 4)
    return float(np.clip(temp, 4.5, 35)), float(hum)


def _gen_sensor_anomaly(rng):
    kind = rng.choice(["spike_high", "spike_low", "freeze"])
    if kind == "spike_high":
        return float(rng.uniform(22, 40)), float(rng.uniform(80, 99))
    elif kind == "spike_low":
        return float(rng.uniform(-10, 0)), float(rng.uniform(5, 15))
    else:
        temp = float(rng.choice([4.5, 5.0, 5.5])) + float(rng.normal(0, 0.001))
        hum = float(rng.choice([48, 50, 52])) + float(rng.normal(0, 0.001))
        return temp, hum


def _update_damage(temp, damage):
    if temp > SAFE_MAX:
        excess = temp - SAFE_MAX
        damage += DAMAGE_K * (1 + 0.15 * excess)
    return min(damage, 10.0)


def _compute_potency(damage):
    return round(float(np.clip(100.0 * np.exp(-POTENCY_K * damage / 10.0), 0, 100)), 2)


def _label_will_breach(temp_series, idx, horizon=10):
    future = temp_series[idx + 1: idx + 1 + horizon]
    return int(sum(t > SAFE_MAX for t in future) >= 5)


def generate_synthetic_data(n: int = 2000, n_batches: int = 5) -> pd.DataFrame:
    """Generate physics-based synthetic cold-chain data matching Avishkar training."""
    rng = np.random.default_rng(42)
    records = []
    batch_size = n // n_batches

    for batch_id in range(n_batches):
        damage = 0.0
        unsafe_mins = 0
        prev_temp = 5.0
        i = 0
        while i < batch_size:
            scenario = rng.choice(
                ["stable", "door_open", "power_failure", "anomaly"],
                p=[0.58, 0.17, 0.15, 0.10]
            )
            if scenario == "stable":
                duration = int(rng.integers(15, 40))
            elif scenario == "door_open":
                duration = int(rng.integers(15, 30))
            elif scenario == "power_failure":
                duration = int(rng.integers(18, 32))
            else:
                duration = int(rng.integers(8, 16))

            for step in range(duration):
                if i >= batch_size:
                    break
                if scenario == "stable":
                    temp, hum = _gen_stable(rng)
                elif scenario == "door_open":
                    temp, hum = _gen_door_open(step, rng)
                elif scenario == "power_failure":
                    temp, hum = _gen_power_failure(step, rng)
                else:
                    temp, hum = _gen_sensor_anomaly(rng)

                temp_delta = round(temp - prev_temp, 4)
                potency = _compute_potency(damage)
                a_flag = 1 if scenario == "anomaly" else 0

                records.append({
                    "batch_id": batch_id, "step": i,
                    "temp": round(float(temp), 3),
                    "humidity": round(float(np.clip(hum, 5, 100)), 2),
                    "temp_delta": temp_delta,
                    "unsafe_mins": unsafe_mins,
                    "damage": round(damage, 4),
                    "potency_pct": potency,
                    "scenario": scenario,
                    "anomaly_flag": a_flag,
                })

                damage = _update_damage(temp, damage)
                if temp > SAFE_MAX:
                    unsafe_mins += 1
                prev_temp = temp
                i += 1

    df = pd.DataFrame(records)
    temp_series = df["temp"].tolist()
    df["will_breach_10min"] = [
        _label_will_breach(temp_series, idx, horizon=10)
        for idx in range(len(df))
    ]
    return df


# ──────────────────────────────────────────────────────────────────────────
# Model training functions
# ──────────────────────────────────────────────────────────────────────────

def train_anomaly_model(df: pd.DataFrame = None) -> None:
    """Train Avishkar Model 1: IsolationForest anomaly detector.

    Features: [temp, humidity, temp_delta, unsafe_mins]
    Trains on normal (non-anomaly) data only — unsupervised.
    """
    logger.info("Training Avishkar Model 1 (IsolationForest — anomaly detection)...")
    if df is None:
        df = generate_synthetic_data()

    # Train on normal data only (matches Avishkar's train_model1.py)
    normal_df = df[df["scenario"] != "anomaly"]
    features = ["temp", "humidity", "temp_delta", "unsafe_mins"]
    X_train = normal_df[features]
    X_test = df[features]
    y_true = df["anomaly_flag"]

    model = IsolationForest(
        contamination=0.045,
        n_estimators=100,
        random_state=42,
    )
    model.fit(X_train)

    # Evaluate
    y_pred_raw = model.predict(X_test)
    y_pred = [1 if x == -1 else 0 for x in y_pred_raw]
    from sklearn.metrics import classification_report
    logger.info("Model 1 evaluation:\n" + classification_report(y_true, y_pred))

    joblib.dump(model, ANOMALY_MODEL_PATH)
    logger.info(f"✅ Model 1 saved → {ANOMALY_MODEL_PATH}")


def train_predictor_model(df: pd.DataFrame = None) -> None:
    """Train Avishkar Model 2: RandomForestClassifier breach predictor.

    Features: [temp, temp_delta, humidity, unsafe_mins, damage, anomaly_flag]
    Label:    will_breach_10min
    """
    logger.info("Training Avishkar Model 2 (RandomForest — breach prediction)...")
    if df is None:
        df = generate_synthetic_data()

    features = ["temp", "temp_delta", "humidity", "unsafe_mins", "damage", "anomaly_flag"]
    X = df[features]
    y = df["will_breach_10min"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=80,
        max_depth=10,
        class_weight="balanced",
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    logger.info("Model 2 evaluation:\n" + classification_report(y_test, y_pred))

    joblib.dump(model, PREDICTOR_MODEL_PATH)
    logger.info(f"✅ Model 2 saved → {PREDICTOR_MODEL_PATH}")


def train_potency_model(df: pd.DataFrame = None) -> None:
    """Train Avishkar Model 3: LinearRegression potency estimator.

    Features: [damage, temp, unsafe_mins]
    Label:    potency_pct
    """
    logger.info("Training Avishkar Model 3 (LinearRegression — potency estimation)...")
    if df is None:
        df = generate_synthetic_data()

    features = ["damage", "temp", "unsafe_mins"]
    X = df[features]
    y = df["potency_pct"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = LinearRegression()
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    logger.info(f"Model 3 R² score: {r2_score(y_test, y_pred):.4f}")

    joblib.dump(model, POTENCY_MODEL_PATH)
    logger.info(f"✅ Model 3 saved → {POTENCY_MODEL_PATH}")


def train_all() -> None:
    """Regenerate synthetic data and retrain all 3 Avishkar models."""
    logger.info("=" * 60)
    logger.info("  AVISHKAR MODEL RETRAINER — starting full pipeline")
    logger.info("=" * 60)

    # Generate data once and share across all 3 trainers
    logger.info("Generating synthetic cold-chain dataset (n=2000)...")
    df = generate_synthetic_data(n=2000, n_batches=5)
    logger.info(f"Dataset generated: {len(df)} rows, scenarios: {df['scenario'].value_counts().to_dict()}")

    train_anomaly_model(df)
    train_predictor_model(df)
    train_potency_model(df)

    logger.info("=" * 60)
    logger.info("  All 3 Avishkar models retrained and saved.")
    logger.info("  Restart the server to load the new models.")
    logger.info("=" * 60)


if __name__ == "__main__":
    train_all()
