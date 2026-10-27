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


def _item_file(run_dir: Path, rid: str) -> Path:
    matches = list(_items_dir(run_dir).rglob(f"*.{rid}.json"))
    assert len(matches) == 1
    return matches[0]


def test_finalize_writes_items_manifest_seen(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    reuters, verge = id_for(run_dir, "reuters.com"), id_for(run_dir, "theverge.com")
    techcrunch, bloomberg = id_for(run_dir, "techcrunch.com"), id_for(run_dir, "bloomberg.com")
    sports = id_for(run_dir, "sports.example.com")
    files = sorted(p.name for p in _items_dir(run_dir).rglob("*.json"))
    assert files == sorted(
        [
            f"261020.anthropic-以-2000-亿美元估值融资-50-亿美元.{techcrunch}.json",
            f"261020.英伟达发布新一代数据中心-gpu-功耗降低-30.{bloomberg}.json",
            f"261020.openai-发布新一代推理模型-api-价格下调-60.{reuters}.json",
        ]
    )
    assert {p.parent.name for p in _items_dir(run_dir).rglob("*.json")} == {"261021"}

    item = read_json_file(_item_file(run_dir, reuters))
    assert item["schema_version"] == "2.1" and item["run_kind"] == "daily"
    assert item["title_zh"] == item["title"]  # 中文原文：title_zh 回退为原标题
    assert [r["id"] for r in item["related"]] == [verge]
    assert item["related"][0]["title"].startswith("OpenAI 新一代推理模型发布")
    assert item["source"]["tier"] == 1 and item["metrics"]["importance"] == 0.8
    assert item["collected_at"] == read_json_file(run_dir / "run.json")["created_at"]
    assert item["synopsis"].startswith("OpenAI 发布新一代推理模型")
    tc = read_json_file(_item_file(run_dir, techcrunch))
    assert tc["title_zh"].startswith("Anthropic") and tc["language"] == "en"

    manifest = read_json_file(run_dir / "manifest.json")
    assert [(e["id"], e["rank"]) for e in manifest["items"]] == [
        (reuters, 1),
        (techcrunch, 2),
        (bloomberg, 3),
    ]
    assert manifest["items"][0]["file"] == (
        f"261021/261020.openai-发布新一代推理模型-api-价格下调-60.{reuters}.json"
    )
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
    out = capsys.readouterr().out
    assert "#1 [0.80]" in out
    # 汇报时要把运行目录告诉用户，然后直接打开阅读器看这次运行
    assert out.splitlines()[-2:] == [
        f"[nd] run: {run_dir}",
        f"[nd] next: open the viewer: nv.py up --run {run_dir.name}",
    ]


def test_events_below_threshold_are_not_written_but_are_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = prepared_run(tmp_path / "p", monkeypatch)
    triage = sample_triage(run_dir)
    triage["events"][2]["importance"] = 0.2  # bloomberg
    ready(run_dir, triage)
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    bloomberg = id_for(run_dir, "bloomberg.com")
    assert not list(_items_dir(run_dir).rglob(f"*.{bloomberg}.json"))
    assert f"{bloomberg} dropped" in (run_dir / "seen.txt").read_text(encoding="utf-8")


def test_adhoc_run_marks_only_kept_items_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = ready(prepared_run(tmp_path / "p", monkeypatch, "--query", "AI"))
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    lines = (run_dir / "seen.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 and all(line.endswith(" kept") for line in lines)
    item = read_json_file(_item_file(run_dir, id_for(run_dir, "reuters.com")))
    assert item["run_kind"] == "adhoc"


def test_validation_failure_writes_nothing(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    del rows[1]["title_zh"]
    write_enriched(run_dir, rows)
    assert cli.main(["finalize", "--run", str(run_dir)]) == 3
    assert not _items_dir(run_dir).exists() or not any(_items_dir(run_dir).rglob("*.json"))
    assert not (run_dir / "manifest.json").exists()
    assert read_json_file(run_dir / "run.json")["status"] == "started"


def test_resolved_lead_url_replaces_the_source_url(run_dir: Path) -> None:
    reuters = id_for(run_dir, "reuters.com")
    write_json_atomic(
        run_dir / "leads.json",
        {reuters: {"lead": "", "resolved_url": "https://real.example.com/a"}},
    )
    assert cli.main(["finalize", "--run", str(run_dir)]) == 0
    source = read_json_file(_item_file(run_dir, reuters))["source"]
    assert source["url"] == "https://real.example.com/a" and source["domain"] == "real.example.com"


def test_crash_mid_commit_leaves_run_unfinalized_and_rerun_completes(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = pool.write_text_atomic

    def broken(path: Path, text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pool, "write_text_atomic", broken)  # seen.txt 是第三步写入
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
    reuters = id_for(run_dir, "reuters.com")
    existing = (
        pool_root
        / "items"
        / (f"261021/261020.openai-发布新一代推理模型-api-价格下调-60.{reuters}.json")
    )
    existing.parent.mkdir(parents=True)
    existing.write_text('{"run_id": "20200101-000000"}', encoding="utf-8")
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
    # 什么都没收进来：打开整个新闻池，而不是一次空运行
    assert capsys.readouterr().out.splitlines()[-1] == "[nd] next: open the viewer: nv.py up"
    assert read_json_file(run_dir / "manifest.json")["items"] == []
    seen = (run_dir / "seen.txt").read_text(encoding="utf-8").splitlines()
    assert sorted(seen) == sorted(f"{rid} dropped" for rid in ids)
