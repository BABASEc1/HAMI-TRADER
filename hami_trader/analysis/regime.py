"""
Section 1 (trend vs rotational/balanced regime) and part of section 17
(MARKET REGIME dashboard field).

Classifies the current market as Trending, Rotational/Balanced, or
Transition — used as context by other engines, never as a standalone
trade trigger.
"""

from dataclasses import dataclass
from typing import List
from data.binance import Candle
import numpy as np


@dataclass
class RegimeState:
    regime: str              # "trending", "rotational", "transition"
    directional_strength: float  # 0-1, how much of total movement was net directional
    explanation: str


def classify_regime(candles: List[Candle], lookback: int = 30) -> RegimeState:
    if len(candles) < lookback:
        lookback = len(candles)
    window = candles[-lookback:]

    closes = np.array([c.close for c in window])
    net_move = abs(closes[-1] - closes[0])
    path_length = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))

    # Efficiency ratio: net move / total path traveled.
    # Close to 1 = straight-line trend. Close to 0 = pure chop.
    efficiency = net_move / path_length if path_length > 0 else 0

    if efficiency >= 0.5:
        regime = "trending"
        explanation = (
            f"Price covered {net_move:.1f} net over a path length of "
            f"{path_length:.1f} (efficiency ratio {efficiency:.2f}) — most "
            f"movement contributed to net directional progress, consistent "
            f"with a trending regime."
        )
    elif efficiency <= 0.2:
        regime = "rotational"
        explanation = (
            f"Price covered only {net_move:.1f} net over a path length of "
            f"{path_length:.1f} (efficiency ratio {efficiency:.2f}) — most "
            f"movement was offsetting, consistent with balance/rotation "
            f"rather than trend."
        )
    else:
        regime = "transition"
        explanation = (
            f"Efficiency ratio {efficiency:.2f} is in between clear trend and "
            f"clear balance — treat this as a possible transition and lean on "
            f"lower-timeframe confirmation before assuming either regime."
        )

    return RegimeState(regime=regime, directional_strength=round(efficiency, 3), explanation=explanation)


def classify_full_regime(candles: List[Candle], volume_trend: str = "flat") -> dict:
    """Module 35: maps real efficiency-ratio + real volatility state
    (analysis.structure.classify_expansion_compression) + real volume
    trend into the fuller regime vocabulary the spec asks for.
    ACCUMULATING/DISTRIBUTING specifically requires rotational
    structure + rising volume — otherwise it's reported as
    ROTATIONAL/BALANCED without overclaiming an accumulation read."""
    from analysis.structure import classify_expansion_compression

    base = classify_regime(candles)
    vol_state = classify_expansion_compression(candles)

    if base.regime == "trending":
        label = "TRENDING"
    elif base.regime == "transition":
        label = "TRANSITIONING"
    elif vol_state["state"] == "expanding":
        label = "EXPANDING"
    elif vol_state["state"] == "compressing":
        label = "COMPRESSING"
    elif volume_trend == "rising":
        # Rotational + rising volume: real basis for accumulation/distribution,
        # but direction (accum vs distrib) needs price position context the
        # caller supplies — default to the more conservative label.
        label = "ROTATIONAL"
    else:
        label = "BALANCED"

    return {
        "label": label, "efficiency": base.directional_strength,
        "volatility_state": vol_state["state"],
        "explanation": f"{base.explanation} Volatility: {vol_state['explanation']}",
    }
