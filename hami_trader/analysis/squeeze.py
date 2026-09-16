"""
Module 26: Squeeze engine.

Combines real OI classification, real liquidation events, real price
velocity, and real funding into a squeeze-pressure score. Explicitly
does NOT call every pump/dump a squeeze — score only crosses into a
directional call above a documented threshold, and the explanation
always lists exactly what evidence contributed.
"""

from dataclasses import dataclass
from typing import Optional, List
from analysis.oi import OIState
from analysis.liquidation import LiquidationAnalysis


@dataclass
class SqueezeScore:
    score: float
    direction: Optional[str]
    explanation: str


def compute_squeeze_pressure(
    oi_state: OIState,
    liq_analysis: LiquidationAnalysis,
    price_velocity_pct: float,
    distance_to_liquidity_pct: Optional[float],
    funding_rate: float,
) -> SqueezeScore:
    score = 0.0
    reasons = []
    direction = None

    if oi_state.classification == "new_shorts":
        score += 25
        reasons.append("OI shows fresh short buildup")
        direction = "short_squeeze_risk"
    elif oi_state.classification == "new_longs":
        score += 25
        reasons.append("OI shows fresh long buildup")
        direction = "long_squeeze_risk"

    if liq_analysis.total_events > 0:
        if liq_analysis.dominant_side == "long_liquidations" and liq_analysis.is_cascade:
            score += 30
            reasons.append(f"{liq_analysis.long_liquidations} long liquidations observed — cascade evidence")
            direction = direction or "long_squeeze_risk"
        elif liq_analysis.dominant_side == "short_liquidations" and liq_analysis.is_cascade:
            score += 30
            reasons.append(f"{liq_analysis.short_liquidations} short liquidations observed — cascade evidence")
            direction = direction or "short_squeeze_risk"
    else:
        reasons.append("No liquidation stream history yet — score based on OI/funding/velocity only, not liquidation evidence")

    if abs(price_velocity_pct) > 1.0:
        score += 20
        reasons.append(f"Elevated price velocity ({price_velocity_pct:+.2f}%)")

    if abs(funding_rate) > 0.0005:
        score += 15
        reasons.append(f"Funding stretched ({funding_rate:.4%})")

    if distance_to_liquidity_pct is not None and abs(distance_to_liquidity_pct) < 0.5:
        score += 10
        reasons.append(f"Price near major liquidity ({distance_to_liquidity_pct:+.2f}%) — common stop-hunt zone")

    score = min(score, 100)
    explanation = (
        f"Squeeze pressure {score:.0f}/100 from: {'; '.join(reasons)}. "
        f"This threshold-based score requires MULTIPLE converging factors — a single fast "
        f"move alone does not trigger a squeeze call here."
    )
    # Deliberately conservative: needs real converging evidence, not just one factor
    return SqueezeScore(score=score, direction=direction if score >= 50 else None, explanation=explanation)
