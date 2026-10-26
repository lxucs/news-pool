from __future__ import annotations

import json
from pathlib import Path

import pytest
from viewer_helpers import CREATED, hex_id, item_doc, write_run

from newsviewer import poolread

ID = hex_id(0xA1)
OTHER = hex_id(0xA2)


def _run(run_dir: Path) -> poolread.Run:
    run = poolread.read_finalized_run(run_dir)
    assert run is not None
    return run


def test_only_finalized_runs_are_read(tmp_path: Path) -> None:
    started = write_run(tmp_path, "20261022-080000", [], status="started")
    done = write_run(tmp_path, "20261021-080000", [item_doc(ID, "标题")])
    assert poolread.read_finalized_run(started) is None
    run = _run(done)
    assert run.run_id == "20261021-080000"
    assert run.kind == "daily" and run.created_at == CREATED
    assert [e["id"] for e in run.entries] == [ID]
    assert poolread.run_dirs(tmp_path) == [done, started]  # run ids sort chronologically


def test_items_are_found_by_file_then_by_id(tmp_path: Path) -> None:
    entry = _run(write_run(tmp_path, "20261021-080000", [item_doc(ID, "新格式")])).entries[0]
    assert entry["file"]
    doc = poolread.load_item(tmp_path, entry)
    assert doc is not None and doc["title_zh"] == "新格式"
    old = write_run(tmp_path, "20261020-080000", [item_doc(OTHER, "旧格式")], with_file_field=False)
    entry = _run(old).entries[0]
    assert "file" not in entry
    doc = poolread.load_item(tmp_path, entry)
    assert doc is not None and doc["title_zh"] == "旧格式"


def test_missing_escaping_or_foreign_item_files_give_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run(write_run(tmp_path, "20261021-080000", [item_doc(ID, "缺文件")], skip_files=[ID]))
    entry = run.entries[0]
    assert poolread.load_item(tmp_path, entry) is None
    escaping = {**entry, "file": "../runs/20261021-080000/run.json"}
    assert poolread.load_item(tmp_path, escaping) is None
    assert "outside items/" in capsys.readouterr().out
    (tmp_path / "items").mkdir(exist_ok=True)  # no item file was written for this run
    (tmp_path / "items" / "x.json").write_text(
        json.dumps(item_doc(OTHER, "别的")), encoding="utf-8"
    )
    assert poolread.load_item(tmp_path, {**entry, "file": "x.json"}) is None  # id mismatch


def test_a_broken_manifest_is_skipped_with_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = write_run(tmp_path, "20261021-080000", [item_doc(ID, "x")])
    (run_dir / "manifest.json").write_text("{broken", encoding="utf-8")
    assert poolread.read_finalized_run(run_dir) is None
    assert "manifest.json" in capsys.readouterr().out


def test_entries_without_a_valid_id_are_dropped(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, "20261021-080000", [item_doc(ID, "x")])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["items"].insert(0, {"id": "not-an-id"})
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert [e["id"] for e in _run(run_dir).entries] == [ID]


def test_dates_use_the_timestamps_own_offset() -> None:
    assert poolread.day_of("2026-10-22T13:52:20.206404+08:00") == "261022"
    assert poolread.day_of("2026-10-21T23:30:00-05:00") == "261021"
    assert poolread.day_of("garbage") == ""
    assert poolread.timestamp_of("2026-10-22T00:00:00+08:00") == poolread.timestamp_of(
        "2026-10-21T16:00:00+00:00"
    )
    assert poolread.timestamp_of("") == 0.0
