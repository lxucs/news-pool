from __future__ import annotations

import argparse
import io
import socket
import sys
from pathlib import Path

import pytest

from newsdigest import cli, console, paths
from newsdigest.errors import ValidationFailed


def test_network_is_blocked() -> None:
    with pytest.raises(BaseException, match="network"):
        socket.create_connection(("example.com", 80))


def test_resolve_pool_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEWS_POOL_DIR", str(tmp_path / "env"))
    assert paths.resolve_pool(str(tmp_path / "cli")) == (tmp_path / "cli").resolve()
    assert paths.resolve_pool(None) == (tmp_path / "env").resolve()
    monkeypatch.delenv("NEWS_POOL_DIR")
    assert paths.resolve_pool(None) == (Path.home() / ".news-pool").resolve()


def test_missing_command_is_usage_error() -> None:
    assert cli.main([]) == 1


def _parser_with(handler: object) -> argparse.ArgumentParser:
    parser = cli.NdParser(prog="nd.py")
    sub = parser.add_subparsers(dest="command", parser_class=cli.NdParser)
    cmd = sub.add_parser("boom")
    cmd.add_argument("--run")
    cmd.set_defaults(handler=handler)
    return parser


def test_nd_error_maps_to_its_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(args: argparse.Namespace) -> int:
        raise ValidationFailed("bad triage")

    monkeypatch.setattr(cli, "build_parser", lambda: _parser_with(handler))
    assert cli.main(["boom"]) == 3


def test_internal_error_logs_traceback_and_exits_5(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(args: argparse.Namespace) -> int:
        raise KeyError("kaboom")

    monkeypatch.setattr(cli, "build_parser", lambda: _parser_with(handler))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert cli.main(["boom", "--run", str(run_dir)]) == 5
    err = capsys.readouterr().err
    assert "internal error in boom: KeyError" in err
    assert "do not edit" in err
    log = (run_dir / "nd-error.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "kaboom" in log


def test_permission_error_is_a_usage_error_not_a_skill_bug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(args: argparse.Namespace) -> int:
        raise PermissionError(13, "Permission denied", "/path/to/pool/runs")

    monkeypatch.setattr(cli, "build_parser", lambda: _parser_with(handler))
    assert cli.main(["boom"]) == 1
    err = capsys.readouterr().err
    assert "permission denied: /path/to/pool/runs" in err
    assert "must be writable" in err and "skill bug" not in err


def test_output_streams_are_reconfigured_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_out, raw_err = io.BytesIO(), io.BytesIO()
    out = io.TextIOWrapper(raw_out, encoding="cp1252", errors="strict")
    err = io.TextIOWrapper(raw_err, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    console.use_utf8()
    print("新闻 ✓")
    print("错误", file=sys.stderr)
    out.flush()
    err.flush()
    assert raw_out.getvalue().decode("utf-8") == "新闻 ✓\n"
    assert raw_err.getvalue().decode("utf-8") == "错误\n"


def test_use_utf8_leaves_streams_without_reconfigure_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    console.use_utf8()  # must not raise


def test_skill_md_quotes_the_message_check_prints() -> None:
    skill = (paths.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "triage.json changed after `leads` ran" in skill
