"""Small local web server for the dashboard (standard library only).

It listens on 127.0.0.1 only. Because any web page you open could send requests
to a local port, requests are rejected unless the Host header names this server
and changes (POST) carry the `X-Golf` header, which other sites cannot add.
"""

from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlparse

from golf.dashboard.api import ApiError, handle
from golf.dashboard.service import AppState

STATIC = Path(__file__).resolve().parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".png": "image/png"}


@lru_cache(maxsize=1)
def plotly_js() -> bytes:
    """The Plotly library, taken from the installed package so the page works offline."""
    from plotly.offline import get_plotlyjs

    return get_plotlyjs().encode("utf-8")


def make_handler(state: AppState, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "GolfDashboard"

        def log_message(self, format, *args):    # keep the console quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "Forbidden"})
            url = urlparse(self.path)
            path = unquote(url.path)
            if path.startswith("/api/"):
                return self._api("GET", path, dict(parse_qsl(url.query)), {})
            if path == "/plotly.js":
                return self._send(200, plotly_js(), TYPES[".js"], cache="max-age=86400")
            if path.startswith("/files/"):
                return self._file(path[len("/files/"):])
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (STATIC / name).resolve()
            if STATIC.resolve() in target.parents and target.is_file():
                return self._send(200, target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"))
            self._json(404, {"error": "Not found"})

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Golf") != "1":
                return self._json(403, {"error": "Forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "Request is not valid JSON"})
            self._api("POST", unquote(urlparse(self.path).path), {}, body)

        def _api(self, method: str, path: str, query: dict, body: dict) -> None:
            try:
                with state.lock:
                    payload = handle(state, method, path, query, body)
                self._json(200, payload)
            except ApiError as error:
                self._json(400, {"error": str(error)})
            except KeyError:
                self._json(404, {"error": "Not found"})
            except Exception as error:               # a bug: show it in the page and in the console
                traceback.print_exc()
                self._json(500, {"error": f"{type(error).__name__}: {error}"})

        def _file(self, relative: str) -> None:
            root = state.config.output_dir.resolve()
            target = (root / relative).resolve()
            if root in target.parents and target.suffix == ".png" and target.is_file():
                return self._send(200, target.read_bytes(), TYPES[".png"])
            self._json(404, {"error": "Not found"})

    return Handler


def create_server(state: AppState, port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, port))
    server.daemon_threads = True
    return server


def serve(config_path: Optional[Path] = None, port: int = 8765, open_browser: bool = True) -> None:
    state = AppState(config_path)
    server = create_server(state, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Dashboard running at {url}   (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
