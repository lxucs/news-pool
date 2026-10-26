"""参数解析、命令分发和退出码约定（各退出码的含义见 SKILL.md）。"""

from __future__ import annotations

import argparse
import traceback
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from . import __version__, fetch, finalize, leads, prepare, runs, status, validate
from .console import error
from .errors import INTERNAL_ERROR_EXIT, NdError, UsageError
from .paths import resolve_pool

CRASH_LOG = "nd-error.log"
COMMAND_MODULES = (runs, fetch, prepare, validate, leads, finalize, status)


class NdParser(argparse.ArgumentParser):
    """argparse 遇到用法错误时以 2 退出，而约定是 1，所以改为抛异常。"""

    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{self.prog}: {message}")


def build_parser() -> NdParser:
    parser = NdParser(prog="nd.py", description="news-digest: deterministic pipeline steps")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", parser_class=NdParser)
    sub.required = True
    for module in COMMAND_MODULES:
        module.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace | None = None
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except NdError as exc:
        error(str(exc))
        return exc.exit_code
    except PermissionError as exc:
        error(
            f"permission denied: {exc.filename}; the pool directory must be writable "
            "(a sandboxed harness may block it)"
        )
        return UsageError.exit_code
    except Exception as exc:  # noqa: BLE001 - 兜底：退出码 5 让 agent 把错误报告给用户
        return _internal_error(exc, args)


def _internal_error(exc: Exception, args: argparse.Namespace | None) -> int:
    command = getattr(args, "command", None) or "nd.py"
    where = ""
    try:
        log_path = _crash_log_path(args)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.now().isoformat()} {command}\n{traceback.format_exc()}\n")
        where = f" (traceback: {log_path})"
    except OSError:
        pass
    error(f"internal error in {command}: {type(exc).__name__}: {exc}{where}")
    error("this is a skill bug: report it to the user; do not edit the skill's scripts")
    return INTERNAL_ERROR_EXIT


def _crash_log_path(args: argparse.Namespace | None) -> Path:
    run = getattr(args, "run", None)
    if run:
        return Path(run).expanduser() / CRASH_LOG
    return resolve_pool(getattr(args, "pool", None)) / CRASH_LOG
