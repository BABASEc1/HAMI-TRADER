"""
Module 33: BTC / market-wide context.

Real Binance data for BTC's own price/structure/OI/funding; BTC
dominance and total market cap come from data/coingecko.py since
Binance doesn't expose those (they're market-cap-share metrics across
all exchanges, not something a single exchange can report).
"""

from dataclasses import dataclass
from typing import Optional
from data.binance import BinanceFeed, DataUnavailableError
from data import coingecko
from analysis import regime, oi as oi_module


@dataclass
class BTCContext:
    btc_price: float
    btc_regime: str
    btc_change_24h_pct: float
    btc_funding_rate: Optional[float]
    btc_oi_change_pct: Optional[float]
    btc_dominance_pct: Optional[float]
    total_market_cap_usd: Optional[float]
    dominance_status: str
    explanation: str


def get_btc_context() -> BTCContext:
    btc_feed = BinanceFeed("BTCUSDT")

    stats = btc_feed.get_24h_stats()
    btc_price = float(stats["lastPrice"])
    change_pct = float(stats["priceChangePercent"])

    candles_4h = btc_feed.get_klines("4h", limit=50)
    btc_regime = regime.classify_regime(candles_4h).regime

    funding_rate, oi_change = None, None
    try:
        oi_raw = oi_module.fetch_oi(btc_feed.client, "BTCUSDT")
        oi_change = oi_raw["oi_change_pct"]
        funding = btc_feed.client.futures_funding_rate(symbol="BTCUSDT", limit=1)
        funding_rate = float(funding[-1]["fundingRate"]) if funding else None
    except (DataUnavailableError, Exception):
        pass

    dominance_pct, total_mcap, dominance_status = None, None, "DATA_UNAVAILABLE"
    try:
        gm = coingecko.fetch_global_market_data()
        dominance_pct, total_mcap = gm.btc_dominance_pct, gm.total_market_cap_usd
        dominance_status = "REAL_IMPLEMENTED (source: CoinGecko, not Binance)"
    except coingecko.ProviderUnavailableError as e:
        dominance_status = f"DATA_UNAVAILABLE ({e.reason})"

    explanation = (
        f"BTC is {btc_regime} ({change_pct:+.2f}% over 24h). "
        + (f"Funding {funding_rate:+.4%}. " if funding_rate is not None else "Funding unavailable. ")
        + (f"BTC dominance {dominance_pct:.1f}%. " if dominance_pct is not None else "Dominance unavailable. ")
    )

    return BTCContext(
        btc_price=btc_price, btc_regime=btc_regime, btc_change_24h_pct=change_pct,
        btc_funding_rate=funding_rate, btc_oi_change_pct=oi_change,
        btc_dominance_pct=dominance_pct, total_market_cap_usd=total_mcap,
        dominance_status=dominance_status, explanation=explanation,
    )


def assess_symbol_vs_btc(symbol_regime: str, symbol_change_pct: float, btc_context: BTCContext) -> dict:
    if symbol_change_pct > 0 and btc_context.btc_change_24h_pct > 0:
        alignment, explanation = "supported", "Both symbol and BTC moving in the same direction."
    elif symbol_change_pct < 0 and btc_context.btc_change_24h_pct < 0:
        alignment, explanation = "supported", "Both symbol and BTC declining together — broad weakness, not isolated."
    elif abs(symbol_change_pct) > abs(btc_context.btc_change_24h_pct) * 1.5:
        alignment = "independent_strength" if symbol_change_pct > 0 else "independent_weakness"
        explanation = f"Symbol moving {symbol_change_pct:+.2f}% vs BTC's {btc_context.btc_change_24h_pct:+.2f}% — asset-specific driver likely."
    else:
        alignment, explanation = "opposed", f"Symbol ({symbol_change_pct:+.2f}%) diverging from BTC ({btc_context.btc_change_24h_pct:+.2f}%) — fighting broader flow."

    return {"alignment": alignment, "explanation": explanation}
