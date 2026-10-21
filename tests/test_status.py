from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from helpers import SAMPLE_NOW, pin_clock, started_run

from newsdigest import cli
from newsdigest.status import next_step


def _status(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    assert cli.main(["status", *argv]) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    "run, files, expected",
    [
        ({"status": "started", "stage": "started"}, [], "fetch"),
        (
            {"status": "started", "stage": "started", "fetch": {"hn": {"ok": False}}},
            [],
            "every source failed",
        ),
        ({"status": "started", "stage": "fetched"}, [], "prepare"),
        ({"status": "started", "stage": "prepared"}, [], "write triage.json"),
        ({"status": "started", "stage": "prepared"}, ["triage.json"], "check, then leads"),
        ({"status": "started", "stage": "leads"}, [], "write enriched-1.jsonl"),
        ({"status": "started", "stage": "leads"}, ["enriched-1.jsonl"], "check, then finalize"),
        ({"status": "finalized", "stage": "finalized"}, [], "finalized"),
        ({"status": "abandoned", "stage": "fetched"}, [], "abandoned"),
    ],
)
def test_next_step(tmp_path: Path, run: dict, files: list[str], expected: str) -> None:
    for name in files:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert expected in next_step(tmp_path, run)


def test_status_without_profile(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert "run `nd.py init`" in _status(["--pool", str(tmp_path / "empty")], capsys)


def test_unfinished_runs_are_resumable_then_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(pool, "--only", "none")
    pin_clock(monkeypatch, SAMPLE_NOW + timedelta(hours=2))
    out = _status(["--pool", str(pool)], capsys)
    assert run_dir.name in out and "resumable" in out and "next: fetch" in out
    pin_clock(monkeypatch, SAMPLE_NOW + timedelta(hours=13))
    assert "stale" in _status(["--pool", str(pool)], capsys)
    assert "next: fetch" in _status(["--run", str(run_dir)], capsys)


def test_abandon_hides_a_run_and_refuses_finalized_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(pool, "--only", "none")
    assert cli.main(["abandon", "--run", str(run_dir)]) == 0
    assert "unfinished" not in _status(["--pool", str(pool)], capsys)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run["status"] = "finalized"
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    assert cli.main(["abandon", "--run", str(run_dir)]) == 1
