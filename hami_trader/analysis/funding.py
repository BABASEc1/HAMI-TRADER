"""
Module 24: Funding engine.

Real data from Binance Futures REST (futures_funding_rate). Includes
history, not just the latest value, so expansion/compression can
actually be measured rather than asserted.
"""

from dataclasses import dataclass
from typing import List
from data.binance import DataUnavailableError


@dataclass
class FundingState:
    current_rate: float
    history: List[float]           # most recent last
    is_extreme: bool
    trend: str                     # "expanding", "compressing", "stable"
    explanation: str

EXTREME_THRESHOLD = 0.0005   # 0.05% per 8h funding interval — a commonly used "stretched" line


def fetch_funding_history(client, symbol: str, limit: int = 20) -> List[dict]:
    try:
        history = client.futures_funding_rate(symbol=symbol, limit=limit)
    except Exception as e:
        raise DataUnavailableError(f"Funding history for {symbol}: {type(e).__name__} — {e}")
    if not history:
        raise DataUnavailableError(f"Funding history for {symbol}: empty response")
    return history


def analyze_funding(history: List[dict]) -> FundingState:
    rates = [float(h["fundingRate"]) for h in history]
    current = rates[-1]
    is_extreme = abs(current) > EXTREME_THRESHOLD

    if len(rates) >= 4:
        recent_avg = sum(abs(r) for r in rates[-2:]) / 2
        older_avg = sum(abs(r) for r in rates[-4:-2]) / 2
        if recent_avg > older_avg * 1.3:
            trend = "expanding"
        elif recent_avg < older_avg * 0.7:
            trend = "compressing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    explanation = (
        f"Current funding {current:.4%} "
        f"({'positive — longs pay shorts' if current > 0 else 'negative — shorts pay longs' if current < 0 else 'neutral'}). "
        + (f"This is stretched relative to the typical ~0.01-0.03% range — costly to hold against the crowd. "
           if is_extreme else "Within a normal range. ")
        + f"Funding has been {trend} over the recent history sampled."
    )

    return FundingState(current_rate=current, history=rates, is_extreme=is_extreme,
                         trend=trend, explanation=explanation)
