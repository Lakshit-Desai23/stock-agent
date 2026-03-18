"""
Single scan run - GitHub Actions mate.
Har 5 min e GitHub Actions aa file run karse.
Positions JSON file ma save thase (GitHub artifact via cache).
"""
import os
import json
import time
import requests
import pyotp
from logzero import logger
from SmartApi import SmartConnect

import config
from data_fetcher import get_symbol_token, fetch_candles, get_ltp
from indicators import add_indicators, build_features
from ml_model import train_model, load_model, predict_signal, create_labels
from risk_manager import calculate_quantity, calculate_sl_target, should_exit, log_trade
from trader import place_order

POSITIONS_FILE = "/tmp/open_positions.json"
PNL_FILE = "/tmp/daily_pnl.json"


def send_alert(msg):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
        if not r.json().get("ok"):
            logger.error(f"Telegram failed: {r.json()}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f)


def load_pnl():
    if os.path.exists(PNL_FILE):
        with open(PNL_FILE) as f:
            return json.load(f).get("pnl", 0.0)
    return 0.0


def save_pnl(pnl):
    with open(PNL_FILE, "w") as f:
        json.dump({"pnl": pnl}, f)


def main():
    # Login
    smart_api = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    data = smart_api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)
    if not data["status"]:
        logger.error(f"Login failed: {data}")
        send_alert(f"Login failed: {data.get('message')}")
        return
    logger.info("Login successful.")

    # Load state
    open_positions = load_positions()
    daily_pnl = load_pnl()

    # Get tokens
    symbol_tokens = {}
    for symbol in config.WATCHLIST:
        token = get_symbol_token(smart_api, symbol)
        if token:
            symbol_tokens[symbol] = token
        time.sleep(0.5)  # avoid rate limit

    # Train or load model - try multiple symbols if first fails
    model, scaler = load_model()
    if not model:
        trained = False
        for sym in config.WATCHLIST:
            token = symbol_tokens.get(sym)
            if not token:
                continue
            df = fetch_candles(smart_api, sym, token)
            if df is None or len(df) < 50:
                logger.warning(f"Cannot get candle data for {sym}, trying next...")
                time.sleep(1)
                continue
            df = add_indicators(df)
            features = build_features(df)
            labels = create_labels(df.iloc[:len(features)])
            min_len = min(len(features), len(labels))
            model, scaler = train_model(features.iloc[:min_len], labels.iloc[:min_len])
            trained = True
            break
        if not trained:
            logger.error("Cannot train model - no candle data available.")
            send_alert("Agent error: Market may be closed or API rate limit hit.")
            return

    # Scan
    for symbol in config.WATCHLIST:
        token = symbol_tokens.get(symbol)
        if not token:
            continue

        ltp = get_ltp(smart_api, symbol, token)
        if not ltp:
            continue

        # Check open position exit
        if symbol in open_positions:
            pos = open_positions[symbol]
            exit_now, reason = should_exit(pos, ltp)
            if exit_now:
                exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                place_order(smart_api, symbol, token, exit_side, pos["qty"])
                pnl = log_trade(symbol, pos["side"], pos["entry"], ltp, pos["qty"], reason)
                daily_pnl += pnl
                send_alert(f"EXIT {symbol} | {reason} | PnL: Rs.{pnl:.2f} | Daily: Rs.{daily_pnl:.2f}")
                del open_positions[symbol]
            continue

        if len(open_positions) >= config.MAX_OPEN_TRADES:
            continue

        # New entry signal
        df = fetch_candles(smart_api, symbol, token)
        if df is None or len(df) < 50:
            logger.warning(f"{symbol} - not enough candle data, skipping.")
            continue
        df = add_indicators(df)
        features = build_features(df)
        if features.empty:
            continue

        signal = predict_signal(model, scaler, features.iloc[[-1]])
        signal_name = {1: "BUY", 0: "HOLD", -1: "SELL"}[signal]
        logger.info(f"{symbol} -> {signal_name} @ Rs.{ltp}")

        if signal == 1:
            qty = calculate_quantity(ltp)
            sl, target = calculate_sl_target(ltp, "BUY")
            order_id = place_order(smart_api, symbol, token, "BUY", qty)
            if order_id:
                open_positions[symbol] = {"side": "BUY", "entry": ltp, "qty": qty, "sl": sl, "target": target}
                send_alert(f"BUY {symbol} @ Rs.{ltp}\nSL: Rs.{sl} | Target: Rs.{target}\nQty: {qty}")

        elif signal == -1:
            qty = calculate_quantity(ltp)
            sl, target = calculate_sl_target(ltp, "SELL")
            order_id = place_order(smart_api, symbol, token, "SELL", qty)
            if order_id:
                open_positions[symbol] = {"side": "SELL", "entry": ltp, "qty": qty, "sl": sl, "target": target}
                send_alert(f"SHORT {symbol} @ Rs.{ltp}\nSL: Rs.{sl} | Target: Rs.{target}\nQty: {qty}")

    save_positions(open_positions)
    save_pnl(daily_pnl)
    logger.info(f"Scan complete. Open: {list(open_positions.keys())} | Daily PnL: Rs.{daily_pnl:.2f}")


if __name__ == "__main__":
    main()
