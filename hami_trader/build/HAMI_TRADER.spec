# PyInstaller spec. Run from the project root on Windows:
#     pyinstaller build\HAMI_TRADER.spec
# (see build/build_windows.bat for the full one-command version)

import os

block_cipher = None
project_root = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

a = Analysis(
    [os.path.join(project_root, "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=[
        (os.path.join(project_root, "config.py"), "."),
    ],
    hiddenimports=[
        "binance", "binance.client", "binance.exceptions",
        "websocket", "requests", "numpy", "matplotlib",
        "matplotlib.backends.backend_tkagg",
        "app", "app.terminal", "app.state", "app.market_browser", "app.chart", "app.settings",
        "data", "data.binance", "data.coingecko", "data.cryptocompare", "data.derivatives",
        "data.news", "data.onchain", "data.macro", "data.orderbook_tracker",
        "analysis", "analysis.structure", "analysis.liquidity", "analysis.amt",
        "analysis.orderflow", "analysis.delta", "analysis.cvd", "analysis.oi",
        "analysis.funding", "analysis.liquidation", "analysis.squeeze",
        "analysis.absorption", "analysis.trapped", "analysis.wick", "analysis.sessions",
        "analysis.regime", "analysis.correlation", "analysis.synthesis",
        "analysis.trade_plan", "analysis.btc_context", "analysis.historical",
        "analysis.orderbook", "analysis.liquidity_flow", "analysis.spoofing", "analysis.big_orders",
        "engine", "engine.pipeline", "engine.cache", "engine.resilience",
        "engine.data_quality", "engine.scheduler", "engine.alerts",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HAMI_TRADER",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
