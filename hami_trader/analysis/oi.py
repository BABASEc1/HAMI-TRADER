"""
Module 23: Open Interest engine.

Real data from Binance Futures REST (futures_open_interest_hist).
No key required — public endpoint. Raises DataUnavailableError
(never fabricates) if the symbol has no futures market.
"""

from dataclasses import dataclass
from data.binance import DataUnavailableError


@dataclass
class OIState:
    oi_now: float
    oi_change_pct: float
    funding_rate: float
    price_change_pct: float
    classification: str      # "new_longs" | "new_shorts" | "long_closing" | "short_covering" | "unclear"
    explanation: str


def fetch_oi(client, symbol: str, lookback_periods: int = 6) -> dict:
    try:
        oi_hist = client.futures_open_interest_hist(symbol=symbol, period="5m", limit=lookback_periods)
    except Exception as e:
        raise DataUnavailableError(f"OI for {symbol}: {type(e).__name__} — {e}")
    if not oi_hist:
        raise DataUnavailableError(f"OI for {symbol}: empty open-interest history returned")

    oi_now = float(oi_hist[-1]["sumOpenInterest"])
    oi_before = float(oi_hist[0]["sumOpenInterest"])
    oi_change_pct = (oi_now - oi_before) / oi_before * 100 if oi_before else 0.0
    return {"oi_now": oi_now, "oi_change_pct": oi_change_pct}


def classify_positioning(price_change_pct: float, oi_change_pct: float, funding_rate: float = 0.0, oi_threshold: float = 0.5) -> OIState:
    """Section 23 matrix:
    price up + OI up     -> new longs
    price up + OI down   -> short covering
    price down + OI up   -> new shorts
    price down + OI down -> long closing / liquidation
    Never claims certainty — always phrased as 'consistent with'.
    """
    price_up = price_change_pct > 0.05
    price_down = price_change_pct < -0.05
    oi_up = oi_change_pct > oi_threshold
    oi_down = oi_change_pct < -oi_threshold

    if price_up and oi_up:
        cls, explanation = "new_longs", (
            f"Price up {price_change_pct:+.2f}% with OI up {oi_change_pct:+.2f}% — "
            f"consistent with fresh long positioning, not just short covering. "
            f"Probabilistic read, not certainty."
        )
    elif price_up and oi_down:
        cls, explanation = "short_covering", (
            f"Price up {price_change_pct:+.2f}% with OI down {oi_change_pct:+.2f}% — "
            f"consistent with shorts covering rather than new conviction longs."
        )
    elif price_down and oi_up:
        cls, explanation = "new_shorts", (
            f"Price down {price_change_pct:+.2f}% with OI up {oi_change_pct:+.2f}% — "
            f"consistent with fresh short positioning being added."
        )
    elif price_down and oi_down:
        cls, explanation = "long_closing", (
            f"Price down {price_change_pct:+.2f}% with OI down {oi_change_pct:+.2f}% — "
            f"consistent with longs closing/being liquidated rather than aggressive new shorting."
        )
    else:
        cls, explanation = "unclear", (
            f"Price change ({price_change_pct:+.2f}%) or OI change ({oi_change_pct:+.2f}%) "
            f"too small to classify positioning confidently."
        )

    return OIState(oi_now=0, oi_change_pct=oi_change_pct, funding_rate=funding_rate,
                    price_change_pct=price_change_pct, classification=cls, explanation=explanation)
