"""
Module 15/17 of the spec: correlation with BTC/ETH/related assets.

Real Pearson correlation computed from actual close-price series —
no fabricated numbers. Flags abnormal relative strength/weakness
(divergence from typical correlation) as requested.
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np
from data.binance import BinanceFeed, Candle, DataUnavailableError


@dataclass
class CorrelationResult:
    symbol_a: str
    symbol_b: str
    correlation: float           # -1 to 1, Pearson coefficient
    window_periods: int
    interpretation: str


def compute_correlation(closes_a: List[float], closes_b: List[float]) -> float:
    n = min(len(closes_a), len(closes_b))
    if n < 5:
        raise ValueError("Need at least 5 aligned data points to compute correlation")
    a = np.array(closes_a[-n:])
    b = np.array(closes_b[-n:])
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _interpret(corr: float) -> str:
    if corr >= 0.7:
        return "strong positive correlation — moves tend to track closely"
    if corr >= 0.3:
        return "moderate positive correlation"
    if corr > -0.3:
        return "weak/no meaningful correlation — largely independent moves"
    if corr > -0.7:
        return "moderate negative correlation"
    return "strong negative correlation — moves tend to oppose each other"


def correlation_report(symbol: str, compare_to: List[str] = None, interval: str = "1h", limit: int = 100) -> List[CorrelationResult]:
    compare_to = compare_to or ["BTCUSDT", "ETHUSDT"]
    results = []

    feed = BinanceFeed(symbol)
    symbol_candles = feed.get_klines(interval, limit=limit)
    symbol_closes = [c.close for c in symbol_candles]

    for other in compare_to:
        if other.upper() == symbol.upper():
            continue
        try:
            other_feed = BinanceFeed(other)
            other_candles = other_feed.get_klines(interval, limit=limit)
            other_closes = [c.close for c in other_candles]
            corr = compute_correlation(symbol_closes, other_closes)
            results.append(CorrelationResult(
                symbol_a=symbol, symbol_b=other, correlation=round(corr, 3),
                window_periods=min(len(symbol_closes), len(other_closes)),
                interpretation=_interpret(corr),
            ))
        except (DataUnavailableError, ValueError) as e:
            results.append(CorrelationResult(
                symbol_a=symbol, symbol_b=other, correlation=float("nan"),
                window_periods=0, interpretation=f"DATA_UNAVAILABLE: {e}",
            ))
    return results


def detect_relative_strength_weakness(symbol_change_pct: float, btc_change_pct: float, typical_corr: float) -> dict:
    """If historically correlated but currently diverging strongly,
    flag it as abnormal relative strength/weakness (section 15)."""
    if typical_corr < 0.3:
        return {"abnormal": False, "explanation": "Correlation with BTC is already weak — divergence isn't abnormal, it's expected."}

    diff = symbol_change_pct - btc_change_pct
    if abs(diff) < 1.0:
        return {"abnormal": False, "explanation": "Move is in line with typical BTC correlation — nothing abnormal."}

    direction = "strength" if diff > 0 else "weakness"
    return {
        "abnormal": True,
        "explanation": (
            f"Symbol normally correlates with BTC ({typical_corr:.2f}) but is currently "
            f"{diff:+.2f}pp {'ahead of' if diff > 0 else 'behind'} BTC's move — "
            f"abnormal relative {direction}, worth understanding why (news/fundamentals) "
            f"before assuming it's just BTC beta."
        ),
    }
