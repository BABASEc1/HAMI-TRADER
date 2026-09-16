"""
Module 22: CVD engine.

CVD series/slope/divergence are computed from real trade data in
analysis/orderflow.py. This module adds the explicit price+CVD
combination matrix the spec requests, with mechanism explanations.
"""

from analysis.orderflow import compute_cvd_series, cvd_slope, detect_price_cvd_divergence, CVDPoint  # re-exported

__all__ = ["compute_cvd_series", "cvd_slope", "detect_price_cvd_divergence", "CVDPoint", "combine_price_and_cvd"]


def combine_price_and_cvd(price_dir: str, cvd_dir: str) -> dict:
    """price_dir/cvd_dir: 'up', 'down', or 'flat'. Real combination
    logic, not a signal — explains the mechanism per the spec."""
    if price_dir == "up" and cvd_dir == "up":
        return {"state": "confirmed_bullish", "explanation": "Price rising with CVD rising — aggressive buying is driving the move; order flow confirms price."}
    if price_dir == "up" and cvd_dir == "down":
        return {"state": "bearish_divergence", "explanation": "Price rising while CVD falls — the rise is happening despite net aggressive selling, often from short covering or thin liquidity rather than genuine demand. Worth watching, not a signal alone."}
    if price_dir == "down" and cvd_dir == "down":
        return {"state": "confirmed_bearish", "explanation": "Price falling with CVD falling — aggressive selling is driving the move; order flow confirms price."}
    if price_dir == "down" and cvd_dir == "up":
        return {"state": "bullish_divergence", "explanation": "Price falling while CVD rises — the decline is happening despite net aggressive buying, often from long liquidation/forced selling absorbing buy pressure rather than genuine supply. Worth watching, not a signal alone."}
    return {"state": "flat", "explanation": "Price and/or CVD are flat — no meaningful directional read this window."}
