"""磁盘上的新闻池：运行及其状态、各来源的覆盖范围、seen 集合、提交，以及条目文件的命名。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .errors import UsageError
from .files import read_json, write_json_atomic, write_text_atomic
from .normalize import from_iso, slugify_title
from .selection import Source

RUN_FILE = "run.json"
MANIFEST_FILE = "manifest.json"
SEEN_FILE = "seen.txt"

STATUS_STARTED = "started"
STATUS_FINALIZED = "finalized"
STATUS_ABANDONED = "abandoned"

STAGE_STARTED = "started"
STAGE_FETCHED = "fetched"
STAGE_PREPARED = "prepared"
STAGE_LEADS = "leads"
STAGE_FINALIZED = "finalized"
STAGES = (STAGE_STARTED, STAGE_FETCHED, STAGE_PREPARED, STAGE_LEADS, STAGE_FINALIZED)

KIND_DAILY = "daily"
KIND_ADHOC = "adhoc"
SEEN_KEPT = "kept"
SEEN_DROPPED = "dropped"


@dataclass(frozen=True)
class Pool:
    root: Path

    @property
    def items_dir(self) -> Path:
        return self.root / "items"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def profile_dir(self) -> Path:
        return self.root / "profile"

    def runs(self) -> list[tuple[Path, dict[str, Any]]]:
        """每个运行目录及其 run.json，最早的在前。"""
        if not self.runs_dir.is_dir():
            return []
        dirs = sorted(p for p in self.runs_dir.iterdir() if (p / RUN_FILE).is_file())
        return [(d, read_json(d / RUN_FILE)) for d in dirs]


def pool_of(run_dir: Path) -> Pool:
    return Pool(run_dir.resolve().parent.parent)


def load_run(run_dir: Path) -> dict[str, Any]:
    path = run_dir / RUN_FILE
    if not path.is_file():
        raise UsageError(
            f"{run_dir} is not a run directory (no {RUN_FILE}); `nd.py status` lists runs"
        )
    return read_json(path)


def save_run(run_dir: Path, run: dict[str, Any]) -> None:
    write_json_atomic(run_dir / RUN_FILE, run)


def open_run(run_arg: str) -> tuple[Path, dict[str, Any]]:
    run_dir = Path(run_arg).expanduser().resolve()
    return run_dir, load_run(run_dir)


def require_open(run: dict[str, Any]) -> None:
    status = run.get("status")
    if status != STATUS_STARTED:
        raise UsageError(f"run {run.get('run_id')} is {status}; start a new one with `nd.py start`")


def require_stage(run: dict[str, Any], stage: str, hint: str) -> None:
    """运行还没到 `stage` 就报错（步骤可以重跑，不能跳过）。"""
    current = run.get("stage", STAGE_STARTED)
    if STAGES.index(current) < STAGES.index(stage):
        raise UsageError(f"run {run.get('run_id')} is at stage {current!r}; {hint}")


def coverage(runs: list[dict[str, Any]]) -> dict[str, datetime]:
    """每个来源的覆盖终点：成功抓取过它的、已 finalize 的每日运行里最晚的时间窗终点。"""
    cov: dict[str, datetime] = {}
    for run in runs:
        if run.get("status") != STATUS_FINALIZED or run.get("kind") != KIND_DAILY:
            continue
        sources = run.get("sources") or {}
        for sid, result in (run.get("fetch") or {}).items():
            info = sources.get(sid)
            if not result.get("ok") or not info:
                continue
            end = from_iso(info["end"])
            if sid not in cov or end > cov[sid]:
                cov[sid] = end
    return cov


def seen_ids(pool: Pool, kind: str) -> set[str]:
    """新运行要跳过的 id：每日运行跳过所有处理过的，临时运行只跳过保留过的条目。"""
    out: set[str] = set()
    for run_dir, run in pool.runs():
        if run.get("status") != STATUS_FINALIZED:
            continue
        path = run_dir / SEEN_FILE
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and (kind == KIND_DAILY or parts[1] == SEEN_KEPT):
                out.add(parts[0])
    return out


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def compute_windows(
    now: datetime,
    sources: list[Source],
    kind: str,
    cov: dict[str, datetime],
    window_cfg: dict[str, Any],
    *,
    since: datetime | None = None,
    hours: float | None = None,
    until: datetime | None = None,
) -> tuple[dict[str, Window], Window]:
    """各来源的时间窗（见 references/schema.md），以及 `manual` 候选用的总时间窗。"""
    end = until or now
    first = timedelta(hours=float(window_cfg["first_run_hours"]))
    overlap = timedelta(hours=float(window_cfg["overlap_hours"]))
    longest = timedelta(hours=float(window_cfg["max_hours"]))
    override = (
        since
        if since is not None
        else (end - timedelta(hours=hours) if hours is not None else None)
    )
    if override is not None and override >= end:
        raise UsageError(f"empty window: {override.isoformat()} is not before {end.isoformat()}")
    windows: dict[str, Window] = {}
    for src in sources:
        if override is not None:
            start = override
        elif kind == KIND_ADHOC or src.id not in cov:
            start = end - first
        else:
            start = max(cov[src.id] - overlap, end - longest)
            if start >= end:  # 上次运行之后系统时钟被往回调了
                start = end - overlap
        windows[src.id] = Window(start, end)
    if windows:
        overall = Window(min(w.start for w in windows.values()), end)
    else:
        overall = Window(override if override is not None else end - first, end)
    return windows, overall


def new_run_id(now: datetime, runs_dir: Path) -> str:
    base = now.strftime("%Y%m%d-%H%M%S")
    candidate, n = base, 1
    while (runs_dir / candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def item_relpath(item: dict[str, Any], slug_max: int) -> str:
    """条目文件在 items/ 下的路径（见 schema.md）：<抓取日>/<发布日>.<slug>.<id>.json。"""
    fetched = from_iso(str(item["collected_at"])).strftime("%y%m%d")
    published = from_iso(str(item["published_at"])).strftime("%y%m%d")
    slug = slugify_title(str(item["title_zh"]), slug_max)
    return f"{fetched}/{published}.{slug}.{item['id']}.json"


def build_manifest(
    run: dict[str, Any], items: list[dict[str, Any]], stats: dict[str, Any], finalized_at: str
) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda it: (
            -float(it["metrics"]["importance"]),
            -from_iso(it["published_at"]).timestamp(),
        ),
    )
    by_category: dict[str, int] = {}
    for item in ordered:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    fetch = run.get("fetch") or {}
    sources = {
        sid: {"start": info["start"], "end": info["end"], **fetch.get(sid, {"ok": False})}
        for sid, info in (run.get("sources") or {}).items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run["run_id"],
        "kind": run["kind"],
        "profile": run["profile"],
        "focus": run.get("focus", ""),
        "queries": run.get("queries", []),
        "window": run["window"],
        "sources": sources,
        "finalized_at": finalized_at,
        "stats": {**stats, "items": len(ordered), "by_category": by_category},
        "warnings": list(run.get("warnings", [])),
        "items": [
            {
                "id": it["id"],
                "file": item_relpath(it, int(run["settings"].get("item_slug_max_chars", 40))),
                "rank": rank,
                "title_zh": it["title_zh"],
                "summary": it["summary"],
                "category": it["category"],
                "importance": it["metrics"]["importance"],
                "source_name": it["source"]["name"],
                "published_at": it["published_at"],
                "url": it["source"]["url"],
                "related_count": len(it["related"]),
            }
            for rank, it in enumerate(ordered, start=1)
        ],
    }


def commit_run(
    pool: Pool,
    run_dir: Path,
    run: dict[str, Any],
    items: list[dict[str, Any]],
    manifest: dict[str, Any],
    seen: list[tuple[str, str]],
) -> None:
    """依次写条目、manifest、seen.txt，最后改 status：只有最后一步才让这次运行生效，
    所以提交中途崩溃只会留下一个未 finalize 的运行，重跑 `finalize` 即可补完。"""
    # 用 .get 兼容：2.1 之前的 run.json 快照里没有这个键；40 是内置默认值。
    slug_max = int(run["settings"].get("item_slug_max_chars", 40))
    for item in items:
        _guard_overwrite(pool, item_relpath(item, slug_max), run["run_id"])
    for item in items:
        write_json_atomic(pool.items_dir / item_relpath(item, slug_max), item)
    write_json_atomic(run_dir / MANIFEST_FILE, manifest)
    write_text_atomic(run_dir / SEEN_FILE, "".join(f"{rid} {state}\n" for rid, state in seen))
    run["status"] = STATUS_FINALIZED
    run["stage"] = STAGE_FINALIZED
    run["finalized_at"] = manifest["finalized_at"]
    save_run(run_dir, run)


def _guard_overwrite(pool: Pool, relpath: str, run_id: str) -> None:
    path = pool.items_dir / relpath
    if not path.is_file():
        return
    owner = str(read_json(path).get("run_id", ""))
    if not owner or owner == run_id:
        return
    owner_run = pool.runs_dir / owner / RUN_FILE
    if owner_run.is_file() and read_json(owner_run).get("status") == STATUS_FINALIZED:
        raise RuntimeError(
            f"item {relpath} already belongs to finalized run {owner}; refusing to overwrite it "
            "(cross-run dedup should have skipped it)"
        )
