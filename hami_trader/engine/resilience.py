"""
Module 24: Logging, error handling, and internet/API reconnect
handling. Wraps real network calls with retry/backoff — does not
mask failures, just retries real requests a bounded number of times
before surfacing the real error.
"""

import logging
import time
import functools
import os
import sys
import config


def setup_logging():
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("crypto_terminal")


log = logging.getLogger("crypto_terminal")


def with_retry(max_retries: int = None, backoff_seconds: int = None):
    """Decorator: retries a real network call on failure with
    exponential-ish backoff, then re-raises the real exception if all
    retries are exhausted. Never returns fabricated data on failure."""
    max_retries = max_retries or config.MAX_RETRIES
    backoff_seconds = backoff_seconds or config.RETRY_BACKOFF_SECONDS

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    log.warning(f"{fn.__name__} failed (attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        time.sleep(backoff_seconds * attempt)
            log.error(f"{fn.__name__} exhausted {max_retries} retries: {last_exc}")
            raise last_exc
        return wrapper
    return decorator


class ConnectionMonitor:
    """Tracks consecutive failures across the whole app so the GUI
    can show a real 'connection lost' state rather than silently
    showing stale data as if it were current."""
    def __init__(self, failure_threshold: int = 3):
        self.failure_threshold = failure_threshold
        self.consecutive_failures = 0
        self.last_success_time = None
        self.last_error = None

    def record_success(self):
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self.last_error = None

    def record_failure(self, error: Exception):
        self.consecutive_failures += 1
        self.last_error = str(error)
        log.error(f"Connection failure #{self.consecutive_failures}: {error}")

    @property
    def is_degraded(self) -> bool:
        return self.consecutive_failures >= self.failure_threshold

    def status_text(self) -> str:
        if self.consecutive_failures == 0:
            return "Connected"
        if self.is_degraded:
            return f"DISCONNECTED ({self.consecutive_failures} consecutive failures) — {self.last_error}"
        return f"Degraded ({self.consecutive_failures} recent failures)"
