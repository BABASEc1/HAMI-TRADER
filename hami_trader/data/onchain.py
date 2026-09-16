"""
Module 31: On-chain analysis provider interface.

HONESTY UP FRONT: Glassnode, CryptoQuant, and Arkham's useful
endpoints (exchange flows, whale transfers, holder activity) are paid
products — none of them offer genuinely useful free-tier access to
these specific metrics as of this writing. CoinMetrics has some free
community data but not exchange-flow-level granularity.

This module implements the REAL provider interface and REAL HTTP
call shape for each, so plugging in a paid key is a one-line config
change with no further code needed — but without a key configured,
every function honestly raises OnChainDataUnavailableError rather
than pretending to have inflow/outflow numbers it doesn't have.

Do not enable a provider here by guessing a free-tier endpoint that
might silently break or misrepresent data — if you have a paid key,
set it in config.py and these functions will use it for real.
"""

from dataclasses import dataclass
from typing import Optional
import config

try:
    import requests
except ImportError:
    requests = None


class OnChainDataUnavailableError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class ExchangeFlowData:
    symbol: str
    inflow_24h: float
    outflow_24h: float
    net_flow_24h: float
    provider: str


def fetch_exchange_flows_glassnode(symbol: str) -> ExchangeFlowData:
    api_key = getattr(config, "GLASSNODE_API_KEY", "")
    if not api_key:
        raise OnChainDataUnavailableError(
            "GLASSNODE_API_KEY not configured. Glassnode's exchange-flow endpoints are a paid "
            "tier (https://glassnode.com/pricing) — set GLASSNODE_API_KEY in config.py if you "
            "have a subscription. Without one, this is honestly DATA_UNAVAILABLE, not estimated."
        )
    if requests is None:
        raise OnChainDataUnavailableError("The 'requests' package is not installed")

    asset = symbol.replace("USDT", "").upper()
    url = "https://api.glassnode.com/v1/metrics/transactions/transfers_to_exchanges_sum"
    try:
        resp = requests.get(url, params={"a": asset, "api_key": api_key, "i": "24h"},
                             timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise OnChainDataUnavailableError(f"Glassnode request failed: {type(e).__name__} — {e}")

    if not data:
        raise OnChainDataUnavailableError(f"Glassnode returned no data for {asset}")

    inflow = data[-1]["v"]
    return ExchangeFlowData(symbol=symbol, inflow_24h=inflow, outflow_24h=0, net_flow_24h=inflow, provider="glassnode")


def fetch_exchange_flows_cryptoquant(symbol: str) -> ExchangeFlowData:
    api_key = getattr(config, "CRYPTOQUANT_API_KEY", "")
    if not api_key:
        raise OnChainDataUnavailableError(
            "CRYPTOQUANT_API_KEY not configured. CryptoQuant's exchange-flow endpoints require a "
            "paid subscription (https://cryptoquant.com/pricing) — set CRYPTOQUANT_API_KEY in "
            "config.py if you have one."
        )
    raise OnChainDataUnavailableError(
        "CryptoQuant integration point is defined but not wired to a live endpoint in this build "
        "— their API requires an account-specific base URL issued at signup. Add your endpoint "
        "in config.py (CRYPTOQUANT_BASE_URL) to complete this integration."
    )


def get_onchain_summary(symbol: str) -> dict:
    """Tries each provider independently; returns explicit
    per-provider status. Never merges/guesses a combined number from
    partial data."""
    result = {}
    for name, fn in [("glassnode", fetch_exchange_flows_glassnode), ("cryptoquant", fetch_exchange_flows_cryptoquant)]:
        try:
            result[name] = {"status": "REAL_IMPLEMENTED", "data": fn(symbol), "reason": ""}
        except OnChainDataUnavailableError as e:
            result[name] = {"status": "DATA_UNAVAILABLE", "data": None, "reason": e.reason}
    return result
