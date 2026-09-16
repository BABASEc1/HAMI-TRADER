"""
Modules 16 & 18: Liquidity Wall engine and Liquidity Add/Pull tracking.

Real temporal classification from a real quantity-over-time series
for a specific price level (data.orderbook_tracker.get_level_history).
Requires genuine accumulated history — with fewer than 3 snapshots,
this honestly reports insufficient history rather than guessing.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class WallState:
    price: float
    side: str                    # "bid" or "ask"
    initial_qty: float
    current_qty: Optional[float]
    max_observed_qty: float
    first_seen: float
    last_seen: float
    classification: str          # "DEFENDED", "CONSUMED", "REPLENISHED", "PULLED", "MOVED", "INSUFFICIENT_HISTORY"
    explanation: str


def classify_wall(price: float, side: str, level_history: List[Tuple[float, Optional[float]]],
                    price_reached_level: bool = False) -> WallState:
    """level_history: [(timestamp, qty_or_None), ...] from
    OrderBookTracker.get_level_history — real observed quantities
    over real time at this specific price."""
    if len(level_history) < 3:
        return WallState(
            price=price, side=side, initial_qty=0, current_qty=None, max_observed_qty=0,
            first_seen=level_history[0][0] if level_history else 0,
            last_seen=level_history[-1][0] if level_history else 0,
            classification="INSUFFICIENT_HISTORY",
            explanation=f"Only {len(level_history)} snapshots observed for this level — need at least "
                        f"3 to classify wall behavior. Let the app run longer to accumulate real history.",
        )

    present_points = [(t, q) for t, q in level_history if q is not None]
    if not present_points:
        return WallState(
            price=price, side=side, initial_qty=0, current_qty=None, max_observed_qty=0,
            first_seen=level_history[0][0], last_seen=level_history[-1][0],
            classification="INSUFFICIENT_HISTORY",
            explanation="This level was never actually observed with resting size in the tracked window.",
        )

    initial_qty = present_points[0][1]
    current_qty = level_history[-1][1]   # None if the level is gone right now
    max_qty = max(q for _, q in present_points)
    first_seen = present_points[0][0]
    last_seen = present_points[-1][0]

    if current_qty is None:
        # The level disappeared. Did price actually reach/execute through it,
        # or did it vanish before being tested? Only the caller (which knows
        # real trade prints near this level) can say for certain — we report
        # the observable fact and let spoofing.py combine it with trade data.
        classification = "CONSUMED" if price_reached_level else "PULLED"
        explanation = (
            f"Wall at {price:.4f} ({side}) was last seen with {present_points[-1][1]:.4f} size, "
            f"now absent. " + (
                "Price actually traded through this level around the same time — consistent with "
                "real execution (CONSUMED)." if price_reached_level else
                "Price did NOT reach this level before it vanished — consistent with the order "
                "being cancelled/pulled rather than executed (PULLED). A single disappearance is "
                "not proof of intent; see the Spoofing tab for repeated-pattern evidence."
            )
        )
    elif current_qty > initial_qty * 1.2:
        classification = "REPLENISHED"
        explanation = (
            f"Wall at {price:.4f} ({side}) grew from {initial_qty:.4f} to {current_qty:.4f} — "
            f"size was added/replenished, not just resting passively."
        )
    elif current_qty < initial_qty * 0.5:
        classification = "CONSUMED" if price_reached_level else "PULLED"
        explanation = (
            f"Wall at {price:.4f} ({side}) shrank from {initial_qty:.4f} to {current_qty:.4f} "
            f"(>50% reduction). " + (
                "Price traded through this range — consistent with real execution." if price_reached_level else
                "Price didn't reach this level — consistent with partial cancellation rather than fills."
            )
        )
    else:
        classification = "DEFENDED"
        explanation = (
            f"Wall at {price:.4f} ({side}) has held roughly steady ({initial_qty:.4f} -> "
            f"{current_qty:.4f}) across {len(present_points)} observations — being defended/maintained. "
            f"This does NOT automatically mean it will hold as support/resistance going forward."
        )

    return WallState(
        price=price, side=side, initial_qty=initial_qty, current_qty=current_qty,
        max_observed_qty=max_qty, first_seen=first_seen, last_seen=last_seen,
        classification=classification, explanation=explanation,
    )


def find_significant_walls(snapshot, min_qty_percentile: float = 90) -> List[Tuple[float, str, float]]:
    """Real statistical outlier detection on a real snapshot: returns
    (price, side, qty) for levels whose size is in the top
    percentile of that snapshot's own book — adaptive per symbol/book
    depth, not a fixed threshold."""
    import numpy as np
    results = []
    for side, book in [("bid", snapshot.bids), ("ask", snapshot.asks)]:
        if not book:
            continue
        qtys = list(book.values())
        threshold = np.percentile(qtys, min_qty_percentile)
        for price, qty in book.items():
            if qty >= threshold and qty > 0:
                results.append((price, side, qty))
    return sorted(results, key=lambda x: -x[2])
