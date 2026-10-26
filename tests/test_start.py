from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from helpers import pin_clock, started_run

from newsdigest import cli

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 21, 8, 30, 15, tzinfo=CST)


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_clock(monkeypatch, NOW)


def _run(run_dir: Path) -> dict:
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


def test_init_copies_example_profile_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"
    assert cli.main(["init", "--pool", str(pool)]) == 0
    config = pool / "profile" / "config.json"
    assert config.is_file() and (pool / "items").is_dir() and (pool / "runs").is_dir()
    config.write_text('{"interests": "mine"}', encoding="utf-8")
    assert cli.main(["init", "--pool", str(pool)]) == 0
    assert "mine" in config.read_text(encoding="utf-8")
    assert "left unchanged" in capsys.readouterr().out


def test_daily_start_uses_profile_sources_and_first_run_window(tmp_path: Path) -> None:
    run_dir = started_run(tmp_path / "p", "--model", "test-model")
    run = _run(run_dir)
    assert run_dir.name == "20261021-083015"
    assert (run["kind"], run["status"], run["stage"]) == ("daily", "started", "started")
    assert list(run["sources"]) == [
        "aihot",
        "qbitai",
        "aiera",
        "leiphone",
        "geekpark",
        "zhidx",
        "gnews",
        "hn",
    ]
    assert run["sources"]["qbitai"]["start"] == (NOW - timedelta(hours=24)).isoformat()
    assert run["queries"] == ["AI 大模型", "人工智能", "智能体"]
    assert run["criterion"].startswith("AI 大模型")
    assert run["model"] == "test-model"
    assert set(run["resources"]) == {
        "feeds.json",
        "tags.txt",
        "source_tiers.json",
        "categories.json",
    }
    assert run["settings"]["min_importance"] == 0.35


def test_only_query_focus_make_an_adhoc_run(tmp_path: Path) -> None:
    run = _run(
        started_run(
            tmp_path / "p", "--only", "qbitai,hn", "--query", "Sora", "--focus", "Sora 相关的新闻"
        )
    )
    assert list(run["sources"]) == ["qbitai", "hn"]
    assert (run["kind"], run["queries"], run["criterion"]) == ("adhoc", ["Sora"], "Sora 相关的新闻")


def test_adhoc_focus_only_keeps_profile_queries_and_query_only_uses_queries(
    tmp_path: Path,
) -> None:
    run = _run(started_run(tmp_path / "p", "--focus", "只看芯片"))
    assert run["kind"] == "adhoc" and run["queries"] == ["AI 大模型", "人工智能", "智能体"]
    assert run["criterion"] == "只看芯片"
    run = _run(started_run(tmp_path / "q", "--query", "a", "--query", "b"))
    assert run["criterion"] == "a、b"


def test_skip_removes_sources(tmp_path: Path) -> None:
    run = _run(started_run(tmp_path / "p", "--skip", "rss"))
    assert list(run["sources"]) == ["gnews", "hn"]


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--only", "nope"], "unknown source"),
        (["--since", "yesterday"], "cannot parse --since"),
        (["--hours", "5", "--since", "2026-10-20"], "not allowed with"),
        (["--hours", "0"], "--hours must be greater than 0"),
        (["--hours", "-3"], "--hours must be greater than 0"),
    ],
)
def test_start_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    pool = tmp_path / "p"
    assert cli.main(["init", "--pool", str(pool)]) == 0
    assert cli.main(["start", "--pool", str(pool), *argv]) == 1
    assert message in capsys.readouterr().err


def test_start_without_profile_points_to_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["start", "--pool", str(tmp_path / "empty")]) == 1
    assert "nd.py init" in capsys.readouterr().err


def test_search_sources_need_queries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pool = tmp_path / "p"
    assert cli.main(["init", "--pool", str(pool)]) == 0
    config = pool / "profile" / "config.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["queries"] = []
    config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["start", "--pool", str(pool)]) == 1
    assert "need queries" in capsys.readouterr().err


def test_sources_lists_feeds_and_builtins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"
    assert cli.main(["init", "--pool", str(pool)]) == 0
    capsys.readouterr()
    assert cli.main(["sources", "--pool", str(pool)]) == 0
    out = capsys.readouterr().out
    assert "qbitai" in out and "量子位" in out and "gdelt" in out and "groups:" in out


def _set_profile_sources(pool: Path, sources: list[str]) -> None:
    config = pool / "profile" / "config.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["sources"] = sources
    config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_unknown_id_in_the_profile_names_the_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"
    assert cli.main(["init", "--pool", str(pool)]) == 0
    _set_profile_sources(pool, ["rss", "nope"])
    capsys.readouterr()
    assert cli.main(["start", "--pool", str(pool)]) == 1
    err = capsys.readouterr().err
    assert "unknown source 'nope' in the profile's `sources` (config.json)" in err
    assert "nd.py sources" in err


def test_sources_still_lists_everything_and_warns_about_an_unknown_profile_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"
    assert cli.main(["init", "--pool", str(pool)]) == 0
    _set_profile_sources(pool, ["rss", "nope"])
    capsys.readouterr()
    assert cli.main(["sources", "--pool", str(pool)]) == 0
    out = capsys.readouterr().out
    assert "qbitai" in out and "gdelt" in out
    assert "warning" in out and "'nope'" in out and "config.json" in out


def test_init_ends_with_a_next_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pool = tmp_path / "p"
    capsys.readouterr()
    assert cli.main(["init", "--pool", str(pool)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].startswith("[nd] next: ask the user what to follow")
    assert "config.json" in lines[-1] and lines[-1].endswith("then start")
    assert any(line.startswith("[nd] pool: ") for line in lines[:-1])
    assert cli.main(["init", "--pool", str(pool)]) == 0  # profile 已经存在
    assert capsys.readouterr().out.splitlines()[-1].startswith("[nd] next: ")
