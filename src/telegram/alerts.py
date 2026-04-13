"""
RICOZ Bot — Telegram Alert Notifications

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

    async def _send(self, message: str):
        """Send message wrapper dengan error handling."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def send_entry(self, symbol: str, side: str, price: float,
                         size_usdt: float, score: int):
        """Entry notification."""
        emoji = "\U0001f7e2" if side == "buy" else "\U0001f534"  # green / red circle
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
        if pnl_usdt > 0:
            emoji = "\u2705"  # check mark
        else:
            emoji = "\u274c"  # cross mark
        msg = (
            f"{emoji} *EXIT \u2014 {reason}*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f4e6 `{symbol}`\n"
            f"\U0001f4b5 PnL: `{pnl_usdt:+.2f} USDT ({pnl_pct:+.2f}%)`"
        )
        await self._send(msg)

    async def send_error(self, error_msg: str):
        """Error alert."""
        msg = f"\U0001f6a8 *ERROR*\n`{error_msg}`"
        await self._send(msg)

    async def send_status(self, status_text: str):
        """Generic status message."""
        msg = f"\U00002139 *STATUS*\n{status_text}"
        await self._send(msg)

    async def send_kill_switch(self, action: str):
        """Kill switch notification."""
        if action == "stop":
            msg = "\U0001f6d1 *BOT STOPPED*\nSemua auto-entry diblock.\n`/go` untuk resume."
        else:
            msg = "\u2705 *BOT RESUMED*\nAuto-entry aktif kembali."
        await self._send(msg)
