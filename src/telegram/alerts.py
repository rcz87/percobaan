"""
RICOZ Bot — Telegram Alert Notifications

Phase 1: Entry, exit, error, status, kill switch alerts.
Pattern dari Freqtrade: message type routing + emoji berdasarkan profit.
"""
from telegram import Bot
from loguru import logger

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramAlerts:
    """Send trading alerts via Telegram."""

    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.chat_id = TELEGRAM_CHAT_ID
        self._enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

    async def _send(self, message: str):
        """Send message wrapper dengan error handling."""
        if not self._enabled:
            logger.debug(f"Telegram disabled, skipping: {message[:50]}...")
            return

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    # ── Trading Alerts ───────────────────────────────────

    async def send_entry(self, symbol: str, side: str, price: float,
                         size_usdt: float, score: int):
        """Entry notification."""
        emoji = "\U0001f7e2" if side == "buy" else "\U0001f534"
        msg = (
            f"{emoji} *ENTRY {side.upper()}*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f4e6 Pair: `{symbol}`\n"
            f"\U0001f4b0 Price: `{price:.4f}`\n"
            f"\U0001f4ca Size: `{size_usdt} USDT`\n"
            f"\U0001f3af Score: `{score}/100`"
        )
        await self._send(msg)

    async def send_exit(self, symbol: str, pnl_usdt: float,
                        pnl_pct: float, reason: str):
        """Exit notification dengan PnL."""
        if pnl_pct >= 5.0:
            emoji = "\U0001f680"  # rocket
        elif pnl_usdt > 0:
            emoji = "\u2705"  # check mark
        elif reason == "SL":
            emoji = "\u26a0\ufe0f"  # warning
        else:
            emoji = "\u274c"  # cross mark
        msg = (
            f"{emoji} *EXIT \u2014 {reason}*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f4e6 `{symbol}`\n"
            f"\U0001f4b5 PnL: `{pnl_usdt:+.2f} USDT ({pnl_pct:+.2f}%)`"
        )
        await self._send(msg)

    # ── System Alerts ────────────────────────────────────

    async def send_error(self, error_msg: str):
        """Error alert."""
        # Escape markdown special chars in error message
        safe_msg = error_msg.replace("`", "'").replace("*", "").replace("_", "")
        msg = f"\U0001f6a8 *ERROR*\n`{safe_msg[:500]}`"
        await self._send(msg)

    async def send_status(self, status_text: str):
        """Generic status message."""
        msg = f"\u2139\ufe0f *STATUS*\n{status_text}"
        await self._send(msg)

    async def send_kill_switch(self, action: str):
        """Kill switch notification."""
        if action == "stop":
            msg = "\U0001f6d1 *BOT STOPPED*\nSemua auto-entry diblock.\n`/go` untuk resume."
        else:
            msg = "\u2705 *BOT RESUMED*\nAuto-entry aktif kembali."
        await self._send(msg)

    async def send_startup(self, mode: str, balance: float, symbols: list[str]):
        """Bot startup notification."""
        symbols_str = ", ".join(symbols)
        msg = (
            f"\U0001f680 *RICOZ Bot Started*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Mode: `{mode}`\n"
            f"Balance: `{balance:.2f} USDT`\n"
            f"Symbols: `{symbols_str}`\n"
            f"\n/help untuk commands"
        )
        await self._send(msg)

    async def send_shutdown(self, reason: str = "Manual"):
        """Bot shutdown notification."""
        msg = (
            f"\U0001f534 *RICOZ Bot Stopped*\n"
            f"Reason: `{reason}`"
        )
        await self._send(msg)
