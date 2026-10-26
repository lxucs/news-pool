"""Output for the agent: short `[nv]` lines; errors on stderr."""

from __future__ import annotations

import sys


def use_utf8() -> None:
    """Chinese output must not crash a console whose encoding cannot hold it (Windows)."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and encoding != "utf8":
            reconfigure(encoding="utf-8", errors="replace")


def say(msg: str) -> None:
    print(f"[nv] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[nv] warning: {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[nv] error: {msg}", file=sys.stderr, flush=True)
