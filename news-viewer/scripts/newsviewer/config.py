"""Settings: references/defaults.json deep-merged with an optional <pool>/viewer/config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import UsageError
from .paths import REFERENCES_DIR, VIEWER_DIR

DEFAULTS_FILE = "defaults.json"
CONFIG_FILE = "config.json"
NUMERIC_KEYS = ("port", "idle_minutes", "heartbeat_s", "start_timeout_s", "refresh_s", "page_size")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Nested objects merge; anything else is replaced; `_`-keys are comments (as news-digest)."""
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
