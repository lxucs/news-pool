"""参数解析、命令分发和退出码约定（每个退出码的含义见 SKILL.md）。"""

from __future__ import annotations

import argparse
import traceback
import webbrowser
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

from . import __version__, lifecycle
from .config import load_settings
from .console import error, say
from .errors import INTERNAL_ERROR_EXIT, NvError, UsageError
from .paths import VIEWER_DIR, existing_pool, resolve_pool

CRASH_LOG = "nv-error.log"
MAX_PORT = 65535
POOL_HELP = "the news pool (default: $NEWS_POOL_DIR or ~/.news-pool)"


class NvParser(argparse.ArgumentParser):
    """argparse 遇到用法错误时以 2 退出；约定是 1，所以改为抛异常。"""

    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{self.prog}: {message}")


def build_parser() -> NvParser:
    parser = NvParser(prog="nv.py", description="nv.py: read the news pool in a browser")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", parser_class=NvParser)
    sub.required = True

    up = sub.add_parser("up", help="start the viewer (or reuse the running one); print its URL")
    _pool_and_port(up)
    up.add_argument("--run", help="open this run: a run id or a run directory")
    up.add_argument("--browser", action="store_true", help="also open the URL in a browser")
    up.set_defaults(handler=cmd_up)

    serve = sub.add_parser("serve", help="run the viewer in the foreground (Ctrl-C stops it)")
    _pool_and_port(serve)
    serve.set_defaults(handler=cmd_serve)

    down = sub.add_parser("down", help="stop the running viewer")
    down.add_argument("--pool", help=POOL_HELP)
    down.set_defaults(handler=cmd_down)

    status = sub.add_parser("status", help="is the viewer running, and where")
    status.add_argument("--pool", help=POOL_HELP)
    status.set_defaults(handler=cmd_status)
    return parser


def _pool_and_port(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pool", help=POOL_HELP)
    parser.add_argument("--port", type=int, help="port on 127.0.0.1 (default: settings, 8765)")


def cmd_up(args: argparse.Namespace) -> int:
    pool = existing_pool(args.pool)
    settings = load_settings(pool)
    port = _port(args.port, settings)
    fragment = _run_fragment(pool, args.run) if args.run else ""
    info, reused = lifecycle.up(pool, port, float(settings["start_timeout_s"]))
    url = info.url + fragment
    say(f"{'reusing the running viewer' if reused else 'started the viewer'} (pid {info.pid})")
    say(f"url: {url}")
    if args.browser:
        webbrowser.open(url)
    say(f"next: give the user this url; {_idle_note(settings)} (`nv.py down` stops it now)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    pool = existing_pool(args.pool)
    settings = load_settings(pool)
    lifecycle.serve(pool, settings, _port(args.port, settings))
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    pool = existing_pool(args.pool)
    say("stopped the viewer" if lifecycle.down(pool) else "the viewer is not running")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    pool = existing_pool(args.pool)
    info = lifecycle.running(pool)
    if info is None:
        say("the viewer is not running")
        say("next: nv.py up")
        return 0
    say(f"running: {info.url} (pid {info.pid}, since {info.started_at})")
    return 0


def _port(value: int | None, settings: dict[str, Any]) -> int:
    port = int(settings["port"]) if value is None else value
    if not 1 <= port <= MAX_PORT:
        raise UsageError(f"port must be 1-{MAX_PORT}, got {port}")
    return port


def _run_fragment(pool: Path, run: str) -> str:
    """`--run` 接受 run_id 或运行目录；URL 会让阅读器直接打开这次运行。"""
    run_id = Path(run).name
    if not (pool / "runs" / run_id / "run.json").is_file():
        raise UsageError(f"no run {run_id!r} in {pool}; `nd.py status` lists runs")
    return f"#/run/{run_id}"


def _idle_note(settings: dict[str, Any]) -> str:
    minutes = settings["idle_minutes"]
    return f"it stops by itself after {minutes:g} idle minutes" if minutes else "it keeps running"


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace | None = None
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except NvError as exc:
        error(str(exc))
        return exc.exit_code
    except PermissionError as exc:
        error(
            f"permission denied: {exc.filename}; <pool>/viewer must be writable "
            "(a sandboxed harness may block it)"
        )
        return UsageError.exit_code
    except Exception as exc:  # noqa: BLE001 - 兜底：退出码 5 让 agent 把错误报告给用户
        return _internal_error(exc, args)


def _internal_error(exc: Exception, args: argparse.Namespace | None) -> int:
    command = getattr(args, "command", None) or "nv.py"
    where = ""
    try:
        pool = resolve_pool(getattr(args, "pool", None))
        if pool.is_dir():  # 绝不为了存错误日志而创建新闻池
            log_path = pool / VIEWER_DIR / CRASH_LOG
            log_path.parent.mkdir(exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"--- {datetime.now().isoformat()} {command}\n{traceback.format_exc()}\n")
            where = f" (traceback: {log_path})"
    except OSError:
        pass
    error(f"internal error in {command}: {type(exc).__name__}: {exc}{where}")
    error("this is a skill bug: report it to the user; do not edit the skill's scripts")
    return INTERNAL_ERROR_EXIT
