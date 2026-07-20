# ChartSimplifier for macOS

The desktop app runs natively on macOS - it's the same Python app as on Windows,
using pywebview's Cocoa/WKWebView backend for the native window and native file
dialogs. It reuses `simplifier.py` and `index.html` from the repo root unchanged.

## Download a prebuilt .app

Grab **ChartSimplifier-macOS.zip** from the
[latest release](https://github.com/HighStormPVP/ChartSimplifier/releases/latest),
unzip it, and drag **ChartSimplifier.app** to Applications. First launch:
**right-click -> Open** once (it's ad-hoc signed but not notarized, so Gatekeeper
asks the first time).

The prebuilt app is compiled on a GitHub-hosted Mac by
[`.github/workflows/build-macos.yml`](../.github/workflows/build-macos.yml) on
every `v*` tag - no local Mac required. It targets **Apple Silicon (arm64)**. On
an Intel Mac, run from source or build a `.app` yourself (below).

## Run from source (no build)

Requires Python 3 (from [python.org](https://www.python.org/downloads/macos/) or
Homebrew).

```
cd mac
./run.command          # or: python3 ../app.py
```

`run.command` installs `pywebview` + `pyobjc` on first run, then launches the app
in its own window. You can also double-click `run.command` in Finder.

## Build a .app bundle

```
cd mac
./build_app.command
```

This installs `py2app`, `pywebview`, and `pyobjc`, then produces
`mac/dist/ChartSimplifier.app`. Drag it to `/Applications`. The build must be run
on a Mac - py2app can't cross-compile from Windows/Linux.

Because the app isn't code-signed or notarized, the first launch needs
**right-click → Open** (or *System Settings → Privacy & Security → Open Anyway*).
To distribute it widely you'd sign and notarize it with an Apple Developer ID.

## What you get

Identical behaviour to the Windows app: pick a level **folder** or **ZIP**, the
two option switches, and **Export as ZIP or Folder**. The simplified level is
written next to the original.
