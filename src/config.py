"""
RICOZ Bot — Configuration loader dari .env
"""
import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


# ── Binance ──────────────────────────────────────────────
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

# ── Telegram ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Trading Config ───────────────────────────────────────
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
AUTO_BUY_AMOUNT_USDT = float(os.getenv("AUTO_BUY_AMOUNT_USDT", "5"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "75"))
SL_PCT = float(os.getenv("SL_PCT", "0.015"))
TP_PCT = float(os.getenv("TP_PCT", "0.030"))
COOLDOWN_SECS = int(os.getenv("COOLDOWN_SECS", "300"))

# ── Risk ─────────────────────────────────────────────────
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "500"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0"))

# ── Database ─────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "./data/ricoz_bot.db")

# ── CoinGlass / McPCG ───────────────────────────────────
MCPCG_URL = os.getenv("MCPCG_URL", "https://mcp.guardiansofthetoken.org/mcp")

# ── Symbols ──────────────────────────────────────────────
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "SOL/USDT:USDT,AVAX/USDT:USDT,SUI/USDT:USDT").split(",")]

# ── Size multiplier berdasarkan score ────────────────────
SIZE_MULTIPLIER = {
    "ENTRY_FULL": 1.0,
    "ENTRY_75": 0.75,
    "ENTRY_50": 0.5,
}


def validate_config():
    """Validasi config minimum untuk bisa jalan."""
    errors = []

    if not BINANCE_API_KEY:
        errors.append("BINANCE_API_KEY not set")
    if not BINANCE_SECRET:
        errors.append("BINANCE_SECRET not set")
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN not set")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID not set")

    if errors:
        for e in errors:
            logger.error(f"Config error: {e}")
        return False

    logger.info(f"Config loaded — {'TESTNET' if BINANCE_TESTNET else 'LIVE'} | "
                f"{'PAPER' if PAPER_MODE else 'REAL'} | "
                f"Symbols: {SYMBOLS}")
    return True
