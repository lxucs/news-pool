from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from helpers import (
    id_for,
    prepared_run,
    read_json_file,
    sample_enriched,
    sample_triage,
    write_enriched,
    write_triage,
)

from newsdigest import __version__, cli
from newsdigest.paths import SKILL_DIR
from newsdigest.pool import load_run


def test_entry_point_runs_under_isolated_python() -> None:
    script = SKILL_DIR / "scripts" / "nd.py"
    done = subprocess.run(
        [sys.executable, "-I", str(script), "--version"], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == __version__


def _finish(run_dir: Path, triage: dict, enriched: list[dict]) -> None:
    write_triage(run_dir, triage)
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    write_enriched(run_dir, enriched)
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0


def test_daily_repeat_adhoc_daily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "p"

    first = prepared_run(pool, monkeypatch)
    _finish(first, sample_triage(first), sample_enriched(first))
    assert len(list((pool / "items").iterdir())) == 3

    repeat = prepared_run(pool, monkeypatch)  # same candidates: all seen
    assert load_run(repeat)["status"] == "finalized"
    assert read_json_file(repeat / "manifest.json")["items"] == []

    adhoc = prepared_run(pool, monkeypatch, "--query", "足球", "--focus", "足球赛事")
    sports = id_for(adhoc, "sports.example.com")  # dropped by the daily run, so eligible again
    assert [i["id"] for i in read_json_file(adhoc / "triage_input.json")["items"]] == [sports]
    triage = {
        "events": [{"primary": sports, "members": [sports], "category": "体育", "importance": 0.5}],
        "drop": [],
    }
    enriched = [
        {
            "id": sports,
            "summary": "某足球队提前三轮夺得联赛冠军",
            "key_points": ["提前三轮", "联赛冠军", "本赛季"],
        }
    ]
    _finish(adhoc, triage, enriched)
    assert (pool / "items" / f"{sports}.json").is_file()
    assert (adhoc / "seen.txt").read_text(encoding="utf-8") == f"{sports} kept\n"

    after = prepared_run(pool, monkeypatch)
    assert load_run(after)["status"] == "finalized"  # nothing new for the daily run either

    capsys.readouterr()
    assert cli.main(["status", "--pool", str(pool)]) == 0
    out = capsys.readouterr().out
    assert "unfinished" not in out and "last finalized run" in out
