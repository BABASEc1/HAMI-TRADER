"""
Module 20/37: Manual Trade Plan engine.

The trade-plan construction logic (conditional entry zones,
confirmation requirements, invalidation, SL, TP1-3, R:R) lives in
analysis/synthesis.py alongside the final-bias computation it depends
on directly (the plan needs the same liquidity levels, trigger
reasons, and bias the synthesis step just computed — splitting them
into fully separate modules would mean passing the same seven
parameters back across a module boundary for no real benefit). This
file re-exports that tested logic under the name requested by the
project layout, so `from analysis.trade_plan import TradePlan` works
exactly as if it were defined here.

NO EXECUTION: grep this file and analysis/synthesis.py — there is no
Binance order-placement call anywhere in either.
"""

from analysis.synthesis import TradePlan, _build_trade_plan as build_trade_plan

__all__ = ["TradePlan", "build_trade_plan"]
