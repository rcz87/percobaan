"""
RICOZ Bot — Order Manager

Koordinasi antara BinanceClient, SL/TP, dan Partial Fill.
Satu entry flow: place order → set SL/TP → handle partial fill.
"""
import asyncio
from loguru import logger

from src.config import SL_PCT, TP_PCT
from .binance_client import BinanceClient
from .sl_tp import SLTPManager
from .partial_fill import PartialFillHandler


class OrderManager:
    """Manages full order lifecycle: entry → SL/TP → partial fill → exit."""

    def __init__(self, client: BinanceClient):
        self.client = client
        self.sl_tp = SLTPManager(client)
        self.partial_fill = PartialFillHandler(client)

    async def execute_entry(self, symbol: str, side: str, amount_usdt: float) -> dict:
        """
        Full entry flow:
        1. Place market order
        2. Handle partial fill
        3. Set SL/TP

        Returns dict dengan entry info.
        """
        # 1. Place market order
        order = await self.client.place_market_order(symbol, side, amount_usdt)

        # 2. Handle partial fill
        filled_qty = await self.partial_fill.handle(
            order_id=order["id"],
            symbol=symbol,
            expected_amount=float(order["amount"]),
        )

        if filled_qty == 0:
            logger.warning(f"{symbol}: Order fully cancelled — zero fill")
            return {"status": "cancelled", "filled": 0}

        # 3. Set SL/TP
        entry_price = float(order.get("average", order.get("price", 0)))
        await self.sl_tp.set_sl_tp(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            qty=filled_qty,
            sl_pct=SL_PCT,
            tp_pct=TP_PCT,
        )

        return {
            "status": "filled",
            "order_id": order["id"],
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "qty": filled_qty,
            "amount_usdt": amount_usdt,
        }

    async def emergency_close(self, symbol: str, side: str, qty: float):
        """Emergency close — cancel orders + market close."""
        close_side = "sell" if side == "buy" else "buy"

        # Cancel semua pending orders dulu
        await self.client.cancel_all_orders(symbol)

        # Market close
        order = await self.client.exchange.create_market_order(
            symbol, close_side, qty, params={"reduceOnly": True}
        )
        logger.warning(f"Emergency close {symbol}: {order['id']}")
        return order
