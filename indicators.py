import pandas as pd
import ta


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators to OHLCV dataframe."""

    # Trend
    df["ema_9"] = ta.trend.ema_indicator(df["close"], window=9)
    df["ema_21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)

    # Momentum
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)
    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    # Volatility
    bb = ta.volatility.BollingerBands(df["close"], window=20)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()
    df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)

    # Volume
    df["volume_sma"] = df["volume"].rolling(window=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma"]

    return df.dropna()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build ML feature set from indicators."""
    features = pd.DataFrame()

    features["rsi"] = df["rsi"]
    features["macd_hist"] = df["macd_hist"]
    features["ema_cross"] = df["ema_9"] - df["ema_21"]
    features["price_vs_ema50"] = (df["close"] - df["ema_50"]) / df["ema_50"]
    features["bb_position"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    features["volume_ratio"] = df["volume_ratio"]
    features["atr_pct"] = df["atr"] / df["close"]

    # Price action
    features["candle_body"] = (df["close"] - df["open"]) / df["open"]
    features["high_low_range"] = (df["high"] - df["low"]) / df["low"]

    return features.dropna()
