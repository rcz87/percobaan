"""
RICOZ Bot — Database Layer (SQLite)

Phase 2: Schema + CRUD + Stats.
Pattern dari Freqtrade persistence/models.py.
"""
import os
import sqlite3
from datetime import datetime
from loguru import logger


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size_usdt REAL NOT NULL,
    qty REAL NOT NULL,
    sl_price REAL,
    tp_price REAL,
    entry_signal_score INTEGER,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    close_price REAL,
    pnl_usdt REAL,
    pnl_pct REAL,
    close_reason TEXT,
    status TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    total_pnl_usdt REAL DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_opened_at ON positions(opened_at);
"""


class Database:
    """SQLite database layer."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Initialize DB connection + create tables."""
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(DB_SCHEMA)
        self.conn.commit()
        logger.info(f"Database connected: {self.db_path}")

    def close(self):
        """Close DB connection."""
        if self.conn:
            self.conn.close()

    # ── Positions CRUD ───────────────────────────────────

    def insert_position(self, position: dict):
        """Insert new open position."""
        self.conn.execute(
            """INSERT INTO positions
               (id, symbol, side, entry_price, size_usdt, qty,
                sl_price, tp_price, entry_signal_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                position["id"],
                position["symbol"],
                position["side"],
                position["entry_price"],
                position["size_usdt"],
                position["qty"],
                position.get("sl_price"),
                position.get("tp_price"),
                position.get("entry_signal_score"),
            ),
        )
        self.conn.commit()
        logger.info(f"DB: Position inserted — {position['symbol']} {position['side']}")

    def close_position(self, position_id: str, close_price: float,
                       pnl_usdt: float, pnl_pct: float, reason: str):
        """Close position dengan PnL info."""
        self.conn.execute(
            """UPDATE positions
               SET status = 'closed', closed_at = ?, close_price = ?,
                   pnl_usdt = ?, pnl_pct = ?, close_reason = ?
               WHERE id = ?""",
            (datetime.utcnow().isoformat(), close_price, pnl_usdt,
             pnl_pct, reason, position_id),
        )
        self.conn.commit()
        logger.info(f"DB: Position closed — {position_id} reason={reason}")

    def get_open_positions(self) -> list:
        """Get semua posisi open."""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_open_position_by_symbol(self, symbol: str) -> dict | None:
        """Get open position untuk specific symbol."""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE status = 'open' AND symbol = ?",
            (symbol,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_position_by_id(self, position_id: str) -> dict | None:
        """Get position by ID."""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_last_close_time(self, symbol: str) -> str | None:
        """Get timestamp posisi terakhir yang ditutup untuk symbol."""
        cursor = self.conn.execute(
            """SELECT closed_at FROM positions
               WHERE symbol = ? AND status = 'closed'
               ORDER BY closed_at DESC LIMIT 1""",
            (symbol,),
        )
        row = cursor.fetchone()
        return row["closed_at"] if row else None

    # ── Daily Stats ──────────────────────────────────────

    def get_today_pnl(self) -> float:
        """Get total PnL hari ini."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            "SELECT total_pnl_usdt FROM daily_stats WHERE date = ?",
            (today,),
        )
        row = cursor.fetchone()
        return row["total_pnl_usdt"] if row else 0.0

    def get_today_stats(self) -> dict:
        """Get full daily stats hari ini."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            "SELECT * FROM daily_stats WHERE date = ?", (today,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {"date": today, "total_pnl_usdt": 0.0, "trades_count": 0, "wins": 0, "losses": 0}

    def update_daily_stats(self, pnl_usdt: float, is_win: bool):
        """Update daily stats setelah close position."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        self.conn.execute(
            """INSERT INTO daily_stats (date, total_pnl_usdt, trades_count, wins, losses)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               total_pnl_usdt = total_pnl_usdt + ?,
               trades_count = trades_count + 1,
               wins = wins + ?,
               losses = losses + ?""",
            (today, pnl_usdt, 1 if is_win else 0, 0 if is_win else 1,
             pnl_usdt, 1 if is_win else 0, 0 if is_win else 1),
        )
        self.conn.commit()

    # ── Trade History + Analytics ─────────────────────────

    def get_trade_history(self, limit: int = 10) -> list:
        """Get last N closed trades."""
        cursor = self.conn.execute(
            """SELECT * FROM positions WHERE status = 'closed'
               ORDER BY closed_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_weekly_stats(self) -> dict:
        """Get aggregated stats for the last 7 days."""
        cursor = self.conn.execute(
            """SELECT
                 COALESCE(SUM(total_pnl_usdt), 0) as total_pnl,
                 COALESCE(SUM(trades_count), 0) as total_trades,
                 COALESCE(SUM(wins), 0) as total_wins,
                 COALESCE(SUM(losses), 0) as total_losses
               FROM daily_stats
               WHERE date >= date('now', '-7 days')"""
        )
        row = cursor.fetchone()
        stats = dict(row)
        total = stats["total_trades"]
        stats["win_rate"] = (stats["total_wins"] / total * 100) if total > 0 else 0.0
        return stats

    def get_all_time_stats(self) -> dict:
        """Get all-time aggregated stats."""
        cursor = self.conn.execute(
            """SELECT
                 COUNT(*) as total_trades,
                 COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END), 0) as wins,
                 COALESCE(SUM(CASE WHEN pnl_usdt <= 0 THEN 1 ELSE 0 END), 0) as losses,
                 COALESCE(SUM(pnl_usdt), 0) as total_pnl,
                 COALESCE(AVG(CASE WHEN pnl_usdt > 0 THEN pnl_usdt END), 0) as avg_win,
                 COALESCE(AVG(CASE WHEN pnl_usdt < 0 THEN ABS(pnl_usdt) END), 0) as avg_loss,
                 COALESCE(MAX(pnl_usdt), 0) as best_trade,
                 COALESCE(MIN(pnl_usdt), 0) as worst_trade
               FROM positions WHERE status = 'closed'"""
        )
        row = cursor.fetchone()
        stats = dict(row)

        total = stats["total_trades"]
        stats["win_rate"] = (stats["wins"] / total * 100) if total > 0 else 0.0

        # Risk-reward ratio
        avg_win = stats["avg_win"]
        avg_loss = stats["avg_loss"]
        stats["rr_ratio"] = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        # Expectancy ratio: ((1 + RR) * WR) - 1
        wr = stats["win_rate"] / 100
        stats["expectancy"] = ((1 + stats["rr_ratio"]) * wr) - 1 if total > 0 else 0.0

        return stats

    def get_pnl_by_symbol(self) -> list:
        """Get PnL breakdown per symbol."""
        cursor = self.conn.execute(
            """SELECT symbol,
                 COUNT(*) as trades,
                 SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) as wins,
                 COALESCE(SUM(pnl_usdt), 0) as total_pnl
               FROM positions WHERE status = 'closed'
               GROUP BY symbol ORDER BY total_pnl DESC"""
        )
        return [dict(row) for row in cursor.fetchall()]
