from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from helpers import (
    SAMPLE_NOW,
    fixture_bytes,
    fixture_text,
    id_for,
    pin_clock,
    prepared_run,
    read_json_file,
    sample_enriched,
    sample_triage,
    set_fetched,
    started_run,
    write_candidates,
    write_enriched,
    write_triage,
)

from newsdigest import cli, leads
from newsdigest.adapters import parse_article_page
from newsdigest.net import FetchError, Response
from newsdigest.pool import load_run, save_run

CST = timezone(timedelta(hours=8))


@pytest.fixture
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = prepared_run(tmp_path / "p", monkeypatch)
    write_triage(run_dir, sample_triage(run_dir))
    return run_dir


def test_no_fetch_builds_enrich_input_in_importance_order(run_dir: Path) -> None:
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    items = read_json_file(run_dir / "enrich_input.json")["items"]
    assert [i["id"] for i in items] == [
        id_for(run_dir, "reuters.com"),
        id_for(run_dir, "techcrunch.com"),
        id_for(run_dir, "bloomberg.com"),
    ]
    assert items[0]["related_titles"] == ["OpenAI 新一代推理模型发布，API 价格下调六成"]
    assert items[1]["title_zh_required"] is True and items[0]["title_zh_required"] is False
    assert load_run(run_dir)["stage"] == "leads"


def test_leads_refuses_an_invalid_triage(run_dir: Path) -> None:
    write_triage(run_dir, {"events": [], "drop": []})
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 3
    assert not (run_dir / "enrich_input.json").exists()


def test_thin_primaries_get_page_descriptions(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = load_run(run_dir)
    run["settings"]["leads"]["min_snippet_chars"] = 10_000  # 每个 primary 都算素材太少
    run["settings"]["leads"]["max"] = 2  # 只抓取最重要的两条
    save_run(run_dir, run)
    reuters, techcrunch = id_for(run_dir, "reuters.com"), id_for(run_dir, "techcrunch.com")
    calls: list[str] = []

    def http_get(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
        calls.append(url)
        if "reuters.com" in url:
            return Response(url, 200, "", fixture_bytes("article_qbitai.html"))
        raise FetchError("HTTP 403")

    monkeypatch.setattr(leads, "http_get", http_get)
    assert cli.main(["leads", "--run", str(run_dir)]) == 0
    assert len(calls) == 2
    page = parse_article_page(fixture_text("article_qbitai.html"), "https://x.example.com", CST)
    items = {i["id"]: i for i in read_json_file(run_dir / "enrich_input.json")["items"]}
    records = {r["id"]: r for r in read_json_file(run_dir / "records.json")}
    assert items[reuters]["text"] == (page["snippet"] or records[reuters]["snippet"])
    assert items[techcrunch]["text"] == records[techcrunch]["snippet"]


def _gnews_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """一次每日运行，唯一的候选是一条没有正文的 Google News 条目，triage 保留了它。"""
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(tmp_path / "p", "--only", "gnews", "--hours", "48")
    when = "2026-10-20T10:00:00+08:00"
    row = {
        "url": "https://news.google.com/rss/articles/abc",
        "title": "某新闻",
        "published_at": when,
        "source": "某报",
    }
    write_candidates(run_dir, "gnews", [row])
    set_fetched(run_dir, {"gnews": {"ok": True, "fetched": 1, "error": "", "oldest": when}})
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    rid = id_for(run_dir, "news.google.com")
    write_triage(
        run_dir,
        {
            "events": [{"primary": rid, "members": [rid], "category": "AI", "importance": 0.7}],
            "drop": [],
        },
    )
    return run_dir, rid


def test_google_news_links_resolve_to_the_publisher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, rid = _gnews_run(tmp_path, monkeypatch)
    publisher = "https://www.qbitai.com/2026/10/x.html"

    def http_get(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
        return Response(publisher, 200, "", fixture_bytes("article_qbitai.html"))

    monkeypatch.setattr(leads, "http_get", http_get)
    assert cli.main(["leads", "--run", str(run_dir)]) == 0
    assert read_json_file(run_dir / "leads.json")[rid]["resolved_url"] == publisher
    assert [i["id"] for i in read_json_file(run_dir / "enrich_input.json")["items"]] == [rid]


def test_kept_events_still_without_text_are_dropped_without_a_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir, rid = _gnews_run(tmp_path, monkeypatch)

    def http_get(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
        return Response(url, 200, "", b"<html><head><title>Google News</title></head></html>")

    monkeypatch.setattr(leads, "http_get", http_get)  # 停在 Google 的跳转页上
    capsys.readouterr()
    assert cli.main(["leads", "--run", str(run_dir)]) == 0
    out = capsys.readouterr().out
    doc = read_json_file(run_dir / "enrich_input.json")
    assert doc["items"] == [] and doc["no_text"] == [rid]
    assert "1 kept events still have no text" in out and "next: finalize" in out
    assert cli.main(["check", "--run", str(run_dir)]) == 0  # 不要求为它写摘要
    assert "next: finalize" in capsys.readouterr().out
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    assert read_json_file(run_dir / "manifest.json")["items"] == []
    assert (run_dir / "seen.txt").read_text(encoding="utf-8") == f"{rid} dropped\n"


def test_check_walks_through_enrichment(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    capsys.readouterr()
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    assert "next: write enriched-1.jsonl" in capsys.readouterr().out
    write_enriched(run_dir, sample_enriched(run_dir))
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "enriched ok: 3 of 3" in out and "next: finalize" in out


def test_check_notices_triage_changed_after_leads(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    doc = sample_triage(run_dir)
    bloomberg = doc["events"].pop()
    doc["drop"].append(bloomberg["primary"])
    write_triage(run_dir, doc)
    capsys.readouterr()
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    assert "changed after `leads`" in capsys.readouterr().out
