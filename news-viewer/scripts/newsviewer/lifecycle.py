"""The server's life: serve (foreground), up (start or reuse, detached), down, the idle watchdog.

<pool>/viewer/server.json records the running server. A health probe that answers with the
same `instance` proves the server is ours and alive. Nothing here kills by pid: a reused pid
could belong to anything."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from types import FrameType
from typing import Any, Protocol

from . import __version__
from .api import APP_NAME, WRITE_HEADER, App
from .console import say
from .errors import StartFailed
from .index import Library
from .paths import NV_SCRIPT, VIEWER_DIR
from .server import HOST, Activity, make_server
from .userdb import now_iso

SERVER_FILE = "server.json"
LOG_FILE = "server.log"
PROBE_TIMEOUT_S = 2.0  # a local health check; anything slower is not a healthy server
POLL_S = 0.1  # how often `up` and `down` look again while waiting
DOWN_WAIT_S = 5.0  # how long `down` waits for the server to go
WATCH_MAX_S = 30.0  # the idle watchdog wakes at least this often


@dataclass(frozen=True)
class ServerInfo:
    pid: int
    port: int
    url: str
    pool: str
    instance: str
    version: str
    started_at: str


class Child(Protocol):
    """What `up` needs of the spawned process (subprocess.Popen satisfies it)."""

    pid: int

    def poll(self) -> int | None: ...


def server_file(pool: Path) -> Path:
    return pool / VIEWER_DIR / SERVER_FILE


def log_file(pool: Path) -> Path:
    return pool / VIEWER_DIR / LOG_FILE


def read_server_info(pool: Path) -> ServerInfo | None:
    try:
        data = json.loads(server_file(pool).read_text(encoding="utf-8"))
        return ServerInfo(**{f.name: data[f.name] for f in fields(ServerInfo)})
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_server_info(pool: Path, info: ServerInfo) -> None:
    """Atomically, so `up` never reads half a file."""
    path = server_file(pool)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(info), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def remove_server_info(pool: Path, instance: str) -> None:
    """Remove server.json only if it still describes `instance` (a newer server may own it)."""
    current = read_server_info(pool)
    if current is not None and current.instance == instance:
        with contextlib.suppress(FileNotFoundError):
            server_file(pool).unlink()


def _local_opener() -> urllib.request.OpenerDirector:
    # Never route a localhost request through a proxy from the environment.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe_health(port: int) -> dict[str, Any] | None:
    """GET /api/health on localhost: the reply, or None if nothing sane answers."""
    url = f"http://{HOST}:{port}/api/health"
    try:
        with _local_opener().open(url, timeout=PROBE_TIMEOUT_S) as reply:
            data = json.loads(reply.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def post_shutdown(port: int) -> None:
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", WRITE_HEADER: "1"},
    )
    with contextlib.suppress(OSError):  # the server may close before it answers
        _local_opener().open(request, timeout=PROBE_TIMEOUT_S).close()


def _is_alive(info: ServerInfo, pool: Path, probe: Callable[[int], dict[str, Any] | None]) -> bool:
    reply = probe(info.port)
    return (
        reply is not None
        and reply.get("app") == APP_NAME
        and reply.get("instance") == info.instance
        and reply.get("pool") == str(pool)
    )


def running(
    pool: Path, probe: Callable[[int], dict[str, Any] | None] = probe_health
) -> ServerInfo | None:
    info = read_server_info(pool)
    return info if info is not None and _is_alive(info, pool, probe) else None


def spawn_detached(pool: Path, port: int) -> subprocess.Popen[bytes]:
    """`nv.py serve` in its own session, so the harness ending its command does not end it."""
    log = log_file(pool)
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(NV_SCRIPT), "serve", "--pool", str(pool), "--port", str(port)]
    with log.open("ab") as out:
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            return subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def up(
    pool: Path,
    port: int,
    timeout_s: float,
    *,
    spawn: Callable[[Path, int], Child] = spawn_detached,
    probe: Callable[[int], dict[str, Any] | None] = probe_health,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[ServerInfo, bool]:
    """This pool's running server, starting one if needed: (info, reused)."""
    current = running(pool, probe)
    if current is not None:
        return current, True
    stale = read_server_info(pool)
    child = spawn(pool, port)
    deadline = clock() + timeout_s
    while True:
        info = read_server_info(pool)
        # A new instance, not the stale record; the pid can differ (Windows venv launchers).
        if info is not None and info != stale and _is_alive(info, pool, probe):
            return info, False
        code = child.poll()
        if code is not None:
            raise StartFailed(
                f"the viewer server exited with code {code} while starting; see {log_file(pool)}"
            )
        if clock() >= deadline:
            raise StartFailed(
                f"the viewer server did not answer within {timeout_s:g}s; see {log_file(pool)}"
            )
        sleep(POLL_S)


def down(
    pool: Path,
    *,
    probe: Callable[[int], dict[str, Any] | None] = probe_health,
    post: Callable[[int], None] = post_shutdown,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Ask this pool's server to stop: False when none was running (a stale record is removed)."""
    info = read_server_info(pool)
    if info is None:
        return False
    if not _is_alive(info, pool, probe):
        remove_server_info(pool, info.instance)
        return False
    post(info.port)
    deadline = clock() + DOWN_WAIT_S
    while clock() < deadline and probe(info.port) is not None:
        sleep(POLL_S)
    return True


def watch_idle(
    activity: Activity, idle_s: float, stop: Callable[[], None], wait: Callable[[float], bool]
) -> None:
    """Call stop() once nothing has been asked of the server for idle_s seconds.

    `wait(t)` sleeps up to t seconds and returns True when the server has already ended."""
    interval = min(WATCH_MAX_S, idle_s / 4)
    while not wait(interval):
        if activity.idle_s() >= idle_s:
            say(f"idle for {idle_s / 60:g} min; stopping")
            stop()
            return


def serve(pool: Path, settings: dict[str, Any], port: int) -> None:
    """Index the pool, bind, record server.json, and serve until shut down."""
    library = Library(pool, refresh_s=float(settings["refresh_s"]))
    httpd = make_server(port)
    instance = secrets.token_hex(8)

    def stop() -> None:
        # shutdown() blocks until serve_forever returns, so never call it on a request thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    httpd.app = App(library, settings, port=httpd.port, instance=instance, on_shutdown=stop)
    info = ServerInfo(
        pid=os.getpid(),
        port=httpd.port,
        url=f"http://{HOST}:{httpd.port}/",
        pool=str(pool),
        instance=instance,
        version=__version__,
        started_at=now_iso(),
    )
    ended = threading.Event()
    idle_s = float(settings["idle_minutes"]) * 60
    if idle_s > 0:
        threading.Thread(
            target=watch_idle, args=(httpd.activity, idle_s, stop, ended.wait), daemon=True
        ).start()
    previous = None
    if threading.current_thread() is threading.main_thread():

        def on_term(signum: int, frame: FrameType | None) -> None:
            stop()

        previous = signal.signal(signal.SIGTERM, on_term)
    write_server_info(pool, info)
    say(f"serving {pool} at {info.url}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ended.set()
        httpd.server_close()
        remove_server_info(pool, instance)
        library.close()
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    say("stopped")
