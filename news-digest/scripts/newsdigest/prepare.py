"""prepare: normalize candidates, apply each source's window, dedup in-run and against the pool."""

from __future__ import annotations

import argparse
from datetime import tzinfo
from pathlib import Path
from typing import Any

from . import clock
from .config import CATEGORIES_FILE, TIERS_FILE, load_categories, load_tiers
from .console import error, say, warn
from .errors import ValidationFailed
from .fetch import CANDIDATES_DIR, LINKS_SOURCE, MANUAL_SOURCE
from .files import load_agent_jsonl, read_jsonl_loose, write_json_atomic
from .normalize import (
    canonicalize_url,
    contains_run,
    detect_lang,
    domain_of,
    from_iso,
    normalize_title,
    parse_time,
    parse_tz,
    strip_html,
    title_tokens,
    url_id,
)
from .pool import (
    STAGE_FETCHED,
    STAGE_PREPARED,
    build_manifest,
    commit_run,
    open_run,
    pool_of,
    require_open,
    require_stage,
    save_run,
    seen_ids,
)
from .selection import KIND_FEED

RECORDS_FILE = "records.json"
TRIAGE_INPUT_FILE = "triage_input.json"
STAT_KEYS = (
    "candidates", "unreadable", "incomplete", "no_time", "out_of_window",
    "duplicate", "already_seen", "over_cap", "new",
)  # fmt: skip

# Candidate files come from adapters, links, or an agent; accept the usual field names.
URL_KEYS = ("url", "link", "source_url", "canonical_url", "href")
TITLE_KEYS = ("title", "headline", "name", "subject")
TIME_KEYS = (
    "published_at", "published", "publish_time", "pubDate", "timestamp",
    "date", "time", "created_at", "datetime",
)  # fmt: skip
SNIPPET_KEYS = ("snippet", "summary", "description", "excerpt", "abstract", "lead", "text")
SOURCE_KEYS = ("source", "source_name", "site", "site_name", "publisher", "provider", "feed")
AUTHOR_KEYS = ("author", "byline", "writer")
IMAGE_KEYS = ("image", "image_url", "thumbnail", "cover", "og_image")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("prepare", help="normalize, window and dedup candidates; write triage input")
    p.add_argument("--run", required=True)
    p.set_defaults(handler=cmd_prepare)


def _pick(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_candidate(
    raw: dict[str, Any], source_id: str, tz: tzinfo, snippet_max: int
) -> tuple[dict[str, Any] | None, str]:
    url = str(_pick(raw, URL_KEYS) or "").strip()
    title = strip_html(str(_pick(raw, TITLE_KEYS) or ""))
    if not url or not title:
        return None, "incomplete"
    published = parse_time(_pick(raw, TIME_KEYS), tz)
    if published is None:  # an unknown publish time is never guessed
        return None, "no_time"
    canonical = canonicalize_url(url)
    domain = domain_of(canonical)
    snippet = strip_html(str(_pick(raw, SNIPPET_KEYS) or ""))[:snippet_max]
    record = {
        "id": url_id(canonical),
        "url": url,
        "canonical_url": canonical,
        "title": title,
        "source_id": source_id,
        "source_name": str(_pick(raw, SOURCE_KEYS) or domain),
        "source_domain": domain,
        "author": str(_pick(raw, AUTHOR_KEYS) or ""),
        "published_at": published.astimezone(tz).isoformat(),
        "snippet": snippet,
        "image": str(_pick(raw, IMAGE_KEYS) or ""),
        "lang": detect_lang(f"{title} {snippet}"),
    }
    return record, ""


def resolve_tier(domain: str, source_name: str, tiers: dict[str, Any]) -> int:
    best_key, best_tier = "", None
    for key, tier in (tiers.get("by_domain") or {}).items():
        if (domain == key or domain.endswith("." + key)) and len(key) > len(best_key):
            best_key, best_tier = key, tier
    if best_tier is not None:
        return int(best_tier)
    by_name = tiers.get("by_name") or {}
    if source_name in by_name:
        return int(by_name[source_name])
    return int(tiers["default"])


def _title_duplicate(
    tokens: tuple[str, ...], kept_runs: list[tuple[str, ...]], min_tokens: int
) -> bool:
    """Same-story headlines: one title's token run contains the other's (a headline
    plus a qualifier). Single-token differences (M5 vs M6) break the run and stay separate."""
    if len(tokens) < min_tokens:
        return False
    return any(
        len(run) >= min_tokens and (contains_run(run, tokens) or contains_run(tokens, run))
        for run in kept_runs
    )


def cmd_prepare(args: argparse.Namespace) -> int:
    run_dir, run = open_run(args.run)
    require_open(run)
    require_stage(run, STAGE_FETCHED, "run `fetch` first")
    settings = run["settings"]
    tz = parse_tz(settings["tz"])
    tiers = load_tiers(Path(run["resources"][TIERS_FILE]))
    windows = {sid: (from_iso(i["start"]), from_iso(i["end"])) for sid, i in run["sources"].items()}
    overall = (from_iso(run["window"]["start"]), from_iso(run["window"]["end"]))
    stats: dict[str, int] = dict.fromkeys(STAT_KEYS, 0)

    valid: list[dict[str, Any]] = []
    for path in sorted((run_dir / CANDIDATES_DIR).glob("*.jsonl")):
        source_id = path.stem
        if source_id == MANUAL_SOURCE:  # written by the agent: a bad line is fixed, not skipped
            rows = _read_manual(path, int(settings["output"]["max_problems"]))
        else:
            rows, unreadable = read_jsonl_loose(path)
            stats["unreadable"] += unreadable
            if unreadable:
                warn(f"{path.name}: {unreadable} unreadable line(s) skipped")
        for raw in rows:
            stats["candidates"] += 1
            rec, reason = normalize_candidate(
                raw, source_id, tz, int(settings["snippet_max_chars"])
            )
            if rec is None:
                stats[reason] += 1
                continue
            if source_id != LINKS_SOURCE:  # links were handed over explicitly: no window
                start, end = windows.get(source_id, overall)
                if not start <= from_iso(rec["published_at"]) < end:
                    stats["out_of_window"] += 1
                    continue
            rec["tier"] = resolve_tier(rec["source_domain"], rec["source_name"], tiers)
            valid.append(rec)

    # Most authoritative, then earliest, copy first, so dedup keeps that one.
    valid.sort(key=lambda r: (r["tier"], r["published_at"]))
    seen = seen_ids(pool_of(run_dir), run["kind"])
    # The .get shim: a run.json snapshot from before 2.1 lacks the key; 4 is the built-in default.
    min_dup_tokens = int(settings.get("title_dup_min_tokens", 4))
    fresh: list[dict[str, Any]] = []
    ids: set[str] = set()
    titles: set[str] = set()
    kept_runs: list[tuple[str, ...]] = []
    for rec in valid:
        title_key = normalize_title(rec["title"])
        tokens = title_tokens(rec["title"])
        if (
            rec["id"] in ids
            or (title_key and title_key in titles)
            or _title_duplicate(tokens, kept_runs, min_dup_tokens)
        ):
            stats["duplicate"] += 1
            continue
        ids.add(rec["id"])
        if title_key:
            titles.add(title_key)
        if tokens:
            kept_runs.append(tokens)
        if rec["id"] in seen:
            stats["already_seen"] += 1
            continue
        fresh.append(rec)

    fresh.sort(key=lambda r: from_iso(r["published_at"]), reverse=True)
    cap = int(settings["max_candidates"])
    stats["over_cap"] = max(0, len(fresh) - cap)
    fresh = fresh[:cap]
    stats["new"] = len(fresh)
    over_cap_warning = (
        [
            f"{stats['over_cap']} candidates over max_candidates were not triaged; "
            "raise max_candidates or run more often"
        ]
        if stats["over_cap"]
        else []
    )

    write_json_atomic(run_dir / RECORDS_FILE, fresh)
    write_json_atomic(run_dir / TRIAGE_INPUT_FILE, _triage_input(run, fresh))
    run["stats"] = stats
    run["warnings"] = _truncation_warnings(run) + over_cap_warning
    run["stage"] = STAGE_PREPARED
    save_run(run_dir, run)
    for message in run["warnings"]:
        warn(message)
    say(
        f"{stats['candidates']} candidates: {stats['new']} new, {stats['duplicate']} duplicates, "
        f"{stats['already_seen']} already seen, {stats['out_of_window']} outside the window, "
        f"{stats['no_time']} without a publish time, {stats['incomplete']} without URL/title, "
        f"{stats['over_cap']} over the cap"
    )
    if not fresh:
        finalized_at = clock.now(tz).isoformat()
        stats_out = {"candidates": stats["candidates"], "new": 0, "events": 0}
        commit_run(
            pool_of(run_dir), run_dir, run, [], build_manifest(run, [], stats_out, finalized_at), []
        )
        say("no new candidates; the run is finalized with an empty digest")
        return 0
    say(f"triage input: {run_dir / TRIAGE_INPUT_FILE}")
    say(f"next: write triage.json (rules: references/taxonomy.md), then check --run {run_dir}")
    return 0


def _read_manual(path: Path, max_problems: int) -> list[dict[str, Any]]:
    """Rows of candidates/manual.jsonl; any line that is not one JSON object fails `prepare`."""
    parsed, json_problems = load_agent_jsonl(path)
    problems = [
        f"{p.file}:{p.line}:{p.col}: invalid JSON ({p.message}): {p.text}" for p in json_problems
    ]
    rows: list[dict[str, Any]] = []
    for lineno, obj in parsed:
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            problems.append(f"{path.name}:{lineno}: each line must be one JSON object")
    if problems:
        for message in problems[:max_problems]:
            error(message)
        if len(problems) > max_problems:
            error(f"... and {len(problems) - max_problems} more")
        raise ValidationFailed(
            f"{CANDIDATES_DIR}/{path.name} has {len(problems)} unreadable line(s); write one "
            "JSON object per line, then run `prepare` again"
        )
    return rows


def _triage_input(run: dict[str, Any], fresh: list[dict[str, Any]]) -> dict[str, Any]:
    settings = run["settings"]
    n = int(settings["triage_snippet_chars"])
    return {
        "run_id": run["run_id"],
        "kind": run["kind"],
        "criterion": run["criterion"],
        "min_importance": settings["min_importance"],
        "categories": load_categories(Path(run["resources"][CATEGORIES_FILE])),
        "count": len(fresh),
        "items": [
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source_name"],
                "tier": r["tier"],
                "lang": r["lang"],
                "published_at": r["published_at"],
                "snippet": r["snippet"][:n],
            }
            for r in fresh
        ],
    }


def _truncation_warnings(run: dict[str, Any]) -> list[str]:
    """A feed exposes only its latest entries; if they don't reach back to the window start,
    whatever was published in between is lost."""
    out: list[str] = []
    fetch = run.get("fetch") or {}
    for sid, info in run["sources"].items():
        result = fetch.get(sid) or {}
        if info.get("kind") != KIND_FEED or not result.get("ok") or not result.get("oldest"):
            continue
        if from_iso(result["oldest"]) > from_iso(info["start"]):
            out.append(
                f"{sid}: its oldest entry ({result['oldest']}) is newer than the window start "
                f"({info['start']}); the feed only exposes its latest entries, so earlier items "
                "were missed"
            )
    return out
