from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest


class NetworkBlocked(BaseException):
    """继承 BaseException，这样抓取代码里的 `except Exception` 吞不掉它。"""


def _blocked(*args: Any, **kwargs: Any) -> NoReturn:
    raise NetworkBlocked("tests must not touch the network")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


@pytest.fixture(autouse=True)
def _isolated_pool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """绝不让测试碰到真实的 ~/.news-pool。"""
    pool = tmp_path / "pool"
    monkeypatch.setenv("NEWS_POOL_DIR", str(pool))
    return pool
