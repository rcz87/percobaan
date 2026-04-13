"""
RICOZ Order Flow Bot — Main Entry Point

Phase 4: Full integration — paper trading tracks in DB, SL/TP simulated.
Signal → Score → State Check → Execute/Paper → Record → Monitor → Notify
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
    SL_PCT,
    TP_PCT,
    SIGNAL_INTERVAL,
    SIGNAL_LOOKBACK,
    SIGNAL_LOOP_SECS,
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
    Background: monitor LIVE open positions for SL/TP fills.
    When position disappears from exchange → record exit in DB.
    """
    logger.info("Live position monitor started")

    while True:
        try:
            exchange_positions = await order_manager.client.get_open_positions()
            exchange_symbols = set()
            for p in exchange_positions:
                exchange_symbols.add(p["symbol"])

            db_open = [p for p in state_manager.get_open_positions() if not p.get("is_paper")]

            for db_pos in db_open:
                symbol = db_pos["symbol"]
                exchange_sym = symbol.replace("/", "").replace(":USDT", "")
                still_open = any(exchange_sym in str(ep.get("symbol", "")) for ep in exchange_positions)

                if not still_open:
                    try:
                        close_price = await order_manager.client.get_price(symbol)
                    except Exception:
                        close_price = db_pos["entry_price"]

                    reason = _detect_close_reason(db_pos, close_price)
                    exit_info = state_manager.record_exit(db_pos["id"], close_price, reason)

                    if exit_info:
                        await alerts.send_exit(symbol, exit_info["pnl_usdt"], exit_info["pnl_pct"], reason)
                        try:
                            await order_manager.client.cancel_all_orders(symbol)
                        except Exception:
                            pass
                        exchange_key = symbol.replace("/", "").replace(":USDT", "")
                        order_manager.active_positions.pop(exchange_key, None)

        except Exception as e:
            logger.error(f"Live monitor error: {e}")

        await asyncio.sleep(10)


async def paper_position_monitor(
    client: BinanceClient,
    state_manager: StateManager,
    alerts: TelegramAlerts,
):
    """
    Background: monitor PAPER positions — simulate SL/TP hits from live price.
    Checks every 10s if current price crossed SL or TP.
    """
    logger.info("Paper position monitor started")

    while True:
        try:
            paper_positions = state_manager.get_open_paper_positions()

            for pos in paper_positions:
                symbol = pos["symbol"]
                try:
                    current_price = await client.get_price(symbol)
                except Exception:
                    continue

                sl = pos.get("sl_price")
                tp = pos.get("tp_price")
                side = pos["side"]
                hit = None

                if side == "buy":  # long
                    if sl and current_price <= sl:
                        hit = "SL"
                    elif tp and current_price >= tp:
                        hit = "TP"
                else:  # short
                    if sl and current_price >= sl:
                        hit = "SL"
                    elif tp and current_price <= tp:
                        hit = "TP"

                if hit:
                    close_price = sl if hit == "SL" else tp
                    exit_info = state_manager.record_exit(pos["id"], close_price, hit)

                    if exit_info:
                        logger.info(
                            f"[PAPER] {symbol} {hit} hit — "
                            f"PnL: {exit_info['pnl_usdt']:+.4f} USDT ({exit_info['pnl_pct']:+.2f}%)"
                        )
                        await alerts.send_exit(
                            f"[PAPER] {symbol}",
                            exit_info["pnl_usdt"],
                            exit_info["pnl_pct"],
                            f"Paper {hit}",
                        )

        except Exception as e:
            logger.error(f"Paper monitor error: {e}")

        await asyncio.sleep(10)


def _detect_close_reason(db_pos: dict, close_price: float) -> str:
    """Determine SL/TP/Closed based on close price vs SL/TP levels."""
    side = db_pos["side"]
    sl = db_pos.get("sl_price")
    tp = db_pos.get("tp_price")

    if side == "buy":
        if tp and close_price >= tp * 0.99:
            return "TP"
        if sl and close_price <= sl * 1.01:
            return "SL"
    else:
        if tp and close_price <= tp * 1.01:
            return "TP"
        if sl and close_price >= sl * 0.99:
            return "SL"
    return "Closed"


async def signal_loop(
    fetcher: CoinGlassDataFetcher,
    engine: SignalEngine,
    state_manager: StateManager,
    order_manager: OrderManager,
    alerts: TelegramAlerts,
    client: BinanceClient,
):
    """
    Signal trading loop — every 30s per symbol.
    Paper mode: simulates entry at current price, records in DB.
    Live mode: executes via OrderManager.
    """
    logger.info(f"Signal loop started — {'PAPER' if PAPER_MODE else 'LIVE'} mode")
    cycle = 0

    while True:
        cycle += 1
        for symbol in SYMBOLS:
            try:
                # ── 1. Fetch ─────────────────────────────
                data = await fetcher.fetch_signal_data(symbol)

                # ── 2. Evaluate ──────────────────────────
                result = engine.evaluate(data)
                decision = result["decision"]
                side = result["side"]
                score = result["score"]
                breakdown = result["breakdown"]
                reason = result["reason"]

                # Trace log every signal (for Phase 4 visibility)
                if decision != "REJECT":
                    logger.info(
                        f"[SIGNAL] {symbol}: {decision} {side.upper()} "
                        f"score={score} breakdown={breakdown} | {reason}"
                    )
                elif cycle % 10 == 0:
                    # Log rejections every 10th cycle to avoid spam
                    logger.debug(f"[SIGNAL] {symbol}: REJECT — {reason}")

                if decision == "REJECT":
                    continue

                # ── 3. State check ───────────────────────
                can_enter, block_reason = state_manager.can_enter(symbol)
                if not can_enter:
                    logger.info(f"[BLOCKED] {symbol}: {decision} {side.upper()} — {block_reason}")
                    continue

                # ── 4. Size ──────────────────────────────
                base_size = AUTO_BUY_AMOUNT_USDT
                size = base_size * SIZE_MULTIPLIER.get(decision, 0.5)

                # ── 5. Execute or Paper ──────────────────
                if PAPER_MODE:
                    # Get current price for paper entry
                    price = await client.get_price(symbol)

                    paper_result = state_manager.record_paper_entry(
                        symbol=symbol,
                        side=side,
                        price=price,
                        size_usdt=size,
                        score=score,
                        breakdown=breakdown,
                    )

                    logger.info(
                        f"[PAPER ENTRY] {symbol} {side.upper()} @ {price:.4f} | "
                        f"size={size:.1f} USDT | score={score} | "
                        f"SL={paper_result['sl_price']:.4f} TP={paper_result['tp_price']:.4f}"
                    )
                    await alerts.send_entry(
                        f"[PAPER] {symbol}", side, price, size, score
                    )

                else:
                    # Live execution
                    logger.info(
                        f"[EXECUTE] {symbol}: {decision} {side.upper()} "
                        f"{size:.1f} USDT (score={score})"
                    )
                    order_result = await order_manager.execute_entry(symbol, side, size)

                    if order_result["status"] == "cancelled":
                        logger.warning(f"{symbol}: Order cancelled — zero fill")
                        continue

                    state_manager.record_entry(order_result, score=score, breakdown=breakdown)
                    await alerts.send_entry(
                        symbol, side, order_result["entry_price"], size, score
                    )

            except Exception as e:
                logger.error(f"[SIGNAL LOOP] {symbol}: {e}")
                await alerts.send_error(f"{symbol}: {e}")

        await asyncio.sleep(SIGNAL_LOOP_SECS)


async def main_loop():
    """Main bot loop — all phases wired."""
    db = Database(DB_PATH)
    db.connect()

    client = BinanceClient()
    alerts = TelegramAlerts()
    state_manager = StateManager(db)
    order_manager = OrderManager(client)
    fetcher = CoinGlassDataFetcher(interval=SIGNAL_INTERVAL, limit=SIGNAL_LOOKBACK)
    engine = SignalEngine()

    telegram_bot = TelegramBot(
        order_manager=order_manager,
        alerts=alerts,
        state_manager=state_manager,
    )

    try:
        await client.initialize()
        await fetcher.initialize()

        balance = await client.get_balance()
        usdt_balance = float(balance.get("USDT", {}).get("free", 0))
        logger.info(f"Connected — USDT balance: {usdt_balance}")

        # Load persisted positions
        db_open = state_manager.get_open_positions()
        paper_open = state_manager.get_open_paper_positions()
        if db_open:
            logger.info(f"Loaded {len(db_open)} live position(s) from DB")
        if paper_open:
            logger.info(f"Loaded {len(paper_open)} paper position(s) from DB")

        if TELEGRAM_BOT_TOKEN:
            await telegram_bot.start()

        mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
        paper = " | PAPER" if PAPER_MODE else ""
        await alerts.send_startup(mode=f"{mode}{paper}", balance=usdt_balance, symbols=SYMBOLS)

        # Start background tasks
        tasks = [
            asyncio.create_task(position_monitor(order_manager, state_manager, alerts)),
            asyncio.create_task(paper_position_monitor(client, state_manager, alerts)),
            asyncio.create_task(signal_loop(fetcher, engine, state_manager, order_manager, alerts, client)),
        ]

        today = state_manager.get_today_stats()
        logger.info(f"RICOZ Bot running — {'PAPER' if PAPER_MODE else 'LIVE'} | {mode}")
        logger.info(f"Symbols: {SYMBOLS}")
        logger.info(f"Live positions: {len(db_open)} | Paper positions: {len(paper_open)}")
        logger.info(f"Today PnL: {today['total_pnl_usdt']:.2f} USDT | Signal loop active")

        await asyncio.gather(*tasks)

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
    if not validate_config():
        logger.error("Config validation failed. Check .env file.")
        return
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("RICOZ Bot stopped by user (Ctrl+C).")


if __name__ == "__main__":
    main()
