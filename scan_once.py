"""
Stock Trading Agent - scan_once.py
Runs once per GitHub Actions trigger.
Sends detailed Telegram alerts for BUY/SELL signals.
"""
import os, json, time, requests, pyotp
from datetime import datetime, timedelta
from logzero import logger
from SmartApi import SmartConnect
import config

POSITIONS_FILE = "/tmp/open_positions.json"


def send_alert(msg):
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
    except Exception as e:
        logger.error(f"Telegram: {e}")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(p):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(p, f)


def get_token(api, symbol):
    try:
        time.sleep(1)  # rate limit
        data = api.searchScrip("NSE", symbol)
        for item in data["data"]:
            if item["tradingsymbol"] == f"{symbol}-EQ":
                return item["symboltoken"]
    except Exception as e:
        logger.error(f"Token {symbol}: {e}")
    return None


def get_candles(api, token):
    try:
        time.sleep(1)  # rate limit
        to = datetime.now()
        frm = to - timedelta(days=5)
        res = api.getCandleData({
            "exchange": "NSE", "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": frm.strftime("%Y-%m-%d %H:%M"),
            "todate": to.strftime("%Y-%m-%d %H:%M"),
        })
        if res.get("status") and res.get("data"):
            import pandas as pd
            df = pd.DataFrame(res["data"], columns=["ts","open","high","low","close","volume"])
            return df.astype(float).tail(100)
    except Exception as e:
        logger.error(f"Candles: {e}")
    return None


def get_ltp(api, symbol, token):
    try:
        time.sleep(0.5)
        d = api.ltpData("NSE", symbol, token)
        return float(d["data"]["ltp"])
    except Exception as e:
        logger.error(f"LTP {symbol}: {e}")
    return None


def analyze(df):
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    ema9  = c.ewm(span=9).mean()
    ema21 = c.ewm(span=21).mean()
    ema50 = c.ewm(span=50).mean()

    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain/loss))

    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    macd_hist = (ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()

    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    bb_upper = sma20 + 2*std20
    bb_lower = sma20 - 2*std20

    ltp    = c.iloc[-1]
    e9     = ema9.iloc[-1]
    e21    = ema21.iloc[-1]
    e50    = ema50.iloc[-1]
    r      = rsi.iloc[-1]
    mh     = macd_hist.iloc[-1]
    mh_p   = macd_hist.iloc[-2]
    bbu    = bb_upper.iloc[-1]
    bbl    = bb_lower.iloc[-1]
    vol_r  = v.iloc[-1] / v.rolling(20).mean().iloc[-1]

    support    = round(l.tail(20).min(), 2)
    resistance = round(h.tail(20).max(), 2)
    trend = "Uptrend" if e9>e21>e50 else ("Downtrend" if e9<e21<e50 else "Sideways")

    buy_score = sell_score = 0
    reasons = []

    if e9 > e21:
        buy_score += 20; reasons.append("EMA9>EMA21 bullish")
    else:
        sell_score += 20; reasons.append("EMA9<EMA21 bearish")

    if ltp > e50:
        buy_score += 15; reasons.append("Above EMA50")
    else:
        sell_score += 15; reasons.append("Below EMA50")

    if r < 35:
        buy_score += 25; reasons.append(f"RSI oversold {r:.0f}")
    elif r > 65:
        sell_score += 25; reasons.append(f"RSI overbought {r:.0f}")
    else:
        buy_score += 5; reasons.append(f"RSI neutral {r:.0f}")

    if mh > 0 and mh > mh_p:
        buy_score += 20; reasons.append("MACD bullish")
    elif mh < 0 and mh < mh_p:
        sell_score += 20; reasons.append("MACD bearish")

    if ltp <= bbl:
        buy_score += 15; reasons.append("At lower BB")
    elif ltp >= bbu:
        sell_score += 15; reasons.append("At upper BB")

    if vol_r > 1.5:
        if buy_score > sell_score: buy_score += 5
        else: sell_score += 5
        reasons.append(f"High vol {vol_r:.1f}x")

    if buy_score >= 55 and buy_score > sell_score:
        return "BUY", min(buy_score,100), r, trend, support, resistance, reasons
    elif sell_score >= 55 and sell_score > buy_score:
        return "SELL", min(sell_score,100), r, trend, support, resistance, reasons
    return "HOLD", 0, r, trend, support, resistance, reasons


def place_order(api, symbol, token, side, qty):
    try:
        res = api.placeOrder({
            "variety": "NORMAL",
            "tradingsymbol": f"{symbol}-EQ",
            "symboltoken": token,
            "transactiontype": side,
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty,
        })
        return res["data"]["orderid"]
    except Exception as e:
        logger.error(f"Order {symbol}: {e}")
    return None


def main():
    # IST time (UTC+5:30)
    from datetime import timezone, timedelta as td
    ist = timezone(td(hours=5, minutes=30))
    now = datetime.now(ist).strftime("%H:%M")

    # Login
    api = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    data = api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)
    if not data["status"]:
        send_alert(f"Login failed: {data.get('message')}")
        return

    # Market hours check
    if not (config.MARKET_OPEN <= now <= config.MARKET_CLOSE):
        send_alert(f"Market Closed ({now} IST)\nAgent will auto-run on market days 09:15-15:20")
        return

    send_alert(f"Market Open - Agent Started\nTime: {now} IST | Scanning {len(config.WATCHLIST)} stocks...")

    positions = load_positions()
    new_trades = 0
    skipped = 0

    for symbol in config.WATCHLIST:
        try:
            token = get_token(api, symbol)
            if not token:
                skipped += 1
                continue

            ltp = get_ltp(api, symbol, token)
            if not ltp:
                skipped += 1
                continue

            # Exit check
            if symbol in positions:
                pos = positions[symbol]
                if pos["side"] == "BUY":
                    if ltp >= pos["target"]:
                        place_order(api, symbol, token, "SELL", pos["qty"])
                        pnl = round((ltp - pos["entry"]) * pos["qty"], 2)
                        send_alert(f"TARGET HIT {symbol}\nEntry: Rs.{pos['entry']} Exit: Rs.{ltp}\nQty: {pos['qty']} | PnL: +Rs.{pnl}")
                        del positions[symbol]
                    elif ltp <= pos["sl"]:
                        place_order(api, symbol, token, "SELL", pos["qty"])
                        pnl = round((ltp - pos["entry"]) * pos["qty"], 2)
                        send_alert(f"STOP LOSS {symbol}\nEntry: Rs.{pos['entry']} Exit: Rs.{ltp}\nQty: {pos['qty']} | PnL: Rs.{pnl}")
                        del positions[symbol]
                continue

            if len(positions) >= config.MAX_OPEN_TRADES:
                continue

            df = get_candles(api, token)
            if df is None or len(df) < 50:
                skipped += 1
                continue

            signal, strength, rsi_val, trend, support, resistance, reasons = analyze(df)
            logger.info(f"{symbol} -> {signal} ({strength}%) @ Rs.{ltp}")

            if signal == "HOLD":
                continue

            qty = max(int(config.CAPITAL_PER_TRADE / ltp), 1)
            if signal == "BUY":
                sl     = round(ltp * (1 - config.STOP_LOSS_PCT), 2)
                target = round(ltp * (1 + config.TARGET_PCT), 2)
                oid    = place_order(api, symbol, token, "BUY", qty)
            else:
                sl     = round(ltp * (1 + config.STOP_LOSS_PCT), 2)
                target = round(ltp * (1 - config.TARGET_PCT), 2)
                oid    = place_order(api, symbol, token, "SELL", qty)

            if oid:
                positions[symbol] = {"side": signal, "entry": ltp, "qty": qty, "sl": sl, "target": target}
                new_trades += 1
                send_alert(
                    f"{'BUY' if signal=='BUY' else 'SHORT'} {symbol}\n"
                    f"Price:  Rs.{ltp}\n"
                    f"Target: Rs.{target}  (+{config.TARGET_PCT*100:.1f}%)\n"
                    f"SL:     Rs.{sl}  (-{config.STOP_LOSS_PCT*100:.1f}%)\n"
                    f"Qty: {qty}  Capital: Rs.{round(ltp*qty)}\n"
                    f"Trend: {trend}  RSI: {rsi_val:.0f}\n"
                    f"Support: Rs.{support}  Resistance: Rs.{resistance}\n"
                    f"Strength: {strength}%\n"
                    f"Why: {', '.join(reasons[:3])}"
                )

        except Exception as e:
            logger.error(f"{symbol}: {e}")

    save_positions(positions)
    send_alert(
        f"Scan Done\n"
        f"New trades: {new_trades}\n"
        f"Open positions: {len(positions)} - {', '.join(positions.keys()) or 'None'}\n"
        f"Skipped: {skipped}"
    )


if __name__ == "__main__":
    main()
