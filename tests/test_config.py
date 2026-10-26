from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsdigest.config import (
    category_names,
    deep_merge,
    load_categories,
    load_feeds,
    load_settings,
    load_tags,
    load_tiers,
    resource_path,
)
from newsdigest.errors import UsageError
from newsdigest.paths import EXAMPLE_PROFILE_DIR, REFERENCES_DIR


def test_deep_merge_merges_dicts_replaces_lists_drops_comments() -> None:
    base = {"a": {"x": 1, "y": 2}, "l": [1, 2], "_comment": "c"}
    assert deep_merge(base, {"a": {"y": 3}, "l": [9], "_note": "n"}) == {
        "a": {"x": 1, "y": 3},
        "l": [9],
    }


def test_example_profile_merges_over_defaults() -> None:
    s = load_settings(EXAMPLE_PROFILE_DIR)
    assert s["name"] == "ai-zh"
    assert s["sources"] == ["rss", "gnews"]
    assert s["per_source_limit"] == 10
    assert s["http"]["timeout_s"] == 20
    assert "_comment" not in s


def test_missing_profile_points_to_init(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="nd.py init"):
        load_settings(tmp_path / "nope")


def test_broken_profile_json_reports_position(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{"interests": "x",\n "queries": [,]}', "utf-8")
    with pytest.raises(UsageError, match=r"config\.json:2:\d+: invalid JSON"):
        load_settings(tmp_path)


def test_non_utf8_profile_is_usage_error(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_bytes('{"interests": "中文"}'.encode("gbk"))
    with pytest.raises(UsageError, match="not valid UTF-8"):
        load_settings(tmp_path)


def test_non_utf8_tags_file_is_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "tags.txt"
    path.write_bytes("大模型\n".encode("gbk"))
    with pytest.raises(UsageError, match="not valid UTF-8"):
        load_tags(path)


def test_unreadable_tags_file_is_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "tags.txt"
    path.mkdir()  # 存在，但读取时抛 OSError（IsADirectoryError）
    with pytest.raises(UsageError, match="cannot read"):
        load_tags(path)


def test_profile_needs_interests(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{"queries": []}', "utf-8")
    with pytest.raises(UsageError, match="interests"):
        load_settings(tmp_path)


def test_resource_path_prefers_profile_copy(tmp_path: Path) -> None:
    assert resource_path(tmp_path, "tags.txt") == REFERENCES_DIR / "tags.txt"
    (tmp_path / "tags.txt").write_text("x\n", "utf-8")
    assert resource_path(tmp_path, "tags.txt") == tmp_path / "tags.txt"


def test_builtin_feeds_load_with_disabled_entries() -> None:
    feeds = load_feeds(REFERENCES_DIR / "feeds.json")
    ids = [f.id for f in feeds]
    assert "qbitai" in ids and len(ids) == len(set(ids))
    assert any(not f.enabled for f in feeds)


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"id": "rss", "name": "x", "url": "https://a.example.com/feed"}, "reserved"),
        ({"id": "Bad Id", "name": "x", "url": "https://a.example.com/feed"}, r"\[a-z0-9_-\]"),
        ({"id": "ok", "name": "x", "url": "ftp://a.example.com/feed"}, "http"),
        ({"id": "ok", "name": "", "url": "https://a.example.com/feed"}, "name"),
    ],
)
def test_load_feeds_rejects_bad_entries(tmp_path: Path, entry: dict, message: str) -> None:
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps([entry]), "utf-8")
    with pytest.raises(UsageError, match=message):
        load_feeds(path)


def test_load_feeds_rejects_duplicate_ids(tmp_path: Path) -> None:
    entry = {"id": "a", "name": "A", "url": "https://a.example.com/feed"}
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps([entry, entry]), "utf-8")
    with pytest.raises(UsageError, match="duplicate"):
        load_feeds(path)


def test_builtin_categories_tags_and_tiers() -> None:
    names = category_names(load_categories(REFERENCES_DIR / "categories.json"))
    assert names[0] == "AI" and names[-1] == "其他" and len(names) == 13
    assert {"大模型", "Agent", "MoE"} <= load_tags(REFERENCES_DIR / "tags.txt")
    assert load_tiers(REFERENCES_DIR / "source_tiers.json")["by_domain"]["reuters.com"] == 1


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"window": 24}, "`window` must be an object"),
        ({"window": {"max_hours": "72"}}, "`window.max_hours` must be a number"),
        ({"leads": {"workers": "8"}}, "`leads.workers` must be a number"),
        ({"http": {"retries": True}}, "`http.retries` must be a number"),
        ({"per_source_limit": "50"}, "`per_source_limit` must be a number"),
        ({"tz": 8}, "`tz` must be a string"),
        ({"sources": "rss"}, "`sources` must be a list"),
    ],
)
def test_settings_types_follow_defaults(tmp_path: Path, extra: dict, message: str) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"interests": "x", "queries": ["q"], **extra}), "utf-8"
    )
    with pytest.raises(UsageError, match=message) as info:
        load_settings(tmp_path)
    assert "config.json" in str(info.value)


def test_settings_accept_ints_for_float_defaults_and_nested_overrides(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {"interests": "x", "queries": ["q"], "min_importance": 1, "leads": {"workers": 2}}
        ),
        "utf-8",
    )
    s = load_settings(tmp_path)
    assert s["min_importance"] == 1 and s["leads"]["workers"] == 2 and s["leads"]["max"] == 30
