import sys, os, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.binance import Candle, Trade
from data.orderbook_tracker import OrderBookSnapshot, OrderBookTracker
from analysis import structure, liquidity, amt, orderflow, delta as delta_mod, cvd as cvd_mod
from analysis import oi as oi_mod, funding as funding_mod, liquidation as liq_mod, squeeze as squeeze_mod
from analysis import absorption, trapped, wick, sessions, regime, big_orders
from analysis import orderbook as orderbook_mod, liquidity_flow, spoofing
from engine import data_quality, cache as cache_mod
from app.market_browser import WatchlistManager
import config


def make_candles(closes, highs=None, lows=None, vol=10.0, dt=300000, start=1_700_000_000_000):
    candles = []
    t = start
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = highs[i] if highs else max(o, c) + 0.5
        l = lows[i] if lows else min(o, c) - 0.5
        candles.append(Candle(open_time=t, open=o, high=h, low=l, close=c, volume=vol, close_time=t + dt))
        t += dt
    return candles


# --- Structure: BOS/MSS ------------------------------------------------------
def test_bos_detected_on_uptrend_continuation():
    # Clear uptrend: higher highs, higher lows, then a continuation break
    closes = [100, 102, 101, 104, 103, 107, 105, 110]
    candles = make_candles(closes)
    events = structure.detect_bos_mss(candles, lookback=1, min_break_pct=0.01)
    assert any(e.event_type in ("BOS", "MSS") for e in events), "Expected at least one structural break"
    print(f"test_bos_detected_on_uptrend_continuation: PASS ({len(events)} events)")


def test_displacement_detects_real_outlier():
    normal = [100 + (i % 3) * 0.1 for i in range(25)]
    candles = make_candles(normal)
    # Append a genuine outlier candle
    big = Candle(open_time=candles[-1].close_time, open=100, high=115, low=99, close=114, volume=50,
                 close_time=candles[-1].close_time + 300000)
    candles.append(big)
    events = structure.detect_displacement(candles, lookback=20, multiple_threshold=2.0)
    assert len(events) >= 1
    print(f"test_displacement_detects_real_outlier: PASS (multiple={events[-1].range_multiple})")


def test_failed_breakout_matches_spec_example():
    # Breakout above level then returns below within lookforward
    closes = [100, 100, 100, 106, 101, 99, 98]
    candles = make_candles(closes)
    result = structure.detect_failed_breakout(candles, level=105, is_high=True, lookforward=3)
    assert result is not None
    assert "failed breakout" in result["explanation"]
    print("test_failed_breakout_matches_spec_example: PASS")


# --- Liquidity ranking ----------------------------------------------------------
def test_liquidity_rank_is_timeframe_aware():
    closes = [100 + (i % 5) for i in range(40)]
    candles_1d = make_candles(closes, dt=86400000)
    candles_1m = make_candles(closes, dt=60000)
    levels = liquidity.build_liquidity_map({"1d": candles_1d, "1m": candles_1m}, current_price=102)
    ranks_1d = [l.rank for l in levels if l.timeframe == "1d"]
    ranks_1m = [l.rank for l in levels if l.timeframe == "1m"]
    if ranks_1d and ranks_1m:
        rank_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        assert max(rank_order[r] for r in ranks_1d) >= max(rank_order[r] for r in ranks_1m), \
            "1D levels should rank at least as high as 1m levels"
    print(f"test_liquidity_rank_is_timeframe_aware: PASS ({len(levels)} levels)")


# --- Absorption outcome classification -------------------------------------------
def test_absorption_outcome_reversal():
    closes = [100, 99.9, 99.8, 99.85]
    candles = make_candles(closes)
    deltas = [-1, -6, -7, -6]
    forward = make_candles([100.5, 101, 101.5], start=candles[-1].close_time)
    event = absorption.detect_absorption(candles, deltas, lookforward=forward)
    assert event is not None
    assert event.outcome == "reversal", event.outcome
    print("test_absorption_outcome_reversal: PASS")


def test_absorption_outcome_failed():
    closes = [100, 99.9, 99.8, 99.85]
    candles = make_candles(closes)
    deltas = [-1, -6, -7, -6]
    forward = make_candles([99.5, 99, 98.5], start=candles[-1].close_time)
    event = absorption.detect_absorption(candles, deltas, lookforward=forward)
    assert event is not None
    assert event.outcome == "failed", event.outcome
    print("test_absorption_outcome_failed: PASS")


# --- Trapped / Failed aggression ----------------------------------------------------
def test_failed_aggression_detection():
    closes = [100, 100.1, 100.05]
    highs = [104.9, 104.95, 104.9]
    lows = [99.5, 99.6, 99.5]
    candles = make_candles(closes, highs=highs, lows=lows)
    deltas = [4, 5, 6]
    event = trapped.detect_failed_aggression(candles, deltas, defended_level=105, next_target_level=95)
    assert event is not None
    assert event.aggressor_side == "buyers"
    print("test_failed_aggression_detection: PASS")


# --- OI / Funding / Liquidation / Squeeze split modules -----------------------------
def test_oi_classification_with_funding():
    s = oi_mod.classify_positioning(price_change_pct=1.0, oi_change_pct=1.0, funding_rate=0.0008)
    assert s.classification == "new_longs"
    assert s.funding_rate == 0.0008
    print("test_oi_classification_with_funding: PASS")


def test_funding_extreme_detection():
    history = [{"fundingRate": "0.0001"}, {"fundingRate": "0.0002"}, {"fundingRate": "0.0009"}, {"fundingRate": "0.0012"}]
    state = funding_mod.analyze_funding(history)
    assert state.is_extreme is True
    print(f"test_funding_extreme_detection: PASS (trend={state.trend})")


def test_liquidation_cascade_classification():
    events = [{"side": "SELL", "time": i, "qty": 1.0} for i in range(10)]
    analysis = liq_mod.analyze_liquidations(events, cascade_threshold=8)
    assert analysis.is_cascade is True
    assert analysis.dominant_side == "long_liquidations"
    print("test_liquidation_cascade_classification: PASS")


def test_squeeze_requires_converging_evidence():
    oi_state = oi_mod.OIState(0, 2.0, 0.0008, 0.0, "new_shorts", "test")
    liq_events = [{"side": "SELL", "time": i, "qty": 1.0} for i in range(10)]
    liq_analysis = liq_mod.analyze_liquidations(liq_events)
    score = squeeze_mod.compute_squeeze_pressure(oi_state, liq_analysis, price_velocity_pct=1.5,
                                                    distance_to_liquidity_pct=0.2, funding_rate=0.0008)
    assert score.score >= 50
    assert score.direction is not None
    print(f"test_squeeze_requires_converging_evidence: PASS (score={score.score})")


def test_squeeze_does_not_fire_on_single_factor():
    oi_state = oi_mod.OIState(0, 0.1, 0.0001, 0.0, "unclear", "test")
    liq_analysis = liq_mod.analyze_liquidations([])
    score = squeeze_mod.compute_squeeze_pressure(oi_state, liq_analysis, price_velocity_pct=0.2,
                                                    distance_to_liquidity_pct=None, funding_rate=0.0001)
    assert score.direction is None, "Should not call a squeeze on weak/no evidence"
    print("test_squeeze_does_not_fire_on_single_factor: PASS")


# --- Big orders / whale adaptive threshold ---------------------------------------------
def test_big_orders_adaptive_per_symbol():
    import random
    random.seed(42)
    # Simulate a low-price altcoin: normal trades ~$50-200, one whale-sized outlier
    trades = [Trade(price=0.001, qty=random.uniform(50000, 200000), time=i, is_buyer_maker=False) for i in range(50)]
    trades.append(Trade(price=0.001, qty=50_000_000, time=999, is_buyer_maker=False))  # huge outlier
    big = big_orders.detect_big_trades(trades, percentile_threshold=95, whale_z_threshold=5.0)
    assert len(big) >= 1
    assert any(b.classification == "WHALE_ACTIVITY" for b in big), [b.classification for b in big]
    print(f"test_big_orders_adaptive_per_symbol: PASS ({len(big)} big trades found)")


def test_big_orders_single_moderately_large_trade_not_whale():
    import random
    random.seed(1)
    trades = [Trade(price=100, qty=random.uniform(1, 5), time=i, is_buyer_maker=False) for i in range(50)]
    trades.append(Trade(price=100, qty=8, time=999, is_buyer_maker=False))  # large but not an extreme outlier
    big = big_orders.detect_big_trades(trades, percentile_threshold=95, whale_z_threshold=5.0)
    if big:
        assert big[-1].classification != "WHALE_ACTIVITY", "Moderately large single trade should not auto-label as whale"
    print("test_big_orders_single_moderately_large_trade_not_whale: PASS")


# --- DOM / Wall / Spoofing (synthetic snapshot sequences) ----------------------------
def test_dom_analysis_basic():
    snap = OrderBookSnapshot(timestamp=time.time(), bids={100: 5, 99.9: 3, 99.8: 50}, asks={100.1: 4, 100.2: 2})
    dom = orderbook_mod.analyze_dom(snap)
    assert dom.best_bid == 100 and dom.best_ask == 100.1
    assert dom.largest_bid_wall == (99.8, 50)
    print(f"test_dom_analysis_basic: PASS (imbalance={dom.imbalance_state})")


def test_wall_classification_insufficient_history():
    result = liquidity_flow.classify_wall(100, "bid", [(1, 10), (2, 10)])
    assert result.classification == "INSUFFICIENT_HISTORY"
    print("test_wall_classification_insufficient_history: PASS")


def test_wall_classification_pulled():
    history = [(1, 50), (2, 48), (3, 52), (4, None)]  # present then vanishes, price never reached it
    result = liquidity_flow.classify_wall(100, "bid", history, price_reached_level=False)
    assert result.classification == "PULLED"
    print("test_wall_classification_pulled: PASS")


def test_wall_classification_replenished():
    history = [(1, 10), (2, 12), (3, 20), (4, 25)]
    result = liquidity_flow.classify_wall(100, "bid", history)
    assert result.classification == "REPLENISHED"
    print("test_wall_classification_replenished: PASS")


def test_spoofing_no_evidence_on_single_disappearance():
    class FakeTracker:
        def get_level_history(self, price, side, tol):
            return [(1, 50), (2, 50), (3, 50), (4, 50), (5, 50), (6, None)]
    result = spoofing.assess_spoofing_risk(FakeTracker(), 100, "bid", recent_trades=[])
    assert result.classification == "NO_CLEAR_SPOOFING_EVIDENCE"
    print("test_spoofing_no_evidence_on_single_disappearance: PASS")


def test_spoofing_high_risk_on_repeated_pattern_without_execution():
    class FakeTracker:
        def get_level_history(self, price, side, tol):
            # appears, vanishes, appears, vanishes, appears, vanishes -> 3 transitions
            return [(1, 50), (2, None), (3, 50), (4, None), (5, 50), (6, None), (7, 50)]
    result = spoofing.assess_spoofing_risk(FakeTracker(), 100, "bid", recent_trades=[])
    assert result.classification == "HIGH_SPOOFING_RISK", result.classification
    print("test_spoofing_high_risk_on_repeated_pattern_without_execution: PASS")


def test_spoofing_history_unavailable_with_too_few_snapshots():
    class FakeTracker:
        def get_level_history(self, price, side, tol):
            return [(1, 50), (2, 50)]
    result = spoofing.assess_spoofing_risk(FakeTracker(), 100, "bid", recent_trades=[], min_observations=6)
    assert result.classification == "ORDER_BOOK_HISTORY_UNAVAILABLE"
    print("test_spoofing_history_unavailable_with_too_few_snapshots: PASS")


# --- Data quality engine ------------------------------------------------------------
def test_data_quality_conflict_detection():
    primary = data_quality.DataPoint(value=100.0, source="binance")
    secondary = data_quality.DataPoint(value=105.0, source="fallback")
    result = data_quality.reconcile(primary, secondary, tolerance_pct=1.0)
    assert result.status == data_quality.STATUS_CONFLICT
    print("test_data_quality_conflict_detection: PASS")


def test_data_quality_confidence_penalty():
    report = data_quality.DataQualityReport()
    report.add(data_quality.DataPoint(1, "a", status=data_quality.STATUS_OK))
    report.add(data_quality.DataPoint(None, "b", status=data_quality.STATUS_UNAVAILABLE, reason="x"))
    report.add(data_quality.DataPoint(None, "c", status=data_quality.STATUS_CONFLICT, reason="y"))
    penalty = report.confidence_penalty()
    assert penalty == 15  # 5 + 10
    print("test_data_quality_confidence_penalty: PASS")


# --- Cache engine ------------------------------------------------------------------
def test_cache_ttl_behavior():
    cache = cache_mod.TTLCache()
    cache.set(("k",), "v1", ttl_seconds=10)
    value, hit = cache.get(("k",))
    assert hit and value == "v1"

    cache.set(("k2",), "v2", ttl_seconds=-1)  # already expired
    value2, hit2 = cache.get(("k2",))
    assert not hit2
    print("test_cache_ttl_behavior: PASS")


def test_cache_invalidate_prefix():
    cache = cache_mod.TTLCache()
    cache.set(("BTCUSDT", "klines"), [1, 2, 3], ttl_seconds=60)
    cache.set(("ETHUSDT", "klines"), [4, 5, 6], ttl_seconds=60)
    cache.invalidate_prefix(("BTCUSDT",))
    _, hit_btc = cache.get(("BTCUSDT", "klines"))
    _, hit_eth = cache.get(("ETHUSDT", "klines"))
    assert not hit_btc and hit_eth
    print("test_cache_invalidate_prefix: PASS")


# --- Watchlist persistence ------------------------------------------------------------
def test_watchlist_persists_across_instances():
    with tempfile.TemporaryDirectory() as d:
        wf = os.path.join(d, "watchlist.json")
        rf = os.path.join(d, "recent.json")
        wm1 = WatchlistManager(watchlist_file=wf, recent_file=rf)
        wm1.add_to_watchlist("ETHUSDT")
        wm1.toggle_favorite("BTCUSDT")
        wm1.record_recent("SOLUSDT")

        wm2 = WatchlistManager(watchlist_file=wf, recent_file=rf)
        assert "ETHUSDT" in wm2.watchlist
        assert "BTCUSDT" in wm2.favorites
        assert "SOLUSDT" in wm2.recent
        print("test_watchlist_persists_across_instances: PASS")


def test_watchlist_recent_cap_and_ordering():
    with tempfile.TemporaryDirectory() as d:
        wm = WatchlistManager(watchlist_file=os.path.join(d, "w.json"), recent_file=os.path.join(d, "r.json"))
        for i in range(config.MAX_RECENT_PAIRS + 5):
            wm.record_recent(f"SYM{i}USDT")
        assert len(wm.recent) == config.MAX_RECENT_PAIRS
        assert wm.recent[0] == f"SYM{config.MAX_RECENT_PAIRS + 4}USDT"  # most recent first
        print("test_watchlist_recent_cap_and_ordering: PASS")


# --- Regime full classification -------------------------------------------------------
def test_full_regime_trending():
    closes = list(range(100, 150))
    candles = make_candles(closes)
    result = regime.classify_full_regime(candles)
    assert result["label"] == "TRENDING"
    print(f"test_full_regime_trending: PASS ({result['label']})")


# --- No order-placement code anywhere (critical safety check) --------------------------
def test_no_order_execution_code_anywhere():
    import glob, inspect
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    forbidden = ["create_order", "futures_create_order", "cancel_order", "futures_cancel"]
    violations = []
    for path in glob.glob(os.path.join(project_root, "**", "*.py"), recursive=True):
        if "/tests/" in path or path.endswith("test_hami_trader.py"):
            continue
        with open(path) as f:
            content = f.read()
        for term in forbidden:
            if term in content:
                violations.append((path, term))
    assert not violations, f"Found forbidden order-execution code: {violations}"
    print("test_no_order_execution_code_anywhere: PASS")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"{t.__name__}: FAIL — {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"{t.__name__}: ERROR — {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)
