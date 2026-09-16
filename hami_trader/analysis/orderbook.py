"""
Module 15: DOM / Order Book engine.

Real metrics computable from a SINGLE real order-book snapshot
(spread, depth, imbalance) — these don't need history. Wall
tracking and spoofing (modules 16/17) DO need history and live in
analysis/liquidity_flow.py and analysis/spoofing.py, reading from
data/orderbook_tracker.py's real rolling history.
"""

from dataclasses import dataclass
from typing import Optional
from data.orderbook_tracker import OrderBookSnapshot


@dataclass
class DOMSnapshot:
    best_bid: float
    best_ask: float
    spread: float
    spread_pct: float
    bid_depth_top10: float      # sum of qty across top 10 bid levels
    ask_depth_top10: float
    imbalance_ratio: float      # bid_depth / ask_depth
    imbalance_state: str        # "bid_heavy", "ask_heavy", "balanced"
    largest_bid_wall: Optional[tuple]   # (price, qty)
    largest_ask_wall: Optional[tuple]


def analyze_dom(snapshot: OrderBookSnapshot, wall_std_multiplier: float = 2.5) -> DOMSnapshot:
    bids = sorted(snapshot.bids.items(), key=lambda x: -x[0])
    asks = sorted(snapshot.asks.items(), key=lambda x: x[0])

    if not bids or not asks:
        raise ValueError("Empty order book snapshot")

    best_bid, best_ask = bids[0][0], asks[0][0]
    spread = best_ask - best_bid
    spread_pct = spread / best_bid * 100 if best_bid else 0

    bid_depth = sum(q for _, q in bids[:10])
    ask_depth = sum(q for _, q in asks[:10])
    imbalance_ratio = bid_depth / ask_depth if ask_depth > 0 else float("inf")

    if imbalance_ratio > 1.5:
        imbalance_state = "bid_heavy"
    elif imbalance_ratio < 0.67:
        imbalance_state = "ask_heavy"
    else:
        imbalance_state = "balanced"

    largest_bid = max(bids, key=lambda x: x[1]) if bids else None
    largest_ask = max(asks, key=lambda x: x[1]) if asks else None

    return DOMSnapshot(
        best_bid=best_bid, best_ask=best_ask, spread=spread, spread_pct=spread_pct,
        bid_depth_top10=bid_depth, ask_depth_top10=ask_depth,
        imbalance_ratio=round(imbalance_ratio, 2) if imbalance_ratio != float("inf") else None,
        imbalance_state=imbalance_state, largest_bid_wall=largest_bid, largest_ask_wall=largest_ask,
    )
