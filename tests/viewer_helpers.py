"""Builders for viewer tests: pools on disk in the shape news-digest's schema.md describes."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CREATED = "2026-10-22T09:00:00+08:00"


def hex_id(n: int) -> str:
    """A valid item id (12 hex digits)."""
    return f"{n:012x}"


def item_doc(
    item_id: str,
    title_zh: str,
    *,
    importance: float = 0.5,
    source_name: str = "来源甲",
    **fields: Any,
) -> dict[str, Any]:
    """An item as news-digest's finalize writes it (schema.md, 条目); `fields` override keys."""
    doc: dict[str, Any] = {
        "schema_version": "2.1",
        "id": item_id,
        "run_id": "",
        "run_kind": "daily",
        "profile": "test",
        "title": title_zh,
        "title_zh": title_zh,
        "language": "zh",
        "summary": f"{title_zh}的摘要",
        "synopsis": f"{title_zh}的详细说明。",
        "key_points": ["要点一", "要点二", "要点三"],
        "why_it_matters": "",
        "category": "AI",
        "tags": [],
        "region": "",
        "entities": {"companies": [], "people": [], "products": []},
        "source": {
            "id": "feed",
            "name": source_name,
            "domain": "example.com",
            "url": f"https://example.com/{item_id}",
            "author": "",
            "tier": 2,
        },
        "published_at": "2026-10-21T08:00:00+08:00",
        "collected_at": CREATED,
        "cover_image": {"url": ""},
        "metrics": {"importance": importance, "novelty": 0.5, "sentiment": "neutral"},
        "flags": {"is_breaking": False, "is_opinion": False, "needs_review": False},
        "related": [],
        "llm": {"model": "test", "skill_version": "2.1.0", "confidence": 0.8},
    }
    doc.update(fields)
    return doc


def write_run(
    pool: Path,
    run_id: str,
    docs: list[dict[str, Any]],
    *,
    status: str = "finalized",
    kind: str = "daily",
    focus: str = "",
    created_at: str = CREATED,
    with_file_field: bool = True,
    skip_files: Iterable[str] = (),
) -> Path:
    """A run directory; when finalized, also its manifest and item files.

    `with_file_field=False` writes a 2.0 manifest (no `file`; items at items/<id>.json). Ids in
    `skip_files` get a manifest entry but no item file. Calling it again for the same run id
    rewrites the run (a started run that later finalizes)."""
    run_dir = pool / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    skipped = set(skip_files)
    day = created_at[2:4] + created_at[5:7] + created_at[8:10]
    entries: list[dict[str, Any]] = []
    for rank, base in enumerate(docs, start=1):
        doc = {**base, "run_id": run_id, "run_kind": kind, "collected_at": created_at}
        rel = f"{day}/{doc['id']}.json" if with_file_field else f"{doc['id']}.json"
        if status == "finalized" and doc["id"] not in skipped:
            path = pool / "items" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        entry: dict[str, Any] = {
            "id": doc["id"],
            "rank": rank,
            "title_zh": doc["title_zh"],
            "summary": doc["summary"],
            "category": doc["category"],
            "importance": doc["metrics"]["importance"],
            "source_name": doc["source"]["name"],
            "published_at": doc["published_at"],
            "url": doc["source"]["url"],
            "related_count": len(doc["related"]),
        }
        if with_file_field:
            entry["file"] = rel
        entries.append(entry)
    run = {
        "run_id": run_id,
        "kind": kind,
        "status": status,
        "created_at": created_at,
        "focus": focus,
    }
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    if status == "finalized":
        manifest = {
            "schema_version": "2.1" if with_file_field else "2.0",
            "run_id": run_id,
            "kind": kind,
            "focus": focus,
            "finalized_at": created_at,
            "items": entries,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
    return run_dir
