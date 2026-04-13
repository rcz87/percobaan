"""
RICOZ Bot — CoinGlass Data Fetcher

Phase 3: Fetch order flow data via McPCG MCP server.
Uses aiohttp to call MCP tools over HTTP (JSON-RPC / Streamable HTTP).
Falls back to direct parsing if available.
"""
import asyncio
import json
import time

import aiohttp
from loguru import logger

from src.config import MCPCG_URL
from .parser import (
    parse_mcp_response,
    parse_cvd_response,
    parse_liquidation_response,
    parse_oi_response,
    parse_taker_response,
)


# Stale signal threshold — blueprint: > 10 detik = cancel
MAX_DATA_AGE_SECS = 120  # WARNING threshold (from MCP server instructions)
SIGNAL_STALE_SECS = 10   # entry rejection threshold


class CoinGlassDataFetcher:
    """Fetch order flow data dari CoinGlass via McPCG MCP server."""

    def __init__(self, interval: str = "5m", limit: int = 10):
        self.base_url = MCPCG_URL
        self.interval = interval
        self.limit = limit
        self.session: aiohttp.ClientSession | None = None

    async def initialize(self):
        """Create aiohttp session."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        logger.info(f"CoinGlass fetcher initialized — McPCG: {self.base_url}")

    async def close(self):
        """Close session."""
        if self.session:
            await self.session.close()

    async def _call_mcp_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Call MCP tool via McPCG HTTP endpoint.
        MCP Streamable HTTP: POST JSON-RPC to the endpoint.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": 1,
        }

        try:
            async with self.session.post(
                self.base_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"McPCG HTTP {resp.status} for {tool_name}")
                    return {"status": "error", "data": f"HTTP {resp.status}"}

                content_type = resp.headers.get("Content-Type", "")

                if "text/event-stream" in content_type:
                    # SSE response — parse event stream
                    text = await resp.text()
                    return self._parse_sse(text)
                else:
                    # JSON response
                    data = await resp.json()
                    if "result" in data:
                        result = data["result"]
                        if isinstance(result, str):
                            return json.loads(result)
                        # result may have content array
                        if isinstance(result, dict) and "content" in result:
                            for item in result["content"]:
                                if item.get("type") == "text":
                                    return json.loads(item["text"])
                        return result
                    return data

        except asyncio.TimeoutError:
            logger.warning(f"McPCG timeout for {tool_name}")
            return {"status": "error", "data": "timeout"}
        except Exception as e:
            logger.warning(f"McPCG error for {tool_name}: {e}")
            return {"status": "error", "data": str(e)}

    def _parse_sse(self, text: str) -> dict:
        """Parse Server-Sent Events response."""
        for line in text.split("\n"):
            if line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    msg = json.loads(data_str)
                    if "result" in msg:
                        result = msg["result"]
                        if isinstance(result, dict) and "content" in result:
                            for item in result["content"]:
                                if item.get("type") == "text":
                                    return json.loads(item["text"])
                        if isinstance(result, str):
                            return json.loads(result)
                        return result
                except json.JSONDecodeError:
                    continue
        return {"status": "error", "data": "Failed to parse SSE"}

    # ── Signal Data Fetchers ─────────────────────────────

    async def fetch_signal_data(self, symbol: str) -> dict:
        """
        Fetch ALL signal data untuk satu symbol secara parallel.
        Returns structured dict for SignalEngine.
        """
        base = symbol.replace("/USDT:USDT", "")  # 'SOL/USDT:USDT' → 'SOL'
        fetch_time = time.time()

        # Fetch all 5 signals in parallel
        results = await asyncio.gather(
            self._fetch_spot_cvd(base),
            self._fetch_futures_cvd(base),
            self._fetch_liquidation(base),
            self._fetch_open_interest(base),
            self._fetch_taker_volume(base),
            return_exceptions=True,
        )

        # Handle exceptions
        spot_cvd = results[0] if not isinstance(results[0], Exception) else self._empty_cvd()
        fut_cvd = results[1] if not isinstance(results[1], Exception) else self._empty_cvd()
        liq = results[2] if not isinstance(results[2], Exception) else self._empty_liq()
        oi = results[3] if not isinstance(results[3], Exception) else self._empty_oi()
        taker = results[4] if not isinstance(results[4], Exception) else self._empty_taker()

        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(f"{base} signal {i} failed: {r}")

        return {
            "symbol": symbol,
            "base": base,
            "spot_cvd": spot_cvd,
            "fut_cvd": fut_cvd,
            "liquidation": liq,
            "open_interest": oi,
            "taker_volume": taker,
            "timestamp": fetch_time,
        }

    async def _fetch_spot_cvd(self, base: str) -> dict:
        """Fetch + parse SpotCVD."""
        raw = await self._call_mcp_tool("coinglass_spot_cvd", {
            "symbol": base, "interval": self.interval, "limit": self.limit,
        })
        data_text = raw.get("data", "")
        parsed = parse_cvd_response(data_text)
        parsed["data_age"] = raw.get("data_age_seconds", 0)
        return parsed

    async def _fetch_futures_cvd(self, base: str) -> dict:
        """Fetch + parse FuturesCVD."""
        raw = await self._call_mcp_tool("coinglass_futures_cvd", {
            "symbol": base, "interval": self.interval, "limit": self.limit,
        })
        data_text = raw.get("data", "")
        parsed = parse_cvd_response(data_text)
        parsed["data_age"] = raw.get("data_age_seconds", 0)
        return parsed

    async def _fetch_liquidation(self, base: str) -> dict:
        """Fetch + parse Liquidation."""
        raw = await self._call_mcp_tool("coinglass_liquidation_cat", {
            "symbol": base, "action": "coin_history",
            "interval": self.interval, "limit": self.limit,
        })
        data_text = raw.get("data", "")
        parsed = parse_liquidation_response(data_text)
        parsed["data_age"] = raw.get("data_age_seconds", 0)
        return parsed

    async def _fetch_open_interest(self, base: str) -> dict:
        """Fetch + parse Open Interest."""
        raw = await self._call_mcp_tool("coinglass_open_interest_cat", {
            "symbol": base, "action": "aggregated_history",
            "interval": self.interval, "limit": self.limit,
        })
        data_text = raw.get("data", "")
        parsed = parse_oi_response(data_text)
        parsed["data_age"] = raw.get("data_age_seconds", 0)
        return parsed

    async def _fetch_taker_volume(self, base: str) -> dict:
        """Fetch + parse Taker Buy/Sell."""
        raw = await self._call_mcp_tool("coinglass_futures_taker_cat", {
            "symbol": base, "action": "coin_taker",
            "interval": self.interval, "limit": self.limit,
        })
        data_text = raw.get("data", "")
        parsed = parse_taker_response(data_text)
        parsed["data_age"] = raw.get("data_age_seconds", 0)
        return parsed

    # ── Empty fallbacks ──────────────────────────────────

    def _empty_cvd(self):
        return {"deltas": [], "values": [], "direction": "unknown",
                "positive_ratio": 0.0, "net_change": 0.0, "data_age": 999}

    def _empty_liq(self):
        return {"long_liqs": [], "short_liqs": [], "total_long": 0,
                "total_short": 0, "dominant_side": "neutral", "data_age": 999}

    def _empty_oi(self):
        return {"values": [], "change": 0, "rising": False,
                "rate": 0.0, "data_age": 999}

    def _empty_taker(self):
        return {"buy_vols": [], "sell_vols": [], "nets": [],
                "buy_dominant_ratio": 0.0, "total_net": 0.0, "data_age": 999}
