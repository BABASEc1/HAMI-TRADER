"""
Module 13/15/25 of the spec: News and fundamentals.

Uses two REAL data sources:
1. CryptoPanic public API (https://cryptopanic.com/developers/api/) —
   requires a free API token (config.CRYPTOPANIC_API_TOKEN). Without
   one, CryptoPanic is skipped (not faked).
2. Binance's own announcements feed (public, no key) — official
   exchange source, always treated as CONFIRMED when present.

CLASSIFICATION HONESTY: "BULLISH/BEARISH/NEUTRAL/HIGH-RISK" tagging
here is a keyword/heuristic classifier over headlines, not a trained
sentiment model and not a guarantee of market impact. It's labeled as
such in the output. CONFIRMED vs RUMOR is based on source tier
(config.OFFICIAL_NEWS_DOMAINS), not fact-checking the claim itself.
"""

import time
from dataclasses import dataclass
from typing import List, Optional
import config

try:
    import requests
except ImportError:
    requests = None


class NewsUnavailableError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published_at: str        # ISO timestamp, as reported by the source
    is_confirmed: bool       # True if from an official-tier source
    sentiment: str           # "BULLISH", "BEARISH", "NEUTRAL", "HIGH_RISK"
    sentiment_basis: str     # explains why it was classified this way


BULLISH_KEYWORDS = [
    "partnership", "listing", "integration", "mainnet launch", "upgrade completed",
    "funding round", "raises", "adoption", "burn", "buyback", "approval",
]
BEARISH_KEYWORDS = [
    "delisting", "hack", "exploit", "vulnerability", "lawsuit", "investigation",
    "unlock", "dump", "insolvency", "halt", "suspends", "rug",
]
HIGH_RISK_KEYWORDS = [
    "hack", "exploit", "sec", "lawsuit", "insolvency", "regulatory", "ban", "fraud",
]


def _classify_sentiment(title: str) -> tuple:
    t = title.lower()
    hits_bull = [k for k in BULLISH_KEYWORDS if k in t]
    hits_bear = [k for k in BEARISH_KEYWORDS if k in t]
    hits_risk = [k for k in HIGH_RISK_KEYWORDS if k in t]

    if hits_risk:
        return "HIGH_RISK", f"Keyword match: {hits_risk} — treat as high-uncertainty regardless of other tags"
    if hits_bear and not hits_bull:
        return "BEARISH", f"Keyword match: {hits_bear}"
    if hits_bull and not hits_bear:
        return "BULLISH", f"Keyword match: {hits_bull}"
    if hits_bull and hits_bear:
        return "NEUTRAL", f"Mixed keyword signals: bullish={hits_bull}, bearish={hits_bear}"
    return "NEUTRAL", "No strong keyword match — headline-only heuristic, read full article for real context"


def _is_official_source(domain: str) -> bool:
    return any(official in domain for official in config.OFFICIAL_NEWS_DOMAINS)


def fetch_cryptopanic_news(symbol_base: str, limit: int = 20) -> List[NewsItem]:
    """symbol_base: e.g. 'BTC' from 'BTCUSDT'. Requires
    config.CRYPTOPANIC_API_TOKEN — raises NewsUnavailableError if not
    configured, rather than silently skipping."""
    if requests is None:
        raise NewsUnavailableError("The 'requests' package is not installed")
    if not config.CRYPTOPANIC_API_TOKEN:
        raise NewsUnavailableError(
            "CRYPTOPANIC_API_TOKEN not configured — get a free token at "
            "https://cryptopanic.com/developers/api/ and set it in config.py "
            "or the CRYPTOPANIC_API_TOKEN environment variable."
        )

    url = "https://cryptopanic.com/api/v1/posts/"
    params = {
        "auth_token": config.CRYPTOPANIC_API_TOKEN,
        "currencies": symbol_base,
        "public": "true",
    }
    try:
        resp = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise NewsUnavailableError(f"CryptoPanic request failed: {type(e).__name__} — {e}")

    items = []
    for post in data.get("results", [])[:limit]:
        domain = post.get("domain", "")
        sentiment, basis = _classify_sentiment(post.get("title", ""))
        items.append(NewsItem(
            title=post.get("title", ""), source=domain or post.get("source", {}).get("title", "unknown"),
            url=post.get("url", ""), published_at=post.get("published_at", ""),
            is_confirmed=_is_official_source(domain), sentiment=sentiment, sentiment_basis=basis,
        ))
    return items


def fetch_binance_announcements(symbol_base: str, limit: int = 10) -> List[NewsItem]:
    """Binance's public announcements feed — official exchange source,
    always CONFIRMED tier. No API key required."""
    if requests is None:
        raise NewsUnavailableError("The 'requests' package is not installed")

    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
    params = {"catalogId": "48", "pageNo": 1, "pageSize": limit}
    try:
        resp = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise NewsUnavailableError(f"Binance announcements request failed: {type(e).__name__} — {e}")

    items = []
    articles = data.get("data", {}).get("catalogs", [{}])[0].get("articles", []) if data.get("data") else []
    for a in articles:
        title = a.get("title", "")
        if symbol_base.upper() not in title.upper():
            continue  # only keep announcements actually mentioning this asset
        sentiment, basis = _classify_sentiment(title)
        items.append(NewsItem(
            title=title, source="binance.com",
            url=f"https://www.binance.com/en/support/announcement/{a.get('code', '')}",
            published_at=str(a.get("releaseDate", "")),
            is_confirmed=True, sentiment=sentiment, sentiment_basis=basis,
        ))
    return items


def get_news_summary(symbol: str) -> dict:
    """Orchestrates both sources; each is independently allowed to
    fail without breaking the other. Returns explicit availability
    status for each source per the spec's data-quality requirement."""
    symbol_base = symbol.upper().replace("USDT", "").replace("BUSD", "")
    result = {
        "cryptopanic": {"status": "DATA_UNAVAILABLE", "items": [], "reason": ""},
        "binance_announcements": {"status": "DATA_UNAVAILABLE", "items": [], "reason": ""},
    }

    try:
        items = fetch_cryptopanic_news(symbol_base)
        result["cryptopanic"] = {"status": "REAL_IMPLEMENTED", "items": items, "reason": ""}
    except NewsUnavailableError as e:
        result["cryptopanic"]["reason"] = e.reason

    try:
        items = fetch_binance_announcements(symbol_base)
        result["binance_announcements"] = {"status": "REAL_IMPLEMENTED", "items": items, "reason": ""}
    except NewsUnavailableError as e:
        result["binance_announcements"]["reason"] = e.reason

    return result
