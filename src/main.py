"""
RICOZ Order Flow Bot — Main Entry Point

Phase 3: Signal Engine wired — full flow:
Signal → Score → State Check → Execute → Record → Notify
"""
import asyncio

from loguru import logger

from src.config import (
    SYMBOLS,
    PAPER_MODE,
    BINANCE_TESTNET,
    TELEGRAM_BOT_TOKEN,
    DB_PATH,
    AUTO_BUY_AMOUNT_USDT,
    SIZE_MULTIPLIER,
    validate_config,
)
from src.executor.binance_client import BinanceClient
from src.executor.order_manager import OrderManager
from src.signal.fetcher import CoinGlassDataFetcher
from src.signal.engine import SignalEngine
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
            exchange_positions = await order_manager.client.get_open_positions()
            exchange_symbols = set()
            for p in exchange_positions:
                exchange_symbols.add(p["symbol"])

            db_open = state_manager.get_open_positions()

            for db_pos in db_open:
                symbol = db_pos["symbol"]
                exchange_sym = symbol.replace("/", "").replace(":USDT", "")
                still_open = any(exchange_sym in str(ep.get("symbol", "")) for ep in exchange_positions)

                if not still_open:
                    try:
                        close_price = await order_manager.client.get_price(symbol)
                    except Exception:
                        close_price = db_pos["entry_price"]

                    entry_price = db_pos["entry_price"]
                    side = db_pos["side"]
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

                    exit_info = state_manager.record_exit(db_pos["id"], close_price, reason)
                    if exit_info:
                        await alerts.send_exit(symbol, exit_info["pnl_usdt"], exit_info["pnl_pct"], reason)
                        try:
                            await order_manager.client.cancel_all_orders(symbol)
                        except Exception:
                            pass
                        exchange_key = symbol.replace("/", "").replace(":USDT", "")
                        order_manager.active_positions.pop(exchange_key, None)

                    logger.info(f"Position exit detected: {symbol} — {reason}")

        except Exception as e:
            logger.error(f"Position monitor error: {e}")

        await asyncio.sleep(10)


async def signal_loop(
    fetcher: CoinGlassDataFetcher,
    engine: SignalEngine,
    state_manager: StateManager,
    order_manager: OrderManager,
    alerts: TelegramAlerts,
):
    """
    Phase 3: Signal trading loop.
    Every 30s: fetch signals → score → state check → execute → record → notify.
    """
    logger.info("Signal loop started")

    while True:
        for symbol in SYMBOLS:
            try:
                # ── 1. Fetch signal data ─────────────────
                data = await fetcher.fetch_signal_data(symbol)

                # ── 2. Evaluate signal ───────────────────
                result = engine.evaluate(data)
                decision = result["decision"]
                side = result["side"]
                score = result["score"]
                reason = result["reason"]

                if decision == "REJECT":
                    logger.debug(f"{symbol}: REJECT — {reason}")
                    continue

                # ── 3. State check ───────────────────────
                can_enter, block_reason = state_manager.can_enter(symbol)
                if not can_enter:
                    logger.info(f"{symbol}: Signal {decision} but blocked — {block_reason}")
                    continue

                # ── 4. Calculate size ────────────────────
                base_size = AUTO_BUY_AMOUNT_USDT
                size = base_size * SIZE_MULTIPLIER.get(decision, 0.5)

                # ── 5. Paper mode or execute ─────────────
                if PAPER_MODE:
                    logger.info(
                        f"[PAPER] {symbol}: {decision} {side.upper()} | "
                        f"size={size:.1f} USDT | score={score} | {reason}"
                    )
                    continue

                # ── 6. Execute order ─────────────────────
                logger.info(f"{symbol}: EXECUTING {decision} {side.upper()} {size:.1f} USDT (score={score})")
                order_result = await order_manager.execute_entry(symbol, side, size)

                if order_result["status"] == "cancelled":
                    logger.warning(f"{symbol}: Order cancelled — zero fill")
                    continue

                # ── 7. Record in DB ──────────────────────
                state_manager.record_entry(order_result, score=score)

                # ── 8. Notify ────────────────────────────
                await alerts.send_entry(
                    symbol, side, order_result["entry_price"], size, score
                )

            except Exception as e:
                logger.error(f"{symbol} signal loop error: {e}")
                await alerts.send_error(f"{symbol}: {e}")

        await asyncio.sleep(30)


async def main_loop():
    """Main bot loop — all phases wired."""
    # ── Initialize components ────────────────────────────
    db = Database(DB_PATH)
    db.connect()

    client = BinanceClient()
    alerts = TelegramAlerts()
    state_manager = StateManager(db)
    order_manager = OrderManager(client)
    fetcher = CoinGlassDataFetcher(interval="5m", limit=10)
    engine = SignalEngine()

    telegram_bot = TelegramBot(
        order_manager=order_manager,
        alerts=alerts,
        state_manager=state_manager,
    )

    try:
        # Connect to Binance
        await client.initialize()
        await fetcher.initialize()

        # Verify connection
        balance = await client.get_balance()
        usdt_balance = float(balance.get("USDT", {}).get("free", 0))
        logger.info(f"Connected — USDT balance: {usdt_balance}")

        # Check persisted positions
        db_open = state_manager.get_open_positions()
        if db_open:
            logger.info(f"Loaded {len(db_open)} open position(s) from DB")

        # Start Telegram bot
        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.start()

        # Send startup alert
        mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
        paper = " | PAPER" if PAPER_MODE else ""
        await alerts.send_startup(
            mode=f"{mode}{paper}",
            balance=usdt_balance,
            symbols=SYMBOLS,
        )

        # Start background tasks
        monitor_task = asyncio.create_task(
            position_monitor(order_manager, state_manager, alerts)
        )
        signal_task = asyncio.create_task(
            signal_loop(fetcher, engine, state_manager, order_manager, alerts)
        )

        today = state_manager.get_today_stats()
        logger.info(f"RICOZ Bot running — {'PAPER' if PAPER_MODE else 'LIVE'} | {mode}")
        logger.info(f"Monitoring: {SYMBOLS}")
        logger.info(f"DB positions: {len(db_open)} | Today PnL: {today['total_pnl_usdt']:.2f} USDT")
        logger.info("Signal loop + position monitor active")

        # Wait forever (tasks run in background)
        await asyncio.gather(monitor_task, signal_task)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        await alerts.send_error(f"Bot crashed: {e}")
        raise
    finally:
        logger.info("Shutting down...")
        await alerts.send_shutdown("Shutdown")
        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.stop()
        await fetcher.close()
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
