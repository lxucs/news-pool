"""Shared test helpers (not fixtures)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from newsdigest import cli, clock
from newsdigest.net import decode_body
from newsdigest.paths import SKILL_DIR

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = SKILL_DIR / "examples" / "raw_sample.jsonl"
CST = timezone(timedelta(hours=8))
SAMPLE_NOW = datetime(2026, 10, 21, 0, 0, tzinfo=CST)  # raw_sample.jsonl is dated 2026-10-20


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return decode_body(fixture_bytes(name), "")


def write_run(
    pool_root: Path,
    run_id: str,
    *,
    kind: str = "daily",
    status: str = "finalized",
    sources: dict[str, tuple[str, str]] | None = None,
    fetch_ok: dict[str, bool] | None = None,
    seen: str | None = None,
) -> Path:
    """A minimal run directory for pool-level tests (not a full pipeline run)."""
    run_dir = pool_root / "runs" / run_id
    run_dir.mkdir(parents=True)
    sources = sources or {}
    fetch_ok = fetch_ok or {}
    run: dict[str, Any] = {
        "run_id": run_id,
        "kind": kind,
        "status": status,
        "stage": "finalized" if status == "finalized" else "started",
        "sources": {sid: {"start": s, "end": e} for sid, (s, e) in sources.items()},
        "fetch": {sid: {"ok": ok} for sid, ok in fetch_ok.items()},
    }
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    if seen is not None:
        (run_dir / "seen.txt").write_text(seen, encoding="utf-8")
    return run_dir


def pin_clock(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr(clock, "now", lambda tz: when.astimezone(tz))


def started_run(pool: Path, *argv: str) -> Path:
    """`init` (idempotent) + `start` with extra flags; returns the new run directory."""
    assert cli.main(["init", "--pool", str(pool)]) == 0
    assert cli.main(["start", "--pool", str(pool), *argv]) == 0
    return sorted((pool / "runs").iterdir())[-1]


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_candidates(run_dir: Path, source_id: str, rows: list[dict[str, Any]] | str) -> None:
    path = run_dir / "candidates" / f"{source_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, str):
        text = rows
    else:
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")


def set_fetched(run_dir: Path, fetch: dict[str, Any]) -> None:
    """Stand in for `fetch` when a test wrote the candidate files itself."""
    run = read_json_file(run_dir / "run.json")
    run["fetch"] = fetch
    run["stage"] = "fetched"
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")


def prepared_run(pool: Path, monkeypatch: pytest.MonkeyPatch, *start_args: str) -> Path:
    """A run over examples/raw_sample.jsonl as manual candidates, through `prepare`."""
    pin_clock(monkeypatch, SAMPLE_NOW)
    run_dir = started_run(pool, "--only", "none", "--hours", "48", *start_args)
    write_candidates(run_dir, "manual", SAMPLE.read_text(encoding="utf-8"))
    assert cli.main(["fetch", "--run", str(run_dir)]) == 0
    assert cli.main(["prepare", "--run", str(run_dir)]) == 0
    return run_dir


def id_for(run_dir: Path, needle: str) -> str:
    """Id of the prepared record whose URL contains `needle`."""
    matches = [r["id"] for r in read_json_file(run_dir / "records.json") if needle in r["url"]]
    assert len(matches) == 1, (needle, matches)
    return matches[0]


def write_triage(run_dir: Path, doc: Any) -> None:
    text = doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False, indent=2)
    (run_dir / "triage.json").write_text(text, encoding="utf-8")


def sample_triage(run_dir: Path) -> dict[str, Any]:
    """What an agent would write for raw_sample.jsonl: 3 events (one with two reports), 1 drop."""
    i = lambda needle: id_for(run_dir, needle)  # noqa: E731
    return {
        "events": [
            {
                "primary": i("reuters.com"),
                "members": [i("reuters.com"), i("theverge.com")],
                "category": "AI",
                "importance": 0.8,
                "novelty": 0.7,
                "sentiment": "neutral",
            },
            {
                "primary": i("techcrunch.com"),
                "members": [i("techcrunch.com")],
                "category": "AI",
                "importance": 0.7,
                "novelty": 0.6,
                "sentiment": "positive",
            },
            {
                "primary": i("bloomberg.com"),
                "members": [i("bloomberg.com")],
                "category": "半导体",
                "importance": 0.6,
                "is_breaking": False,
            },
        ],
        "drop": [i("sports.example.com")],
    }


def sample_enriched(run_dir: Path) -> list[dict[str, Any]]:
    i = lambda needle: id_for(run_dir, needle)  # noqa: E731
    return [
        {
            "id": i("reuters.com"),
            "summary": "OpenAI 发布新推理模型，API 降价六成",
            "key_points": ["基准提升 18%", "输入价 0.8 美元/百万 token", "Tier 3 起开放"],
            "tags": ["大模型", "推理优化"],
            "region": "US",
            "entities": {"companies": ["OpenAI"], "people": [], "products": []},
            "confidence": 0.9,
        },
        {
            "id": i("techcrunch.com"),
            "title_zh": "Anthropic 以 2000 亿美元估值融资 50 亿美元",
            "summary": "Anthropic 完成 50 亿美元融资，估值翻倍至 2000 亿美元",
            "key_points": ["主权基金领投", "半年估值翻倍", "金额 50 亿美元"],
            "tags": ["融资"],
            "region": "US",
            "confidence": 0.85,
        },
        {
            "id": i("bloomberg.com"),
            "summary": "英伟达发布 3nm 数据中心 GPU，功耗降三成",
            "key_points": ["3nm 工艺", "功耗降低 30%", "明年一季度量产"],
            "region": "US",
        },
    ]


def write_enriched(run_dir: Path, rows: list[dict[str, Any]], n: int = 1) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    (run_dir / f"enriched-{n}.jsonl").write_text(text, encoding="utf-8")
