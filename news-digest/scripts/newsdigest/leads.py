"""leads: a page description for kept primaries with little text; writes enrich_input.json."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import tzinfo
from typing import Any

from .adapters import parse_article_page
from .console import say
from .files import write_json_atomic
from .net import FetchError, http_get
from .normalize import domain_of, parse_tz
from .pool import STAGE_LEADS, require_open, save_run
from .validate import ENRICH_INPUT_FILE, load_context, require_valid_triage

LEADS_FILE = "leads.json"
GOOGLE_NEWS_HOST = "news.google.com"


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "leads", help="fetch descriptions for thin primaries; write enrich_input.json"
    )
    p.add_argument("--run", required=True)
    p.add_argument("--no-fetch", action="store_true", help="skip the network; use snippets only")
    p.set_defaults(handler=cmd_leads)


def cmd_leads(args: argparse.Namespace) -> int:
    ctx = load_context(args.run)
    require_open(ctx.run)
    triage = require_valid_triage(ctx)  # no tokens get spent enriching a bad triage
    settings = ctx.run["settings"]
    cfg = settings["leads"]
    tz = parse_tz(settings["tz"])
    kept = sorted(triage.kept(ctx.min_importance), key=lambda e: -e["importance"])
    thin = [
        ctx.records[e["primary"]]
        for e in kept
        if len(ctx.records[e["primary"]]["snippet"]) < int(cfg["min_snippet_chars"])
    ][: int(cfg["max"])]

    found: dict[str, dict[str, str]] = {}
    if thin and not args.no_fetch:
        with ThreadPoolExecutor(max_workers=int(cfg["workers"])) as executor:
            for rid, lead in executor.map(lambda rec: _lead(rec, settings, tz), thin):
                if lead["lead"] or lead["resolved_url"]:
                    found[rid] = lead
    write_json_atomic(ctx.run_dir / LEADS_FILE, found)

    items = []
    for event in kept:
        rec = ctx.records[event["primary"]]
        items.append(
            {
                "id": rec["id"],
                "title": rec["title"],
                "source": rec["source_name"],
                "lang": rec["lang"],
                "title_zh_required": rec["lang"] != "zh",
                "published_at": rec["published_at"],
                "category": event["category"],
                "text": found.get(rec["id"], {}).get("lead") or rec["snippet"],
                "related_titles": [
                    ctx.records[m]["title"] for m in event["members"] if m != event["primary"]
                ],
            }
        )
    write_json_atomic(
        ctx.run_dir / ENRICH_INPUT_FILE,
        {"run_id": ctx.run["run_id"], "count": len(items), "items": items},
    )
    ctx.run["stage"] = STAGE_LEADS
    save_run(ctx.run_dir, ctx.run)
    fetched = "skipped (--no-fetch)" if args.no_fetch else f"{len(found)} of {len(thin)} found"
    say(f"{len(items)} kept primaries; descriptions for thin ones: {fetched}")
    say(f"enrich input: {ctx.run_dir / ENRICH_INPUT_FILE}")
    if items:
        say("next: write enriched-1.jsonl (then -2, -3 … per batch), then check")
    else:
        say(f"nothing was kept, so there is nothing to enrich; next: finalize --run {ctx.run_dir}")
    return 0


def _lead(
    record: dict[str, Any], settings: dict[str, Any], tz: tzinfo
) -> tuple[str, dict[str, str]]:
    nothing = {"lead": "", "resolved_url": ""}
    http = settings["http"]
    try:
        resp = http_get(record["url"], http, user_agent=http["article_user_agent"])
    except FetchError:
        return record["id"], nothing
    if domain_of(resp.url) == GOOGLE_NEWS_HOST:  # still on Google's redirect page
        return record["id"], nothing
    page = parse_article_page(resp.text, resp.url, tz)
    resolved = resp.url if domain_of(record["url"]) == GOOGLE_NEWS_HOST else ""
    return record["id"], {"lead": page["snippet"], "resolved_url": resolved}
