"""ChartSimplifier - local app that turns any ADOFAI chart into a layout.

Run with:  python app.py
Opens a small web UI in your browser. No dependencies beyond Python 3.8+.
"""

import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from simplifier import simplify_level

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
    # A frozen EXE re-invokes itself with --dialog; a source run uses python -c
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
            log_lines = []
            try:
                if not path:
                    raise ValueError("No level selected.")
                output = simplify_level(path, log_lines.append)
                self._send_json({"ok": True, "log": log_lines, "output": str(output)})
            except Exception as exc:  # surfaced in the UI console
                self._send_json({"ok": False, "log": log_lines, "error": str(exc)})
        else:
            self.send_error(404)


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
    print(f"ChartSimplifier running at {url}  (Ctrl+C to quit)")
    threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dialog":
        run_dialog_mode(sys.argv[2])
    else:
        main()
