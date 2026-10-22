from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from helpers import read_json_file, write_run

from newsdigest.errors import UsageError
from newsdigest.pool import (
    Pool,
    build_manifest,
    commit_run,
    compute_windows,
    coverage,
    load_run,
    new_run_id,
    seen_ids,
)
from newsdigest.selection import Source

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 21, 8, 0, tzinfo=CST)
WINDOW_CFG = {"first_run_hours": 24, "overlap_hours": 2, "max_hours": 72}
QBITAI = Source("qbitai", "量子位", "feed", "rss", "https://www.qbitai.com/feed")
HN = Source("hn", "Hacker News 搜索", "search", "hn")


def iso(dt: datetime) -> str:
    return dt.isoformat()


def test_coverage_uses_only_finalized_daily_successful_fetches(tmp_path: Path) -> None:
    t1, t2, t3 = NOW - timedelta(days=2), NOW - timedelta(days=1), NOW
    write_run(
        tmp_path,
        "r1",
        sources={"qbitai": (iso(t1 - timedelta(days=1)), iso(t1)), "hn": (iso(t1), iso(t1))},
        fetch_ok={"qbitai": True, "hn": False},
    )
    write_run(
        tmp_path,
        "r2",
        kind="adhoc",
        sources={"qbitai": (iso(t1), iso(t2))},
        fetch_ok={"qbitai": True},
    )
    write_run(
        tmp_path,
        "r3",
        status="started",
        sources={"qbitai": (iso(t2), iso(t3))},
        fetch_ok={"qbitai": True},
    )
    runs = [run for _, run in Pool(tmp_path).runs()]
    assert coverage(runs) == {"qbitai": t1}


def test_seen_ids_daily_skips_everything_adhoc_only_kept(tmp_path: Path) -> None:
    write_run(tmp_path, "r1", seen="a kept\nb dropped\n")
    write_run(tmp_path, "r2", status="started", seen="c kept\n")
    pool = Pool(tmp_path)
    assert seen_ids(pool, "daily") == {"a", "b"}
    assert seen_ids(pool, "adhoc") == {"a"}


def test_windows_first_run_covered_capped_and_adhoc() -> None:
    cov = {"qbitai": NOW - timedelta(hours=20), "hn": NOW - timedelta(days=5)}
    windows, overall = compute_windows(NOW, [QBITAI, HN], "daily", cov, WINDOW_CFG)
    assert windows["qbitai"].start == NOW - timedelta(hours=22)
    assert windows["hn"].start == NOW - timedelta(hours=72)
    assert overall.start == NOW - timedelta(hours=72) and overall.end == NOW

    windows, _ = compute_windows(NOW, [QBITAI], "daily", {}, WINDOW_CFG)
    assert windows["qbitai"].start == NOW - timedelta(hours=24)

    windows, _ = compute_windows(NOW, [QBITAI], "adhoc", cov, WINDOW_CFG)
    assert windows["qbitai"].start == NOW - timedelta(hours=24)


def test_windows_overrides_and_no_sources() -> None:
    cov = {"qbitai": NOW - timedelta(hours=20)}
    windows, _ = compute_windows(NOW, [QBITAI], "daily", cov, WINDOW_CFG, hours=6)
    assert windows["qbitai"].start == NOW - timedelta(hours=6)
    since = NOW - timedelta(days=3)
    windows, _ = compute_windows(NOW, [QBITAI], "daily", cov, WINDOW_CFG, since=since)
    assert windows["qbitai"].start == since
    _, overall = compute_windows(NOW, [], "daily", cov, WINDOW_CFG)
    assert overall.start == NOW - timedelta(hours=24)
    with pytest.raises(UsageError, match="empty window"):
        compute_windows(NOW, [QBITAI], "daily", cov, WINDOW_CFG, since=NOW)


def test_new_run_id_avoids_collisions(tmp_path: Path) -> None:
    (tmp_path / "20261021-080000").mkdir()
    assert new_run_id(NOW, tmp_path) == "20261021-080000-2"


def _item(item_id: str, importance: float, published: datetime, category: str = "AI") -> dict:
    return {
        "id": item_id,
        "title_zh": item_id,
        "summary": "s",
        "category": category,
        "metrics": {"importance": importance},
        "published_at": iso(published),
        "collected_at": iso(NOW),
        "source": {"name": "量子位", "url": f"https://a.example.com/{item_id}"},
        "related": [{"id": "x"}] if item_id == "b" else [],
        "run_id": "r9",
    }


RUN = {
    "run_id": "r9",
    "kind": "daily",
    "profile": "ai-zh",
    "focus": "",
    "queries": [],
    "window": {"start": "s", "end": "e", "tz": "+08:00"},
    "sources": {"qbitai": {"start": "s", "end": "e"}, "hn": {"start": "s", "end": "e"}},
    "fetch": {"qbitai": {"ok": True, "fetched": 3}},
    "warnings": ["w"],
    "settings": {"item_slug_max_chars": 40},
}


def test_manifest_orders_by_importance_then_newest() -> None:
    items = [
        _item("a", 0.8, NOW - timedelta(hours=5)),
        _item("b", 0.8, NOW - timedelta(hours=1)),
        _item("c", 0.9, NOW - timedelta(hours=9), category="半导体"),
    ]
    manifest = build_manifest(RUN, items, {"candidates": 10, "new": 5, "events": 4}, iso(NOW))
    assert [(e["id"], e["rank"]) for e in manifest["items"]] == [("c", 1), ("b", 2), ("a", 3)]
    assert manifest["stats"] == {
        "candidates": 10,
        "new": 5,
        "events": 4,
        "items": 3,
        "by_category": {"半导体": 1, "AI": 2},
    }
    assert manifest["items"][1]["related_count"] == 1
    files = {e["id"]: e["file"] for e in manifest["items"]}
    assert files["a"] == "261021/261021.a.a.json"
    assert files["b"] == "261021/261021.b.b.json"
    assert files["c"] == "261021/261020.c.c.json"  # published 9h before NOW: 2026-10-20 23:00
    assert manifest["sources"]["hn"]["ok"] is False
    assert manifest["warnings"] == ["w"]


def test_commit_writes_everything_and_marks_finalized(tmp_path: Path) -> None:
    pool = Pool(tmp_path)
    run_dir = write_run(tmp_path, "r9", status="started")
    run = dict(RUN, status="started", stage="leads")
    items = [_item("a", 0.8, NOW)]
    manifest = build_manifest(run, items, {}, iso(NOW))
    commit_run(pool, run_dir, run, items, manifest, [("a", "kept"), ("z", "dropped")])
    assert (pool.items_dir / "261021" / "261021.a.a.json").is_file()
    assert read_json_file(run_dir / "manifest.json")["items"][0]["file"] == (
        "261021/261021.a.a.json"
    )
    assert (run_dir / "seen.txt").read_text(encoding="utf-8") == "a kept\nz dropped\n"
    saved = load_run(run_dir)
    assert saved["status"] == "finalized" and saved["stage"] == "finalized"


def test_commit_refuses_to_overwrite_another_finalized_runs_item(tmp_path: Path) -> None:
    pool = Pool(tmp_path)
    write_run(tmp_path, "r1")
    existing = pool.items_dir / "261021" / "261021.a.a.json"
    existing.parent.mkdir(parents=True)
    existing.write_text('{"run_id": "r1"}', encoding="utf-8")
    run_dir = write_run(tmp_path, "r9", status="started")
    run = dict(RUN, status="started")
    items = [_item("a", 0.8, NOW)]
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        commit_run(pool, run_dir, run, items, build_manifest(run, items, {}, iso(NOW)), [])
    assert not (run_dir / "manifest.json").exists()


def test_commit_overwrites_orphans_from_unfinalized_runs(tmp_path: Path) -> None:
    pool = Pool(tmp_path)
    write_run(tmp_path, "r1", status="started")
    existing = pool.items_dir / "261021" / "261021.a.a.json"
    existing.parent.mkdir(parents=True)
    existing.write_text('{"run_id": "r1"}', encoding="utf-8")
    run_dir = write_run(tmp_path, "r9", status="started")
    run = dict(RUN, status="started")
    items = [_item("a", 0.8, NOW)]
    commit_run(pool, run_dir, run, items, build_manifest(run, items, {}, iso(NOW)), [])
    assert '"r9"' in existing.read_text(encoding="utf-8")
