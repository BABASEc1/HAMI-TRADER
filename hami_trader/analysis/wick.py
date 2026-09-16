"""
Module 10/13 of the spec: Wick analysis, separate from candle bodies,
plus wick-derived Fibonacci zones. All computed directly from real
OHLC candle data — no external data source needed, so this is always
REAL_IMPLEMENTED whenever candles were successfully fetched.
"""

from dataclasses import dataclass
from typing import List, Optional
from data.binance import Candle


@dataclass
class WickMetrics:
    candle_index: int
    upper_wick: float
    lower_wick: float
    upper_wick_pct_of_range: float   # upper wick as % of full high-low range
    lower_wick_pct_of_range: float
    body_pct_of_range: float
    classification: str              # e.g. "upper_wick_rejection", "lower_wick_rejection", "no_significant_wick"


def analyze_candle_wicks(candle: Candle, index: int, rejection_threshold: float = 0.4) -> WickMetrics:
    full_range = candle.high - candle.low
    if full_range <= 0:
        return WickMetrics(index, 0, 0, 0, 0, 0, "no_range")

    body_top = max(candle.open, candle.close)
    body_bottom = min(candle.open, candle.close)

    upper_wick = candle.high - body_top
    lower_wick = body_bottom - candle.low
    body = body_top - body_bottom

    upper_pct = upper_wick / full_range
    lower_pct = lower_wick / full_range
    body_pct = body / full_range

    if upper_pct >= rejection_threshold:
        cls = "upper_wick_rejection"
    elif lower_pct >= rejection_threshold:
        cls = "lower_wick_rejection"
    else:
        cls = "no_significant_wick"

    return WickMetrics(index, upper_wick, lower_wick, upper_pct, lower_pct, body_pct, cls)


def find_significant_wicks(candles: List[Candle], rejection_threshold: float = 0.4, min_range_pct: float = 0.001) -> List[WickMetrics]:
    """Scans candles for wicks that represent meaningful rejection,
    filtering out near-zero-range candles (illiquid/noise ticks)."""
    results = []
    for i, c in enumerate(candles):
        if c.close == 0:
            continue
        range_pct = (c.high - c.low) / c.close
        if range_pct < min_range_pct:
            continue
        wm = analyze_candle_wicks(c, i, rejection_threshold)
        if wm.classification != "no_significant_wick" and wm.classification != "no_range":
            results.append(wm)
    return results


@dataclass
class WickFibZone:
    wick_high: float
    wick_low: float
    level_0382: float
    level_05: float
    level_0618: float
    level_0786: float
    direction: str   # "bullish_wick" (lower wick, potential support zone) or "bearish_wick"


def compute_wick_fibonacci(candle: Candle, custom_levels: Optional[List[float]] = None) -> dict:
    """Builds Fibonacci retracement levels from a candle's wick range
    specifically (not the whole candle body-to-body swing) — per the
    spec's explicit request for wick-derived Fib zones."""
    levels = custom_levels or [0.382, 0.5, 0.618, 0.786]

    body_top = max(candle.open, candle.close)
    body_bottom = min(candle.open, candle.close)

    zones = {}
    if candle.high > body_top:  # has an upper wick
        wick_range = candle.high - body_top
        zones["upper_wick"] = {
            f"{lvl}": round(candle.high - wick_range * lvl, 4) for lvl in levels
        }
    if body_bottom > candle.low:  # has a lower wick
        wick_range = body_bottom - candle.low
        zones["lower_wick"] = {
            f"{lvl}": round(candle.low + wick_range * lvl, 4) for lvl in levels
        }
    return zones


def wick_reaction_zone(candles: List[Candle], lookback: int = 20) -> Optional[dict]:
    """Identifies the most significant recent wick and returns it as a
    'reaction zone' — the price band between the wick extreme and the
    body, which price often revisits. This is descriptive, not
    predictive: it reports where the zone is and why it's flagged."""
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    wicks = find_significant_wicks(recent)
    if not wicks:
        return None

    strongest = max(wicks, key=lambda w: max(w.upper_wick_pct_of_range, w.lower_wick_pct_of_range))
    c = recent[strongest.candle_index]
    body_top = max(c.open, c.close)
    body_bottom = min(c.open, c.close)

    if strongest.classification == "upper_wick_rejection":
        zone = {"zone_high": c.high, "zone_low": body_top, "type": "upper_wick_rejection",
                "explanation": (
                    f"Upper wick occupies {strongest.upper_wick_pct_of_range:.0%} of this candle's "
                    f"range — price was rejected from {c.high:.4f} back down to {body_top:.4f}. "
                    f"This zone ({body_top:.4f}-{c.high:.4f}) is a common area for price to react "
                    f"if revisited, though repeated tests can also exhaust the level."
                )}
    else:
        zone = {"zone_high": body_bottom, "zone_low": c.low, "type": "lower_wick_rejection",
                "explanation": (
                    f"Lower wick occupies {strongest.lower_wick_pct_of_range:.0%} of this candle's "
                    f"range — price was rejected from {c.low:.4f} back up to {body_bottom:.4f}. "
                    f"This zone ({c.low:.4f}-{body_bottom:.4f}) is a common area for price to react "
                    f"if revisited."
                )}
    return zone
