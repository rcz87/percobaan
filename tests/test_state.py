"""
RICOZ Bot — Phase 2 Tests: StateManager + Database

Jalankan: python -m pytest tests/test_state.py -v
"""
import os
import pytest
from datetime import datetime, timedelta

from src.state.db import Database
from src.state.manager import StateManager


@pytest.fixture
def db(tmp_path):
    """Create temp database for each test."""
    db_path = str(tmp_path / "test_ricoz.db")
    database = Database(db_path)
    database.connect()
    yield database
    database.close()


@pytest.fixture
def state(db):
    """Create StateManager with temp DB."""
    return StateManager(db)


# ── Database CRUD Tests ──────────────────────────────────

class TestDatabase:

    def test_create_tables(self, db):
        """Tables created on connect."""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        assert "positions" in tables
        assert "daily_stats" in tables

    def test_insert_and_get_position(self, db):
        """Insert position + get by symbol."""
        db.insert_position({
            "id": "test-001",
            "symbol": "SOL/USDT:USDT",
            "side": "buy",
            "entry_price": 150.0,
            "size_usdt": 10.0,
            "qty": 0.066,
            "sl_price": 147.75,
            "tp_price": 154.50,
            "entry_signal_score": 85,
        })

        pos = db.get_open_position_by_symbol("SOL/USDT:USDT")
        assert pos is not None
        assert pos["id"] == "test-001"
        assert pos["entry_price"] == 150.0
        assert pos["status"] == "open"

    def test_close_position(self, db):
        """Close position updates status + PnL."""
        db.insert_position({
            "id": "test-002",
            "symbol": "AVAX/USDT:USDT",
            "side": "buy",
            "entry_price": 40.0,
            "size_usdt": 5.0,
            "qty": 0.125,
        })

        db.close_position("test-002", 41.2, 0.15, 3.0, "TP")

        pos = db.get_position_by_id("test-002")
        assert pos["status"] == "closed"
        assert pos["close_reason"] == "TP"
        assert pos["pnl_usdt"] == 0.15
        assert pos["close_price"] == 41.2

    def test_get_open_positions(self, db):
        """Only returns open positions."""
        db.insert_position({
            "id": "open-1", "symbol": "SOL/USDT:USDT", "side": "buy",
            "entry_price": 150.0, "size_usdt": 10.0, "qty": 0.066,
        })
        db.insert_position({
            "id": "open-2", "symbol": "AVAX/USDT:USDT", "side": "sell",
            "entry_price": 40.0, "size_usdt": 5.0, "qty": 0.125,
        })
        db.close_position("open-2", 39.0, 0.12, 2.5, "TP")

        open_positions = db.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0]["id"] == "open-1"

    def test_daily_stats(self, db):
        """Daily stats accumulate correctly."""
        db.update_daily_stats(1.5, is_win=True)
        db.update_daily_stats(-0.8, is_win=False)
        db.update_daily_stats(2.0, is_win=True)

        pnl = db.get_today_pnl()
        assert pnl == pytest.approx(2.7, rel=1e-4)

        stats = db.get_today_stats()
        assert stats["trades_count"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1

    def test_trade_history(self, db):
        """Trade history returns closed trades in order."""
        for i in range(5):
            db.insert_position({
                "id": f"hist-{i}", "symbol": "SOL/USDT:USDT", "side": "buy",
                "entry_price": 150.0 + i, "size_usdt": 5.0, "qty": 0.033,
            })
            db.close_position(f"hist-{i}", 151.0 + i, 0.03 * i, 0.6 * i, "TP")

        history = db.get_trade_history(3)
        assert len(history) == 3
        assert history[0]["id"] == "hist-4"  # most recent first

    def test_all_time_stats(self, db):
        """All-time stats with win rate and RR."""
        # 3 wins, 2 losses
        for i, (pnl, reason) in enumerate([
            (3.0, "TP"), (2.5, "TP"), (-1.5, "SL"), (1.8, "TP"), (-1.2, "SL")
        ]):
            db.insert_position({
                "id": f"at-{i}", "symbol": "SOL/USDT:USDT", "side": "buy",
                "entry_price": 150.0, "size_usdt": 5.0, "qty": 0.033,
            })
            db.close_position(f"at-{i}", 151.0, pnl, pnl / 5 * 100, reason)

        stats = db.get_all_time_stats()
        assert stats["total_trades"] == 5
        assert stats["wins"] == 3
        assert stats["losses"] == 2
        assert stats["win_rate"] == 60.0
        assert stats["total_pnl"] == pytest.approx(4.6, rel=1e-4)
        assert stats["rr_ratio"] > 0

    def test_pnl_by_symbol(self, db):
        """PnL breakdown per symbol."""
        db.insert_position({
            "id": "sym-1", "symbol": "SOL/USDT:USDT", "side": "buy",
            "entry_price": 150.0, "size_usdt": 5.0, "qty": 0.033,
        })
        db.close_position("sym-1", 153.0, 1.5, 3.0, "TP")

        db.insert_position({
            "id": "sym-2", "symbol": "AVAX/USDT:USDT", "side": "buy",
            "entry_price": 40.0, "size_usdt": 5.0, "qty": 0.125,
        })
        db.close_position("sym-2", 38.0, -0.5, -5.0, "SL")

        by_symbol = db.get_pnl_by_symbol()
        assert len(by_symbol) == 2
        assert by_symbol[0]["symbol"] == "SOL/USDT:USDT"  # highest PnL first


# ── StateManager Tests ───────────────────────────────────

class TestStateManager:

    def test_can_enter_empty(self, state):
        """Can enter when no positions."""
        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is True
        assert reason == "OK"

    def test_block_duplicate_entry(self, state):
        """Block entry if same symbol already open."""
        state.db.insert_position({
            "id": "dup-1", "symbol": "SOL/USDT:USDT", "side": "buy",
            "entry_price": 150.0, "size_usdt": 10.0, "qty": 0.066,
        })

        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is False
        assert "Already have" in reason

    def test_max_positions_block(self, state):
        """Block when max positions reached."""
        state.max_positions = 2
        for i, sym in enumerate(["SOL/USDT:USDT", "AVAX/USDT:USDT"]):
            state.db.insert_position({
                "id": f"max-{i}", "symbol": sym, "side": "buy",
                "entry_price": 100.0, "size_usdt": 5.0, "qty": 0.05,
            })

        can, reason = state.can_enter("SUI/USDT:USDT")
        assert can is False
        assert "Max positions" in reason

    def test_cooldown_block(self, state):
        """Block entry within cooldown period."""
        state.cooldown_secs = 300
        state.db.insert_position({
            "id": "cool-1", "symbol": "SOL/USDT:USDT", "side": "buy",
            "entry_price": 150.0, "size_usdt": 10.0, "qty": 0.066,
        })
        # Close it just now
        state.db.close_position("cool-1", 152.0, 0.13, 1.3, "TP")

        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is False
        assert "cooldown" in reason

    def test_daily_drawdown_block(self, state):
        """Block when daily drawdown exceeds limit."""
        state.max_daily_drawdown_pct = 3.0
        # Simulate -20 USDT loss (4% of 500 USDT capital)
        state.db.update_daily_stats(-20.0, is_win=False)

        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is False
        assert "drawdown" in reason

    def test_kill_switch(self, state):
        """Kill switch blocks all entries."""
        state.stop()
        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is False
        assert "STOPPED" in reason

        state.go()
        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is True

    def test_record_entry(self, state):
        """Record entry stores in DB."""
        order_result = {
            "order_id": "entry-001",
            "ccxt_symbol": "SOL/USDT:USDT",
            "side": "buy",
            "entry_price": 150.0,
            "amount_usdt": 10.0,
            "qty": 0.066,
            "sl_price": 147.75,
            "tp_price": 154.50,
        }
        state.record_entry(order_result, score=85)

        pos = state.db.get_open_position_by_symbol("SOL/USDT:USDT")
        assert pos is not None
        assert pos["entry_signal_score"] == 85

    def test_record_exit(self, state):
        """Record exit calculates PnL correctly."""
        state.db.insert_position({
            "id": "exit-001", "symbol": "SOL/USDT:USDT", "side": "buy",
            "entry_price": 100.0, "size_usdt": 10.0, "qty": 0.1,
        })

        exit_info = state.record_exit("exit-001", 103.0, "TP")
        assert exit_info is not None
        assert exit_info["pnl_usdt"] > 0
        assert exit_info["reason"] == "TP"

        # Verify DB updated
        pos = state.db.get_position_by_id("exit-001")
        assert pos["status"] == "closed"

    def test_record_exit_short(self, state):
        """Short PnL: profit when price goes down."""
        state.db.insert_position({
            "id": "short-001", "symbol": "SOL/USDT:USDT", "side": "sell",
            "entry_price": 100.0, "size_usdt": 10.0, "qty": 0.1,
        })

        exit_info = state.record_exit("short-001", 97.0, "TP")
        assert exit_info["pnl_usdt"] > 0  # profit on short

    def test_record_exit_updates_daily_stats(self, state):
        """Exit updates daily stats."""
        state.db.insert_position({
            "id": "stats-001", "symbol": "SOL/USDT:USDT", "side": "buy",
            "entry_price": 100.0, "size_usdt": 10.0, "qty": 0.1,
        })
        state.record_exit("stats-001", 103.0, "TP")

        today = state.get_today_stats()
        assert today["trades_count"] == 1
        assert today["wins"] == 1
        assert today["total_pnl_usdt"] > 0

    def test_drawdown_calculation(self, state):
        """Drawdown = abs(loss) / capital * 100."""
        # -15 USDT on 500 capital = 3%
        state.db.update_daily_stats(-15.0, is_win=False)
        assert state.daily_drawdown_pct() == pytest.approx(3.0, rel=1e-4)

    def test_no_drawdown_when_positive(self, state):
        """No drawdown when PnL is positive."""
        state.db.update_daily_stats(10.0, is_win=True)
        assert state.daily_drawdown_pct() == 0.0
