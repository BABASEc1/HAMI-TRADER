"""
Module 8: Liquidity engine.

Produces a hierarchy of real liquidity pools (swing highs/lows,
PDH/PDL, equal highs/lows) tagged with type, timeframe, a
LOW/MEDIUM/HIGH/CRITICAL rank (timeframe-aware per the spec), and
fresh/tested/consumed status. Also detects real liquidity sweeps.
This module does NOT decide bullish/bearish — it reports what
happened; interpretation happens in synthesis.py combined with order flow.
"""

from dataclasses import dataclass
from typing import List, Literal
from data.binance import Candle
from analysis.structure import find_swing_points
import config

LiquidityStatus = Literal["fresh", "tested", "consumed"]
LiquidityRank = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class LiquidityLevel:
    price: float
    level_type: str
    timeframe: str
    strength: float
    status: LiquidityStatus = "fresh"
    touches: int = 0
    rank: LiquidityRank = "LOW"

    def distance_pct(self, current_price: float) -> float:
        return (self.price - current_price) / current_price * 100


@dataclass
class SweepEvent:
    level: LiquidityLevel
    swept_price: float
    candle_index: int
    reclaimed: bool
    explanation: str = ""


def _score_strength(timeframe: str, touches: int) -> float:
    base = config.TIMEFRAME_WEIGHT.get(timeframe, 1)
    return round(base + (touches - 1) * 0.5, 2)


def _rank_from_strength(strength: float) -> LiquidityRank:
    """Timeframe-aware ranking, per the spec's explicit requirement —
    strength already folds in TIMEFRAME_WEIGHT, so a 1d equal-highs
    cluster naturally ranks CRITICAL while a 1m swing point ranks LOW."""
    if strength >= 6:
        return "CRITICAL"
    if strength >= 4:
        return "HIGH"
    if strength >= 2:
        return "MEDIUM"
    return "LOW"


def build_liquidity_map(candles_by_tf: dict, current_price: float) -> List[LiquidityLevel]:
    levels: List[LiquidityLevel] = []

    for tf, candles in candles_by_tf.items():
        if len(candles) < 10:
            continue

        swing_highs, swing_lows = find_swing_points(candles)

        if tf == "1d" and len(candles) >= 2:
            prev_day = candles[-2]
            levels.append(LiquidityLevel(prev_day.high, "PDH", tf, _score_strength(tf, 1)))
            levels.append(LiquidityLevel(prev_day.low, "PDL", tf, _score_strength(tf, 1)))

        levels += _cluster_equal_levels(swing_highs, tf, "high")
        levels += _cluster_equal_levels(swing_lows, tf, "low")

        for _, price in swing_highs[-5:]:
            levels.append(LiquidityLevel(price, "swing_high", tf, _score_strength(tf, 1)))
        for _, price in swing_lows[-5:]:
            levels.append(LiquidityLevel(price, "swing_low", tf, _score_strength(tf, 1)))

    for lvl in levels:
        lvl.status = _infer_status(lvl, current_price)
        lvl.rank = _rank_from_strength(lvl.strength)

    levels.sort(key=lambda l: l.strength, reverse=True)
    return levels


def _cluster_equal_levels(points, tf: str, kind: str):
    if len(points) < 2:
        return []
    prices = sorted(p for _, p in points)
    clusters, current_cluster = [], [prices[0]]

    for p in prices[1:]:
        if abs(p - current_cluster[-1]) / current_cluster[-1] <= config.EQUAL_LEVEL_TOLERANCE_PCT:
            current_cluster.append(p)
        else:
            if len(current_cluster) >= 2:
                clusters.append(current_cluster)
            current_cluster = [p]
    if len(current_cluster) >= 2:
        clusters.append(current_cluster)

    label = "equal_highs" if kind == "high" else "equal_lows"
    out = []
    for cluster in clusters:
        avg_price = sum(cluster) / len(cluster)
        out.append(LiquidityLevel(avg_price, label, tf, _score_strength(tf, len(cluster)), touches=len(cluster)))
    return out


def _infer_status(level: LiquidityLevel, current_price: float) -> LiquidityStatus:
    dist = abs(level.distance_pct(current_price))
    return "tested" if dist < 0.05 else "fresh"


def detect_sweeps(levels: List[LiquidityLevel], candles: List[Candle]) -> List[SweepEvent]:
    events = []
    for lvl in levels:
        for i, c in enumerate(candles):
            swept_high = lvl.level_type in ("swing_high", "equal_highs", "PDH") and c.high > lvl.price and c.close < lvl.price
            swept_low = lvl.level_type in ("swing_low", "equal_lows", "PDL") and c.low < lvl.price and c.close > lvl.price
            if swept_high or swept_low:
                direction = "above" if swept_high else "below"
                events.append(SweepEvent(
                    level=lvl, swept_price=c.high if swept_high else c.low, candle_index=i, reclaimed=True,
                    explanation=(
                        f"Price traded {direction} the {lvl.level_type} at {lvl.price:.4f} "
                        f"({lvl.timeframe}, rank {lvl.rank}) but closed back on the other side — "
                        f"consistent with a liquidity sweep rather than genuine acceptance."
                    ),
                ))
    return events
