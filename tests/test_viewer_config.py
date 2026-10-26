from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from newsviewer import __version__
from newsviewer.config import load_settings
from newsviewer.errors import UsageError
from newsviewer.paths import NV_SCRIPT, existing_pool, resolve_pool


def test_entry_point_runs_under_isolated_python() -> None:
    done = subprocess.run(
        [sys.executable, "-I", str(NV_SCRIPT), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == __version__


def test_pool_resolution_prefers_the_flag_then_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEWS_POOL_DIR", str(tmp_path / "env"))
    assert resolve_pool(str(tmp_path / "flag")) == (tmp_path / "flag").resolve()
    assert resolve_pool(None) == (tmp_path / "env").resolve()


def test_a_missing_pool_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="news-digest"):
        existing_pool(str(tmp_path / "nope"))


def test_defaults_load_and_the_pool_config_overrides_them(tmp_path: Path) -> None:
    (tmp_path / "viewer").mkdir()
    assert load_settings(tmp_path)["port"] == 8765
    (tmp_path / "viewer" / "config.json").write_text(
        json.dumps({"port": 9000, "_note": "comment"}), encoding="utf-8"
    )
    settings = load_settings(tmp_path)
    assert settings["port"] == 9000
    assert settings["idle_minutes"] == 120
    assert "_note" not in settings and "_comment" not in settings


def test_a_broken_config_names_file_line_and_column(tmp_path: Path) -> None:
    (tmp_path / "viewer").mkdir()
    (tmp_path / "viewer" / "config.json").write_text('{"port": }', encoding="utf-8")
    with pytest.raises(UsageError, match=r"config\.json:1:\d+"):
        load_settings(tmp_path)


def test_a_non_numeric_setting_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "viewer").mkdir()
    (tmp_path / "viewer" / "config.json").write_text(
        json.dumps({"idle_minutes": "soon"}), encoding="utf-8"
    )
    with pytest.raises(UsageError, match="idle_minutes"):
        load_settings(tmp_path)
