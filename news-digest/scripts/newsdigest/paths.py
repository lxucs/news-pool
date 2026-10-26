"""skill 自身文件（references、示例 profile）的位置，以及新闻池的位置。"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
REFERENCES_DIR = SKILL_DIR / "references"
EXAMPLES_DIR = SKILL_DIR / "examples"
EXAMPLE_PROFILE_PREFIX = "profile-"  # examples/profile-<名字>/ 是一个示例 profile
DEFAULT_EXAMPLE = "ai-zh"
EXAMPLE_PROFILE_DIR = EXAMPLES_DIR / f"{EXAMPLE_PROFILE_PREFIX}{DEFAULT_EXAMPLE}"

POOL_ENV = "NEWS_POOL_DIR"
DEFAULT_POOL = "~/.news-pool"


def example_profiles() -> dict[str, Path]:
    """示例 profile，按名字排序：名字 -> 目录。"""
    prefix = EXAMPLE_PROFILE_PREFIX
    dirs = sorted(p for p in EXAMPLES_DIR.glob(f"{prefix}*") if p.is_dir())
    return {p.name[len(prefix) :]: p for p in dirs}


def init_hint() -> str:
    """没有 profile 时告诉 agent 怎么建：先问用户关注什么，再从最接近的示例开始。"""
    return (
        "ask the user what news they follow, then run `nd.py init --example NAME` with the "
        f"closest example: {', '.join(example_profiles())}"
    )


def resolve_pool(cli_value: str | None) -> Path:
    """依次取 --pool、$NEWS_POOL_DIR、~/.news-pool。"""
    raw = cli_value or os.environ.get(POOL_ENV) or DEFAULT_POOL
    return Path(raw).expanduser().resolve()
