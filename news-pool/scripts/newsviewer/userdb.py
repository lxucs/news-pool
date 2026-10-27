"""阅读器自己的数据，存在 <pool>/viewer/viewer.db：每个条目的状态、笔记、收藏夹。

它以 schema `userdb` 的名义 attach 到索引的内存连接上（index.py），所以一条查询就能把条目和
用户标记 join 起来。键是条目 id，永久稳定（schema.md）。用默认的 rollback journal 而不是 WAL：
新闻池可能放在同步文件夹里，WAL 的附属文件在那里会出问题；而且写入方只有一个。nd.py
从不读写这个数据库。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ApiError, Conflict, NotFound

DB_FILE = "viewer.db"
SCHEMA = "userdb"

# (version, statements)。只能追加：版本为 N 的数据库会把之后的每一项各执行一次。
MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            "CREATE TABLE userdb.item_state ("
            " id TEXT PRIMARY KEY,"
            " starred_at TEXT, read_at TEXT, hidden_at TEXT,"
            " note TEXT NOT NULL DEFAULT '', note_updated_at TEXT)",
            "CREATE TABLE userdb.collections ("
            " cid INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,"
            " description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)",
            "CREATE TABLE userdb.collection_items ("
            " cid INTEGER NOT NULL REFERENCES collections(cid) ON DELETE CASCADE,"
            " id TEXT NOT NULL, added_at TEXT NOT NULL, PRIMARY KEY (cid, id))",
        ),
    ),
)

STATE_COLUMNS = ("starred_at", "read_at", "hidden_at", "note", "note_updated_at")
_EMPTY_STATE: dict[str, Any] = {
    "starred_at": None,
    "read_at": None,
    "hidden_at": None,
    "note": "",
    "note_updated_at": None,
}


def connect(path: Path) -> sqlite3.Connection:
    """一个内存连接（条目索引就在里面），并 attach 了 viewer.db。

    check_same_thread=False：服务在多个 thread 上应答；index.py 用同一个 lock 把对这个连接的
    每次使用串行化。"""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    attach(conn, path)
    return conn


def attach(conn: sqlite3.Connection, path: Path) -> None:
    """把 viewer.db（不存在就创建）attach 为 `userdb`，并把它向前迁移到最新版本。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(f"ATTACH DATABASE ? AS {SCHEMA}", (str(path),))
    version = int(conn.execute(f"PRAGMA {SCHEMA}.user_version").fetchone()[0])
    for target, statements in MIGRATIONS:
        if version >= target:
            continue
        conn.execute("BEGIN")  # DDL 不会自己开启事务
        with conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA {SCHEMA}.user_version = {target}")
        version = target


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_state(conn: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {', '.join(STATE_COLUMNS)} FROM userdb.item_state WHERE id = ?", (item_id,)
    ).fetchone()
    return dict(_EMPTY_STATE) if row is None else dict(zip(STATE_COLUMNS, row))


def set_flags(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    starred: bool | None = None,
    read: bool | None = None,
    hidden: bool | None = None,
    now: str,
) -> dict[str, Any]:
    """设置（True）或清除（False）标记。设置时保留已有的时间戳，所以重复星标不会改变条目在
    星标视图里的位置。"""
    changes = {"starred_at": starred, "read_at": read, "hidden_at": hidden}
    with conn:
        conn.execute("INSERT OR IGNORE INTO userdb.item_state (id) VALUES (?)", (item_id,))
        for column, value in changes.items():
            if value is None:
                continue
            if value:
                conn.execute(
                    f"UPDATE userdb.item_state SET {column} = COALESCE({column}, ?) WHERE id = ?",
                    (now, item_id),
                )
            else:
                conn.execute(
                    f"UPDATE userdb.item_state SET {column} = NULL WHERE id = ?", (item_id,)
                )
    return get_state(conn, item_id)


def set_note(conn: sqlite3.Connection, item_id: str, note: str, *, now: str) -> dict[str, Any]:
    """按输入原样保存笔记；空白的笔记等于清除。"""
    with conn:
        conn.execute("INSERT OR IGNORE INTO userdb.item_state (id) VALUES (?)", (item_id,))
        if note.strip():
            conn.execute(
                "UPDATE userdb.item_state SET note = ?, note_updated_at = ? WHERE id = ?",
                (note, now, item_id),
            )
        else:
            conn.execute(
                "UPDATE userdb.item_state SET note = '', note_updated_at = NULL WHERE id = ?",
                (item_id,),
            )
    return get_state(conn, item_id)


def mark_read(conn: sqlite3.Connection, ids: list[str], *, now: str) -> int:
    """给 `ids` 中未读的条目写上 read_at；返回改变了多少条。"""
    changed = 0
    with conn:
        for item_id in ids:
            conn.execute("INSERT OR IGNORE INTO userdb.item_state (id) VALUES (?)", (item_id,))
            cursor = conn.execute(
                "UPDATE userdb.item_state SET read_at = ? WHERE id = ? AND read_at IS NULL",
                (now, item_id),
            )
            changed += cursor.rowcount
    return changed


def create_collection(conn: sqlite3.Connection, name: str, description: str, *, now: str) -> int:
    cleaned = _collection_name(name)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO userdb.collections (name, description, created_at) VALUES (?, ?, ?)",
                (cleaned, description, now),
            )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a collection named {cleaned!r} already exists") from exc
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def get_collection(conn: sqlite3.Connection, cid: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT cid, name, description, created_at FROM userdb.collections WHERE cid = ?", (cid,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no collection {cid}")
    return dict(row)


def require_collection(conn: sqlite3.Connection, cid: int) -> None:
    get_collection(conn, cid)


def update_collection(
    conn: sqlite3.Connection, cid: int, *, name: str | None, description: str | None
) -> None:
    require_collection(conn, cid)
    try:
        with conn:
            if name is not None:
                cleaned = _collection_name(name)
                conn.execute("UPDATE userdb.collections SET name = ? WHERE cid = ?", (cleaned, cid))
            if description is not None:
                conn.execute(
                    "UPDATE userdb.collections SET description = ? WHERE cid = ?",
                    (description, cid),
                )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a collection named {name!r} already exists") from exc


def delete_collection(conn: sqlite3.Connection, cid: int) -> None:
    """删除收藏夹，条目保留。collection_items 里的行级联删除（外键已开启）。"""
    require_collection(conn, cid)
    with conn:
        conn.execute("DELETE FROM userdb.collections WHERE cid = ?", (cid,))


def add_to_collection(conn: sqlite3.Connection, cid: int, item_id: str, *, now: str) -> None:
    require_collection(conn, cid)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO userdb.collection_items (cid, id, added_at) VALUES (?, ?, ?)",
            (cid, item_id, now),
        )


def remove_from_collection(conn: sqlite3.Connection, cid: int, item_id: str) -> None:
    require_collection(conn, cid)
    with conn:
        conn.execute("DELETE FROM userdb.collection_items WHERE cid = ? AND id = ?", (cid, item_id))


def item_collections(conn: sqlite3.Connection, item_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT cid FROM userdb.collection_items WHERE id = ? ORDER BY cid", (item_id,)
    )
    return [int(row[0]) for row in rows]


def _collection_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ApiError("a collection needs a name")
    return cleaned
