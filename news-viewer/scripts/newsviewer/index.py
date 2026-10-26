"""条目索引：已 finalize 的运行载入一个内存 SQLite 数据库，库上同时 attach 了 viewer.db，
所以视图、过滤条件、搜索、用户标记和分页都是同一条查询。

已 finalize 的运行不会再变，所以索引只增不减：refresh() 补上自上次查看以来新 finalize 的运行。
每个公共方法都持有同一个 lock；服务在多个 thread 上应答，而连接只有一个。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import poolread, userdb
from .errors import ApiError, NotFound
from .paths import VIEWER_DIR

VIEWS = ("latest", "unread", "starred", "notes", "hidden", "collection")
COUNTED_VIEWS = ("latest", "unread", "starred", "notes", "hidden")
FLAG_KEYS = ("is_breaking", "is_opinion", "needs_review")

_SCHEMA = """
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, focus TEXT NOT NULL,
  finalized_at TEXT NOT NULL, created_at TEXT NOT NULL, item_count INTEGER NOT NULL);
CREATE TABLE items (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, run_kind TEXT NOT NULL, fetch_day TEXT NOT NULL,
  published_at TEXT NOT NULL, published_ts REAL NOT NULL, category TEXT NOT NULL,
  importance REAL NOT NULL, source_name TEXT NOT NULL, title TEXT NOT NULL,
  title_zh TEXT NOT NULL, summary TEXT NOT NULL, url TEXT NOT NULL,
  related_count INTEGER NOT NULL, tags TEXT NOT NULL, flags TEXT NOT NULL,
  missing INTEGER NOT NULL, doc TEXT NOT NULL, haystack TEXT NOT NULL, title_hay TEXT NOT NULL);
CREATE TABLE item_tags (id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (id, tag));
"""
_ITEM_COLUMNS = (
    "id",
    "run_id",
    "run_kind",
    "fetch_day",
    "published_at",
    "published_ts",
    "category",
    "importance",
    "source_name",
    "title",
    "title_zh",
    "summary",
    "url",
    "related_count",
    "tags",
    "flags",
    "missing",
    "doc",
    "haystack",
    "title_hay",
)
_INSERT_ITEM = (
    f"INSERT INTO items ({', '.join(_ITEM_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _ITEM_COLUMNS)})"
)
_FROM = "FROM items i LEFT JOIN userdb.item_state s ON s.id = i.id"
_VIEW_WHERE = {
    "latest": "s.hidden_at IS NULL",
    "unread": "s.hidden_at IS NULL AND s.read_at IS NULL",
    "starred": "s.starred_at IS NOT NULL",
    "notes": "s.note <> ''",
    "hidden": "s.hidden_at IS NOT NULL",
    "collection": "1",
}
_DAY_ORDER = "i.fetch_day DESC, i.importance DESC, i.published_ts DESC, i.id"
_VIEW_ORDER = {
    "latest": _DAY_ORDER,
    "unread": _DAY_ORDER,
    "starred": "s.starred_at DESC, i.id",
    "notes": "s.note_updated_at DESC, i.id",
    "hidden": "s.hidden_at DESC, i.id",
    "collection": "ci.added_at DESC, i.id",
}
_LIST_COLUMNS = (
    "i.id, i.title_zh, i.title, i.summary, i.category, i.importance, i.source_name, "
    "i.published_at, i.fetch_day, i.run_id, i.run_kind, i.tags, i.url, i.related_count, "
    "i.flags, i.missing, s.starred_at, s.read_at, s.hidden_at, s.note"
)
_COLLECTIONS = (
    "SELECT c.cid, c.name, c.description, c.created_at, COUNT(i.id) AS count "
    "FROM userdb.collections c "
    "LEFT JOIN userdb.collection_items ci ON ci.cid = c.cid "
    "LEFT JOIN items i ON i.id = ci.id "
)


@dataclass(frozen=True)
class Query:
    """一次列表请求：一个视图、可选的过滤条件和搜索、一页（`limit` 由 api.py 设定）。"""

    view: str = "latest"
    cid: int | None = None
    category: str = ""
    tag: str = ""
    source: str = ""
    run: str = ""
    q: str = ""
    offset: int = 0
    limit: int = 50


class Library:
    def __init__(
        self, pool: Path, *, refresh_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.pool = pool
        self._refresh_s = refresh_s
        self._clock = clock
        self._lock = threading.RLock()
        self._conn = userdb.connect(pool / VIEWER_DIR / userdb.DB_FILE)
        # SQLite 的 lower() 只转换 ASCII；搜索时两边都用 Python 的转小写。
        self._conn.create_function("pylower", 1, _lower, deterministic=True)
        self._conn.executescript(_SCHEMA)
        self._indexed: set[str] = set()
        self._looked: dict[str, float] = {}  # run_id -> 上次见它未 finalize 时 run.json 的 mtime
        self._last_refresh: float | None = None
        self.refresh(force=True)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- 读取 ------------------------------------------------------------------------------

    def refresh(self, *, force: bool = False) -> None:
        """把自上次查看以来新 finalize 的运行加入索引（最多每 refresh_s 秒一次）。"""
        with self._lock:
            now = self._clock()
            last = self._last_refresh
            if not force and last is not None and now - last < self._refresh_s:
                return
            self._last_refresh = now
            for run_dir in poolread.run_dirs(self.pool):
                run_id = run_dir.name
                if run_id in self._indexed:
                    continue
                mtime = poolread.run_mtime(run_dir)
                if mtime is None or self._looked.get(run_id) == mtime:
                    continue
                run = poolread.read_finalized_run(run_dir)
                if run is None:
                    self._looked[run_id] = mtime
                    continue
                self._add_run(run)
                self._indexed.add(run_id)

    def list_items(self, query: Query) -> dict[str, Any]:
        self.refresh()
        with self._lock:
            joins, where, params = self._where(query)
            total = self._count(query)
            order = _VIEW_ORDER[query.view]
            terms = _terms(query.q)
            if terms:
                title_hit = " AND ".join("instr(i.title_hay, ?) > 0" for _ in terms)
                order = f"CASE WHEN {title_hit} THEN 0 ELSE 1 END, {order}"
            rows = self._conn.execute(
                f"SELECT {_LIST_COLUMNS} {_FROM}{joins} WHERE {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, *terms, query.limit, query.offset],
            ).fetchall()
        return {"items": [_list_row(r) for r in rows], "total": total, "offset": query.offset}

    def item(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc, missing FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFound(f"no item {item_id}")
            return {
                "item": json.loads(row["doc"]),
                "missing": bool(row["missing"]),
                "state": userdb.get_state(self._conn, item_id),
                "cids": userdb.item_collections(self._conn, item_id),
            }

    def meta(self) -> dict[str, Any]:
        self.refresh()
        with self._lock:
            runs = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT run_id, kind, focus, finalized_at, created_at, item_count "
                    "FROM runs ORDER BY run_id DESC"
                )
            ]
            collections = [
                dict(r) for r in self._conn.execute(_COLLECTIONS + "GROUP BY c.cid ORDER BY c.name")
            ]
            return {
                "runs": runs,
                "categories": self._counts_by("i.category"),
                "sources": self._counts_by("i.source_name"),
                "collections": collections,
                "counts": {view: self._count(Query(view=view)) for view in COUNTED_VIEWS},
            }

    # --- 用户标记 --------------------------------------------------------------------------

    def set_state(
        self,
        item_id: str,
        *,
        starred: bool | None = None,
        read: bool | None = None,
        hidden: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_item(item_id)
            return userdb.set_flags(
                self._conn,
                item_id,
                starred=starred,
                read=read,
                hidden=hidden,
                now=userdb.now_iso(),
            )

    def set_note(self, item_id: str, note: str) -> dict[str, Any]:
        with self._lock:
            self._require_item(item_id)
            return userdb.set_note(self._conn, item_id, note, now=userdb.now_iso())

    def mark_read(self, *, ids: Iterable[str] = (), fetch_day: str = "") -> int:
        """把某个抓取日的可见条目、或给定的 id 标为已读；返回改变了多少条。"""
        with self._lock:
            if fetch_day:
                targets = [
                    str(r[0])
                    for r in self._conn.execute(
                        f"SELECT i.id {_FROM} WHERE i.fetch_day = ? AND s.hidden_at IS NULL",
                        (fetch_day,),
                    )
                ]
            else:
                targets = [i for i in dict.fromkeys(ids) if self._has(i)]
            return userdb.mark_read(self._conn, targets, now=userdb.now_iso())

    def create_collection(self, name: str, description: str = "") -> dict[str, Any]:
        with self._lock:
            cid = userdb.create_collection(self._conn, name, description, now=userdb.now_iso())
            return self._collection(cid)

    def update_collection(
        self, cid: int, *, name: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            userdb.update_collection(self._conn, cid, name=name, description=description)
            return self._collection(cid)

    def delete_collection(self, cid: int) -> None:
        with self._lock:
            userdb.delete_collection(self._conn, cid)

    def collect(self, cid: int, item_id: str) -> None:
        with self._lock:
            self._require_item(item_id)
            userdb.add_to_collection(self._conn, cid, item_id, now=userdb.now_iso())

    def uncollect(self, cid: int, item_id: str) -> None:
        # 不检查条目：已经不在索引里的 id 也能从收藏夹移除。
        with self._lock:
            userdb.remove_from_collection(self._conn, cid, item_id)

    # --- 内部方法，调用方持有 lock ---------------------------------------------------------

    def _add_run(self, run: poolread.Run) -> None:
        rows: list[tuple[Any, ...]] = []
        tags: list[tuple[str, str]] = []
        added: set[str] = set()
        for entry in run.entries:
            item_id = str(entry["id"])
            if item_id in added or self._has(item_id):
                continue  # 更早的运行已索引过的 id 优先
            added.add(item_id)
            doc = poolread.load_item(self.pool, entry)
            missing = doc is None
            if doc is None:
                doc = _doc_from_entry(run, entry)
            row = _item_row(run, entry, doc, missing)
            rows.append(tuple(row[column] for column in _ITEM_COLUMNS))
            tags.extend((item_id, tag) for tag in _strings(doc.get("tags")))
        with self._conn:
            self._conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                (run.run_id, run.kind, run.focus, run.finalized_at, run.created_at, len(rows)),
            )
            self._conn.executemany(_INSERT_ITEM, rows)
            self._conn.executemany("INSERT OR IGNORE INTO item_tags VALUES (?, ?)", tags)

    def _where(self, query: Query) -> tuple[str, str, list[Any]]:
        """额外的 join、WHERE 子句，以及按出现顺序排列的参数。"""
        if query.view not in _VIEW_WHERE:
            raise ApiError(f"view must be one of: {', '.join(VIEWS)}")
        joins = ""
        params: list[Any] = []
        if query.view == "collection":
            if query.cid is None:
                raise ApiError("view=collection needs cid")
            userdb.require_collection(self._conn, query.cid)
            joins = " JOIN userdb.collection_items ci ON ci.id = i.id AND ci.cid = ?"
            params.append(query.cid)
        clauses = [_VIEW_WHERE[query.view]]
        for column, value in (
            ("i.category", query.category),
            ("i.source_name", query.source),
            ("i.run_id", query.run),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if query.tag:
            clauses.append("EXISTS (SELECT 1 FROM item_tags t WHERE t.id = i.id AND t.tag = ?)")
            params.append(query.tag)
        for term in _terms(query.q):
            clauses.append("(instr(i.haystack, ?) > 0 OR instr(pylower(s.note), ?) > 0)")
            params.extend((term, term))
        return joins, " AND ".join(clauses), params

    def _count(self, query: Query) -> int:
        joins, where, params = self._where(query)
        sql = f"SELECT COUNT(*) {_FROM}{joins} WHERE {where}"
        return int(self._conn.execute(sql, params).fetchone()[0])

    def _counts_by(self, column: str) -> list[dict[str, Any]]:
        """`column` 每个取值下的可见（未隐藏）条目数，多的在前。"""
        sql = (
            f"SELECT {column} AS name, COUNT(*) AS count {_FROM} WHERE s.hidden_at IS NULL "
            f"GROUP BY {column} ORDER BY count DESC, name"
        )
        return [dict(r) for r in self._conn.execute(sql)]

    def _collection(self, cid: int) -> dict[str, Any]:
        row = self._conn.execute(_COLLECTIONS + "WHERE c.cid = ? GROUP BY c.cid", (cid,)).fetchone()
        if row is None:
            raise NotFound(f"no collection {cid}")
        return dict(row)

    def _has(self, item_id: str) -> bool:
        found = self._conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
        return found is not None

    def _require_item(self, item_id: str) -> None:
        if not self._has(item_id):
            raise NotFound(f"no item {item_id}")


def _doc_from_entry(run: poolread.Run, entry: dict[str, Any]) -> dict[str, Any]:
    """条目文件缺失时，manifest 对该条目所知的内容（见 schema.md 的 manifest 一节）。"""
    title_zh = _text(entry.get("title_zh"))
    return {
        "id": entry["id"],
        "run_id": run.run_id,
        "run_kind": run.kind,
        "title": title_zh,
        "title_zh": title_zh,
        "summary": _text(entry.get("summary")),
        "category": _text(entry.get("category")),
        "metrics": {"importance": _number(entry.get("importance"))},
        "source": {"name": _text(entry.get("source_name")), "url": _text(entry.get("url"))},
        "published_at": _text(entry.get("published_at")),
        "collected_at": run.created_at,
        "tags": [],
        "related": [],
    }


def _item_row(
    run: poolread.Run, entry: dict[str, Any], doc: dict[str, Any], missing: bool
) -> dict[str, Any]:
    source = _mapping(doc.get("source"))
    flags = _mapping(doc.get("flags"))
    title_zh = _text(doc.get("title_zh"))
    title = _text(doc.get("title")) or title_zh
    published_at = _text(doc.get("published_at"))
    related = _list(doc.get("related"))
    return {
        "id": entry["id"],
        "run_id": run.run_id,
        "run_kind": run.kind,
        "fetch_day": poolread.day_of(_text(doc.get("collected_at")) or run.created_at),
        "published_at": published_at,
        "published_ts": poolread.timestamp_of(published_at),
        "category": _text(doc.get("category")),
        "importance": _number(_mapping(doc.get("metrics")).get("importance")),
        "source_name": _text(source.get("name")),
        "title": title,
        "title_zh": title_zh,
        "summary": _text(doc.get("summary")),
        "url": _text(source.get("url")),
        # 文件缺失时没有 related 列表，但 manifest 里仍记着它的数量。
        "related_count": int(_number(entry.get("related_count"))) if missing else len(related),
        "tags": json.dumps(_strings(doc.get("tags")), ensure_ascii=False),
        "flags": json.dumps({key: bool(flags.get(key)) for key in FLAG_KEYS}),
        "missing": int(missing),
        "doc": json.dumps(doc, ensure_ascii=False),
        "haystack": _haystack(doc),
        "title_hay": _lower(f"{title}\n{title_zh}"),
    }


def _haystack(doc: dict[str, Any]) -> str:
    """搜索查看的全部内容，转成小写：标题、summary、synopsis、key_points、why_it_matters、
    标签、entities、来源名、相关报道的标题。"""
    parts = [_text(doc.get(key)) for key in ("title", "title_zh", "summary", "synopsis")]
    parts.append(_text(doc.get("why_it_matters")))
    parts.extend(_strings(doc.get("key_points")))
    parts.extend(_strings(doc.get("tags")))
    for names in _mapping(doc.get("entities")).values():
        parts.extend(_strings(names))
    parts.append(_text(_mapping(doc.get("source")).get("name")))
    parts.extend(_text(_mapping(r).get("title")) for r in _list(doc.get("related")))
    return _lower("\n".join(p for p in parts if p))


def _list_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title_zh": row["title_zh"],
        "title": row["title"],
        "summary": row["summary"],
        "category": row["category"],
        "importance": row["importance"],
        "source_name": row["source_name"],
        "published_at": row["published_at"],
        "fetch_day": row["fetch_day"],
        "run_id": row["run_id"],
        "run_kind": row["run_kind"],
        "tags": json.loads(row["tags"]),
        "url": row["url"],
        "related_count": row["related_count"],
        "flags": json.loads(row["flags"]),
        "missing": bool(row["missing"]),
        "starred": row["starred_at"] is not None,
        "read": row["read_at"] is not None,
        "hidden": row["hidden_at"] is not None,
        "has_note": bool(row["note"]),
    }


def _terms(q: str) -> list[str]:
    return _lower(q).split()


def _lower(value: object) -> str:
    return value.lower() if isinstance(value, str) else ""


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [v for v in _list(value) if isinstance(v, str)]
