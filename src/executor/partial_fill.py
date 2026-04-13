"""
RICOZ Bot — Partial Fill Handler

Phase 1: Market orders di futures biasanya instan.
Tapi tetap handle edge case: partial fill → cancel sisa.
Blueprint rule: tunggu 2s → cek → kalau partial → cancel sisa.
"""
import asyncio
from loguru import logger

from .binance_client import BinanceClient


class PartialFillHandler:
    """Handle partial fills dengan timeout + cancel logic."""

    def __init__(self, client: BinanceClient, timeout_secs: int = 2):
        self.client = client
        self.timeout_secs = timeout_secs

    async def handle(self, order_id: str, symbol: str, expected_amount: float) -> float:
        """
        Check fill status, cancel sisa kalau partial.

        Market orders di futures biasanya instant full fill.
        Tetap handle edge case untuk safety.

        Returns:
            float: Jumlah yang benar-benar filled (bisa 0 kalau cancelled)
        """
        # Quick check dulu — market orders biasanya sudah filled
        order = await self.client.fetch_order(order_id, symbol)
        status = order.get("status", "unknown")
        filled = float(order.get("filled", 0))

        if status == "closed":
            logger.info(f"Order {order_id} fully filled: {filled}")
            return filled

        # Belum filled — tunggu sebentar (edge case)
        logger.info(f"Order {order_id} status={status}, waiting {self.timeout_secs}s...")
        await asyncio.sleep(self.timeout_secs)

        order = await self.client.fetch_order(order_id, symbol)
        status = order.get("status", "unknown")
        filled = float(order.get("filled", 0))

        if status == "closed":
            logger.info(f"Order {order_id} fully filled after wait: {filled}")
            return filled

        if status == "open" and filled > 0:
            # Partial fill — cancel sisa
            logger.warning(f"Partial fill {order_id}: {filled}/{expected_amount} — cancelling remaining")
            try:
                await self.client.cancel_order(order_id, symbol)
            except Exception as e:
                logger.warning(f"Cancel failed (may already closed): {e}")
            return filled

        if status == "open" and filled == 0:
            # Zero fill — cancel semua
            logger.warning(f"Zero fill {order_id} — cancelling")
            try:
                await self.client.cancel_order(order_id, symbol)
            except Exception as e:
                logger.warning(f"Cancel failed: {e}")
            return 0.0

        # Cancelled atau status lain — return whatever was filled
        logger.info(f"Order {order_id} final status: {status}, filled: {filled}")
        return filled
