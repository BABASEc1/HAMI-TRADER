"""
app/chart.py — Module 5: Real interactive chart.

Matplotlib candlesticks (built from real OHLCV) embedded in Tkinter
via FigureCanvasTkAgg, with mouse-wheel zoom, click-drag pan, and a
crosshair with OHLC readout. Overlays are drawn ONLY for levels the
analysis engine actually computed and passed in — every label on
this chart corresponds to a real calculated value, never a decorative
placeholder line.
"""

import tkinter as tk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
import numpy as np

BG = "#0d1117"
FG = "#c9d1d9"
GREEN = "#3fb950"
RED = "#f85149"
GRID = "#21262d"

OVERLAY_COLORS = {
    "PDH": "#d29922", "PDL": "#d29922", "equal_highs": "#f85149", "equal_lows": "#3fb950",
    "swing_high": "#58a6ff", "swing_low": "#58a6ff", "POC": "#e3b341", "VAH": "#a371f7", "VAL": "#a371f7",
    "entry": "#3fb950", "sl": "#f85149", "tp": "#3fb950",
}


class CandlestickChart(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.figure = Figure(figsize=(10, 6), dpi=100, facecolor=BG)
        self.ax = self.figure.add_subplot(111)
        self.ax_vol = self.ax.twinx()
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.crosshair_label = tk.Label(self, text="", bg=BG, fg=FG, font=("Consolas", 9), anchor="w")
        self.crosshair_label.pack(fill="x")

        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_drag)

        self._candles = []
        self._pan_start = None
        self._xlim_start = None

    def _style_axes(self):
        for ax in (self.ax, self.ax_vol):
            ax.set_facecolor(BG)
            ax.tick_params(colors=FG, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(GRID)
        self.ax.grid(True, color=GRID, linewidth=0.5, alpha=0.5)
        self.ax_vol.set_ylim(0, None)

    def plot(self, candles: list, overlays: dict = None, symbol: str = "", timeframe: str = ""):
        """candles: list of data.binance.Candle (real OHLCV).
        overlays: dict of {label: (price, type_key)} or
        {label: (price1, price2, type_key)} for zones — ONLY real
        computed values should ever be passed here."""
        self._candles = candles
        self.ax.clear()
        self.ax_vol.clear()
        self._style_axes()

        if not candles:
            self.ax.text(0.5, 0.5, "No data", color=FG, ha="center", transform=self.ax.transAxes)
            self.canvas.draw()
            return

        xs = np.arange(len(candles))
        opens = np.array([c.open for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        closes = np.array([c.close for c in candles])
        volumes = np.array([c.volume for c in candles])

        width = 0.6
        for x, o, h, l, c in zip(xs, opens, highs, lows, closes):
            color = GREEN if c >= o else RED
            self.ax.plot([x, x], [l, h], color=color, linewidth=0.8)
            rect = Rectangle((x - width / 2, min(o, c)), width, max(abs(c - o), 1e-9), color=color)
            self.ax.add_patch(rect)

        vol_colors = [GREEN if c >= o else RED for o, c in zip(opens, closes)]
        self.ax_vol.bar(xs, volumes, color=vol_colors, alpha=0.25, width=width)

        if overlays:
            self._draw_overlays(overlays, xs[-1])

        self.ax.set_xlim(-1, len(candles))
        self.ax.set_title(f"{symbol} — {timeframe}", color=FG, fontsize=10, loc="left")
        self.figure.tight_layout()
        self.canvas.draw()

    def _draw_overlays(self, overlays: dict, right_x: int):
        for label, spec in overlays.items():
            color = None
            for key, c in OVERLAY_COLORS.items():
                if key.lower() in label.lower():
                    color = c
                    break
            color = color or "#8b949e"

            if len(spec) == 2:
                price, _ = spec
                self.ax.axhline(price, color=color, linewidth=0.8, linestyle="--", alpha=0.8)
                self.ax.text(right_x, price, f" {label}: {price:.4g}", color=color, fontsize=7, va="bottom")
            elif len(spec) == 3:
                p1, p2, _ = spec
                self.ax.axhspan(min(p1, p2), max(p1, p2), color=color, alpha=0.08)
                self.ax.text(right_x, max(p1, p2), f" {label}", color=color, fontsize=7, va="bottom")

    def _on_mouse_move(self, event):
        if event.inaxes != self.ax or not self._candles or event.xdata is None:
            return
        idx = int(round(event.xdata))
        if 0 <= idx < len(self._candles):
            c = self._candles[idx]
            self.crosshair_label.configure(
                text=f"O:{c.open:.4g} H:{c.high:.4g} L:{c.low:.4g} C:{c.close:.4g} Vol:{c.volume:.2f}"
            )

    def _on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        cur_xlim = self.ax.get_xlim()
        scale = 0.85 if event.button == "up" else 1.15
        center = event.xdata if event.xdata is not None else (cur_xlim[0] + cur_xlim[1]) / 2
        new_left = center - (center - cur_xlim[0]) * scale
        new_right = center + (cur_xlim[1] - center) * scale
        self.ax.set_xlim(new_left, new_right)
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes != self.ax:
            return
        self._pan_start = event.xdata
        self._xlim_start = self.ax.get_xlim()

    def _on_release(self, event):
        self._pan_start = None
        self._xlim_start = None

    def _on_drag(self, event):
        if self._pan_start is None or event.inaxes != self.ax or event.xdata is None:
            return
        dx = self._pan_start - event.xdata
        self.ax.set_xlim(self._xlim_start[0] + dx, self._xlim_start[1] + dx)
        self.canvas.draw_idle()


def build_overlays_from_report(report) -> dict:
    """Converts real computed values from the analysis report into
    the chart's overlay format. Every entry here traces back to an
    actual calculated event — nothing decorative."""
    overlays = {}

    liq = report.modules.get("liquidity")
    if liq and liq.status == "REAL_IMPLEMENTED":
        for lvl in liq.data["levels"][:8]:  # top 8 by strength to avoid clutter
            overlays[f"{lvl.level_type}_{lvl.timeframe}"] = (lvl.price, lvl.level_type)

    profile = report.modules.get("market_profile")
    if profile and profile.status == "REAL_IMPLEMENTED":
        p = profile.data["profile"]
        overlays["POC"] = (p.poc, "POC")
        overlays["VAH_VAL"] = (p.vah, p.val, "VAH")

    verdict = report.final_verdict
    if verdict and verdict.overall_bias != "NEUTRAL":
        tp = verdict.trade_plan
        if tp.tp1:
            overlays["TP1"] = (tp.tp1, "tp")
        if tp.stop_loss_area:
            pass  # stop_loss_area is descriptive text, not a bare number — skip on chart

    return overlays
