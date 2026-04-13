"""
RICOZ Bot — Telegram Bot Setup + Command Handlers

Phase 1: Real commands wired to BinanceClient + OrderManager.
- /status — balance + open positions + live PnL
- /stop, /go — kill switch
- /close_all — emergency close
- /test_order — testnet order test (Phase 1 verification)
- /balance — quick balance check
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
        self.is_stopped = False
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

    # ── Core Commands (Phase 1) ──────────────────────────

    @authorized_only
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available commands."""
        mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
        paper = " | PAPER" if PAPER_MODE else ""
        await update.message.reply_text(
            f"RICOZ Order Flow Bot ({mode}{paper})\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "/status — Bot status + positions\n"
            "/balance — Account balance\n"
            "/positions — Open positions detail\n"
            "/test_order — Place test order (testnet)\n"
            "/stop — Pause auto-entry\n"
            "/go — Resume auto-entry\n"
            "/close_all — Emergency close ALL\n"
            "/pnl — PnL summary\n"
            "/history — Last 10 trades\n"
            "/help — Show this help"
        )

    @authorized_only
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status, balance, open positions."""
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        try:
            # Balance
            balance = await self.order_manager.client.get_balance()
            usdt_free = float(balance.get("USDT", {}).get("free", 0))
            usdt_used = float(balance.get("USDT", {}).get("used", 0))
            usdt_total = usdt_free + usdt_used

            # Positions
            positions = await self.order_manager.get_positions_summary()

            mode = "TESTNET" if BINANCE_TESTNET else "LIVE"
            paper = " | PAPER" if PAPER_MODE else ""
            stopped = " | STOPPED" if self.is_stopped else ""

            msg = (
                f"RICOZ Bot Status\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Mode: {mode}{paper}{stopped}\n"
                f"Balance: {usdt_total:.2f} USDT\n"
                f"  Free: {usdt_free:.2f}\n"
                f"  In use: {usdt_used:.2f}\n"
                f"Open positions: {len(positions)}\n"
            )

            if positions:
                msg += "━━━━━━━━━━━━━━━━━━━\n"
                for p in positions:
                    emoji = "+" if p["pnl_pct"] >= 0 else ""
                    msg += (
                        f"{p['symbol']} {p['side'].upper()}\n"
                        f"  Entry: {p['entry_price']:.4f}\n"
                        f"  Mark: {p['mark_price']:.4f}\n"
                        f"  PnL: {emoji}{p['pnl_pct']:.2f}% ({p['unrealized_pnl']:+.4f} USDT)\n"
                    )

            await update.message.reply_text(msg)

        except Exception as e:
            logger.error(f"/status error: {e}")
            await update.message.reply_text(f"Error: {e}")

    @authorized_only
    async def _cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Quick balance check."""
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        try:
            balance = await self.order_manager.client.get_balance()
            usdt = balance.get("USDT", {})
            msg = (
                f"Account Balance\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"USDT Free:  {float(usdt.get('free', 0)):.2f}\n"
                f"USDT Used:  {float(usdt.get('used', 0)):.2f}\n"
                f"USDT Total: {float(usdt.get('total', 0)):.2f}"
            )
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    @authorized_only
    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detail open positions with live PnL."""
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
                emoji = "+" if p["pnl_pct"] >= 0 else ""
                msg += (
                    f"\n{p['symbol']} — {p['side'].upper()}\n"
                    f"  Entry:     {p['entry_price']:.4f}\n"
                    f"  Mark:      {p['mark_price']:.4f}\n"
                    f"  Contracts: {p['contracts']}\n"
                    f"  PnL:       {emoji}{p['pnl_pct']:.2f}% ({p['unrealized_pnl']:+.4f} USDT)\n"
                )

            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    # ── Kill Switch ──────────────────────────────────────

    @authorized_only
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kill switch — block semua entry baru."""
        self.is_stopped = True
        if self.state_manager:
            self.state_manager.stop()
        logger.warning("Bot STOPPED via Telegram /stop")
        await update.message.reply_text(
            "Bot STOPPED\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Semua auto-entry diblock.\n"
            "Open positions tetap dimonitor.\n"
            "/go untuk resume."
        )
        if self.alerts:
            await self.alerts.send_kill_switch("stop")

    @authorized_only
    async def _cmd_go(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume — unblock entry."""
        self.is_stopped = False
        if self.state_manager:
            self.state_manager.go()
        logger.info("Bot RESUMED via Telegram /go")
        await update.message.reply_text(
            "Bot RESUMED\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Auto-entry aktif kembali."
        )
        if self.alerts:
            await self.alerts.send_kill_switch("go")

    # ── Emergency Close ──────────────────────────────────

    @authorized_only
    async def _cmd_close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Emergency close ALL open positions."""
        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        await update.message.reply_text("Closing ALL positions...")

        try:
            closed = await self.order_manager.close_all_positions()

            if not closed:
                await update.message.reply_text("No open positions to close.")
                return

            msg = f"Closed {len(closed)} position(s)\n━━━━━━━━━━━━━━━━━━━\n"
            for c in closed:
                msg += f"  {c['symbol']}\n"

            await update.message.reply_text(msg)

            if self.alerts:
                await self.alerts.send_status(f"Emergency close: {len(closed)} positions closed")

        except Exception as e:
            logger.error(f"/close_all error: {e}")
            await update.message.reply_text(f"Error: {e}")

    # ── Test Order (Phase 1 Verification) ────────────────

    @authorized_only
    async def _cmd_test_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Phase 1 test: Place small order on testnet → set SL/TP → report.
        Usage: /test_order [symbol] [side] [usdt]
        Default: /test_order SOL/USDT:USDT buy 5
        """
        if not BINANCE_TESTNET:
            await update.message.reply_text("test_order hanya untuk TESTNET mode.")
            return

        if not self.order_manager:
            await update.message.reply_text("OrderManager not initialized.")
            return

        # Parse args
        args = context.args or []
        symbol = args[0] if len(args) > 0 else "SOL/USDT:USDT"
        side = args[1] if len(args) > 1 else "buy"
        amount_usdt = float(args[2]) if len(args) > 2 else 5.0

        await update.message.reply_text(
            f"Placing test order...\n"
            f"  Symbol: {symbol}\n"
            f"  Side: {side}\n"
            f"  Amount: {amount_usdt} USDT"
        )

        try:
            result = await self.order_manager.execute_entry(symbol, side, amount_usdt)

            if result["status"] == "cancelled":
                await update.message.reply_text("Order cancelled — zero fill.")
                return

            msg = (
                f"Test Order SUCCESS\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol:  {result['ccxt_symbol']}\n"
                f"Side:    {result['side'].upper()}\n"
                f"Entry:   {result['entry_price']:.4f}\n"
                f"Qty:     {result['qty']}\n"
                f"SL:      {result['sl_price']:.4f}\n"
                f"TP:      {result['tp_price']:.4f}\n"
                f"Order:   {result['order_id']}"
            )
            await update.message.reply_text(msg)

            # Send alert via alerts channel too
            if self.alerts:
                await self.alerts.send_entry(symbol, side, result["entry_price"], amount_usdt, 100)

        except Exception as e:
            error_msg = f"Test order FAILED: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            await update.message.reply_text(error_msg)

            if self.alerts:
                await self.alerts.send_error(error_msg)

    # ── Placeholder Commands (Phase 2+) ──────────────────

    @authorized_only
    async def _cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """PnL summary — Phase 2."""
        await update.message.reply_text(
            "PnL Summary\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Akan tersedia di Phase 2 (State Manager)."
        )

    @authorized_only
    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trade history — Phase 2."""
        await update.message.reply_text(
            "Trade History\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Akan tersedia di Phase 2 (State Manager)."
        )
