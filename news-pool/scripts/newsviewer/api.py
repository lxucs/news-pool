"""HTTP API 和静态文件合成一个纯函数：App.handle(Request) -> Response。

server.py 只负责在 http.server 与这些 dataclass 之间转换，所以这里的每条规则（路由、只认
localhost 的 Host 检查、写请求头、静态文件路径不越界）都不用 socket 就能测试。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .errors import ApiError, Forbidden, MethodNotAllowed, NotFound
from .index import VIEWS, Library, Query
from .paths import STATIC_DIR
from .poolread import ID_PATTERN

APP_NAME = "news-viewer"
WRITE_HEADER = "x-news-viewer"  # 每个非 GET 请求都要带 `X-News-Viewer: 1`（防跨站写入）
MAX_LIMIT = 200  # 每页行数的上限，免得 `limit=10**9` 拖住服务
JSON_TYPE = "application/json; charset=utf-8"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".md": "text/plain; charset=utf-8",
}
# 'unsafe-eval'：Vue 在浏览器里编译页面的模板（没有构建步骤）。
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https: http: data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_DAY_RE = re.compile(r"\d{6}")


@dataclass(frozen=True)
class Request:
    method: str
    path: str  # 已做百分号解码，不含查询字符串
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)  # 名字为小写
    body: bytes = b""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = JSON_TYPE
    headers: dict[str, str] = field(default_factory=dict)


def json_response(obj: Any, status: int = 200) -> Response:
    return Response(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


class App:
    def __init__(
        self,
        library: Library,
        settings: dict[str, Any],
        *,
        port: int,
        instance: str,
        on_shutdown: Callable[[], None],
        static_dir: Path = STATIC_DIR,
    ) -> None:
        self.library = library
        self.instance = instance
        self._settings = settings
        self._hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._on_shutdown = on_shutdown
        self._static_dir = static_dir.resolve()
        item = f"(?P<id>{ID_PATTERN})"
        cid = r"(?P<cid>\d+)"
        routes: list[tuple[str, str, Callable[[Request, dict[str, str]], Any]]] = [
            ("GET", "/api/health", self._health),
            ("GET", "/api/meta", self._meta),
            ("GET", "/api/items", self._items),
            ("GET", f"/api/items/{item}", self._item),
            ("PATCH", f"/api/items/{item}/state", self._state),
            ("PUT", f"/api/items/{item}/note", self._note),
            ("POST", "/api/read", self._read),
            ("POST", "/api/collections", self._create_collection),
            ("PATCH", f"/api/collections/{cid}", self._update_collection),
            ("DELETE", f"/api/collections/{cid}", self._delete_collection),
            ("PUT", f"/api/collections/{cid}/items/{item}", self._collect),
            ("DELETE", f"/api/collections/{cid}/items/{item}", self._uncollect),
            ("POST", "/api/shutdown", self._shutdown),
        ]
        self._routes = [(method, re.compile(path), fn) for method, path, fn in routes]

    def handle(self, req: Request) -> Response:
        try:
            if req.headers.get("host", "") not in self._hosts:
                raise Forbidden("unexpected Host header; the viewer only answers on localhost")
            resp = self._api(req) if req.path.startswith("/api/") else self._static(req)
        except ApiError as exc:
            resp = json_response({"error": str(exc)}, exc.status)
        headers = {**SECURITY_HEADERS, **resp.headers}
        return Response(resp.status, resp.body, resp.content_type, headers)

    # --- 路由 ------------------------------------------------------------------------------

    def _api(self, req: Request) -> Response:
        allowed: list[str] = []
        for method, pattern, fn in self._routes:
            match = pattern.fullmatch(req.path)
            if match is None:
                continue
            if method != req.method:
                allowed.append(method)
                continue
            if method != "GET" and req.headers.get(WRITE_HEADER) != "1":
                raise Forbidden("writes need the X-News-Viewer: 1 header")
            return json_response(fn(req, match.groupdict()))
        if allowed:
            raise MethodNotAllowed(f"{req.method} is not allowed here; use {', '.join(allowed)}")
        raise NotFound(f"no such endpoint: {req.path}")

    def _static(self, req: Request) -> Response:
        if req.method not in ("GET", "HEAD"):
            raise MethodNotAllowed("static files are GET only")
        target = (self._static_dir / (req.path.lstrip("/") or "index.html")).resolve()
        if self._static_dir not in target.parents or not target.is_file():
            raise NotFound(f"no such file: {req.path}")
        content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        return Response(200, target.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    # --- 接口 ------------------------------------------------------------------------------

    def _health(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        return {
            "app": APP_NAME,
            "version": __version__,
            "pool": str(self.library.pool),
            "instance": self.instance,
            "pid": os.getpid(),
        }

    def _meta(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        meta = self.library.meta()
        meta["version"] = __version__
        meta["settings"] = {
            "heartbeat_s": self._settings["heartbeat_s"],
            "page_size": self._settings["page_size"],
        }
        return meta

    def _items(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        q = req.query
        view = q.get("view", "latest")
        if view not in VIEWS:
            raise ApiError(f"view must be one of: {', '.join(VIEWS)}")
        offset = _int_param(q, "offset", 0)
        if offset < 0:
            raise ApiError("offset must not be negative")
        limit = _int_param(q, "limit", int(self._settings["page_size"]))
        query = Query(
            view=view,
            cid=_int_param(q, "cid", 0) if q.get("cid") else None,
            category=q.get("category", ""),
            tag=q.get("tag", ""),
            source=q.get("source", ""),
            run=q.get("run", ""),
            q=q.get("q", ""),
            offset=offset,
            limit=min(max(limit, 1), MAX_LIMIT),
        )
        return self.library.list_items(query)

    def _item(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        return self.library.item(params["id"])

    def _state(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        body = _body(req)
        flags = {key: _optional_bool(body, key) for key in ("starred", "read", "hidden")}
        if all(value is None for value in flags.values()):
            raise ApiError("send at least one of starred, read, hidden")
        return self.library.set_state(
            params["id"], starred=flags["starred"], read=flags["read"], hidden=flags["hidden"]
        )

    def _note(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        note = _body(req).get("note")
        if not isinstance(note, str):
            raise ApiError("note must be a string")
        return self.library.set_note(params["id"], note)

    def _read(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        body = _body(req)
        if "fetch_day" in body:
            day = body["fetch_day"]
            if not isinstance(day, str) or _DAY_RE.fullmatch(day) is None:
                raise ApiError("fetch_day must be yymmdd")
            return {"updated": self.library.mark_read(fetch_day=day)}
        ids = body.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ApiError("send ids (a list of item ids) or fetch_day")
        return {"updated": self.library.mark_read(ids=ids)}

    def _create_collection(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        body = _body(req)
        name, description = body.get("name"), body.get("description", "")
        if not isinstance(name, str) or not isinstance(description, str):
            raise ApiError("name and description must be strings")
        return self.library.create_collection(name, description)

    def _update_collection(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        body = _body(req)
        name, description = body.get("name"), body.get("description")
        for value in (name, description):
            if value is not None and not isinstance(value, str):
                raise ApiError("name and description must be strings")
        return self.library.update_collection(
            int(params["cid"]), name=name, description=description
        )

    def _delete_collection(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        self.library.delete_collection(int(params["cid"]))
        return {"ok": True}

    def _collect(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        self.library.collect(int(params["cid"]), params["id"])
        return {"ok": True}

    def _uncollect(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        self.library.uncollect(int(params["cid"]), params["id"])
        return {"ok": True}

    def _shutdown(self, req: Request, params: dict[str, str]) -> dict[str, Any]:
        self._on_shutdown()
        return {"ok": True}


def _body(req: Request) -> dict[str, Any]:
    if not req.body:
        return {}
    try:
        obj = json.loads(req.body.decode("utf-8"))
    except ValueError as exc:  # UnicodeDecodeError 也是 ValueError
        raise ApiError("the request body must be JSON") from exc
    if not isinstance(obj, dict):
        raise ApiError("the request body must be a JSON object")
    return obj


def _int_param(query: dict[str, str], key: str, default: int) -> int:
    raw = query.get(key, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ApiError(f"{key} must be an integer") from exc


def _optional_bool(body: dict[str, Any], key: str) -> bool | None:
    value = body.get(key)
    if value is not None and not isinstance(value, bool):
        raise ApiError(f"{key} must be true or false")
    return value
