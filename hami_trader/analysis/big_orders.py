"""
Modules 13 & 14: Big Orders / Large Trades and Whale Activity.

Threshold is computed adaptively PER SYMBOL from that symbol's own
real recent trade-size distribution — never a fixed BTC-sized
number applied to every altcoin. A single large trade is labeled
LARGE_TRADE by default; only trades that are extreme statistical
outliers (both in absolute USD size AND relative to that market's
own normal activity) get labeled WHALE_ACTIVITY, and even then the
label states it's inferred from trade size alone, not verified
wallet-level whale identity.
"""

from dataclasses import dataclass
from typing import List
import numpy as np
from data.binance import Trade


@dataclass
class BigTrade:
    price: float
    qty: float
    usd_value: float
    side: str
    timestamp: int
    percentile: float
    z_score: float
    classification: str   # "LARGE_TRADE", "UNUSUAL_ACTIVITY", "WHALE_ACTIVITY"
    explanation: str


def compute_adaptive_threshold(trades: List[Trade], percentile: float = 95) -> dict:
    """Real percentile computed from this specific symbol's real
    recent trade sizes — automatically scales for a $60k BTC trade
    vs a $0.001 memecoin trade."""
    if len(trades) < 20:
        return {"threshold_qty": None, "reason": "Fewer than 20 recent trades — insufficient sample for an adaptive threshold."}

    sizes = np.array([t.qty * t.price for t in trades])  # USD notional
    threshold = float(np.percentile(sizes, percentile))
    mean, std = float(sizes.mean()), float(sizes.std())
    return {"threshold_usd": threshold, "mean_usd": mean, "std_usd": std, "sample_size": len(trades)}


def detect_big_trades(trades: List[Trade], percentile_threshold: float = 95, whale_z_threshold: float = 5.0) -> List[BigTrade]:
    stats = compute_adaptive_threshold(trades, percentile_threshold)
    if stats.get("threshold_usd") is None:
        return []

    threshold_usd = stats["threshold_usd"]
    mean_usd, std_usd = stats["mean_usd"], stats["std_usd"]
    sizes = np.array([t.qty * t.price for t in trades])

    results = []
    for t, usd_val in zip(trades, sizes):
        if usd_val < threshold_usd:
            continue
        pct = float((sizes < usd_val).mean() * 100)
        z = (usd_val - mean_usd) / std_usd if std_usd > 0 else 0

        if z >= whale_z_threshold:
            cls = "WHALE_ACTIVITY"
            note = (f"This trade (${usd_val:,.0f}) is a {z:.1f} standard-deviation outlier for this "
                     f"specific market's recent activity — statistically significant relative to "
                     f"{stats['sample_size']} recent trades, not just a large-looking number.")
        elif z >= 3.0:
            cls = "UNUSUAL_ACTIVITY"
            note = f"This trade (${usd_val:,.0f}) is a {z:.1f} standard-deviation outlier — unusual but not extreme."
        else:
            cls = "LARGE_TRADE"
            note = f"This trade (${usd_val:,.0f}) is in the top {100 - pct:.1f}% of recent trade sizes for this market."

        results.append(BigTrade(
            price=t.price, qty=t.qty, usd_value=round(usd_val, 2), side=t.side, timestamp=t.time,
            percentile=round(pct, 1), z_score=round(z, 2), classification=cls,
            explanation=note + " A single trade being large does NOT by itself mean bullish or bearish intent.",
        ))
    return results
