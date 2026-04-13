"""
RICOZ Bot — Signal Engine

Phase 3: Scoring system 0-100 + entry decision logic.
SpotCVD = Hard Veto #1 (max 30 poin)
FutCVD  = Hard Veto #2 (max 25 poin)
"""
from loguru import logger

from .cvd import CVDAnalyzer


class SignalEngine:
    """Scoring + entry decision berdasarkan order flow data."""

    def __init__(self):
        self.cvd = CVDAnalyzer()

    def calculate_score(self, data: dict) -> tuple[int, dict]:
        """
        Calculate signal score 0-100.

        Score breakdown:
        - SpotCVD:     max 30 poin (#1 paling penting)
        - FutCVD:      max 25 poin
        - Liquidation: max 20 poin
        - OI:          max 15 poin
        - Taker:       max 10 poin
        Total:         max 100 poin

        Returns:
            (score, breakdown_dict)
        """
        score = 0
        breakdown = {}

        # 1. SpotCVD (max 30) — paling penting
        spot_ok, _ = self.cvd.check_spot_cvd(data["spot_cvd"].get("history", []))
        if spot_ok:
            s = min(30, int(data["spot_cvd"]["strength"] * 30))
            score += s
            breakdown["spot_cvd"] = s

        # 2. FutCVD alignment (max 25)
        if data["fut_cvd"].get("aligned_with_spot", False):
            s = min(25, int(data["fut_cvd"]["strength"] * 25))
            score += s
            breakdown["fut_cvd"] = s

        # 3. Liquidation confluence (max 20)
        if data["liquidation"].get("confirms_direction", False):
            s = min(20, int(data["liquidation"]["intensity"] * 20))
            score += s
            breakdown["liquidation"] = s

        # 4. OI rising (max 15)
        if data["open_interest"].get("rising", False):
            s = min(15, int(data["open_interest"]["rate"] * 15))
            score += s
            breakdown["oi"] = s

        # 5. Taker volume dominant (max 10)
        if data["taker_volume"].get("dominant", False):
            s = min(10, int(data["taker_volume"]["ratio"] * 10))
            score += s
            breakdown["taker"] = s

        return score, breakdown

    def decide_entry(self, score: int, breakdown: dict) -> tuple[str, str]:
        """
        Entry decision berdasarkan score + hard veto.

        Returns:
            (decision, reason)
            decision: 'REJECT', 'ENTRY_FULL', 'ENTRY_75', 'ENTRY_50'
        """
        # Hard veto — SpotCVD wajib ada
        if breakdown.get("spot_cvd", 0) == 0:
            return "REJECT", "SpotCVD gate failed — hard veto"

        # Hard veto — FutCVD wajib align
        if breakdown.get("fut_cvd", 0) == 0:
            return "REJECT", "FutCVD not aligned — hard veto"

        # Score-based sizing
        if score >= 90:
            return "ENTRY_FULL", f"Score {score} — 100% size"
        if score >= 80:
            return "ENTRY_75", f"Score {score} — 75% size"
        if score >= 70:
            return "ENTRY_50", f"Score {score} — 50% size"

        return "REJECT", f"Score {score} below threshold (min 70)"
