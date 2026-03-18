import pandas as pd
import numpy as np
from logzero import logger
from config import CANDLE_INTERVAL, LOOKBACK_CANDLES
from datetime import datetime, timedelta
import config


def get_symbol_token(smart_api, symbol: str) -> str:
    if config.PAPER_TRADING and smart_api is None:
        return f"MOCK-{symbol}"
    try:
        data = smart_api.searchScrip("NSE", symbol)
        for item in data["data"]:
            # Match exact EQ symbol
            if item["tradingsymbol"] == f"{symbol}-EQ":
                return item["symboltoken"]
        # Fallback: first EQ type
        for item in data["data"]:
            if item["tradingsymbol"].endswith("-EQ"):
                return item["symboltoken"]
    except Exception as e:
        logger.error(f"Token fetch failed for {symbol}: {e}")
    return None


def _mock_candles(symbol: str) -> pd.DataFrame:
    """Generate realistic-looking fake OHLCV data for testing."""
    np.random.seed(abs(hash(symbol)) % 1000)
    base = np.random.randint(500, 3000)
    n = LOOKBACK_CANDLES
    closes = base + np.cumsum(np.random.randn(n) * base * 0.005)
    opens = closes + np.random.randn(n) * base * 0.002
    highs = np.maximum(opens, closes) + abs(np.random.randn(n)) * base * 0.003
    lows = np.minimum(opens, closes) - abs(np.random.randn(n)) * base * 0.003
    volumes = np.random.randint(10000, 500000, n).astype(float)
    idx = pd.date_range(end=datetime.now(), periods=n, freq="5min")
    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=idx)
    return df.astype(float)


def fetch_candles(smart_api, symbol: str, token: str) -> pd.DataFrame:
    """Fetch OHLCV candle data for a symbol."""
    if config.PAPER_TRADING and smart_api is None:
        logger.info(f"[PAPER] Mock candles for {symbol}")
        return _mock_candles(symbol)
    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=5)  # enough for 100 5-min candles

        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": CANDLE_INTERVAL,
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        response = smart_api.getCandleData(params)
        if response["status"] and response["data"]:
            df = pd.DataFrame(
                response["data"],
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp").astype(float)
            return df.tail(LOOKBACK_CANDLES)
    except Exception as e:
        logger.error(f"Candle fetch failed for {symbol}: {e}")
    return None


def get_ltp(smart_api, symbol: str, token: str) -> float:
    """Get last traded price."""
    if config.PAPER_TRADING and smart_api is None:
        # Return last close of mock data as LTP
        df = _mock_candles(symbol)
        return round(float(df["close"].iloc[-1]), 2)
    try:
        data = smart_api.ltpData("NSE", symbol, token)
        return float(data["data"]["ltp"])
    except Exception as e:
        logger.error(f"LTP fetch failed for {symbol}: {e}")
    return None
