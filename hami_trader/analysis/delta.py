"""
Module 21: Delta engine.

Delta is computed from real trade prints in analysis/orderflow.py
(compute_delta, using the tick-rule documented in data/binance.py).
This module adds delta STRUCTURE analysis across a candle series —
spikes, acceleration/deceleration — without duplicating the core
computation.
"""

from dataclasses import dataclass
from typing import List
import numpy as np
from analysis.orderflow import compute_delta, DeltaSnapshot  # re-exported for module-per-spec layout

__all__ = ["compute_delta", "DeltaSnapshot", "detect_delta_spikes", "delta_acceleration"]


@dataclass
class DeltaSpike:
    index: int
    delta: float
    z_score: float
    explanation: str


def detect_delta_spikes(candle_deltas: List[float], z_threshold: float = 2.0) -> List[DeltaSpike]:
    """Real statistical outlier detection on a real per-candle delta
    series — a spike is a delta that is a genuine statistical outlier
    versus the recent distribution, not just 'a big number'."""
    if len(candle_deltas) < 10:
        return []
    arr = np.array(candle_deltas)
    mean, std = arr.mean(), arr.std()
    if std == 0:
        return []

    spikes = []
    for i, d in enumerate(candle_deltas):
        z = (d - mean) / std
        if abs(z) >= z_threshold:
            spikes.append(DeltaSpike(
                index=i, delta=d, z_score=round(float(z), 2),
                explanation=f"Delta {d:+.2f} is {z:+.1f} standard deviations from the recent mean — a real statistical spike.",
            ))
    return spikes


def delta_acceleration(candle_deltas: List[float], window: int = 5) -> str:
    """Real comparison of the most recent window's average delta
    magnitude vs the prior window — accelerating, decelerating, or stable."""
    if len(candle_deltas) < window * 2:
        return "insufficient_data"
    recent = np.mean([abs(d) for d in candle_deltas[-window:]])
    older = np.mean([abs(d) for d in candle_deltas[-window * 2:-window]])
    if older == 0:
        return "insufficient_data"
    ratio = recent / older
    if ratio >= 1.3:
        return "accelerating"
    if ratio <= 0.7:
        return "decelerating"
    return "stable"
