from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from newsviewer import userdb
from newsviewer.errors import ApiError, Conflict, NotFound

NOW = "2026-10-22T10:00:00+08:00"
LATER = "2026-10-22T11:00:00+08:00"
ID = "0000000000a1"
OTHER = "0000000000a2"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = userdb.connect(tmp_path / "viewer" / "viewer.db")
    yield connection
    connection.close()


def _version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA userdb.user_version").fetchone()[0])


def test_a_new_database_is_migrated_once(tmp_path: Path) -> None:
    path = tmp_path / "viewer" / "viewer.db"
    latest = userdb.MIGRATIONS[-1][0]
    first = userdb.connect(path)
    assert _version(first) == latest
    first.close()
    second = userdb.connect(path)  # reopening must not run the migrations again
    assert _version(second) == latest
    second.close()


def test_flags_set_clear_and_keep_their_first_timestamp(conn: sqlite3.Connection) -> None:
    assert userdb.get_state(conn, ID) == {
        "starred_at": None,
        "read_at": None,
        "hidden_at": None,
        "note": "",
        "note_updated_at": None,
    }
    assert userdb.set_flags(conn, ID, starred=True, now=NOW)["starred_at"] == NOW
    assert userdb.set_flags(conn, ID, starred=True, now=LATER)["starred_at"] == NOW
    assert userdb.set_flags(conn, ID, starred=False, now=LATER)["starred_at"] is None
    state = userdb.set_flags(conn, ID, read=True, hidden=True, now=LATER)
    assert state["read_at"] == LATER and state["hidden_at"] == LATER


def test_notes_set_and_clear(conn: sqlite3.Connection) -> None:
    state = userdb.set_note(conn, ID, "要跟进\n第二行", now=NOW)
    assert state["note"] == "要跟进\n第二行" and state["note_updated_at"] == NOW
    state = userdb.set_note(conn, ID, "   ", now=LATER)
    assert state["note"] == "" and state["note_updated_at"] is None


def test_mark_read_counts_only_unread_items(conn: sqlite3.Connection) -> None:
    userdb.set_flags(conn, ID, read=True, now=NOW)
    assert userdb.mark_read(conn, [ID, OTHER], now=LATER) == 1
    assert userdb.get_state(conn, ID)["read_at"] == NOW


def test_collections(conn: sqlite3.Connection) -> None:
    cid = userdb.create_collection(conn, " 跟进 ", "", now=NOW)
    assert userdb.get_collection(conn, cid)["name"] == "跟进"
    with pytest.raises(Conflict):
        userdb.create_collection(conn, "跟进", "", now=NOW)
    with pytest.raises(ApiError):
        userdb.create_collection(conn, "  ", "", now=NOW)
    userdb.add_to_collection(conn, cid, ID, now=NOW)
    userdb.add_to_collection(conn, cid, ID, now=LATER)  # idempotent
    assert userdb.item_collections(conn, ID) == [cid]
    other = userdb.create_collection(conn, "芯片", "", now=NOW)
    with pytest.raises(Conflict):
        userdb.update_collection(conn, other, name="跟进", description=None)
    userdb.update_collection(conn, cid, name="待跟进", description="本周")
    assert userdb.get_collection(conn, cid)["description"] == "本周"
    userdb.remove_from_collection(conn, cid, ID)
    assert userdb.item_collections(conn, ID) == []
    userdb.add_to_collection(conn, cid, ID, now=NOW)
    userdb.delete_collection(conn, cid)
    assert userdb.item_collections(conn, ID) == []  # ON DELETE CASCADE
    with pytest.raises(NotFound):
        userdb.delete_collection(conn, cid)
    with pytest.raises(NotFound):
        userdb.add_to_collection(conn, cid, ID, now=NOW)


def test_data_survives_reconnecting(tmp_path: Path) -> None:
    path = tmp_path / "viewer" / "viewer.db"
    first = userdb.connect(path)
    userdb.set_flags(first, ID, starred=True, now=NOW)
    first.close()
    second = userdb.connect(path)
    assert userdb.get_state(second, ID)["starred_at"] == NOW
    second.close()
