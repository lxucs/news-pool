"""finalize：全部校验一遍，再提交条目、manifest 和 seen.txt（见 pool.commit_run）。"""

from __future__ import annotations

import argparse
from typing import Any

from . import SCHEMA_VERSION, clock
from .console import say, warn
from .files import read_json
from .leads import LEADS_FILE
from .normalize import domain_of, parse_tz
from .paths import viewer_hint
from .pool import (
    KIND_DAILY,
    MANIFEST_FILE,
    SEEN_DROPPED,
    SEEN_KEPT,
    STAGE_LEADS,
    STATUS_FINALIZED,
    build_manifest,
    commit_run,
    pool_of,
    require_open,
    require_stage,
)
from .validate import (
    FLAG_KEYS,
    RunContext,
    clear_problems,
    load_context,
    require_valid_enriched,
    require_valid_triage,
    summarized_events,
)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("finalize", help="validate, then write items, manifest and seen.txt")
    p.add_argument("--run", required=True)
    p.set_defaults(handler=cmd_finalize)


def cmd_finalize(args: argparse.Namespace) -> int:
    ctx = load_context(args.run)
    run = ctx.run
    if run.get("status") == STATUS_FINALIZED:
        say(f"run {run['run_id']} is already finalized; nothing to do")
        return 0
    require_open(run)
    require_stage(run, STAGE_LEADS, "run `leads` first")
    triage = require_valid_triage(ctx)
    enriched = require_valid_enriched(ctx, triage)
    clear_problems(ctx)
    leads_path = ctx.run_dir / LEADS_FILE
    leads = read_json(leads_path) if leads_path.is_file() else {}

    kept = summarized_events(ctx, triage)
    items = [
        build_item(ctx, e, enriched.rows[e["primary"]], leads.get(e["primary"], {})) for e in kept
    ]
    kept_ids = {m for e in kept for m in e["members"]}
    seen = [(rid, SEEN_KEPT) for rid in ctx.input_ids if rid in kept_ids]
    if run["kind"] == KIND_DAILY:  # 临时运行丢弃的条目，之后的每日运行仍可以收录
        seen += [(rid, SEEN_DROPPED) for rid in ctx.input_ids if rid not in kept_ids]
    stats = {
        "candidates": run["stats"]["candidates"],
        "new": len(ctx.input_ids),
        "events": len(triage.events),
    }
    finalized_at = clock.now(parse_tz(run["settings"]["tz"])).isoformat()
    manifest = build_manifest(run, items, stats, finalized_at)
    commit_run(pool_of(ctx.run_dir), ctx.run_dir, run, items, manifest, seen)
    _report(ctx, manifest)
    return 0


def build_item(
    ctx: RunContext, event: dict[str, Any], enr: dict[str, Any], lead: dict[str, Any]
) -> dict[str, Any]:
    run = ctx.run
    rec = ctx.records[event["primary"]]
    resolved = str(lead.get("resolved_url") or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": rec["id"],
        "run_id": run["run_id"],
        "run_kind": run["kind"],
        "profile": run["profile"],
        "title": rec["title"],
        "title_zh": enr["title_zh"] or rec["title"],
        "language": rec["lang"],
        "summary": enr["summary"],
        "synopsis": enr["synopsis"],
        "key_points": enr["key_points"],
        "why_it_matters": enr["why_it_matters"],
        "category": event["category"],
        "tags": enr["tags"],
        "region": enr["region"],
        "entities": enr["entities"],
        "source": {
            "id": rec["source_id"],
            "name": rec["source_name"],
            "domain": domain_of(resolved) if resolved else rec["source_domain"],
            "url": resolved or rec["url"],
            "author": rec["author"],
            "tier": rec["tier"],
        },
        "published_at": rec["published_at"],
        "collected_at": run["created_at"],
        "cover_image": {"url": rec["image"]},
        "metrics": {
            "importance": event["importance"],
            "novelty": event["novelty"],
            "sentiment": event["sentiment"],
        },
        "flags": {key: event[key] for key in FLAG_KEYS},
        "related": [
            {
                "id": other["id"],
                "title": other["title"],
                "source_name": other["source_name"],
                "url": other["url"],
                "published_at": other["published_at"],
                "language": other["lang"],
            }
            for other in (ctx.records[m] for m in event["members"] if m != event["primary"])
        ],
        "llm": {
            "model": run.get("model", ""),
            "skill_version": run.get("skill_version", ""),
            "confidence": enr["confidence"],
        },
    }


def _report(ctx: RunContext, manifest: dict[str, Any]) -> None:
    stats = manifest["stats"]
    top = int(ctx.run["settings"]["output"]["report_top"])
    say(
        f"finalized {manifest['run_id']} ({manifest['kind']}): {stats['items']} items from "
        f"{stats['events']} events; {stats['new']} new of {stats['candidates']} candidates"
    )
    if stats["by_category"]:
        say("by category: " + ", ".join(f"{k} {v}" for k, v in stats["by_category"].items()))
    for entry in manifest["items"][:top]:
        say(f"  #{entry['rank']} [{entry['importance']:.2f}] {entry['title_zh']} — {entry['url']}")
    failed = [
        f"{sid} ({info.get('error') or 'failed'})"
        for sid, info in manifest["sources"].items()
        if not info.get("ok")
    ]
    if failed:
        warn("sources that failed (their window is retried next run): " + "; ".join(failed))
    for message in manifest["warnings"]:
        warn(message)
    say(f"manifest: {ctx.run_dir / MANIFEST_FILE}")
    say(f"run: {ctx.run_dir}")
    say(viewer_hint(manifest["run_id"] if stats["items"] else None))
