"""
RICOZ Bot — Telegram Bot Setup + Command Handlers

Phase 2: All commands wired to StateManager + DB.
/status, /pnl, /history now show real data.
/test_order records entry in DB.
"""
import functools
import traceback

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from loguru import logger

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_MODE, BINANCE_TESTNET


def authorized_only(func):
    """Decorator — hanya TELEGRAM_CHAT_ID yang boleh akses."""
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != TELEGRAM_CHAT_ID:
            logger.warning(f"Unauthorized access attempt: {update.effective_chat.id}")
            return
        return await func(self, update, context)
    return wrapper


class TelegramBot:
    """Telegram command handler + control layer."""

    def __init__(self, order_manager=None, alerts=None, state_manager=None):
        self.order_manager = order_manager
        self.alerts = alerts
        self.state_manager = state_manager
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self._register_handlers()

    def _register_handlers(self):
        """Register semua command handlers."""
        handlers = [
            CommandHandler("start", self._cmd_help),
            CommandHandler("help", self._cmd_help),
            CommandHandler("status", self._cmd_status),
            CommandHandler("balance", self._cmd_balance),
            CommandHandler("positions", self._cmd_positions),
            CommandHandler("stop", self._cmd_stop),
            CommandHandler("go", self._cmd_go),
            CommandHandler("close_all", self._cmd_close_all),
            CommandHandler("test_order", self._cmd_test_order),
            CommandHandler("pnl", self._cmd_pnl),
            CommandHandler("history", self._cmd_history),
            CommandHandler(["score", "stats"], self._cmd_stats),
            CommandHandler("paper", self._cmd_paper),
        ]
        for handler in handlers:
            self.app.add_handler(handler)

    async def start(self):
        """Start polling."""
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram bot started polling")

    async def stop(self):
        """Stop polling."""
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # ── Help ─────────────────────────────────────────────

    @authorized_only
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
        paper = " | PAPER" if PAPER_MODE else ""
        await update.message.reply_text(
            f"RICOZ Order Flow Bot ({mode}{paper})\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "/status — Bot status + positions\n"
            "/balance — Account balance\n"
            "/positions — Open positions detail\n"
            "/pnl — Daily/weekly PnL\n"
            "/stats — All-time stats + edge\n"
            "/paper — Paper trading stats\n"
            "/history — Last 10 trades\n"
            "/test_order — Place test order\n"
            "/stop — Pause auto-entry\n"
            "/go — Resume auto-entry\n"
            "/close_all — Emergency close ALL\n"
            "/help — Show this help"
        )

    # ── Status (Phase 2: with DB data) ───────────────────

    @authorized_only
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        try:
            balance = await self.order_manager.client.get_balance()
            usdt_free = float(balance.get("USDT", {}).get("free", 0))
            usdt_used = float(balance.get("USDT", {}).get("used", 0))
            usdt_total = usdt_free + usdt_used

            positions = await self.order_manager.get_positions_summary()

            mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
            paper = " | PAPER" if PAPER_MODE else ""
            stopped = ""
            if self.state_manager and self.state_manager.is_stopped:
                stopped = " | STOPPED"

            # DB stats
            today = self.state_manager.get_today_stats() if self.state_manager else {}
            drawdown = self.state_manager.daily_drawdown_pct() if self.state_manager else 0

            msg = (
                f"RICOZ Bot Status\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Mode: {mode}{paper}{stopped}\n"
                f"Balance: {usdt_total:.2f} USDT (free: {usdt_free:.2f})\n"
                f"Open: {len(positions)} position(s)\n"
                f"Today: {today.get('total_pnl_usdt', 0):+.2f} USDT | "
                f"{today.get('trades_count', 0)} trades | "
                f"W{today.get('wins', 0)}/L{today.get('losses', 0)}\n"
                f"Drawdown: {drawdown:.1f}%\n"
            )

            if positions:
                msg += "━━━━━━━━━━━━━━━━━━━\n"
                for p in positions:
                    sign = "+" if p["pnl_pct"] >= 0 else ""
                    msg += (
                        f"{p['symbol']} {p['side'].upper()}\n"
                        f"  {p['entry_price']:.4f} -> {p['mark_price']:.4f} "
                        f"({sign}{p['pnl_pct']:.2f}%)\n"
                    )

            await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"/status error: {e}")
            await update.message.reply_text(f"Error: {e}")

    @authorized_only
    async def _cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return
        try:
            balance = await self.order_manager.client.get_balance()
            usdt = balance.get("USDT", {})
            await update.message.reply_text(
                f"Account Balance\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Free:  {float(usdt.get('free', 0)):.2f} USDT\n"
                f"Used:  {float(usdt.get('used', 0)):.2f} USDT\n"
                f"Total: {float(usdt.get('total', 0)):.2f} USDT"
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    @authorized_only
    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return
        try:
            positions = await self.order_manager.get_positions_summary()
            if not positions:
                await update.message.reply_text("No open positions.")
                return

            msg = f"Open Positions ({len(positions)})\n━━━━━━━━━━━━━━━━━━━\n"
            for p in positions:
                sign = "+" if p["pnl_pct"] >= 0 else ""
                msg += (
                    f"\n{p['symbol']} — {p['side'].upper()}\n"
                    f"  Entry:     {p['entry_price']:.4f}\n"
                    f"  Mark:      {p['mark_price']:.4f}\n"
                    f"  Contracts: {p['contracts']}\n"
                    f"  PnL: {sign}{p['pnl_pct']:.2f}% ({p['unrealized_pnl']:+.4f} USDT)\n"
                )
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    # ── PnL + Stats (Phase 2) ────────────────────────────

    @authorized_only
    async def _cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Daily + weekly PnL summary."""
        if not self.state_manager:
            await update.message.reply_text("StateManager not initialized.")
            return

        today = self.state_manager.get_today_stats()
        weekly = self.state_manager.get_weekly_stats()
        by_symbol = self.state_manager.get_pnl_by_symbol()

        msg = (
            f"PnL Summary\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Today:\n"
            f"  PnL: {today['total_pnl_usdt']:+.2f} USDT\n"
            f"  Trades: {today['trades_count']} (W{today['wins']}/L{today['losses']})\n"
            f"\n7 Days:\n"
            f"  PnL: {weekly['total_pnl']:+.2f} USDT\n"
            f"  Trades: {weekly['total_trades']} (W{weekly['total_wins']}/L{weekly['total_losses']})\n"
            f"  Win rate: {weekly['win_rate']:.1f}%\n"
        )

        if by_symbol:
            msg += "\nPer Symbol:\n"
            for s in by_symbol:
                msg += f"  {s['symbol']}: {s['total_pnl']:+.2f} ({s['trades']} trades, W{s['wins']})\n"

        await update.message.reply_text(msg)

    @authorized_only
    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """All-time stats with edge metrics."""
        if not self.state_manager:
            await update.message.reply_text("StateManager not initialized.")
            return

        stats = self.state_manager.get_all_time_stats()

        if stats["total_trades"] == 0:
            await update.message.reply_text("No trades yet.")
            return

        msg = (
            f"All-Time Stats\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Total trades: {stats['total_trades']}\n"
            f"Win/Loss: {stats['wins']}W / {stats['losses']}L\n"
            f"Win rate: {stats['win_rate']:.1f}%\n"
            f"Total PnL: {stats['total_pnl']:+.2f} USDT\n"
            f"\nEdge Metrics:\n"
            f"  Avg win:  {stats['avg_win']:.4f} USDT\n"
            f"  Avg loss: {stats['avg_loss']:.4f} USDT\n"
            f"  R:R ratio: {stats['rr_ratio']:.2f}\n"
            f"  Expectancy: {stats['expectancy']:+.3f}\n"
            f"\nBest:  {stats['best_trade']:+.4f} USDT\n"
            f"Worst: {stats['worst_trade']:+.4f} USDT"
        )

        await update.message.reply_text(msg)

    @authorized_only
    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Last 10 trades from DB."""
        if not self.state_manager:
            await update.message.reply_text("StateManager not initialized.")
            return

        trades = self.state_manager.get_trade_history(10)
        if not trades:
            await update.message.reply_text("No trade history yet.")
            return

        msg = f"Last {len(trades)} Trades\n━━━━━━━━━━━━━━━━━━━\n"
        for t in trades:
            pnl = t.get("pnl_usdt", 0) or 0
            pnl_pct = t.get("pnl_pct", 0) or 0
            sign = "+" if pnl >= 0 else ""
            reason = t.get("close_reason", "?")
            closed = (t.get("closed_at") or "")[:16]  # trim seconds
            msg += (
                f"\n{t['symbol']} {t['side'].upper()} [{reason}]\n"
                f"  {t['entry_price']:.4f} -> {t.get('close_price', 0):.4f}\n"
                f"  PnL: {sign}{pnl:.4f} USDT ({sign}{pnl_pct:.2f}%)\n"
                f"  {closed}\n"
            )

        await update.message.reply_text(msg)

    # ── Paper Trading Stats ────────────────────────────

    @authorized_only
    async def _cmd_paper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Paper trading stats + open positions."""
        if not self.state_manager:
            await update.message.reply_text("StateManager not initialized.")
            return

        stats = self.state_manager.get_paper_stats()
        open_paper = self.state_manager.get_open_paper_positions()

        msg = (
            f"Paper Trading\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Open: {len(open_paper)} position(s)\n"
            f"Closed: {stats['total_trades']} trades\n"
            f"Win/Loss: {stats['wins']}W / {stats['losses']}L\n"
            f"Win rate: {stats['win_rate']:.1f}%\n"
            f"PnL: {stats['total_pnl']:+.2f} USDT\n"
        )

        if stats["total_trades"] > 0:
            msg += (
                f"\nEdge:\n"
                f"  R:R: {stats['rr_ratio']:.2f}\n"
                f"  Expectancy: {stats['expectancy']:+.3f}\n"
                f"  Best: {stats['best_trade']:+.4f}\n"
                f"  Worst: {stats['worst_trade']:+.4f}\n"
            )

        if open_paper:
            msg += "\nOpen Paper Positions:\n"
            for p in open_paper[:5]:
                msg += (
                    f"  {p['symbol']} {p['side'].upper()} "
                    f"@ {p['entry_price']:.4f} "
                    f"(SL:{p.get('sl_price', 0):.4f} TP:{p.get('tp_price', 0):.4f})\n"
                )

        await update.message.reply_text(msg)

    # ── Kill Switch ──────────────────────────────────────

    @authorized_only
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.state_manager:
            self.state_manager.stop()
        logger.warning("Bot STOPPED via Telegram /stop")
        await update.message.reply_text(
            "Bot STOPPED\n━━━━━━━━━━━━━━━━━━━\n"
            "Semua auto-entry diblock.\n"
            "Open positions tetap dimonitor.\n/go untuk resume."
        )
        if self.alerts:
            await self.alerts.send_kill_switch("stop")

    @authorized_only
    async def _cmd_go(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.state_manager:
            self.state_manager.go()
        logger.info("Bot RESUMED via Telegram /go")
        await update.message.reply_text(
            "Bot RESUMED\n━━━━━━━━━━━━━━━━━━━\nAuto-entry aktif kembali."
        )
        if self.alerts:
            await self.alerts.send_kill_switch("go")

    # ── Emergency Close ──────────────────────────────────

    @authorized_only
    async def _cmd_close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        await update.message.reply_text("Closing ALL positions...")

        try:
            closed = await self.order_manager.close_all_positions()

            if not closed:
                await update.message.reply_text("No open positions to close.")
                return

            # Record exits in DB
            for c in closed:
                symbol = c["symbol"]
                if self.state_manager:
                    try:
                        close_price = await self.order_manager.client.get_price(symbol)
                        self.state_manager.record_exit_by_symbol(symbol, close_price, "Manual")
                    except Exception as e:
                        logger.error(f"Failed to record exit for {symbol}: {e}")

            msg = f"Closed {len(closed)} position(s)\n━━━━━━━━━━━━━━━━━━━\n"
            for c in closed:
                msg += f"  {c['symbol']}\n"
            await update.message.reply_text(msg)

            if self.alerts:
                await self.alerts.send_status(f"Emergency close: {len(closed)} positions closed")
        except Exception as e:
            logger.error(f"/close_all error: {e}")
            await update.message.reply_text(f"Error: {e}")

    # ── Test Order ───────────────────────────────────────

    @authorized_only
    async def _cmd_test_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Place test order + record in DB."""
        if not BINANCE_TESTNET:
            await update.message.reply_text("test_order hanya untuk TESTNET.")
            return
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        # Check state_manager guards
        args = context.args or []
        symbol = args[0] if len(args) > 0 else "SOL/USDT:USDT"
        side = args[1] if len(args) > 1 else "buy"
        amount_usdt = float(args[2]) if len(args) > 2 else 5.0

        if self.state_manager:
            can, reason = self.state_manager.can_enter(symbol)
            if not can:
                await update.message.reply_text(f"Entry BLOCKED: {reason}")
                return

        await update.message.reply_text(
            f"Placing order: {symbol} {side.upper()} {amount_usdt} USDT..."
        )

        try:
            result = await self.order_manager.execute_entry(symbol, side, amount_usdt)

            if result["status"] == "cancelled":
                await update.message.reply_text("Order cancelled — zero fill.")
                return

            # Record in DB
            if self.state_manager:
                self.state_manager.record_entry(result, score=100)

            msg = (
                f"Order SUCCESS\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol:  {result['ccxt_symbol']}\n"
                f"Side:    {result['side'].upper()}\n"
                f"Entry:   {result['entry_price']:.4f}\n"
                f"Qty:     {result['qty']}\n"
                f"SL:      {result['sl_price']:.4f}\n"
                f"TP:      {result['tp_price']:.4f}"
            )
            await update.message.reply_text(msg)

            if self.alerts:
                await self.alerts.send_entry(
                    symbol, side, result["entry_price"], amount_usdt, 100
                )
        except Exception as e:
            error_msg = f"Order FAILED: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            await update.message.reply_text(error_msg)
            if self.alerts:
                await self.alerts.send_error(error_msg)
