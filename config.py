import os
from dotenv import load_dotenv

load_dotenv()

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
STOP_LOSS_PCT = 0.015   # 1.5% stop loss
TARGET_PCT = 0.03       # 3% target (2:1 RR)
CANDLE_INTERVAL = "FIVE_MINUTE"
LOOKBACK_CANDLES = 100

# Market hours (IST)
MARKET_OPEN = os.getenv("MARKET_OPEN", "09:15")
MARKET_CLOSE = os.getenv("MARKET_CLOSE", "15:20")

# Paper trading mode - True = no real orders, only logs/alerts
PAPER_TRADING = False
