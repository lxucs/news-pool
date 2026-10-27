"""给 agent 看的输出：简短的 `[nd]` 行；错误写到 stderr。"""

from __future__ import annotations

import sys


def use_utf8() -> None:
    """控制台编码容不下中文时（Windows），输出中文也不能崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and encoding != "utf8":
            reconfigure(encoding="utf-8", errors="replace")


def say(msg: str) -> None:
    print(f"[nd] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[nd] warning: {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[nd] error: {msg}", file=sys.stderr, flush=True)
