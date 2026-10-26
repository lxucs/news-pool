"""skill 自身文件的位置，以及新闻池和阅读器数据的位置。"""

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
VIEWER_DIR = "viewer"  # <pool>/viewer/ 存放阅读器自己的文件；news-digest 从不碰它


def resolve_pool(cli_value: str | None) -> Path:
    """依次取 --pool、$NEWS_POOL_DIR、~/.news-pool（与 news-digest 的规则相同）。"""
    raw = cli_value or os.environ.get(POOL_ENV) or DEFAULT_POOL
    return Path(raw).expanduser().resolve()


def existing_pool(cli_value: str | None) -> Path:
    """要提供的新闻池。阅读器从不创建新闻池：那是 news-digest 第一次运行时的事。"""
    pool = resolve_pool(cli_value)
    if not pool.is_dir():
        raise UsageError(
            f"no news pool at {pool}; fetch news with the news-digest skill first "
            "(or pass --pool / set NEWS_POOL_DIR)"
        )
    return pool
