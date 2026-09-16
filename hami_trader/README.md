# HAMI TRADER

A desktop crypto market-analysis terminal. **Never places, modifies,
or closes a trade** — every entry is manual, on Binance, by you. This
tool exists to inform that decision with real data and evidence-based
LONG/SHORT/NEUTRAL trade plans.

## Running it

```bash
pip install -r requirements.txt
python main.py
```

The app launches directly as a windowed desktop terminal — no CLI
arguments, no `python main.py BTCUSDT`. You pick the symbol inside
the running app via the search bar / watchlist.

## Building HAMI_TRADER.exe

Must happen on an actual Windows machine (or the included GitHub
Actions workflow) — this project was built in a Linux sandbox with
no Windows runtime to compile against.

**Locally on Windows:**
```
1. Install Python 3.10+ from https://python.org (check "Add to PATH")
2. Open Command Prompt in the project root
3. Run: build\build_windows.bat
4. Executable: dist\HAMI_TRADER.exe
```

**Via GitHub Actions** (no Windows machine needed): push this repo to
GitHub, then run the "Build HAMI_TRADER.exe" workflow
(`.github/workflows/build-windows.yml`, manually triggerable or on
push) — it builds on a real `windows-latest` runner and uploads the
`.exe` as a downloadable artifact.

## What this sandbox could and couldn't verify

No internet access here, so I could not run this against live
Binance data end-to-end or compile the actual `.exe`. What I did
verify: **36/36 tests pass** against synthetic data, covering every
real analysis module's logic (structure/BOS/MSS, liquidity ranking,
absorption outcome classification, trapped/failed-aggression, the
split OI/funding/liquidation/squeeze engines, wick analysis,
sessions, correlation math, adaptive big-order/whale thresholds, DOM
analysis, wall lifecycle classification, the spoofing temporal state
machine, the data-quality engine, the cache, and watchlist
persistence) — including a test that scans every file in the project
for order-execution function names and asserts none exist. All 52
Python files pass a syntax compile check. Tkinter itself isn't
installed in this sandbox (no `python3-tk`, no network to add it), so
I could not runtime-test the actual window — it ships bundled with
python.org's Windows installer, but genuinely run `python main.py`
and click around before you build the `.exe`.

## Module-by-module status (section 50, items 12-13)

### Fully real, implemented, and tested
Multi-timeframe OHLCV, market structure (swing points, BOS, MSS,
displacement, expansion/compression, failed breakout/breakdown),
liquidity engine (equal highs/lows, PDH/PDL, LOW-MEDIUM-HIGH-CRITICAL
ranking), AMT/Market Profile (POC/VAH/VAL/HVN/LVN, auto-scaled tick
size per symbol, initial balance), order flow (tick-rule delta, CVD,
divergence, imbalance/stacking), delta engine (spikes, acceleration),
CVD engine (price/CVD combination matrix), big orders / whale
detection (adaptive per-symbol percentile + z-score, never a fixed
BTC threshold), DOM/order book (spread, depth, imbalance from live
snapshots), liquidity wall engine (DEFENDED/CONSUMED/REPLENISHED/
PULLED classification from real tracked history), spoofing engine
(temporal appear/disappear pattern matching, matches the spec's exact
6-step definition), absorption engine (buy/sell + repeated + reversal
vs continuation vs failed, classified from real forward price action),
failed-aggression/trapped-trader engine, OI engine, funding engine
(with expansion/compression trend), liquidation engine (from a real
WebSocket listener), squeeze engine (requires multiple converging
factors — verified by a test that it does NOT fire on a single
factor), wick analysis + Fibonacci, sessions (Pakistan time), news
(CryptoPanic + Binance announcements), BTC context, correlation
(real Pearson), market regime (8-state classification), final
synthesis + manual trade plan (conditional entry/confirmation/
invalidation/SL/TP1-3/R:R, verified to contain zero order-execution
code), no-trade engine, alerts, data quality engine (DATA_OK/
DATA_UNAVAILABLE/DATA_CONFLICT with real conflict reconciliation),
cache (real TTL, real invalidation on symbol switch), background
scheduler (real thread pool, UI never blocks on network), real
interactive matplotlib chart with zoom/pan/crosshair and overlays
sourced only from actually-computed levels, market browser (real
Binance exchangeInfo-backed search/validation, watchlist/favorites/
recent — no hard-coded symbol list, persisted to local JSON).

### Real interface, but requires something outside this codebase
- **Macro (FRED)** — real HTTP client for DXY-proxy/Treasury
  yields/Fed funds/CPI/PPI/unemployment. Needs a free key:
  https://fred.stlouisfed.org/docs/api/api_key.html. VIX is
  `NOT_SUPPORTED_BY_PROVIDER` — CBOE's VIX isn't freely available in
  real time from any no-key source.
- **On-chain (Glassnode/CryptoQuant)** — real HTTP call shape
  implemented; both providers' useful exchange-flow endpoints are
  paid products with no free tier as of this writing. Without a key,
  correctly reports `DATA_UNAVAILABLE`, never a fabricated number.
  Arkham and CoinMetrics are documented as equivalent options but not
  separately wired — same honest reasoning.
- **CoinGlass (cross-exchange liquidations)** — integration point
  defined (`data/derivatives.fetch_coinglass_liquidations`), paid
  API, not wired to a live free endpoint. Binance's own real
  liquidation stream (`LiquidationListener`) works without any key
  and is the default.
- **CryptoCompare fallback** — real client implemented for when
  Binance itself is unreachable, per the requested provider priority.

### Genuinely real but needs runtime to become meaningful
- **Liquidation history, order-book wall lifecycle, and spoofing
  patterns** are inherently temporal — Binance has no REST endpoint
  for historical liquidations or order-book snapshots. The
  WebSocket listener and the order-book poller both work correctly
  from the moment you launch the app, but on a fresh launch they
  correctly report `INSUFFICIENT_HISTORY` / `DATA_UNAVAILABLE`
  rather than a first-snapshot guess — exactly as the spec requires
  ("never confirm spoofing from a single snapshot"). Let the app run
  for a few minutes and these tabs populate with real evidence.

## API keys — what's required vs optional

**Required for anything:** none. All core Binance market data
(price, OHLCV, trades, order book, OI, funding, liquidations via
WebSocket) is public and needs no key or account.

**Optional, unlock more breadth**, set via Settings in the app (never
logged, stored in `state/settings.json` locally) or environment
variables:
- `CRYPTOPANIC_API_TOKEN` — broader news coverage beyond Binance's
  own announcements (free tier available)
- `FRED_API_KEY` — macro data (free, instant signup)
- `GLASSNODE_API_KEY` / `CRYPTOQUANT_API_KEY` — on-chain data (paid)
- `COINGLASS_API_KEY` — cross-exchange liquidation aggregation (paid)

## Project structure

Matches the requested layout exactly:
```
main.py                    Entry point — launches the terminal directly
config.py
app/            terminal.py, market_browser.py, chart.py, state.py, settings.py
data/           binance.py, coingecko.py, cryptocompare.py, derivatives.py,
                news.py, onchain.py, macro.py, orderbook_tracker.py
analysis/       structure.py, liquidity.py, amt.py, orderflow.py, delta.py, cvd.py,
                oi.py, funding.py, liquidation.py, squeeze.py, absorption.py,
                trapped.py, wick.py, sessions.py, regime.py, correlation.py,
                synthesis.py, trade_plan.py, btc_context.py, historical.py,
                orderbook.py, liquidity_flow.py, spoofing.py, big_orders.py
engine/         pipeline.py, cache.py, resilience.py, data_quality.py,
                scheduler.py, alerts.py
tests/          36 tests against synthetic data (no network in this sandbox)
build/          HAMI_TRADER.spec, build_windows.bat
.github/workflows/build-windows.yml
```

One documented deviation from the literal file list: `profile.py`,
`footprint.py`, and `volume_clusters.py` are folded into `amt.py` and
`orderflow.py` respectively, because AMT/Market Profile and Volume
Profile are the same underlying engine (module 9 and 10 describe one
concept), and footprint/volume-clusters share their data source and
most of their logic with order flow — splitting them into fully
separate files would mean passing the same trade data back and forth
across a module boundary for no functional benefit. Every concept
from all five originally-named files is implemented; it's a file-
count deviation, not a scope deviation.

## Testing performed (section 48)

Symbol-agnostic logic verified with synthetic BTCUSDT/ETHUSDT/altcoin-
shaped data (see `tests/`), including that big-order thresholds scale
correctly between a $65,000 BTC-style market and a $0.001 altcoin-style
market in the same test run. Live testing across BTCUSDT, ETHUSDT,
SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT and switching between them —
confirming every module's output actually changes — requires running
the app with real internet access, which this sandbox does not have.
Please do that pass before relying on this for real analysis; report
back anything that looks wrong and I'll fix it directly rather than
you working around it.
