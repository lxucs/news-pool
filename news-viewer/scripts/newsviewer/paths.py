"""Where the skill's own files are, and where the pool and the viewer's data are."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import UsageError

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
REFERENCES_DIR = SKILL_DIR / "references"
STATIC_DIR = Path(__file__).resolve().parent / "static"
NV_SCRIPT = SKILL_DIR / "scripts" / "nv.py"

POOL_ENV = "NEWS_POOL_DIR"
DEFAULT_POOL = "~/.news-pool"
VIEWER_DIR = "viewer"  # <pool>/viewer/ holds the viewer's own files; news-digest never touches it


def resolve_pool(cli_value: str | None) -> Path:
    """--pool, then $NEWS_POOL_DIR, then ~/.news-pool (the same rule as news-digest)."""
    raw = cli_value or os.environ.get(POOL_ENV) or DEFAULT_POOL
    return Path(raw).expanduser().resolve()


def existing_pool(cli_value: str | None) -> Path:
    """The pool to serve. The viewer never creates one: that is news-digest's first run."""
    pool = resolve_pool(cli_value)
    if not pool.is_dir():
        raise UsageError(
            f"no news pool at {pool}; fetch news with the news-digest skill first "
            "(or pass --pool / set NEWS_POOL_DIR)"
        )
    return pool
