"""
Modules 17-19: Final Analysis Dashboard, Manual Trade Plan, and
No-Trade Logic.

This module produces the final verdict shown in the GUI. It computes
a bias and confidence score from real signals gathered by the other
engines, and — critically — NEVER places, modifies, or closes any
order. There is no Binance order-placement import anywhere in this
file or this project. The output is display-only text/data for a
human to read and act on manually.
"""

from dataclasses import dataclass, field
from typing import Optional, List
import config


@dataclass
class TradePlan:
    long_entry_zone: Optional[str] = None
    long_confirmation: Optional[str] = None
    short_entry_zone: Optional[str] = None
    short_confirmation: Optional[str] = None
    invalidation: Optional[str] = None
    stop_loss_area: Optional[str] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    primary_liquidity_target: Optional[float] = None
    expected_risk_reward: Optional[str] = None
    wait_for: Optional[str] = None   # explicit confirmation text, e.g. spec's example phrasing


@dataclass
class FinalVerdict:
    market_regime: str
    htf_bias: str
    mtf_bias: str
    ltf_condition: str
    primary_liquidity_target: Optional[float]
    secondary_liquidity_target: Optional[float]
    important_resistance: List[float]
    important_support: List[float]
    poc: float
    vah: float
    val: float
    cvd_state: str
    oi_state: str
    funding_state: str
    liquidation_condition: str
    squeeze_risk: str
    trapped_participants: str
    order_flow_state: str
    absorption_state: str
    news_state: str
    overall_bias: str          # "LONG", "SHORT", "NEUTRAL"
    confidence: int            # 0-100
    confidence_explanation: str
    trade_plan: TradePlan
    no_trade_reasons: List[str] = field(default_factory=list)

    def render_text(self) -> str:
        L = []
        L.append("=== FINAL ANALYSIS DASHBOARD ===")
        L.append(f"MARKET REGIME: {self.market_regime}")
        L.append(f"HTF BIAS: {self.htf_bias}")
        L.append(f"MTF BIAS: {self.mtf_bias}")
        L.append(f"LTF CONDITION: {self.ltf_condition}")
        L.append(f"PRIMARY LIQUIDITY TARGET: {self.primary_liquidity_target}")
        L.append(f"SECONDARY LIQUIDITY TARGET: {self.secondary_liquidity_target}")
        L.append(f"IMPORTANT RESISTANCE: {self.important_resistance}")
        L.append(f"IMPORTANT SUPPORT: {self.important_support}")
        L.append(f"POC: {self.poc}  VAH: {self.vah}  VAL: {self.val}")
        L.append(f"CVD: {self.cvd_state}")
        L.append(f"OI: {self.oi_state}")
        L.append(f"FUNDING: {self.funding_state}")
        L.append(f"LIQUIDATION CONDITION: {self.liquidation_condition}")
        L.append(f"SQUEEZE RISK: {self.squeeze_risk}")
        L.append(f"TRAPPED PARTICIPANTS: {self.trapped_participants}")
        L.append(f"ORDER FLOW: {self.order_flow_state}")
        L.append(f"ABSORPTION: {self.absorption_state}")
        L.append(f"NEWS: {self.news_state}")
        L.append("")
        L.append(f"OVERALL BIAS: {self.overall_bias}")
        L.append(f"CONFIDENCE: {self.confidence}%")
        L.append(f"  {self.confidence_explanation}")

        if self.overall_bias == "NEUTRAL":
            L.append("\n=== NO TRADE / WAIT ===")
            for r in self.no_trade_reasons:
                L.append(f"  - {r}")
        else:
            tp = self.trade_plan
            L.append("\n=== MANUAL TRADE PLAN (you decide whether to act on this) ===")
            if tp.long_entry_zone:
                L.append(f"POTENTIAL LONG ENTRY ZONE: {tp.long_entry_zone}")
                L.append(f"LONG CONFIRMATION: {tp.long_confirmation}")
            if tp.short_entry_zone:
                L.append(f"POTENTIAL SHORT ENTRY ZONE: {tp.short_entry_zone}")
                L.append(f"SHORT CONFIRMATION: {tp.short_confirmation}")
            L.append(f"INVALIDATION: {tp.invalidation}")
            L.append(f"STOP LOSS AREA: {tp.stop_loss_area}")
            L.append(f"TP1: {tp.tp1}")
            L.append(f"TP2: {tp.tp2}")
            L.append(f"TP3: {tp.tp3}")
            L.append(f"PRIMARY LIQUIDITY TARGET: {tp.primary_liquidity_target}")
            L.append(f"EXPECTED RISK/REWARD: {tp.expected_risk_reward}")
            L.append(f"WAIT FOR: {tp.wait_for}")

        return "\n".join(L)


def build_final_verdict(
    price: float, htf_regime: str, ltf_regime: str,
    nearest_liquidity_up, nearest_liquidity_down, all_levels,
    profile, value_state: dict, delta_snapshot, cvd_trend: str, divergence: dict,
    absorption, trap, squeeze, oi_state, wick_zone: Optional[dict],
    news_summary: dict, btc_alignment: Optional[dict],
) -> FinalVerdict:

    # --- Bias building blocks, all from real upstream signals -----------
    htf_bias = "Bullish" if htf_regime == "trending" and cvd_trend == "rising" else \
               "Bearish" if htf_regime == "trending" and cvd_trend == "falling" else "Neutral"
    mtf_bias = "Bullish" if cvd_trend == "rising" else "Bearish" if cvd_trend == "falling" else "Neutral"
    ltf_condition = "Bullish" if delta_snapshot.delta > 0 else "Bearish" if delta_snapshot.delta < 0 else "Neutral"

    resistance = sorted({l.price for l in all_levels if l.price > price and l.strength >= 3})[:3]
    support = sorted({l.price for l in all_levels if l.price < price and l.strength >= 3}, reverse=True)[:3]

    cvd_state = "Divergence" if divergence.get("divergence") else \
        ("Bullish" if cvd_trend == "rising" else "Bearish" if cvd_trend == "falling" else "Neutral")
    oi_state_str = oi_state.classification.replace("_", " ").title() if oi_state else "DATA_UNAVAILABLE"
    funding_state = f"{oi_state.funding_rate:.4%}" if oi_state and oi_state.funding_rate else "DATA_UNAVAILABLE"
    squeeze_risk = squeeze.direction.replace("_", " ").title() if squeeze and squeeze.direction else "Low"
    liquidation_condition = squeeze.explanation if squeeze else "DATA_UNAVAILABLE"

    trapped = "None detected this cycle"
    if trap:
        trapped = f"{trap.trap_type.replace('_', ' ').title()} at {trap.level:.4f} — {trap.explanation}"

    order_flow_state = "Buyer controlled" if delta_snapshot.delta_pct > 15 else \
        "Seller controlled" if delta_snapshot.delta_pct < -15 else "Mixed"

    absorption_state = "None detected"
    if absorption:
        absorption_state = f"{absorption.side.replace('_', ' ').title()} ({absorption.strength}, confirmed={absorption.confirmed})"

    news_state, news_reasons = _summarize_news(news_summary)

    # --- Score bias direction (mirrors confluence.py's spirit, no execution) ---
    score = 0
    reasons_long, reasons_short = [], []

    if absorption and absorption.confirmed:
        if absorption.side == "sell_side":
            score += 25; reasons_long.append("Confirmed seller absorption")
        else:
            score -= 25; reasons_short.append("Confirmed buyer absorption")

    if trap:
        if trap.trap_type == "short_trap":
            score += 15; reasons_long.append("Short trap detected")
        else:
            score -= 15; reasons_short.append("Long trap detected")

    if squeeze and squeeze.direction == "short_squeeze_risk":
        score += 15; reasons_long.append("Short squeeze conditions building")
    elif squeeze and squeeze.direction == "long_squeeze_risk":
        score -= 15; reasons_short.append("Long squeeze conditions building")

    if divergence.get("divergence"):
        if divergence.get("price_dir") == "down" and divergence.get("cvd_dir") == "up":
            score += 10; reasons_long.append("Bullish CVD/price divergence")
        elif divergence.get("price_dir") == "up" and divergence.get("cvd_dir") == "down":
            score -= 10; reasons_short.append("Bearish CVD/price divergence")

    if value_state["state"] == "outside_value_below":
        score += 5; reasons_long.append("Price outside value, below VAL")
    elif value_state["state"] == "outside_value_above":
        score -= 5; reasons_short.append("Price outside value, above VAH")

    if btc_alignment and btc_alignment.get("alignment") == "opposed":
        score = int(score * 0.6)  # broader market opposing the setup reduces confidence

    confidence = min(abs(score) * 2, 100)  # simple, documented scaling — not a proven model

    no_trade_reasons = []
    if abs(score) < 20:
        overall_bias = "NEUTRAL"
        no_trade_reasons.append("No confirmed trigger (absorption/trap/squeeze) with sufficient weight fired.")
        if not absorption and not trap:
            no_trade_reasons.append("Neither absorption nor a trapped-trader pattern was detected this cycle.")
        no_trade_reasons.append(
            f"Nearest liquidity: upside {nearest_liquidity_up.price if nearest_liquidity_up else 'n/a'}, "
            f"downside {nearest_liquidity_down.price if nearest_liquidity_down else 'n/a'} — "
            f"price would need to reach and react at one of these for a new trigger to be possible."
        )
        trade_plan = TradePlan(wait_for="A confirmed absorption or trapped-trader trigger, per the reasons above.")
    else:
        overall_bias = "LONG" if score > 0 else "SHORT"
        trade_plan = _build_trade_plan(
            overall_bias, price, nearest_liquidity_up, nearest_liquidity_down,
            reasons_long if overall_bias == "LONG" else reasons_short,
        )

    confidence_explanation = (
        f"Score {score:+d} from: {'; '.join(reasons_long + reasons_short) if (reasons_long or reasons_short) else 'no strong signals'}. "
        f"Confidence is a simple documented scaling of signal weight, not a statistically validated probability."
    )

    return FinalVerdict(
        market_regime=htf_regime.title(), htf_bias=htf_bias, mtf_bias=mtf_bias, ltf_condition=ltf_condition,
        primary_liquidity_target=(nearest_liquidity_up.price if overall_bias == "LONG" and nearest_liquidity_up
                                   else nearest_liquidity_down.price if nearest_liquidity_down else None),
        secondary_liquidity_target=(nearest_liquidity_down.price if overall_bias == "LONG" and nearest_liquidity_down
                                     else nearest_liquidity_up.price if nearest_liquidity_up else None),
        important_resistance=resistance, important_support=support,
        poc=profile.poc, vah=profile.vah, val=profile.val,
        cvd_state=cvd_state, oi_state=oi_state_str, funding_state=funding_state,
        liquidation_condition=liquidation_condition, squeeze_risk=squeeze_risk,
        trapped_participants=trapped, order_flow_state=order_flow_state,
        absorption_state=absorption_state, news_state=news_state,
        overall_bias=overall_bias, confidence=confidence, confidence_explanation=confidence_explanation,
        trade_plan=trade_plan, no_trade_reasons=no_trade_reasons,
    )


def _build_trade_plan(bias: str, price: float, up, down, reasons: List[str]) -> TradePlan:
    tp = TradePlan()
    reasons_text = ", ".join(reasons) if reasons else "current signal weight"

    if bias == "LONG":
        stop_ref = down.price if down else price * 0.99
        risk = price - stop_ref
        tp.long_entry_zone = f"{stop_ref:.4f} - {price:.4f} (on retest/confirmation, not market chase)"
        tp.long_confirmation = f"Wait for sweep of downside liquidity + reclaim + confirmation via: {reasons_text}"
        tp.invalidation = f"Close below {stop_ref:.4f}"
        tp.stop_loss_area = f"Just below {stop_ref:.4f}"
        tp.tp1 = round(price + risk * 1.5, 4)
        tp.tp2 = round(up.price, 4) if up else round(price + risk * 3, 4)
        tp.tp3 = round(tp.tp2 + risk, 4)
        tp.primary_liquidity_target = tp.tp2
        tp.expected_risk_reward = f"~1:{round((tp.tp1 - price) / risk, 2)} to TP1" if risk > 0 else "undetermined"
        tp.wait_for = (
            f"Do not long yet. Wait for sell-side liquidity sweep of {stop_ref:.4f}, reclaim, and "
            f"confirmation from: {reasons_text}."
        )
    else:
        stop_ref = up.price if up else price * 1.01
        risk = stop_ref - price
        tp.short_entry_zone = f"{price:.4f} - {stop_ref:.4f} (on retest/confirmation, not market chase)"
        tp.short_confirmation = f"Wait for sweep of upside liquidity + failed reclaim + confirmation via: {reasons_text}"
        tp.invalidation = f"Close above {stop_ref:.4f}"
        tp.stop_loss_area = f"Just above {stop_ref:.4f}"
        tp.tp1 = round(price - risk * 1.5, 4)
        tp.tp2 = round(down.price, 4) if down else round(price - risk * 3, 4)
        tp.tp3 = round(tp.tp2 - risk, 4)
        tp.primary_liquidity_target = tp.tp2
        tp.expected_risk_reward = f"~1:{round((price - tp.tp1) / risk, 2)} to TP1" if risk > 0 else "undetermined"
        tp.wait_for = (
            f"Do not short yet. Wait for external liquidity sweep above {stop_ref:.4f}, failed reclaim, "
            f"and confirmation from: {reasons_text}."
        )
    return tp


def _summarize_news(news_summary: dict) -> tuple:
    all_items = []
    for source, payload in news_summary.items():
        if payload["status"] == "REAL_IMPLEMENTED":
            all_items.extend(payload["items"])

    if not all_items:
        return "DATA_UNAVAILABLE", []

    high_risk = [i for i in all_items if i.sentiment == "HIGH_RISK"]
    bullish = [i for i in all_items if i.sentiment == "BULLISH"]
    bearish = [i for i in all_items if i.sentiment == "BEARISH"]

    if high_risk:
        return "High Risk", [i.title for i in high_risk[:3]]
    if len(bullish) > len(bearish):
        return "Bullish", [i.title for i in bullish[:3]]
    if len(bearish) > len(bullish):
        return "Bearish", [i.title for i in bearish[:3]]
    return "Neutral", [i.title for i in all_items[:3]]
