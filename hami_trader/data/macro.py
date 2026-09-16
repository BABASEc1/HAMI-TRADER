"""
Module 32: Macro engine.

Real data from FRED (Federal Reserve Economic Data,
https://fred.stlouisfed.org) — the actual official source the spec
asks to prefer. Requires a free API key (instant signup, no approval
wait): https://fred.stlouisfed.org/docs/api/api_key.html

Without a key configured, every function here raises
MacroDataUnavailableError with that exact instruction — it does NOT
fabricate a CPI print or a fed funds rate.

FRED series IDs used (real, stable, official):
  DXY proxy       : DTWEXBGS  (Trade Weighted US Dollar Index, real FRED series;
                     FRED does not publish the ICE DXY ticker itself, so this
                     is the closest official substitute — documented, not hidden)
  10Y Treasury    : DGS10
  2Y Treasury     : DGS2
  Fed Funds Rate  : FEDFUNDS
  CPI (YoY infl.) : CPIAUCSL
  Core PPI        : PPIACO
  Unemployment    : UNRATE (proxy context around NFP)
VIX is NOT on FRED under a free-reusable series in real time reliably;
left as NOT_SUPPORTED_BY_PROVIDER here — see README for the honest
reason (CBOE's VIX is licensed data on most free APIs).
"""

from dataclasses import dataclass
from typing import Optional, List
import config

try:
    import requests
except ImportError:
    requests = None


class MacroDataUnavailableError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


FRED_SERIES = {
    "dxy_proxy": "DTWEXBGS",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "fed_funds_rate": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "ppi": "PPIACO",
    "unemployment": "UNRATE",
}

NOT_SUPPORTED = {"vix": "CBOE VIX is not freely available in real time via FRED or another no-key provider — licensed data."}


@dataclass
class MacroSeries:
    series_id: str
    label: str
    latest_value: float
    latest_date: str
    previous_value: Optional[float]
    change: Optional[float]


def fetch_fred_series(series_key: str, limit: int = 2) -> MacroSeries:
    if series_key in NOT_SUPPORTED:
        raise MacroDataUnavailableError(f"NOT_SUPPORTED_BY_PROVIDER: {NOT_SUPPORTED[series_key]}")
    if requests is None:
        raise MacroDataUnavailableError("The 'requests' package is not installed")
    api_key = getattr(config, "FRED_API_KEY", "")
    if not api_key:
        raise MacroDataUnavailableError(
            "FRED_API_KEY not configured — get a free key at "
            "https://fred.stlouisfed.org/docs/api/api_key.html and set it in "
            "config.py or the FRED_API_KEY environment variable."
        )

    series_id = FRED_SERIES.get(series_key)
    if series_id is None:
        raise MacroDataUnavailableError(f"Unknown macro series key: {series_key}")

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "sort_order": "desc", "limit": limit,
    }
    try:
        resp = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
    except Exception as e:
        raise MacroDataUnavailableError(f"FRED request failed for {series_id}: {type(e).__name__} — {e}")

    obs = [o for o in obs if o["value"] != "."]  # FRED uses "." for missing data points
    if not obs:
        raise MacroDataUnavailableError(f"FRED returned no valid observations for {series_id}")

    latest = obs[0]
    previous = obs[1] if len(obs) > 1 else None
    latest_val = float(latest["value"])
    prev_val = float(previous["value"]) if previous else None

    return MacroSeries(
        series_id=series_id, label=series_key, latest_value=latest_val, latest_date=latest["date"],
        previous_value=prev_val, change=(latest_val - prev_val) if prev_val is not None else None,
    )


def fetch_macro_snapshot() -> dict:
    """Fetches every configured series independently — one failing
    (e.g. missing key) doesn't block the others from reporting."""
    result = {}
    for key in list(FRED_SERIES.keys()) + list(NOT_SUPPORTED.keys()):
        try:
            result[key] = {"status": "REAL_IMPLEMENTED", "data": fetch_fred_series(key), "reason": ""}
        except MacroDataUnavailableError as e:
            status = "NOT_SUPPORTED" if key in NOT_SUPPORTED else "DATA_UNAVAILABLE"
            result[key] = {"status": status, "data": None, "reason": e.reason}
    return result
