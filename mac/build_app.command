#!/bin/bash
# Double-click (or run) to build ChartSimplifier.app with py2app.
cd "$(dirname "$0")" || exit 1
python3 -m pip install -U py2app pywebview pyobjc || exit 1
rm -rf build dist
python3 setup.py py2app || exit 1
echo ""
echo "Built: $(pwd)/dist/ChartSimplifier.app"
echo "Drag it to /Applications to install."
