"""skill 自身文件的位置，以及新闻池的位置。"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
REFERENCES_DIR = SKILL_DIR / "references"
EXAMPLE_PROFILE_DIR = SKILL_DIR / "examples" / "profile-ai-zh"

POOL_ENV = "NEWS_POOL_DIR"
DEFAULT_POOL = "~/.news-pool"


def resolve_pool(cli_value: str | None) -> Path:
    """依次取 --pool、$NEWS_POOL_DIR、~/.news-pool。"""
    raw = cli_value or os.environ.get(POOL_ENV) or DEFAULT_POOL
    return Path(raw).expanduser().resolve()
