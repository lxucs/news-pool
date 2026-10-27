"""leads：为文本太少的保留 primary 抓取页面描述；写出 enrich_input.json。
抓了也没有正文的事件记进 enrich_input.json 的 `no_text`，不写摘要、不落盘。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import tzinfo
from typing import Any

from .adapters import parse_article_page
from .console import say
from .files import write_json_atomic
from .net import FetchError, http_get
from .normalize import is_google_news, parse_tz
from .pool import STAGE_LEADS, require_open, save_run
from .validate import ENRICH_INPUT_FILE, NO_TEXT_KEY, load_context, require_valid_triage

LEADS_FILE = "leads.json"


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
    triage = require_valid_triage(ctx)  # 免得在有错的 triage 上白花 token 写摘要
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
    no_text: list[str] = []
    for event in kept:
        rec = ctx.records[event["primary"]]
        text = found.get(rec["id"], {}).get("lead") or rec["snippet"]
        if not text:  # 抓了页面也没有正文：写不出摘要，这个事件不落盘
            no_text.append(rec["id"])
            continue
        items.append(
            {
                "id": rec["id"],
                "title": rec["title"],
                "source": rec["source_name"],
                "lang": rec["lang"],
                "title_zh_required": rec["lang"] != "zh",
                "published_at": rec["published_at"],
                "category": event["category"],
                "text": text,
                "related_titles": [
                    ctx.records[m]["title"] for m in event["members"] if m != event["primary"]
                ],
            }
        )
    write_json_atomic(
        ctx.run_dir / ENRICH_INPUT_FILE,
        {"run_id": ctx.run["run_id"], "count": len(items), "items": items, NO_TEXT_KEY: no_text},
    )
    ctx.run["stage"] = STAGE_LEADS
    save_run(ctx.run_dir, ctx.run)
    fetched = "skipped (--no-fetch)" if args.no_fetch else f"{len(found)} of {len(thin)} found"
    say(f"{len(items)} primaries to summarize; descriptions for thin ones: {fetched}")
    if no_text:
        say(f"{len(no_text)} kept events still have no text; they are dropped, no summary needed")
    say(f"enrich input: {ctx.run_dir / ENRICH_INPUT_FILE}")
    if items:
        say("next: write enriched-1.jsonl (then -2, -3 … per batch), then check")
    else:
        say(f"nothing to summarize; next: finalize --run {ctx.run_dir}")
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
    if is_google_news(resp.url):  # 还停在 Google 的跳转页上
        return record["id"], nothing
    page = parse_article_page(resp.text, resp.url, tz)
    resolved = resp.url if is_google_news(record["url"]) else ""
    return record["id"], {"lead": page["snippet"], "resolved_url": resolved}
