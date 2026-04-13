"""
RICOZ Bot — Partial Fill Handler

Tunggu fill → cek status → cancel sisa kalau partial.
Blueprint rule: tunggu 2s → cek → kalau partial → cancel sisa.
"""
import asyncio
from loguru import logger

from .binance_client import BinanceClient


class PartialFillHandler:
    """Handle partial fills dengan timeout + cancel logic."""

    def __init__(self, client: BinanceClient, timeout_secs: int = 5):
        self.client = client
        self.timeout_secs = timeout_secs

    async def handle(self, order_id: str, symbol: str, expected_amount: float) -> float:
        """
        Tunggu fill, cancel sisa kalau partial.

        Args:
            order_id: ID order dari exchange
            symbol: Trading pair
            expected_amount: Amount yang diexpect full fill

        Returns:
            float: Jumlah yang benar-benar filled (bisa 0 kalau cancelled)
        """
        await asyncio.sleep(self.timeout_secs)

        order = await self.client.fetch_order(order_id, symbol)
        status = order.get("status", "unknown")
        filled = float(order.get("filled", 0))

        if status == "closed":
            # Full fill
            logger.info(f"Order {order_id} fully filled: {filled}")
            return filled

        if status == "open" and filled > 0:
            # Partial fill — cancel sisa
            logger.warning(f"Partial fill {order_id}: {filled}/{expected_amount} — cancelling remaining")
            await self.client.cancel_order(order_id, symbol)
            return filled

        if status == "open" and filled == 0:
            # Zero fill — cancel semua
            logger.warning(f"Zero fill {order_id} — cancelling")
            await self.client.cancel_order(order_id, symbol)
            return 0.0

        # Order sudah cancelled atau status lain
        logger.info(f"Order {order_id} status: {status}, filled: {filled}")
        return filled
