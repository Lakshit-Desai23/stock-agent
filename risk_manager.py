from config import STOP_LOSS_PCT, TARGET_PCT, CAPITAL_PER_TRADE
from logzero import logger


def calculate_quantity(ltp: float) -> int:
    """Calculate how many shares to buy based on capital per trade."""
    qty = int(CAPITAL_PER_TRADE / ltp)
    return max(qty, 1)


def calculate_sl_target(entry_price: float, side: str):
    """
    Calculate stop loss and target prices.
    side: 'BUY' or 'SELL'
    """
    if side == "BUY":
        sl = round(entry_price * (1 - STOP_LOSS_PCT), 2)
        target = round(entry_price * (1 + TARGET_PCT), 2)
    else:
        sl = round(entry_price * (1 + STOP_LOSS_PCT), 2)
        target = round(entry_price * (1 - TARGET_PCT), 2)
    return sl, target


def should_exit(position: dict, current_price: float) -> tuple[bool, str]:
    """
    Check if position should be exited.
    Returns (should_exit: bool, reason: str)
    """
    side = position["side"]
    sl = position["sl"]
    target = position["target"]

    if side == "BUY":
        if current_price <= sl:
            return True, "STOP_LOSS"
        if current_price >= target:
            return True, "TARGET"
    else:
        if current_price >= sl:
            return True, "STOP_LOSS"
        if current_price <= target:
            return True, "TARGET"

    return False, ""


def log_trade(symbol, side, entry, exit_price, qty, reason):
    pnl = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
    logger.info(f"TRADE CLOSED | {symbol} | {side} | Entry: {entry} | Exit: {exit_price} | Qty: {qty} | PnL: {pnl:.2f} | Reason: {reason}")
    return pnl
