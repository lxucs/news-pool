from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers import prepared_run, sample_enriched, sample_triage, write_enriched, write_triage
from viewer_helpers import hex_id, item_doc, write_run

from newsdigest import cli as nd_cli
from newsviewer import userdb
from newsviewer.errors import ApiError, NotFound
from newsviewer.index import Library, Query

A1, A2, A3, B1, B2 = (hex_id(n) for n in (0xA1, 0xA2, 0xA3, 0xB1, 0xB2))
DAY1 = "2026-10-21T08:00:00+08:00"
DAY2 = "2026-10-22T08:00:00+08:00"
RUN1, RUN2, RUN3 = "20261021-080000", "20261022-080000", "20261022-120000"


@pytest.fixture
def pool(tmp_path: Path) -> Path:
    root = tmp_path / "pool"
    write_run(
        root,
        RUN1,
        [
            item_doc(A1, "OpenAI 发布新模型", importance=0.9, tags=["大模型"]),
            item_doc(
                A2,
                "台积电 3nm 芯片量产",
                importance=0.4,
                source_name="来源乙",
                category="半导体",
                tags=["芯片"],
            ),
            item_doc(A3, "欧盟发布 AI 法案细则", importance=0.6, category="政策监管"),
        ],
        created_at=DAY1,
    )
    write_run(
        root,
        RUN2,
        [
            item_doc(B1, "英伟达发布新 GPU", importance=0.5, synopsis="功耗降低三成，明年量产。"),
            item_doc(B2, "Anthropic 完成新一轮融资", importance=0.7),
        ],
        created_at=DAY2,
    )
    write_run(root, RUN3, [], status="started", created_at=DAY2)
    return root


@pytest.fixture
def lib(pool: Path) -> Iterator[Library]:
    library = Library(pool, refresh_s=0)
    yield library
    library.close()


def ids(library: Library, **query: Any) -> list[str]:
    return [row["id"] for row in library.list_items(Query(**query))["items"]]


def _fake_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """给标记提供互不相同且递增的时间戳，让视图的排序确定。"""
    ticks = iter(range(60))
    monkeypatch.setattr(userdb, "now_iso", lambda: f"2026-10-22T10:{next(ticks):02d}:00+08:00")


def test_only_finalized_runs_are_indexed(lib: Library) -> None:
    assert [r["run_id"] for r in lib.meta()["runs"]] == [RUN2, RUN1]
    assert lib.list_items(Query())["total"] == 5


def test_latest_orders_by_fetch_day_then_importance(lib: Library) -> None:
    rows = lib.list_items(Query())["items"]
    assert [r["id"] for r in rows] == [B2, B1, A1, A3, A2]
    assert [r["fetch_day"] for r in rows] == ["261022", "261022", "261021", "261021", "261021"]
    assert rows[0]["read"] is False and rows[0]["missing"] is False


def test_item_detail_returns_the_stored_document(lib: Library) -> None:
    detail = lib.item(B1)
    assert detail["item"]["synopsis"] == "功耗降低三成，明年量产。"
    assert detail["missing"] is False and detail["cids"] == []
    assert detail["state"]["read_at"] is None
    with pytest.raises(NotFound):
        lib.item(hex_id(0xFFF))


def test_a_missing_item_file_is_indexed_from_the_manifest(tmp_path: Path) -> None:
    gone = hex_id(0xC1)
    write_run(tmp_path, RUN1, [item_doc(gone, "文件被删的新闻")], skip_files=[gone])
    library = Library(tmp_path, refresh_s=0)
    row = library.list_items(Query())["items"][0]
    assert row["missing"] is True and row["title_zh"] == "文件被删的新闻"
    detail = library.item(gone)
    assert detail["missing"] is True
    assert detail["item"]["summary"] == "文件被删的新闻的摘要"
    library.close()


def test_a_2_0_manifest_finds_items_by_id(tmp_path: Path) -> None:
    old = hex_id(0xC2)
    write_run(tmp_path, RUN1, [item_doc(old, "旧运行")], with_file_field=False)
    library = Library(tmp_path, refresh_s=0)
    detail = library.item(old)
    assert detail["missing"] is False and detail["item"]["synopsis"] == "旧运行的详细说明。"
    library.close()


def test_an_id_already_indexed_from_an_earlier_run_wins(tmp_path: Path) -> None:
    dup = hex_id(0xD1)
    write_run(tmp_path, RUN1, [item_doc(dup, "第一次")], created_at=DAY1)
    write_run(tmp_path, RUN2, [item_doc(dup, "第二次")], created_at=DAY2)
    library = Library(tmp_path, refresh_s=0)
    assert [r["title_zh"] for r in library.list_items(Query())["items"]] == ["第一次"]
    assert [r["item_count"] for r in library.meta()["runs"]] == [0, 1]
    library.close()


def test_refresh_picks_up_a_run_that_finalizes_later(pool: Path) -> None:
    now = [0.0]
    library = Library(pool, refresh_s=5, clock=lambda: now[0])
    assert library.list_items(Query())["total"] == 5
    run_dir = write_run(pool, RUN3, [item_doc(hex_id(0xE1), "稍后完成")], created_at=DAY2)
    run_json = run_dir / "run.json"
    stat = run_json.stat()
    os.utime(run_json, (stat.st_atime, stat.st_mtime + 10))  # 照顾 mtime 精度粗的文件系统
    assert library.list_items(Query())["total"] == 5  # 还在 refresh_s 之内：尚未重新扫描
    now[0] = 6.0
    assert library.list_items(Query())["total"] == 6
    library.close()


def test_views_follow_the_marks(lib: Library) -> None:
    lib.set_state(B1, starred=True)
    lib.set_state(A1, hidden=True)
    lib.set_state(A3, read=True)
    lib.set_note(A2, "值得跟进")
    assert ids(lib, view="latest") == [B2, B1, A3, A2]
    assert ids(lib, view="unread") == [B2, B1, A2]
    assert ids(lib, view="starred") == [B1]
    assert ids(lib, view="notes") == [A2]
    assert ids(lib, view="hidden") == [A1]
    rows = {r["id"]: r for r in lib.list_items(Query())["items"]}
    assert rows[B1]["starred"] and rows[A2]["has_note"] and rows[A3]["read"]


def test_hidden_items_stay_in_starred_and_collections(lib: Library) -> None:
    lib.set_state(A1, starred=True, hidden=True)
    cid = lib.create_collection("跟进")["cid"]
    lib.collect(cid, A1)
    assert A1 not in ids(lib, view="latest")
    assert ids(lib, view="starred") == [A1]
    assert ids(lib, view="collection", cid=cid) == [A1]


def test_starred_and_collection_views_put_the_latest_mark_first(
    lib: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_clock(monkeypatch)
    cid = lib.create_collection("芯片")["cid"]
    lib.collect(cid, A2)
    lib.collect(cid, B1)
    lib.set_state(A3, starred=True)
    lib.set_state(B2, starred=True)
    assert ids(lib, view="collection", cid=cid) == [B1, A2]
    assert ids(lib, view="starred") == [B2, A3]


def test_search_matches_every_term_across_fields_and_notes(lib: Library) -> None:
    assert ids(lib, q="发布") == [B1, A1, A3]
    assert ids(lib, q="发布 gpu") == [B1]  # 每个词都要匹配，不区分大小写
    assert ids(lib, q="芯片") == [A2]
    assert ids(lib, q="不存在的词") == []
    lib.set_note(A3, "下周跟进")
    assert ids(lib, q="跟进") == [A3]


def test_title_matches_rank_before_body_matches(lib: Library) -> None:
    # A2 的标题里有「量产」；B1 只在 synopsis 里有，尽管 B1 更新。
    assert ids(lib, q="量产") == [A2, B1]


def test_filters_narrow_any_view(lib: Library) -> None:
    assert ids(lib, category="半导体") == [A2]
    assert ids(lib, tag="大模型") == [A1]
    assert ids(lib, source="来源乙") == [A2]
    assert ids(lib, run=RUN2) == [B2, B1]


def test_paging_keeps_the_total(lib: Library) -> None:
    page = lib.list_items(Query(offset=2, limit=2))
    assert [r["id"] for r in page["items"]] == [A1, A3]
    assert page["total"] == 5 and page["offset"] == 2


def test_mark_read_by_day_skips_hidden_items(lib: Library) -> None:
    lib.set_state(A1, hidden=True)
    assert lib.mark_read(fetch_day="261021") == 2
    assert lib.item(A1)["state"]["read_at"] is None
    assert ids(lib, view="unread") == [B2, B1]


def test_mark_read_by_ids_ignores_unknown_and_repeated_ids(lib: Library) -> None:
    assert lib.mark_read(ids=[B1, hex_id(0xFFF), B1]) == 1


def test_meta_counts_categories_sources_and_collections(lib: Library) -> None:
    lib.set_state(A1, hidden=True, starred=True)
    cid = lib.create_collection("跟进")["cid"]
    lib.collect(cid, B1)
    meta = lib.meta()
    assert meta["counts"] == {"latest": 4, "unread": 4, "starred": 1, "notes": 0, "hidden": 1}
    assert meta["categories"] == [
        {"name": "AI", "count": 2},
        {"name": "半导体", "count": 1},
        {"name": "政策监管", "count": 1},
    ]
    assert meta["sources"] == [{"name": "来源甲", "count": 3}, {"name": "来源乙", "count": 1}]
    assert [(c["cid"], c["name"], c["count"]) for c in meta["collections"]] == [(cid, "跟进", 1)]


def test_bad_queries_and_unknown_targets(lib: Library) -> None:
    with pytest.raises(ApiError):
        lib.list_items(Query(view="collection"))
    with pytest.raises(NotFound):
        lib.list_items(Query(view="collection", cid=99))
    with pytest.raises(ApiError):
        lib.list_items(Query(view="nope"))
    with pytest.raises(NotFound):
        lib.set_state(hex_id(0xFFF), starred=True)
    with pytest.raises(NotFound):
        lib.collect(lib.create_collection("x")["cid"], hex_id(0xFFF))


def test_marks_survive_a_restart(pool: Path) -> None:
    first = Library(pool, refresh_s=0)
    first.set_state(B1, starred=True)
    first.close()
    second = Library(pool, refresh_s=0)
    assert ids(second, view="starred") == [B1]
    second.close()


def test_the_viewer_reads_a_pool_written_by_news_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约测试：两个 skill 一旦对不上，这里就会失败。"""
    pool = tmp_path / "p"
    run_dir = prepared_run(pool, monkeypatch)
    write_triage(run_dir, sample_triage(run_dir))
    assert nd_cli.main(["check", "--run", str(run_dir)]) == 0
    assert nd_cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    write_enriched(run_dir, sample_enriched(run_dir))
    assert nd_cli.main(["check", "--run", str(run_dir)]) == 0
    assert nd_cli.main(["finalize", "--run", str(run_dir)]) == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    library = Library(pool, refresh_s=0)
    rows = library.list_items(Query())["items"]
    assert [r["id"] for r in rows] == [e["id"] for e in manifest["items"]]
    for entry in manifest["items"]:
        detail = library.item(entry["id"])
        assert detail["missing"] is False
        assert detail["item"]["title_zh"] == entry["title_zh"]
        assert detail["item"]["synopsis"]
    assert library.meta()["runs"][0]["run_id"] == run_dir.name
    library.close()
