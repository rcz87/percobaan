"""
RICOZ Bot — Phase 3 Tests: Parser + CVD + Signal Engine

Jalankan: python -m pytest tests/test_signal.py -v
"""
import time
import pytest

from src.signal.parser import (
    parse_number,
    parse_table_rows,
    parse_cvd_response,
    parse_liquidation_response,
    parse_oi_response,
    parse_taker_response,
    parse_summary_direction,
    parse_summary_ratio,
    parse_summary_net,
)
from src.signal.cvd import CVDAnalyzer
from src.signal.engine import SignalEngine


# ── Parser Tests ─────────────────────────────────────────

class TestParseNumber:

    def test_plain_number(self):
        assert parse_number("502362") == 502362.0

    def test_with_commas(self):
        assert parse_number("-28,724") == -28724.0

    def test_positive_sign(self):
        assert parse_number("+949,895") == 949895.0

    def test_dollar_K(self):
        assert parse_number("$949.8K") == pytest.approx(949800, rel=1e-2)

    def test_dollar_M(self):
        assert parse_number("$1.56M") == pytest.approx(1560000, rel=1e-2)

    def test_dollar_B(self):
        assert parse_number("$4.72B") == pytest.approx(4720000000, rel=1e-2)

    def test_zero(self):
        assert parse_number("+0") == 0.0
        assert parse_number("$0.00") == 0.0

    def test_negative_dollar(self):
        assert parse_number("-$447.5K") == pytest.approx(-447500, rel=1e-2)

    def test_empty(self):
        assert parse_number("") == 0.0


class TestParseTableRows:

    def test_cvd_table(self):
        table = """```
  Time |            CVD |        Delta
────── | ────────────── | ────────────
 09:55 |        -28,724 |           +0
 10:00 |        -63,968 |      -35,244
 10:05 |        -71,562 |       -7,593
```"""
        rows = parse_table_rows(table)
        assert len(rows) == 3
        assert rows[0]["time"] == "09:55"
        assert rows[0]["cvd"] == "-28,724"
        assert rows[1]["delta"] == "-35,244"

    def test_taker_table(self):
        table = """```
  Time |      Buy Vol |     Sell Vol |          Net | Aggressor
────── | ──────────── | ──────────── | ──────────── | ─────────
 09:55 |      $949.8K |       $1.40M |     -$447.5K |      SELL
 10:00 |       $3.08M |       $2.13M |     +$949.9K |       BUY
```"""
        rows = parse_table_rows(table)
        assert len(rows) == 2
        assert rows[0]["aggressor"] == "SELL"
        assert rows[1]["net"] == "+$949.9K"


class TestParseSummary:

    def test_direction_rising(self):
        assert parse_summary_direction("direction: rising") == "rising"

    def test_direction_falling(self):
        assert parse_summary_direction("direction: falling") == "falling"

    def test_ratio(self):
        pos, total = parse_summary_ratio("3/4 positive delta")
        assert pos == 3
        assert total == 4

    def test_ratio_buy(self):
        pos, total = parse_summary_ratio("3/5 buy-dominant")
        assert pos == 3
        assert total == 5

    def test_net_change(self):
        val = parse_summary_net("net change: +$1.56M")
        assert val == pytest.approx(1560000, rel=1e-2)

    def test_total_net(self):
        val = parse_summary_net("total net: +$1.14M")
        assert val == pytest.approx(1140000, rel=1e-2)


class TestParseCVDResponse:

    SAMPLE = """## Spot CVD — SOL

*(last 5 of 5)*

```
  Time |            CVD |        Delta
────── | ────────────── | ────────────
 09:55 |        -28,724 |           +0
 10:00 |        -63,968 |      -35,244
 10:05 |        -71,562 |       -7,593
 10:10 |       -170,040 |      -98,478
 10:15 |       -327,255 |     -157,215
```

**Summary:** 0/4 positive delta, net change: -$298.5K, direction: falling
"""

    def test_parse_deltas(self):
        result = parse_cvd_response(self.SAMPLE)
        assert len(result["deltas"]) == 5
        assert result["deltas"][1] == pytest.approx(-35244, rel=1e-2)

    def test_parse_direction(self):
        result = parse_cvd_response(self.SAMPLE)
        assert result["direction"] == "falling"

    def test_parse_ratio(self):
        result = parse_cvd_response(self.SAMPLE)
        assert result["positive_ratio"] == 0.0

    def test_parse_net(self):
        result = parse_cvd_response(self.SAMPLE)
        assert result["net_change"] == pytest.approx(-298500, rel=1e-2)


class TestParseOIResponse:

    SAMPLE = """## OI Aggregated — SOL

```
  Time |         Open |         High |          Low |        Close
────── | ──────────── | ──────────── | ──────────── | ────────────
 09:55 |       $4.72B |       $4.73B |       $4.72B |       $4.72B
 10:15 |       $4.73B |       $4.73B |       $4.73B |       $4.73B
```

**Summary:** OI $4.72B -> $4.73B (change: +$10.43M)
"""

    def test_parse_values(self):
        result = parse_oi_response(self.SAMPLE)
        assert len(result["values"]) == 2
        assert result["values"][0] == pytest.approx(4.72e9, rel=1e-2)

    def test_parse_rising(self):
        result = parse_oi_response(self.SAMPLE)
        assert result["rising"] is True

    def test_parse_change(self):
        result = parse_oi_response(self.SAMPLE)
        assert result["change"] == pytest.approx(10430000, rel=1e-2)


# ── CVD Analyzer Tests (Phase 3) ────────────────────────

class TestCVDAnalyzerPhase3:

    def test_spot_cvd_sustained_falling(self):
        """Sustained falling = valid SHORT signal."""
        cvd = CVDAnalyzer()
        data = {"deltas": [-100, -200, -300], "direction": "falling", "positive_ratio": 0.0}
        ok, reason, direction = cvd.check_spot_cvd(data)
        assert ok is True
        assert direction == "short"

    def test_spot_cvd_sustained_rising(self):
        """Sustained rising = valid LONG signal."""
        cvd = CVDAnalyzer()
        data = {"deltas": [100, 200, 300], "direction": "rising", "positive_ratio": 0.75}
        ok, reason, direction = cvd.check_spot_cvd(data)
        assert ok is True
        assert direction == "long"

    def test_spot_cvd_mixed_rejected(self):
        """Mixed deltas = rejected."""
        cvd = CVDAnalyzer()
        data = {"deltas": [100, -50, 200], "direction": "rising", "positive_ratio": 0.5}
        ok, _, direction = cvd.check_spot_cvd(data)
        assert ok is False

    def test_fut_cvd_aligned(self):
        cvd = CVDAnalyzer()
        spot = {"direction": "rising"}
        fut = {"direction": "rising"}
        ok, _ = cvd.check_fut_cvd_alignment(spot, fut)
        assert ok is True

    def test_fut_cvd_divergence(self):
        cvd = CVDAnalyzer()
        spot = {"direction": "rising"}
        fut = {"direction": "falling"}
        ok, reason = cvd.check_fut_cvd_alignment(spot, fut)
        assert ok is False
        assert "divergence" in reason

    def test_liquidation_confluence_long(self):
        """Shorts liquidated = confirms long."""
        cvd = CVDAnalyzer()
        liq = {"dominant_side": "short", "total_long": 1000, "total_short": 5000}
        ok, intensity = cvd.check_liquidation_confluence(liq, "long")
        assert ok is True
        assert intensity > 0

    def test_taker_confluence_long(self):
        """Buy dominant = confirms long."""
        cvd = CVDAnalyzer()
        taker = {"buy_dominant_ratio": 0.8, "total_net": 500000}
        ok, ratio = cvd.check_taker_confluence(taker, "long")
        assert ok is True


# ── Signal Engine Tests (Phase 3) ────────────────────────

class TestSignalEnginePhase3:

    def _make_bullish_data(self):
        return {
            "symbol": "SOL/USDT:USDT",
            "spot_cvd": {
                "deltas": [100, 200, 300, 400, 500],
                "values": [100, 300, 600, 1000, 1500],
                "direction": "rising",
                "positive_ratio": 0.8,
                "net_change": 1400,
            },
            "fut_cvd": {
                "deltas": [50, 100, 150, 200, 250],
                "values": [50, 150, 300, 500, 750],
                "direction": "rising",
                "positive_ratio": 0.75,
                "net_change": 700,
            },
            "liquidation": {
                "dominant_side": "short",
                "total_long": 1000,
                "total_short": 5000,
            },
            "open_interest": {
                "rising": True,
                "rate": 0.02,
                "values": [100, 102],
                "change": 2,
            },
            "taker_volume": {
                "buy_dominant_ratio": 0.7,
                "total_net": 500000,
                "nets": [100, 200, -50, 300, 150],
            },
            "timestamp": time.time(),
        }

    def test_bullish_signal_entry(self):
        engine = SignalEngine()
        data = self._make_bullish_data()
        result = engine.evaluate(data)
        assert result["decision"] != "REJECT"
        assert result["side"] == "buy"
        assert result["score"] > 0

    def test_bearish_signal_entry(self):
        engine = SignalEngine()
        data = self._make_bullish_data()
        # Flip to bearish
        data["spot_cvd"]["deltas"] = [-100, -200, -300, -400, -500]
        data["spot_cvd"]["direction"] = "falling"
        data["spot_cvd"]["positive_ratio"] = 0.0
        data["fut_cvd"]["direction"] = "falling"
        data["fut_cvd"]["positive_ratio"] = 0.0
        data["taker_volume"]["buy_dominant_ratio"] = 0.2
        data["taker_volume"]["total_net"] = -500000
        data["liquidation"]["dominant_side"] = "long"

        result = engine.evaluate(data)
        assert result["side"] == "sell"

    def test_stale_signal_rejected(self):
        engine = SignalEngine()
        data = self._make_bullish_data()
        data["timestamp"] = time.time() - 60  # 60s old
        result = engine.evaluate(data)
        assert result["decision"] == "REJECT"
        assert result["stale"] is True

    def test_spot_cvd_veto(self):
        engine = SignalEngine()
        data = self._make_bullish_data()
        data["spot_cvd"]["deltas"] = [100, -50, 200]  # mixed = fail
        result = engine.evaluate(data)
        assert result["decision"] == "REJECT"
        assert "SpotCVD" in result["reason"]

    def test_fut_cvd_veto(self):
        engine = SignalEngine()
        data = self._make_bullish_data()
        data["fut_cvd"]["direction"] = "falling"  # divergence
        result = engine.evaluate(data)
        assert result["decision"] == "REJECT"
        assert "FutCVD" in result["reason"]
