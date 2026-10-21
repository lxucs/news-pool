from __future__ import annotations

from pathlib import Path

import pytest
from helpers import (
    id_for,
    prepared_run,
    read_json_file,
    sample_enriched,
    sample_triage,
    write_enriched,
    write_run,
    write_triage,
)

from newsdigest import cli, pool
from newsdigest.files import write_json_atomic
from newsdigest.pool import load_run
from newsdigest.status import next_step


def ready(run_dir: Path, triage: dict | None = None) -> Path:
    write_triage(run_dir, triage or sample_triage(run_dir))
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    write_enriched(run_dir, sample_enriched(run_dir))
    return run_dir


@pytest.fixture
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return ready(prepared_run(tmp_path / "p", monkeypatch))


def _items_dir(run_dir: Path) -> Path:
    return run_dir.parent.parent / "items"


def test_finalize_writes_items_manifest_seen(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    reuters, verge = id_for(run_dir, "reuters.com"), id_for(run_dir, "theverge.com")
    techcrunch, bloomberg = id_for(run_dir, "techcrunch.com"), id_for(run_dir, "bloomberg.com")
    sports = id_for(run_dir, "sports.example.com")
    assert sorted(p.stem for p in _items_dir(run_dir).iterdir()) == sorted(
        [reuters, techcrunch, bloomberg]
    )

    item = read_json_file(_items_dir(run_dir) / f"{reuters}.json")
    assert item["schema_version"] == "2.0" and item["run_kind"] == "daily"
    assert item["title_zh"] == item["title"]  # Chinese original: title_zh falls back to it
    assert [r["id"] for r in item["related"]] == [verge]
    assert item["related"][0]["title"].startswith("OpenAI 新一代推理模型发布")
    assert item["source"]["tier"] == 1 and item["metrics"]["importance"] == 0.8
    assert item["collected_at"] == read_json_file(run_dir / "run.json")["created_at"]
    tc = read_json_file(_items_dir(run_dir) / f"{techcrunch}.json")
    assert tc["title_zh"].startswith("Anthropic") and tc["language"] == "en"

    manifest = read_json_file(run_dir / "manifest.json")
    assert [(e["id"], e["rank"]) for e in manifest["items"]] == [
        (reuters, 1),
        (techcrunch, 2),
        (bloomberg, 3),
    ]
    assert manifest["stats"]["events"] == 3 and manifest["stats"]["new"] == 5
    seen = (run_dir / "seen.txt").read_text(encoding="utf-8").splitlines()
    assert sorted(seen) == sorted(
        [
            f"{reuters} kept",
            f"{verge} kept",
            f"{techcrunch} kept",
            f"{bloomberg} kept",
            f"{sports} dropped",
        ]
    )
    run = read_json_file(run_dir / "run.json")
    assert run["status"] == "finalized" and run["stage"] == "finalized"
    assert "#1 [0.80]" in capsys.readouterr().out


def test_events_below_threshold_are_not_written_but_are_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = prepared_run(tmp_path / "p", monkeypatch)
    triage = sample_triage(run_dir)
    triage["events"][2]["importance"] = 0.2  # bloomberg
    ready(run_dir, triage)
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    bloomberg = id_for(run_dir, "bloomberg.com")
    assert not (_items_dir(run_dir) / f"{bloomberg}.json").exists()
    assert f"{bloomberg} dropped" in (run_dir / "seen.txt").read_text(encoding="utf-8")


def test_adhoc_run_marks_only_kept_items_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = ready(prepared_run(tmp_path / "p", monkeypatch, "--query", "AI"))
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    lines = (run_dir / "seen.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 and all(line.endswith(" kept") for line in lines)
    item = read_json_file(_items_dir(run_dir) / f"{id_for(run_dir, 'reuters.com')}.json")
    assert item["run_kind"] == "adhoc"


def test_validation_failure_writes_nothing(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    del rows[1]["title_zh"]
    write_enriched(run_dir, rows)
    assert cli.main(["finalize", "--run", str(run_dir)]) == 3
    assert not _items_dir(run_dir).exists() or not any(_items_dir(run_dir).iterdir())
    assert not (run_dir / "manifest.json").exists()
    assert read_json_file(run_dir / "run.json")["status"] == "started"


def test_resolved_lead_url_replaces_the_source_url(run_dir: Path) -> None:
    reuters = id_for(run_dir, "reuters.com")
    write_json_atomic(
        run_dir / "leads.json",
        {reuters: {"lead": "", "resolved_url": "https://real.example.com/a"}},
    )
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    source = read_json_file(_items_dir(run_dir) / f"{reuters}.json")["source"]
    assert source["url"] == "https://real.example.com/a" and source["domain"] == "real.example.com"


def test_crash_mid_commit_leaves_run_unfinalized_and_rerun_completes(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = pool.write_text_atomic

    def broken(path: Path, text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pool, "write_text_atomic", broken)  # seen.txt is the third write
    assert cli.main(["finalize", "--run", str(run_dir)]) == 5
    assert (run_dir / "manifest.json").exists()
    assert read_json_file(run_dir / "run.json")["status"] == "started"
    assert (run_dir / "nd-error.log").is_file()

    monkeypatch.setattr(pool, "write_text_atomic", real)
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    assert read_json_file(run_dir / "run.json")["status"] == "finalized"


def test_refuses_to_overwrite_an_item_of_another_finalized_run(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool_root = run_dir.parent.parent
    write_run(pool_root, "20200101-000000")
    items = pool_root / "items"
    items.mkdir(exist_ok=True)
    reuters = id_for(run_dir, "reuters.com")
    (items / f"{reuters}.json").write_text('{"run_id": "20200101-000000"}', encoding="utf-8")
    assert cli.main(["finalize", "--run", str(run_dir)]) == 5
    assert "refusing to overwrite" in capsys.readouterr().err


def test_finalizing_twice_is_a_no_op(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    capsys.readouterr()
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    assert "already finalized" in capsys.readouterr().out


def test_nothing_kept_goes_check_leads_check_finalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = prepared_run(tmp_path / "p", monkeypatch)
    ids = [r["id"] for r in read_json_file(run_dir / "records.json")]
    write_triage(run_dir, {"events": [], "drop": ids})
    capsys.readouterr()
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    assert "next: leads" in capsys.readouterr().out
    assert cli.main(["leads", "--run", str(run_dir), "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "next: finalize" in out and "enriched-1" not in out
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "next: finalize" in out and "enriched-1" not in out
    step = next_step(run_dir, load_run(run_dir))
    assert "finalize" in step and "enriched" not in step
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    assert read_json_file(run_dir / "manifest.json")["items"] == []
    seen = (run_dir / "seen.txt").read_text(encoding="utf-8").splitlines()
    assert sorted(seen) == sorted(f"{rid} dropped" for rid in ids)
