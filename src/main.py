"""
RICOZ Order Flow Bot — Main Entry Point

Build order: Phase 1 → 2 → 3 → 4 → 5
Jangan skip phase. Bottom-up execution.
"""
import asyncio
import os

from loguru import logger

from src.config import (
    SYMBOLS,
    PAPER_MODE,
    AUTO_BUY_AMOUNT_USDT,
    SIZE_MULTIPLIER,
    validate_config,
)


# ── Logging setup ────────────────────────────────────────
logger.add(
    "logs/ricoz_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)


async def main_loop():
    """
    Main trading loop.
    Signal → State Check → Execute → Notify
    Runs every 30 seconds per symbol.
    """
    # TODO Phase 1: Initialize executor (BinanceClient)
    # TODO Phase 2: Initialize state manager
    # TODO Phase 3: Initialize signal engine + fetcher
    # TODO Phase 1: Initialize telegram alerts

    logger.info(f"RICOZ Bot started — {'PAPER' if PAPER_MODE else 'LIVE'} mode")
    logger.info(f"Monitoring: {SYMBOLS}")

    while True:
        for symbol in SYMBOLS:
            try:
                # ── Phase 3: Fetch signal data ───────────
                # data = await signal_fetcher.fetch_signal_data(symbol)

                # ── Phase 3: Calculate score ─────────────
                # score, breakdown = signal_engine.calculate_score(data)

                # ── Phase 3: Entry decision ──────────────
                # decision, reason = signal_engine.decide_entry(score, breakdown)
                # if 'ENTRY' not in decision:
                #     logger.info(f'{symbol}: {reason}')
                #     continue

                # ── Phase 2: State check ─────────────────
                # can_enter, block_reason = state_manager.can_enter(symbol)
                # if not can_enter:
                #     logger.info(f'{symbol}: Blocked — {block_reason}')
                #     continue

                # ── Phase 1: Calculate size & execute ────
                # base_size = AUTO_BUY_AMOUNT_USDT
                # size = base_size * SIZE_MULTIPLIER.get(decision, 0.5)

                # if PAPER_MODE:
                #     logger.info(f'[PAPER] {symbol}: {decision} — {size} USDT, score {score}')
                #     continue

                # order = await executor.place_market_order(symbol, 'buy', size)
                # entry_price = order['average']
                # qty = order['filled']
                # await executor.set_sl_tp(symbol, 'buy', entry_price, qty)

                # ── Phase 2: Record + Phase 1: Notify ────
                # state_manager.record_entry(symbol, order, score, breakdown)
                # await telegram.send_entry(symbol, 'buy', entry_price, size, score)

                pass  # placeholder sampai phase diimplementasi

            except Exception as e:
                logger.error(f"{symbol}: {e}")
                # await telegram.send_error(f'{symbol}: {e}')

        await asyncio.sleep(30)


def main():
    """Entry point."""
    if not validate_config():
        logger.error("Config validation failed. Check .env file.")
        return

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("RICOZ Bot stopped by user.")


if __name__ == "__main__":
    main()
