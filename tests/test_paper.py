"""
RICOZ Bot — Phase 4 Tests: Paper Trading + Integration

Jalankan: python -m pytest tests/test_paper.py -v
"""
import pytest

from src.state.db import Database
from src.state.manager import StateManager


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_paper.db")
    database = Database(db_path)
    database.connect()
    yield database
    database.close()


@pytest.fixture
def state(db):
    return StateManager(db)


# ── Paper Entry Tests ────────────────────────────────────

class TestPaperEntry:

    def test_record_paper_entry(self, state):
        """Paper entry creates position with is_paper=1."""
        result = state.record_paper_entry(
            symbol="SOL/USDT:USDT",
            side="buy",
            price=150.0,
            size_usdt=10.0,
            score=85,
            breakdown={"spot_cvd": 25, "fut_cvd": 20},
        )

        assert result["ccxt_symbol"] == "SOL/USDT:USDT"
        assert result["is_paper"] is True
        assert result["order_id"].startswith("paper-")

        # Verify in DB
        pos = state.db.get_open_position_by_symbol("SOL/USDT:USDT")
        assert pos is not None
        assert pos["is_paper"] == 1
        assert pos["entry_signal_score"] == 85

    def test_paper_entry_sl_tp_long(self, state):
        """Paper long: SL below, TP above."""
        result = state.record_paper_entry("SOL/USDT:USDT", "buy", 100.0, 10.0, 80)
        assert result["sl_price"] < 100.0  # SL below entry
        assert result["tp_price"] > 100.0  # TP above entry

    def test_paper_entry_sl_tp_short(self, state):
        """Paper short: SL above, TP below."""
        result = state.record_paper_entry("SOL/USDT:USDT", "sell", 100.0, 10.0, 80)
        assert result["sl_price"] > 100.0  # SL above entry
        assert result["tp_price"] < 100.0  # TP below entry

    def test_paper_qty_calculation(self, state):
        """Paper qty = size_usdt / price."""
        result = state.record_paper_entry("SOL/USDT:USDT", "buy", 150.0, 15.0, 80)
        assert result["qty"] == pytest.approx(0.1, rel=1e-4)

    def test_paper_entry_blocked_by_state(self, state):
        """Paper entry respects state guards."""
        state.record_paper_entry("SOL/USDT:USDT", "buy", 150.0, 10.0, 80)
        # Same symbol should be blocked
        can, reason = state.can_enter("SOL/USDT:USDT")
        assert can is False
        assert "Already have" in reason

    def test_paper_entry_max_positions(self, state):
        """Paper entries count toward max positions."""
        state.max_positions = 2
        state.record_paper_entry("SOL/USDT:USDT", "buy", 150.0, 10.0, 80)
        state.record_paper_entry("AVAX/USDT:USDT", "buy", 40.0, 5.0, 75)
        can, reason = state.can_enter("SUI/USDT:USDT")
        assert can is False
        assert "Max positions" in reason


# ── Paper Exit Tests ─────────────────────────────────────

class TestPaperExit:

    def test_paper_exit_tp(self, state):
        """Paper TP exit records positive PnL."""
        result = state.record_paper_entry("SOL/USDT:USDT", "buy", 100.0, 10.0, 80)
        exit_info = state.record_exit(result["order_id"], 103.0, "TP")

        assert exit_info is not None
        assert exit_info["pnl_usdt"] > 0
        assert exit_info["reason"] == "TP"

    def test_paper_exit_sl(self, state):
        """Paper SL exit records negative PnL."""
        result = state.record_paper_entry("SOL/USDT:USDT", "buy", 100.0, 10.0, 80)
        exit_info = state.record_exit(result["order_id"], 98.5, "SL")

        assert exit_info is not None
        assert exit_info["pnl_usdt"] < 0

    def test_paper_exit_short_tp(self, state):
        """Paper short TP: price goes down = profit."""
        result = state.record_paper_entry("SOL/USDT:USDT", "sell", 100.0, 10.0, 80)
        exit_info = state.record_exit(result["order_id"], 97.0, "TP")
        assert exit_info["pnl_usdt"] > 0

    def test_paper_exit_clears_position(self, state):
        """After paper exit, position slot is freed."""
        result = state.record_paper_entry("SOL/USDT:USDT", "buy", 100.0, 10.0, 80)
        state.record_exit(result["order_id"], 103.0, "TP")

        can, _ = state.can_enter("SOL/USDT:USDT")
        # Should be blocked by cooldown, not by duplicate
        assert "cooldown" in _.lower() or can is True


# ── Paper Stats Tests ────────────────────────────────────

class TestPaperStats:

    def test_paper_stats_empty(self, state):
        """Paper stats with no trades."""
        stats = state.get_paper_stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0

    def test_paper_stats_after_trades(self, state):
        """Paper stats accumulate correctly."""
        # 2 wins, 1 loss
        for symbol, close, reason in [
            ("SOL/USDT:USDT", 103.0, "TP"),
            ("AVAX/USDT:USDT", 41.2, "TP"),
            ("SUI/USDT:USDT", 1.85, "SL"),
        ]:
            result = state.record_paper_entry(symbol, "buy",
                                               100.0 if "SOL" in symbol else 40.0 if "AVAX" in symbol else 2.0,
                                               10.0, 80)
            state.record_exit(result["order_id"], close, reason)

        stats = state.get_paper_stats()
        assert stats["total_trades"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["win_rate"] == pytest.approx(66.67, rel=1e-1)

    def test_paper_history(self, state):
        """Paper history returns only paper trades."""
        result = state.record_paper_entry("SOL/USDT:USDT", "buy", 100.0, 10.0, 80)
        state.record_exit(result["order_id"], 103.0, "TP")

        history = state.get_paper_history(5)
        assert len(history) == 1
        assert history[0]["is_paper"] == 1

    def test_paper_positions_separate(self, state):
        """Open paper positions returned separately."""
        state.record_paper_entry("SOL/USDT:USDT", "buy", 150.0, 10.0, 80)

        paper = state.get_open_paper_positions()
        assert len(paper) == 1

        # Also appears in general open positions
        all_open = state.get_open_positions()
        assert len(all_open) == 1


# ── Integration Flow Tests ───────────────────────────────

class TestIntegrationFlow:

    def test_full_paper_lifecycle(self, state):
        """Entry → hold → exit → stats."""
        # Entry
        entry = state.record_paper_entry("SOL/USDT:USDT", "buy", 150.0, 10.0, 85,
                                          breakdown={"spot_cvd": 25, "fut_cvd": 20})
        assert state.count_open_positions() == 1

        # Can't enter same symbol
        can, _ = state.can_enter("SOL/USDT:USDT")
        assert can is False

        # Exit with TP
        exit_info = state.record_exit(entry["order_id"], 154.5, "TP")
        assert exit_info["pnl_usdt"] > 0
        assert state.count_open_positions() == 0

        # Stats updated
        today = state.get_today_stats()
        assert today["trades_count"] >= 1
        assert today["wins"] >= 1

    def test_drawdown_circuit_breaker(self, state):
        """Multiple losses → drawdown → blocked."""
        state.max_daily_drawdown_pct = 3.0

        # Create and close 3 losing trades
        for i, sym in enumerate(["SOL/USDT:USDT", "AVAX/USDT:USDT", "SUI/USDT:USDT"]):
            entry = state.record_paper_entry(sym, "buy", 100.0, 10.0, 75)
            state.record_exit(entry["order_id"], 94.0, "SL")  # ~6% loss each

        # Should be blocked by drawdown
        can, reason = state.can_enter("BNB/USDT:USDT")
        assert can is False
        assert "drawdown" in reason.lower()

    def test_restart_resilience(self, state, db):
        """Positions survive DB reconnect."""
        state.record_paper_entry("SOL/USDT:USDT", "buy", 150.0, 10.0, 80)
        assert state.count_open_positions() == 1

        # Simulate restart — new StateManager same DB
        state2 = StateManager(db)
        assert state2.count_open_positions() == 1

        pos = state2.get_open_positions()
        assert pos[0]["symbol"] == "SOL/USDT:USDT"
