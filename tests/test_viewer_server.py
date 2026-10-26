from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from viewer_helpers import hex_id, item_doc, write_run

from newsviewer.api import App
from newsviewer.config import load_settings
from newsviewer.index import Library
from newsviewer.server import MAX_BODY, Activity, Handler

ITEM = hex_id(0xA1)


class FakeSocket:
    """Just enough of a socket for BaseHTTPRequestHandler: one request in, the response out."""

    def __init__(self, raw: bytes) -> None:
        self._raw = io.BytesIO(raw)
        self.sent = bytearray()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        return self._raw

    def sendall(self, data: bytes) -> None:
        self.sent += data


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def app(tmp_path: Path) -> Iterator[App]:
    pool = tmp_path / "pool"
    write_run(pool, "20261021-080000", [item_doc(ITEM, "第一条")])
    library = Library(pool, refresh_s=0)
    yield App(library, load_settings(pool), port=8765, instance="inst", on_shutdown=lambda: None)
    library.close()


def exchange(app: App, raw: bytes, activity: Activity | None = None) -> tuple[bytes, Any]:
    sock = FakeSocket(raw)
    server = SimpleNamespace(app=app, activity=activity or Activity())
    Handler(cast(Any, sock), ("127.0.0.1", 50000), cast(Any, server))
    head, _, body = bytes(sock.sent).partition(b"\r\n\r\n")
    return head, json.loads(body) if body else None


def test_a_request_is_translated_and_stamps_activity(app: App) -> None:
    clock = FakeClock()
    activity = Activity(clock=clock)
    clock.now = 50.0
    head, data = exchange(
        app, b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n\r\n", activity
    )
    assert head.startswith(b"HTTP/1.1 200")
    assert b"Content-Security-Policy" in head and b"application/json" in head
    assert data["instance"] == "inst"
    assert activity.idle_s() == 0.0


def test_query_strings_and_bodies_reach_the_app(app: App) -> None:
    head, page = exchange(
        app,
        b"GET /api/items?q=%E7%AC%AC%E4%B8%80 HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n\r\n",
    )
    assert head.startswith(b"HTTP/1.1 200") and [r["id"] for r in page["items"]] == [ITEM]
    body = b'{"starred": true}'
    raw = (
        f"PATCH /api/items/{ITEM}/state HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n"
        f"X-News-Viewer: 1\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    head, state = exchange(app, raw)
    assert head.startswith(b"HTTP/1.1 200") and state["starred_at"]


def test_an_oversized_body_is_refused(app: App) -> None:
    raw = (
        f"PUT /api/items/{ITEM}/note HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n"
        f"X-News-Viewer: 1\r\nContent-Length: {MAX_BODY + 1}\r\n\r\n"
    ).encode()
    head, data = exchange(app, raw)
    assert head.startswith(b"HTTP/1.1 413") and "too large" in data["error"]
