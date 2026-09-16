"""
app/settings.py — Module 42: API key security & settings.

Keys are stored in a local JSON file (state/settings.json), which is
never printed to logs, console, or error messages — engine/resilience.py's
logger and every exception message in this project reference error
TYPES and endpoint names, never raw key values, by construction (no
code path formats an API key into a log string). Public Binance market
data never requires these keys — every key here is optional and only
unlocks additional REAL data (news breadth, macro, on-chain).
"""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Dict
import config

SETTINGS_FILE = "state/settings.json"
SENSITIVE_KEYS = {
    "CRYPTOPANIC_API_TOKEN", "FRED_API_KEY", "GLASSNODE_API_KEY",
    "CRYPTOQUANT_API_KEY", "COINGLASS_API_KEY",
}


@dataclass
class Settings:
    api_keys: Dict[str, str] = field(default_factory=dict)
    sensitivity: str = "MEDIUM"
    default_symbol: str = "BTCUSDT"
    orderbook_poll_seconds: float = 3.0


def load_settings() -> Settings:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                data = json.load(f)
            return Settings(**data)
        except Exception:
            pass
    return Settings()


def save_settings(settings: Settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(asdict(settings), f, indent=2)


def apply_settings_to_config(settings: Settings):
    """Pushes loaded settings into the config module at runtime so
    every data provider picks them up without a restart. Never logs
    the values it's applying."""
    for key, value in settings.api_keys.items():
        if hasattr(config, key):
            setattr(config, key, value)
    config.SENSITIVITY = settings.sensitivity
    config.DEFAULT_SYMBOL = settings.default_symbol
    config.ORDERBOOK_POLL_SECONDS = settings.orderbook_poll_seconds


def mask_key(value: str) -> str:
    """Used anywhere a key might otherwise be displayed — shows only
    enough to confirm something is set, never the full value."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]
