"""
RICOZ Order Flow Bot — Main Entry Point

Phase 1: Execution Engine aktif.
BinanceClient + OrderManager + TelegramBot + TelegramAlerts.
"""
import asyncio
import signal as sig

from loguru import logger

from src.config import (
    SYMBOLS,
    PAPER_MODE,
    BINANCE_TESTNET,
    TELEGRAM_BOT_TOKEN,
    validate_config,
)
from src.executor.binance_client import BinanceClient
from src.executor.order_manager import OrderManager
from src.telegram.alerts import TelegramAlerts
from src.telegram.bot import TelegramBot


# ── Logging setup ────────────────────────────────────────
logger.add(
    "logs/ricoz_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)


async def position_monitor(order_manager: OrderManager, alerts: TelegramAlerts):
    """
    Background task: monitor open positions untuk SL/TP fills.
    Cek setiap 10 detik apakah ada posisi yang sudah close.
    """
    logger.info("Position monitor started")
    tracked: dict[str, dict] = {}  # symbol → position info

    while True:
        try:
            open_positions = await order_manager.client.get_open_positions()
            open_symbols = {p["symbol"] for p in open_positions}

            # Detect closed positions (was tracked, now gone)
            for symbol, info in list(tracked.items()):
                if symbol not in open_symbols:
                    # Position closed — SL or TP hit
                    price = await order_manager.client.get_price(info["ccxt_symbol"])
                    entry_price = info["entry_price"]
                    side = info["side"]

                    if side == "buy":
                        pnl_pct = ((price - entry_price) / entry_price) * 100
                    else:
                        pnl_pct = ((entry_price - price) / entry_price) * 100

                    pnl_usdt = info["qty"] * entry_price * (pnl_pct / 100)

                    reason = "TP" if pnl_usdt > 0 else "SL"
                    await alerts.send_exit(info["ccxt_symbol"], pnl_usdt, pnl_pct, reason)

                    # Cancel remaining SL or TP order
                    try:
                        await order_manager.client.cancel_all_orders(info["ccxt_symbol"])
                    except Exception:
                        pass

                    del tracked[symbol]
                    logger.info(f"Position closed detected: {symbol} — {reason} — PnL: {pnl_usdt:+.2f} USDT")

            # Update tracked positions from order_manager
            for sym, info in order_manager.active_positions.items():
                if sym not in tracked:
                    tracked[sym] = info

            # Cleanup tracked jika order_manager sudah remove
            for sym in list(tracked.keys()):
                if sym not in order_manager.active_positions and sym in open_symbols:
                    pass  # still open on exchange, keep tracking

        except Exception as e:
            logger.error(f"Position monitor error: {e}")

        await asyncio.sleep(10)


async def main_loop():
    """
    Main bot loop.
    Phase 1: Initialize executor + telegram, monitor positions.
    """
    # ── Initialize components ────────────────────────────
    client = BinanceClient()
    alerts = TelegramAlerts()
    order_manager = OrderManager(client)
    telegram_bot = TelegramBot(order_manager=order_manager, alerts=alerts)

    try:
        # Connect to Binance
        await client.initialize()

        # Verify connection
        balance = await client.get_balance()
        usdt_balance = balance.get("USDT", {}).get("free", 0)
        logger.info(f"Connected — USDT balance: {usdt_balance}")

        # Start Telegram bot
        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.start()

        # Send startup alert
        mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
        paper = " | PAPER MODE" if PAPER_MODE else ""
        await alerts.send_status(
            f"Bot started\n"
            f"Mode: `{mode}{paper}`\n"
            f"Balance: `{usdt_balance:.2f} USDT`\n"
            f"Symbols: `{', '.join(SYMBOLS)}`"
        )

        # Start position monitor as background task
        monitor_task = asyncio.create_task(position_monitor(order_manager, alerts))

        logger.info(f"RICOZ Bot running — {'PAPER' if PAPER_MODE else 'LIVE'} | {mode}")
        logger.info(f"Monitoring: {SYMBOLS}")
        logger.info("Waiting for commands via Telegram...")

        # Phase 1: Bot idle — waits for Telegram commands
        # Trading loop akan diaktifkan di Phase 3 (Signal Engine)
        while True:
            await asyncio.sleep(30)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        await alerts.send_error(f"Bot crashed: {e}")
        raise
    finally:
        logger.info("Shutting down...")
        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.stop()
        await client.close()
        logger.info("RICOZ Bot stopped.")


def main():
    """Entry point."""
    if not validate_config():
        logger.error("Config validation failed. Check .env file.")
        return

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("RICOZ Bot stopped by user (Ctrl+C).")


if __name__ == "__main__":
    main()
