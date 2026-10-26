"""fetch：每个选中的来源按各自的时间窗抓取；需要时再抓手动给出的链接。"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .adapters import (
    ParseError,
    is_captcha_page,
    parse_article_page,
    parse_feed,
    parse_gdelt,
    parse_gnews,
    parse_hn,
    parse_wscn,
)
from .console import say, warn
from .errors import AllSourcesFailed, UsageError
from .files import write_jsonl_atomic
from .net import FetchError, http_get
from .normalize import from_iso, parse_time, parse_tz, strip_html
from .pool import STAGE_FETCHED, open_run, require_open, save_run

CANDIDATES_DIR = "candidates"
LINKS_SOURCE = "links"
MANUAL_SOURCE = "manual"

# 各接口地址及文档规定的上限（协议常量，不是可调参数）。
GNEWS_URL = "https://news.google.com/rss/search"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WSCN_URL = "https://api-one.wallstcn.com/apiv1/content/articles"
WSCN_MAX_LIMIT = 35  # 2026-10-26 实测：limit 超过 35 时 `data` 返回空字符串
HN_MAX_HITS = 1000
GDELT_MAX_RECORDS = 250
GDELT_MIN_MINUTES = 15
GNEWS_WHEN = ((1, "1h"), (12, "12h"), (24, "1d"))  # 更长的时间窗用 "7d"，即它支持的最大值
SEARCH_PARSERS = {"gnews": parse_gnews, "hn": parse_hn, "gdelt": parse_gdelt}


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("fetch", help="fetch every selected source over its window")
    p.add_argument("--run", required=True)
    p.add_argument("--links", help="file of article URLs to add, one per line")
    p.set_defaults(handler=cmd_fetch)


def cmd_fetch(args: argparse.Namespace) -> int:
    run_dir, run = open_run(args.run)
    require_open(run)
    settings = run["settings"]
    tz = parse_tz(settings["tz"])
    cand_dir = run_dir / CANDIDATES_DIR
    results: dict[str, dict[str, Any]] = {}
    for sid, info in run["sources"].items():
        rows, errors, no_text = _fetch_source(info, run["queries"], settings)
        write_jsonl_atomic(cand_dir / f"{sid}.jsonl", rows)
        results[sid] = {
            "ok": not errors,
            "fetched": len(rows),
            "error": "; ".join(errors),
            "oldest": _oldest(rows, tz),
        }
        say(
            f"{sid}: {len(rows)} candidates"
            + (f" ({no_text} without text skipped)" if no_text else "")
            + (f"; FAILED: {'; '.join(errors)}" if errors else "")
        )
    linked = 0
    if args.links:
        linked = _fetch_links(Path(args.links).expanduser(), cand_dir, settings, tz)
        say(f"links: {linked} candidates")
    run["fetch"] = results
    # 某个来源部分 query 失败但仍返回了候选行，不算彻底失败；links 产出了候选的运行也不算。
    if results and not linked and not any(r["ok"] or r["fetched"] for r in results.values()):
        save_run(run_dir, run)
        raise AllSourcesFailed(
            "every selected source failed (reasons above and in run.json); this usually means "
            "no network access, which sandboxed harnesses often block"
        )
    run["stage"] = STAGE_FETCHED
    save_run(run_dir, run)
    failed = [sid for sid, r in results.items() if not r["ok"]]
    if failed:
        warn(f"failed sources keep their window for the next run: {', '.join(failed)}")
    say(f"next: prepare --run {run_dir}")
    return 0


def _fetch_source(
    info: dict[str, Any], queries: list[str], settings: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], int]:
    """(候选行, 错误, 跳过的没有正文的行数)。订阅式来源先丢掉没有正文的行，再取
    per_source_limit 条；检索式来源的条目本来就没有正文，原样交给 triage。"""
    adapter = info["adapter"]
    try:
        if adapter == "rss":
            _, rows = parse_feed(http_get(info["url"], settings["http"]).text)
            rows = [dict(row, source=info["name"]) for row in rows]
        elif adapter == "wscn":
            # 总是要接口允许的最多条数：丢掉没有正文的之后，剩下的还要够 per_source_limit 条。
            url = f"{WSCN_URL}?{urlencode({'limit': WSCN_MAX_LIMIT})}"
            rows = parse_wscn(http_get(url, settings["http"]).text)
        else:
            rows, errors = _search(adapter, info, queries, settings)
            return rows, errors, 0
    except (FetchError, ParseError) as exc:
        return [], [str(exc)], 0
    kept, no_text = _with_text(rows, int(settings["per_source_limit"]))
    return kept, [], no_text


def _with_text(rows: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    """按原顺序（最新的在前）取前 limit 条有正文的行；返回它们和途中跳过的行数。"""
    kept: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if len(kept) == limit:
            break
        if strip_html(str(row.get("snippet") or "")):
            kept.append(row)
        else:
            skipped += 1
    return kept, skipped


def _search(
    adapter: str, info: dict[str, Any], queries: list[str], settings: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    start, end = from_iso(info["start"]), from_iso(info["end"])
    limit = int(settings["per_source_limit"])
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for i, query in enumerate(queries):
        if adapter == "gdelt" and i:
            time.sleep(float(settings["gdelt"]["min_interval_s"]))
        try:
            text = http_get(
                search_url(adapter, query, start, end, limit, settings), settings["http"]
            ).text
            found = SEARCH_PARSERS[adapter](text)
        except (FetchError, ParseError) as exc:
            errors.append(f"{query!r}: {exc}")
            continue
        for row in found[:limit]:
            if row["url"] not in seen:
                seen.add(row["url"])
                rows.append(row)
    return rows, errors


def search_url(
    adapter: str, query: str, start: datetime, end: datetime, limit: int, settings: dict[str, Any]
) -> str:
    if adapter == "gnews":
        hours = (end - start).total_seconds() / 3600
        when = next((label for bound, label in GNEWS_WHEN if hours <= bound), "7d")
        g = settings["gnews"]
        params = {"q": f"{query} when:{when}", "hl": g["hl"], "gl": g["gl"], "ceid": g["ceid"]}
        return f"{GNEWS_URL}?{urlencode(params)}"
    if adapter == "hn":
        window = f"created_at_i>{int(start.timestamp())},created_at_i<{int(end.timestamp())}"
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": min(limit, HN_MAX_HITS),
            "numericFilters": window,
        }
        return f"{HN_URL}?{urlencode(params)}"
    if adapter == "gdelt":
        minutes = max(GDELT_MIN_MINUTES, int((end - start).total_seconds() // 60))
        timespan = f"{minutes // 60}h" if minutes >= 60 else f"{minutes}min"
        params = {
            "query": f'"{query}"' if " " in query else query,
            "mode": "ArtList",
            "format": "json",
            "timespan": timespan,
            "maxrecords": min(limit, GDELT_MAX_RECORDS),
            "sort": "DateDesc",
        }
        return f"{GDELT_URL}?{urlencode(params)}"
    raise UsageError(f"unknown search adapter {adapter!r}")


def _oldest(rows: list[dict[str, Any]], tz: tzinfo) -> str:
    times = [t for t in (parse_time(r.get("published_at"), tz) for r in rows) if t is not None]
    return min(times).isoformat() if times else ""


def _fetch_links(path: Path, cand_dir: Path, settings: dict[str, Any], tz: tzinfo) -> int:
    if not path.is_file():
        raise UsageError(f"--links file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    urls = [s.strip() for s in lines if s.strip() and not s.lstrip().startswith("#")]
    http = settings["http"]
    rows: list[dict[str, Any]] = []
    for url in urls:
        try:
            resp = http_get(url, http, user_agent=http["article_user_agent"])
        except FetchError as exc:
            warn(f"link skipped ({exc}): {url}")
            continue
        if is_captcha_page(resp.url, resp.text):
            warn(f"link blocked by a captcha page, skipped: {url}")
            continue
        page = parse_article_page(resp.text, resp.url, tz)
        if not page["title"]:
            warn(f"link skipped (no title found): {url}")
            continue
        if not page["snippet"]:
            warn(f"link skipped (no description found on the page): {url}")
            continue
        if not page["published_at"]:
            warn(f"link has no publish time; prepare will drop it: {url}")
        rows.append(page)
    write_jsonl_atomic(cand_dir / f"{LINKS_SOURCE}.jsonl", rows)
    return len(rows)
