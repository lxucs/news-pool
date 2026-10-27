"""prepare：规范化候选，丢掉没有正文的（检索源除外），按各来源的时间窗过滤，在运行内去重并对照
新闻池去重。"""

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
from .paths import viewer_hint
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
from .selection import KIND_FEED, KIND_SEARCH

RECORDS_FILE = "records.json"
TRIAGE_INPUT_FILE = "triage_input.json"
STAT_KEYS = (
    "candidates", "unreadable", "incomplete", "no_time", "no_text", "out_of_window",
    "duplicate", "already_seen", "over_cap", "new",
)  # fmt: skip

# 候选文件可能来自 adapter、links 或 agent；常见的字段名都接受。
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
    raw: dict[str, Any], source_id: str, tz: tzinfo, snippet_max: int, require_text: bool = True
) -> tuple[dict[str, Any] | None, str]:
    url = str(_pick(raw, URL_KEYS) or "").strip()
    title = strip_html(str(_pick(raw, TITLE_KEYS) or ""))
    if not url or not title:
        return None, "incomplete"
    published = parse_time(_pick(raw, TIME_KEYS), tz)
    if published is None:  # 发布时间未知时绝不猜测
        return None, "no_time"
    snippet = strip_html(str(_pick(raw, SNIPPET_KEYS) or ""))[:snippet_max]
    if require_text and not snippet:  # 没有正文就写不出摘要，不必交给 agent
        return None, "no_text"
    canonical = canonicalize_url(url)
    domain = domain_of(canonical)
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
    """同一件事的标题：一个标题的连续 token 序列包含另一个的（标题加上修饰语）。只差
    一个 token 的（M5 与 M6）会打断连续序列，仍算作不同的标题。"""
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
    # 检索式来源的条目本来就没有正文，仍交给 triage；没有正文的事件到 `leads` 再丢。
    search_ids = {sid for sid, info in run["sources"].items() if info.get("kind") == KIND_SEARCH}
    stats: dict[str, int] = dict.fromkeys(STAT_KEYS, 0)

    valid: list[dict[str, Any]] = []
    for path in sorted((run_dir / CANDIDATES_DIR).glob("*.jsonl")):
        source_id = path.stem
        if source_id == MANUAL_SOURCE:  # agent 写的文件：坏行要改好，不跳过
            rows = _read_manual(path, int(settings["output"]["max_problems"]))
        else:
            rows, unreadable = read_jsonl_loose(path)
            stats["unreadable"] += unreadable
            if unreadable:
                warn(f"{path.name}: {unreadable} unreadable line(s) skipped")
        for raw in rows:
            stats["candidates"] += 1
            rec, reason = normalize_candidate(
                raw,
                source_id,
                tz,
                int(settings["snippet_max_chars"]),
                require_text=source_id not in search_ids,
            )
            if rec is None:
                stats[reason] += 1
                continue
            if source_id != LINKS_SOURCE:  # links 是明确交来的链接：不受时间窗限制
                start, end = windows.get(source_id, overall)
                if not start <= from_iso(rec["published_at"]) < end:
                    stats["out_of_window"] += 1
                    continue
            rec["tier"] = resolve_tier(rec["source_domain"], rec["source_name"], tiers)
            valid.append(rec)

    # 最权威的排前面，同样权威时最早的排前面，去重时就保留这一份。
    valid.sort(key=lambda r: (r["tier"], r["published_at"]))
    seen = seen_ids(pool_of(run_dir), run["kind"])
    # 用 .get 兼容：2.1 之前的 run.json 快照里没有这个键；4 是内置默认值。
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
        f"{stats['no_time']} without a publish time, {stats['no_text']} without text, "
        f"{stats['incomplete']} without URL/title, {stats['over_cap']} over the cap"
    )
    if not fresh:
        finalized_at = clock.now(tz).isoformat()
        stats_out = {"candidates": stats["candidates"], "new": 0, "events": 0}
        commit_run(
            pool_of(run_dir), run_dir, run, [], build_manifest(run, [], stats_out, finalized_at), []
        )
        say("no new candidates; the run is finalized with an empty digest")
        say(f"run: {run_dir}")
        say(viewer_hint(None))
        return 0
    say(f"triage input: {run_dir / TRIAGE_INPUT_FILE}")
    say(f"next: write triage.json (rules: references/taxonomy.md), then check --run {run_dir}")
    return 0


def _read_manual(path: Path, max_problems: int) -> list[dict[str, Any]]:
    """candidates/manual.jsonl 的各行；只要有一行不是单个 JSON 对象，`prepare` 就失败。"""
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
    """订阅源只提供最新的若干条；这些条目覆盖不到时间窗起点时，中间发布的内容就丢了。
    取满了 per_source_limit 条的来源不提示：那是 profile 有意设的上限。"""
    out: list[str] = []
    fetch = run.get("fetch") or {}
    limit = int(run["settings"]["per_source_limit"])
    for sid, info in run["sources"].items():
        result = fetch.get(sid) or {}
        if info.get("kind") != KIND_FEED or not result.get("ok") or not result.get("oldest"):
            continue
        if int(result.get("fetched", 0)) >= limit:
            continue
        if from_iso(result["oldest"]) > from_iso(info["start"]):
            out.append(
                f"{sid}: its oldest entry ({result['oldest']}) is newer than the window start "
                f"({info['start']}); the feed only exposes its latest entries, so earlier items "
                "were missed"
            )
    return out
