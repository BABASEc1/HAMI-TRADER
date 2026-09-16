@echo off
REM Run from the PROJECT ROOT on a Windows machine:
REM     build\build_windows.bat
REM Requires Python 3.10+ from python.org (bundles Tkinter) and internet
REM access to install dependencies.

echo === HAMI TRADER - Windows EXE build ===

python -m venv build_venv
call build_venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo Building HAMI_TRADER.exe...
pyinstaller build\HAMI_TRADER.spec --distpath dist --workpath build\work --clean

echo.
echo === Build complete ===
echo Your executable is at: dist\HAMI_TRADER.exe
echo Double-click it to run - no Python needed on the machine afterward.
echo.
echo To configure optional API keys (news breadth, macro, on-chain),
echo launch the app and open Settings, or set environment variables
echo before launching (see README.md).

pause
