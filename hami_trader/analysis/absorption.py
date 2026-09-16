"""
Module 19: Absorption engine.

Detects buy/sell absorption from real per-candle delta vs real price
progress, then classifies the OUTCOME using what price actually did
afterward: reversal, continuation, or failed. Per the spec: absorption
alone is never an automatic reversal signal — the outcome classification
requires the subsequent candles as evidence, not just the absorption
candle itself.
"""

from dataclasses import dataclass
from typing import List, Optional
from data.binance import Candle
import config


@dataclass
class AbsorptionEvent:
    side: str                  # "buy_side" or "sell_side"
    strength: str               # "low", "medium", "high"
    confirmed: bool            # kept for backward compatibility with synthesis.py
    outcome: str                # "pending", "reversal", "continuation", "failed"
    explanation: str


def detect_absorption(candles: List[Candle], deltas: List[float], lookforward: List[Candle] = None) -> Optional[AbsorptionEvent]:
    """candles/deltas aligned, most recent last. `lookforward`
    (optional): real candles AFTER the absorption window, used to
    classify the outcome as reversal/continuation/failed. Without it,
    outcome is "pending" — deliberately not guessed."""
    if len(candles) < 4 or len(deltas) < 4:
        return None

    window_c = candles[-4:]
    window_d = deltas[-4:]
    total_delta = sum(window_d)
    price_progress = window_c[-1].close - window_c[0].open
    price_range = sum(c.high - c.low for c in window_c) or 1e-9
    threshold = config.NOISE_THRESHOLDS[config.SENSITIVITY]["min_delta_btc"] * 2

    side = None
    if total_delta < -threshold:
        progress_ratio = abs(price_progress) / price_range
        if progress_ratio < 0.25:
            side = "sell_side"
    elif total_delta > threshold:
        progress_ratio = abs(price_progress) / price_range
        if progress_ratio < 0.25:
            side = "buy_side"

    if side is None:
        return None

    strength = "high" if abs(total_delta) > 5 else "medium"
    last = window_c[-1]
    confirmed = (last.close > last.open) if side == "sell_side" else (last.close < last.open)

    outcome, outcome_text = "pending", (
        "Confirmation of what happens next requires subsequent candles — not yet available in this check."
    )
    if lookforward:
        outcome, outcome_text = _classify_outcome(side, window_c[-1].close, lookforward)

    label = "SELLER ABSORPTION / BUYER PASSIVE CONTROL" if side == "sell_side" else "BUYER ABSORPTION / SELLER PASSIVE CONTROL"
    explanation = (
        f"{'Aggressive selling' if side == 'sell_side' else 'Aggressive buying'} over the last "
        f"{len(window_c)} candles (net delta {total_delta:.2f}) produced only "
        f"{abs(price_progress) / price_range:.0%} of the price range as net progress — "
        f"consistent with {label}. {outcome_text}"
    )

    return AbsorptionEvent(side=side, strength=strength, confirmed=confirmed, outcome=outcome, explanation=explanation)


def _classify_outcome(side: str, absorption_close: float, lookforward: List[Candle]) -> tuple:
    """Real classification using real subsequent candles — this is
    where 'absorption + reversal' vs 'absorption + continuation' vs
    'failed absorption' actually gets decided, per the spec's explicit
    instruction not to call absorption alone a reversal signal."""
    if not lookforward:
        return "pending", "No forward data available to classify the outcome yet."

    final_close = lookforward[-1].close
    move_pct = (final_close - absorption_close) / absorption_close * 100

    if side == "sell_side":
        # Absorption of selling -> reversal would mean price moves UP afterward
        if move_pct > 0.3:
            return "reversal", f"Confirmed: price moved {move_pct:+.2f}% higher after the absorption — reversal outcome."
        elif move_pct < -0.3:
            return "failed", f"Absorption failed: price continued {move_pct:+.2f}% lower despite the absorption — sellers ultimately won."
        else:
            return "continuation", f"Price stayed roughly flat ({move_pct:+.2f}%) — absorption held but hasn't produced a clear reversal yet."
    else:
        if move_pct < -0.3:
            return "reversal", f"Confirmed: price moved {move_pct:+.2f}% lower after the absorption — reversal outcome."
        elif move_pct > 0.3:
            return "failed", f"Absorption failed: price continued {move_pct:+.2f}% higher despite the absorption — buyers ultimately won."
        else:
            return "continuation", f"Price stayed roughly flat ({move_pct:+.2f}%) — absorption held but hasn't produced a clear reversal yet."


def track_repeated_absorption(events: List[AbsorptionEvent], min_repeats: int = 3) -> Optional[str]:
    """Real check across a sequence of real detected events — flags
    when the same side has been absorbed repeatedly, which is
    stronger evidence than a single occurrence."""
    if len(events) < min_repeats:
        return None
    recent = events[-min_repeats:]
    sides = {e.side for e in recent}
    if len(sides) == 1:
        return f"Repeated {recent[0].side} absorption detected across the last {min_repeats} occurrences — stronger evidence than a single event, still not a guarantee."
    return None
