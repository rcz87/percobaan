"""
RICOZ Bot — Binance CCXT Wrapper

Phase 1: Core execution engine.
Pattern dari Freqtrade exchange.py:
- @retrier decorator dengan quadratic backoff
- Precision enforcement sebelum order
- Error classification (retryable vs fatal)
"""
import asyncio
import functools

import ccxt.async_support as ccxt
from loguru import logger

from src.config import BINANCE_API_KEY, BINANCE_SECRET, BINANCE_TESTNET


# ── Retry Decorator (Freqtrade pattern) ──────────────────
API_RETRY_COUNT = 4


def retrier(f):
    """Retry decorator dengan quadratic backoff untuk network errors."""
    @functools.wraps(f)
    async def wrapper(*args, **kwargs):
        for attempt in range(API_RETRY_COUNT):
            try:
                return await f(*args, **kwargs)
            except (ccxt.NetworkError, ccxt.DDoSProtection) as e:
                if attempt == API_RETRY_COUNT - 1:
                    logger.error(f"Max retries reached for {f.__name__}: {e}")
                    raise
                wait = (API_RETRY_COUNT - attempt) ** 2 + 1
                logger.warning(f"{f.__name__} retry {attempt + 1}/{API_RETRY_COUNT} — wait {wait}s: {e}")
                await asyncio.sleep(wait)
            except ccxt.InsufficientFunds as e:
                logger.error(f"Insufficient funds: {e}")
                raise
            except ccxt.InvalidOrder as e:
                logger.error(f"Invalid order: {e}")
                raise
            except ccxt.AuthenticationError as e:
                logger.error(f"Auth error: {e}")
                raise
            except ccxt.ExchangeError as e:
                logger.error(f"Exchange error: {e}")
                raise
    return wrapper


class BinanceClient:
    """CCXT async wrapper untuk Binance USDM Futures."""

    def __init__(self):
        self.exchange = ccxt.binanceusdm({
            "apiKey": BINANCE_API_KEY,
            "secret": BINANCE_SECRET,
            "enableRateLimit": True,
        })
        if BINANCE_TESTNET:
            self.exchange.set_sandbox_mode(True)
            logger.info("Binance client initialized — TESTNET mode")
        else:
            logger.info("Binance client initialized — LIVE mode")

    async def initialize(self):
        """Load markets — panggil sebelum trading."""
        await self.exchange.load_markets()
        logger.info(f"Markets loaded: {len(self.exchange.markets)} pairs")

    async def close(self):
        """Cleanup — selalu panggil di finally block."""
        await self.exchange.close()

    # ── Market Data ──────────────────────────────────────

    @retrier
    async def get_price(self, symbol: str) -> float:
        """Get last price untuk symbol."""
        ticker = await self.exchange.fetch_ticker(symbol)
        return ticker["last"]

    @retrier
    async def get_balance(self) -> dict:
        """Get account balance."""
        return await self.exchange.fetch_balance()

    @retrier
    async def get_open_positions(self) -> list:
        """Get semua posisi terbuka (contracts > 0)."""
        positions = await self.exchange.fetch_positions()
        return [p for p in positions if abs(p["contracts"]) > 0]

    # ── Order Execution ──────────────────────────────────

    @retrier
    async def place_market_order(self, symbol: str, side: str, amount_usdt: float) -> dict:
        """
        Place market order berdasarkan USDT amount.
        Returns CCXT order dict.
        """
        price = await self.get_price(symbol)
        qty = amount_usdt / price

        # Precision enforcement (Freqtrade pattern)
        qty = self.exchange.amount_to_precision(symbol, qty)
        qty = float(qty)

        logger.info(f"Placing {side.upper()} market order: {symbol} qty={qty} (~{amount_usdt} USDT)")
        order = await self.exchange.create_market_order(symbol, side, qty)
        logger.info(f"Order filled: {order['id']} — avg price {order.get('average', 'N/A')}")
        return order

    @retrier
    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel specific order."""
        return await self.exchange.cancel_order(order_id, symbol)

    @retrier
    async def cancel_all_orders(self, symbol: str):
        """Cancel semua open orders untuk symbol."""
        await self.exchange.cancel_all_orders(symbol)
        logger.info(f"All orders cancelled for {symbol}")

    @retrier
    async def fetch_order(self, order_id: str, symbol: str) -> dict:
        """Fetch order status by ID."""
        return await self.exchange.fetch_order(order_id, symbol)

    @retrier
    async def set_leverage(self, leverage: int, symbol: str):
        """Set leverage untuk symbol."""
        await self.exchange.set_leverage(leverage, symbol)
        logger.info(f"Leverage set to {leverage}x for {symbol}")
