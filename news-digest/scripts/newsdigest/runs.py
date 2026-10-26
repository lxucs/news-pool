"""运行的生命周期：`init`（新闻池和 profile）、`sources`（可选的来源）、`start`（新建运行）。"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__, clock
from .config import (
    FEEDS_FILE,
    PROFILE_CONFIG,
    RESOURCE_FILES,
    load_feeds,
    load_settings,
    resource_path,
)
from .console import say, warn
from .errors import UsageError
from .normalize import parse_time, parse_tz
from .paths import EXAMPLE_PROFILE_DIR, resolve_pool
from .pool import (
    KIND_ADHOC,
    KIND_DAILY,
    STAGE_STARTED,
    STATUS_STARTED,
    Pool,
    compute_windows,
    coverage,
    new_run_id,
    save_run,
)
from .selection import (
    KIND_SEARCH,
    PROFILE_ORIGIN,
    Source,
    build_registry,
    parse_id_list,
    select_sources,
    unknown_ids,
)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="create the pool and a profile copied from the example")
    p.add_argument("--pool")
    p.set_defaults(handler=cmd_init)

    p = sub.add_parser("sources", help="list every selectable source id")
    p.add_argument("--pool")
    p.add_argument("--profile", help="profile directory (default: <pool>/profile)")
    p.set_defaults(handler=cmd_sources)

    p = sub.add_parser("start", help="create a run: select sources and resolve their windows")
    p.add_argument("--pool")
    p.add_argument("--profile", help="profile directory (default: <pool>/profile)")
    p.add_argument("--only", help="comma-separated source ids/groups; replaces the profile list")
    p.add_argument("--skip", help="comma-separated source ids/groups to leave out")
    p.add_argument("--query", action="append", default=[], help="search query; makes the run adhoc")
    p.add_argument("--focus", help="what to keep, in one sentence; makes the run adhoc")
    span = p.add_mutually_exclusive_group()
    span.add_argument("--hours", type=float, help="window: the past N hours, for every source")
    span.add_argument("--since", help="window start (ISO 8601), for every source")
    p.add_argument("--until", help="window end (ISO 8601); default now")
    p.add_argument("--model", default="", help="the agent's model name, recorded in items")
    p.set_defaults(handler=cmd_start)


def cmd_init(args: argparse.Namespace) -> int:
    pool = Pool(resolve_pool(args.pool))
    pool.items_dir.mkdir(parents=True, exist_ok=True)
    pool.runs_dir.mkdir(parents=True, exist_ok=True)
    created = not pool.profile_dir.exists()
    if not created:
        say(f"profile already exists, left unchanged: {pool.profile_dir}")
    else:
        shutil.copytree(EXAMPLE_PROFILE_DIR, pool.profile_dir)
        say(f"created a profile from the example: {pool.profile_dir}")
    say(f"pool: {pool.root}")
    if created:
        config = pool.profile_dir / PROFILE_CONFIG
        say(
            f"next: ask the user what to follow, edit `interests` and `queries` in {config}, "
            "then start"
        )
    else:
        say("next: status")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    pool = Pool(resolve_pool(args.pool))
    settings, registry = _load_profile(_profile_dir(args, pool))
    configured = settings["sources"]
    unknown = unknown_ids(configured, registry)
    for token in unknown:
        warn(f"unknown source {token!r} in {PROFILE_ORIGIN}; ignored here, but `start` fails on it")
    known = [t for t in configured if t not in unknown]
    default_ids = {s.id for s in select_sources(known, None, None, registry)}
    cov = coverage([run for _, run in pool.runs()])
    for src in registry.values():
        state = "on" if src.id in default_ids else ("disabled" if not src.enabled else "off")
        covered = cov[src.id].isoformat() if src.id in cov else "-"
        say(f"{src.id:<20} {src.kind:<6} {state:<8} {src.name}  covered-until={covered}")
    say("groups: rss = every enabled feed; none = no sources (links/manual only)")
    say("`on` = in the profile's default selection; choose others with `start --only a,b`")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    if args.hours is not None and args.hours <= 0:
        raise UsageError("--hours must be greater than 0")
    pool = Pool(resolve_pool(args.pool))
    profile_dir = _profile_dir(args, pool)
    settings, registry = _load_profile(profile_dir)
    tz = parse_tz(settings["tz"])
    now = clock.now(tz)
    selected = select_sources(
        settings["sources"], parse_id_list(args.only), parse_id_list(args.skip), registry
    )
    given = [q.strip() for q in args.query if q.strip()]
    focus = (args.focus or "").strip()
    kind = KIND_ADHOC if given or focus else KIND_DAILY
    queries = given or list(settings["queries"])
    if not queries and any(s.kind == KIND_SEARCH for s in selected):
        raise UsageError(
            "search sources need queries: set `queries` in the profile or pass --query"
        )
    criterion = settings["interests"] if kind == KIND_DAILY else (focus or "、".join(queries))
    windows, overall = compute_windows(
        now,
        selected,
        kind,
        coverage([run for _, run in pool.runs()]),
        settings["window"],
        since=_cli_time(args.since, tz, "--since"),
        hours=args.hours,
        until=_cli_time(args.until, tz, "--until"),
    )
    pool.runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id(now, pool.runs_dir)
    run_dir = pool.runs_dir / run_id
    run: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "kind": kind,
        "profile": settings["name"],
        "profile_dir": str(profile_dir),
        "model": args.model,
        "skill_version": __version__,
        "created_at": now.isoformat(),
        "status": STATUS_STARTED,
        "stage": STAGE_STARTED,
        "criterion": criterion,
        "focus": focus,
        "queries": queries,
        "window": {
            "start": overall.start.isoformat(),
            "end": overall.end.isoformat(),
            "tz": settings["tz"],
        },
        "sources": {
            src.id: {
                "name": src.name,
                "kind": src.kind,
                "adapter": src.adapter,
                "url": src.url,
                "start": windows[src.id].start.isoformat(),
                "end": windows[src.id].end.isoformat(),
            }
            for src in selected
        },
        "fetch": {},
        "warnings": [],
        "stats": {},
        "settings": settings,
        "resources": {name: str(resource_path(profile_dir, name)) for name in RESOURCE_FILES},
    }
    run_dir.mkdir()
    save_run(run_dir, run)
    for other_dir, other in pool.runs():
        if other.get("status") == STATUS_STARTED and other_dir != run_dir:
            say(
                f"note: run {other_dir.name} is unfinished; "
                "`status` shows how to resume or abandon it"
            )
    say(f"run: {run_dir}")
    say(f"kind: {kind}; criterion: {criterion}")
    for sid, window in windows.items():
        say(f"  {sid}: {window.start.isoformat()} .. {window.end.isoformat()}")
    if not windows:
        say("  no sources selected: add `fetch --links FILE` or write candidates/manual.jsonl")
    say(f"next: fetch --run {run_dir}")
    return 0


def _profile_dir(args: argparse.Namespace, pool: Pool) -> Path:
    return Path(args.profile).expanduser().resolve() if args.profile else pool.profile_dir


def _load_profile(profile_dir: Path) -> tuple[dict[str, Any], dict[str, Source]]:
    settings = load_settings(profile_dir)
    registry = build_registry(load_feeds(resource_path(profile_dir, FEEDS_FILE)))
    return settings, registry


def _cli_time(value: str | None, tz: tzinfo, flag: str) -> datetime | None:
    if value is None:
        return None
    parsed = parse_time(value, tz)
    if parsed is None:
        raise UsageError(f"cannot parse {flag} {value!r}; use ISO 8601 like 2026-10-20T08:00+08:00")
    return parsed
