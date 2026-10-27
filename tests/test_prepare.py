from __future__ import annotations

from pathlib import Path

import pytest
from helpers import (
    SAMPLE,
    SAMPLE_NOW,
    id_for,
    pin_clock,
    prepared_run,
    read_json_file,
    set_fetched,
    started_run,
    write_candidates,
)

from newsdigest import cli
from newsdigest.pool import load_run, save_run


def test_sample_counts_tiers_and_triage_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = prepared_run(tmp_path / "p", monkeypatch)
    run = load_run(run_dir)
    assert run["stage"] == "prepared"
    s = run["stats"]
    assert (s["candidates"], s["new"], s["duplicate"], s["out_of_window"], s["no_time"]) == (
        8,
        5,
        1,
        1,
        1,
    )
    tri = read_json_file(run_dir / "triage_input.json")
    assert tri["kind"] == "daily" and tri["min_importance"] == 0.35
    assert tri["criterion"].startswith("AI 大模型")
    assert tri["categories"][0]["name"] == "AI"
    items = tri["items"]
    times = [i["published_at"] for i in items]
    assert times == sorted(times, reverse=True)
    by_id = {i["id"]: i for i in items}
    reuters = by_id[id_for(run_dir, "reuters.com")]
    assert (reuters["tier"], reuters["lang"]) == (1, "zh")
    techcrunch = by_id[id_for(run_dir, "techcrunch.com")]
    assert (techcrunch["tier"], techcrunch["lang"], techcrunch["source"]) == (2, "en", "TechCrunch")
    assert all(len(i["snippet"]) <= 120 for i in items)
    assert not any(i["related_only"] for i in items)  # 都有正文，都能当 primary


def test_title_duplicates_keep_the_more_authoritative_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir,
        "manual",
        [
            {
                "url": "https://blog.example.com/copy",
                "title": "英伟达发布新 GPU",
                "published_at": "2026-10-20T08:00:00+08:00",
                "snippet": "正文",
                "source": "Some Blog",
            },
            {
                "url": "https://www.reuters.com/nvidia",
                "title": "英伟达发布新GPU！",
                "published_at": "2026-10-20T09:00:00+08:00",
                "snippet": "正文",
                "source": "Reuters",
            },
        ],
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert [r["source_name"] for r in read_json_file(run_dir / "records.json")] == ["Reuters"]


def test_cross_run_dedup_daily_skips_all_adhoc_skips_only_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = tmp_path / "p"
    first = prepared_run(pool, monkeypatch)
    reuters, sports = id_for(first, "reuters.com"), id_for(first, "sports.example.com")
    run = load_run(first)
    run["status"] = "finalized"
    save_run(first, run)
    (first / "seen.txt").write_text(f"{reuters} kept\n{sports} dropped\n", encoding="utf-8")

    daily = prepared_run(pool, monkeypatch)
    daily_ids = {i["id"] for i in read_json_file(daily / "triage_input.json")["items"]}
    assert reuters not in daily_ids and sports not in daily_ids

    adhoc = prepared_run(pool, monkeypatch, "--query", "体育")
    adhoc_ids = {i["id"] for i in read_json_file(adhoc / "triage_input.json")["items"]}
    assert reuters not in adhoc_ids and sports in adhoc_ids


def test_source_window_applies_and_links_are_exempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "qbitai", "--hours", "6")  # 从 10-20 18:00 开始
    write_candidates(
        run_dir,
        "qbitai",
        [
            {
                "url": "https://www.qbitai.com/a",
                "title": "窗口内",
                "published_at": "2026-10-20T20:00:00+08:00",
                "snippet": "正文",
            },
            {
                "url": "https://www.qbitai.com/b",
                "title": "窗口外",
                "published_at": "2026-10-20T10:00:00+08:00",
                "snippet": "正文",
            },
        ],
    )
    write_candidates(
        run_dir,
        "links",
        [
            {
                "url": "https://mp.weixin.qq.com/s/old",
                "title": "用户投递的旧文",
                "published_at": "2026-10-01T10:00:00+08:00",
                "snippet": "正文",
                "source": "某公众号",
            },
        ],
    )
    set_fetched(
        run_dir,
        {"qbitai": {"ok": True, "fetched": 2, "error": "", "oldest": "2026-10-20T10:00:00+08:00"}},
    )
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    titles = {i["title"] for i in read_json_file(run_dir / "triage_input.json")["items"]}
    assert titles == {"窗口内", "用户投递的旧文"}
    assert load_run(run_dir)["warnings"] == []


def test_feed_that_only_reaches_back_part_of_the_window_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "qbitai", "--hours", "6")
    write_candidates(
        run_dir,
        "qbitai",
        [
            {
                "url": "https://www.qbitai.com/a",
                "title": "最新",
                "published_at": "2026-10-20T20:00:00+08:00",
                "snippet": "正文",
            },
        ],
    )
    set_fetched(
        run_dir,
        {"qbitai": {"ok": True, "fetched": 1, "error": "", "oldest": "2026-10-20T20:00:00+08:00"}},
    )
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    warnings = load_run(run_dir)["warnings"]
    assert len(warnings) == 1 and warnings[0].startswith("qbitai:")


def test_feed_that_filled_per_source_limit_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "qbitai", "--hours", "6")
    write_candidates(
        run_dir,
        "qbitai",
        [
            {
                "url": "https://www.qbitai.com/a",
                "title": "最新",
                "published_at": "2026-10-20T20:00:00+08:00",
                "snippet": "正文",
            },
        ],
    )
    run = load_run(run_dir)
    run["settings"]["per_source_limit"] = 1  # 截断来自 profile 有意设的上限，不是订阅源
    save_run(run_dir, run)
    set_fetched(
        run_dir,
        {"qbitai": {"ok": True, "fetched": 1, "error": "", "oldest": "2026-10-20T20:00:00+08:00"}},
    )
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert load_run(run_dir)["warnings"] == []


def test_rows_without_text_are_dropped_except_from_search_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "gnews", "--hours", "48")
    when = "2026-10-20T10:00:00+08:00"
    gnews_url = "https://news.google.com/rss/articles/a"
    write_candidates(
        run_dir, "gnews", [{"url": gnews_url, "title": "只有标题", "published_at": when}]
    )
    write_candidates(
        run_dir,
        "manual",
        [{"url": "https://a.example.com/x", "title": "手动找到的", "published_at": when}],
    )
    set_fetched(run_dir, {"gnews": {"ok": True, "fetched": 1, "error": "", "oldest": when}})
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert [r["source_id"] for r in read_json_file(run_dir / "records.json")] == ["gnews"]
    assert load_run(run_dir)["stats"]["no_text"] == 1
    # 只有标题的 Google News 条目交给 triage，但标明它只能当同一事件的其他报道
    items = read_json_file(run_dir / "triage_input.json")["items"]
    assert [i["related_only"] for i in items] == [True]


def test_cap_keeps_the_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(run_dir, "manual", SAMPLE.read_text(encoding="utf-8"))
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    run = load_run(run_dir)
    run["settings"]["max_candidates"] = 2
    save_run(run_dir, run)
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    urls = [r["url"] for r in read_json_file(run_dir / "records.json")]
    assert len(urls) == 2 and "bloomberg.com" in urls[0] and "sports.example.com" in urls[1]
    assert load_run(run_dir)["stats"]["over_cap"] == 3


def test_no_new_candidates_finalizes_an_empty_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "1")
    write_candidates(run_dir, "manual", SAMPLE.read_text(encoding="utf-8"))
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert load_run(run_dir)["status"] == "finalized"
    assert read_json_file(run_dir / "manifest.json")["items"] == []
    assert (run_dir / "seen.txt").read_text(encoding="utf-8") == ""
    out = capsys.readouterr().out
    assert "no new candidates" in out
    assert out.splitlines()[-2:] == [f"[nd] run: {run_dir}", "[nd] next: open the viewer: nv.py up"]


def test_prepare_before_fetch_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none")
    assert cli.main(["prepare", "--run", str(run_dir)]) == 1
    assert "fetch" in capsys.readouterr().err


def test_broken_manual_line_exits_3_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    good = SAMPLE.read_text(encoding="utf-8").splitlines()[0]
    write_candidates(run_dir, "manual", good + '\n{"url": "https://a.example.com/x", "title": \n')
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 3
    assert "manual.jsonl:2:" in capsys.readouterr().err
    assert load_run(run_dir)["stage"] == "fetched"
    assert load_run(run_dir)["status"] == "started"
    assert not (run_dir / "records.json").exists()


def test_manual_file_with_pretty_printed_json_is_not_silently_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir, "manual", '{\n  "url": "https://a.example.com/x",\n  "title": "t"\n}\n'
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 3
    assert load_run(run_dir)["status"] == "started"


def test_manual_file_tolerates_a_bom_and_a_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    body = SAMPLE.read_text(encoding="utf-8")
    write_candidates(run_dir, "manual", "\ufeff```json\n" + body + "```\n")
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert load_run(run_dir)["stats"]["candidates"] == 8


def test_bom_in_an_adapter_candidate_file_is_stripped_and_unreadable_lines_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    row = (
        '{"url": "https://a.example.com/x", "title": "某新闻", '
        '"published_at": "2026-10-20T10:00:00+08:00", "snippet": "正文"}'
    )
    write_candidates(run_dir, "qbitai", "\ufeff" + row + "\nnot json\n")
    set_fetched(run_dir, {})
    capsys.readouterr()
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert load_run(run_dir)["stats"]["new"] == 1
    assert "warning" in out and "qbitai.jsonl" in out and "1 unreadable" in out


def test_candidates_over_the_cap_leave_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(run_dir, "manual", SAMPLE.read_text(encoding="utf-8"))
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    run = load_run(run_dir)
    run["settings"]["max_candidates"] = 2
    save_run(run_dir, run)
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    warnings = load_run(run_dir)["warnings"]
    assert len(warnings) == 1 and "3 candidates over max_candidates" in warnings[0]


def test_qualifier_suffix_title_is_a_duplicate_within_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir,
        "manual",
        [
            {
                "url": "https://blog.example.com/short",
                "title": "英伟达发布新一代数据中心 GPU",
                "published_at": "2026-10-20T08:00:00+08:00",
                "snippet": "正文",
                "source": "Some Blog",
            },
            {
                "url": "https://www.reuters.com/long",
                "title": "英伟达发布新一代数据中心 GPU，功耗降低 30%",
                "published_at": "2026-10-20T09:00:00+08:00",
                "snippet": "正文",
                "source": "Reuters",
            },
        ],
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert [r["source_name"] for r in read_json_file(run_dir / "records.json")] == ["Reuters"]
    assert load_run(run_dir)["stats"]["duplicate"] == 1


def test_qualifier_prefix_title_is_also_a_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir,
        "manual",
        [
            {
                "url": "https://www.reuters.com/plain",
                "title": "苹果发布M5芯片",
                "published_at": "2026-10-20T08:00:00+08:00",
                "snippet": "正文",
                "source": "Reuters",
            },
            {
                "url": "https://blog.example.com/flash",
                "title": "快讯：苹果发布M5芯片",
                "published_at": "2026-10-20T09:00:00+08:00",
                "snippet": "正文",
                "source": "Some Blog",
            },
        ],
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    assert [r["source_name"] for r in read_json_file(run_dir / "records.json")] == ["Reuters"]
    assert load_run(run_dir)["stats"]["duplicate"] == 1


def test_single_token_differences_stay_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir,
        "manual",
        [
            {
                "url": "https://a.example.com/m5",
                "title": "苹果发布M5芯片",
                "published_at": "2026-10-20T08:00:00+08:00",
                "snippet": "正文",
            },
            {
                "url": "https://b.example.com/m6",
                "title": "苹果发布M6芯片",
                "published_at": "2026-10-20T08:30:00+08:00",
                "snippet": "正文",
            },
            {
                "url": "https://c.example.com/m5pro",
                "title": "苹果发布M5 Pro芯片",
                "published_at": "2026-10-20T09:00:00+08:00",
                "snippet": "正文",
            },
        ],
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    titles = sorted(r["title"] for r in read_json_file(run_dir / "records.json"))
    assert titles == ["苹果发布M5 Pro芯片", "苹果发布M5芯片", "苹果发布M6芯片"]
    assert load_run(run_dir)["stats"]["duplicate"] == 0


def test_short_titles_dedup_only_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir,
        "manual",
        [
            {
                "url": "https://a.example.com/1",
                "title": "声明",
                "published_at": "2026-10-20T08:00:00+08:00",
                "snippet": "正文",
            },
            {
                "url": "https://b.example.com/2",
                "title": "某公司发布重要声明",
                "published_at": "2026-10-20T09:00:00+08:00",
                "snippet": "正文",
            },
            {
                "url": "https://c.example.com/3",
                "title": "声明",
                "published_at": "2026-10-20T10:00:00+08:00",
                "snippet": "正文",
            },
        ],
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    titles = sorted(r["title"] for r in read_json_file(run_dir / "records.json"))
    assert titles == ["声明", "某公司发布重要声明"]
    assert load_run(run_dir)["stats"]["duplicate"] == 1


def test_title_dup_min_tokens_is_tunable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "none", "--hours", "48")
    write_candidates(
        run_dir,
        "manual",
        [
            {
                "url": "https://a.example.com/1",
                "title": "声明",
                "published_at": "2026-10-20T08:00:00+08:00",
                "snippet": "正文",
            },
            {
                "url": "https://b.example.com/2",
                "title": "某公司发布重要声明",
                "published_at": "2026-10-20T09:00:00+08:00",
                "snippet": "正文",
            },
        ],
    )
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    run = load_run(run_dir)
    run["settings"]["title_dup_min_tokens"] = 2
    save_run(run_dir, run)
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    # 两条都是 tier 3，所以较早的候选（声明）留下，较长的标题算作重复。
    assert [r["title"] for r in read_json_file(run_dir / "records.json")] == ["声明"]
    assert load_run(run_dir)["stats"]["duplicate"] == 1
