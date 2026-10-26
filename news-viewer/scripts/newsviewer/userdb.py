"""The viewer's own data in <pool>/viewer/viewer.db: per-item state, notes, collections.

Attached as schema `userdb` on the index's in-memory connection (index.py), so one query can
join items with the user's marks. Keys are item ids, stable forever (schema.md). The default
rollback journal, not WAL: the pool may sit in a synced folder, where WAL's side files misbehave,
and there is one writer. news-digest never reads or writes this database."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ApiError, Conflict, NotFound

DB_FILE = "viewer.db"
SCHEMA = "userdb"

# (version, statements). Append only: a database at version N runs every later entry once.
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
    """An in-memory connection (the item index lives there) with viewer.db attached.

    check_same_thread=False: the server answers on several threads; index.py serializes every
    use of the connection with one lock."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    attach(conn, path)
    return conn


def attach(conn: sqlite3.Connection, path: Path) -> None:
    """Attach viewer.db (created if absent) as `userdb` and migrate it forward."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(f"ATTACH DATABASE ? AS {SCHEMA}", (str(path),))
    version = int(conn.execute(f"PRAGMA {SCHEMA}.user_version").fetchone()[0])
    for target, statements in MIGRATIONS:
        if version >= target:
            continue
        conn.execute("BEGIN")  # DDL does not open a transaction by itself
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
    """Set (True) or clear (False) flags. Setting keeps an existing timestamp, so starring twice
    does not move an item in the starred view."""
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
    """Store the note as typed; a blank note clears it."""
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
    """Stamp read_at on the unread ones among `ids`; how many changed."""
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
    """The collection goes; its items stay. collection_items rows cascade (foreign keys on)."""
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
