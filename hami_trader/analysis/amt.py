"""
Section 2: Auction Market Theory / Market Profile.

Builds a volume profile from candle data (volume distributed across
the candle's price range, approximated — true tick-level distribution
would need trade-by-trade data, see note in build_profile) and derives
POC, VAH, VAL, HVN/LVN, and initial balance. Also classifies current
price behavior relative to value: rotating / attempting to leave /
accepted outside / rejected back in — per the spec's explicit
instruction NOT to treat VAH/VAL/POC as automatic signals.
"""

from dataclasses import dataclass
from typing import List, Dict
from data.binance import Candle
import config


@dataclass
class VolumeProfile:
    poc: float                  # Point of Control — price with most volume
    vah: float                  # Value Area High
    val: float                  # Value Area Low
    hvn: List[float]            # High Volume Nodes
    lvn: List[float]            # Low Volume Nodes
    price_volume: Dict[float, float]  # bucketed price -> volume


def auto_tick_size(reference_price: float) -> float:
    """Scales the volume-profile bucket size to the symbol's price
    magnitude. A fixed 5.0 USDT bucket is meaningless for a $0.01
    altcoin (every bucket would span 500x the price) and too fine for
    BTC at $100k+. Targets roughly 200-500 buckets across a typical
    daily range."""
    if reference_price <= 0:
        return config.PROFILE_TICK_SIZE
    magnitude = 10 ** (len(str(int(reference_price))) - 1) if reference_price >= 1 else reference_price
    if reference_price >= 1000:
        return round(reference_price * 0.0005, 2)
    elif reference_price >= 1:
        return round(reference_price * 0.001, 4)
    else:
        return round(reference_price * 0.002, 8)


def build_profile(candles: List[Candle], tick_size: float = None) -> VolumeProfile:
    """Distributes each candle's volume evenly across its high-low
    range, bucketed by tick_size. This is the standard approximation
    when only OHLCV candles are available (no raw trade tape for the
    whole window). It's good enough for POC/VAH/VAL in practice, but
    a trade-level profile (using get_recent_trades) is more precise
    for short/recent windows — see build_profile_from_trades below.
    """
    tick_size = tick_size or config.PROFILE_TICK_SIZE
    buckets: Dict[float, float] = {}

    for c in candles:
        if c.high == c.low:
            buckets[round(c.open / tick_size) * tick_size] = buckets.get(
                round(c.open / tick_size) * tick_size, 0) + c.volume
            continue
        n_buckets = max(1, int((c.high - c.low) / tick_size))
        vol_per_bucket = c.volume / n_buckets
        price = c.low
        while price <= c.high:
            key = round(price / tick_size) * tick_size
            buckets[key] = buckets.get(key, 0) + vol_per_bucket
            price += tick_size

    return _profile_from_buckets(buckets)


def build_profile_from_trades(trades, tick_size: float = None) -> VolumeProfile:
    """More precise profile built directly from trade prints — use
    this for the current session/day where you have the full trade
    tape, rather than the candle-approximation above."""
    tick_size = tick_size or config.PROFILE_TICK_SIZE
    buckets: Dict[float, float] = {}
    for t in trades:
        key = round(t.price / tick_size) * tick_size
        buckets[key] = buckets.get(key, 0) + t.qty
    return _profile_from_buckets(buckets)


def _profile_from_buckets(buckets: Dict[float, float]) -> VolumeProfile:
    if not buckets:
        raise ValueError("No volume data to build profile from")

    sorted_prices = sorted(buckets.keys())
    total_volume = sum(buckets.values())
    poc_price = max(buckets, key=buckets.get)

    # Expand outward from POC until value_area_pct of volume is captured
    target = total_volume * config.PROFILE_VALUE_AREA_PCT
    included = {poc_price}
    captured = buckets[poc_price]
    idx = sorted_prices.index(poc_price)
    lo, hi = idx, idx

    while captured < target and (lo > 0 or hi < len(sorted_prices) - 1):
        vol_below = buckets[sorted_prices[lo - 1]] if lo > 0 else -1
        vol_above = buckets[sorted_prices[hi + 1]] if hi < len(sorted_prices) - 1 else -1
        if vol_above >= vol_below:
            hi += 1
            captured += buckets[sorted_prices[hi]]
            included.add(sorted_prices[hi])
        else:
            lo -= 1
            captured += buckets[sorted_prices[lo]]
            included.add(sorted_prices[lo])

    vah = max(included)
    val = min(included)

    avg_vol = total_volume / len(buckets)
    hvn = sorted([p for p, v in buckets.items() if v > avg_vol * 1.5], reverse=True)[:5]
    lvn = sorted([p for p, v in buckets.items() if v < avg_vol * 0.5])[:5]

    return VolumeProfile(poc=poc_price, vah=vah, val=val, hvn=hvn, lvn=lvn, price_volume=buckets)


def classify_price_vs_value(current_price: float, profile: VolumeProfile) -> dict:
    """Per the spec: never treat VAH/VAL/POC as automatic buy/sell
    triggers. Just classify current price's relationship to value,
    and leave interpretation to the confluence/explanation layer."""
    if profile.val <= current_price <= profile.vah:
        state = "rotating_inside_value"
        explanation = (
            f"Price ({current_price:.1f}) is inside the value area "
            f"({profile.val:.1f}-{profile.vah:.1f}). This typically reflects "
            f"balance/acceptance — two-sided trade — rather than directional intent."
        )
    elif current_price > profile.vah:
        state = "outside_value_above"
        explanation = (
            f"Price ({current_price:.1f}) is trading above the value area high "
            f"({profile.vah:.1f}). Whether this is acceptance (initiative buying, "
            f"likely to hold) or rejection (responsive selling pushing price back "
            f"in) requires watching subsequent candles — not something the "
            f"profile alone can tell you."
        )
    else:
        state = "outside_value_below"
        explanation = (
            f"Price ({current_price:.1f}) is trading below the value area low "
            f"({profile.val:.1f}). Same caveat: acceptance vs rejection needs "
            f"confirmation from what price does next, not the level itself."
        )

    return {"state": state, "explanation": explanation}


def initial_balance(candles: List[Candle], ib_periods: int = 2) -> dict:
    """First `ib_periods` candles of a session define the Initial
    Balance range. Caller is responsible for passing only the
    session's candles (see engine/dashboard.py session slicing)."""
    if len(candles) < ib_periods:
        return {"ib_high": None, "ib_low": None}
    ib_candles = candles[:ib_periods]
    return {
        "ib_high": max(c.high for c in ib_candles),
        "ib_low": min(c.low for c in ib_candles),
    }
