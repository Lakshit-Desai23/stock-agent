"""
Stock Trading Agent - Full Algorithm
1. Login to Angel One
2. Fetch real-time candle data for each stock
3. Calculate technical indicators
4. Generate BUY/SELL signals
5. Calculate entry, target, stop loss, quantity
6. Send detailed Telegram alert
7. Place order on Angel One
"""
import os
import json
import time
import requests
import pyotp
from datetime import datetime
from logzero import logger
from SmartApi import SmartConnect

import config

POSITIONS_FILE = "/tmp/open_positions.json"


# ── Telegram ───────────────────────────────────────────────────────────────────
def send_alert(msg: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
    except Exception as e:
        logger.error(f"Telegram error: {e}")


# ── Positions ──────────────────────────────────────────────────────────────────
def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f)


# ── Fetch candles ──────────────────────────────────────────────────────────────
def get_token(smart_api, symbol):
    try:
        time.sleep(0.5)
        data = smart_api.searchScrip("NSE", symbol)
        for item in data["data"]:
            if item["tradingsymbol"] == f"{symbol}-EQ":
                return item["symboltoken"]
    except Exception as e:
        logger.error(f"Token error {symbol}: {e}")
    return None


def get_candles(smart_api, symbol, token):
    try:
        from datetime import timedelta
        to_date = datetime.now()
        from_date = to_date - timedelta(days=5)
        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }
        res = smart_api.getCandleData(params)
        if res.get("status") and res.get("data"):
            import pandas as pd
            df = pd.DataFrame(res["data"], columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df.tail(100)
    except Exception as e:
        logger.error(f"Candle error {symbol}: {e}")
    return None


def get_ltp(smart_api, symbol, token):
    try:
        data = smart_api.ltpData("NSE", symbol, token)
        return float(data["data"]["ltp"])
    except Exception as e:
        logger.error(f"LTP error {symbol}: {e}")
    return None


# ── Technical Analysis ─────────────────────────────────────────────────────────
def analyze(df):
    """
    Returns signal dict with:
    - signal: BUY / SELL / HOLD
    - strength: 0-100
    - reasons: list of reasons
    - support, resistance, trend
    """
    import pandas as pd

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # EMA
    ema9 = close.ewm(span=9).mean()
    ema21 = close.ewm(span=21).mean()
    ema50 = close.ewm(span=50).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    signal_line = macd.ewm(span=9).mean()
    macd_hist = macd - signal_line

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # Volume
    vol_avg = volume.rolling(20).mean()

    # Latest values
    c = close.iloc[-1]
    e9 = ema9.iloc[-1]
    e21 = ema21.iloc[-1]
    e50 = ema50.iloc[-1]
    r = rsi.iloc[-1]
    mh = macd_hist.iloc[-1]
    mh_prev = macd_hist.iloc[-2]
    bbu = bb_upper.iloc[-1]
    bbl = bb_lower.iloc[-1]
    vol_ratio = volume.iloc[-1] / vol_avg.iloc[-1] if vol_avg.iloc[-1] > 0 else 1

    # Support / Resistance (last 20 candles)
    support = round(low.tail(20).min(), 2)
    resistance = round(high.tail(20).max(), 2)

    # Trend
    if e9 > e21 > e50:
        trend = "Uptrend"
    elif e9 < e21 < e50:
        trend = "Downtrend"
    else:
        trend = "Sideways"

    # Score system
    buy_score = 0
    sell_score = 0
    reasons = []

    # EMA crossover
    if e9 > e21:
        buy_score += 20
        reasons.append("EMA9 > EMA21 (bullish)")
    else:
        sell_score += 20
        reasons.append("EMA9 < EMA21 (bearish)")

    # Price vs EMA50
    if c > e50:
        buy_score += 15
        reasons.append("Price above EMA50")
    else:
        sell_score += 15
        reasons.append("Price below EMA50")

    # RSI
    if r < 35:
        buy_score += 25
        reasons.append(f"RSI oversold ({r:.1f})")
    elif r > 65:
        sell_score += 25
        reasons.append(f"RSI overbought ({r:.1f})")
    elif 40 <= r <= 60:
        buy_score += 10
        reasons.append(f"RSI neutral ({r:.1f})")

    # MACD histogram turning
    if mh > 0 and mh > mh_prev:
        buy_score += 20
        reasons.append("MACD bullish momentum")
    elif mh < 0 and mh < mh_prev:
        sell_score += 20
        reasons.append("MACD bearish momentum")

    # Bollinger Band
    if c <= bbl:
        buy_score += 15
        reasons.append("Price at lower Bollinger Band")
    elif c >= bbu:
        sell_score += 15
        reasons.append("Price at upper Bollinger Band")

    # Volume confirmation
    if vol_ratio > 1.5:
        if buy_score > sell_score:
            buy_score += 5
        else:
            sell_score += 5
        reasons.append(f"High volume ({vol_ratio:.1f}x avg)")

    # Decision
    if buy_score >= 55 and buy_score > sell_score:
        signal = "BUY"
        strength = min(buy_score, 100)
    elif sell_score >= 55 and sell_score > buy_score:
        signal = "SELL"
        strength = min(sell_score, 100)
    else:
        signal = "HOLD"
        strength = 0

    return {
        "signal": signal,
        "strength": strength,
        "rsi": round(r, 1),
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
        "ltp": round(c, 2),
    }


# ── Order placement ────────────────────────────────────────────────────────────
def place_order(smart_api, symbol, token, side, qty):
    try:
        params = {
            "variety": "NORMAL",
            "tradingsymbol": f"{symbol}-EQ",
            "symboltoken": token,
            "transactiontype": side,
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty,
        }
        res = smart_api.placeOrder(params)
        return res["data"]["orderid"]
    except Exception as e:
        logger.error(f"Order error {symbol}: {e}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now().strftime("%H:%M")
    logger.info(f"Scan started at {now}")

    # Login
    smart_api = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    data = smart_api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)
    if not data["status"]:
        send_alert(f"Login failed: {data.get('message')}")
        return

    send_alert(f"Stock Agent Started\nTime: {now} IST\nScanning {len(config.WATCHLIST)} stocks...")

    # Check if market is open
    market_open = config.MARKET_OPEN <= now <= config.MARKET_CLOSE
    if not market_open:
        send_alert(f"Market is closed ({now} IST)\nMarket hours: {config.MARKET_OPEN} - {config.MARKET_CLOSE}")
        return

    open_positions = load_positions()
    trade_count = 0

    for symbol in config.WATCHLIST:
        try:
            token = get_token(smart_api, symbol)
            if not token:
                continue

            ltp = get_ltp(smart_api, symbol, token)
            if not ltp:
                continue

            # Check exit for open positions
            if symbol in open_positions:
                pos = open_positions[symbol]
                side = pos["side"]
                sl = pos["sl"]
                target = pos["target"]
                entry = pos["entry"]
                qty = pos["qty"]

                if (side == "BUY" and ltp >= target):
                    place_order(smart_api, symbol, token, "SELL", qty)
                    pnl = round((ltp - entry) * qty, 2)
                    send_alert(
                        f"TARGET HIT - {symbol}\n"
                        f"Entry: Rs.{entry} | Exit: Rs.{ltp}\n"
                        f"Qty: {qty} | PnL: +Rs.{pnl}"
                    )
                    del open_positions[symbol]
                elif (side == "BUY" and ltp <= sl):
                    place_order(smart_api, symbol, token, "SELL", qty)
                    pnl = round((ltp - entry) * qty, 2)
                    send_alert(
                        f"STOP LOSS HIT - {symbol}\n"
                        f"Entry: Rs.{entry} | Exit: Rs.{ltp}\n"
                        f"Qty: {qty} | PnL: Rs.{pnl}"
                    )
                    del open_positions[symbol]
                continue

            # Skip if max trades reached
            if len(open_positions) >= config.MAX_OPEN_TRADES:
                continue

            # Fetch candles and analyze
            df = get_candles(smart_api, symbol, token)
            if df is None or len(df) < 50:
                logger.warning(f"{symbol} - insufficient data, market may be closed")
                continue

            result = analyze(df)
            signal = result["signal"]

            if signal == "HOLD":
                continue

            # Calculate trade parameters
            qty = max(int(config.CAPITAL_PER_TRADE / ltp), 1)
            if signal == "BUY":
                sl = round(ltp * (1 - config.STOP_LOSS_PCT), 2)
                target = round(ltp * (1 + config.TARGET_PCT), 2)
                order_id = place_order(smart_api, symbol, token, "BUY", qty)
            else:
                sl = round(ltp * (1 + config.STOP_LOSS_PCT), 2)
                target = round(ltp * (1 - config.TARGET_PCT), 2)
                order_id = place_order(smart_api, symbol, token, "SELL", qty)

            if order_id:
                open_positions[symbol] = {
                    "side": signal, "entry": ltp, "qty": qty,
                    "sl": sl, "target": target
                }
                trade_count += 1

                msg = (
                    f"{'BUY' if signal == 'BUY' else 'SHORT'} {symbol}\n"
                    f"Price: Rs.{ltp}\n"
                    f"Target: Rs.{target} (+{config.TARGET_PCT*100:.1f}%)\n"
                    f"Stop Loss: Rs.{sl} (-{config.STOP_LOSS_PCT*100:.1f}%)\n"
                    f"Qty: {qty} | Capital: Rs.{round(ltp*qty, 0)}\n"
                    f"Trend: {result['trend']} | RSI: {result['rsi']}\n"
                    f"Support: Rs.{result['support']} | Resistance: Rs.{result['resistance']}\n"
                    f"Signal Strength: {result['strength']}%\n"
                    f"Reasons: {', '.join(result['reasons'][:3])}"
                )
                send_alert(msg)

        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            continue

    save_positions(open_positions)

    # Summary
    send_alert(
        f"Scan Complete\n"
        f"New Trades: {trade_count}\n"
        f"Open Positions: {len(open_positions)}\n"
        f"Stocks: {', '.join(open_positions.keys()) if open_positions else 'None'}"
    )


if __name__ == "__main__":
    main()
