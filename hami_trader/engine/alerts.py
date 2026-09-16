"""
Module 20/21: Alert system. Checks real computed values against
thresholds and logs/fires alerts — no simulated conditions.
"""

import json
import time
import os
from dataclasses import dataclass, asdict
from typing import List, Optional
import config


@dataclass
class Alert:
    alert_type: str
    symbol: str
    message: str
    severity: str   # "info", "warning", "critical"
    timestamp: float


class AlertManager:
    def __init__(self, log_file: str = None):
        self.log_file = log_file or config.ALERT_LOG_FILE
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        self._callbacks = []

    def register_callback(self, fn):
        """fn(Alert) -> None — called synchronously when an alert
        fires, e.g. to update the GUI or play a sound."""
        self._callbacks.append(fn)

    def fire(self, alert_type: str, symbol: str, message: str, severity: str = "info"):
        alert = Alert(alert_type=alert_type, symbol=symbol, message=message,
                       severity=severity, timestamp=time.time())
        with open(self.log_file, "a") as f:
            f.write(json.dumps(asdict(alert)) + "\n")
        for cb in self._callbacks:
            try:
                cb(alert)
            except Exception:
                pass
        return alert

    def check_and_fire(self, verdict, symbol: str, prior_verdict=None) -> List[Alert]:
        """Real condition checks against the actual computed
        FinalVerdict — no simulated triggers."""
        fired = []

        if verdict.squeeze_risk not in ("Low", None) and (prior_verdict is None or prior_verdict.squeeze_risk != verdict.squeeze_risk):
            fired.append(self.fire("squeeze_conditions", symbol, f"Squeeze risk: {verdict.squeeze_risk}", "warning"))

        if verdict.cvd_state == "Divergence":
            fired.append(self.fire("cvd_divergence", symbol, "CVD/price divergence detected", "info"))

        if verdict.absorption_state != "None detected":
            fired.append(self.fire("absorption_detected", symbol, verdict.absorption_state, "info"))

        if verdict.overall_bias != "NEUTRAL" and (prior_verdict is None or prior_verdict.overall_bias != verdict.overall_bias):
            fired.append(self.fire("entry_confirmation", symbol, f"Bias shifted to {verdict.overall_bias} (confidence {verdict.confidence}%)", "critical"))

        if verdict.news_state == "High Risk":
            fired.append(self.fire("high_risk_news", symbol, "High-risk news detected", "critical"))

        if prior_verdict is not None and prior_verdict.market_regime != verdict.market_regime:
            fired.append(self.fire("regime_change", symbol, f"Market regime changed: {prior_verdict.market_regime} -> {verdict.market_regime}", "warning"))

        return fired
