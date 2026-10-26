"""服务的生命周期：serve（前台）、up（在后台启动，或复用已有的服务）、down、空闲看门狗线程。

<pool>/viewer/server.json 记录正在运行的服务。健康检查回复的 `instance` 与记录相同，就证明服务
是我们的、而且还活着。这里从不按 pid 杀进程：被复用的 pid 可能属于任何进程。"""

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
PROBE_TIMEOUT_S = 2.0  # 本机健康检查；比这更慢就不算健康的服务
POLL_S = 0.1  # `up` 和 `down` 等待时每隔多久再看一次
DOWN_WAIT_S = 5.0  # `down` 等服务退出的最长时间
WATCH_MAX_S = 30.0  # 空闲看门狗线程至少隔这么久醒来一次


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
    """`up` 对启动的子进程的要求（subprocess.Popen 满足）。"""

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
    """原子写入，`up` 永远不会读到半个文件。"""
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
    """只在 server.json 仍描述 `instance` 时才删除它（它可能已归更新的服务所有）。"""
    current = read_server_info(pool)
    if current is not None and current.instance == instance:
        with contextlib.suppress(FileNotFoundError):
            server_file(pool).unlink()


def _local_opener() -> urllib.request.OpenerDirector:
    # localhost 请求绝不走环境变量里配置的代理。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe_health(port: int) -> dict[str, Any] | None:
    """在 localhost 上 GET /api/health：返回回复；没有正常的应答时返回 None。"""
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
    with contextlib.suppress(OSError):  # 服务可能在应答前就关闭了
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
    """在独立的 session 里运行 `nv.py serve`，harness 结束它的命令时不会连带结束服务。"""
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
    """这个新闻池正在运行的服务，必要时启动一个：返回 (info, reused)。"""
    current = running(pool, probe)
    if current is not None:
        return current, True
    stale = read_server_info(pool)
    child = spawn(pool, port)
    deadline = clock() + timeout_s
    while True:
        info = read_server_info(pool)
        # 要的是新实例，不是过期的记录；pid 可能不同（Windows 上的 venv 启动器）。
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
    """请这个新闻池的服务停止：没有服务在运行时返回 False（过期的记录会被删除）。"""
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
    """服务连续 idle_s 秒没有收到任何请求时，调用一次 stop()。

    `wait(t)` 最多睡 t 秒；服务已经结束时返回 True。"""
    interval = min(WATCH_MAX_S, idle_s / 4)
    while not wait(interval):
        if activity.idle_s() >= idle_s:
            say(f"idle for {idle_s / 60:g} min; stopping")
            stop()
            return


def serve(pool: Path, settings: dict[str, Any], port: int) -> None:
    """为新闻池建索引、绑定端口、写 server.json，然后一直服务到被关闭。"""
    library = Library(pool, refresh_s=float(settings["refresh_s"]))
    httpd = make_server(port)
    instance = secrets.token_hex(8)

    def stop() -> None:
        # shutdown() 会阻塞到 serve_forever 返回为止，所以绝不能在处理请求的 thread 上调用。
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
