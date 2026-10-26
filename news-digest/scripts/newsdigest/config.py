"""配置（defaults.json 与 profile 深度合并的结果），以及各资源文件的加载函数。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import UsageError
from .files import read_json
from .normalize import parse_tz
from .paths import REFERENCES_DIR, init_hint

DEFAULTS_FILE = "defaults.json"
PROFILE_CONFIG = "config.json"
FEEDS_FILE = "feeds.json"
TAGS_FILE = "tags.txt"
TIERS_FILE = "source_tiers.json"
CATEGORIES_FILE = "categories.json"
RESOURCE_FILES = (FEEDS_FILE, TAGS_FILE, TIERS_FILE, CATEGORIES_FILE)

# 命令行赋予了特殊含义的词；订阅源不能用它们作 id。
RESERVED_SOURCE_IDS = frozenset({"rss", "none", "wscn", "gnews", "hn", "gdelt", "links", "manual"})
_FEED_ID_RE = re.compile(r"[a-z0-9_-]+")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """嵌套对象逐层合并，其余值（包括列表）直接替换。以 `_` 开头的键是注释。"""
    out = {k: v for k, v in base.items() if not k.startswith("_")}
    for key, value in override.items():
        if key.startswith("_"):
            continue
        current = out.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            out[key] = deep_merge(current, value)
        else:
            out[key] = value
    return out


def load_json_config(path: Path) -> Any:
    try:
        return read_json(path)
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}") from None
    except UnicodeDecodeError as exc:
        raise UsageError(f"{path}: not valid UTF-8 ({exc.reason})") from None
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror}") from None


def load_settings(profile_dir: Path) -> dict[str, Any]:
    cfg_path = profile_dir / PROFILE_CONFIG
    if not cfg_path.exists():
        raise UsageError(f"no profile at {profile_dir} (missing {PROFILE_CONFIG}); {init_hint()}")
    defaults = load_json_config(REFERENCES_DIR / DEFAULTS_FILE)
    profile = load_json_config(cfg_path)
    if not isinstance(profile, dict):
        raise UsageError(f"{cfg_path}: expected a JSON object")
    settings = deep_merge(defaults, profile)
    settings.setdefault("name", profile_dir.name)
    settings.setdefault("queries", [])
    problems = _type_problems(defaults, settings) + _settings_problems(settings)
    if problems:
        raise UsageError(f"{cfg_path}: " + "; ".join(problems))
    return settings


def _kind(value: object) -> str:
    if isinstance(value, bool):
        return "true or false"
    if isinstance(value, (int, float)):
        return "a number"
    return {dict: "an object", list: "a list", str: "a string"}.get(type(value), "")


def _type_problems(defaults: dict[str, Any], merged: dict[str, Any], prefix: str = "") -> list[str]:
    """defaults.json 里有的键必须保持原来的 JSON 类型（对象逐层递归检查）。"""
    problems: list[str] = []
    for key, default in defaults.items():
        if key.startswith("_") or key not in merged:
            continue
        value, name = merged[key], f"{prefix}{key}"
        want = _kind(default)
        if _kind(value) != want:
            problems.append(f"`{name}` must be {want}")
        elif isinstance(default, dict):
            problems += _type_problems(default, value, f"{name}.")
    return problems


def _settings_problems(s: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not _nonempty_str(s.get("interests")):
        problems.append("`interests` must be a non-empty string describing what to keep")
    if not _str_list(s.get("queries")):
        problems.append("`queries` must be a list of non-empty strings")
    if not _str_list(s.get("sources")):
        problems.append("`sources` must be a list of source ids")
    try:
        parse_tz(str(s.get("tz", "")))
    except ValueError as exc:
        problems.append(f"`tz`: {exc}")
    return problems


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: object) -> bool:
    return isinstance(value, list) and all(_nonempty_str(v) for v in value)


def resource_path(profile_dir: Path, filename: str) -> Path:
    """profile 里有这个资源文件就用 profile 的，否则用 skill 内置的。"""
    own = profile_dir / filename
    return own if own.exists() else REFERENCES_DIR / filename


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    url: str
    enabled: bool = True
    note: str = ""


def load_feeds(path: Path) -> list[Feed]:
    data = load_json_config(path)
    if not isinstance(data, list):
        raise UsageError(f"{path}: expected a JSON list of feeds")
    feeds: list[Feed] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            problems.append(f"[{i}]: expected an object")
            continue
        fid = entry.get("id")
        if not isinstance(fid, str) or not _FEED_ID_RE.fullmatch(fid):
            problems.append(f"[{i}]: `id` must match [a-z0-9_-]+")
            continue
        where = f"[{i}] {fid}"
        if fid in RESERVED_SOURCE_IDS:
            problems.append(f"{where}: `id` is reserved")
        if fid in seen:
            problems.append(f"{where}: duplicate `id`")
        seen.add(fid)
        name, url, enabled = entry.get("name"), entry.get("url"), entry.get("enabled", True)
        if not _nonempty_str(name):
            problems.append(f"{where}: `name` must be a non-empty string")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            problems.append(f"{where}: `url` must be an http(s) URL")
        if not isinstance(enabled, bool):
            problems.append(f"{where}: `enabled` must be true or false")
        feeds.append(
            Feed(fid, str(name), str(url), enabled is not False, str(entry.get("note", "")))
        )
    if problems:
        raise UsageError(f"{path}: " + "; ".join(problems))
    return feeds


def load_categories(path: Path) -> list[dict[str, Any]]:
    data = load_json_config(path)
    if not isinstance(data, list) or not data:
        raise UsageError(f"{path}: expected a non-empty JSON list of categories")
    names: list[str] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or not _nonempty_str(entry.get("name")):
            raise UsageError(f"{path}: [{i}] needs a non-empty `name`")
        if entry["name"] in names:
            raise UsageError(f"{path}: duplicate category {entry['name']!r}")
        names.append(entry["name"])
    return data


def category_names(categories: list[dict[str, Any]]) -> list[str]:
    return [str(c["name"]) for c in categories]


def load_tags(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"{path}: not valid UTF-8 ({exc.reason})") from None
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror}") from None
    tags: set[str] = set()
    for line in text.splitlines():
        tag = line.split("#", 1)[0].strip()
        if tag:
            tags.add(tag)
    return tags


def load_tiers(path: Path) -> dict[str, Any]:
    data = load_json_config(path)
    if not isinstance(data, dict) or not isinstance(data.get("default"), int):
        raise UsageError(f"{path}: expected an object with an integer `default`")
    for key in ("by_domain", "by_name"):
        if not isinstance(data.get(key, {}), dict):
            raise UsageError(f"{path}: `{key}` must be an object")
    return data
