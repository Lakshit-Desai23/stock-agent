import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from logzero import logger
import pickle
import os


MODEL_PATH = "model.pkl"
SCALER_PATH = "scaler.pkl"


def create_labels(df: pd.DataFrame, forward_candles: int = 3, target_pct: float = 0.015) -> pd.Series:
    """
    Label each candle:
      1 = price goes up by target_pct in next N candles (BUY signal)
      0 = no clear move (HOLD)
     -1 = price goes down by target_pct (SELL/SHORT signal)
    """
    labels = []
    closes = df["close"].values
    for i in range(len(closes) - forward_candles):
        future_max = max(closes[i+1:i+1+forward_candles])
        future_min = min(closes[i+1:i+1+forward_candles])
        if future_max >= closes[i] * (1 + target_pct):
            labels.append(1)
        elif future_min <= closes[i] * (1 - target_pct):
            labels.append(-1)
        else:
            labels.append(0)
    return pd.Series(labels)


def train_model(features: pd.DataFrame, labels: pd.Series):
    """Train Random Forest classifier."""
    scaler = StandardScaler()
    X = scaler.fit_transform(features)
    y = labels.values

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=5,
        random_state=42,
        class_weight="balanced"
    )
    model.fit(X, y)

    # Save model
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    with open(SCALER_PATH, "wb") as f:
        pickle.dump(scaler, f)

    logger.info("Model trained and saved.")
    return model, scaler


def load_model():
    """Load saved model and scaler."""
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)
        with open(SCALER_PATH, "rb") as f:
            scaler = pickle.load(f)
        return model, scaler
    return None, None


def predict_signal(model, scaler, features_row: pd.DataFrame) -> int:
    """
    Returns:
      1  = BUY
      0  = HOLD
     -1  = SELL/EXIT
    """
    try:
        X = scaler.transform(features_row)
        pred = model.predict(X)[0]
        proba = model.predict_proba(X)[0]
        confidence = max(proba)

        # Only act on high confidence signals
        if confidence < 0.45:
            return 0

        return int(pred)
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        return 0
