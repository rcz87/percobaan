"""
RICOZ Bot — Telegram Bot Setup + Command Handlers

Pattern dari Freqtrade telegram.py:
- Handler registration sebagai flat list
- @authorized_only decorator
- 3-level kill switch: /stop, /go, /close_all
"""
import functools

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from loguru import logger

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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

    def __init__(self, state_manager=None, order_manager=None):
        self.state_manager = state_manager
        self.order_manager = order_manager
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self._register_handlers()

    def _register_handlers(self):
        """Register semua command handlers."""
        handlers = [
            CommandHandler("status", self._cmd_status),
            CommandHandler("stop", self._cmd_stop),
            CommandHandler("go", self._cmd_go),
            CommandHandler("close_all", self._cmd_close_all),
            CommandHandler("positions", self._cmd_positions),
            CommandHandler("pnl", self._cmd_pnl),
            CommandHandler("history", self._cmd_history),
            CommandHandler("help", self._cmd_help),
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

    # ── Commands ─────────────────────────────────────────

    @authorized_only
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status, open positions, daily PnL."""
        # TODO Phase 2: Implement with state_manager
        await update.message.reply_text(
            "RICOZ Bot Status\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Status: Running\n"
            "Mode: PAPER\n"
            "Open positions: 0\n"
            "Daily PnL: $0.00"
        )

    @authorized_only
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kill switch — block semua entry baru."""
        if self.state_manager:
            self.state_manager.stop()
        await update.message.reply_text("Bot STOPPED — semua auto-entry diblock.\n/go untuk resume.")

    @authorized_only
    async def _cmd_go(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume — unblock entry."""
        if self.state_manager:
            self.state_manager.go()
        await update.message.reply_text("Bot RESUMED — auto-entry aktif kembali.")

    @authorized_only
    async def _cmd_close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Emergency close semua posisi."""
        # TODO Phase 1+2: Implement with order_manager + state_manager
        await update.message.reply_text("Emergency close ALL positions triggered.")

    @authorized_only
    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detail setiap open position."""
        # TODO Phase 2: Implement with state_manager
        await update.message.reply_text("No open positions.")

    @authorized_only
    async def _cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Daily/weekly PnL summary."""
        # TODO Phase 2: Implement with state_manager
        await update.message.reply_text("PnL Summary\n━━━━━━━━━━━━━━━━━━━\nToday: $0.00")

    @authorized_only
    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Last 10 trades."""
        # TODO Phase 2: Implement with state_manager
        await update.message.reply_text("No trade history yet.")

    @authorized_only
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available commands."""
        await update.message.reply_text(
            "RICOZ Bot Commands\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "/status — Bot status + daily PnL\n"
            "/stop — Pause semua auto-entry\n"
            "/go — Resume auto-entry\n"
            "/close_all — Emergency close all\n"
            "/positions — Detail open positions\n"
            "/pnl — PnL summary\n"
            "/history — Last 10 trades\n"
            "/help — Show this help"
        )
