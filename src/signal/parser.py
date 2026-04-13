"""
RICOZ Bot — CoinGlass Response Parser

Parse markdown table responses from McPCG/CoinGlass MCP tools
into structured numeric data for the Signal Engine.
"""
import re
import json
from loguru import logger


def parse_number(s: str) -> float:
    """
    Parse number string from CoinGlass format.
    Handles: +502,362 / -28,724 / $4.72B / $949.8K / $1.40M / $0.00
    """
    s = s.strip().replace(",", "").replace("$", "")
    if not s or s == "0" or s == "+0":
        return 0.0

    multiplier = 1.0
    if s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 1_000_000_000
        s = s[:-1]

    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def parse_table_rows(markdown: str) -> list[dict]:
    """
    Parse markdown table rows into list of dicts.
    Input format:
    ```
      Time |    Col1 |    Col2
    ────── | ────── | ──────
     09:55 |  value |  value
    ```
    """
    lines = markdown.strip().split("\n")
    rows = []
    headers = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("```") or line.startswith("*"):
            continue
        if "──" in line:
            continue  # separator

        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]

        if not headers:
            headers = [h.strip().lower().replace(" ", "_") for h in parts]
            continue

        if len(parts) == len(headers):
            row = {}
            for i, h in enumerate(headers):
                row[h] = parts[i]
            rows.append(row)

    return rows


def parse_mcp_response(raw: str) -> dict:
    """
    Parse raw MCP tool response.
    Returns: {"status": str, "data": str, "data_age_seconds": float, ...}
    """
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if "result" in parsed:
            inner = json.loads(parsed["result"]) if isinstance(parsed["result"], str) else parsed["result"]
            return inner
        return parsed
    except (json.JSONDecodeError, TypeError):
        return {"status": "error", "data": str(raw)}


def parse_summary_direction(data_text: str) -> str:
    """Extract direction from summary line: 'direction: falling/rising'."""
    match = re.search(r"direction:\s*(\w+)", data_text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return "unknown"


def parse_summary_ratio(data_text: str) -> tuple[int, int]:
    """Extract ratio from summary: '3/4 positive delta' -> (3, 4)."""
    match = re.search(r"(\d+)/(\d+)\s+(?:positive|buy)", data_text, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


def parse_summary_net(data_text: str) -> float:
    """Extract net change from summary: 'net change: +$1.56M'."""
    match = re.search(r"net\s*(?:change)?:\s*([+\-]?\$?[\d,.]+[KMB]?)", data_text, re.IGNORECASE)
    if match:
        return parse_number(match.group(1))
    # Try "total net: +$1.14M"
    match = re.search(r"total\s*net:\s*([+\-]?\$?[\d,.]+[KMB]?)", data_text, re.IGNORECASE)
    if match:
        return parse_number(match.group(1))
    return 0.0


def parse_oi_change(data_text: str) -> float:
    """Extract OI change from summary: 'change: +$10.43M'."""
    match = re.search(r"change:\s*([+\-]?\$?[\d,.]+[KMB]?)", data_text, re.IGNORECASE)
    if match:
        return parse_number(match.group(1))
    return 0.0


# ── High-level parsers per signal type ───────────────────

def parse_cvd_response(data_text: str) -> dict:
    """
    Parse SpotCVD or FutCVD response.
    Returns: {
        "deltas": [float],   # delta per candle
        "values": [float],   # CVD values
        "direction": str,    # "rising" or "falling"
        "positive_ratio": float,  # 0.0-1.0
        "net_change": float,
    }
    """
    rows = parse_table_rows(data_text)
    deltas = []
    values = []

    for row in rows:
        delta = parse_number(row.get("delta", "0"))
        cvd = parse_number(row.get("cvd", "0"))
        deltas.append(delta)
        values.append(cvd)

    direction = parse_summary_direction(data_text)
    pos_count, total_count = parse_summary_ratio(data_text)
    net_change = parse_summary_net(data_text)

    return {
        "deltas": deltas,
        "values": values,
        "direction": direction,
        "positive_ratio": pos_count / total_count if total_count > 0 else 0.0,
        "net_change": net_change,
    }


def parse_liquidation_response(data_text: str) -> dict:
    """
    Parse liquidation response.
    Returns: {
        "long_liqs": [float],
        "short_liqs": [float],
        "total_long": float,
        "total_short": float,
        "dominant_side": str,  # "long" or "short" or "neutral"
    }
    """
    rows = parse_table_rows(data_text)
    long_liqs = []
    short_liqs = []

    for row in rows:
        long_liq = parse_number(row.get("long_liq", "0"))
        short_liq = parse_number(row.get("short_liq", "0"))
        long_liqs.append(long_liq)
        short_liqs.append(short_liq)

    total_long = sum(long_liqs)
    total_short = sum(short_liqs)

    if total_long > total_short * 1.5:
        dominant = "long"   # longs getting liquidated → bearish
    elif total_short > total_long * 1.5:
        dominant = "short"  # shorts getting liquidated → bullish
    else:
        dominant = "neutral"

    return {
        "long_liqs": long_liqs,
        "short_liqs": short_liqs,
        "total_long": total_long,
        "total_short": total_short,
        "dominant_side": dominant,
    }


def parse_oi_response(data_text: str) -> dict:
    """
    Parse Open Interest response.
    Returns: {
        "values": [float],  # OI close values
        "change": float,    # net OI change
        "rising": bool,
        "rate": float,      # % change
    }
    """
    rows = parse_table_rows(data_text)
    values = []

    for row in rows:
        close_val = parse_number(row.get("close", "0"))
        values.append(close_val)

    change = parse_oi_change(data_text)
    first = values[0] if values else 0
    last = values[-1] if values else 0
    rising = last > first
    rate = abs(last - first) / first if first > 0 else 0.0

    return {
        "values": values,
        "change": change,
        "rising": rising,
        "rate": rate,
    }


def parse_taker_response(data_text: str) -> dict:
    """
    Parse Taker Buy/Sell response.
    Returns: {
        "buy_vols": [float],
        "sell_vols": [float],
        "nets": [float],
        "buy_dominant_ratio": float,
        "total_net": float,
    }
    """
    rows = parse_table_rows(data_text)
    buy_vols = []
    sell_vols = []
    nets = []

    for row in rows:
        buy = parse_number(row.get("buy_vol", "0"))
        sell = parse_number(row.get("sell_vol", "0"))
        net = parse_number(row.get("net", "0"))
        buy_vols.append(buy)
        sell_vols.append(sell)
        nets.append(net)

    buy_dominant_count = sum(1 for n in nets if n > 0)
    total = len(nets) if nets else 1

    return {
        "buy_vols": buy_vols,
        "sell_vols": sell_vols,
        "nets": nets,
        "buy_dominant_ratio": buy_dominant_count / total,
        "total_net": parse_summary_net(data_text) or sum(nets),
    }
