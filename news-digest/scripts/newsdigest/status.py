"""status / abandon：新闻池的现状，以及每个未完成的运行下一步该做什么。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import clock
from .config import PROFILE_CONFIG, load_settings
from .console import say
from .errors import UsageError
from .files import read_json
from .normalize import from_iso, parse_tz
from .paths import init_hint, resolve_pool
from .pool import (
    MANIFEST_FILE,
    STAGE_FETCHED,
    STAGE_LEADS,
    STAGE_PREPARED,
    STAGE_STARTED,
    STATUS_ABANDONED,
    STATUS_FINALIZED,
    STATUS_STARTED,
    Pool,
    coverage,
    open_run,
    save_run,
)
from .validate import ENRICH_INPUT_FILE, TRIAGE_FILE


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("status", help="pool, profile, coverage, and what unfinished runs need next")
    p.add_argument("--pool")
    p.add_argument("--run", help="show one run only")
    p.set_defaults(handler=cmd_status)

    p = sub.add_parser("abandon", help="mark an unfinished run abandoned")
    p.add_argument("--run", required=True)
    p.set_defaults(handler=cmd_abandon)


def next_step(run_dir: Path, run: dict[str, Any]) -> str:
    status = run.get("status")
    if status == STATUS_FINALIZED:
        return "nothing: the run is finalized"
    if status == STATUS_ABANDONED:
        return "nothing: the run was abandoned"
    stage = run.get("stage", STAGE_STARTED)
    if stage == STAGE_STARTED:
        fetch = run.get("fetch") or {}
        if fetch and not any(r.get("ok") for r in fetch.values()):
            return (
                "every source failed last time: check network access, then `fetch` again "
                "(or `abandon`)"
            )
        return "fetch"
    if stage == STAGE_FETCHED:
        return "prepare"
    if stage == STAGE_PREPARED:
        if (run_dir / TRIAGE_FILE).is_file():
            return "check, then leads"
        return (
            "write triage.json from triage_input.json (rules: references/taxonomy.md), then check"
        )
    if stage == STAGE_LEADS:
        if _nothing_to_summarize(run_dir):
            return "finalize (nothing to summarize)"
        if any(run_dir.glob("enriched-*.jsonl")):
            return "check, then finalize"
        return "write enriched-1.jsonl from enrich_input.json, then check"
    return f"unknown stage {stage!r}"


def _nothing_to_summarize(run_dir: Path) -> bool:
    path = run_dir / ENRICH_INPUT_FILE
    return path.is_file() and not read_json(path)["items"]


def cmd_status(args: argparse.Namespace) -> int:
    if args.run:
        run_dir, run = open_run(args.run)
        say(
            f"run {run['run_id']}: kind={run['kind']} status={run['status']} "
            f"stage={run.get('stage')}"
        )
        say(f"next: {next_step(run_dir, run)}")
        return 0
    pool = Pool(resolve_pool(args.pool))
    say(f"pool: {pool.root}")
    if not (pool.profile_dir / PROFILE_CONFIG).is_file():
        say("profile: missing")
        say(f"next: {init_hint()}")
        return 0
    settings = load_settings(pool.profile_dir)
    say(f"profile: {settings['name']}: {settings['interests']}")
    runs = pool.runs()
    cov = coverage([run for _, run in runs])
    if cov:
        say(
            "covered until: "
            + ", ".join(f"{sid} {t.isoformat()}" for sid, t in sorted(cov.items()))
        )
    finalized = [(d, r) for d, r in runs if r.get("status") == STATUS_FINALIZED]
    if finalized:
        last_dir, last = finalized[-1]
        manifest = last_dir / MANIFEST_FILE
        count = read_json(manifest)["stats"]["items"] if manifest.is_file() else "?"
        say(f"last finalized run: {last['run_id']} ({last['kind']}, {count} items)")
    else:
        say("no finalized runs yet")
    now = clock.now(parse_tz(settings["tz"]))
    limit = float(settings["resume_hours"])
    for run_dir, run in runs:
        if run.get("status") != STATUS_STARTED:
            continue
        age = (now - from_iso(run["created_at"])).total_seconds() / 3600
        label = (
            "resumable"
            if age <= limit
            else f"stale (older than {limit:g}h: leave it or abandon it)"
        )
        say(f"unfinished: {run_dir} stage={run.get('stage')} age={age:.1f}h {label}")
        say(f"  next: {next_step(run_dir, run)}")
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    run_dir, run = open_run(args.run)
    if run.get("status") == STATUS_FINALIZED:
        raise UsageError(f"run {run['run_id']} is finalized; it cannot be abandoned")
    run["status"] = STATUS_ABANDONED
    save_run(run_dir, run)
    say(f"run {run['run_id']} abandoned; it no longer counts and is no longer listed")
    return 0
