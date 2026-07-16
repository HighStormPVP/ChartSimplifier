#!/bin/bash
# Double-click to run ChartSimplifier from source on macOS (no build needed).
cd "$(dirname "$0")/.." || exit 1
if ! python3 -c "import webview" >/dev/null 2>&1; then
  echo "First run: installing pywebview + pyobjc ..."
  python3 -m pip install --user pywebview pyobjc || {
    echo "Could not install dependencies. Install Python 3 from python.org and retry."
    exit 1
  }
fi
exec python3 app.py
