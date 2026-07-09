"""ChartSimplifier - local app that turns any ADOFAI chart into a layout.

Run with:  python app.py
Opens in its own native window (pywebview). Falls back to an Edge/Chrome app
window, then to a browser tab. Only optional dependency: pywebview.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from simplifier import simplify_level

try:
    import webview  # pywebview - native window
except Exception:
    webview = None

WINDOW = None  # the pywebview window, when running in native mode

APP_DIR = Path(__file__).resolve().parent
# When frozen into an EXE, PyInstaller unpacks bundled files to _MEIPASS
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
INDEX_FILE = BUNDLE_DIR / "index.html"
FROZEN = getattr(sys, "frozen", False)
PORT = 8347

# Native dialogs run in a subprocess so tkinter never fights the server threads
_DIALOG_LOCK = threading.Lock()


def run_dialog_mode(kind):
    """Executed in the child process: show the dialog, print the chosen path."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if kind == "folder":
        path = filedialog.askdirectory(title="Select your ADOFAI level folder")
    else:
        path = filedialog.askopenfilename(
            title="Select your zipped ADOFAI level",
            filetypes=[("ZIP files", "*.zip")])
    print(path or "")


def open_dialog(kind):
    # Native mode: pywebview's own file dialogs, parented to our window
    if WINDOW is not None:
        try:
            file_dialog = getattr(webview, "FileDialog", None)
            if kind == "folder":
                dialog_type = file_dialog.FOLDER if file_dialog else webview.FOLDER_DIALOG
                result = WINDOW.create_file_dialog(dialog_type)
            else:
                dialog_type = file_dialog.OPEN if file_dialog else webview.OPEN_DIALOG
                result = WINDOW.create_file_dialog(
                    dialog_type, file_types=("ZIP files (*.zip)",))
            if not result:
                return ""
            return result[0] if isinstance(result, (list, tuple)) else str(result)
        except Exception:
            pass  # fall through to the tkinter subprocess

    # A frozen EXE re-invokes itself with --dialog; a source run uses python
    if FROZEN:
        cmd = [sys.executable, "--dialog", kind]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve()), "--dialog", kind]
    with _DIALOG_LOCK:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result.stdout.strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal quiet

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = INDEX_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/pick-folder":
            self._send_json({"path": open_dialog("folder")})
        elif self.path == "/api/pick-zip":
            self._send_json({"path": open_dialog("zip")})
        elif self.path == "/api/simplify":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                payload = {}
            path = (payload.get("path") or "").strip().strip('"')
            options = {
                "keep_track_color": bool(payload.get("keepTrackColor", True)),
                "keep_camera": bool(payload.get("keepCamera", True)),
            }
            log_lines = []
            try:
                if not path:
                    raise ValueError("No level selected.")
                output = simplify_level(path, log_lines.append, options)
                self._send_json({"ok": True, "log": log_lines, "output": str(output)})
            except Exception as exc:  # surfaced in the UI console
                self._send_json({"ok": False, "log": log_lines, "error": str(exc)})
        else:
            self.send_error(404)


def find_app_browser():
    """A Chromium browser we can launch in app mode (own window, no tabs)."""
    candidates = [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        path = Path(os.path.expandvars(candidate))
        if path.is_file():
            return str(path)
    return None


def open_native_window(url):
    """True native window via pywebview (WebView2). Blocks until closed."""
    if webview is None:
        return False
    global WINDOW
    try:
        WINDOW = webview.create_window(
            "ChartSimplifier", url, width=640, height=900,
            background_color="#0c0d1a")
        webview.start()
        return True
    except Exception:
        WINDOW = None
        return False


def open_app_window(url):
    """Fallback: Edge/Chrome app-mode window. Blocks until closed."""
    browser = find_app_browser()
    if not browser:
        return False
    profile = Path(tempfile.gettempdir()) / "ChartSimplifierWindow"
    proc = subprocess.Popen([
        browser, f"--app={url}", f"--user-data-dir={profile}",
        "--window-size=640,900", "--no-first-run",
        "--no-default-browser-check",
    ])
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    shutil.rmtree(profile, ignore_errors=True)
    return True


def main():
    port = PORT
    server = None
    for _ in range(20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    if server is None:
        print("Could not find a free port.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        if not open_native_window(url) and not open_app_window(url):
            print(f"ChartSimplifier running at {url}  (Ctrl+C to quit)")
            webbrowser.open(url)
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    server.shutdown()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dialog":
        run_dialog_mode(sys.argv[2])
    else:
        main()
