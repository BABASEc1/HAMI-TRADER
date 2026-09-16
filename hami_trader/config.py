"""
Central configuration for the analysis terminal. This is a read-only
analysis tool — there is deliberately no API_SECRET, no order
settings, no risk-per-trade sizing here, because this application
never places, modifies, or closes a trade. See README.md.
"""

import os

DEFAULT_SYMBOL = "BTCUSDT"

TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]

TIMEFRAME_WEIGHT = {
    "1d": 6, "4h": 5, "1h": 4, "30m": 3, "15m": 2.5, "5m": 2, "3m": 1, "1m": 0.5,
}

PROFILE_VALUE_AREA_PCT = 0.70
# Tick size for volume-profile bucketing — auto-scaled per symbol at
# runtime (see engine/market_profile.auto_tick_size) since a fixed
# 5.0 USDT bucket makes no sense for a $0.01 altcoin. This value is
# only the fallback if auto-detection isn't used.
PROFILE_TICK_SIZE = 5.0

SENSITIVITY = "MEDIUM"
NOISE_THRESHOLDS = {
    "LOW":    {"min_volume_btc": 1.0,  "min_delta_btc": 0.5,  "min_imbalance_ratio": 1.5},
    "MEDIUM": {"min_volume_btc": 3.0,  "min_delta_btc": 1.5,  "min_imbalance_ratio": 2.0},
    "HIGH":   {"min_volume_btc": 8.0,  "min_delta_btc": 4.0,  "min_imbalance_ratio": 3.0},
}

EQUAL_LEVEL_TOLERANCE_PCT = 0.0008

SESSIONS_UTC = {
    "Asia": (0, 8),
    "London": (7, 16),
    "New_York": (13, 21),
}
LOCAL_TZ_OFFSET_HOURS = 5  # Pakistan Standard Time, UTC+5

# --- News / fundamentals ------------------------------------------------
# CryptoPanic free tier requires an auth token for the public API.
# Get one free at https://cryptopanic.com/developers/api/
# Leave blank to disable CryptoPanic and fall back to Binance's own
# announcements feed only (no key required for that one).
CRYPTOPANIC_API_TOKEN = os.environ.get("CRYPTOPANIC_API_TOKEN", "")

# Source tiers for confirmed-vs-rumor classification (module 13/25).
# "official" sources are treated as CONFIRMED; everything else is
# treated as UNCONFIRMED / COMMUNITY unless it explicitly cites an
# official source.
OFFICIAL_NEWS_DOMAINS = [
    "binance.com", "coinbase.com", "sec.gov", "etherscan.io",
]

# --- Historical comparison -----------------------------------------------
HISTORICAL_LOOKBACK_DAYS = 180  # how far back to search for similar setups

# --- Alerts ---------------------------------------------------------------
ALERT_LOG_FILE = "state/alerts.jsonl"

# --- Logging ---------------------------------------------------------------
LOG_FILE = "state/terminal.log"
LOG_LEVEL = "INFO"

# --- Macro (module 32) ----------------------------------------------------
# Free, instant-signup key: https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# --- On-chain (module 31) — PAID tiers, optional -----------------------------
GLASSNODE_API_KEY = os.environ.get("GLASSNODE_API_KEY", "")
CRYPTOQUANT_API_KEY = os.environ.get("CRYPTOQUANT_API_KEY", "")

# --- Derivatives aggregator (liquidations across exchanges) — PAID, optional
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "")

# --- Order book / DOM tracking ------------------------------------------------
ORDERBOOK_POLL_SECONDS = 3.0
ORDERBOOK_MAX_SNAPSHOTS = 200
ORDERBOOK_DEPTH_LIMIT = 100

# --- Watchlist / market browser persistence -----------------------------------
WATCHLIST_FILE = "state/watchlist.json"
RECENT_PAIRS_FILE = "state/recent_pairs.json"
MAX_RECENT_PAIRS = 15

# --- Big orders / whale detection ------------------------------------------------
BIG_ORDER_PERCENTILE = 95
WHALE_Z_SCORE_THRESHOLD = 5.0

# --- Network resilience -----------------------------------------------------
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 10
