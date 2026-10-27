"""URL、时间和文本的规范化——这些规则只在这里写一份。"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone, tzinfo
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ID_HEX_CHARS = 12  # schema：条目 id = sha1(规范化 URL) 的前 12 位十六进制
GOOGLE_NEWS_HOST = "news.google.com"  # Google News 条目的链接是这里的跳转地址

TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "igshid",
        "spm",
        "from",
        "ref",
        "ref_src",
        "referrer",
        "share_token",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "vero_id",
        "s_cid",
    }
)

TIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%d %B %Y",
)

_TZ_RE = re.compile(r"([+-])(\d{1,2})(?::?(\d{2}))?")
_EPOCH_RE = re.compile(r"\d{9,14}(?:\.\d+)?")
_MS_THRESHOLD = 1e11  # 比这个大的 epoch 值按毫秒处理
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(
    "[\\s　!-/:-@\\[-`{-~、。，．！？；：\"'\\u201c\\u201d\\u2018\\u2019"
    "（）《》〈〉【】〔〕…—～·_|-]+"
)
_CJK_RANGE = "㐀-䶿一-鿿豈-﫿"  # 当作文字处理的 CJK 区段（detect_lang、slug、token）
_CJK_RE = re.compile(f"[{_CJK_RANGE}]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+-]*")
# slug 保留 CJK 字符和 ASCII 字母数字，其余字符都当作分隔。标题去重用的 token：拉丁字母 /
# 数字词和单个 CJK 字符（数字单独成 token，所以 提升2倍 ≠ 提升3倍）。
_SLUG_SEPARATE_RE = re.compile(f"[^0-9A-Za-z{_CJK_RANGE}]+")
_TITLE_TOKEN_RE = re.compile(rf"[A-Za-z][A-Za-z0-9.+-]*|[0-9]+|[{_CJK_RANGE}]")
_FRACTION_RE = re.compile(r"(?<=\d:\d\d)\.(\d+)")
ISO_FRACTION_DIGITS = 6  # Python 3.9 的 fromisoformat 只接受恰好 3 位或 6 位


def parse_tz(text: str) -> timezone:
    s = (text or "").strip()
    if s.upper() in {"UTC", "Z", "GMT"}:
        return timezone.utc
    m = _TZ_RE.fullmatch(s)
    if not m:
        raise ValueError(f"cannot parse timezone {text!r}; use an offset like +08:00")
    hours, minutes = int(m.group(2)), int(m.group(3) or 0)
    if hours > 14 or minutes > 59:
        raise ValueError(f"timezone offset out of range: {text!r}")
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_time(value: object, default_tz: tzinfo) -> datetime | None:
    """解析 epoch 秒 / 毫秒、ISO 8601、RFC 2822 和几种常见格式。不带时区的按 default_tz。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(float(value), default_tz)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if _EPOCH_RE.fullmatch(s):
        return _from_epoch(float(s), default_tz)
    if s[-1] in "Zz":
        s = s[:-1] + "+00:00"
    parsed = _try_iso(s) or _try_rfc2822(s) or _try_formats(s)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_tz)


def from_iso(text: str) -> datetime:
    """读回本包写出的 ISO 时间戳（总是带时区偏移）。"""
    return datetime.fromisoformat(text)


def _from_epoch(n: float, tz: tzinfo) -> datetime | None:
    if n > _MS_THRESHOLD:
        n /= 1000.0
    if n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n, tz=tz)
    except (OverflowError, OSError, ValueError):
        return None


def _try_iso(s: str) -> datetime | None:
    s = _FRACTION_RE.sub(
        lambda m: "." + m.group(1)[:ISO_FRACTION_DIGITS].ljust(ISO_FRACTION_DIGITS, "0"), s
    )
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _try_rfc2822(s: str) -> datetime | None:
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        return None


def _try_formats(s: str) -> datetime | None:
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    )
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def url_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:ID_HEX_CHARS]


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def is_google_news(url: str) -> bool:
    return domain_of(url) == GOOGLE_NEWS_HOST


def normalize_title(title: str) -> str:
    return _PUNCT_RE.sub("", title or "").lower()


def slugify_title(title: str, max_chars: int) -> str:
    """可安全用作文件名、小写、用短横线分隔的 slug（见 schema.md 的条目文件命名）。"""
    slug = _SLUG_SEPARATE_RE.sub("-", (title or "").lower()).strip("-")
    if len(slug) > max_chars:
        slug = slug[:max_chars].rstrip("-")
    return slug or "untitled"


def title_tokens(title: str) -> tuple[str, ...]:
    """标题的去重键：经 normalize_title 处理后的拉丁字母 / 数字词和单个 CJK 字符。"""
    return tuple(_TITLE_TOKEN_RE.findall(normalize_title(title)))


def contains_run(inner: tuple[str, ...], outer: tuple[str, ...]) -> bool:
    """`inner` 作为连续的 token（而不是分散地）出现在 `outer` 里时为 True。"""
    if not inner or len(inner) > len(outer):
        return False
    # 两边补空格，让匹配只能在 token 边界处开始和结束。
    return f" {' '.join(inner)} " in f" {' '.join(outer)} "


def detect_lang(text: str) -> str:
    cjk = len(_CJK_RE.findall(text or ""))
    words = len(_LATIN_WORD_RE.findall(text or ""))
    return "zh" if cjk >= 2 and cjk >= words else "en"


def strip_html(text: str) -> str:
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()
