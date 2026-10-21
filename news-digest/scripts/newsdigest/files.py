"""Pool file I/O: atomic writes, our own JSON, and located parsing of agent-written JSON."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

QUOTE_CHARS = 120  # how much of an offending line an error message quotes


def write_text_atomic(path: Path, text: str) -> None:
    """Write a temp file in the same directory, then rename: readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_json_atomic(path: Path, obj: Any) -> None:
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_jsonl_atomic(path: Path, rows: Iterable[Any]) -> None:
    write_text_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def read_jsonl_loose(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Object rows of a candidates file, and how many lines were skipped as unusable."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                skipped += 1
    return rows, skipped


@dataclass(frozen=True)
class JsonProblem:
    file: str
    line: int
    col: int
    message: str
    text: str


class AgentJsonError(Exception):
    def __init__(self, problem: JsonProblem) -> None:
        super().__init__(f"{problem.file}:{problem.line}:{problem.col}: {problem.message}")
        self.problem = problem


def _unwrap_lines(text: str) -> list[str]:
    """Drop a BOM and blank out one surrounding Markdown fence, keeping line numbers intact."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    filled = [i for i, line in enumerate(lines) if line.strip()]
    if len(filled) >= 2:
        first, last = filled[0], filled[-1]
        if lines[first].strip().startswith("```") and lines[last].strip() == "```":
            lines[first] = ""
            lines[last] = ""
    return lines


def _quote(lines: list[str], lineno: int) -> str:
    return lines[lineno - 1].strip()[:QUOTE_CHARS] if 0 < lineno <= len(lines) else ""


def load_agent_json(path: Path) -> Any:
    lines = _unwrap_lines(path.read_text(encoding="utf-8", errors="replace"))
    try:
        return json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        problem = JsonProblem(path.name, exc.lineno, exc.colno, exc.msg, _quote(lines, exc.lineno))
        raise AgentJsonError(problem) from None


def load_agent_jsonl(path: Path) -> tuple[list[tuple[int, Any]], list[JsonProblem]]:
    """(line number, value) for each parsable line, and a problem for each line that is not."""
    rows: list[tuple[int, Any]] = []
    problems: list[JsonProblem] = []
    lines = _unwrap_lines(path.read_text(encoding="utf-8", errors="replace"))
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rows.append((lineno, json.loads(line)))
        except json.JSONDecodeError as exc:
            problems.append(
                JsonProblem(path.name, lineno, exc.colno, exc.msg, _quote(lines, lineno))
            )
    return rows, problems
