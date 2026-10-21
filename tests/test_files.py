from __future__ import annotations

from pathlib import Path

import pytest

from newsdigest import files
from newsdigest.files import (
    AgentJsonError,
    load_agent_json,
    load_agent_jsonl,
    read_json,
    read_jsonl_loose,
    write_json_atomic,
)


def test_write_json_atomic_roundtrip_no_temp_left(tmp_path: Path) -> None:
    path = tmp_path / "a" / "x.json"
    write_json_atomic(path, {"标题": 1})
    assert read_json(path) == {"标题": 1}
    assert "标题" in path.read_text(encoding="utf-8")
    assert [p.name for p in path.parent.iterdir()] == ["x.json"]


def test_failed_replace_keeps_original_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "x.json"
    write_json_atomic(path, {"v": 1})

    def boom(src: str, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(files.os, "replace", boom)
    with pytest.raises(OSError):
        write_json_atomic(path, {"v": 2})
    assert read_json(path) == {"v": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_agent_json_tolerates_bom_and_one_fence(tmp_path: Path) -> None:
    path = tmp_path / "triage.json"
    path.write_text('\ufeff```json\n{"events": [], "drop": []}\n```\n', encoding="utf-8")
    assert load_agent_json(path) == {"events": [], "drop": []}


def test_agent_json_error_keeps_real_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "triage.json"
    path.write_text('```json\n{\n  "events": [],\n  "drop": ["a",],\n}\n```\n', encoding="utf-8")
    with pytest.raises(AgentJsonError) as info:
        load_agent_json(path)
    problem = info.value.problem
    assert problem.file == "triage.json"
    assert problem.line == 4
    assert '"drop"' in problem.text


def test_agent_json_rejects_trailing_text(tmp_path: Path) -> None:
    path = tmp_path / "triage.json"
    path.write_text('{"events": []} // done\n', encoding="utf-8")
    with pytest.raises(AgentJsonError, match="Extra data"):
        load_agent_json(path)


def test_agent_jsonl_reports_each_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "enriched-1.jsonl"
    path.write_text('```jsonl\n{"id": "a"}\n{"id": "b",}\n\n{"id": "c"}\n```\n', encoding="utf-8")
    rows, problems = load_agent_jsonl(path)
    assert [lineno for lineno, _ in rows] == [2, 5]
    assert [(p.file, p.line) for p in problems] == [("enriched-1.jsonl", 3)]


def test_read_jsonl_loose_skips_unusable_lines(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text('{"a": 1}\nnot json\n[1]\n\n{"b": 2}\n', encoding="utf-8")
    rows, skipped = read_jsonl_loose(path)
    assert rows == [{"a": 1}, {"b": 2}] and skipped == 2
