"""
RICOZ Bot — Signal Engine

Phase 3: Score from real CoinGlass data, determine entry side + size.
SpotCVD = Hard Veto #1 (max 30 pts) — determines direction
FutCVD  = Hard Veto #2 (max 25 pts) — must align
"""
import time
from loguru import logger

from src.config import MIN_SCORE
from .cvd import CVDAnalyzer


# Stale data threshold — blueprint: > 10 seconds = don't trade
SIGNAL_STALE_SECS = 10


class SignalEngine:
    """Scoring + entry decision berdasarkan order flow data."""

    def __init__(self):
        self.cvd = CVDAnalyzer()

    def evaluate(self, data: dict) -> dict:
        """
        Full signal evaluation pipeline.
        data = dict from CoinGlassDataFetcher.fetch_signal_data()

        Returns:
            {
                "decision": "REJECT" | "ENTRY_FULL" | "ENTRY_75" | "ENTRY_50",
                "side": "buy" | "sell",
                "score": int,
                "breakdown": dict,
                "reason": str,
                "stale": bool,
            }
        """
        symbol = data.get("symbol", "?")

        # ── Check data freshness ─────────────────────────
        signal_age = time.time() - data.get("timestamp", 0)
        if signal_age > SIGNAL_STALE_SECS:
            return self._reject(f"Signal stale ({signal_age:.0f}s > {SIGNAL_STALE_SECS}s)", stale=True)

        # ── Step 1: SpotCVD Gate (Hard Veto #1) ─────────
        spot_cvd = data.get("spot_cvd", {})
        spot_ok, spot_reason, direction = self.cvd.check_spot_cvd(spot_cvd)

        if not spot_ok:
            return self._reject(f"SpotCVD veto: {spot_reason}")

        # direction determines trade side
        side = "buy" if direction == "long" else "sell"

        # ── Step 2: FutCVD Alignment (Hard Veto #2) ──────
        fut_cvd = data.get("fut_cvd", {})
        fut_ok, fut_reason = self.cvd.check_fut_cvd_alignment(spot_cvd, fut_cvd)

        if not fut_ok:
            return self._reject(f"FutCVD veto: {fut_reason}")

        # ── Step 3: Score all signals ────────────────────
        score, breakdown = self._calculate_score(data, side)

        # ── Step 4: Entry decision ───────────────────────
        decision, reason = self._decide(score, breakdown)

        logger.info(f"{symbol}: {decision} {side.upper()} | score={score} | {reason}")

        return {
            "decision": decision,
            "side": side,
            "score": score,
            "breakdown": breakdown,
            "reason": reason,
            "stale": False,
        }

    def _calculate_score(self, data: dict, side: str) -> tuple[int, dict]:
        """
        Calculate signal score 0-100.

        Breakdown:
        - SpotCVD:     max 30 pts (#1)
        - FutCVD:      max 25 pts (#2)
        - Liquidation: max 20 pts (#3)
        - OI:          max 15 pts (#4)
        - Taker:       max 10 pts (#5)
        """
        score = 0
        breakdown = {}

        # 1. SpotCVD (max 30) — already passed gate
        spot = data.get("spot_cvd", {})
        spot_strength = spot.get("positive_ratio", 0.0)
        if side == "sell":
            spot_strength = 1 - spot_strength
        s = min(30, int(spot_strength * 30) + 10)  # base 10 for passing gate
        score += s
        breakdown["spot_cvd"] = s

        # 2. FutCVD (max 25) — already passed alignment
        fut = data.get("fut_cvd", {})
        fut_strength = fut.get("positive_ratio", 0.0)
        if side == "sell":
            fut_strength = 1 - fut_strength
        s = min(25, int(fut_strength * 25) + 8)  # base 8 for passing alignment
        score += s
        breakdown["fut_cvd"] = s

        # 3. Liquidation (max 20)
        liq = data.get("liquidation", {})
        liq_ok, liq_intensity = self.cvd.check_liquidation_confluence(liq, "long" if side == "buy" else "short")
        if liq_ok:
            s = min(20, int(liq_intensity * 20))
            score += s
            breakdown["liquidation"] = s

        # 4. OI (max 15)
        oi = data.get("open_interest", {})
        if oi.get("rising", False):
            rate = min(1.0, oi.get("rate", 0.0) * 100)  # normalize small rates
            s = min(15, int(rate * 15) + 5)  # base 5 for rising OI
            score += s
            breakdown["oi"] = s

        # 5. Taker (max 10)
        taker = data.get("taker_volume", {})
        taker_ok, taker_ratio = self.cvd.check_taker_confluence(taker, "long" if side == "buy" else "short")
        if taker_ok:
            s = min(10, int(taker_ratio * 10))
            score += s
            breakdown["taker"] = s

        return score, breakdown

    def _decide(self, score: int, breakdown: dict) -> tuple[str, str]:
        """Entry decision based on score with liquidation quality check."""
        # Liquidation quality gate — borderline score (<85) without liquidation
        # confluence = insufficient conviction. Not a hard veto, just raises bar
        # for marginal signals so we don't buy tops without forced-squeeze fuel.
        has_liq = breakdown.get("liquidation", 0) > 0

        if not has_liq and score < 85:
            return "REJECT", f"Score {score} without liquidation confluence — insufficient conviction"

        if score >= 90:
            return "ENTRY_FULL", f"Score {score} — 100% size"
        if score >= 80:
            return "ENTRY_75", f"Score {score} — 75% size"
        if score >= MIN_SCORE:
            return "ENTRY_50", f"Score {score} — 50% size"

        return "REJECT", f"Score {score} below threshold (min {MIN_SCORE})"

    def _reject(self, reason: str, stale: bool = False) -> dict:
        return {
            "decision": "REJECT",
            "side": "neutral",
            "score": 0,
            "breakdown": {},
            "reason": reason,
            "stale": stale,
        }
