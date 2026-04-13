"""
RICOZ Bot — CoinGlass Data Fetcher

Phase 3: Poll CoinGlass via McPCG setiap 30 detik per pair.
Fetch parallel untuk speed (asyncio.gather).
"""
import asyncio
import time

from loguru import logger

from src.config import MCPCG_URL


class CoinGlassDataFetcher:
    """Fetch order flow data dari CoinGlass via McPCG."""

    def __init__(self):
        self.base_url = MCPCG_URL

    async def fetch_signal_data(self, symbol: str) -> dict:
        """
        Fetch semua signal data untuk satu symbol secara parallel.

        Args:
            symbol: e.g. 'SOL/USDT:USDT'

        Returns:
            dict dengan semua signal data + timestamp
        """
        base = symbol.replace("/USDT:USDT", "")  # 'SOL/USDT:USDT' → 'SOL'

        # Fetch parallel untuk speed
        spot_cvd, fut_cvd, liq, oi, taker = await asyncio.gather(
            self.get_spot_cvd(base),
            self.get_futures_cvd(base),
            self.get_liquidation(base),
            self.get_open_interest(base),
            self.get_taker_volume(base),
        )

        return {
            "symbol": symbol,
            "spot_cvd": spot_cvd,
            "fut_cvd": fut_cvd,
            "liquidation": liq,
            "open_interest": oi,
            "taker_volume": taker,
            "timestamp": time.time(),
        }

    async def get_spot_cvd(self, base_symbol: str) -> dict:
        """Fetch SpotCVD data — #1 HARD VETO signal."""
        # TODO Phase 3: Implement McPCG call → coinglass_spot_cvd
        logger.debug(f"Fetching SpotCVD for {base_symbol}")
        return {"history": [], "strength": 0.0}

    async def get_futures_cvd(self, base_symbol: str) -> dict:
        """Fetch FuturesCVD data — #2 HARD VETO signal."""
        # TODO Phase 3: Implement McPCG call → coinglass_futures_cvd
        logger.debug(f"Fetching FutCVD for {base_symbol}")
        return {"history": [], "strength": 0.0, "aligned_with_spot": False}

    async def get_liquidation(self, base_symbol: str) -> dict:
        """Fetch Liquidation data — #3 Confluence."""
        # TODO Phase 3: Implement McPCG call → coinglass_liquidation_cat
        logger.debug(f"Fetching Liquidation for {base_symbol}")
        return {"confirms_direction": False, "intensity": 0.0}

    async def get_open_interest(self, base_symbol: str) -> dict:
        """Fetch Open Interest data — #4 Confirmation."""
        # TODO Phase 3: Implement McPCG call → coinglass_open_interest_cat
        logger.debug(f"Fetching OI for {base_symbol}")
        return {"rising": False, "rate": 0.0}

    async def get_taker_volume(self, base_symbol: str) -> dict:
        """Fetch Taker Volume data — #5 Confirmation."""
        # TODO Phase 3: Implement McPCG call → coinglass_futures_taker_cat
        logger.debug(f"Fetching Taker Volume for {base_symbol}")
        return {"dominant": False, "ratio": 0.0}
