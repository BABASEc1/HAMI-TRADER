"""
app/state.py — shared application state with pub-sub. Changing the
selected symbol here is the single source of truth that drives every
analysis module and every panel to update together — nothing reads a
stale symbol from its own local copy.
"""

from dataclasses import dataclass, field
from typing import Callable, List
import config


@dataclass
class AppState:
    symbol: str = config.DEFAULT_SYMBOL
    timeframe: str = "15m"
    _symbol_listeners: List[Callable[[str], None]] = field(default_factory=list)
    _timeframe_listeners: List[Callable[[str], None]] = field(default_factory=list)

    def on_symbol_change(self, fn: Callable[[str], None]):
        self._symbol_listeners.append(fn)

    def on_timeframe_change(self, fn: Callable[[str], None]):
        self._timeframe_listeners.append(fn)

    def set_symbol(self, symbol: str):
        symbol = symbol.upper().strip()
        if symbol == self.symbol:
            return
        self.symbol = symbol
        for fn in self._symbol_listeners:
            fn(symbol)

    def set_timeframe(self, tf: str):
        if tf == self.timeframe:
            return
        self.timeframe = tf
        for fn in self._timeframe_listeners:
            fn(tf)
