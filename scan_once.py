"""
Stock Trading Agent - scan_once.py
Dynamic algorithm - auto-adapts to market conditions.
"""
import os, json, time, requests, pyotp
from datetime import datetime, timedelta, timezone
import config

try:
    from logzero import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

from SmartApi import SmartConnect
import pandas as pd
import numpy as np

POSITIONS_FILE = "/tmp/open_positions.json"
IST = timezone(timedelta(hours=5, minutes=30))


# ─── Telegram ────────────────────────────────────────────────────────────────

def send_alert(msg):
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram: {e}")


# ─── Positions ───────────────────────────────────────────────────────────────

def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(p):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(p, f)


# ─── Angel One API ───────────────────────────────────────────────────────────

def get_token(api, symbol, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(2)
            data = api.searchScrip("NSE", symbol)
            if data and data.get("data"):
                for item in data["data"]:
                    if item["tradingsymbol"] == f"{symbol}-EQ":
                        return item["symboltoken"]
        except Exception as e:
            logger.error(f"Token {symbol} attempt {attempt+1}: {e}")
            time.sleep(3)
    return None


def get_candles(api, token, symbol="", retries=3):
    to = datetime.now(IST)
    frm = to - timedelta(days=15)
    params = {
        "exchange": "NSE", "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": frm.strftime("%Y-%m-%d %H:%M"),
        "todate":   to.strftime("%Y-%m-%d %H:%M"),
    }
    for attempt in range(retries):
        try:
            time.sleep(3 + attempt * 2)
            res = api.getCandleData(params)
            raw = res.get("data")
            if not raw:
                logger.warning(f"Candles {symbol} attempt {attempt+1}: empty - {res.get('message')}")
                continue
            rows = []
            for row in raw:
                try:
                    rows.append({
                        "ts": row[0], "open": float(row[1]), "high": float(row[2]),
                        "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
                    })
                except (IndexError, ValueError, TypeError):
                    continue
            if rows:
                df = pd.DataFrame(rows)
                logger.info(f"{symbol} candles: {len(df)}")
                return df.tail(120)
        except Exception as e:
            logger.error(f"Candles {symbol} attempt {attempt+1}: {e}")
            time.sleep(3)
    return None


def get_ltp(api, symbol, token):
    try:
        time.sleep(1)
        d = api.ltpData("NSE", symbol, token)
        if d and d.get("data"):
            return float(d["data"]["ltp"])
    except Exception as e:
        logger.error(f"LTP {symbol}: {e}")
    return None


def place_order(api, symbol, token, side, qty):
    if config.PAPER_TRADING:
        logger.info(f"[PAPER] {side} {qty} x {symbol}")
        return f"PAPER-{symbol}-{side}"
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


# ─── Indicators ──────────────────────────────────────────────────────────────

def compute_indicators(df):
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    # EMAs
    ema9  = c.ewm(span=9,  adjust=False).mean()
    ema21 = c.ewm(span=21, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200= c.ewm(span=200,adjust=False).mean()

    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    hist  = macd - signal_line

    # Bollinger Bands
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_pct   = (c - bb_lower) / (bb_upper - bb_lower + 1e-9)  # 0=lower, 1=upper

    # ATR (volatility)
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = atr / c * 100  # ATR as % of price

    # Volume
    vol_sma20 = v.rolling(20).mean()
    vol_ratio = v / vol_sma20.replace(0, 1)

    # Stochastic
    low14  = l.rolling(14).min()
    high14 = h.rolling(14).max()
    stoch_k = 100 * (c - low14) / (high14 - low14 + 1e-9)
    stoch_d = stoch_k.rolling(3).mean()

    # Support / Resistance (pivot points from last 20 candles)
    support    = round(l.tail(20).min(), 2)
    resistance = round(h.tail(20).max(), 2)

    return {
        "close": c.iloc[-1], "prev_close": c.iloc[-2],
        "ema9": ema9.iloc[-1], "ema21": ema21.iloc[-1],
        "ema50": ema50.iloc[-1], "ema200": ema200.iloc[-1],
        "ema9_prev": ema9.iloc[-2], "ema21_prev": ema21.iloc[-2],
        "rsi": rsi.iloc[-1], "rsi_prev": rsi.iloc[-2],
        "macd": macd.iloc[-1], "macd_prev": macd.iloc[-2],
        "hist": hist.iloc[-1], "hist_prev": hist.iloc[-2],
        "signal_line": signal_line.iloc[-1],
        "bb_upper": bb_upper.iloc[-1], "bb_lower": bb_lower.iloc[-1],
        "bb_pct": bb_pct.iloc[-1],
        "atr": atr.iloc[-1], "atr_pct": atr_pct.iloc[-1],
        "vol_ratio": vol_ratio.iloc[-1],
        "stoch_k": stoch_k.iloc[-1], "stoch_d": stoch_d.iloc[-1],
        "support": support, "resistance": resistance,
        "high": df["high"].iloc[-1], "low": df["low"].iloc[-1],
    }


# ─── Market Regime Detection ─────────────────────────────────────────────────

def detect_regime(df):
    """
    Detect if market is: TRENDING_UP, TRENDING_DOWN, SIDEWAYS, VOLATILE
    This changes how we weight indicators.
    """
    c = df["close"]
    h = df["high"]
    l = df["low"]

    ema20 = c.ewm(span=20).mean()
    ema50 = c.ewm(span=50).mean()

    # ADX - trend strength
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    up_move   = h.diff().clip(lower=0)
    down_move = (-l.diff()).clip(lower=0)
    plus_di  = 100 * (up_move.rolling(14).mean()   / atr14.replace(0, 1e-9))
    minus_di = 100 * (down_move.rolling(14).mean() / atr14.replace(0, 1e-9))
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.rolling(14).mean().iloc[-1]

    # Volatility check
    returns = c.pct_change().tail(20)
    volatility = returns.std() * 100  # daily std %

    e20 = ema20.iloc[-1]
    e50 = ema50.iloc[-1]

    if volatility > 2.0:
        return "VOLATILE", adx
    elif adx > 25:
        if e20 > e50:
            return "TRENDING_UP", adx
        else:
            return "TRENDING_DOWN", adx
    else:
        return "SIDEWAYS", adx


# ─── Dynamic Signal Engine ───────────────────────────────────────────────────

def analyze(df):
    if len(df) < 50:
        return "HOLD", 0, 0, 0, 50, "Unknown", 0, 0, []

    ind = compute_indicators(df)
    regime, adx = detect_regime(df)

    buy_signals  = []
    sell_signals = []
    buy_score  = 0
    sell_score = 0

    ltp = ind["close"]

    # ── 1. Trend Direction (weight depends on regime) ──
    trend_weight = 30 if regime in ("TRENDING_UP", "TRENDING_DOWN") else 15

    if ind["ema9"] > ind["ema21"] > ind["ema50"]:
        buy_score += trend_weight
        buy_signals.append("Strong uptrend (EMA stack)")
    elif ind["ema9"] > ind["ema21"]:
        buy_score += trend_weight // 2
        buy_signals.append("EMA9>EMA21 bullish")
    elif ind["ema9"] < ind["ema21"] < ind["ema50"]:
        sell_score += trend_weight
        sell_signals.append("Strong downtrend (EMA stack)")
    elif ind["ema9"] < ind["ema21"]:
        sell_score += trend_weight // 2
        sell_signals.append("EMA9<EMA21 bearish")

    # ── 2. EMA Crossover (fresh cross = strong signal) ──
    ema_cross_buy  = ind["ema9_prev"] <= ind["ema21_prev"] and ind["ema9"] > ind["ema21"]
    ema_cross_sell = ind["ema9_prev"] >= ind["ema21_prev"] and ind["ema9"] < ind["ema21"]
    if ema_cross_buy:
        buy_score += 20
        buy_signals.append("Fresh EMA bullish crossover")
    if ema_cross_sell:
        sell_score += 20
        sell_signals.append("Fresh EMA bearish crossover")

    # ── 3. RSI (dynamic zones based on regime) ──
    rsi = ind["rsi"]
    if regime == "TRENDING_UP":
        # In uptrend, RSI 40-70 is normal, <40 is oversold opportunity
        if 40 <= rsi <= 65:
            buy_score += 15
            buy_signals.append(f"RSI healthy {rsi:.0f} in uptrend")
        elif rsi < 40:
            buy_score += 25
            buy_signals.append(f"RSI oversold {rsi:.0f} - pullback buy")
        elif rsi > 75:
            sell_score += 15
            sell_signals.append(f"RSI overbought {rsi:.0f}")
    elif regime == "TRENDING_DOWN":
        if rsi > 60:
            sell_score += 25
            sell_signals.append(f"RSI overbought {rsi:.0f} in downtrend")
        elif 35 <= rsi <= 60:
            sell_score += 15
            sell_signals.append(f"RSI bearish zone {rsi:.0f}")
    else:  # SIDEWAYS / VOLATILE
        if rsi < 30:
            buy_score += 25
            buy_signals.append(f"RSI oversold {rsi:.0f}")
        elif rsi > 70:
            sell_score += 25
            sell_signals.append(f"RSI overbought {rsi:.0f}")
        elif 45 <= rsi <= 55:
            pass  # neutral, no score

    # RSI momentum (rising/falling)
    if ind["rsi"] > ind["rsi_prev"] and rsi < 60:
        buy_score += 5
    elif ind["rsi"] < ind["rsi_prev"] and rsi > 40:
        sell_score += 5

    # ── 4. MACD ──
    macd_cross_buy  = ind["hist_prev"] < 0 and ind["hist"] > 0
    macd_cross_sell = ind["hist_prev"] > 0 and ind["hist"] < 0
    macd_bull = ind["hist"] > 0 and ind["hist"] > ind["hist_prev"]
    macd_bear = ind["hist"] < 0 and ind["hist"] < ind["hist_prev"]

    if macd_cross_buy:
        buy_score += 25
        buy_signals.append("MACD bullish crossover")
    elif macd_bull:
        buy_score += 15
        buy_signals.append("MACD histogram rising")

    if macd_cross_sell:
        sell_score += 25
        sell_signals.append("MACD bearish crossover")
    elif macd_bear:
        sell_score += 15
        sell_signals.append("MACD histogram falling")

    # ── 5. Bollinger Bands ──
    bb_pct = ind["bb_pct"]
    if bb_pct < 0.2:  # near lower band
        buy_score += 15
        buy_signals.append(f"Near lower BB ({bb_pct:.0%})")
    elif bb_pct > 0.8:  # near upper band
        sell_score += 15
        sell_signals.append(f"Near upper BB ({bb_pct:.0%})")

    # BB squeeze breakout (low volatility -> expansion)
    bb_width = (ind["bb_upper"] - ind["bb_lower"]) / ind["close"]
    if bb_width < 0.02:  # tight squeeze
        # Direction determined by EMA
        if ind["ema9"] > ind["ema21"]:
            buy_score += 10
            buy_signals.append("BB squeeze - bullish breakout likely")
        else:
            sell_score += 10
            sell_signals.append("BB squeeze - bearish breakout likely")

    # ── 6. Stochastic ──
    sk = ind["stoch_k"]
    sd = ind["stoch_d"]
    if sk < 20 and sd < 20 and sk > sd:
        buy_score += 15
        buy_signals.append(f"Stochastic oversold crossover {sk:.0f}")
    elif sk > 80 and sd > 80 and sk < sd:
        sell_score += 15
        sell_signals.append(f"Stochastic overbought crossover {sk:.0f}")

    # ── 7. Volume Confirmation (mandatory filter) ──
    vol_ratio = ind["vol_ratio"]
    vol_confirmed = vol_ratio > 1.2

    if vol_ratio > 1.5:
        if buy_score > sell_score:
            buy_score += 10
            buy_signals.append(f"Volume surge {vol_ratio:.1f}x confirms buy")
        else:
            sell_score += 10
            sell_signals.append(f"Volume surge {vol_ratio:.1f}x confirms sell")
    elif vol_ratio < 0.7:
        # Low volume = weak signal, reduce scores
        buy_score  = int(buy_score  * 0.8)
        sell_score = int(sell_score * 0.8)

    # ── 8. Price vs Key Levels ──
    if ltp > ind["ema200"]:
        buy_score += 10
        buy_signals.append("Above EMA200 (long-term bullish)")
    else:
        sell_score += 10
        sell_signals.append("Below EMA200 (long-term bearish)")

    # Near support = buy opportunity
    support_dist = (ltp - ind["support"]) / ltp
    resist_dist  = (ind["resistance"] - ltp) / ltp
    if support_dist < 0.01:  # within 1% of support
        buy_score += 15
        buy_signals.append(f"Near support Rs.{ind['support']}")
    if resist_dist < 0.01:  # within 1% of resistance
        sell_score += 15
        sell_signals.append(f"Near resistance Rs.{ind['resistance']}")

    # ── 9. Regime bonus ──
    if regime == "TRENDING_UP" and buy_score > sell_score:
        buy_score += 10
    elif regime == "TRENDING_DOWN" and sell_score > buy_score:
        sell_score += 10
    elif regime == "VOLATILE":
        # Reduce scores in volatile market - higher bar needed
        buy_score  = int(buy_score  * 0.85)
        sell_score = int(sell_score * 0.85)

    # ── Determine trend label ──
    if ind["ema9"] > ind["ema21"] > ind["ema50"]:
        trend = "Uptrend"
    elif ind["ema9"] < ind["ema21"] < ind["ema50"]:
        trend = "Downtrend"
    else:
        trend = "Sideways"

    # ── Final decision (threshold = 45) ──
    THRESHOLD = 45
    reasons = (buy_signals if buy_score > sell_score else sell_signals)[:4]

    if buy_score >= THRESHOLD and buy_score > sell_score:
        return "BUY",  min(buy_score, 100), buy_score, sell_score, rsi, trend, ind["support"], ind["resistance"], reasons
    elif sell_score >= THRESHOLD and sell_score > buy_score:
        return "SELL", min(sell_score, 100), buy_score, sell_score, rsi, trend, ind["support"], ind["resistance"], reasons

    return "HOLD", 0, buy_score, sell_score, rsi, trend, ind["support"], ind["resistance"], reasons


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    now_ist = datetime.now(IST)
    now = now_ist.strftime("%H:%M")

    # Login
    try:
        api = SmartConnect(api_key=config.ANGEL_API_KEY)
        totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
        data = api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)
        if not data["status"]:
            send_alert(f"Login failed: {data.get('message')}")
            return
        logger.info("Login successful")
    except Exception as e:
        send_alert(f"Login error: {e}")
        return

    # Market hours check
    if not (config.MARKET_OPEN <= now <= config.MARKET_CLOSE):
        send_alert(f"Market Closed ({now} IST)\nAgent will auto-run on market days {config.MARKET_OPEN}-{config.MARKET_CLOSE}")
        return

    mode = "PAPER" if config.PAPER_TRADING else "LIVE"
    send_alert(f"Market Open - Agent Started [{mode}]\nTime: {now} IST | Scanning {len(config.WATCHLIST)} stocks...")

    positions  = load_positions()
    new_trades = 0
    skip_reasons  = []
    scan_summary  = []

    for symbol in config.WATCHLIST:
        try:
            token = get_token(api, symbol)
            if not token:
                skip_reasons.append(f"{symbol}:no_token")
                continue

            ltp = get_ltp(api, symbol, token)
            if not ltp:
                skip_reasons.append(f"{symbol}:no_ltp")
                continue

            # ── Exit check for open positions ──
            if symbol in positions:
                pos = positions[symbol]
                if pos["side"] == "BUY":
                    if ltp >= pos["target"]:
                        place_order(api, symbol, token, "SELL", pos["qty"])
                        pnl = round((ltp - pos["entry"]) * pos["qty"], 2)
                        send_alert(f"TARGET HIT {symbol}\nEntry: Rs.{pos['entry']} | Exit: Rs.{ltp}\nQty: {pos['qty']} | PnL: +Rs.{pnl}")
                        del positions[symbol]
                    elif ltp <= pos["sl"]:
                        place_order(api, symbol, token, "SELL", pos["qty"])
                        pnl = round((ltp - pos["entry"]) * pos["qty"], 2)
                        send_alert(f"STOP LOSS HIT {symbol}\nEntry: Rs.{pos['entry']} | Exit: Rs.{ltp}\nQty: {pos['qty']} | PnL: Rs.{pnl}")
                        del positions[symbol]
                elif pos["side"] == "SELL":
                    if ltp <= pos["target"]:
                        place_order(api, symbol, token, "BUY", pos["qty"])
                        pnl = round((pos["entry"] - ltp) * pos["qty"], 2)
                        send_alert(f"TARGET HIT {symbol} (SHORT)\nEntry: Rs.{pos['entry']} | Exit: Rs.{ltp}\nQty: {pos['qty']} | PnL: +Rs.{pnl}")
                        del positions[symbol]
                    elif ltp >= pos["sl"]:
                        place_order(api, symbol, token, "BUY", pos["qty"])
                        pnl = round((pos["entry"] - ltp) * pos["qty"], 2)
                        send_alert(f"STOP LOSS HIT {symbol} (SHORT)\nEntry: Rs.{pos['entry']} | Exit: Rs.{ltp}\nQty: {pos['qty']} | PnL: Rs.{pnl}")
                        del positions[symbol]
                continue

            if len(positions) >= config.MAX_OPEN_TRADES:
                continue

            df = get_candles(api, token, symbol)
            if df is None or len(df) < 50:
                count = len(df) if df is not None else "None"
                skip_reasons.append(f"{symbol}:candles({count})")
                continue

            signal, strength, buy_sc, sell_sc, rsi_val, trend, support, resistance, reasons = analyze(df)
            scan_summary.append(f"{symbol}:{signal}(B{buy_sc}/S{sell_sc})")
            logger.info(f"{symbol} -> {signal} B={buy_sc} S={sell_sc} RSI={rsi_val:.0f} @ Rs.{ltp}")

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
                positions[symbol] = {
                    "side": signal, "entry": ltp,
                    "qty": qty, "sl": sl, "target": target
                }
                new_trades += 1
                send_alert(
                    f"{'BUY' if signal == 'BUY' else 'SHORT'} {symbol} [{mode}]\n"
                    f"Price:  Rs.{ltp}\n"
                    f"Target: Rs.{target}  (+{config.TARGET_PCT*100:.1f}%)\n"
                    f"SL:     Rs.{sl}  (-{config.STOP_LOSS_PCT*100:.1f}%)\n"
                    f"Qty: {qty}  Capital: Rs.{round(ltp*qty)}\n"
                    f"Trend: {trend}  RSI: {rsi_val:.0f}\n"
                    f"Support: Rs.{support}  Resistance: Rs.{resistance}\n"
                    f"Strength: {strength}%\n"
                    f"Why: {', '.join(reasons)}"
                )

        except Exception as e:
            logger.error(f"{symbol}: {e}")
            skip_reasons.append(f"{symbol}:error")

    save_positions(positions)

    scores_text = "  ".join(scan_summary) if scan_summary else "None"
    skip_text   = ", ".join(skip_reasons) if skip_reasons else "None"
    send_alert(
        f"Scan Done [{mode}]\n"
        f"New trades: {new_trades}\n"
        f"Open: {len(positions)} - {', '.join(positions.keys()) or 'None'}\n"
        f"Scores: {scores_text}\n"
        f"Skipped: {skip_text}"
    )


if __name__ == "__main__":
    main()
