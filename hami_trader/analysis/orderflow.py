"""
Sections 3 & 5: Footprint/Order Flow and Delta/CVD.

Built from the trade tape (aggTrades) using the tick-rule
approximation documented in data/binance_feed.py and README.md.

Per the spec's explicit instruction: this module does NOT label
positive delta as automatically bullish or negative delta as
automatically bearish. It reports the numbers and structural
observations (imbalance, stacking); direction/meaning is inferred
only in combination with price action in the dashboard layer.
"""

from dataclasses import dataclass
from typing import List
from data.binance import Trade
import config


@dataclass
class DeltaSnapshot:
    buy_volume: float
    sell_volume: float
    delta: float
    delta_pct: float          # delta as % of total volume
    total_volume: float
    trade_count: int


@dataclass
class CVDPoint:
    time: int
    cvd: float


def compute_delta(trades: List[Trade]) -> DeltaSnapshot:
    buy_vol = sum(t.qty for t in trades if t.side == "BUY")
    sell_vol = sum(t.qty for t in trades if t.side == "SELL")
    total = buy_vol + sell_vol
    delta = buy_vol - sell_vol
    delta_pct = (delta / total * 100) if total > 0 else 0.0
    return DeltaSnapshot(
        buy_volume=buy_vol, sell_volume=sell_vol, delta=delta,
        delta_pct=delta_pct, total_volume=total, trade_count=len(trades),
    )


def compute_cvd_series(trades: List[Trade], bucket_ms: int = 60_000) -> List[CVDPoint]:
    """Cumulative volume delta over time, bucketed (default 1 minute).
    Trades must be time-ordered (Binance aggTrades are)."""
    if not trades:
        return []

    buckets = {}
    for t in trades:
        bucket_key = t.time - (t.time % bucket_ms)
        signed_qty = t.qty if t.side == "BUY" else -t.qty
        buckets[bucket_key] = buckets.get(bucket_key, 0) + signed_qty

    series = []
    running = 0.0
    for ts in sorted(buckets.keys()):
        running += buckets[ts]
        series.append(CVDPoint(time=ts, cvd=running))
    return series


def cvd_slope(series: List[CVDPoint], lookback: int = 10) -> str:
    """Simple direction read on recent CVD — 'rising', 'falling', or
    'flat'. This is a description of what happened, not a signal."""
    if len(series) < lookback + 1:
        return "insufficient_data"
    recent = series[-lookback:]
    change = recent[-1].cvd - recent[0].cvd
    threshold = config.NOISE_THRESHOLDS[config.SENSITIVITY]["min_delta_btc"]
    if change > threshold:
        return "rising"
    if change < -threshold:
        return "falling"
    return "flat"


def detect_price_cvd_divergence(price_series: List[float], cvd_series: List[CVDPoint]) -> dict:
    """Compares the direction of price over the window vs the
    direction of CVD over the same window. Flags divergence — does
    NOT claim what happens next. That requires the confluence layer
    (Phase 2) combining this with liquidity/structure context."""
    if len(price_series) < 2 or len(cvd_series) < 2:
        return {"divergence": False, "explanation": "Insufficient data."}

    price_change = price_series[-1] - price_series[0]
    cvd_change = cvd_series[-1].cvd - cvd_series[0].cvd

    price_dir = "up" if price_change > 0 else "down" if price_change < 0 else "flat"
    cvd_dir = "up" if cvd_change > 0 else "down" if cvd_change < 0 else "flat"

    diverges = (price_dir == "up" and cvd_dir == "down") or (price_dir == "down" and cvd_dir == "up")

    explanation = (
        f"Price moved {price_dir} while CVD moved {cvd_dir}. "
        + (
            "This is a divergence: price is making progress in one direction "
            "while net aggressive order flow is not confirming it — evidence "
            "worth watching, not a standalone signal."
            if diverges else
            "Price and CVD are directionally aligned — order flow is "
            "confirming price movement in this window."
        )
    )
    return {"divergence": diverges, "price_dir": price_dir, "cvd_dir": cvd_dir, "explanation": explanation}


def detect_volume_imbalance(trades: List[Trade], min_ratio: float = None) -> List[dict]:
    """Flags price levels where buy or sell volume dominates the
    other by min_ratio — a basic version of 'stacked imbalance'
    (grouping consecutive imbalanced levels) is included."""
    min_ratio = min_ratio or config.NOISE_THRESHOLDS[config.SENSITIVITY]["min_imbalance_ratio"]

    tick = config.PROFILE_TICK_SIZE
    level_buy, level_sell = {}, {}
    for t in trades:
        key = round(t.price / tick) * tick
        if t.side == "BUY":
            level_buy[key] = level_buy.get(key, 0) + t.qty
        else:
            level_sell[key] = level_sell.get(key, 0) + t.qty

    imbalances = []
    all_levels = sorted(set(level_buy) | set(level_sell))
    for price in all_levels:
        b, s = level_buy.get(price, 0), level_sell.get(price, 0)
        if b > 0 and s > 0:
            ratio = b / s if b > s else s / b
            side = "buy" if b > s else "sell"
        elif b > 0:
            ratio, side = float("inf"), "buy"
        elif s > 0:
            ratio, side = float("inf"), "sell"
        else:
            continue
        if ratio >= min_ratio:
            imbalances.append({"price": price, "side": side, "ratio": round(ratio, 2) if ratio != float("inf") else None})

    # Stack detection: 3+ consecutive price levels imbalanced the same direction
    stacked = []
    run = []
    for imb in imbalances:
        if run and run[-1]["side"] == imb["side"] and abs(imb["price"] - run[-1]["price"]) <= tick * 1.5:
            run.append(imb)
        else:
            if len(run) >= 3:
                stacked.append(run)
            run = [imb]
    if len(run) >= 3:
        stacked.append(run)

    return imbalances, stacked
