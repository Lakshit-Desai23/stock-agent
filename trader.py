from logzero import logger
import config


def place_order(smart_api, symbol: str, token: str, side: str, qty: int) -> str:
    """
    Place a market order on Angel One.
    side: 'BUY' or 'SELL'
    Returns order_id or None
    """
    if config.PAPER_TRADING:
        fake_id = f"PAPER-{symbol}-{side}-{qty}"
        logger.info(f"[PAPER] Order simulated | {side} {qty} {symbol} | ID: {fake_id}")
        return fake_id

    try:
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": side,
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty,
        }
        response = smart_api.placeOrder(order_params)
        order_id = response["data"]["orderid"]
        logger.info(f"Order placed | {side} {qty} {symbol} | Order ID: {order_id}")
        return order_id
    except Exception as e:
        logger.error(f"Order placement failed for {symbol}: {e}")
        return None


def place_sl_order(smart_api, symbol: str, token: str, side: str, qty: int, trigger_price: float) -> str:
    """Place a stop-loss market order."""
    try:
        order_params = {
            "variety": "STOPLOSS",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": side,
            "exchange": "NSE",
            "ordertype": "STOPLOSS_MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty,
            "triggerprice": trigger_price,
        }
        response = smart_api.placeOrder(order_params)
        order_id = response["data"]["orderid"]
        logger.info(f"SL Order placed | {side} {qty} {symbol} @ trigger {trigger_price} | Order ID: {order_id}")
        return order_id
    except Exception as e:
        logger.error(f"SL order failed for {symbol}: {e}")
        return None


def cancel_order(smart_api, order_id: str, variety: str = "NORMAL"):
    """Cancel an existing order."""
    try:
        smart_api.cancelOrder(order_id, variety)
        logger.info(f"Order {order_id} cancelled.")
    except Exception as e:
        logger.error(f"Cancel order failed: {e}")
