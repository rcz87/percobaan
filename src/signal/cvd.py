"""
RICOZ Bot — CVD Analyzer

SpotCVD + FutCVD logic.
SpotCVD = Hard Veto #1: harus POSITIF dan sustained 3+ candles.
"""
from loguru import logger


class CVDAnalyzer:
    """Analyze Cumulative Volume Delta data."""

    def check_spot_cvd(self, cvd_history: list) -> tuple[bool, str]:
        """
        SpotCVD Gate — Hard Veto #1.
        Harus POSITIF dan sustained 3+ candles.
        Single flip = REJECT.

        Args:
            cvd_history: List of CVD values (recent candles)

        Returns:
            (pass, reason)
        """
        if len(cvd_history) < 3:
            return False, "Insufficient CVD history"

        last_3 = cvd_history[-3:]
        all_positive = all(c > 0 for c in last_3)

        if not all_positive:
            return False, f"SpotCVD not sustained positive: {last_3}"

        return True, f"SpotCVD OK — sustained {last_3}"

    def check_fut_cvd_alignment(self, spot_cvd: list, fut_cvd: list) -> tuple[bool, str]:
        """
        FutCVD Alignment Check — Hard Veto #2.
        FutCVD harus align dengan SpotCVD direction.
        Divergence = hedging signal = REJECT.

        Args:
            spot_cvd: SpotCVD history
            fut_cvd: FuturesCVD history

        Returns:
            (aligned, reason)
        """
        if len(spot_cvd) < 2 or len(fut_cvd) < 2:
            return False, "Insufficient CVD data for alignment check"

        # Check direction alignment (both positive or both negative)
        spot_direction = spot_cvd[-1] > 0
        fut_direction = fut_cvd[-1] > 0

        if spot_direction != fut_direction:
            return False, f"CVD divergence — Spot: {'UP' if spot_direction else 'DOWN'}, Fut: {'UP' if fut_direction else 'DOWN'}"

        return True, "SpotCVD + FutCVD aligned"

    def detect_cvd_divergence(self, price_trend: str, cvd_trend: str) -> tuple[bool, str]:
        """
        Detect price vs CVD divergence.
        Price naik tapi CVD turun = bearish divergence.
        Price turun tapi CVD naik = bullish divergence.
        """
        if price_trend == "up" and cvd_trend == "down":
            return True, "Bearish divergence — price up, CVD down"
        if price_trend == "down" and cvd_trend == "up":
            return True, "Bullish divergence — price down, CVD up"

        return False, "No divergence"
