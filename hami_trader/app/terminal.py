"""
app/terminal.py — the desktop terminal. This is what main.py launches
directly (module 46's explicit requirement: no CLI, no
`python main.py BTCUSDT`). Symbol switching goes through
AppState.set_symbol, which every panel below subscribes to, so
switching pairs genuinely updates every module (module 3/48's
explicit requirement) rather than leaving stale tabs behind.
"""

import sys
import os
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.pipeline import AnalysisSession
from engine import resilience, scheduler
from engine.alerts import AlertManager
from app.state import AppState
from app.market_browser import SymbolDirectory, WatchlistManager
from app.chart import CandlestickChart, build_overlays_from_report
from app.settings import load_settings, save_settings, apply_settings_to_config, mask_key, SENSITIVE_KEYS
import config

log = resilience.setup_logging()

BG = "#0d1117"
PANEL_BG = "#161b22"
FG = "#c9d1d9"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d29922"


class HamiTraderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HAMI TRADER — Manual Trading Terminal (never places orders)")
        self.root.geometry("1600x950")
        self.root.configure(bg=BG)

        settings = load_settings()
        apply_settings_to_config(settings)
        self.settings = settings

        self.state = AppState(symbol=settings.default_symbol or config.DEFAULT_SYMBOL)
        self.session = AnalysisSession(self.state.symbol)
        self.symbol_directory = SymbolDirectory(self.session.feed.client)
        self.watchlist = WatchlistManager()
        self.alert_manager = AlertManager()
        self.scheduler = scheduler.BackgroundScheduler(max_workers=4)
        self.prior_verdict = None
        self.current_report = None

        self.state.on_symbol_change(self._on_symbol_changed)

        self._build_style()
        self._build_layout()

        self.watchlist.record_recent(self.state.symbol)
        self._refresh_watchlist_ui()
        self.run_analysis()
        self._poll_scheduler()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_BG, foreground=FG, padding=[10, 4])
        style.map("TNotebook.Tab", background=[("selected", ACCENT)])
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Consolas", 9))
        style.configure("Header.TLabel", background=BG, foreground=ACCENT, font=("Consolas", 11, "bold"))
        style.configure("TButton", font=("Consolas", 9, "bold"), padding=(8, 5))
        style.configure("Treeview", background=PANEL_BG, foreground=FG, fieldbackground=PANEL_BG)

    def _build_layout(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="HAMI TRADER", style="Header.TLabel").pack(side="left", padx=(0, 16))

        ttk.Label(top, text="Symbol:").pack(side="left")
        self.symbol_entry = ttk.Entry(top, font=("Consolas", 11), width=14)
        self.symbol_entry.insert(0, self.state.symbol)
        self.symbol_entry.pack(side="left", padx=(4, 4))
        self.symbol_entry.bind("<Return>", lambda e: self._search_symbol())

        self.go_btn = ttk.Button(top, text="GO", command=self._search_symbol)
        self.go_btn.pack(side="left", padx=(0, 4))
        self.watch_btn = ttk.Button(top, text="+ Watchlist", command=lambda: self._add_current_to_watchlist())
        self.watch_btn.pack(side="left", padx=(0, 4))
        self.fav_btn = ttk.Button(top, text="\u2605 Favorite", command=lambda: self._toggle_favorite())
        self.fav_btn.pack(side="left", padx=(0, 12))

        ttk.Label(top, text="Timeframe:").pack(side="left")
        self.tf_var = tk.StringVar(value=self.state.timeframe)
        tf_menu = ttk.Combobox(top, textvariable=self.tf_var, values=config.TIMEFRAMES, width=6, state="readonly")
        tf_menu.pack(side="left", padx=(4, 12))
        tf_menu.bind("<<ComboboxSelected>>", lambda e: self._on_timeframe_selected())

        self.analyze_btn = ttk.Button(top, text="ANALYZE", command=self.run_analysis)
        self.analyze_btn.pack(side="left", padx=(0, 12))

        self.status_label = ttk.Label(top, text="Ready")
        self.status_label.pack(side="left", padx=8)

        self.conn_label = ttk.Label(top, text="Connection: unknown", foreground=YELLOW)
        self.conn_label.pack(side="right")
        ttk.Button(top, text="Settings", command=self._open_settings).pack(side="right", padx=(0, 12))

        disclaimer = ttk.Label(
            self.root,
            text="MANUAL TRADING TOOL — this software never places, modifies, or closes orders. "
                 "You execute manually on Binance yourself.",
            foreground=YELLOW, background=BG, font=("Consolas", 8, "italic"),
        )
        disclaimer.pack(fill="x", padx=8)

        divider = tk.Frame(self.root, bg="#30363d", height=1)
        divider.pack(fill="x", padx=0, pady=(4, 0))

        main_pane = tk.PanedWindow(self.root, orient="horizontal", bg=BG, sashwidth=4)
        main_pane.pack(fill="both", expand=True, padx=8, pady=6)

        left = ttk.Frame(main_pane, width=220)
        main_pane.add(left, minsize=180)
        self._build_watchlist_panel(left)

        right = ttk.Frame(main_pane)
        main_pane.add(right, minsize=800)

        chart_and_tabs = tk.PanedWindow(right, orient="vertical", bg=BG, sashwidth=4)
        chart_and_tabs.pack(fill="both", expand=True)

        chart_frame = ttk.Frame(chart_and_tabs, height=380)
        chart_and_tabs.add(chart_frame, minsize=250)
        self.chart = CandlestickChart(chart_frame)
        self.chart.pack(fill="both", expand=True)

        tabs_frame = ttk.Frame(chart_and_tabs)
        chart_and_tabs.add(tabs_frame, minsize=300)
        self._build_tabs(tabs_frame)

    def _build_watchlist_panel(self, parent):
        ttk.Label(parent, text="WATCHLIST", style="Header.TLabel").pack(anchor="w", pady=(4, 2))
        self.watchlist_box = tk.Listbox(parent, bg=PANEL_BG, fg=FG, font=("Consolas", 10), height=8,
                                          selectbackground=ACCENT, selectforeground="#0d1117",
                                          borderwidth=0, highlightbackground="#30363d", highlightthickness=1)
        self.watchlist_box.pack(fill="x", pady=(0, 10))
        self.watchlist_box.bind("<Double-Button-1>", lambda e: self._select_from_list(self.watchlist_box))

        ttk.Label(parent, text="FAVORITES", style="Header.TLabel").pack(anchor="w", pady=(4, 2))
        self.favorites_box = tk.Listbox(parent, bg=PANEL_BG, fg=FG, font=("Consolas", 10), height=5,
                                          selectbackground=ACCENT, selectforeground="#0d1117",
                                          borderwidth=0, highlightbackground="#30363d", highlightthickness=1)
        self.favorites_box.pack(fill="x", pady=(0, 10))
        self.favorites_box.bind("<Double-Button-1>", lambda e: self._select_from_list(self.favorites_box))

        ttk.Label(parent, text="RECENT", style="Header.TLabel").pack(anchor="w", pady=(4, 2))
        self.recent_box = tk.Listbox(parent, bg=PANEL_BG, fg=FG, font=("Consolas", 10), height=10,
                                       selectbackground=ACCENT, selectforeground="#0d1117",
                                       borderwidth=0, highlightbackground="#30363d", highlightthickness=1)
        self.recent_box.pack(fill="x")
        self.recent_box.bind("<Double-Button-1>", lambda e: self._select_from_list(self.recent_box))

    def _build_tabs(self, parent):
        split = tk.PanedWindow(parent, orient="horizontal", bg=BG, sashwidth=4)
        split.pack(fill="both", expand=True)

        section_panel = ttk.Frame(split, width=170)
        split.add(section_panel, minsize=150)

        content_panel = ttk.Frame(split)
        split.add(content_panel, minsize=500)

        ttk.Label(section_panel, text="SECTIONS", style="Header.TLabel").pack(anchor="w", pady=(4, 2), padx=4)
        list_frame = tk.Frame(section_panel, bg=PANEL_BG)
        list_frame.pack(fill="both", expand=True, padx=(4, 0))
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self.section_list = tk.Listbox(
            list_frame, bg=PANEL_BG, fg=FG, font=("Consolas", 10), selectbackground=ACCENT,
            selectforeground="#0d1117", activestyle="none", borderwidth=0, highlightthickness=0,
            yscrollcommand=scrollbar.set,
        )
        self.section_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.section_list.yview)

        self.section_names = [
            "FINAL SYNTHESIS", "TRADE PLAN", "MARKET STRUCTURE", "MTF", "LIQUIDITY",
            "AMT / PROFILE", "ORDER FLOW", "DELTA / CVD", "BIG ORDERS", "DOM",
            "LIQUIDITY WALLS", "SPOOFING", "ABSORPTION / TRAPPED", "OI / FUNDING",
            "LIQUIDATIONS / SQUEEZE", "WICK", "SESSIONS", "NEWS", "MACRO", "ON-CHAIN",
            "BTC CONTEXT", "CORRELATION", "MARKET REGIME", "DATA STATUS", "ALERTS", "LOGS",
        ]
        for name in self.section_names:
            self.section_list.insert("end", f"  {name}")
        self.section_list.bind("<<ListboxSelect>>", self._on_section_selected)

        header_row = ttk.Frame(content_panel)
        header_row.pack(fill="x", padx=8, pady=(6, 0))
        self.section_title = ttk.Label(header_row, text="FINAL SYNTHESIS", style="Header.TLabel")
        self.section_title.pack(anchor="w")

        text_frame = tk.Frame(content_panel, bg=PANEL_BG, highlightbackground="#30363d", highlightthickness=1)
        text_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.content_text = tk.Text(
            text_frame, bg=PANEL_BG, fg=FG, insertbackground=FG, font=("Consolas", 10),
            wrap="word", padx=12, pady=10, borderwidth=0, highlightthickness=0,
        )
        self.content_text.pack(fill="both", expand=True)
        self.content_text.configure(state="disabled")
        self.content_text.tag_configure("long", foreground=GREEN, font=("Consolas", 14, "bold"))
        self.content_text.tag_configure("short", foreground=RED, font=("Consolas", 14, "bold"))
        self.content_text.tag_configure("neutral", foreground=YELLOW, font=("Consolas", 14, "bold"))

        # tabs dict kept for backward compatibility with _set_text/_render_module,
        # which write into whichever section is stored here by name
        self.tabs = {name: None for name in self.section_names}
        self._tab_content = {name: "" for name in self.section_names}
        self._tab_tag = {}

        self.section_list.selection_set(0)

    def _on_section_selected(self, event):
        sel = self.section_list.curselection()
        if not sel:
            return
        name = self.section_names[sel[0]]
        self.section_title.configure(text=name)
        self.content_text.configure(state="normal")
        self.content_text.delete("1.0", "end")
        tag = self._tab_tag.get(name)
        if tag:
            self.content_text.insert("end", self._tab_content[name], tag)
        else:
            self.content_text.insert("end", self._tab_content[name])
        self.content_text.configure(state="disabled")

    def _search_symbol(self):
        query = self.symbol_entry.get().strip().upper()
        if not query:
            return
        direct = self.symbol_directory.validate(query)
        matches = [direct] if direct else self.symbol_directory.search(query, limit=1)
        if not matches:
            messagebox.showwarning("Symbol not found", f"'{query}' isn't a valid, currently trading Binance symbol.")
            return
        self.state.set_symbol(matches[0].symbol)

    def _select_from_list(self, listbox):
        sel = listbox.curselection()
        if not sel:
            return
        text = listbox.get(sel[0]).strip()
        if text.startswith("("):
            return  # placeholder row like "(empty — click + Watchlist)"
        symbol = text.split(" ")[-1]
        self.state.set_symbol(symbol)

    def _add_current_to_watchlist(self):
        self.watchlist.add_to_watchlist(self.state.symbol)
        self._refresh_watchlist_ui()

    def _toggle_favorite(self):
        self.watchlist.toggle_favorite(self.state.symbol)
        self._refresh_watchlist_ui()

    def _refresh_watchlist_ui(self):
        self.watchlist_box.delete(0, "end")
        if self.watchlist.watchlist:
            for s in self.watchlist.watchlist:
                self.watchlist_box.insert("end", f"  {s}")
        else:
            self.watchlist_box.insert("end", "  (empty — click + Watchlist)")

        self.favorites_box.delete(0, "end")
        if self.watchlist.favorites:
            for s in self.watchlist.favorites:
                self.favorites_box.insert("end", f"  \u2605 {s}")
        else:
            self.favorites_box.insert("end", "  (none yet)")

        self.recent_box.delete(0, "end")
        if self.watchlist.recent:
            for s in self.watchlist.recent:
                self.recent_box.insert("end", f"  {s}")
        else:
            self.recent_box.insert("end", "  (none yet)")

    def _on_symbol_changed(self, new_symbol: str):
        self.symbol_entry.delete(0, "end")
        self.symbol_entry.insert(0, new_symbol)
        self.session.switch_symbol(new_symbol)
        self.watchlist.record_recent(new_symbol)
        self._refresh_watchlist_ui()
        self.run_analysis()

    def _on_timeframe_selected(self):
        self.state.set_timeframe(self.tf_var.get())
        self.run_analysis()

    def run_analysis(self):
        self.analyze_btn.configure(state="disabled")
        self.status_label.configure(text=f"Analyzing {self.state.symbol}...")
        self.scheduler.submit("analysis", self.session.run_full_analysis)

    def _poll_scheduler(self):
        for job in self.scheduler.drain_results(max_items=5):
            if job.job_id == "analysis":
                self.analyze_btn.configure(state="normal")
                if job.error:
                    log.error(f"Analysis failed: {job.error}")
                    self.status_label.configure(text=f"Error: {job.error}")
                else:
                    self._render_report(job.result)
        self.root.after(500, self._poll_scheduler)

    def _open_settings(self):
        SettingsDialog(self.root, self.settings, self._on_settings_saved)

    def _on_settings_saved(self, new_settings):
        self.settings = new_settings
        save_settings(new_settings)
        apply_settings_to_config(new_settings)
        messagebox.showinfo("Settings saved", "Some changes take effect on next analysis run.")

    def _on_close(self):
        self.session.shutdown()
        self.scheduler.shutdown()
        self.root.destroy()

    def _render_report(self, report):
        self.current_report = report
        self.status_label.configure(text=f"Analysis complete: {report.symbol}")
        self.conn_label.configure(
            text=f"Connection: {self.session.connection_monitor.status_text()}",
            foreground=GREEN if not self.session.connection_monitor.is_degraded else RED,
        )

        overlays = build_overlays_from_report(report)
        mtf = report.modules.get("multi_timeframe")
        candles = mtf.data.get(self.state.timeframe, []) if mtf and mtf.status == "REAL_IMPLEMENTED" else []
        self.chart.plot(candles, overlays, report.symbol, self.state.timeframe)

        v = report.final_verdict
        if v:
            tag = "long" if v.overall_bias == "LONG" else "short" if v.overall_bias == "SHORT" else "neutral"
            content = f"{v.overall_bias}   CONFIDENCE: {v.confidence}%\n\n" + v.render_text()
            self._set_text("FINAL SYNTHESIS", content, tag=tag)
            self.alert_manager.check_and_fire(v, report.symbol, self.prior_verdict)
            self.prior_verdict = v
        else:
            self._set_text("FINAL SYNTHESIS", "Final synthesis unavailable — see DATA STATUS section.", tag="neutral")

        self._set_text("TRADE PLAN", str(v.trade_plan.__dict__) if v else "Unavailable — see DATA STATUS.")
        self._render_module("MARKET STRUCTURE", report, "structure")
        self._render_module("MTF", report, "market_regime")
        self._render_module("LIQUIDITY", report, "liquidity")
        self._render_module("AMT / PROFILE", report, "market_profile")
        self._render_module("ORDER FLOW", report, "order_flow")
        self._render_module("DELTA / CVD", report, "order_flow")
        self._render_module("BIG ORDERS", report, "big_orders")
        self._render_module("DOM", report, "orderbook")
        self._render_module("LIQUIDITY WALLS", report, "liquidity_walls")
        self._render_module("SPOOFING", report, "spoofing")
        self._render_module("ABSORPTION / TRAPPED", report, "absorption_trap")
        self._render_module("OI / FUNDING", report, "oi")
        self._render_module("LIQUIDATIONS / SQUEEZE", report, "liquidations")
        self._render_module("WICK", report, "wick_analysis")
        self._render_module("SESSIONS", report, "sessions")
        self._render_module("NEWS", report, "news")
        self._render_module("MACRO", report, "macro")
        self._render_module("ON-CHAIN", report, "onchain")
        self._render_module("BTC CONTEXT", report, "btc_context")
        self._render_module("CORRELATION", report, "correlation")
        self._render_module("MARKET REGIME", report, "market_regime")

        self._set_text("DATA STATUS", report.data_quality_report.render_text() if report.data_quality_report else "n/a")
        self._render_alerts()
        self._render_logs()

    def _set_text(self, tab, content, tag=None):
        text = content if isinstance(content, str) else repr(content)
        self._tab_content[tab] = text
        self._tab_tag[tab] = tag
        # Only touch the widget if this section is currently the one shown
        sel = self.section_list.curselection()
        if sel and self.section_names[sel[0]] == tab:
            self.content_text.configure(state="normal")
            self.content_text.delete("1.0", "end")
            if tag:
                self.content_text.insert("end", text, tag)
            else:
                self.content_text.insert("end", text)
            self.content_text.configure(state="disabled")

    def _render_module(self, tab, report, key):
        mr = report.modules.get(key)
        if mr is None:
            self._set_text(tab, "No data.")
            return
        if mr.status != "REAL_IMPLEMENTED":
            self._set_text(tab, f"[{mr.status}]\n{mr.reason}")
            return
        self._set_text(tab, self._format_data(mr.data))

    def _format_data(self, data) -> str:
        if hasattr(data, "explanation"):
            return getattr(data, "explanation", "") + "\n\n" + repr(data)
        if isinstance(data, dict):
            return "\n".join(f"{k}: {v}" for k, v in data.items())
        if isinstance(data, list):
            return "\n".join(str(x) for x in data) if data else "None found this cycle."
        return str(data)

    def _render_alerts(self):
        try:
            with open(config.ALERT_LOG_FILE) as f:
                lines = f.readlines()[-50:]
            self._set_text("ALERTS", "".join(lines) if lines else "No alerts fired yet.")
        except FileNotFoundError:
            self._set_text("ALERTS", "No alerts fired yet.")

    def _render_logs(self):
        try:
            with open(config.LOG_FILE) as f:
                lines = f.readlines()[-100:]
            self._set_text("LOGS", "".join(lines))
        except FileNotFoundError:
            self._set_text("LOGS", "No logs yet.")


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=BG)
        self.geometry("500x400")
        self.settings = settings
        self.on_save = on_save
        self.entries = {}

        ttk.Label(self, text="API Keys (all optional — public Binance data needs none)", style="Header.TLabel").pack(pady=8)
        for key in sorted(SENSITIVE_KEYS):
            row = ttk.Frame(self)
            row.pack(fill="x", padx=12, pady=3)
            ttk.Label(row, text=key, width=25).pack(side="left")
            entry = ttk.Entry(row, show="*", width=30)
            entry.insert(0, settings.api_keys.get(key, ""))
            entry.pack(side="left")
            self.entries[key] = entry

        ttk.Button(self, text="Save", command=self._save).pack(pady=12)

    def _save(self):
        for key, entry in self.entries.items():
            self.settings.api_keys[key] = entry.get().strip()
        self.on_save(self.settings)
        self.destroy()


def main():
    root = tk.Tk()
    app = HamiTraderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
