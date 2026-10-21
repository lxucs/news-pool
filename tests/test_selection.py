from __future__ import annotations

import pytest

from newsdigest.config import Feed
from newsdigest.errors import UsageError
from newsdigest.selection import build_registry, parse_id_list, select_sources

FEEDS = [
    Feed("qbitai", "量子位", "https://www.qbitai.com/feed"),
    Feed("aiera", "新智元", "https://www.aiera.com.cn/feed"),
    Feed("huxiu", "虎嗅", "https://www.huxiu.com/rss/0.xml", enabled=False),
]
REGISTRY = build_registry(FEEDS)


def ids(sources: list) -> list[str]:
    return [s.id for s in sources]


def test_rss_group_expands_to_enabled_feeds() -> None:
    assert ids(select_sources(["rss", "hn"], None, None, REGISTRY)) == ["qbitai", "aiera", "hn"]


def test_only_replaces_profile_list_and_skip_removes() -> None:
    assert ids(select_sources(["rss"], ["qbitai", "gdelt"], None, REGISTRY)) == ["qbitai", "gdelt"]
    assert ids(select_sources(["rss", "hn"], None, ["aiera"], REGISTRY)) == ["qbitai", "hn"]


def test_none_selects_nothing() -> None:
    assert select_sources(["rss"], ["none"], None, REGISTRY) == []


def test_unknown_id_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="nd.py sources"):
        select_sources(["rss"], ["jiqizhixin"], None, REGISTRY)
    with pytest.raises(UsageError):
        select_sources(["rss"], None, ["typo"], REGISTRY)


def test_disabled_feed_named_explicitly_is_an_error_but_silently_skipped_in_profile() -> None:
    with pytest.raises(UsageError, match="disabled"):
        select_sources(["rss"], ["huxiu"], None, REGISTRY)
    assert ids(select_sources(["huxiu", "hn"], None, None, REGISTRY)) == ["hn"]


def test_parse_id_list() -> None:
    assert parse_id_list(None) is None
    assert parse_id_list(" qbitai, hn ,,") == ["qbitai", "hn"]
