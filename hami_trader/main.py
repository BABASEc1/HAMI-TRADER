"""
main.py — HAMI TRADER's entry point. Launches the desktop terminal
directly. No CLI arguments, no `python main.py BTCUSDT` required —
the symbol is chosen inside the running app via the Market Browser.
This is also the file PyInstaller targets to build HAMI_TRADER.exe
(see build/HAMI_TRADER.spec).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.terminal import main

if __name__ == "__main__":
    main()
