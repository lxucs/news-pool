"""Validation of agent-written files (triage.json, enriched-*.jsonl) and the `check` command."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .config import CATEGORIES_FILE, TAGS_FILE, category_names, load_categories, load_tags
from .console import error, say, warn
from .errors import ValidationFailed
from .files import (
    AgentJsonError,
    JsonProblem,
    load_agent_json,
    load_agent_jsonl,
    read_json,
    write_json_atomic,
)
from .pool import STAGE_PREPARED, open_run, require_open, require_stage
from .prepare import RECORDS_FILE, TRIAGE_INPUT_FILE

TRIAGE_FILE = "triage.json"
ENRICH_INPUT_FILE = "enrich_input.json"
ERRORS_FILE = "errors.json"
ENRICHED_RE = re.compile(r"enriched-(\d+)\.jsonl")

# Schema rules (documented in references/schema.md and SKILL.md).
SENTIMENTS = ("positive", "neutral", "negative")
REGIONS = ("CN", "US", "EU", "JP", "GLOBAL")
FLAG_KEYS = ("is_breaking", "is_opinion", "needs_review")
ENTITY_KEYS = ("companies", "people", "products")
SUMMARY_MAX_CHARS = 60
KEY_POINTS = 3
MAX_TAGS = 10


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("check", help="validate triage.json / enriched-*.jsonl and say what's next")
    p.add_argument("--run", required=True)
    p.set_defaults(handler=cmd_check)


@dataclass(frozen=True)
class Problem:
    file: str
    line: int | None
    id: str
    field: str
    message: str

    def format(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        parts = [where] + [p for p in (self.id, self.field) if p]
        return f"{' '.join(parts)}: {self.message}"


def from_json_problem(p: JsonProblem) -> Problem:
    return Problem(p.file, p.line, "", f"col {p.col}", f"invalid JSON ({p.message}): {p.text}")


@dataclass
class RunContext:
    run_dir: Path
    run: dict[str, Any]
    records: dict[str, dict[str, Any]]
    input_ids: list[str]
    categories: list[str]
    min_importance: float
    vocab: set[str]
    max_problems: int


def load_context(run_arg: str) -> RunContext:
    run_dir, run = open_run(run_arg)
    require_stage(run, STAGE_PREPARED, "run `prepare` first")
    settings = run["settings"]
    triage_input = read_json(run_dir / TRIAGE_INPUT_FILE)
    return RunContext(
        run_dir=run_dir,
        run=run,
        records={r["id"]: r for r in read_json(run_dir / RECORDS_FILE)},
        input_ids=[item["id"] for item in triage_input["items"]],
        categories=category_names(load_categories(Path(run["resources"][CATEGORIES_FILE]))),
        min_importance=float(settings["min_importance"]),
        vocab=load_tags(Path(run["resources"][TAGS_FILE])),
        max_problems=int(settings["output"]["max_problems"]),
    )


@dataclass
class Triage:
    events: list[dict[str, Any]]
    drop: list[str]

    def kept(self, min_importance: float) -> list[dict[str, Any]]:
        return [e for e in self.events if e["importance"] >= min_importance]


def _is_unit(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_triage(ctx: RunContext) -> tuple[Triage | None, list[Problem]]:
    path = ctx.run_dir / TRIAGE_FILE
    if not path.is_file():
        return None, [
            Problem(TRIAGE_FILE, None, "", "", "missing; write it from triage_input.json")
        ]
    try:
        doc = load_agent_json(path)
    except AgentJsonError as exc:
        return None, [from_json_problem(exc.problem)]
    return check_triage(doc, ctx.input_ids, ctx.categories)


def check_triage(
    doc: Any, input_ids: list[str], categories: list[str]
) -> tuple[Triage | None, list[Problem]]:
    problems: list[Problem] = []

    def bad(rid: str, where: str, message: str) -> None:
        problems.append(Problem(TRIAGE_FILE, None, rid, where, message))

    if not isinstance(doc, dict):
        bad("", "", "the top level must be an object with `events` and `drop`")
        return None, problems
    raw_events = doc.get("events")
    if not isinstance(raw_events, list):
        bad("", "events", "must be a list")
        raw_events = []
    raw_drop = doc.get("drop", [])
    if not isinstance(raw_drop, list) or not all(isinstance(x, str) for x in raw_drop):
        bad("", "drop", "must be a list of ids")
        raw_drop = [x for x in raw_drop if isinstance(x, str)] if isinstance(raw_drop, list) else []
    counts: Counter[str] = Counter(raw_drop)
    events: list[dict[str, Any]] = []
    for i, ev in enumerate(raw_events):
        where = f"events[{i}]"
        if not isinstance(ev, dict):
            bad("", where, "must be an object")
            continue
        event, members = _check_event(ev, where, categories, bad)
        counts.update(members)
        if event is not None:
            events.append(event)
    known = set(input_ids)
    for rid, n in counts.items():
        if rid not in known:
            bad(rid, "", "unknown id (not in triage_input.json)")
        elif n > 1:
            bad(rid, "", f"appears {n} times; each id belongs to exactly one event or to drop")
    for rid in input_ids:
        if rid not in counts:
            bad(rid, "", "missing; put it in an event's members or in drop")
    return (Triage(events, list(raw_drop)) if not problems else None), problems


def _check_event(
    ev: dict[str, Any], where: str, categories: list[str], bad: Callable[[str, str, str], None]
) -> tuple[dict[str, Any] | None, list[str]]:
    ok = True
    members = ev.get("members")
    if not isinstance(members, list) or not members or not all(isinstance(m, str) for m in members):
        bad("", f"{where}.members", "must be a non-empty list of ids")
        ok = False
        members = [m for m in members if isinstance(m, str)] if isinstance(members, list) else []
    primary = ev.get("primary")
    pid = primary if isinstance(primary, str) else ""
    if not pid:
        bad("", f"{where}.primary", "must be an id")
        ok = False
    elif pid not in members:
        bad(pid, f"{where}.primary", "must be one of the event's members")
        ok = False
    category = ev.get("category")
    if category not in categories:
        expected = ", ".join(categories)
        bad(
            pid, f"{where}.category", f"{category!r} is not a category; expected one of: {expected}"
        )
        ok = False
    importance: Any = ev.get("importance")
    novelty: Any = ev.get("novelty", 0.0)
    for name, value in (("importance", importance), ("novelty", novelty)):
        if not _is_unit(value):
            bad(pid, f"{where}.{name}", "must be a number from 0 to 1")
            ok = False
    sentiment = ev.get("sentiment", "neutral")
    if sentiment not in SENTIMENTS:
        bad(pid, f"{where}.sentiment", f"expected one of: {', '.join(SENTIMENTS)}")
        ok = False
    flags: dict[str, bool] = {}
    for key in FLAG_KEYS:
        value = ev.get(key, False)
        if not isinstance(value, bool):
            bad(pid, f"{where}.{key}", "must be true or false")
            ok = False
        flags[key] = value is True
    if not ok:
        return None, members
    event = {
        "primary": pid,
        "members": list(dict.fromkeys(members)),
        "category": category,
        "importance": float(importance),
        "novelty": float(novelty),
        "sentiment": sentiment,
        **flags,
    }
    return event, members


@dataclass
class Enriched:
    rows: dict[str, dict[str, Any]]
    warnings: list[str]


def kept_primaries(ctx: RunContext, triage: Triage) -> dict[str, str]:
    """Kept primary id → its language (an English item needs `title_zh`)."""
    return {
        e["primary"]: ctx.records[e["primary"]]["lang"] for e in triage.kept(ctx.min_importance)
    }


def load_enriched(ctx: RunContext, primaries: dict[str, str]) -> tuple[Enriched, list[Problem]]:
    problems: list[Problem] = []
    warnings: list[str] = []
    numbered: list[tuple[int, Path]] = []
    for path in sorted(ctx.run_dir.glob("enriched-*.jsonl")):
        m = ENRICHED_RE.fullmatch(path.name)
        if m is None:
            warnings.append(f"{path.name}: ignored; corrections go in enriched-<n>.jsonl")
            continue
        numbered.append((int(m.group(1)), path))
    numbered.sort()
    if not numbered:
        if not primaries:  # nothing was kept: there is nothing to enrich
            return Enriched({}, warnings), []
        missing = Problem(
            "enriched-1.jsonl", None, "", "", "missing; write it from enrich_input.json"
        )
        return Enriched({}, warnings), [missing]

    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    unusable: list[str] = []  # file:line of each line that carries no row
    for _, path in numbered:
        rows, json_problems = load_agent_jsonl(path)
        # Only a kept primary left without a line is real loss; a corrected line in a later
        # file makes a broken one harmless, so these are reported only as warnings.
        for p in json_problems:
            where = f"{p.file}:{p.line}:{p.col}"
            unusable.append(where)
            warnings.append(f"{where}: unparsable line ignored ({p.message}): {p.text}")
        for lineno, obj in rows:
            if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
                where = f"{path.name}:{lineno}"
                unusable.append(where)
                warnings.append(
                    f"{where}: line ignored; each line must be an object with an `id` string"
                )
                continue
            rid = obj["id"]
            if rid in latest:
                old_file, old_line, _ = latest[rid]
                warnings.append(
                    f"{rid}: {old_file}:{old_line} is superseded by {path.name}:{lineno}"
                )
            latest[rid] = (path.name, lineno, obj)

    out: dict[str, dict[str, Any]] = {}
    unknown_tags: Counter[str] = Counter()
    for rid, (fname, lineno, obj) in latest.items():
        if rid not in primaries:
            warnings.append(f"{fname}:{lineno} {rid}: not a kept primary; ignored")
            continue
        row = _check_enriched_row(obj, primaries[rid], fname, lineno, problems, warnings)
        if row is not None:
            out[rid] = row
            unknown_tags.update(t for t in row["tags"] if t not in ctx.vocab)
    for rid in primaries:
        if rid not in latest:
            message = "missing: every kept primary needs one line"
            if unusable:
                shown = ", ".join(unusable[: ctx.max_problems])
                message += f" (unusable lines, possibly this one: {shown})"
            problems.append(Problem("enriched-*.jsonl", None, rid, "", message))
    if unknown_tags and ctx.vocab:
        top = ", ".join(f"{t}({n})" for t, n in unknown_tags.most_common())
        warnings.append(f"tags outside tags.txt (add the recurring ones there): {top}")
    return Enriched(out, warnings), problems


def _check_enriched_row(
    obj: dict[str, Any],
    lang: str,
    fname: str,
    lineno: int,
    problems: list[Problem],
    warnings: list[str],
) -> dict[str, Any] | None:
    rid = obj["id"]
    before = len(problems)

    def bad(field: str, message: str) -> None:
        problems.append(Problem(fname, lineno, rid, field, message))

    summary: Any = obj.get("summary")
    if not _nonempty_str(summary):
        bad("summary", "must be a non-empty string")
    key_points: Any = obj.get("key_points")
    if (
        not isinstance(key_points, list)
        or not key_points
        or not all(_nonempty_str(k) for k in key_points)
    ):
        bad("key_points", "must be a non-empty list of strings")
    title_zh = obj.get("title_zh", "")
    if not isinstance(title_zh, str):
        bad("title_zh", "must be a string")
    elif lang != "zh" and not title_zh.strip():
        bad("title_zh", "required: the original title is not Chinese")
    why = obj.get("why_it_matters", "")
    if not isinstance(why, str):
        bad("why_it_matters", "must be a string")
    tags: Any = obj.get("tags", [])
    if not isinstance(tags, list) or not all(_nonempty_str(t) for t in tags):
        bad("tags", "must be a list of strings")
    region = obj.get("region", "")
    if region != "" and region not in REGIONS:
        bad("region", f"expected one of: {', '.join(REGIONS)}, or empty")
    entities: Any = obj.get("entities", {})
    if not isinstance(entities, dict) or not all(
        isinstance(entities.get(k, []), list)
        and all(isinstance(x, str) for x in entities.get(k, []))
        for k in ENTITY_KEYS
    ):
        bad("entities", f"must be an object of string lists: {', '.join(ENTITY_KEYS)}")
    confidence: Any = obj.get("confidence", 0.0)
    if not _is_unit(confidence):
        bad("confidence", "must be a number from 0 to 1")
    if len(problems) > before:
        return None

    where = f"{fname}:{lineno} {rid}"
    if len(summary) > SUMMARY_MAX_CHARS:
        warnings.append(f"{where}: summary is {len(summary)} chars (aim for ≤ {SUMMARY_MAX_CHARS})")
    if len(key_points) != KEY_POINTS:
        warnings.append(f"{where}: key_points has {len(key_points)} entries (aim for {KEY_POINTS})")
    if len(tags) > MAX_TAGS:
        warnings.append(f"{where}: {len(tags)} tags (aim for at most {MAX_TAGS})")
    return {
        "title_zh": title_zh.strip(),
        "summary": summary.strip(),
        "key_points": [k.strip() for k in key_points],
        "why_it_matters": why.strip(),
        "tags": [t.strip() for t in tags],
        "region": region,
        "entities": {k: list(entities.get(k, [])) for k in ENTITY_KEYS},
        "confidence": float(confidence),
    }


def report_problems(ctx: RunContext, problems: list[Problem], what: str) -> ValidationFailed:
    for problem in problems[: ctx.max_problems]:
        error(problem.format())
    hidden = len(problems) - ctx.max_problems
    if hidden > 0:
        error(f"... and {hidden} more")
    path = ctx.run_dir / ERRORS_FILE
    write_json_atomic(path, {"count": len(problems), "problems": [asdict(p) for p in problems]})
    return ValidationFailed(
        f"{what} has {len(problems)} problem(s), all listed in {path}; "
        "fix exactly those entries, then run `check` again"
    )


def clear_problems(ctx: RunContext) -> None:
    (ctx.run_dir / ERRORS_FILE).unlink(missing_ok=True)


def require_valid_triage(ctx: RunContext) -> Triage:
    triage, problems = load_triage(ctx)
    if triage is None:
        raise report_problems(ctx, problems, TRIAGE_FILE)
    return triage


def require_valid_enriched(ctx: RunContext, triage: Triage) -> Enriched:
    enriched, problems = load_enriched(ctx, kept_primaries(ctx, triage))
    for message in enriched.warnings:
        warn(message)
    if problems:
        raise report_problems(ctx, problems, "enriched-*.jsonl")
    return enriched


def cmd_check(args: argparse.Namespace) -> int:
    ctx = load_context(args.run)
    require_open(ctx.run)
    triage = require_valid_triage(ctx)
    kept = triage.kept(ctx.min_importance)
    say(
        f"triage.json ok: {len(triage.events)} events, {len(kept)} kept "
        f"(importance >= {ctx.min_importance}), {len(triage.drop)} dropped"
    )
    enrich_input = ctx.run_dir / ENRICH_INPUT_FILE
    if not enrich_input.is_file():
        clear_problems(ctx)
        say(f"next: leads --run {ctx.run_dir}")
        return 0
    if {item["id"] for item in read_json(enrich_input)["items"]} != set(
        kept_primaries(ctx, triage)
    ):
        clear_problems(ctx)
        say(f"triage.json changed after `leads` ran; next: leads --run {ctx.run_dir}")
        return 0
    if kept and not any(ctx.run_dir.glob("enriched-*.jsonl")):
        clear_problems(ctx)
        say(
            "next: write enriched-1.jsonl (then -2, -3 … per batch) from enrich_input.json, "
            "then check"
        )
        return 0
    enriched = require_valid_enriched(ctx, triage)
    clear_problems(ctx)
    say(f"enriched ok: {len(enriched.rows)} of {len(kept)} kept primaries")
    say(f"next: finalize --run {ctx.run_dir}")
    return 0
