"""Where the skill's own files are, and where the pool is."""

from __future__ import annotations

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
REFERENCES_DIR = SKILL_DIR / "references"
EXAMPLE_PROFILE_DIR = SKILL_DIR / "examples" / "profile-ai-zh"

POOL_ENV = "NEWS_POOL_DIR"
DEFAULT_POOL = "~/.news-pool"


def resolve_pool(cli_value: str | None) -> Path:
    """--pool, then $NEWS_POOL_DIR, then ~/.news-pool."""
    raw = cli_value or os.environ.get(POOL_ENV) or DEFAULT_POOL
    return Path(raw).expanduser().resolve()
