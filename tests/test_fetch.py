from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
from helpers import fixture_bytes, pin_clock, read_json_file, started_run

from newsdigest import cli, fetch
from newsdigest.config import load_settings
from newsdigest.net import FetchError, Response
from newsdigest.paths import EXAMPLE_PROFILE_DIR
from newsdigest.pool import load_run

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 21, 8, 0, tzinfo=CST)
Routes = dict[str, Any]


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_clock(monkeypatch, NOW)


def fake_http(routes: Routes, calls: list[str]) -> Callable[..., Response]:
    """Answer by URL prefix with fixture bytes, or raise the given exception."""

    def http_get(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
        calls.append(url)
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return Response(url, 200, "", payload)
        raise FetchError("HTTP 404")

    return http_get


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fetch_writes_candidates_and_records_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "qbitai,aiera,hn")
    calls: list[str] = []
    routes: Routes = {
        "https://www.qbitai.com/feed": fixture_bytes("rss_qbitai.xml"),
        "https://www.aiera.com.cn/feed": b"<html><body>blocked</body></html>",
        "https://hn.algolia.com/": fixture_bytes("hn_search.json"),
    }
    monkeypatch.setattr(fetch, "http_get", fake_http(routes, calls))
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    run = load_run(run_dir)
    assert run["stage"] == "fetched"
    assert run["fetch"]["qbitai"]["ok"] and run["fetch"]["qbitai"]["fetched"] == 3
    assert run["fetch"]["qbitai"]["oldest"]
    assert run["fetch"]["aiera"]["ok"] is False
    assert "not an RSS/Atom feed" in run["fetch"]["aiera"]["error"]
    assert {r["source"] for r in _rows(run_dir / "candidates" / "qbitai.jsonl")} == {"量子位"}
    assert _rows(run_dir / "candidates" / "aiera.jsonl") == []
    hn_calls = [c for c in calls if "hn.algolia.com" in c]
    assert len(hn_calls) == 3  # one request per profile query: synonyms are not ANDed
    assert all("created_at_i%3E" in c for c in hn_calls)


def test_every_source_failing_exits_4_and_keeps_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "qbitai,hn")
    monkeypatch.setattr(fetch, "http_get", fake_http({}, []))
    assert cli.main(["fetch", "--run", str(run_dir)]) == 4
    run = load_run(run_dir)
    assert run["stage"] == "started"
    assert not any(r["ok"] for r in run["fetch"].values())


def test_partial_search_failure_keeps_rows_but_does_not_count_as_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "hn")
    calls: list[str] = []
    ok = fake_http({"https://hn.algolia.com/": fixture_bytes("hn_search.json")}, calls)

    def flaky(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
        if len(calls) == 1:  # the second query fails
            calls.append(url)
            raise FetchError("HTTP 503")
        return ok(url, http_cfg, user_agent)

    monkeypatch.setattr(fetch, "http_get", flaky)
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    result = load_run(run_dir)["fetch"]["hn"]
    assert result["ok"] is False and "HTTP 503" in result["error"] and result["fetched"] == 3


def test_search_urls_carry_query_and_window() -> None:
    settings = load_settings(EXAMPLE_PROFILE_DIR)
    start = NOW - timedelta(hours=24)
    gnews = fetch.search_url("gnews", "AI 大模型", start, NOW, 50, settings)
    assert gnews.startswith("https://news.google.com/rss/search?")
    assert "when%3A1d" in gnews and "hl=zh-CN" in gnews
    gdelt = fetch.search_url("gdelt", "AI 大模型", start, NOW, 50, settings)
    assert "timespan=24h" in gdelt and "%22AI" in gdelt
    hn = fetch.search_url("hn", "AI", start, NOW, 50, settings)
    assert f"created_at_i%3E{int(start.timestamp())}" in hn


def test_links_become_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "none")
    links = tmp_path / "links.txt"
    links.write_text(
        "# shared from WeChat\nhttps://www.qbitai.com/2026/10/x.html\nhttps://gone.example.com/a\n",
        encoding="utf-8",
    )
    routes: Routes = {"https://www.qbitai.com/": fixture_bytes("article_qbitai.html")}
    monkeypatch.setattr(fetch, "http_get", fake_http(routes, []))
    assert cli.main(["fetch", "--run", str(run_dir), "--links", str(links)]) == 0
    rows = _rows(run_dir / "candidates" / "links.jsonl")
    assert len(rows) == 1 and rows[0]["title"]
    assert load_run(run_dir)["stage"] == "fetched"


def test_link_with_a_visible_date_reaches_triage_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real qbitai capture: its only publish time is the visible date and time spans.
    run_dir = started_run(tmp_path / "p", "--only", "none", "--focus", "收录这些链接")
    links = tmp_path / "links.txt"
    links.write_text("https://www.qbitai.com/2026/10/x.html\n", encoding="utf-8")
    routes: Routes = {"https://www.qbitai.com/": fixture_bytes("article_qbitai.html")}
    monkeypatch.setattr(fetch, "http_get", fake_http(routes, []))
    assert cli.main(["fetch", "--run", str(run_dir), "--links", str(links)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    items = read_json_file(run_dir / "triage_input.json")["items"]
    assert len(items) == 1 and items[0]["published_at"] == "2026-10-21T10:37:39+08:00"
    assert items[0]["title"].startswith("飞书豆包工作AI先锋")


def test_link_without_a_publish_time_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "none")
    links = tmp_path / "links.txt"
    links.write_text("https://www.qbitai.com/2026/10/x.html\n", encoding="utf-8")
    undated = b"<html><head><title>Undated</title></head><body><p>text</p></body></html>"
    routes: Routes = {"https://www.qbitai.com/": undated}
    monkeypatch.setattr(fetch, "http_get", fake_http(routes, []))
    assert cli.main(["fetch", "--run", str(run_dir), "--links", str(links)]) == 0
    assert "no publish time" in capsys.readouterr().out


def test_link_redirected_to_a_captcha_page_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "none")
    links = tmp_path / "links.txt"
    links.write_text("https://mp.weixin.qq.com/s/abc\n", encoding="utf-8")
    captcha = "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=x"

    def http_get(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
        return Response(captcha, 200, "", b"<html><head><title>Verify</title></head></html>")

    monkeypatch.setattr(fetch, "http_get", http_get)
    assert cli.main(["fetch", "--run", str(run_dir), "--links", str(links)]) == 0
    out = capsys.readouterr().out
    assert "blocked by a captcha page" in out and "links: 0 candidates" in out
    assert _rows(run_dir / "candidates" / "links.jsonl") == []


def test_links_alone_keep_the_run_going_when_every_source_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = started_run(tmp_path / "p", "--only", "qbitai")
    links = tmp_path / "links.txt"
    links.write_text("https://www.qbitai.com/2026/10/x.html\n", encoding="utf-8")
    routes: Routes = {
        "https://www.qbitai.com/feed": FetchError("HTTP 503"),
        "https://www.qbitai.com/2026": fixture_bytes("article_qbitai.html"),
    }
    monkeypatch.setattr(fetch, "http_get", fake_http(routes, []))
    assert cli.main(["fetch", "--run", str(run_dir), "--links", str(links)]) == 0
    assert load_run(run_dir)["stage"] == "fetched"
