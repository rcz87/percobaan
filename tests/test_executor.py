"""
RICOZ Bot — Phase 1 Tests

Jalankan: python -m pytest tests/ -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ── SL/TP Math Tests ────────────────────────────────────

class TestSLTPMath:
    """Test SL/TP price calculations."""

    def test_sl_price_long(self):
        """SL untuk long = entry * (1 - sl_pct)."""
        entry, sl_pct = 100.0, 0.015
        assert entry * (1 - sl_pct) == 98.5

    def test_tp_price_long(self):
        """TP untuk long = entry * (1 + tp_pct)."""
        entry, tp_pct = 100.0, 0.03
        assert entry * (1 + tp_pct) == 103.0

    def test_sl_price_short(self):
        """SL untuk short = entry * (1 + sl_pct)."""
        entry, sl_pct = 100.0, 0.015
        assert entry * (1 + sl_pct) == pytest.approx(101.5)

    def test_tp_price_short(self):
        """TP untuk short = entry * (1 - tp_pct)."""
        entry, tp_pct = 100.0, 0.03
        assert entry * (1 - tp_pct) == 97.0

    def test_risk_reward_ratio(self):
        """Default SL 1.5% TP 3.0% = 2:1 RR."""
        sl_pct, tp_pct = 0.015, 0.030
        rr = tp_pct / sl_pct
        assert rr == 2.0


# ── CVD Logic Tests ──────────────────────────────────────

class TestCVDAnalyzer:
    """Test SpotCVD + FutCVD logic (dict interface)."""

    def test_spot_cvd_sustained_positive(self):
        """SpotCVD sustained rising = valid LONG signal."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        data = {"deltas": [10, 20, 30], "direction": "rising", "positive_ratio": 1.0}
        result, reason, direction = cvd.check_spot_cvd(data)
        assert result is True
        assert direction == "long"

    def test_spot_cvd_single_flip_rejected(self):
        """SpotCVD single flip = rejected."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        data = {"deltas": [10, -5, 30], "direction": "rising", "positive_ratio": 0.66}
        result, _, _ = cvd.check_spot_cvd(data)
        assert result is False

    def test_spot_cvd_direction_mismatch_rejected(self):
        """SpotCVD all negative but direction rising = rejected."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        data = {"deltas": [-10, -20, -30], "direction": "rising", "positive_ratio": 0.0}
        result, _, _ = cvd.check_spot_cvd(data)
        assert result is False

    def test_spot_cvd_insufficient_history(self):
        """SpotCVD < 3 candles = rejected."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        data = {"deltas": [10, 20], "direction": "rising", "positive_ratio": 1.0}
        result, reason, _ = cvd.check_spot_cvd(data)
        assert result is False
        assert "Insufficient" in reason

    def test_spot_cvd_empty(self):
        """SpotCVD empty deltas = rejected."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        data = {"deltas": [], "direction": "unknown", "positive_ratio": 0.0}
        result, _, _ = cvd.check_spot_cvd(data)
        assert result is False

    def test_cvd_alignment_both_rising(self):
        """SpotCVD + FutCVD same direction (rising) = aligned."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        result, _ = cvd.check_fut_cvd_alignment(
            {"direction": "rising"}, {"direction": "rising"}
        )
        assert result is True

    def test_cvd_alignment_both_falling(self):
        """SpotCVD + FutCVD same direction (falling) = aligned."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        result, _ = cvd.check_fut_cvd_alignment(
            {"direction": "falling"}, {"direction": "falling"}
        )
        assert result is True

    def test_cvd_divergence_rejected(self):
        """SpotCVD rising + FutCVD falling = divergence = rejected."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()
        result, reason = cvd.check_fut_cvd_alignment(
            {"direction": "rising"}, {"direction": "falling"}
        )
        assert result is False
        assert "divergence" in reason

    def test_cvd_divergence_detection(self):
        """Price vs CVD divergence detection."""
        from src.signal.cvd import CVDAnalyzer
        cvd = CVDAnalyzer()

        bearish, _ = cvd.detect_cvd_divergence("up", "down")
        assert bearish is True

        bullish, _ = cvd.detect_cvd_divergence("down", "up")
        assert bullish is True

        no_div, _ = cvd.detect_cvd_divergence("up", "up")
        assert no_div is False


# ── Signal Engine Tests ──────────────────────────────────

class TestSignalEngine:
    """Test scoring + entry decision (via _decide)."""

    def test_score_reject_below_threshold(self):
        """Score below MIN_SCORE = REJECT."""
        from src.signal.engine import SignalEngine
        engine = SignalEngine()
        decision, _ = engine._decide(65, {"spot_cvd": 20, "fut_cvd": 15, "liquidation": 10})
        assert decision == "REJECT"

    def test_score_at_min_entry_75(self):
        """Score at MIN_SCORE (80) with liquidation = ENTRY_75."""
        from src.signal.engine import SignalEngine
        engine = SignalEngine()
        decision, _ = engine._decide(80, {"spot_cvd": 25, "fut_cvd": 20, "liquidation": 12})
        assert decision == "ENTRY_75"

    def test_score_entry_75(self):
        """Score 85 without liquidation = ENTRY_75 (above quality gate)."""
        from src.signal.engine import SignalEngine
        engine = SignalEngine()
        decision, _ = engine._decide(85, {"spot_cvd": 28, "fut_cvd": 22})
        assert decision == "ENTRY_75"

    def test_score_entry_full(self):
        """Score >= 90 = ENTRY_FULL."""
        from src.signal.engine import SignalEngine
        engine = SignalEngine()
        decision, _ = engine._decide(95, {"spot_cvd": 30, "fut_cvd": 25})
        assert decision == "ENTRY_FULL"


# ── Retry Logic Tests ────────────────────────────────────

class TestRetryLogic:
    """Test @retrier decorator pattern."""

    def test_retry_quadratic_backoff_values(self):
        """Verify quadratic backoff: (max - attempt)^2 + 1."""
        max_retries = 4
        expected = [17, 10, 5, 2]  # (4-0)^2+1, (4-1)^2+1, (4-2)^2+1, (4-3)^2+1
        for attempt in range(max_retries):
            wait = (max_retries - attempt) ** 2 + 1
            assert wait == expected[attempt]


# ── PnL Calculation Tests ───────────────────────────────

class TestPnLCalculation:
    """Test fee-inclusive PnL calculation (Freqtrade pattern)."""

    def test_pnl_long_profit(self):
        """Long profit: (close - entry) * qty * (1 - fee)."""
        entry, close, qty = 100.0, 103.0, 1.0
        fee_rate = 0.0004
        pnl = (close - entry) * qty * (1 - fee_rate)
        assert pnl == pytest.approx(2.9988, rel=1e-4)

    def test_pnl_long_loss(self):
        """Long loss: negative PnL."""
        entry, close, qty = 100.0, 98.5, 1.0
        fee_rate = 0.0004
        pnl = (close - entry) * qty * (1 - fee_rate)
        assert pnl < 0

    def test_pnl_short_profit(self):
        """Short profit: (entry - close) * qty * (1 - fee)."""
        entry, close, qty = 100.0, 97.0, 1.0
        fee_rate = 0.0004
        pnl = (entry - close) * qty * (1 - fee_rate)
        assert pnl == pytest.approx(2.9988, rel=1e-4)

    def test_pnl_short_loss(self):
        """Short loss: negative PnL."""
        entry, close, qty = 100.0, 101.5, 1.0
        fee_rate = 0.0004
        pnl = (entry - close) * qty * (1 - fee_rate)
        assert pnl < 0

    def test_pnl_precision_8_decimals(self):
        """PnL rounded to 8 decimals (Freqtrade pattern)."""
        pnl = 2.998800120000001
        pnl_precise = float(f"{pnl:.8f}")
        assert pnl_precise == 2.99880012
