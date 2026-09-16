"""
CoinGecko public API — used ONLY for data Binance doesn't expose
(BTC dominance, total market cap). No API key required for the free
public endpoints used here. Real HTTP calls, real JSON parsing, no
fabricated numbers.
"""

from dataclasses import dataclass
from typing import Optional
import config

try:
    import requests
except ImportError:
    requests = None


class ProviderUnavailableError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class GlobalMarketData:
    btc_dominance_pct: float
    total_market_cap_usd: float
    total_volume_24h_usd: float
    active_cryptocurrencies: int


def fetch_global_market_data() -> GlobalMarketData:
    if requests is None:
        raise ProviderUnavailableError("The 'requests' package is not installed")
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()["data"]
    except Exception as e:
        raise ProviderUnavailableError(f"CoinGecko /global request failed: {type(e).__name__} — {e}")

    return GlobalMarketData(
        btc_dominance_pct=data["market_cap_percentage"]["btc"],
        total_market_cap_usd=data["total_market_cap"]["usd"],
        total_volume_24h_usd=data["total_volume"]["usd"],
        active_cryptocurrencies=data.get("active_cryptocurrencies", 0),
    )


def search_coin(query: str) -> list:
    """Real coin search — used by the Market Browser to resolve a
    free-text name (e.g. 'ether') to a real known project, as a
    supplement to Binance's own symbol list. Returns [] on failure,
    not fabricated results."""
    if requests is None:
        return []
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/search",
                             params={"query": query}, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json().get("coins", [])
    except Exception:
        return []
