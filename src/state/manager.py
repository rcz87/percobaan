"""
RICOZ Bot — State Manager

Phase 2: Track posisi aktif, prevent double entry, enforce risk rules.
Pattern dari Freqtrade: can_enter checks sebelum setiap trade.
"""
from datetime import datetime, timedelta
from loguru import logger

from src.config import MAX_POSITIONS, COOLDOWN_SECS, INITIAL_CAPITAL, MAX_DAILY_LOSS_PCT
from .db import Database


class StateManager:
    """State tracking + risk guard."""

    def __init__(self, db: Database):
        self.db = db
        self.max_positions = MAX_POSITIONS
        self.cooldown_secs = COOLDOWN_SECS
        self.max_daily_drawdown_pct = MAX_DAILY_LOSS_PCT
        self.is_stopped = False  # Kill switch via /stop

    # ── Entry Guard ──────────────────────────────────────

    def can_enter(self, symbol: str) -> tuple[bool, str]:
        """
        Cek apakah boleh entry untuk symbol.
        Returns (allowed, reason).
        """
        # 0. Kill switch
        if self.is_stopped:
            return False, "Bot is STOPPED — /go to resume"

        # 1. Cek posisi aktif di pair ini
        if self.has_open_position(symbol):
            return False, f"Already have open position in {symbol}"

        # 2. Cek max concurrent positions
        open_count = self.count_open_positions()
        if open_count >= self.max_positions:
            return False, f"Max positions ({self.max_positions}) reached — {open_count} open"

        # 3. Cek cooldown (5 menit setelah close)
        if self.is_on_cooldown(symbol):
            return False, f"{symbol} on cooldown"

        # 4. Cek daily drawdown
        drawdown = self.daily_drawdown_pct()
        if drawdown >= self.max_daily_drawdown_pct:
            return False, f"Daily drawdown {drawdown:.1f}% >= limit {self.max_daily_drawdown_pct}%"

        return True, "OK"

    # ── Position Tracking ────────────────────────────────

    def has_open_position(self, symbol: str) -> bool:
        """Cek apakah ada open position di symbol."""
        return self.db.get_open_position_by_symbol(symbol) is not None

    def count_open_positions(self) -> int:
        """Hitung jumlah posisi terbuka."""
        return len(self.db.get_open_positions())

    def is_on_cooldown(self, symbol: str) -> bool:
        """Cek cooldown — 5 menit setelah close."""
        last_close = self.db.get_last_close_time(symbol)
        if last_close is None:
            return False
        last_close_dt = datetime.fromisoformat(last_close)
        elapsed = (datetime.utcnow() - last_close_dt).total_seconds()
        return elapsed < self.cooldown_secs

    # ── Risk Management ──────────────────────────────────

    def daily_drawdown_pct(self) -> float:
        """Calculate daily drawdown sebagai % dari initial capital."""
        today_pnl = self.db.get_today_pnl()
        if today_pnl >= 0:
            return 0.0
        return abs(today_pnl) / INITIAL_CAPITAL * 100

    # ── Record Keeping ───────────────────────────────────

    def record_entry(self, symbol: str, order: dict, score: int, breakdown: dict):
        """Record new entry ke database."""
        position = {
            "id": order["order_id"],
            "symbol": symbol,
            "side": order["side"],
            "entry_price": order["entry_price"],
            "size_usdt": order["amount_usdt"],
            "qty": order["qty"],
            "sl_price": order.get("sl_price"),
            "tp_price": order.get("tp_price"),
            "entry_signal_score": score,
        }
        self.db.insert_position(position)
        logger.info(f"Position recorded: {symbol} {order['side']} @ {order['entry_price']}")

    def record_exit(self, position_id: str, close_price: float,
                    entry_price: float, side: str, qty: float, reason: str):
        """
        Record exit + update PnL.
        Fee-inclusive PnL (Freqtrade pattern).
        """
        fee_rate = 0.0004  # 0.04% taker fee Binance

        if side == "buy":  # long
            pnl_usdt = (close_price - entry_price) * qty * (1 - fee_rate)
        else:  # short
            pnl_usdt = (entry_price - close_price) * qty * (1 - fee_rate)

        pnl_pct = float(f"{(pnl_usdt / (entry_price * qty)) * 100:.8f}")
        pnl_usdt = float(f"{pnl_usdt:.8f}")

        self.db.close_position(position_id, close_price, pnl_usdt, pnl_pct, reason)
        self.db.update_daily_stats(pnl_usdt, is_win=pnl_usdt > 0)

        logger.info(f"Position closed: {position_id} — PnL: {pnl_usdt:+.4f} USDT ({pnl_pct:+.2f}%) — {reason}")

    # ── Kill Switch ──────────────────────────────────────

    def stop(self):
        """Kill switch — block semua entry."""
        self.is_stopped = True
        logger.warning("Bot STOPPED — all entries blocked")

    def go(self):
        """Resume — unblock entry."""
        self.is_stopped = False
        logger.info("Bot RESUMED — entries allowed")
