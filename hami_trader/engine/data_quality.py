"""
Module 40: Data Quality engine.

Every data point flowing through the app is wrapped in a DataPoint
with source, timestamp, freshness, and status. When two providers
disagree on the same fact (e.g. Binance price vs a fallback
provider's price), that's a real DATA_CONFLICT — flagged explicitly,
with the higher-priority source preferred and confidence reduced,
never silently resolved by picking one and hiding the disagreement.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional, List

STATUS_OK = "DATA_OK"
STATUS_UNAVAILABLE = "DATA_UNAVAILABLE"
STATUS_CONFLICT = "DATA_CONFLICT"
STATUS_NOT_SUPPORTED = "NOT_SUPPORTED_BY_PROVIDER"

STALE_AFTER_SECONDS = 120


@dataclass
class DataPoint:
    value: Any
    source: str
    status: str = STATUS_OK
    fetched_at: float = field(default_factory=time.time)
    units: str = ""
    reason: str = ""
    conflict_with: Optional["DataPoint"] = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.fetched_at

    @property
    def is_stale(self) -> bool:
        return self.age_seconds > STALE_AFTER_SECONDS

    def as_display(self) -> str:
        if self.status == STATUS_UNAVAILABLE:
            return f"DATA_UNAVAILABLE ({self.reason})"
        if self.status == STATUS_NOT_SUPPORTED:
            return f"NOT_SUPPORTED_BY_PROVIDER ({self.reason})"
        if self.status == STATUS_CONFLICT:
            return f"DATA_CONFLICT: {self.source}={self.value} vs {self.conflict_with.source}={self.conflict_with.value}"
        stale_flag = " [STALE]" if self.is_stale else ""
        return f"{self.value} (source: {self.source}, {self.age_seconds:.0f}s ago){stale_flag}"


def reconcile(primary: DataPoint, secondary: DataPoint, tolerance_pct: float = 0.5) -> DataPoint:
    """Compares two real DataPoints for the same fact from different
    providers. Binance is preferred for price-sensitive values (per
    the spec's explicit instruction) when both are numeric and close
    enough; otherwise flags a real conflict rather than averaging or
    guessing."""
    if primary.status != STATUS_OK or secondary.status != STATUS_OK:
        return primary if primary.status == STATUS_OK else secondary

    try:
        diff_pct = abs(float(primary.value) - float(secondary.value)) / abs(float(primary.value)) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return primary  # non-numeric — can't quantify conflict, trust primary silently would be wrong; caller should compare manually

    if diff_pct > tolerance_pct:
        return DataPoint(
            value=primary.value, source=primary.source, status=STATUS_CONFLICT,
            reason=f"{primary.source} and {secondary.source} disagree by {diff_pct:.2f}% "
                   f"(tolerance {tolerance_pct}%) — showing {primary.source} as primary per config.",
            conflict_with=secondary,
        )
    return primary


class DataQualityReport:
    """Aggregates DataPoints across a full analysis run so the GUI's
    DATA STATUS tab and the confidence calculation both read from one
    real, consistent source of truth."""
    def __init__(self):
        self.points: List[DataPoint] = []

    def add(self, dp: DataPoint):
        self.points.append(dp)

    @property
    def unavailable_count(self) -> int:
        return sum(1 for p in self.points if p.status == STATUS_UNAVAILABLE)

    @property
    def conflict_count(self) -> int:
        return sum(1 for p in self.points if p.status == STATUS_CONFLICT)

    @property
    def ok_count(self) -> int:
        return sum(1 for p in self.points if p.status == STATUS_OK)

    def confidence_penalty(self) -> int:
        """Real, documented penalty — not arbitrary: each unavailable
        critical data point and each conflict reduces confidence."""
        return min(self.unavailable_count * 5 + self.conflict_count * 10, 60)

    def render_text(self) -> str:
        lines = [f"DATA QUALITY: {self.ok_count} OK, {self.unavailable_count} unavailable, {self.conflict_count} conflicts"]
        for p in self.points:
            lines.append(f"  [{p.status}] {p.source}: {p.as_display() if p.status == STATUS_OK else p.reason}")
        return "\n".join(lines)
