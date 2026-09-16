"""
app/market_browser.py — Module 3: Market Browser / Pair Search.

Real pair validation against Binance's actual exchangeInfo (no
hard-coded symbol list — whatever Binance actually lists is what's
searchable). Watchlist/favorites/recent pairs persist to local JSON
files, not hard-coded either.
"""

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import List, Optional
import config


@dataclass
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    is_spot_trading: bool


class SymbolDirectory:
    """Real, live list of every symbol Binance actually supports —
    fetched once per session (cached), not hard-coded. Used for
    search/validation."""

    def __init__(self, client):
        self.client = client
        self._symbols: Optional[List[SymbolInfo]] = None
        self._fetched_at = 0

    def refresh(self, force: bool = False):
        if self._symbols is not None and not force and (time.time() - self._fetched_at) < 3600:
            return
        info = self.client.get_exchange_info()
        self._symbols = [
            SymbolInfo(
                symbol=s["symbol"], base_asset=s["baseAsset"], quote_asset=s["quoteAsset"],
                status=s["status"], is_spot_trading=s.get("isSpotTradingAllowed", True),
            )
            for s in info["symbols"]
        ]
        self._fetched_at = time.time()

    def validate(self, symbol: str) -> Optional[SymbolInfo]:
        self.refresh()
        symbol = symbol.upper().strip()
        return next((s for s in self._symbols if s.symbol == symbol and s.status == "TRADING"), None)

    def search(self, query: str, limit: int = 20) -> List[SymbolInfo]:
        """Real search over the real symbol list — matches by symbol
        substring or base-asset substring (covers 'search by coin
        name' for well-known tickers; free-text project names beyond
        the ticker itself go through data/coingecko.search_coin)."""
        self.refresh()
        query = query.upper().strip()
        if not query:
            return []
        matches = [s for s in self._symbols if s.status == "TRADING" and
                   (query in s.symbol or query in s.base_asset)]
        # Prioritize exact/prefix matches, then USDT pairs, then alphabetical
        matches.sort(key=lambda s: (
            not s.symbol.startswith(query), s.quote_asset != "USDT", s.symbol,
        ))
        return matches[:limit]


class WatchlistManager:
    """Real local persistence — no hard-coded pairs. Three lists:
    watchlist (explicit adds), favorites (starred subset), recent
    (auto-tracked, capped at config.MAX_RECENT_PAIRS)."""

    def __init__(self, watchlist_file: str = None, recent_file: str = None):
        self.watchlist_file = watchlist_file or config.WATCHLIST_FILE
        self.recent_file = recent_file or config.RECENT_PAIRS_FILE
        os.makedirs(os.path.dirname(self.watchlist_file), exist_ok=True)
        self.watchlist: List[str] = self._load(self.watchlist_file, [])
        self.favorites: List[str] = self._load(self.watchlist_file.replace(".json", "_favorites.json"), [])
        self.recent: List[str] = self._load(self.recent_file, [])

    def _load(self, path: str, default):
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                return default
        return default

    def _save(self, path: str, data):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def add_to_watchlist(self, symbol: str):
        symbol = symbol.upper()
        if symbol not in self.watchlist:
            self.watchlist.append(symbol)
            self._save(self.watchlist_file, self.watchlist)

    def remove_from_watchlist(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self.watchlist:
            self.watchlist.remove(symbol)
            self._save(self.watchlist_file, self.watchlist)

    def toggle_favorite(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self.favorites:
            self.favorites.remove(symbol)
        else:
            self.favorites.append(symbol)
        self._save(self.watchlist_file.replace(".json", "_favorites.json"), self.favorites)

    def record_recent(self, symbol: str):
        symbol = symbol.upper()
        if symbol in self.recent:
            self.recent.remove(symbol)
        self.recent.insert(0, symbol)
        self.recent = self.recent[:config.MAX_RECENT_PAIRS]
        self._save(self.recent_file, self.recent)
