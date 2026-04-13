"""
RICOZ Bot — CVD Analyzer

Phase 3: Work with parsed CoinGlass CVD data.
SpotCVD = Hard Veto #1: direction must be sustained.
FutCVD = Hard Veto #2: must align with SpotCVD.
"""
from loguru import logger


class CVDAnalyzer:
    """Analyze Cumulative Volume Delta data from CoinGlass."""

    def check_spot_cvd(self, cvd_data: dict) -> tuple[bool, str, str]:
        """
        SpotCVD Gate — Hard Veto #1.
        Check direction sustained over recent candles.

        Args:
            cvd_data: Parsed CVD dict from fetcher/parser

        Returns:
            (pass, reason, direction)  — direction is "long" or "short"
        """
        deltas = cvd_data.get("deltas", [])
        direction = cvd_data.get("direction", "unknown")
        positive_ratio = cvd_data.get("positive_ratio", 0.0)

        if len(deltas) < 3:
            return False, "Insufficient CVD history", "neutral"

        # Check last 3 deltas for sustained direction
        last_3 = deltas[-3:]
        all_positive = all(d > 0 for d in last_3)
        all_negative = all(d < 0 for d in last_3)

        if all_positive and direction == "rising":
            return True, f"SpotCVD OK — sustained rising, ratio {positive_ratio:.0%}", "long"

        if all_negative and direction == "falling":
            return True, f"SpotCVD OK — sustained falling, ratio {1-positive_ratio:.0%}", "short"

        # Mixed signals
        return False, f"SpotCVD not sustained — deltas: {last_3}, dir: {direction}", "neutral"

    def check_fut_cvd_alignment(self, spot_data: dict, fut_data: dict) -> tuple[bool, str]:
        """
        FutCVD Alignment Check — Hard Veto #2.
        FutCVD must align with SpotCVD direction.
        Divergence = hedging = REJECT.

        Args:
            spot_data: Parsed SpotCVD dict
            fut_data: Parsed FutCVD dict

        Returns:
            (aligned, reason)
        """
        spot_dir = spot_data.get("direction", "unknown")
        fut_dir = fut_data.get("direction", "unknown")

        if spot_dir == "unknown" or fut_dir == "unknown":
            return False, "CVD direction unknown"

        if spot_dir == fut_dir:
            return True, f"CVD aligned — both {spot_dir}"

        return False, f"CVD divergence — Spot: {spot_dir}, Fut: {fut_dir}"

    def check_liquidation_confluence(self, liq_data: dict, trade_side: str) -> tuple[bool, float]:
        """
        Liquidation confluence check.
        For LONG: shorts getting liquidated = bullish (confirms our direction)
        For SHORT: longs getting liquidated = bearish (confirms our direction)

        Returns:
            (confirms, intensity 0.0-1.0)
        """
        dominant = liq_data.get("dominant_side", "neutral")
        total_long = liq_data.get("total_long", 0)
        total_short = liq_data.get("total_short", 0)
        total = total_long + total_short

        if total == 0:
            return False, 0.0  # no liquidation data

        if trade_side == "long" and dominant == "short":
            # Shorts getting liquidated → bullish → confirms long
            intensity = min(1.0, total_short / max(total, 1) * 2)
            return True, intensity

        if trade_side == "short" and dominant == "long":
            # Longs getting liquidated → bearish → confirms short
            intensity = min(1.0, total_long / max(total, 1) * 2)
            return True, intensity

        return False, 0.0

    def check_taker_confluence(self, taker_data: dict, trade_side: str) -> tuple[bool, float]:
        """
        Taker volume confluence.
        For LONG: buy-dominant taker = confirms.
        For SHORT: sell-dominant taker = confirms.

        Returns:
            (confirms, ratio 0.0-1.0)
        """
        buy_ratio = taker_data.get("buy_dominant_ratio", 0.0)
        total_net = taker_data.get("total_net", 0.0)

        if trade_side == "long":
            confirms = buy_ratio >= 0.6 and total_net > 0
            return confirms, buy_ratio

        if trade_side == "short":
            sell_ratio = 1 - buy_ratio
            confirms = sell_ratio >= 0.6 and total_net < 0
            return confirms, sell_ratio

        return False, 0.0
