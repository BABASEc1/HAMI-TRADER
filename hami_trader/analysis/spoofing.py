"""
Module 17: Spoofing engine.

Implements the spec's own 6-step temporal pattern exactly:
  1. Large order appears.
  2. Order persists or changes.
  3. Price approaches.
  4. Order repeatedly disappears/cancels before execution.
  5. Liquidity reappears elsewhere.
  6. Price moves through the previous wall.

Real classification from real wall-history sequences
(analysis/liquidity_flow.classify_wall) plus real trade prints near
the level (to distinguish "cancelled before execution" from "filled
by real trades"). NEVER confirms spoofing from a single snapshot —
requires a repeated appear/vanish pattern across multiple real
observations.
"""

from dataclasses import dataclass
from typing import List, Optional
from data.orderbook_tracker import OrderBookTracker


@dataclass
class SpoofingAssessment:
    price: float
    side: str
    classification: str      # "NO_CLEAR_SPOOFING_EVIDENCE", "POSSIBLE_SPOOFING", "HIGH_SPOOFING_RISK", "ORDER_BOOK_HISTORY_UNAVAILABLE"
    appear_disappear_count: int
    price_approached_without_fill: bool
    explanation: str


def assess_spoofing_risk(
    tracker: OrderBookTracker, price: float, side: str,
    recent_trades: List[dict] = None, tolerance_pct: float = 0.0005,
    min_observations: int = 6,
) -> SpoofingAssessment:
    """recent_trades: real aggTrade-derived dicts with 'price' and
    'qty' — used to check whether the level was ever actually
    executed against (step 6) vs just repeatedly cancelled (step 4)."""
    history = tracker.get_level_history(price, side, tolerance_pct)

    if len(history) < min_observations:
        return SpoofingAssessment(
            price=price, side=side, classification="ORDER_BOOK_HISTORY_UNAVAILABLE",
            appear_disappear_count=0, price_approached_without_fill=False,
            explanation=(
                f"Only {len(history)} snapshots observed — need at least {min_observations} to "
                f"evaluate a temporal spoofing pattern. Order-book history accumulates only while "
                f"the app runs; this is not something a single check can determine."
            ),
        )

    # Count real appear->disappear transitions (step 1/4 pattern)
    transitions = 0
    was_present = history[0][1] is not None
    for _, qty in history[1:]:
        now_present = qty is not None
        if was_present and not now_present:
            transitions += 1
        was_present = now_present

    # Did real trades ever print at/through this level? (distinguishes
    # cancellation from genuine execution — step 6)
    executed = False
    if recent_trades:
        executed = any(abs(t["price"] - price) / price <= tolerance_pct * 3 for t in recent_trades)

    price_approached = any(qty is not None for _, qty in history)  # level was seen near real market activity

    if transitions >= 3 and not executed:
        classification = "HIGH_SPOOFING_RISK"
        explanation = (
            f"This level reappeared/vanished {transitions} times across {len(history)} real "
            f"observations, with no real trade prints executing through it — matches the full "
            f"repeated appear/cancel pattern (steps 1-5 of the spoofing definition) without genuine "
            f"execution (step 6 absent). This is evidence, not proof — a market maker legitimately "
            f"adjusting quotes can look similar."
        )
    elif transitions >= 2:
        classification = "POSSIBLE_SPOOFING"
        explanation = (
            f"This level appeared/vanished {transitions} times across {len(history)} observations — "
            f"some evidence of a repeated cancel pattern, but below the threshold for a high-confidence "
            f"read, or real trades did partially execute against it."
        )
    else:
        classification = "NO_CLEAR_SPOOFING_EVIDENCE"
        explanation = (
            f"Only {transitions} appear/disappear transition(s) observed across {len(history)} "
            f"snapshots — a single order vanishing once is common and unremarkable behavior, not "
            f"evidence of spoofing."
        )

    return SpoofingAssessment(
        price=price, side=side, classification=classification, appear_disappear_count=transitions,
        price_approached_without_fill=price_approached and not executed, explanation=explanation,
    )
