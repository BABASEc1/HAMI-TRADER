"""
Live and historical market data from Binance's public endpoints.
No API key required for any of this — it's all public market data
(spot + USD-M futures market-data endpoints).

DATA HONESTY: every fetch method here either returns real data from
Binance or raises DataUnavailableError with a specific reason. Nothing
in this module invents or interpolates fake values. Callers (the
analysis engines and the orchestrator) are responsible for catching
DataUnavailableError and surfacing "DATA UNAVAILABLE" to the user
rather than silently proceeding as if data existed.
"""

from dataclasses import dataclass
from typing import List, Optional


class DataUnavailableError(Exception):
    """Raised whenever real data could not be obtained — network
    failure, invalid symbol, endpoint doesn't exist for this market,
    etc. Always carries a human-readable reason."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass
class Trade:
    price: float
    qty: float
    time: int
    is_buyer_maker: bool
    # If is_buyer_maker is True, the SELLER was the aggressor (hit the bid).
    # If False, the BUYER was the aggressor (lifted the ask).
    # This is the tick-rule approximation described in README.md.

    @property
    def side(self) -> str:
        return "SELL" if self.is_buyer_maker else "BUY"


TIMEFRAME_INTERVALS = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}


class BinanceFeed:
    def __init__(self, symbol: str):
        # Imported lazily so this module (and the Candle/Trade
        # dataclasses used throughout the engine layer) can be used
        # and unit-tested with synthetic data without requiring the
        # python-binance package to be installed.
        from binance.client import Client
        from binance.exceptions import BinanceAPIException
        self._BinanceAPIException = BinanceAPIException
        self.symbol = symbol.upper()
        self.client = Client()

    def _wrap(self, fn, *args, reason_prefix: str, **kwargs):
        try:
            return fn(*args, **kwargs)
        except self._BinanceAPIException as e:
            raise DataUnavailableError(f"{reason_prefix}: Binance API error — {e}")
        except Exception as e:
            raise DataUnavailableError(f"{reason_prefix}: {type(e).__name__} — {e}")

    def get_klines(self, interval: str, limit: int = 200) -> List[Candle]:
        raw = self._wrap(self.client.get_klines, symbol=self.symbol, interval=interval,
                          limit=limit, reason_prefix=f"klines({interval})")
        return [
            Candle(open_time=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5]), close_time=k[6])
            for k in raw
        ]

    def get_multi_tf_klines(self, timeframes: List[str], limit: int = 200) -> dict:
        """Fetches each timeframe independently; a failure on one
        timeframe does not silently corrupt the others — it's
        reported per-timeframe by the caller catching
        DataUnavailableError per key if it chooses to iterate
        individually instead of calling this bulk helper."""
        result = {}
        for tf in timeframes:
            interval = TIMEFRAME_INTERVALS.get(tf, tf)
            result[tf] = self.get_klines(interval, limit=limit)
        return result

    def get_recent_trades(self, limit: int = 1000) -> List[Trade]:
        raw = self._wrap(self.client.get_aggregate_trades, symbol=self.symbol, limit=limit,
                          reason_prefix="recent_trades")
        return [Trade(price=float(t["p"]), qty=float(t["q"]), time=t["T"], is_buyer_maker=t["m"]) for t in raw]

    def get_order_book(self, limit: int = 100):
        return self._wrap(self.client.get_order_book, symbol=self.symbol, limit=limit,
                           reason_prefix="order_book")

    def get_24h_stats(self):
        return self._wrap(self.client.get_ticker, symbol=self.symbol, reason_prefix="24h_stats")

    # --- Futures-only data (OI, funding, mark price) ---------------------
    # These require the symbol to exist as a USD-M perpetual on Binance
    # Futures. If it doesn't (e.g. an obscure spot-only listing), this
    # raises DataUnavailableError with a clear reason rather than
    # guessing or fabricating a number.

    def get_open_interest(self):
        return self._wrap(self.client.futures_open_interest, symbol=self.symbol,
                           reason_prefix="open_interest")

    def get_open_interest_hist(self, period: str = "5m", limit: int = 30):
        return self._wrap(self.client.futures_open_interest_hist, symbol=self.symbol,
                           period=period, limit=limit, reason_prefix="open_interest_hist")

    def get_funding_rate_history(self, limit: int = 50):
        return self._wrap(self.client.futures_funding_rate, symbol=self.symbol, limit=limit,
                           reason_prefix="funding_rate_history")

    def get_mark_price(self):
        return self._wrap(self.client.futures_mark_price, symbol=self.symbol,
                           reason_prefix="mark_price")

    def get_futures_klines(self, interval: str, limit: int = 200) -> List[Candle]:
        """Futures klines — used where futures-specific price action
        (e.g. relative to funding/OI) matters more than spot."""
        raw = self._wrap(self.client.futures_klines, symbol=self.symbol, interval=interval,
                          limit=limit, reason_prefix=f"futures_klines({interval})")
        return [
            Candle(open_time=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5]), close_time=k[6])
            for k in raw
        ]

    def symbol_exists_on_futures(self) -> bool:
        try:
            info = self._wrap(self.client.futures_exchange_info, reason_prefix="exchange_info")
            return any(s["symbol"] == self.symbol for s in info["symbols"])
        except DataUnavailableError:
            return False
