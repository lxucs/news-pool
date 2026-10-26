from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from viewer_helpers import hex_id, item_doc, write_run

from newsviewer.api import App, Request
from newsviewer.config import load_settings
from newsviewer.index import Library

ITEM = hex_id(0xA1)
OTHER = hex_id(0xA2)
UNKNOWN = hex_id(0xFFF)
HOST = {"host": "127.0.0.1:8765"}
WRITE = {**HOST, "x-news-viewer": "1"}


@dataclass
class Env:
    app: App
    shutdowns: list[bool] = field(default_factory=list)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    pool = tmp_path / "pool"
    write_run(
        pool,
        "20261021-080000",
        [item_doc(ITEM, "第一条", importance=0.9), item_doc(OTHER, "第二条", importance=0.3)],
    )
    static = tmp_path / "static"
    (static / "vendor").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (static / "app.js").write_text("export {};", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not for the browser", encoding="utf-8")
    library = Library(pool, refresh_s=0)
    shutdowns: list[bool] = []
    app = App(
        library,
        load_settings(pool),
        port=8765,
        instance="inst",
        on_shutdown=lambda: shutdowns.append(True),
        static_dir=static,
    )
    yield Env(app, shutdowns)
    library.close()


def call(
    app: App,
    method: str,
    path: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
    **query: str,
) -> tuple[int, Any]:
    if body is None:
        raw = b""
    elif isinstance(body, bytes):
        raw = body
    else:
        raw = json.dumps(body).encode("utf-8")
    if headers is None:
        headers = HOST if method == "GET" else WRITE
    resp = app.handle(Request(method, path, query, headers, raw))
    return resp.status, json.loads(resp.body)


def test_requests_for_another_host_are_refused(env: Env) -> None:
    status, data = call(env.app, "GET", "/api/health", headers={"host": "evil.example:8765"})
    assert status == 403 and "Host" in data["error"]
    assert call(env.app, "GET", "/api/health", headers={})[0] == 403
    assert call(env.app, "GET", "/api/health", headers={"host": "localhost:8765"})[0] == 200


def test_health_identifies_the_instance(env: Env) -> None:
    status, data = call(env.app, "GET", "/api/health")
    assert status == 200
    assert data["app"] == "news-viewer" and data["instance"] == "inst" and data["pid"] > 0


def test_writes_need_the_viewer_header(env: Env) -> None:
    url = f"/api/items/{ITEM}/state"
    assert call(env.app, "PATCH", url, {"starred": True}, headers=HOST)[0] == 403
    status, state = call(env.app, "PATCH", url, {"starred": True})
    assert status == 200 and state["starred_at"]


def test_list_items_and_its_parameters(env: Env) -> None:
    status, page = call(env.app, "GET", "/api/items")
    assert status == 200 and page["total"] == 2
    assert [r["id"] for r in page["items"]] == [ITEM, OTHER]
    assert call(env.app, "GET", "/api/items", view="nope")[0] == 400
    assert call(env.app, "GET", "/api/items", offset="-1")[0] == 400
    assert call(env.app, "GET", "/api/items", limit="abc")[0] == 400
    assert call(env.app, "GET", "/api/items", view="collection")[0] == 400
    _, page = call(env.app, "GET", "/api/items", limit="1")
    assert len(page["items"]) == 1 and page["total"] == 2
    _, page = call(env.app, "GET", "/api/items", limit="100000")  # 截到上限，而不是拒绝
    assert len(page["items"]) == 2


def test_item_detail_and_unknown_ids(env: Env) -> None:
    status, detail = call(env.app, "GET", f"/api/items/{ITEM}")
    assert status == 200 and detail["item"]["title_zh"] == "第一条"
    assert call(env.app, "GET", f"/api/items/{UNKNOWN}")[0] == 404
    assert call(env.app, "GET", "/api/items/not-an-id")[0] == 404


def test_state_validation(env: Env) -> None:
    url = f"/api/items/{ITEM}/state"
    assert call(env.app, "PATCH", url, b"{not json")[0] == 400
    assert call(env.app, "PATCH", url, {})[0] == 400
    assert call(env.app, "PATCH", url, {"starred": "yes"})[0] == 400
    _, state = call(env.app, "PATCH", url, {"hidden": True, "read": True})
    assert state["hidden_at"] and state["read_at"]


def test_notes(env: Env) -> None:
    _, state = call(env.app, "PUT", f"/api/items/{ITEM}/note", {"note": "要跟进"})
    assert state["note"] == "要跟进"
    assert call(env.app, "PUT", f"/api/items/{ITEM}/note", {"note": 3})[0] == 400
    assert call(env.app, "PUT", f"/api/items/{UNKNOWN}/note", {"note": "x"})[0] == 404


def test_mark_read_by_ids_and_by_day(env: Env) -> None:
    assert call(env.app, "POST", "/api/read", {"ids": [ITEM]}) == (200, {"updated": 1})
    assert call(env.app, "POST", "/api/read", {"fetch_day": "261022"}) == (200, {"updated": 1})
    assert call(env.app, "POST", "/api/read", {"fetch_day": "2026-10-22"})[0] == 400
    assert call(env.app, "POST", "/api/read", {"ids": "abc"})[0] == 400


def test_collections(env: Env) -> None:
    status, c = call(env.app, "POST", "/api/collections", {"name": "跟进"})
    assert status == 200 and (c["name"], c["count"]) == ("跟进", 0)
    assert call(env.app, "POST", "/api/collections", {"name": "跟进"})[0] == 409
    assert call(env.app, "POST", "/api/collections", {"name": "  "})[0] == 400
    cid = c["cid"]
    assert call(env.app, "PUT", f"/api/collections/{cid}/items/{ITEM}") == (200, {"ok": True})
    assert call(env.app, "PUT", f"/api/collections/{cid}/items/{UNKNOWN}")[0] == 404
    _, page = call(env.app, "GET", "/api/items", view="collection", cid=str(cid))
    assert [r["id"] for r in page["items"]] == [ITEM]
    _, c = call(
        env.app, "PATCH", f"/api/collections/{cid}", {"name": "待跟进", "description": "本周"}
    )
    assert (c["name"], c["description"], c["count"]) == ("待跟进", "本周", 1)
    assert call(env.app, "DELETE", f"/api/collections/{cid}/items/{ITEM}")[0] == 200
    assert call(env.app, "DELETE", f"/api/collections/{cid}")[0] == 200
    assert call(env.app, "DELETE", f"/api/collections/{cid}")[0] == 404


def test_meta_carries_the_client_settings(env: Env) -> None:
    status, meta = call(env.app, "GET", "/api/meta")
    assert status == 200
    assert meta["settings"] == {"heartbeat_s": 60, "page_size": 50}
    assert meta["counts"]["latest"] == 2 and meta["version"]


def test_shutdown_and_unknown_routes(env: Env) -> None:
    assert call(env.app, "POST", "/api/shutdown", {}) == (200, {"ok": True})
    assert env.shutdowns == [True]
    assert call(env.app, "GET", "/api/nope")[0] == 404
    assert call(env.app, "DELETE", "/api/meta")[0] == 405


def test_static_files_and_containment(env: Env) -> None:
    resp = env.app.handle(Request("GET", "/", {}, HOST))
    assert resp.status == 200 and resp.content_type.startswith("text/html")
    assert resp.headers["Cache-Control"] == "no-cache"
    assert "unsafe-eval" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    js = env.app.handle(Request("GET", "/app.js", {}, HOST))
    assert js.content_type.startswith("text/javascript")
    for path in ("/../secret.txt", "/vendor", "/missing.js"):
        assert env.app.handle(Request("GET", path, {}, HOST)).status == 404
    assert env.app.handle(Request("POST", "/", {}, WRITE)).status == 405
