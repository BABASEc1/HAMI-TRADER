"""
Derivatives data provider: real liquidation stream from Binance
Futures' public WebSocket (`!forceOrder@arr`) — this is Binance's
ONLY public liquidation feed; there is no REST history endpoint for
market-wide liquidations, so continuous collection is the only way
to have real liquidation history.

COINGLASS NOTE: CoinGlass aggregates liquidations across many
exchanges and would give a much richer picture than Binance alone,
but their useful API tiers are paid (https://coinglass.com/pricing).
An integration point is defined below (fetch_coinglass_liquidations)
so adding a key later is a one-line change — without one it correctly
raises DataUnavailableError rather than faking cross-exchange data.
"""

import time
import threading
import json
from collections import deque
from typing import List
import config
from data.binance import DataUnavailableError

try:
    import requests
except ImportError:
    requests = None


class LiquidationListener:
    """Collects recent forced-liquidation events from Binance's public
    !forceOrder@arr stream. Runs in a background thread; call start()
    once. If this hasn't been running, get_recent() returns an empty
    list — analysis/liquidation.py handles that honestly rather than
    guessing."""

    def __init__(self, symbol: str, max_events: int = 500):
        self.symbol = symbol.upper()
        self.events = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._thread = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def set_symbol(self, symbol: str):
        """Called when the user switches pairs in the Market Browser —
        events for the old symbol are cleared so stale data never
        leaks into a new symbol's analysis."""
        with self._lock:
            self.symbol = symbol.upper()
            self.events.clear()

    def _run(self):
        import websocket

        url = "wss://fstream.binance.com/ws/!forceOrder@arr"

        def on_message(ws, message):
            try:
                data = json.loads(message)
                order = data.get("o", {})
                if order.get("s") != self.symbol:
                    return
                with self._lock:
                    self.events.append({
                        "time": order.get("T"), "side": order.get("S"),
                        "price": float(order.get("ap", 0)), "qty": float(order.get("q", 0)),
                    })
            except Exception:
                pass

        while self._running:
            try:
                ws = websocket.WebSocketApp(url, on_message=on_message)
                ws.run_forever(ping_interval=20)
            except Exception:
                pass
            if self._running:
                time.sleep(5)

    def get_recent(self, window_seconds: int = 300) -> List[dict]:
        cutoff = int(time.time() * 1000) - window_seconds * 1000
        with self._lock:
            return [e for e in self.events if e["time"] and e["time"] >= cutoff]


def fetch_coinglass_liquidations(symbol: str) -> dict:
    """Integration point for CoinGlass's cross-exchange liquidation
    data — requires a paid API key. Raises honestly without one."""
    api_key = getattr(config, "COINGLASS_API_KEY", "")
    if not api_key:
        raise DataUnavailableError(
            "COINGLASS_API_KEY not configured. CoinGlass's liquidation API requires a paid "
            "plan (https://coinglass.com/pricing) — set COINGLASS_API_KEY in config.py if you "
            "have one. Without it, cross-exchange liquidation aggregation is DATA_UNAVAILABLE; "
            "the LiquidationListener above still gives you real Binance-only liquidation data."
        )
    if requests is None:
        raise DataUnavailableError("The 'requests' package is not installed")

    url = "https://open-api.coinglass.com/public/v2/liquidation_history"
    try:
        resp = requests.get(url, params={"symbol": symbol.replace("USDT", "")},
                             headers={"coinglassSecret": api_key}, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise DataUnavailableError(f"CoinGlass request failed: {type(e).__name__} — {e}")
