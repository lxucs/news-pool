from __future__ import annotations

from pathlib import Path

import pytest

from newsviewer import cli, lifecycle
from newsviewer.lifecycle import ServerInfo


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_missing_pool_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "up", "--pool", str(tmp_path / "none"))
    assert code == 1 and "news-digest" in err


def test_bad_arguments_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys)[0] == 1
    assert run(capsys, "up", "--port", "abc")[0] == 1
    assert run(capsys, "up", "--pool", str(tmp_path), "--port", "70000")[0] == 1
    code, _, err = run(capsys, "up", "--pool", str(tmp_path), "--run", "20990101-000000")
    assert code == 1 and "no run" in err


def test_up_prints_the_url_with_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "runs" / "20261022-080000"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    info = ServerInfo(1, 8765, "http://127.0.0.1:8765/", str(tmp_path), "i", "1.0.0", "t")
    calls: list[tuple[Path, int, float]] = []

    def fake_up(pool: Path, port: int, timeout_s: float) -> tuple[ServerInfo, bool]:
        calls.append((pool, port, timeout_s))
        return info, False

    monkeypatch.setattr(lifecycle, "up", fake_up)
    code, out, _ = run(capsys, "up", "--pool", str(tmp_path), "--run", str(run_dir))
    assert code == 0
    assert "url: http://127.0.0.1:8765/#/run/20261022-080000" in out
    assert out.strip().splitlines()[-1].startswith("[nv] next:")
    assert calls == [(tmp_path.resolve(), 8765, 10.0)]


def test_status_and_down_when_nothing_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "status", "--pool", str(tmp_path))
    assert code == 0 and "not running" in out
    code, out, _ = run(capsys, "down", "--pool", str(tmp_path))
    assert code == 0 and "not running" in out


def test_unexpected_errors_exit_5_with_a_crash_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(pool: Path, port: int, timeout_s: float) -> tuple[ServerInfo, bool]:
        raise RuntimeError("boom")

    monkeypatch.setattr(lifecycle, "up", boom)
    code, _, err = run(capsys, "up", "--pool", str(tmp_path))
    assert code == 5 and "boom" in err
    log = tmp_path / "viewer" / "nv-error.log"
    assert "RuntimeError" in log.read_text(encoding="utf-8")
