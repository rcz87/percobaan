"""
RICOZ Bot — Order Manager

Phase 1: Full order lifecycle.
Place order → handle partial fill → set SL/TP → track position → emergency close.
"""
from loguru import logger

from src.config import SL_PCT, TP_PCT
from .binance_client import BinanceClient
from .sl_tp import SLTPManager
from .partial_fill import PartialFillHandler


class OrderManager:
    """Manages full order lifecycle: entry → SL/TP → monitor → exit."""

    def __init__(self, client: BinanceClient):
        self.client = client
        self.sl_tp = SLTPManager(client)
        self.partial_fill = PartialFillHandler(client)
        self.active_positions: dict[str, dict] = {}  # symbol → position info

    async def execute_entry(self, symbol: str, side: str, amount_usdt: float) -> dict:
        """
        Full entry flow:
        1. Place market order
        2. Handle partial fill
        3. Set SL/TP
        4. Track position

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
        entry_price = float(order.get("average") or order.get("price") or 0)
        sl_tp_info = await self.sl_tp.set_sl_tp(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            qty=filled_qty,
            sl_pct=SL_PCT,
            tp_pct=TP_PCT,
        )

        # 4. Track position
        position_info = {
            "order_id": order["id"],
            "ccxt_symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "qty": filled_qty,
            "amount_usdt": amount_usdt,
            "sl_price": sl_tp_info["sl_price"],
            "tp_price": sl_tp_info["tp_price"],
            "sl_order_id": sl_tp_info["sl_order_id"],
            "tp_order_id": sl_tp_info["tp_order_id"],
        }

        # Track by exchange symbol (e.g. 'SOLUSDT')
        exchange_symbol = symbol.replace("/", "").replace(":USDT", "")
        self.active_positions[exchange_symbol] = position_info

        logger.info(
            f"Position opened: {symbol} {side.upper()} "
            f"@ {entry_price:.4f} | qty={filled_qty} | "
            f"SL={sl_tp_info['sl_price']:.4f} TP={sl_tp_info['tp_price']:.4f}"
        )

        return {"status": "filled", **position_info}

    async def emergency_close(self, symbol: str, side: str, qty: float) -> dict:
        """Emergency close — cancel all orders + market close."""
        close_side = "sell" if side == "buy" else "buy"

        # Cancel semua pending orders dulu
        try:
            await self.client.cancel_all_orders(symbol)
        except Exception as e:
            logger.warning(f"Cancel orders failed (may already be filled): {e}")

        # Market close
        order = await self.client.exchange.create_market_order(
            symbol, close_side, qty, params={"reduceOnly": True}
        )
        logger.warning(f"Emergency close {symbol}: {order['id']}")

        # Remove from tracking
        exchange_symbol = symbol.replace("/", "").replace(":USDT", "")
        self.active_positions.pop(exchange_symbol, None)

        return order

    async def close_all_positions(self) -> list:
        """Emergency close ALL open positions."""
        closed = []
        positions = await self.client.get_open_positions()

        for pos in positions:
            try:
                symbol = pos["symbol"]
                side = "buy" if pos["side"] == "long" else "sell"
                qty = abs(pos["contracts"])

                order = await self.emergency_close(symbol, side, qty)
                closed.append({"symbol": symbol, "order": order})
                logger.warning(f"Closed position: {symbol}")
            except Exception as e:
                logger.error(f"Failed to close {pos['symbol']}: {e}")

        self.active_positions.clear()
        return closed

    async def get_positions_summary(self) -> list[dict]:
        """Get summary of all open positions with live PnL."""
        positions = await self.client.get_open_positions()
        summary = []

        for pos in positions:
            symbol = pos["symbol"]
            entry_price = float(pos.get("entryPrice", 0))
            mark_price = float(pos.get("markPrice", 0))
            contracts = abs(pos["contracts"])
            side = pos.get("side", "long")
            unrealized_pnl = float(pos.get("unrealizedPnl", 0))

            if entry_price > 0:
                if side == "long":
                    pnl_pct = ((mark_price - entry_price) / entry_price) * 100
                else:
                    pnl_pct = ((entry_price - mark_price) / entry_price) * 100
            else:
                pnl_pct = 0.0

            summary.append({
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "mark_price": mark_price,
                "contracts": contracts,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
            })

        return summary
