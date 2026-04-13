"""
RICOZ Bot — State Manager

Phase 2: Track posisi, prevent double entry, enforce risk rules, record PnL.
Pattern dari Freqtrade: can_enter checks + fee-inclusive PnL.
"""
from datetime import datetime
from loguru import logger

from src.config import MAX_POSITIONS, COOLDOWN_SECS, INITIAL_CAPITAL, MAX_DAILY_LOSS_PCT
from .db import Database


FEE_RATE = 0.0004  # 0.04% taker fee Binance


class StateManager:
    """State tracking + risk guard + PnL recording."""

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

    def get_open_positions(self) -> list:
        """Get semua open positions dari DB."""
        return self.db.get_open_positions()

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

    # ── Record Entry ─────────────────────────────────────

    def record_entry(self, order_result: dict, score: int = 0):
        """
        Record new entry ke database.
        order_result = dict from OrderManager.execute_entry()
        """
        position = {
            "id": order_result["order_id"],
            "symbol": order_result["ccxt_symbol"],
            "side": order_result["side"],
            "entry_price": order_result["entry_price"],
            "size_usdt": order_result["amount_usdt"],
            "qty": order_result["qty"],
            "sl_price": order_result.get("sl_price"),
            "tp_price": order_result.get("tp_price"),
            "entry_signal_score": score,
        }
        self.db.insert_position(position)
        logger.info(
            f"State: Entry recorded — {position['symbol']} "
            f"{position['side']} @ {position['entry_price']:.4f}"
        )

    # ── Record Exit ──────────────────────────────────────

    def record_exit(self, position_id: str, close_price: float, reason: str):
        """
        Record exit + calculate fee-inclusive PnL.
        Looks up position from DB by ID.
        """
        position = self.db.get_position_by_id(position_id)
        if not position:
            logger.error(f"State: Position {position_id} not found in DB")
            return None

        entry_price = position["entry_price"]
        qty = position["qty"]
        side = position["side"]

        # Fee-inclusive PnL (Freqtrade pattern)
        if side == "buy":  # long
            pnl_usdt = (close_price - entry_price) * qty * (1 - FEE_RATE)
        else:  # short
            pnl_usdt = (entry_price - close_price) * qty * (1 - FEE_RATE)

        pnl_pct = float(f"{(pnl_usdt / (entry_price * qty)) * 100:.8f}")
        pnl_usdt = float(f"{pnl_usdt:.8f}")

        # Update DB
        self.db.close_position(position_id, close_price, pnl_usdt, pnl_pct, reason)
        self.db.update_daily_stats(pnl_usdt, is_win=pnl_usdt > 0)

        logger.info(
            f"State: Exit recorded — {position['symbol']} "
            f"PnL: {pnl_usdt:+.4f} USDT ({pnl_pct:+.2f}%) — {reason}"
        )

        return {
            "position_id": position_id,
            "symbol": position["symbol"],
            "side": side,
            "entry_price": entry_price,
            "close_price": close_price,
            "qty": qty,
            "pnl_usdt": pnl_usdt,
            "pnl_pct": pnl_pct,
            "reason": reason,
        }

    def record_exit_by_symbol(self, symbol: str, close_price: float, reason: str):
        """Record exit by looking up open position for symbol."""
        position = self.db.get_open_position_by_symbol(symbol)
        if not position:
            logger.warning(f"State: No open position found for {symbol}")
            return None
        return self.record_exit(position["id"], close_price, reason)

    # ── Stats ────────────────────────────────────────────

    def get_today_stats(self) -> dict:
        """Get today's trading stats."""
        return self.db.get_today_stats()

    def get_weekly_stats(self) -> dict:
        """Get 7-day stats."""
        return self.db.get_weekly_stats()

    def get_all_time_stats(self) -> dict:
        """Get all-time stats with win rate, RR, expectancy."""
        return self.db.get_all_time_stats()

    def get_pnl_by_symbol(self) -> list:
        """Get PnL per symbol."""
        return self.db.get_pnl_by_symbol()

    def get_trade_history(self, limit: int = 10) -> list:
        """Get last N trades."""
        return self.db.get_trade_history(limit)

    # ── Kill Switch ──────────────────────────────────────

    def stop(self):
        """Kill switch — block semua entry."""
        self.is_stopped = True
        logger.warning("Bot STOPPED — all entries blocked")

    def go(self):
        """Resume — unblock entry."""
        self.is_stopped = False
        logger.info("Bot RESUMED — entries allowed")
