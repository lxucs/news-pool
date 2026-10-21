"""The source registry (built-in adapters + feeds.json) and per-run source selection."""

from __future__ import annotations

from dataclasses import dataclass

from .adapters import WSCN_SOURCE_NAME
from .config import PROFILE_CONFIG, Feed
from .errors import UsageError

GROUP_RSS = "rss"
SELECT_NONE = "none"
KIND_FEED = "feed"
KIND_SEARCH = "search"
PROFILE_ORIGIN = f"the profile's `sources` ({PROFILE_CONFIG})"


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str  # KIND_FEED or KIND_SEARCH
    adapter: str  # "rss", "wscn", "gnews", "hn" or "gdelt"
    url: str = ""
    enabled: bool = True


BUILTIN_SOURCES = (
    Source("wscn", WSCN_SOURCE_NAME, KIND_FEED, "wscn"),
    Source("gnews", "Google News 搜索", KIND_SEARCH, "gnews"),
    Source("hn", "Hacker News 搜索", KIND_SEARCH, "hn"),
    Source("gdelt", "GDELT 搜索", KIND_SEARCH, "gdelt"),
)


def build_registry(feeds: list[Feed]) -> dict[str, Source]:
    registry = {s.id: s for s in BUILTIN_SOURCES}
    for feed in feeds:
        registry[feed.id] = Source(feed.id, feed.name, KIND_FEED, "rss", feed.url, feed.enabled)
    return registry


def parse_id_list(text: str | None) -> list[str] | None:
    """`--only a,b` → ["a", "b"]; an absent flag → None."""
    if text is None:
        return None
    return [part.strip() for part in text.split(",") if part.strip()]


def unknown_ids(tokens: list[str], registry: dict[str, Source]) -> list[str]:
    return [t for t in tokens if t not in registry and t not in (SELECT_NONE, GROUP_RSS)]


def select_sources(
    configured: list[str],
    only: list[str] | None,
    skip: list[str] | None,
    registry: dict[str, Source],
) -> list[Source]:
    """--only replaces the profile's list; --skip removes from whichever list applies."""
    if only is not None:
        ids = _expand(only, registry, explicit=True, origin="--only")
    else:
        ids = _expand(configured, registry, explicit=False, origin=PROFILE_ORIGIN)
    if skip:
        dropped = set(_expand(skip, registry, explicit=False, origin="--skip"))
        ids = [i for i in ids if i not in dropped]
    return [registry[i] for i in ids]


def _expand(
    tokens: list[str], registry: dict[str, Source], *, explicit: bool, origin: str
) -> list[str]:
    ids: list[str] = []
    for token in tokens:
        if token == SELECT_NONE:
            continue
        if token == GROUP_RSS:
            ids += [s.id for s in registry.values() if s.adapter == "rss" and s.enabled]
            continue
        source = registry.get(token)
        if source is None:
            raise UsageError(
                f"unknown source {token!r} in {origin}; run `nd.py sources` for the list of ids"
            )
        if not source.enabled:
            if explicit:
                raise UsageError(f"source {token!r} ({source.name}) is disabled in feeds.json")
            continue
        ids.append(token)
    return list(dict.fromkeys(ids))
