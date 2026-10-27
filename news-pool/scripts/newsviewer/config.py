"""设置：references/viewer-defaults.json 与可选的 <pool>/viewer/config.json 深度合并。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import UsageError
from .paths import REFERENCES_DIR, VIEWER_DIR

DEFAULTS_FILE = "viewer-defaults.json"
CONFIG_FILE = "config.json"
NUMERIC_KEYS = ("port", "idle_minutes", "heartbeat_s", "start_timeout_s", "refresh_s", "page_size")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """嵌套对象逐层合并，其他值直接替换；以 `_` 开头的键是注释（与 nd.py 的 profile 相同）。"""
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


def load_settings(pool: Path) -> dict[str, Any]:
    override = pool / VIEWER_DIR / CONFIG_FILE
    extra = _read_object(override) if override.is_file() else {}
    settings = deep_merge(_read_object(REFERENCES_DIR / DEFAULTS_FILE), extra)
    for key in NUMERIC_KEYS:
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise UsageError(f"{override}: {key} must be a non-negative number, got {value!r}")
    return settings


def _read_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            obj = json.load(fh)
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise UsageError(f"{path}: expected a JSON object")
    return obj
