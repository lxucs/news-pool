"""The one place that reads the wall clock, so tests can pin it."""

from __future__ import annotations

from datetime import datetime, tzinfo


def now(tz: tzinfo) -> datetime:
    return datetime.now(tz)
