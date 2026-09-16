"""
Module 25: Liquidation engine.

Real-time-only by nature — see data/derivatives.py for the WebSocket
listener that actually collects events (!forceOrder@arr, Binance's
only public liquidation feed; there is no REST history endpoint for
market-wide liquidations). This module analyzes whatever real events
the listener has collected; it never fabricates a history.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class LiquidationAnalysis:
    total_events: int
    long_liquidations: int          # side == SELL (a long being force-closed)
    short_liquidations: int         # side == BUY
    total_long_qty: float
    total_short_qty: float
    is_cascade: bool
    dominant_side: Optional[str]
    explanation: str


def analyze_liquidations(events: List[dict], cascade_threshold: int = 8, imbalance_ratio: float = 2.0) -> LiquidationAnalysis:
    if not events:
        return LiquidationAnalysis(
            total_events=0, long_liquidations=0, short_liquidations=0,
            total_long_qty=0, total_short_qty=0, is_cascade=False, dominant_side=None,
            explanation="No liquidation events collected yet in this window. This requires the "
                        "background WebSocket listener to have been running — a single point-in-time "
                        "check has nothing to report.",
        )

    long_liqs = [e for e in events if e["side"] == "SELL"]
    short_liqs = [e for e in events if e["side"] == "BUY"]
    total_long_qty = sum(e["qty"] for e in long_liqs)
    total_short_qty = sum(e["qty"] for e in short_liqs)

    is_cascade = len(events) >= cascade_threshold
    dominant_side = None
    if long_liqs and short_liqs:
        if len(long_liqs) > len(short_liqs) * imbalance_ratio:
            dominant_side = "long_liquidations"
        elif len(short_liqs) > len(long_liqs) * imbalance_ratio:
            dominant_side = "short_liquidations"
    elif long_liqs:
        dominant_side = "long_liquidations"
    elif short_liqs:
        dominant_side = "short_liquidations"

    explanation = (
        f"{len(events)} real liquidation events observed ({len(long_liqs)} longs, "
        f"{len(short_liqs)} shorts). "
        + (f"This meets the cascade threshold ({cascade_threshold}+) — consistent with a "
           f"forced-selling/buying cascade in motion. " if is_cascade else "Below cascade threshold. ")
        + (f"Dominant side: {dominant_side}." if dominant_side else "No clear dominant side.")
    )

    return LiquidationAnalysis(
        total_events=len(events), long_liquidations=len(long_liqs), short_liquidations=len(short_liqs),
        total_long_qty=total_long_qty, total_short_qty=total_short_qty,
        is_cascade=is_cascade, dominant_side=dominant_side, explanation=explanation,
    )
