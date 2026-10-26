"""唯一读取系统时钟的地方，方便测试把时间固定住。"""

from __future__ import annotations

from datetime import datetime, tzinfo


def now(tz: tzinfo) -> datetime:
    return datetime.now(tz)
