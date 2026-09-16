"""
Module 21: Historical/backtest comparison.

Finds real historical occurrences of a similar condition (using
actual historical klines fetched from Binance, going back
config.HISTORICAL_LOOKBACK_DAYS) and reports what happened afterward
— real computed statistics, not invented ones. Explicitly does not
present this as predictive.
"""

from dataclasses import dataclass
from typing import List, Callable
import numpy as np
from data.binance import Candle, DataUnavailableError
import config


@dataclass
class HistoricalOutcome:
    occurrence_time: int
    forward_return_pct: float
    max_favorable_excursion_pct: float
    max_adverse_excursion_pct: float


@dataclass
class HistoricalComparisonResult:
    condition_name: str
    occurrences_found: int
    lookback_days: int
    win_rate: float
    avg_forward_return_pct: float
    avg_mfe_pct: float
    avg_mae_pct: float
    outcomes: List[HistoricalOutcome]
    explanation: str


def fetch_historical_candles(client, symbol: str, interval: str = "1h") -> List[Candle]:
    """Real historical data via python-binance's get_historical_klines,
    which paginates automatically. This can be slow for long lookback
    windows on fine timeframes — that's the real cost of using real
    data, not something to fake around."""
    from datetime import datetime, timedelta
    start_str = (datetime.utcnow() - timedelta(days=config.HISTORICAL_LOOKBACK_DAYS)).strftime("%d %b %Y")
    try:
        raw = client.get_historical_klines(symbol, interval, start_str)
    except Exception as e:
        raise DataUnavailableError(f"historical_klines({interval}): {type(e).__name__} — {e}")

    return [
        Candle(open_time=k[0], open=float(k[1]), high=float(k[2]), low=float(k[3]),
               close=float(k[4]), volume=float(k[5]), close_time=k[6])
        for k in raw
    ]


def find_similar_setups(
    candles: List[Candle],
    condition_fn: Callable[[List[Candle], int], bool],
    condition_name: str,
    forward_window: int = 12,
) -> HistoricalComparisonResult:
    """condition_fn(candles, index) -> bool: returns True if the
    condition (e.g. 'price swept prior day low and closed back above
    it') holds at that index. Scans the whole historical series for
    every real occurrence, then measures what actually happened over
    the next `forward_window` candles."""
    outcomes = []

    for i in range(20, len(candles) - forward_window):
        if not condition_fn(candles, i):
            continue

        entry_price = candles[i].close
        forward = candles[i + 1:i + 1 + forward_window]
        if not forward:
            continue

        forward_return = (forward[-1].close - entry_price) / entry_price * 100
        mfe = max((c.high - entry_price) / entry_price * 100 for c in forward)
        mae = min((c.low - entry_price) / entry_price * 100 for c in forward)

        outcomes.append(HistoricalOutcome(
            occurrence_time=candles[i].open_time,
            forward_return_pct=round(forward_return, 2),
            max_favorable_excursion_pct=round(mfe, 2),
            max_adverse_excursion_pct=round(mae, 2),
        ))

    n = len(outcomes)
    if n == 0:
        return HistoricalComparisonResult(
            condition_name=condition_name, occurrences_found=0,
            lookback_days=config.HISTORICAL_LOOKBACK_DAYS, win_rate=0,
            avg_forward_return_pct=0, avg_mfe_pct=0, avg_mae_pct=0, outcomes=[],
            explanation=f"No occurrences of '{condition_name}' found in the last "
                        f"{config.HISTORICAL_LOOKBACK_DAYS} days of real data — "
                        f"nothing to compare against.",
        )

    win_rate = sum(1 for o in outcomes if o.forward_return_pct > 0) / n * 100
    avg_ret = float(np.mean([o.forward_return_pct for o in outcomes]))
    avg_mfe = float(np.mean([o.max_favorable_excursion_pct for o in outcomes]))
    avg_mae = float(np.mean([o.max_adverse_excursion_pct for o in outcomes]))

    return HistoricalComparisonResult(
        condition_name=condition_name, occurrences_found=n,
        lookback_days=config.HISTORICAL_LOOKBACK_DAYS, win_rate=round(win_rate, 1),
        avg_forward_return_pct=round(avg_ret, 2), avg_mfe_pct=round(avg_mfe, 2),
        avg_mae_pct=round(avg_mae, 2), outcomes=outcomes,
        explanation=(
            f"'{condition_name}' occurred {n} times in the last {config.HISTORICAL_LOOKBACK_DAYS} "
            f"days. Forward-looking {forward_window} candles later: {win_rate:.0f}% of occurrences "
            f"were positive, average return {avg_ret:+.2f}%, average max favorable excursion "
            f"{avg_mfe:+.2f}%, average max adverse excursion {avg_mae:+.2f}%. "
            f"This describes what happened historically — it is NOT a guarantee of what "
            f"will happen this time, and {n} occurrences is a {'small' if n < 30 else 'moderate'} "
            f"sample size."
        ),
    )


# --- Example real, reusable condition functions -----------------------

def condition_equal_lows_sweep_reclaim(candles: List[Candle], i: int, lookback: int = 20) -> bool:
    """Real condition: current candle wicks below the lowest low of
    the prior `lookback` candles but closes back above it."""
    if i < lookback:
        return False
    prior_low = min(c.low for c in candles[i - lookback:i])
    c = candles[i]
    return c.low < prior_low and c.close > prior_low


def condition_outside_range_rejection(candles: List[Candle], i: int, lookback: int = 20) -> bool:
    """Real condition: candle closes above the prior lookback-period
    high but the FOLLOWING candle immediately fails to hold above it."""
    if i < lookback or i + 1 >= len(candles):
        return False
    prior_high = max(c.high for c in candles[i - lookback:i])
    return candles[i].close > prior_high and candles[i + 1].close < prior_high
