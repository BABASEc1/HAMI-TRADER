"""
Modules 20 & 27: Failed Aggression / Trapped Aggressor engine and
Trapped Trader engine.

Two related but distinct real detectors:
1. detect_trapped_traders — a specific breakout/breakdown failure at
   a named liquidity level (section 27's "failed breakout traders").
2. detect_failed_aggression — a more general check: aggressive delta
   in one direction with little price progress against a level that
   HOLDS (section 20) — doesn't require a full breakout, just failed
   push.
Both always report: who was aggressive, where, what failed, the
invalidation level, and the likely exit/liquidity target.
"""

from dataclasses import dataclass
from typing import List, Optional
from data.binance import Candle


@dataclass
class TrapEvent:
    trap_type: str             # "long_trap" or "short_trap"
    level: float
    invalidation: float
    likely_exit_target: Optional[float]
    explanation: str


def detect_trapped_traders(candles: List[Candle], breakout_level: float, deltas: List[float],
                             next_target_level: Optional[float] = None) -> Optional[TrapEvent]:
    if len(candles) < 2 or len(deltas) < 2:
        return None

    breakout_candle = candles[-2]
    close_candle = candles[-1]

    if breakout_candle.high > breakout_level and deltas[-2] > 0:
        if close_candle.close < breakout_level:
            return TrapEvent(
                trap_type="long_trap", level=breakout_level, invalidation=breakout_candle.high,
                likely_exit_target=next_target_level,
                explanation=(
                    f"Aggressive buyers pushed price above {breakout_level:.4f} (delta {deltas[-2]:+.2f}), "
                    f"but price has closed back below it. These buyers are likely now underwater — "
                    f"their exit selling becomes future liquidity if price revisits their entry near "
                    f"{breakout_level:.4f}. Invalidation of the trap read: a reclaim and close back above "
                    f"{breakout_candle.high:.4f}."
                    + (f" Likely exit/liquidity target if the trap resolves lower: {next_target_level:.4f}." if next_target_level else "")
                ),
            )

    if breakout_candle.low < breakout_level and deltas[-2] < 0:
        if close_candle.close > breakout_level:
            return TrapEvent(
                trap_type="short_trap", level=breakout_level, invalidation=breakout_candle.low,
                likely_exit_target=next_target_level,
                explanation=(
                    f"Aggressive sellers pushed price below {breakout_level:.4f} (delta {deltas[-2]:+.2f}), "
                    f"but price has closed back above it. These sellers are likely now underwater — "
                    f"their covering becomes future buy pressure if price revisits their entry near "
                    f"{breakout_level:.4f}. Invalidation of the trap read: a breakdown and close back below "
                    f"{breakout_candle.low:.4f}."
                    + (f" Likely exit/liquidity target if the trap resolves higher: {next_target_level:.4f}." if next_target_level else "")
                ),
            )
    return None


@dataclass
class FailedAggressionEvent:
    aggressor_side: str        # "buyers" or "sellers"
    level_defended: float
    invalidation: float
    likely_exit_target: Optional[float]
    explanation: str


def detect_failed_aggression(
    candles: List[Candle], deltas: List[float], defended_level: float,
    min_delta: float = 3.0, max_progress_pct: float = 0.3, next_target_level: Optional[float] = None,
) -> Optional[FailedAggressionEvent]:
    """More general than a breakout trap: aggressive delta pushing
    toward `defended_level` (e.g. a resistance/support) without
    meaningfully breaking or moving through it."""
    if len(candles) < 3 or len(deltas) < 3:
        return None

    window_c = candles[-3:]
    window_d = deltas[-3:]
    total_delta = sum(window_d)
    price_progress = window_c[-1].close - window_c[0].open

    if total_delta > min_delta:
        # aggressive buying toward resistance
        if window_c[-1].high >= defended_level * 0.999 and abs(price_progress) / max(defended_level, 1e-9) * 100 < max_progress_pct:
            return FailedAggressionEvent(
                aggressor_side="buyers", level_defended=defended_level,
                invalidation=defended_level * 1.002, likely_exit_target=next_target_level,
                explanation=(
                    f"Buyers were aggressive (delta {total_delta:+.2f}) pushing toward {defended_level:.4f}, "
                    f"but made little net progress ({price_progress:+.4f}) — the level is holding. These "
                    f"buyers may be trapped if price now turns down; invalidation of this read is a clean "
                    f"break and acceptance above {defended_level * 1.002:.4f}."
                    + (f" Likely exit/liquidity target: {next_target_level:.4f}." if next_target_level else "")
                ),
            )
    elif total_delta < -min_delta:
        if window_c[-1].low <= defended_level * 1.001 and abs(price_progress) / max(defended_level, 1e-9) * 100 < max_progress_pct:
            return FailedAggressionEvent(
                aggressor_side="sellers", level_defended=defended_level,
                invalidation=defended_level * 0.998, likely_exit_target=next_target_level,
                explanation=(
                    f"Sellers were aggressive (delta {total_delta:+.2f}) pushing toward {defended_level:.4f}, "
                    f"but made little net progress ({price_progress:+.4f}) — the level is holding. These "
                    f"sellers may be trapped if price now turns up; invalidation of this read is a clean "
                    f"break and acceptance below {defended_level * 0.998:.4f}."
                    + (f" Likely exit/liquidity target: {next_target_level:.4f}." if next_target_level else "")
                ),
            )
    return None
