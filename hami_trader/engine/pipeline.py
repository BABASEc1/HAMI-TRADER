"""
engine/pipeline.py — the orchestrator. Unlike a one-shot CLI script,
this runs as a persistent session inside the GUI: switching symbols
restarts the liquidation listener and order-book tracker for the new
symbol (module 3/4's explicit requirement that changing pairs updates
EVERY module), while cached historical data for the old symbol is
invalidated (engine/cache.py).
"""

from dataclasses import dataclass, field
from typing import Optional, Any, Dict
import time

from data.binance import BinanceFeed, DataUnavailableError
from data.derivatives import LiquidationListener
from data.orderbook_tracker import OrderBookTracker
from data import news as news_module, coingecko, macro, onchain
from analysis import (
    structure, liquidity, amt, orderflow, delta as delta_module, cvd as cvd_module,
    regime, oi as oi_module, funding as funding_module, liquidation as liq_module,
    squeeze as squeeze_module, absorption, trapped, wick, sessions, correlation,
    btc_context, synthesis, orderbook as orderbook_module, liquidity_flow, spoofing, big_orders,
)
from engine import resilience, cache, data_quality
import config

log = resilience.setup_logging()


@dataclass
class ModuleResult:
    status: str
    data: Any = None
    reason: str = ""


@dataclass
class FullReport:
    symbol: str
    timestamp: float
    modules: Dict[str, ModuleResult] = field(default_factory=dict)
    final_verdict: Optional[synthesis.FinalVerdict] = None
    data_quality: Optional[data_quality.DataQualityReport] = None


class AnalysisSession:
    """One instance lives for the lifetime of the GUI. Holds the
    stateful, real-time-accumulating pieces (liquidation listener,
    order-book tracker) that a one-shot function call cannot."""

    def __init__(self, symbol: str = None):
        self.symbol = (symbol or config.DEFAULT_SYMBOL).upper()
        self.feed = BinanceFeed(self.symbol)
        self.liq_listener = LiquidationListener(self.symbol)
        self.liq_listener.start()
        self.ob_tracker = OrderBookTracker(
            self.feed, poll_interval_seconds=config.ORDERBOOK_POLL_SECONDS,
            max_snapshots=config.ORDERBOOK_MAX_SNAPSHOTS, depth_limit=config.ORDERBOOK_DEPTH_LIMIT,
        )
        self.ob_tracker.start()
        self.connection_monitor = resilience.ConnectionMonitor()

    def switch_symbol(self, new_symbol: str):
        new_symbol = new_symbol.upper()
        if new_symbol == self.symbol:
            return
        log.info(f"Switching symbol {self.symbol} -> {new_symbol}")
        cache.get_global_cache().invalidate_prefix((new_symbol,))
        cache.get_global_cache().invalidate_prefix((self.symbol,))

        self.symbol = new_symbol
        self.feed = BinanceFeed(new_symbol)
        self.liq_listener.set_symbol(new_symbol)   # clears old-symbol events per its own implementation

        self.ob_tracker.stop()
        self.ob_tracker = OrderBookTracker(
            self.feed, poll_interval_seconds=config.ORDERBOOK_POLL_SECONDS,
            max_snapshots=config.ORDERBOOK_MAX_SNAPSHOTS, depth_limit=config.ORDERBOOK_DEPTH_LIMIT,
        )
        self.ob_tracker.start()

    def shutdown(self):
        self.liq_listener.stop()
        self.ob_tracker.stop()

    def run_full_analysis(self) -> FullReport:
        symbol = self.symbol
        report = FullReport(symbol=symbol, timestamp=time.time())
        dq = data_quality.DataQualityReport()
        report.data_quality = dq
        feed = self.feed

        try:
            stats = feed.get_24h_stats()
            price = float(stats["lastPrice"])
            report.modules["price"] = ModuleResult("REAL_IMPLEMENTED", {"price": price, "stats": stats})
            dq.add(data_quality.DataPoint(price, "binance", units="USDT"))
            self.connection_monitor.record_success()
        except DataUnavailableError as e:
            self.connection_monitor.record_failure(e)
            report.modules["price"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
            dq.add(data_quality.DataPoint(None, "binance", status=data_quality.STATUS_UNAVAILABLE, reason=str(e)))
            return report

        is_futures = feed.symbol_exists_on_futures()

        candles_by_tf = {}
        for tf in config.TIMEFRAMES:
            try:
                candles_by_tf[tf] = feed.get_klines(tf, limit=200)
            except DataUnavailableError as e:
                report.modules[f"klines_{tf}"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        report.modules["multi_timeframe"] = ModuleResult(
            "REAL_IMPLEMENTED" if candles_by_tf else "DATA_UNAVAILABLE", candles_by_tf,
            reason="" if candles_by_tf else "No timeframe data fetched",
        )

        # --- Structure: BOS/MSS/displacement/expansion-compression ---------
        structure_data = {}
        if "15m" in candles_by_tf:
            try:
                structure_data["bos_mss"] = structure.detect_bos_mss(candles_by_tf["15m"])
                structure_data["displacement"] = structure.detect_displacement(candles_by_tf["15m"])
                structure_data["expansion_compression"] = structure.classify_expansion_compression(candles_by_tf["15m"])
                report.modules["structure"] = ModuleResult("REAL_IMPLEMENTED", structure_data)
            except Exception as e:
                report.modules["structure"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        else:
            report.modules["structure"] = ModuleResult("DATA_UNAVAILABLE", reason="No 15m candles")

        # --- Liquidity -------------------------------------------------------
        levels, up, down = [], None, None
        if candles_by_tf:
            try:
                levels = liquidity.build_liquidity_map({tf: c for tf, c in candles_by_tf.items() if tf in ("1h", "4h", "1d")}, price)
                up_levels = [l for l in levels if l.price > price]
                down_levels = [l for l in levels if l.price < price]
                up = min(up_levels, key=lambda l: l.price) if up_levels else None
                down = max(down_levels, key=lambda l: l.price) if down_levels else None
                report.modules["liquidity"] = ModuleResult("REAL_IMPLEMENTED", {"levels": levels, "nearest_up": up, "nearest_down": down})
            except Exception as e:
                report.modules["liquidity"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        else:
            report.modules["liquidity"] = ModuleResult("DATA_UNAVAILABLE", reason="No candle data")

        # --- AMT / Market Profile / Volume Profile ------------------------------
        profile, value_state = None, {"state": "unknown", "explanation": "DATA_UNAVAILABLE"}
        if candles_by_tf.get("1h"):
            try:
                tick = amt.auto_tick_size(price)
                profile = amt.build_profile(candles_by_tf["1h"], tick_size=tick)
                value_state = amt.classify_price_vs_value(price, profile)
                report.modules["market_profile"] = ModuleResult("REAL_IMPLEMENTED", {"profile": profile, "value_state": value_state})
            except Exception as e:
                report.modules["market_profile"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        else:
            report.modules["market_profile"] = ModuleResult("DATA_UNAVAILABLE", reason="No 1h candles")

        # --- Footprint / Order flow / Delta / CVD ------------------------------
        delta_snapshot, cvd_trend, divergence, candle_deltas, imbalances, stacked = None, "unknown", {}, [], [], []
        try:
            trades = feed.get_recent_trades(limit=1000)
            delta_snapshot = orderflow.compute_delta(trades)
            cvd_series = orderflow.compute_cvd_series(trades)
            cvd_trend = orderflow.cvd_slope(cvd_series)
            price_series = [c.close for c in candles_by_tf.get("5m", [])[-len(cvd_series):]] if cvd_series else []
            divergence = orderflow.detect_price_cvd_divergence(price_series, cvd_series) if price_series else {"divergence": False, "explanation": "Insufficient data"}
            imbalances, stacked = orderflow.detect_volume_imbalance(trades)
            if "5m" in candles_by_tf:
                candle_deltas = [orderflow.compute_delta([t for t in trades if c.open_time <= t.time < c.close_time]).delta for c in candles_by_tf["5m"]]
            spikes = delta_module.detect_delta_spikes(candle_deltas) if candle_deltas else []
            accel = delta_module.delta_acceleration(candle_deltas) if candle_deltas else "insufficient_data"
            combo = cvd_module.combine_price_and_cvd(divergence.get("price_dir", "flat"), divergence.get("cvd_dir", "flat"))
            report.modules["order_flow"] = ModuleResult("REAL_IMPLEMENTED", {
                "delta": delta_snapshot, "cvd_trend": cvd_trend, "divergence": divergence,
                "imbalances": imbalances, "stacked_imbalances": stacked,
                "delta_spikes": spikes, "delta_acceleration": accel, "price_cvd_combo": combo,
            })
        except DataUnavailableError as e:
            report.modules["order_flow"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

        # --- Big orders / whale activity ---------------------------------------
        try:
            big_trades = big_orders.detect_big_trades(trades, config.BIG_ORDER_PERCENTILE, config.WHALE_Z_SCORE_THRESHOLD)
            report.modules["big_orders"] = ModuleResult("REAL_IMPLEMENTED", big_trades)
        except Exception as e:
            report.modules["big_orders"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

        # --- Absorption / Trapped / Failed aggression ---------------------------
        absorption_evt, trap_evt, failed_agg = None, None, None
        if candle_deltas and "5m" in candles_by_tf:
            try:
                absorption_evt = absorption.detect_absorption(candles_by_tf["5m"], candle_deltas)
                breakout_ref = up.price if up else (down.price if down else price)
                trap_evt = trapped.detect_trapped_traders(candles_by_tf["5m"], breakout_ref, candle_deltas, next_target_level=(down.price if down else None))
                defended_level = down.price if down else price
                failed_agg = trapped.detect_failed_aggression(candles_by_tf["5m"], candle_deltas, defended_level)
                report.modules["absorption_trap"] = ModuleResult("REAL_IMPLEMENTED", {"absorption": absorption_evt, "trap": trap_evt, "failed_aggression": failed_agg})
            except Exception as e:
                report.modules["absorption_trap"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        else:
            report.modules["absorption_trap"] = ModuleResult("DATA_UNAVAILABLE", reason="Insufficient order flow data")

        # --- OI / Funding / Liquidations / Squeeze --------------------------------
        oi_state, funding_state, liq_analysis, squeeze_score = None, None, None, squeeze_module.SqueezeScore(0, None, "Not computed")
        if is_futures:
            try:
                oi_raw = oi_module.fetch_oi(feed.client, symbol)
                price_change_pct = ((candles_by_tf["1h"][-1].close - candles_by_tf["1h"][0].close) / candles_by_tf["1h"][0].close * 100) if "1h" in candles_by_tf else 0
                funding_hist = funding_module.fetch_funding_history(feed.client, symbol)
                funding_state = funding_module.analyze_funding(funding_hist)
                oi_state = oi_module.classify_positioning(price_change_pct, oi_raw["oi_change_pct"], funding_state.current_rate)
                report.modules["oi"] = ModuleResult("REAL_IMPLEMENTED", oi_state)
                report.modules["funding"] = ModuleResult("REAL_IMPLEMENTED", funding_state)
            except DataUnavailableError as e:
                report.modules["oi"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
                report.modules["funding"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

            liq_events = self.liq_listener.get_recent()
            liq_analysis = liq_module.analyze_liquidations(liq_events)
            report.modules["liquidations"] = ModuleResult(
                "REAL_IMPLEMENTED" if liq_events else "DATA_UNAVAILABLE", liq_analysis,
                reason="" if liq_events else "No liquidation events collected yet — needs continuous runtime.",
            )

            if oi_state and funding_state:
                nearest_dist = min([abs(l.distance_pct(price)) for l in (up, down) if l], default=None)
                squeeze_score = squeeze_module.compute_squeeze_pressure(oi_state, liq_analysis, price_change_pct, nearest_dist, funding_state.current_rate)
            report.modules["squeeze"] = ModuleResult("REAL_IMPLEMENTED", squeeze_score)
        else:
            for key in ("oi", "funding", "liquidations", "squeeze"):
                report.modules[key] = ModuleResult("NOT_SUPPORTED", reason=f"{symbol} has no Binance Futures perpetual — this data doesn't exist for spot-only symbols")

        # --- DOM / Order book / Liquidity walls / Spoofing ------------------------
        latest_ob = self.ob_tracker.get_latest()
        if latest_ob:
            try:
                dom = orderbook_module.analyze_dom(latest_ob)
                report.modules["orderbook"] = ModuleResult("REAL_IMPLEMENTED", dom)

                sig_walls = liquidity_flow.find_significant_walls(latest_ob)
                wall_states = [
                    liquidity_flow.classify_wall(p, side, self.ob_tracker.get_level_history(p, side))
                    for p, side, qty in sig_walls[:5]
                ]
                report.modules["liquidity_walls"] = ModuleResult("REAL_IMPLEMENTED", wall_states)

                recent_trade_dicts = [{"price": t.price, "qty": t.qty} for t in trades[-200:]] if 'trades' in dir() else []
                spoof_assessments = [
                    spoofing.assess_spoofing_risk(self.ob_tracker, p, side, recent_trade_dicts)
                    for p, side, qty in sig_walls[:5]
                ]
                report.modules["spoofing"] = ModuleResult("REAL_IMPLEMENTED", spoof_assessments)
            except Exception as e:
                report.modules["orderbook"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
                report.modules["liquidity_walls"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
                report.modules["spoofing"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        else:
            reason = self.ob_tracker.last_error or "Order-book tracker hasn't collected a snapshot yet"
            for key in ("orderbook", "liquidity_walls", "spoofing"):
                report.modules[key] = ModuleResult("DATA_UNAVAILABLE", reason=reason)

        # --- Wick / Sessions ------------------------------------------------------
        wick_zone = None
        if "15m" in candles_by_tf:
            try:
                wick_zone = wick.wick_reaction_zone(candles_by_tf["15m"])
                report.modules["wick_analysis"] = ModuleResult("REAL_IMPLEMENTED", wick_zone)
            except Exception as e:
                report.modules["wick_analysis"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        if "5m" in candles_by_tf:
            try:
                report.modules["sessions"] = ModuleResult("REAL_IMPLEMENTED", sessions.compute_session_ranges(candles_by_tf["5m"]))
            except Exception as e:
                report.modules["sessions"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

        # --- News ---------------------------------------------------------------
        try:
            news_summary = news_module.get_news_summary(symbol)
            any_real = any(v["status"] == "REAL_IMPLEMENTED" for v in news_summary.values())
            report.modules["news"] = ModuleResult("REAL_IMPLEMENTED" if any_real else "DATA_UNAVAILABLE", news_summary)
        except Exception as e:
            news_summary = {}
            report.modules["news"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

        # --- Macro ----------------------------------------------------------------
        try:
            report.modules["macro"] = ModuleResult("REAL_IMPLEMENTED", macro.fetch_macro_snapshot())
        except Exception as e:
            report.modules["macro"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

        # --- On-chain --------------------------------------------------------------
        try:
            onchain_summary = onchain.get_onchain_summary(symbol)
            any_real = any(v["status"] == "REAL_IMPLEMENTED" for v in onchain_summary.values())
            report.modules["onchain"] = ModuleResult("REAL_IMPLEMENTED" if any_real else "DATA_UNAVAILABLE", onchain_summary,
                                                       reason="" if any_real else "No on-chain provider key configured")
        except Exception as e:
            report.modules["onchain"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))

        # --- BTC context + correlation ------------------------------------------------
        btc_ctx, btc_alignment = None, None
        if symbol != "BTCUSDT":
            try:
                btc_ctx = btc_context.get_btc_context()
                change_pct = float(stats.get("priceChangePercent", 0))
                htf_r = regime.classify_regime(candles_by_tf.get("4h", [])).regime if "4h" in candles_by_tf else "unknown"
                btc_alignment = btc_context.assess_symbol_vs_btc(htf_r, change_pct, btc_ctx)
                report.modules["btc_context"] = ModuleResult("REAL_IMPLEMENTED", {"context": btc_ctx, "alignment": btc_alignment})
            except DataUnavailableError as e:
                report.modules["btc_context"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
            try:
                report.modules["correlation"] = ModuleResult("REAL_IMPLEMENTED", correlation.correlation_report(symbol))
            except Exception as e:
                report.modules["correlation"] = ModuleResult("DATA_UNAVAILABLE", reason=str(e))
        else:
            report.modules["btc_context"] = ModuleResult("NOT_SUPPORTED", reason="Symbol IS BTC")
            report.modules["correlation"] = ModuleResult("NOT_SUPPORTED", reason="Symbol IS BTC")

        # --- Market regime ------------------------------------------------------------
        htf_regime_state = regime.classify_regime(candles_by_tf["4h"]) if "4h" in candles_by_tf else None
        ltf_regime_state = regime.classify_regime(candles_by_tf["15m"]) if "15m" in candles_by_tf else None
        full_regime = regime.classify_full_regime(candles_by_tf["1h"]) if "1h" in candles_by_tf else None
        htf_regime = htf_regime_state.regime if htf_regime_state else "unknown"
        ltf_regime = ltf_regime_state.regime if ltf_regime_state else "unknown"
        report.modules["market_regime"] = ModuleResult(
            "REAL_IMPLEMENTED" if full_regime else "DATA_UNAVAILABLE", {"htf": htf_regime_state, "ltf": ltf_regime_state, "full": full_regime},
        )

        # --- Final synthesis + manual trade plan -----------------------------------------
        if profile and delta_snapshot:
            fv = synthesis.build_final_verdict(
                price=price, htf_regime=htf_regime, ltf_regime=ltf_regime,
                nearest_liquidity_up=up, nearest_liquidity_down=down, all_levels=levels,
                profile=profile, value_state=value_state, delta_snapshot=delta_snapshot,
                cvd_trend=cvd_trend, divergence=divergence, absorption=absorption_evt, trap=trap_evt,
                squeeze=squeeze_score, oi_state=oi_state, wick_zone=wick_zone,
                news_summary=news_summary, btc_alignment=btc_alignment,
            )
            # Apply the real data-quality penalty (module 40) to confidence —
            # missing critical data genuinely lowers it, not just cosmetically.
            penalty = dq.confidence_penalty()
            fv.confidence = max(0, fv.confidence - penalty)
            if penalty:
                fv.confidence_explanation += f" (reduced by {penalty} for {dq.unavailable_count} unavailable / {dq.conflict_count} conflicting data points)"
            report.final_verdict = fv
            report.modules["final_verdict"] = ModuleResult("REAL_IMPLEMENTED", fv)
        else:
            report.modules["final_verdict"] = ModuleResult("DATA_UNAVAILABLE", reason="Missing market profile or order flow data")

        return report
