from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from newsviewer import __version__, lifecycle
from newsviewer.api import Request
from newsviewer.config import load_settings
from newsviewer.errors import StartFailed
from newsviewer.lifecycle import (
    ServerInfo,
    down,
    read_server_info,
    remove_server_info,
    running,
    up,
    watch_idle,
    write_server_info,
)
from newsviewer.server import Activity


def info(
    pool: Path, instance: str = "one", port: int = 8765, version: str = __version__
) -> ServerInfo:
    return ServerInfo(
        pid=111,
        port=port,
        url=f"http://127.0.0.1:{port}/",
        pool=str(pool),
        instance=instance,
        version=version,
        started_at="2026-10-22T10:00:00+08:00",
    )


def answering(pool: Path, instance: str) -> Any:
    """一个健康检查函数：恰好有一个存活的服务（`instance`）应答。"""

    def probe(port: int) -> dict[str, Any] | None:
        return {"app": "news-viewer", "instance": instance, "pool": str(pool)}

    return probe


def silent(port: int) -> dict[str, Any] | None:
    return None


class FakeChild:
    def __init__(self, code: int | None = None) -> None:
        self.pid = 222
        self.code = code

    def poll(self) -> int | None:
        return self.code


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_server_info_round_trip_and_owner_only_removal(tmp_path: Path) -> None:
    write_server_info(tmp_path, info(tmp_path))
    assert read_server_info(tmp_path) == info(tmp_path)
    remove_server_info(tmp_path, "someone-else")
    assert read_server_info(tmp_path) is not None
    remove_server_info(tmp_path, "one")
    assert read_server_info(tmp_path) is None


def test_an_unreadable_server_file_counts_as_none(tmp_path: Path) -> None:
    (tmp_path / "viewer").mkdir()
    (tmp_path / "viewer" / "server.json").write_text("{half", encoding="utf-8")
    assert read_server_info(tmp_path) is None


def test_up_reuses_a_live_server(tmp_path: Path) -> None:
    write_server_info(tmp_path, info(tmp_path))

    def spawn(pool: Path, port: int) -> FakeChild:
        raise AssertionError("a live server must be reused")

    result = up(tmp_path, 8765, 10, spawn=spawn, probe=answering(tmp_path, "one"))
    assert result == (info(tmp_path), True)
    assert running(tmp_path, probe=answering(tmp_path, "one")) == info(tmp_path)


def test_up_starts_a_server_when_the_recorded_one_is_gone(tmp_path: Path) -> None:
    write_server_info(tmp_path, info(tmp_path, "stale"))
    fresh = info(tmp_path, "fresh", port=8766)

    def spawn(pool: Path, port: int) -> FakeChild:
        assert port == 8765
        write_server_info(pool, fresh)  # 子进程开始提供服务后会做的事
        return FakeChild()

    t = FakeTime()
    result = up(
        tmp_path,
        8765,
        10,
        spawn=spawn,
        probe=answering(tmp_path, "fresh"),
        sleep=t.sleep,
        clock=t.clock,
    )
    assert result == (fresh, False)


def test_up_replaces_a_server_from_another_version(tmp_path: Path) -> None:
    # 例如升级前从旧目录启动的服务：它的页面文件可能已经不在了
    write_server_info(tmp_path, info(tmp_path, "old", version="1.0.0"))
    fresh = info(tmp_path, "fresh")
    live: list[str | None] = ["old"]
    posted: list[int] = []

    def probe(port: int) -> dict[str, Any] | None:
        instance = live[0]
        return None if instance is None else answering(tmp_path, instance)(port)

    def post(port: int) -> None:
        posted.append(port)
        live[0] = None  # 旧服务收到请求后退出

    def spawn(pool: Path, port: int) -> FakeChild:
        write_server_info(pool, fresh)
        live[0] = "fresh"
        return FakeChild()

    t = FakeTime()
    result = up(
        tmp_path,
        8765,
        10,
        spawn=spawn,
        probe=probe,
        post=post,
        sleep=t.sleep,
        clock=t.clock,
    )
    assert result == (fresh, False)
    assert posted == [8765]


def test_up_reports_a_child_that_exits_while_starting(tmp_path: Path) -> None:
    t = FakeTime()
    with pytest.raises(StartFailed, match="server.log"):
        up(
            tmp_path,
            8765,
            10,
            spawn=lambda pool, port: FakeChild(code=1),
            probe=silent,
            sleep=t.sleep,
            clock=t.clock,
        )


def test_up_gives_up_after_the_start_timeout(tmp_path: Path) -> None:
    t = FakeTime()
    with pytest.raises(StartFailed, match="did not answer within 10s"):
        up(
            tmp_path,
            8765,
            10,
            spawn=lambda pool, port: FakeChild(),
            probe=silent,
            sleep=t.sleep,
            clock=t.clock,
        )
    assert t.now >= 10


def test_down(tmp_path: Path) -> None:
    assert down(tmp_path, probe=silent) is False
    write_server_info(tmp_path, info(tmp_path))
    assert down(tmp_path, probe=silent) is False
    assert read_server_info(tmp_path) is None  # 过期的记录被清理掉

    write_server_info(tmp_path, info(tmp_path))
    alive = [True]
    posted: list[int] = []

    def probe(port: int) -> dict[str, Any] | None:
        return answering(tmp_path, "one")(port) if alive[0] else None

    def post(port: int) -> None:
        posted.append(port)
        alive[0] = False

    t = FakeTime()
    assert down(tmp_path, probe=probe, post=post, sleep=t.sleep, clock=t.clock) is True
    assert posted == [8765]


def test_watch_idle_stops_an_idle_server() -> None:
    t = FakeTime()
    activity = Activity(clock=t.clock)
    stops: list[bool] = []

    def wait(seconds: float) -> bool:
        t.now += seconds
        return False

    watch_idle(activity, 600, lambda: stops.append(True), wait)
    assert stops == [True] and t.now == 600


def test_watch_idle_keeps_a_busy_server_and_returns_when_it_ends() -> None:
    t = FakeTime()
    activity = Activity(clock=t.clock)
    stops: list[bool] = []
    ticks: list[float] = []

    def wait(seconds: float) -> bool:
        ticks.append(seconds)
        t.now += seconds
        activity.touch()
        return len(ticks) >= 5  # 服务自己结束了

    watch_idle(activity, 600, lambda: stops.append(True), wait)
    assert stops == [] and ticks == [30.0] * 5  # 每次等 min(30 s, idle / 4)


def test_serve_records_the_server_while_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = tmp_path / "pool"
    pool.mkdir()
    seen: dict[str, Any] = {}

    class FakeHTTPD:
        port = 8765

        def __init__(self) -> None:
            self.activity = Activity()
            self.app: Any = None

        def serve_forever(self) -> None:
            seen["info"] = read_server_info(pool)
            health = self.app.handle(Request("GET", "/api/health", {}, {"host": "127.0.0.1:8765"}))
            seen["health"] = json.loads(health.body)

        def shutdown(self) -> None:
            pass

        def server_close(self) -> None:
            seen["closed"] = True

    monkeypatch.setattr(lifecycle, "make_server", lambda port: FakeHTTPD())
    lifecycle.serve(pool, load_settings(pool), 8765)
    assert seen["info"].port == 8765
    assert seen["health"]["instance"] == seen["info"].instance
    assert seen["closed"] and read_server_info(pool) is None
