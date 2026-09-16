"""
Real order-book snapshot poller and rolling history. Wall tracking
and spoofing analysis (analysis/liquidity_flow.py, analysis/spoofing.py)
are inherently temporal — a single snapshot cannot show whether a
wall was added, defended, or pulled. This tracker polls Binance's
real public order-book endpoint on an interval and keeps a real
rolling history in memory, which those analysis modules read from.

Like the liquidation listener, this needs runtime to accumulate
anything meaningful — on first launch, wall/spoofing analysis will
correctly report limited history rather than a fabricated verdict.
"""

import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class OrderBookSnapshot:
    timestamp: float
    bids: Dict[float, float]   # price -> qty
    asks: Dict[float, float]


class OrderBookTracker:
    def __init__(self, feed, poll_interval_seconds: float = 3.0, max_snapshots: int = 200, depth_limit: int = 100):
        """feed: a data.binance.BinanceFeed instance (real client)."""
        self.feed = feed
        self.poll_interval = poll_interval_seconds
        self.depth_limit = depth_limit
        self.snapshots: deque = deque(maxlen=max_snapshots)
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self.last_error: Optional[str] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                raw = self.feed.get_order_book(limit=self.depth_limit)
                snap = OrderBookSnapshot(
                    timestamp=time.time(),
                    bids={float(p): float(q) for p, q in raw["bids"]},
                    asks={float(p): float(q) for p, q in raw["asks"]},
                )
                with self._lock:
                    self.snapshots.append(snap)
                self.last_error = None
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            time.sleep(self.poll_interval)

    def get_history(self) -> List[OrderBookSnapshot]:
        with self._lock:
            return list(self.snapshots)

    def get_latest(self) -> Optional[OrderBookSnapshot]:
        with self._lock:
            return self.snapshots[-1] if self.snapshots else None

    def get_level_history(self, price: float, side: str, tolerance_pct: float = 0.0005) -> List[tuple]:
        """Real quantity-over-time history for a specific price level
        (the actual basis for wall/spoofing classification). Returns
        [(timestamp, qty_or_None), ...] — None means the level wasn't
        present in that snapshot (i.e. it disappeared)."""
        history = self.get_history()
        result = []
        for snap in history:
            book_side = snap.bids if side == "bid" else snap.asks
            match_qty = None
            for p, q in book_side.items():
                if abs(p - price) / price <= tolerance_pct:
                    match_qty = q
                    break
            result.append((snap.timestamp, match_qty))
        return result
