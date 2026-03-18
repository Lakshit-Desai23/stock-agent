import time
import pyotp
import requests
import schedule
from datetime import datetime
from logzero import logger
from SmartApi import SmartConnect

import config
from data_fetcher import get_symbol_token, fetch_candles, get_ltp
from indicators import add_indicators, build_features
from ml_model import train_model, load_model, predict_signal, create_labels
from risk_manager import calculate_quantity, calculate_sl_target, should_exit, log_trade
from trader import place_order, place_sl_order, cancel_order


# ── State ──────────────────────────────────────────────────────────────────────
smart_api = None
symbol_tokens = {}          # symbol -> token
open_positions = {}         # symbol -> position dict
daily_pnl = 0.0


# ── Telegram alert ─────────────────────────────────────────────────────────────
def send_alert(msg: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured - skipping alert.")
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
        res = r.json()
        if res.get("ok"):
            logger.info(f"Telegram alert sent.")
        else:
            logger.error(f"Telegram failed: {res}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


# ── Login ──────────────────────────────────────────────────────────────────────
def login():
    global smart_api
    if config.PAPER_TRADING:
        smart_api = None
        logger.info("[PAPER] Paper trading mode - skipping Angel One login.")
        send_alert("Stock Agent started in PAPER TRADING mode.")
        return
    smart_api = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    data = smart_api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)
    if data["status"]:
        logger.info("Angel One login successful.")
        send_alert("Stock Agent started. Login successful.")
    else:
        raise Exception(f"Login failed: {data}")


# ── Train / load model ─────────────────────────────────────────────────────────
def initialize_model():
    """Try loading saved model, else train fresh on first symbol in watchlist."""
    model, scaler = load_model()
    if model:
        logger.info("Loaded existing ML model.")
        return model, scaler

    logger.info("No saved model found. Training on historical data...")
    symbol = config.WATCHLIST[0]
    token = symbol_tokens.get(symbol)
    if not token:
        raise Exception("Cannot train model - token not found.")

    df = fetch_candles(smart_api, symbol, token)
    df = add_indicators(df)
    features = build_features(df)
    labels = create_labels(df.iloc[:len(features)])
    min_len = min(len(features), len(labels))
    model, scaler = train_model(features.iloc[:min_len], labels.iloc[:min_len])
    return model, scaler


# ── Core scan loop ─────────────────────────────────────────────────────────────
def scan_and_trade(model, scaler):
    global open_positions, daily_pnl

    now = datetime.now().strftime("%H:%M")
    if now >= config.MARKET_CLOSE:
        close_all_positions()
        return

    for symbol in config.WATCHLIST:
        token = symbol_tokens.get(symbol)
        if not token:
            continue

        ltp = get_ltp(smart_api, symbol, token)
        if not ltp:
            continue

        # ── Manage open position ───────────────────────────────────────────────
        if symbol in open_positions:
            pos = open_positions[symbol]
            exit_now, reason = should_exit(pos, ltp)
            if exit_now:
                exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                place_order(smart_api, symbol, token, exit_side, pos["qty"])
                pnl = log_trade(symbol, pos["side"], pos["entry"], ltp, pos["qty"], reason)
                daily_pnl += pnl
                send_alert(f"EXIT {symbol} | {reason} | PnL: ₹{pnl:.2f} | Daily PnL: ₹{daily_pnl:.2f}")
                del open_positions[symbol]
            continue  # don't look for new entry if already in trade

        # ── Look for new entry ─────────────────────────────────────────────────
        if len(open_positions) >= config.MAX_OPEN_TRADES:
            continue

        df = fetch_candles(smart_api, symbol, token)
        if df is None or len(df) < 50:
            continue

        df = add_indicators(df)
        features = build_features(df)
        if features.empty:
            continue

        last_features = features.iloc[[-1]]
        signal = predict_signal(model, scaler, last_features)
        signal_name = {1: "BUY", 0: "HOLD", -1: "SELL"}[signal]
        logger.info(f"{symbol} -> Signal: {signal_name} | LTP: ₹{ltp}")

        if signal == 1:   # BUY
            qty = calculate_quantity(ltp)
            sl, target = calculate_sl_target(ltp, "BUY")
            order_id = place_order(smart_api, symbol, token, "BUY", qty)
            if order_id:
                open_positions[symbol] = {
                    "side": "BUY", "entry": ltp, "qty": qty,
                    "sl": sl, "target": target, "order_id": order_id
                }
                send_alert(f"BUY {symbol} @ ₹{ltp} | SL: ₹{sl} | Target: ₹{target} | Qty: {qty}")

        elif signal == -1:  # SHORT (only if allowed in your account)
            qty = calculate_quantity(ltp)
            sl, target = calculate_sl_target(ltp, "SELL")
            order_id = place_order(smart_api, symbol, token, "SELL", qty)
            if order_id:
                open_positions[symbol] = {
                    "side": "SELL", "entry": ltp, "qty": qty,
                    "sl": sl, "target": target, "order_id": order_id
                }
                send_alert(f"SHORT {symbol} @ ₹{ltp} | SL: ₹{sl} | Target: ₹{target} | Qty: {qty}")


# ── Force close all at market end ──────────────────────────────────────────────
def close_all_positions():
    global open_positions, daily_pnl
    for symbol, pos in list(open_positions.items()):
        token = symbol_tokens.get(symbol)
        ltp = get_ltp(smart_api, symbol, token)
        exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
        place_order(smart_api, symbol, token, exit_side, pos["qty"])
        pnl = log_trade(symbol, pos["side"], pos["entry"], ltp or pos["entry"], pos["qty"], "MARKET_CLOSE")
        daily_pnl += pnl
        del open_positions[symbol]
    if daily_pnl != 0:
        send_alert(f"Market closed. Total Daily PnL: ₹{daily_pnl:.2f}")
        daily_pnl = 0.0


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    global symbol_tokens

    login()

    # Fetch tokens for all watchlist symbols
    for symbol in config.WATCHLIST:
        token = get_symbol_token(smart_api, symbol)
        if token:
            symbol_tokens[symbol] = token
            logger.info(f"Token loaded: {symbol} -> {token}")
        else:
            logger.warning(f"Could not get token for {symbol}")

    model, scaler = initialize_model()

    # Schedule scan every 5 minutes during market hours
    schedule.every(5).minutes.do(scan_and_trade, model=model, scaler=scaler)

    logger.info("Agent running. Scanning every 5 minutes...")
    # Run once immediately on start
    scan_and_trade(model=model, scaler=scaler)

    while True:
        now = datetime.now().strftime("%H:%M")
        if config.MARKET_OPEN <= now <= config.MARKET_CLOSE:
            schedule.run_pending()
        elif config.PAPER_TRADING:
            # Paper mode: scan every 5 min regardless of market hours for testing
            scan_and_trade(model=model, scaler=scaler)
            time.sleep(300)
            continue
        else:
            logger.info(f"Market closed ({now}). Waiting...")
        time.sleep(60)


if __name__ == "__main__":
    main()
