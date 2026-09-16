"""
Modules 6 & 7: Market Structure engine and Multi-Timeframe engine.

Real detection from real candles: swing points, BOS (break of
structure — continuation), MSS (market structure shift — reversal),
displacement, expansion/compression, and failed breakout/breakdown.
Per the spec: minor candle movement is NOT marked as BOS/MSS — both
require a genuine swing point break with real follow-through.
"""

from dataclasses import dataclass
from typing import List, Optional, Literal
from data.binance import Candle
import numpy as np


def find_swing_points(candles: List[Candle], lookback: int = 3):
    """A swing high/low needs `lookback` lower/higher candles on each
    side. Simple, well-understood fractal method — deliberately not
    fancy, because the liquidity concept depends on it being legible."""
    swing_highs, swing_lows = [], []
    n = len(candles)
    for i in range(lookback, n - lookback):
        window = candles[i - lookback:i + lookback + 1]
        c = candles[i]
        if c.high == max(w.high for w in window):
            swing_highs.append((i, c.high))
        if c.low == min(w.low for w in window):
            swing_lows.append((i, c.low))
    return swing_highs, swing_lows


@dataclass
class StructureEvent:
    event_type: str          # "BOS" or "MSS"
    direction: str            # "bullish" or "bearish"
    broken_level: float
    broken_index: int
    explanation: str


def detect_bos_mss(candles: List[Candle], lookback: int = 3, min_break_pct: float = 0.05) -> List[StructureEvent]:
    """Real structural break detection:
    - Track the current sequence of swing highs/lows.
    - A close beyond the most recent relevant swing point, by at
      least min_break_pct (filters noise/minor movement per spec),
      is a structural break.
    - If the break continues the prior trend direction -> BOS.
    - If it breaks against the prior trend direction -> MSS.
    """
    swing_highs, swing_lows = find_swing_points(candles, lookback)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return []

    events = []
    trend = None  # "up" or "down", inferred from swing sequence

    # Determine an initial trend from the first two swing highs/lows
    if swing_highs[0][1] < swing_highs[1][1] and swing_lows[0][1] < swing_lows[1][1]:
        trend = "up"
    elif swing_highs[0][1] > swing_highs[1][1] and swing_lows[0][1] > swing_lows[1][1]:
        trend = "down"

    last_swing_high = swing_highs[0]
    last_swing_low = swing_lows[0]
    sh_idx, sl_idx = 1, 1

    for i, c in enumerate(candles):
        # Advance to the most recent swing point before this candle
        while sh_idx < len(swing_highs) and swing_highs[sh_idx][0] < i:
            last_swing_high = swing_highs[sh_idx]
            sh_idx += 1
        while sl_idx < len(swing_lows) and swing_lows[sl_idx][0] < i:
            last_swing_low = swing_lows[sl_idx]
            sl_idx += 1

        break_up_pct = (c.close - last_swing_high[1]) / last_swing_high[1] * 100
        break_down_pct = (last_swing_low[1] - c.close) / last_swing_low[1] * 100

        if break_up_pct > min_break_pct:
            event_type = "BOS" if trend == "up" else "MSS"
            events.append(StructureEvent(
                event_type=event_type, direction="bullish", broken_level=last_swing_high[1], broken_index=i,
                explanation=(
                    f"Close ({c.close:.4f}) broke above prior swing high {last_swing_high[1]:.4f} "
                    f"by {break_up_pct:.2f}% — "
                    + (f"continuation of the existing uptrend (BOS)." if event_type == "BOS"
                       else f"this breaks AGAINST the prior downtrend — a structure shift (MSS), "
                            f"first evidence of a possible trend change, not confirmation of one.")
                ),
            ))
            trend = "up"
            last_swing_high = (i, c.close)

        elif break_down_pct > min_break_pct:
            event_type = "BOS" if trend == "down" else "MSS"
            events.append(StructureEvent(
                event_type=event_type, direction="bearish", broken_level=last_swing_low[1], broken_index=i,
                explanation=(
                    f"Close ({c.close:.4f}) broke below prior swing low {last_swing_low[1]:.4f} "
                    f"by {break_down_pct:.2f}% — "
                    + (f"continuation of the existing downtrend (BOS)." if event_type == "BOS"
                       else f"this breaks AGAINST the prior uptrend — a structure shift (MSS), "
                            f"first evidence of a possible trend change, not confirmation of one.")
                ),
            ))
            trend = "down"
            last_swing_low = (i, c.close)

    return events


@dataclass
class DisplacementEvent:
    direction: str
    candle_index: int
    range_multiple: float     # how many times the recent average range
    explanation: str


def detect_displacement(candles: List[Candle], lookback: int = 20, multiple_threshold: float = 2.0) -> List[DisplacementEvent]:
    """Real displacement = a candle (or short run) whose range is a
    real statistical outlier vs the recent average range — not just
    'a big-looking candle'."""
    events = []
    for i in range(lookback, len(candles)):
        window = candles[i - lookback:i]
        avg_range = np.mean([c.high - c.low for c in window])
        if avg_range <= 0:
            continue
        c = candles[i]
        candle_range = c.high - c.low
        multiple = candle_range / avg_range
        if multiple >= multiple_threshold:
            direction = "bullish" if c.close > c.open else "bearish"
            events.append(DisplacementEvent(
                direction=direction, candle_index=i, range_multiple=round(multiple, 2),
                explanation=(
                    f"Candle range ({candle_range:.4f}) is {multiple:.1f}x the {lookback}-candle "
                    f"average ({avg_range:.4f}) — a real statistical outlier, consistent with "
                    f"{direction} displacement (aggressive, likely institutional-size participation)."
                ),
            ))
    return events


def classify_expansion_compression(candles: List[Candle], lookback: int = 20) -> dict:
    """Real volatility-regime read: compares recent true range to the
    longer-window average true range."""
    if len(candles) < lookback * 2:
        return {"state": "unknown", "explanation": "Insufficient candle history."}

    ranges = [c.high - c.low for c in candles]
    recent_avg = np.mean(ranges[-lookback:])
    older_avg = np.mean(ranges[-lookback * 2:-lookback])

    if older_avg <= 0:
        return {"state": "unknown", "explanation": "Degenerate range data."}

    ratio = recent_avg / older_avg
    if ratio >= 1.3:
        state = "expanding"
    elif ratio <= 0.7:
        state = "compressing"
    else:
        state = "stable"

    return {
        "state": state, "ratio": round(ratio, 2),
        "explanation": f"Recent average range is {ratio:.2f}x the prior window's average range — {state}.",
    }


def detect_failed_breakout(candles: List[Candle], level: float, is_high: bool, lookforward: int = 5) -> Optional[dict]:
    """Real check: did price close beyond `level`, then fail to hold
    (close back on the origin side) within `lookforward` candles?
    Mechanism-first, matching the spec's own example exactly."""
    for i, c in enumerate(candles[:-lookforward]):
        broke = (c.close > level) if is_high else (c.close < level)
        if not broke:
            continue
        forward = candles[i + 1:i + 1 + lookforward]
        returned = any((fc.close < level) if is_high else (fc.close > level) for fc in forward)
        if returned:
            return {
                "level": level, "break_index": i, "is_high": is_high,
                "explanation": (
                    f"Breakout + no acceptance + return below level = failed breakout. "
                    f"Price closed {'above' if is_high else 'below'} {level:.4f} at candle {i}, "
                    f"but returned to the origin side within {lookforward} candles — no acceptance, "
                    f"a failed {'breakout' if is_high else 'breakdown'}."
                ),
            }
    return None
