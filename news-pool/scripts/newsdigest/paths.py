"""skill 自身文件（references、示例 profile）的位置，以及新闻池的位置。"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
REFERENCES_DIR = SKILL_DIR / "references"
PROFILES_DIR = SKILL_DIR / "assets" / "profiles"  # 每个子目录是一个示例 profile，目录名就是它的名字
DEFAULT_EXAMPLE = "ai-zh"
EXAMPLE_PROFILE_DIR = PROFILES_DIR / DEFAULT_EXAMPLE

POOL_ENV = "NEWS_POOL_DIR"
DEFAULT_POOL = "~/.news-pool"


def example_profiles() -> dict[str, Path]:
    """示例 profile，按名字排序：名字 -> 目录。"""
    return {p.name: p for p in sorted(PROFILES_DIR.iterdir()) if p.is_dir()}


def init_hint() -> str:
    """没有 profile 时告诉 agent 怎么建：先问用户关注什么，再从最接近的示例开始。"""
    return (
        "ask the user what news they follow, then run `nd.py init --example NAME` with the "
        f"closest example: {', '.join(example_profiles())}"
    )


def viewer_hint(run_id: str | None) -> str:
    """一次运行落盘之后的 `next:`：用同一个 skill 的 nv.py 打开阅读器看这次运行；什么都没收进来时
    打开整个新闻池。"""
    command = f"nv.py up --run {run_id}" if run_id else "nv.py up"
    return f"next: open the viewer: {command}"


def resolve_pool(cli_value: str | None) -> Path:
    """依次取 --pool、$NEWS_POOL_DIR、~/.news-pool。"""
    raw = cli_value or os.environ.get(POOL_ENV) or DEFAULT_POOL
    return Path(raw).expanduser().resolve()
