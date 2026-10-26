"""http.server 胶水层：请求字节 -> api.Request，api.Response -> 字节，
外加供空闲看门狗线程读取的活动时间戳。"""

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
MAX_BODY = 1_000_000  # 单位是字节；页面发送的最大内容是笔记


class Activity:
    """服务上次应答请求的时间（monotonic 秒数），供空闲看门狗线程读取。"""

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
    # 在 Windows 上，SO_REUSEADDR 会让第二个服务也能绑定已被占用的端口。
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address: tuple[str, int]) -> None:
        self.app: App | None = None
        self.activity = Activity()
        super().__init__(address, Handler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind 还会解析一个我们用不到的主机名；跳过这次查询。
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
        """不输出：请求行只会让 server.log 越来越大。"""

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
            self.close_connection = True  # 请求体没有读取
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
    """绑定 127.0.0.1:<port>；该端口被占用时，让操作系统挑一个空闲端口。"""
    try:
        return ViewerHTTPServer((HOST, port))
    except OSError as exc:
        in_use = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
        if exc.errno not in in_use:
            raise
        return ViewerHTTPServer((HOST, 0))
