"""
RICOZ Order Flow Bot — Main Entry Point

Phase 2: StateManager wired — positions persist, PnL tracked, risk enforced.
"""
import asyncio

from loguru import logger

from src.config import (
    SYMBOLS,
    PAPER_MODE,
    BINANCE_TESTNET,
    TELEGRAM_BOT_TOKEN,
    DB_PATH,
    validate_config,
)
from src.executor.binance_client import BinanceClient
from src.executor.order_manager import OrderManager
from src.state.db import Database
from src.state.manager import StateManager
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


async def position_monitor(
    order_manager: OrderManager,
    state_manager: StateManager,
    alerts: TelegramAlerts,
):
    """
    Background task: monitor open positions untuk SL/TP fills.
    Cek setiap 10 detik. Ketika posisi hilang dari exchange → record exit di DB.
    """
    logger.info("Position monitor started")

    while True:
        try:
            # Get positions from exchange
            exchange_positions = await order_manager.client.get_open_positions()
            exchange_symbols = set()
            for p in exchange_positions:
                exchange_symbols.add(p["symbol"])

            # Get tracked positions from DB
            db_open = state_manager.get_open_positions()

            for db_pos in db_open:
                symbol = db_pos["symbol"]
                # Convert CCXT symbol to exchange format for comparison
                exchange_sym = symbol.replace("/", "").replace(":USDT", "")

                # Check if position still exists on exchange
                still_open = any(exchange_sym in str(ep.get("symbol", "")) for ep in exchange_positions)

                if not still_open:
                    # Position closed on exchange — SL or TP hit
                    try:
                        close_price = await order_manager.client.get_price(symbol)
                    except Exception:
                        close_price = db_pos["entry_price"]  # fallback

                    entry_price = db_pos["entry_price"]
                    side = db_pos["side"]

                    # Determine reason by comparing close price to SL/TP
                    sl_price = db_pos.get("sl_price")
                    tp_price = db_pos.get("tp_price")

                    if side == "buy":
                        if tp_price and close_price >= tp_price * 0.99:
                            reason = "TP"
                        elif sl_price and close_price <= sl_price * 1.01:
                            reason = "SL"
                        else:
                            reason = "Closed"
                    else:
                        if tp_price and close_price <= tp_price * 1.01:
                            reason = "TP"
                        elif sl_price and close_price >= sl_price * 0.99:
                            reason = "SL"
                        else:
                            reason = "Closed"

                    # Record exit in DB
                    exit_info = state_manager.record_exit(db_pos["id"], close_price, reason)

                    if exit_info:
                        # Send Telegram alert
                        await alerts.send_exit(
                            symbol,
                            exit_info["pnl_usdt"],
                            exit_info["pnl_pct"],
                            reason,
                        )

                        # Cancel remaining SL/TP orders
                        try:
                            await order_manager.client.cancel_all_orders(symbol)
                        except Exception:
                            pass

                        # Remove from order_manager tracking
                        exchange_key = symbol.replace("/", "").replace(":USDT", "")
                        order_manager.active_positions.pop(exchange_key, None)

                    logger.info(f"Position exit detected: {symbol} — {reason}")

        except Exception as e:
            logger.error(f"Position monitor error: {e}")

        await asyncio.sleep(10)


async def main_loop():
    """
    Main bot loop.
    Phase 1+2: Executor + StateManager + Telegram, all wired.
    """
    # ── Initialize components ────────────────────────────
    db = Database(DB_PATH)
    db.connect()

    client = BinanceClient()
    alerts = TelegramAlerts()
    state_manager = StateManager(db)
    order_manager = OrderManager(client)
    telegram_bot = TelegramBot(
        order_manager=order_manager,
        alerts=alerts,
        state_manager=state_manager,
    )

    try:
        # Connect to Binance
        await client.initialize()

        # Verify connection
        balance = await client.get_balance()
        usdt_balance = float(balance.get("USDT", {}).get("free", 0))
        logger.info(f"Connected — USDT balance: {usdt_balance}")

        # Check for persisted open positions
        db_open = state_manager.get_open_positions()
        if db_open:
            logger.info(f"Loaded {len(db_open)} open position(s) from DB")
            for pos in db_open:
                logger.info(f"  {pos['symbol']} {pos['side']} @ {pos['entry_price']:.4f}")

        # Start Telegram bot
        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.start()

        # Send startup alert
        mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
        paper = " | PAPER MODE" if PAPER_MODE else ""
        today = state_manager.get_today_stats()
        await alerts.send_startup(
            mode=f"{mode}{paper}",
            balance=usdt_balance,
            symbols=SYMBOLS,
        )

        # Start position monitor as background task
        monitor_task = asyncio.create_task(
            position_monitor(order_manager, state_manager, alerts)
        )

        logger.info(f"RICOZ Bot running — {'PAPER' if PAPER_MODE else 'LIVE'} | {mode}")
        logger.info(f"Monitoring: {SYMBOLS}")
        logger.info(f"DB open positions: {len(db_open)} | Today PnL: {today['total_pnl_usdt']:.2f} USDT")
        logger.info("Waiting for commands via Telegram...")

        # Bot idle — waits for Telegram commands
        # Trading loop akan diaktifkan di Phase 3 (Signal Engine)
        while True:
            await asyncio.sleep(30)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        await alerts.send_error(f"Bot crashed: {e}")
        raise
    finally:
        logger.info("Shutting down...")
        await alerts.send_shutdown("Shutdown")
        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.stop()
        await client.close()
        db.close()
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
