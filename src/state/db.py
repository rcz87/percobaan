"""
RICOZ Bot — Database Layer (SQLite)

Phase 2: Schema + CRUD operations.
Pattern dari Freqtrade persistence/models.py.
"""
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
"""


class Database:
    """SQLite database layer."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Initialize DB connection + create tables."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
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
               (id, symbol, side, entry_price, size_usdt, qty, sl_price, tp_price, entry_signal_score)
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

    def close_position(self, position_id: str, close_price: float,
                       pnl_usdt: float, pnl_pct: float, reason: str):
        """Close position dengan PnL info."""
        self.conn.execute(
            """UPDATE positions
               SET status = 'closed', closed_at = ?, pnl_usdt = ?,
                   pnl_pct = ?, close_reason = ?
               WHERE id = ?""",
            (datetime.utcnow().isoformat(), pnl_usdt, pnl_pct, reason, position_id),
        )
        self.conn.commit()

    def get_open_positions(self) -> list:
        """Get semua posisi open."""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE status = 'open'"
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

    def get_trade_history(self, limit: int = 10) -> list:
        """Get last N closed trades."""
        cursor = self.conn.execute(
            """SELECT * FROM positions WHERE status = 'closed'
               ORDER BY closed_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
