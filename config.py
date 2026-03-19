import os

# Load .env only in local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Angel One credentials
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY")
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Trading config
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", 10000))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", 3))

# Stocks to watch (NSE symbols)
WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "WIPRO", "AXISBANK", "KOTAKBANK", "LT"
]

# Strategy settings
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", 1.0)) / 100
TARGET_PCT    = float(os.getenv("TARGET_PCT", 2.0)) / 100
CANDLE_INTERVAL = "FIVE_MINUTE"
LOOKBACK_CANDLES = 100

# Market hours (IST)
MARKET_OPEN = os.getenv("MARKET_OPEN", "09:15")
MARKET_CLOSE = os.getenv("MARKET_CLOSE", "15:20")

# Paper trading mode
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() in ("true", "1", "yes")

# Auto trade: True = real orders, False = analysis only (Telegram signals)
AUTO_TRADE = os.getenv("AUTO_TRADE", "False").lower() in ("true", "1", "yes")

# Max total capital - trades beyond this will be rejected
MAX_CAPITAL = float(os.getenv("MAX_CAPITAL", 5000))
