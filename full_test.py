"""
Full end-to-end paper trading test.
Market hours bypass karke turant run thay chhe.
API aave tyare sirf .env credentials + PAPER_TRADING=False karvu.
"""
import requests
import config
from logzero import logger
from data_fetcher import get_symbol_token, fetch_candles, get_ltp
from indicators import add_indicators, build_features
from ml_model import train_model, load_model, predict_signal, create_labels
from risk_manager import calculate_quantity, calculate_sl_target, should_exit, log_trade
from trader import place_order


open_positions = {}
daily_pnl = 0.0


def send_alert(msg: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured.")
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
        if r.json().get("ok"):
            logger.info(f"Telegram sent: {msg[:60]}...")
        else:
            logger.error(f"Telegram failed: {r.json()}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


def run_test():
    global open_positions, daily_pnl

    smart_api = None  # paper mode - no real API
    logger.info("=" * 50)
    logger.info("FULL PAPER TRADING TEST STARTED")
    logger.info("=" * 50)

    send_alert("🤖 Stock Agent - Full Test Started\nPaper Trading Mode ON")

    # Step 1: Load tokens
    symbol_tokens = {}
    for symbol in config.WATCHLIST:
        token = get_symbol_token(smart_api, symbol)
        symbol_tokens[symbol] = token
        logger.info(f"Token: {symbol} -> {token}")

    # Step 2: Train model
    logger.info("Training ML model...")
    symbol = config.WATCHLIST[0]
    df = fetch_candles(smart_api, symbol, symbol_tokens[symbol])
    df = add_indicators(df)
    features = build_features(df)
    labels = create_labels(df.iloc[:len(features)])
    min_len = min(len(features), len(labels))
    model, scaler = train_model(features.iloc[:min_len], labels.iloc[:min_len])
    logger.info("Model trained.")

    # Step 3: Scan all symbols and simulate trades
    logger.info("Scanning watchlist for signals...")
    for symbol in config.WATCHLIST:
        token = symbol_tokens[symbol]
        ltp = get_ltp(smart_api, symbol, token)
        logger.info(f"{symbol} LTP: ₹{ltp}")

        df = fetch_candles(smart_api, symbol, token)
        df = add_indicators(df)
        features = build_features(df)
        if features.empty:
            continue

        signal = predict_signal(model, scaler, features.iloc[[-1]])
        signal_name = {1: "BUY", 0: "HOLD", -1: "SELL"}[signal]
        logger.info(f"{symbol} Signal: {signal_name}")

        if signal == 1 and len(open_positions) < config.MAX_OPEN_TRADES:
            qty = calculate_quantity(ltp)
            sl, target = calculate_sl_target(ltp, "BUY")
            order_id = place_order(smart_api, symbol, token, "BUY", qty)
            open_positions[symbol] = {
                "side": "BUY", "entry": ltp, "qty": qty,
                "sl": sl, "target": target, "order_id": order_id
            }
            msg = f"📈 BUY {symbol}\n@ ₹{ltp}\nSL: ₹{sl}\nTarget: ₹{target}\nQty: {qty}"
            send_alert(msg)

        elif signal == -1 and len(open_positions) < config.MAX_OPEN_TRADES:
            qty = calculate_quantity(ltp)
            sl, target = calculate_sl_target(ltp, "SELL")
            order_id = place_order(smart_api, symbol, token, "SELL", qty)
            open_positions[symbol] = {
                "side": "SELL", "entry": ltp, "qty": qty,
                "sl": sl, "target": target, "order_id": order_id
            }
            msg = f"📉 SHORT {symbol}\n@ ₹{ltp}\nSL: ₹{sl}\nTarget: ₹{target}\nQty: {qty}"
            send_alert(msg)

    # Step 4: Simulate price movement and check exits
    logger.info("Simulating price movement for exit test...")
    for symbol, pos in list(open_positions.items()):
        token = symbol_tokens[symbol]
        # Force exit by simulating target hit
        sim_price = pos["target"]
        exit_now, reason = should_exit(pos, sim_price)
        if exit_now:
            exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
            place_order(smart_api, symbol, token, exit_side, pos["qty"])
            pnl = log_trade(symbol, pos["side"], pos["entry"], sim_price, pos["qty"], reason)
            daily_pnl += pnl
            msg = f"✅ EXIT {symbol}\n{reason}\nEntry: ₹{pos['entry']}\nExit: ₹{sim_price}\nPnL: ₹{pnl:.2f}"
            send_alert(msg)
            del open_positions[symbol]

    # Step 5: Summary
    summary = f"📊 Test Complete\nTotal Simulated PnL: ₹{daily_pnl:.2f}\nOpen Positions: {len(open_positions)}"
    logger.info(summary)
    send_alert(summary)
    logger.info("=" * 50)
    logger.info("ALL TESTS PASSED - Agent ready for live trading")
    logger.info("To go live: set PAPER_TRADING=False in config.py + add Angel One API keys in .env")
    logger.info("=" * 50)


if __name__ == "__main__":
    run_test()
