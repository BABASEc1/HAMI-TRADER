import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.binance import Candle, Trade
from analysis import structure, amt, orderflow, wick, sessions, correlation


def make_candles(closes, vol=10.0, dt=300000, start=1_700_000_000_000):
    candles = []
    t = start
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        candles.append(Candle(open_time=t, open=o, high=h, low=l, close=c, volume=vol, close_time=t + dt))
        t += dt
    return candles


def test_swing_points_still_work_after_migration():
    closes = [100, 101, 102, 105, 103, 102, 101, 99, 98, 100, 102, 104]
    candles = make_candles(closes)
    highs, lows = structure.find_swing_points(candles, lookback=2)
    assert len(highs) >= 1 and len(lows) >= 1
    print("test_swing_points_still_work_after_migration: PASS")


def test_amt_profile_still_works():
    closes = [100] * 50 + [110] * 5
    candles = make_candles(closes)
    profile = amt.build_profile(candles, tick_size=1.0)
    assert profile.val <= profile.poc <= profile.vah
    print(f"test_amt_profile_still_works: PASS (POC={profile.poc})")


def test_auto_tick_size_scales_with_price():
    btc_tick = amt.auto_tick_size(65000)
    alt_tick = amt.auto_tick_size(0.05)
    assert btc_tick > alt_tick
    print(f"test_auto_tick_size_scales_with_price: PASS (BTC={btc_tick}, alt={alt_tick})")


def test_orderflow_delta_still_works():
    trades = [Trade(price=100, qty=1.0, time=i, is_buyer_maker=(i % 3 == 0)) for i in range(10)]
    d = orderflow.compute_delta(trades)
    assert d.trade_count == 10
    print(f"test_orderflow_delta_still_works: PASS (delta={d.delta})")


def test_wick_analysis_still_works():
    c = Candle(open_time=0, open=100, high=110, low=99.5, close=100.5, volume=10, close_time=60000)
    wm = wick.analyze_candle_wicks(c, 0)
    assert wm.classification == "upper_wick_rejection"
    print("test_wick_analysis_still_works: PASS")


def test_sessions_still_work():
    n = 288
    closes = [100 + (i % 20) for i in range(n)]
    candles = make_candles(closes, dt=300000, start=1_700_000_000_000 - (1_700_000_000_000 % 86400000))
    ranges = sessions.compute_session_ranges(candles)
    assert len(ranges) > 0
    print(f"test_sessions_still_work: PASS ({len(ranges)} sessions)")


def test_correlation_math_still_works():
    a = [100 + i for i in range(50)]
    b = [200 + i * 2 for i in range(50)]
    corr = correlation.compute_correlation(a, b)
    assert corr > 0.99
    print("test_correlation_math_still_works: PASS")


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
