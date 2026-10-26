from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

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

from newsdigest import cli
from newsdigest.pool import load_run, save_run
from newsdigest.validate import kept_primaries, load_context, load_enriched, require_valid_triage


@pytest.fixture
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return prepared_run(tmp_path / "p", monkeypatch)


def test_valid_triage_passes_check(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_triage(run_dir, sample_triage(run_dir))
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "3 events, 3 kept" in out and "next: leads" in out
    assert not (run_dir / "errors.json").exists()


def test_fenced_triage_is_accepted(run_dir: Path) -> None:
    body = json.dumps(sample_triage(run_dir), ensure_ascii=False)
    write_triage(run_dir, f"```json\n{body}\n```\n")
    assert cli.main(["check", "--run", str(run_dir)]) == 0


Mutation = Callable[[dict[str, Any], Path], None]


def _drop_sports(doc: dict[str, Any], run_dir: Path) -> None:
    doc["drop"] = []


def _unknown_id(doc: dict[str, Any], run_dir: Path) -> None:
    doc["drop"].append("ffffffffffff")


def _duplicate(doc: dict[str, Any], run_dir: Path) -> None:
    doc["drop"].append(id_for(run_dir, "bloomberg.com"))


def _primary_outside(doc: dict[str, Any], run_dir: Path) -> None:
    doc["events"][1]["primary"] = id_for(run_dir, "reuters.com")


def _bad_category(doc: dict[str, Any], run_dir: Path) -> None:
    doc["events"][0]["category"] = "科技"


def _bad_importance(doc: dict[str, Any], run_dir: Path) -> None:
    doc["events"][0]["importance"] = 1.5


def _bad_sentiment(doc: dict[str, Any], run_dir: Path) -> None:
    doc["events"][0]["sentiment"] = "bullish"


def _bad_flag(doc: dict[str, Any], run_dir: Path) -> None:
    doc["events"][0]["is_opinion"] = "yes"


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (_drop_sports, "missing; put it in an event's members or in drop"),
        (_unknown_id, "unknown id"),
        (_duplicate, "appears 2 times"),
        (_primary_outside, "must be one of the event's members"),
        (_bad_category, "expected one of: AI, 半导体"),
        (_bad_importance, "number from 0 to 1"),
        (_bad_sentiment, "positive, neutral, negative"),
        (_bad_flag, "true or false"),
    ],
)
def test_triage_problems_exit_3_with_located_messages(
    run_dir: Path, capsys: pytest.CaptureFixture[str], mutate: Mutation, expected: str
) -> None:
    doc = sample_triage(run_dir)
    mutate(doc, run_dir)
    write_triage(run_dir, doc)
    assert cli.main(["check", "--run", str(run_dir)]) == 3
    assert expected in capsys.readouterr().err
    assert read_json_file(run_dir / "errors.json")["count"] >= 1


def test_broken_json_reports_line_and_column(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_triage(run_dir, '{\n  "events": [],\n  "drop": ["a",]\n}\n')
    assert cli.main(["check", "--run", str(run_dir)]) == 3
    assert "triage.json:3 col" in capsys.readouterr().err


def test_error_output_is_capped_but_errors_json_is_complete(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = load_run(run_dir)
    run["settings"]["output"]["max_problems"] = 2
    save_run(run_dir, run)
    write_triage(run_dir, {"events": [], "drop": []})  # 5 个 id 全部缺失
    assert cli.main(["check", "--run", str(run_dir)]) == 3
    err_lines = [
        line for line in capsys.readouterr().err.splitlines() if line.startswith("[nd] error:")
    ]
    assert len(err_lines) == 4  # 2 条问题 + "... and 3 more" + 汇总行
    assert read_json_file(run_dir / "errors.json")["count"] == 5


def test_errors_json_is_cleared_once_check_passes(run_dir: Path) -> None:
    write_triage(run_dir, {"events": [], "drop": []})
    assert cli.main(["check", "--run", str(run_dir)]) == 3
    write_triage(run_dir, sample_triage(run_dir))
    assert cli.main(["check", "--run", str(run_dir)]) == 0
    assert not (run_dir / "errors.json").exists()


def _enriched(run_dir: Path) -> tuple[Any, list[Any]]:
    write_triage(run_dir, sample_triage(run_dir))
    ctx = load_context(str(run_dir))
    triage = require_valid_triage(ctx)
    return load_enriched(ctx, kept_primaries(ctx, triage))


def test_valid_enriched_normalizes_defaults(run_dir: Path) -> None:
    write_enriched(run_dir, sample_enriched(run_dir))
    enriched, problems = _enriched(run_dir)
    assert problems == []
    row = enriched.rows[id_for(run_dir, "bloomberg.com")]
    assert row["tags"] == [] and row["why_it_matters"] == "" and row["confidence"] == 0.0
    assert row["entities"] == {"companies": [], "people": [], "products": []}
    assert row["synopsis"].startswith("英伟达")


def test_missing_synopsis_is_a_problem(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    del rows[0]["synopsis"]
    write_enriched(run_dir, rows)
    _, problems = _enriched(run_dir)
    assert [p.field for p in problems] == ["synopsis"]


def test_overlong_synopsis_only_warns(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    rows[0]["synopsis"] = "长" * 251
    write_enriched(run_dir, rows)
    enriched, problems = _enriched(run_dir)
    assert problems == []
    assert any("synopsis is 251 chars" in w for w in enriched.warnings)


def test_english_item_needs_title_zh_and_every_primary_needs_a_line(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    del rows[1]["title_zh"]
    write_enriched(run_dir, rows[:2])
    _, problems = _enriched(run_dir)
    messages = [p.format() for p in problems]
    assert any("title_zh" in m for m in messages)
    assert any(id_for(run_dir, "bloomberg.com") in m and "missing" in m for m in messages)


def test_region_must_be_known_or_empty(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    rows[0]["region"] = "Asia"
    rows[1]["region"] = ""
    write_enriched(run_dir, rows)
    _, problems = _enriched(run_dir)
    assert [p.field for p in problems] == ["region"]


def test_later_file_supersedes_and_warns(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    broken = dict(rows[2], summary="")
    write_enriched(run_dir, rows[:2] + [broken], n=1)
    write_enriched(run_dir, [rows[2]], n=2)
    enriched, problems = _enriched(run_dir)
    assert problems == []
    assert any("superseded by enriched-2.jsonl" in w for w in enriched.warnings)


def test_soft_rules_only_warn(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    rows[0]["summary"] = "很长" * 40
    rows[0]["key_points"] = ["只有一条"]
    rows[0]["tags"] = ["一个词表外的标签"]
    write_enriched(run_dir, rows)
    (run_dir / "enriched-fix.jsonl").write_text("{}\n", encoding="utf-8")
    enriched, problems = _enriched(run_dir)
    assert problems == []
    text = "\n".join(enriched.warnings)
    assert "summary is 80 chars" in text and "key_points has 1" in text
    assert "一个词表外的标签(1)" in text and "enriched-fix.jsonl: ignored" in text


def _truncated_line(run_dir: Path) -> str:
    return '{"id": "' + id_for(run_dir, "bloomberg.com") + '", "summary": "英伟达发布\n'


def test_unparsable_line_superseded_by_a_later_file_is_only_a_warning(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    write_enriched(run_dir, rows[:2])
    with (run_dir / "enriched-1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(_truncated_line(run_dir))
    write_enriched(run_dir, [rows[2]], n=2)
    enriched, problems = _enriched(run_dir)
    assert problems == []
    assert len(enriched.rows) == 3
    assert any(w.startswith("enriched-1.jsonl:3:") for w in enriched.warnings)


def test_missing_primary_names_the_unparsable_lines(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    write_enriched(run_dir, rows[:2])
    with (run_dir / "enriched-1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(_truncated_line(run_dir))
    _, problems = _enriched(run_dir)
    assert len(problems) == 1
    message = problems[0].format()
    assert "missing" in message and "enriched-1.jsonl:3:" in message


def test_non_object_line_superseded_by_a_later_file_is_only_a_warning(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    write_enriched(run_dir, rows[:2])
    with (run_dir / "enriched-1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('["not", "an", "object"]\n{"summary": "no id"}\n')
    write_enriched(run_dir, [rows[2]], n=2)
    enriched, problems = _enriched(run_dir)
    assert problems == []
    assert len(enriched.rows) == 3
    assert any(w.startswith("enriched-1.jsonl:3:") for w in enriched.warnings)
    assert any(w.startswith("enriched-1.jsonl:4:") for w in enriched.warnings)


def test_missing_primary_names_the_non_object_lines(run_dir: Path) -> None:
    rows = sample_enriched(run_dir)
    write_enriched(run_dir, rows[:2])
    with (run_dir / "enriched-1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('["not", "an", "object"]\n')
    _, problems = _enriched(run_dir)
    assert len(problems) == 1
    message = problems[0].format()
    assert "missing" in message and "enriched-1.jsonl:3" in message
