"""http.server glue: request bytes -> api.Request, api.Response -> bytes, plus the activity
stamp the idle watchdog reads."""

from __future__ import annotations

import errno
import socketserver
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

from .api import SECURITY_HEADERS, App, Request, Response, json_response

HOST = "127.0.0.1"
MAX_BODY = 1_000_000  # bytes; a note is the largest thing the page sends


class Activity:
    """When the server last answered a request (monotonic seconds), for the idle watchdog."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last = clock()

    def touch(self) -> None:
        with self._lock:
            self._last = self._clock()

    def idle_s(self) -> float:
        with self._lock:
            return self._clock() - self._last


class ViewerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second server bind a port that is already in use.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address: tuple[str, int]) -> None:
        self.app: App | None = None
        self.activity = Activity()
        super().__init__(address, Handler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind also resolves a host name we never use; skip that lookup.
        socketserver.TCPServer.server_bind(self)
        self.server_name = HOST
        self.server_port = int(self.server_address[1])

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class Handler(BaseHTTPRequestHandler):
    server_version = "news-viewer"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet: request lines would only grow server.log."""

    def _dispatch(self) -> None:
        server = cast("ViewerHTTPServer", self.server)
        server.activity.touch()
        app = server.app
        assert app is not None, "serve() sets the app before serving"
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            message = "request body too large" if length > MAX_BODY else "bad Content-Length"
            base = json_response({"error": message}, 413 if length > MAX_BODY else 400)
            response = Response(base.status, base.body, base.content_type, dict(SECURITY_HEADERS))
            self.close_connection = True  # the body was not read
        else:
            body = self.rfile.read(length) if length else b""
            parts = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
            headers = {k.lower(): v for k, v in self.headers.items()}
            response = app.handle(Request(self.command, unquote(parts.path), query, headers, body))
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)


def make_server(port: int) -> ViewerHTTPServer:
    """Bind 127.0.0.1:<port>; if that port is taken, let the OS pick a free one."""
    try:
        return ViewerHTTPServer((HOST, port))
    except OSError as exc:
        in_use = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
        if exc.errno not in in_use:
            raise
        return ViewerHTTPServer((HOST, 0))
