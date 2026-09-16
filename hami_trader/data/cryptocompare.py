"""
CryptoCompare public API — real fallback OHLCV provider used ONLY
when Binance itself is unreachable (per section 41's requested
provider architecture: Binance primary, CryptoCompare fallback). No
API key required for the free tier's basic historical endpoints used
here (rate-limited without a key, but functional).
"""

from dataclasses import dataclass
from typing import List
import config

try:
    import requests
except ImportError:
    requests = None


class ProviderUnavailableError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


INTERVAL_ENDPOINT = {
    "1m": "histominute", "3m": "histominute", "5m": "histominute", "15m": "histominute", "30m": "histominute",
    "1h": "histohour", "4h": "histohour", "1d": "histoday",
}
INTERVAL_AGGREGATE = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 1, "4h": 4, "1d": 1,
}


@dataclass
class FallbackCandle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


def fetch_fallback_klines(symbol: str, interval: str, limit: int = 200) -> List[FallbackCandle]:
    """symbol like 'BTCUSDT' -> split into fsym/tsym for CryptoCompare's API shape."""
    if requests is None:
        raise ProviderUnavailableError("The 'requests' package is not installed")

    fsym = symbol[:-4] if symbol.endswith("USDT") else symbol[:3]
    tsym = "USDT" if symbol.endswith("USDT") else symbol[3:]
    endpoint = INTERVAL_ENDPOINT.get(interval)
    if endpoint is None:
        raise ProviderUnavailableError(f"CryptoCompare has no matching interval for '{interval}'")

    url = f"https://min-api.cryptocompare.com/data/v2/{endpoint}"
    params = {"fsym": fsym, "tsym": tsym, "limit": limit, "aggregate": INTERVAL_AGGREGATE.get(interval, 1)}

    try:
        resp = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        raise ProviderUnavailableError(f"CryptoCompare request failed: {type(e).__name__} — {e}")

    if payload.get("Response") == "Error":
        raise ProviderUnavailableError(f"CryptoCompare error: {payload.get('Message', 'unknown')}")

    data = payload.get("Data", {}).get("Data", [])
    if not data:
        raise ProviderUnavailableError(f"CryptoCompare returned no data for {fsym}/{tsym}")

    return [
        FallbackCandle(
            open_time=d["time"] * 1000, open=d["open"], high=d["high"], low=d["low"],
            close=d["close"], volume=d.get("volumeto", 0), close_time=d["time"] * 1000,
        )
        for d in data
    ]
