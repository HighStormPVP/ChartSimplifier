"""py2app build script for ChartSimplifier.app (macOS).

Build a double-clickable .app bundle:

    cd mac
    python3 -m pip install -U py2app pywebview pyobjc
    python3 setup.py py2app

The finished app is written to mac/dist/ChartSimplifier.app. See mac/README.md.

The app reuses the shared, cross-platform simplifier.py and index.html from the
repository root - this script pulls them in from one level up.
"""

import os
from setuptools import setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP = [os.path.join(ROOT, "app.py")]
DATA_FILES = [os.path.join(ROOT, "index.html")]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.icns"),
    "plist": {
        "CFBundleName": "ChartSimplifier",
        "CFBundleDisplayName": "ChartSimplifier",
        "CFBundleIdentifier": "com.chartsimplifier",
        "CFBundleVersion": "1.3.0",
        "CFBundleShortVersionString": "1.3.0",
        "NSHighResolutionCapable": True,
        # Cocoa/WKWebView app; no dock menu weirdness on launch
        "LSApplicationCategoryType": "public.app-category.utilities",
    },
    "packages": ["webview"],
    "includes": ["simplifier"],
}

setup(
    app=APP,
    name="ChartSimplifier",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
