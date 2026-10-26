"""按 news-digest 的 schema.md 的约定读取新闻池：已 finalize 的运行、它们的 manifest、条目文件。
阅读器从不往这里写。读不了的内容一律跳过、绝不崩溃：不存在的文件直接跳过，损坏的文件
记一条警告（进 server.log）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .console import warn

ID_PATTERN = r"[0-9a-f]{12}"  # schema.md：sha1(规范化 URL) 的前 12 位十六进制
RUN_FILE = "run.json"
MANIFEST_FILE = "manifest.json"
STATUS_FINALIZED = "finalized"

_ID_RE = re.compile(ID_PATTERN)


@dataclass(frozen=True)
class Run:
    run_id: str
    kind: str
    focus: str
    finalized_at: str
    created_at: str  # 运行的开始时间 = 其条目的 collected_at
    entries: list[dict[str, Any]]  # manifest 的 items[]，按 rank 排序


def run_dirs(pool: Path) -> list[Path]:
    """运行目录，最早的在前（run_id 就是开始时间戳）。"""
    runs = pool / "runs"
    if not runs.is_dir():
        return []
    return sorted(p for p in runs.iterdir() if p.is_dir())


def run_mtime(run_dir: Path) -> float | None:
    try:
        return (run_dir / RUN_FILE).stat().st_mtime
    except OSError:
        return None


def read_finalized_run(run_dir: Path) -> Run | None:
    """运行及其 manifest 条目；尚未 finalize（或读不了）时返回 None。"""
    run = _read_object(run_dir / RUN_FILE)
    if run is None or run.get("status") != STATUS_FINALIZED:
        return None
    manifest = _read_object(run_dir / MANIFEST_FILE)
    if manifest is None:
        return None
    items = manifest.get("items")
    entries = [
        e
        for e in (items if isinstance(items, list) else [])
        if isinstance(e, dict) and isinstance(e.get("id"), str) and _ID_RE.fullmatch(e["id"])
    ]
    return Run(
        run_id=run_dir.name,
        kind=_text(manifest.get("kind")) or _text(run.get("kind")),
        focus=_text(manifest.get("focus")),
        finalized_at=_text(manifest.get("finalized_at")) or _text(run.get("finalized_at")),
        created_at=_text(run.get("created_at")),
        entries=entries,
    )


def load_item(pool: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    """manifest 条目指向的条目文件：`file`（2.1），没有就用 items/<id>.json（2.0）。"""
    items_dir = (pool / "items").resolve()
    rel = entry.get("file")
    name = rel if isinstance(rel, str) and rel else f"{entry['id']}.json"
    path = (items_dir / name).resolve()
    if items_dir not in path.parents:
        warn(f"manifest entry {entry['id']}: file {rel!r} is outside items/; ignored")
        return None
    if not path.is_file():
        return None
    doc = _read_object(path)
    if doc is None:
        return None
    if doc.get("id") != entry["id"]:
        warn(f"{path}: id {doc.get('id')!r} does not match the manifest's {entry['id']}; ignored")
        return None
    return doc


def day_of(iso: str) -> str:
    """ISO 时间戳在它自己的时区偏移下的 %y%m%d（即条目目录名）；格式不对时返回 ''。"""
    parsed = _parse(iso)
    return parsed.strftime("%y%m%d") if parsed is not None else ""


def timestamp_of(iso: str) -> float:
    parsed = _parse(iso)
    return parsed.timestamp() if parsed is not None else 0.0


def _parse(iso: str) -> datetime | None:
    try:
        # Python 3.9 的 fromisoformat 不接受末尾的 Z。
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        warn(f"{path}: unreadable ({exc}); skipped")
        return None
    if not isinstance(obj, dict):
        warn(f"{path}: not a JSON object; skipped")
        return None
    return obj


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
