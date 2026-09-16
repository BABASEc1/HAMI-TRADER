"""
Module 12/14 of the spec: Market sessions (Asia/London/New York),
using Pakistan Standard Time (UTC+5) for interface display as
requested. All computed from real candle timestamps — no external
data needed.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from data.binance import Candle
import config

PKT = timezone(timedelta(hours=config.LOCAL_TZ_OFFSET_HOURS))


@dataclass
class SessionRange:
    name: str
    high: float
    low: float
    start_time_pkt: str
    end_time_pkt: str
    candle_count: int
    swept: bool = False
    sweep_explanation: str = ""


def _in_session(ts_ms: int, start_hour_utc: int, end_hour_utc: int) -> bool:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    hour = dt.hour
    if start_hour_utc < end_hour_utc:
        return start_hour_utc <= hour < end_hour_utc
    return hour >= start_hour_utc or hour < end_hour_utc  # wraps midnight


def compute_session_ranges(candles: List[Candle]) -> List[SessionRange]:
    """Computes today's (UTC calendar day of the most recent candle)
    high/low for each configured session, using only real candle
    data passed in — typically 5m or 15m candles covering the last
    24-48h."""
    if not candles:
        return []

    ranges = []
    for name, (start_h, end_h) in config.SESSIONS_UTC.items():
        session_candles = [c for c in candles if _in_session(c.open_time, start_h, end_h)]
        if not session_candles:
            continue
        high = max(c.high for c in session_candles)
        low = min(c.low for c in session_candles)
        start_dt = datetime.fromtimestamp(session_candles[0].open_time / 1000, tz=PKT)
        end_dt = datetime.fromtimestamp(session_candles[-1].close_time / 1000, tz=PKT)
        ranges.append(SessionRange(
            name=name, high=high, low=low,
            start_time_pkt=start_dt.strftime("%H:%M PKT"),
            end_time_pkt=end_dt.strftime("%H:%M PKT"),
            candle_count=len(session_candles),
        ))
    return ranges


def detect_session_sweep(session: SessionRange, later_candles: List[Candle]) -> SessionRange:
    """Checks whether price, after the session closed, swept the
    session's high or low and closed back inside — a session
    liquidity sweep."""
    for c in later_candles:
        if c.high > session.high and c.close < session.high:
            session.swept = True
            session.sweep_explanation = (
                f"{session.name} session high ({session.high:.4f}) was swept "
                f"(wicked to {c.high:.4f}) and price closed back below it — "
                f"consistent with a session liquidity sweep."
            )
            return session
        if c.low < session.low and c.close > session.low:
            session.swept = True
            session.sweep_explanation = (
                f"{session.name} session low ({session.low:.4f}) was swept "
                f"(wicked to {c.low:.4f}) and price closed back above it — "
                f"consistent with a session liquidity sweep."
            )
            return session
    return session


def current_session_pkt() -> str:
    now_utc_hour = datetime.now(timezone.utc).hour
    active = [name for name, (s, e) in config.SESSIONS_UTC.items() if _in_session(
        int(datetime.now(timezone.utc).timestamp() * 1000), s, e
    )]
    return ", ".join(active) if active else "Between sessions"
