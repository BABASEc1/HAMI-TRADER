"""
Module 44: Cache / performance engine.

A real in-memory TTL cache, keyed by (function, args). Historical
candle data (e.g. yesterday's 1D candles) doesn't need to be
re-fetched every refresh cycle — only the most recent, still-forming
candle actually changes. This cache is intentionally simple (no
external dependency) but genuinely reduces redundant network calls,
which matters for Binance's rate limits (section 44/45).
"""

import time
import threading
import functools
from typing import Any, Callable, Dict, Tuple


class TTLCache:
    def __init__(self):
        self._store: Dict[Tuple, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Tuple):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None, False
            expires_at, value = entry
            if time.time() > expires_at:
                del self._store[key]
                return None, False
            return value, True

    def set(self, key: Tuple, value: Any, ttl_seconds: float):
        with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)

    def clear(self):
        with self._lock:
            self._store.clear()

    def invalidate_prefix(self, prefix: Tuple):
        """Used when the user switches symbols — drop every cached
        entry for the old symbol so stale data never leaks across pairs."""
        with self._lock:
            keys_to_drop = [k for k in self._store if k[:len(prefix)] == prefix]
            for k in keys_to_drop:
                del self._store[k]


_global_cache = TTLCache()


def cached(ttl_seconds: float = 30):
    """Decorator for functions where args are hashable (symbol,
    interval, limit, etc.) — real caching, not a no-op decorator."""
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__name__, args, tuple(sorted(kwargs.items())))
            value, hit = _global_cache.get(key)
            if hit:
                return value
            result = fn(*args, **kwargs)
            _global_cache.set(key, result, ttl_seconds)
            return result
        wrapper.cache_clear = _global_cache.clear
        return wrapper
    return decorator


def get_global_cache() -> TTLCache:
    return _global_cache
