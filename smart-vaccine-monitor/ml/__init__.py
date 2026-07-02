"""ML package — Avishkar pre-trained models (IsolationForest, RandomForest, LinearRegression).

Key exports:
    avishkar          — AvishkarAdapter singleton (loads .pkl models)
    anomaly_detector  — thin wrapper around avishkar.detect_anomaly
    prediction_model  — thin wrapper around avishkar.predict_breach_probability / predict_potency
    train_all         — retrain all 3 models from ml.trainer
"""
