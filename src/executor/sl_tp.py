"""
RICOZ Bot — Stop Loss / Take Profit Manager

SL/TP auto-set setelah entry fill.
Pattern: STOP_MARKET + TAKE_PROFIT_MARKET (dari CCXT Binance examples).
"""
from loguru import logger

from .binance_client import BinanceClient


class SLTPManager:
    """Set dan manage SL/TP orders."""

    def __init__(self, client: BinanceClient):
        self.client = client

    async def set_sl_tp(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        qty: float,
        sl_pct: float = 0.015,
        tp_pct: float = 0.030,
    ) -> dict:
        """
        Set SL dan TP setelah entry fill.

        Args:
            symbol: Trading pair (e.g. 'SOL/USDT:USDT')
            side: Entry side ('buy' atau 'sell')
            entry_price: Harga entry rata-rata
            qty: Jumlah yang di-fill
            sl_pct: Stop loss percentage (default 1.5%)
            tp_pct: Take profit percentage (default 3.0%)

        Returns:
            dict dengan SL dan TP order info
        """
        close_side = "sell" if side == "buy" else "buy"

        # Calculate SL/TP prices
        if side == "buy":  # long
            sl_price = entry_price * (1 - sl_pct)
            tp_price = entry_price * (1 + tp_pct)
        else:  # short
            sl_price = entry_price * (1 + sl_pct)
            tp_price = entry_price * (1 - tp_pct)

        # Precision enforcement
        exchange = self.client.exchange
        sl_price = float(exchange.price_to_precision(symbol, sl_price))
        tp_price = float(exchange.price_to_precision(symbol, tp_price))
        qty = float(exchange.amount_to_precision(symbol, qty))

        # Place SL (STOP_MARKET)
        sl_order = await exchange.create_order(
            symbol, "STOP_MARKET", close_side, qty, None,
            {"stopPrice": sl_price, "reduceOnly": True}
        )
        logger.info(f"SL set: {symbol} @ {sl_price} ({sl_pct*100}%)")

        # Place TP (TAKE_PROFIT_MARKET)
        tp_order = await exchange.create_order(
            symbol, "TAKE_PROFIT_MARKET", close_side, qty, None,
            {"stopPrice": tp_price, "reduceOnly": True}
        )
        logger.info(f"TP set: {symbol} @ {tp_price} ({tp_pct*100}%)")

        return {
            "sl_order_id": sl_order["id"],
            "tp_order_id": tp_order["id"],
            "sl_price": sl_price,
            "tp_price": tp_price,
        }
