"""Source payload → candidate rows. Pure functions: text in, rows out; no network here."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone, tzinfo
from typing import Any
from xml.etree import ElementTree

from .normalize import domain_of, parse_time, strip_html

Candidate = dict[str, Any]

WSCN_SOURCE_NAME = "华尔街见闻"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"
WSCN_ARTICLE_URL = "https://wallstreetcn.com/articles/{}"
MRSS_NS = "{http://search.yahoo.com/mrss/}"
QUOTE_CHARS = 80  # how much of an unparsable body an error quotes

_XML_DECL_RE = re.compile(r"\A\s*<\?xml[^>]*\?>")
_GDELT_SEEN_RE = re.compile(r"\d{8}T\d{6}Z")
_META_TAG_RE = re.compile(r"<meta\s[^>]*>", re.I)
_ATTR_RE = re.compile(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_JSON_LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_TIME_TAG_RE = re.compile(r"""<time\b[^>]*?\sdatetime\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
VISIBLE_TIME_WINDOW = 300  # chars after a date element in which its time element must start
CAPTCHA_MARKER = "wappoc_appmsgcaptcha"  # WeChat's verification page, served instead of an article
# Elements whose class mentions date/time (`<span class="date">`); the text is read up to the
# first closing tag of the same name, and the lookahead lets nested ones match as well.
_DATE_TIME_ELEMENT_RE = re.compile(
    r"""<(\w+)\b[^>]*?\sclass\s*=\s*(["'])([^"']*(?:date|time)[^"']*)\2[^>]*>(?=(.*?)</\1\s*>)""",
    re.I | re.S,
)
_VISIBLE_DATE_RE = re.compile(r"(?<!\d)(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})(?!\d)")
_VISIBLE_CLOCK_RE = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])")
# Publish-time meta keys tried after the WeChat `ct` and `article:published_time`, in order.
_META_TIME_KEYS = ("datepublished", "pubdate", "publishdate", "publish-date", "og:release_date")
_JS_HEX_RE = re.compile(r"\\x([0-9a-fA-F]{2})")
# mp.weixin.qq.com article pages carry their metadata in inline script variables.
_WECHAT = {
    "title": (r"var\s+msg_title\s*=\s*'(.*?)'\s*\.html", r'var\s+msg_title\s*=\s*"(.*?)"'),
    "source": (r'var\s+nickname\s*=\s*htmlDecode\("(.*?)"\)', r'var\s+nickname\s*=\s*"(.*?)"'),
    "ct": (r'var\s+ct\s*=\s*"?(\d{10})"?',),
    "desc": (r'var\s+msg_desc\s*=\s*htmlDecode\("(.*?)"\)', r'var\s+msg_desc\s*=\s*"(.*?)"'),
}


class ParseError(Exception):
    """The payload is not in the shape this adapter expects (e.g. an HTML block page)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_xml(text: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(_XML_DECL_RE.sub("", text, count=1))
    except ElementTree.ParseError as exc:
        raise ParseError(f"not XML ({exc})") from None


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ParseError(f"not JSON: {text.strip()[:QUOTE_CHARS]!r}") from None


def _child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for child in node:
        if _local(child.tag) == name:
            return child
    return None


def _text(node: ElementTree.Element, *names: str) -> str:
    """Text of the first non-empty child among `names`, tried in that order."""
    for name in names:
        child = _child(node, name)
        if child is not None and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def _entry_link(node: ElementTree.Element) -> str:
    fallback = ""
    for child in node:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if href is None:  # RSS: <link>url</link>
            return (child.text or "").strip()
        if (child.get("rel") or "alternate") == "alternate":  # Atom
            return href.strip()
        fallback = fallback or href.strip()
    return fallback


def _author(node: ElementTree.Element) -> str:
    for name in ("creator", "author"):
        child = _child(node, name)
        if child is not None:
            return _text(child, "name") or (child.text or "").strip()
    return ""


def _image(node: ElementTree.Element) -> str:
    for child in node:
        if _local(child.tag) == "enclosure" and (child.get("type") or "").startswith("image/"):
            return child.get("url") or ""
        if child.tag in (MRSS_NS + "thumbnail", MRSS_NS + "content") and child.get("url"):
            return child.get("url") or ""
    return ""


def parse_feed(text: str) -> tuple[str, list[Candidate]]:
    """RSS 2.0, RSS 1.0 (RDF) or Atom → (feed title, rows). The caller names the source."""
    root = _parse_xml(text)
    kind = _local(root.tag)
    if kind not in ("rss", "feed", "RDF"):
        raise ParseError(f"not an RSS/Atom feed (root element <{kind}>)")
    channel = _child(root, "channel") if kind != "feed" else None
    feed_title = _text(channel if channel is not None else root, "title")
    rows: list[Candidate] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = strip_html(_text(node, "title"))
        url = _entry_link(node)
        if not title or not url:
            continue
        rows.append(
            {
                "url": url,
                "title": title,
                "author": _author(node),
                "published_at": _text(node, "pubDate", "published", "updated", "date"),
                "snippet": strip_html(_text(node, "description", "summary", "encoded", "content")),
                "image": _image(node),
            }
        )
    return feed_title, rows


def parse_gnews(text: str) -> list[Candidate]:
    root = _parse_xml(text)
    if _local(root.tag) != "rss":
        raise ParseError(f"not a Google News RSS feed (root element <{_local(root.tag)}>)")
    rows: list[Candidate] = []
    for item in root.iter("item"):
        title = strip_html(_text(item, "title"))
        url = _text(item, "link")
        if not title or not url:
            continue
        source = _text(item, "source")
        suffix = f" - {source}"
        if source and title.endswith(suffix):
            title = title[: -len(suffix)].rstrip()
        snippet = strip_html(_text(item, "description"))
        if title in snippet:  # the description only repeats the headline and the outlet
            snippet = ""
        rows.append(
            {
                "url": url,
                "title": title,
                "source": source,
                "author": "",
                "published_at": _text(item, "pubDate"),
                "snippet": snippet,
                "image": "",
            }
        )
    return rows


def parse_hn(text: str) -> list[Candidate]:
    data = _parse_json(text)
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list):
        raise ParseError("no `hits` list in the HN response")
    rows: list[Candidate] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "")
        if not url and hit.get("objectID"):
            url = HN_ITEM_URL.format(hit["objectID"])
        if not title or not url:
            continue
        rows.append(
            {
                "url": url,
                # HN only aggregates; the linked site is the real source and decides the tier.
                "source": domain_of(url) or "news.ycombinator.com",
                "title": title,
                "author": str(hit.get("author") or ""),
                "published_at": hit.get("created_at_i") or hit.get("created_at") or "",
                "snippet": strip_html(str(hit.get("story_text") or "")),
                "image": "",
            }
        )
    return rows


def parse_wscn(text: str) -> list[Candidate]:
    data = _parse_json(text)
    payload = data.get("data") if isinstance(data, dict) else None
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ParseError("no `data.items` list in the wallstcn response")
    rows: list[Candidate] = []
    seen: set[str] = set()
    for art in items:
        if not isinstance(art, dict):
            continue
        title = str(art.get("title") or "").strip()
        url = str(art.get("uri") or "")
        if not url.startswith("http"):
            url = WSCN_ARTICLE_URL.format(art["id"]) if art.get("id") else ""
        if not title or not url or url in seen:  # the API repeats entries
            continue
        seen.add(url)
        author = art.get("author")
        rows.append(
            {
                "url": url,
                "title": title,
                "source": WSCN_SOURCE_NAME,
                "author": str(author.get("display_name") or "") if isinstance(author, dict) else "",
                "published_at": art.get("display_time") or "",
                "snippet": strip_html(str(art.get("content_short") or "")),
                "image": "",
            }
        )
    return rows


def parse_gdelt(text: str) -> list[Candidate]:
    data = _parse_json(text)
    if data == {}:  # GDELT answers {} when nothing matches
        return []
    articles = data.get("articles") if isinstance(data, dict) else None
    if not isinstance(articles, list):
        raise ParseError("no `articles` list in the GDELT response")
    rows: list[Candidate] = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        title = str(art.get("title") or "").strip()
        url = str(art.get("url") or "")
        if not title or not url:
            continue
        seen = str(art.get("seendate") or "")
        published = ""
        if _GDELT_SEEN_RE.fullmatch(seen):
            stamp = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            published = stamp.isoformat()
        rows.append(
            {
                "url": url,
                "title": title,
                "source": str(art.get("domain") or ""),
                "author": "",
                "published_at": published,
                "snippet": "",
                "image": str(art.get("socialimage") or ""),
            }
        )
    return rows


def _meta(html_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in _META_TAG_RE.findall(html_text):
        attrs: dict[str, str] = {}
        for m in _ATTR_RE.finditer(tag):
            attrs[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3) or ""
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key and "content" in attrs and key not in out:
            out[key] = html.unescape(attrs["content"]).strip()
    return out


def _wechat(html_text: str, key: str) -> str:
    for pattern in _WECHAT[key]:
        m = re.search(pattern, html_text, re.S)
        if m:
            value = _JS_HEX_RE.sub(lambda h: chr(int(h.group(1), 16)), m.group(1))
            return html.unescape(value).strip()
    return ""


def _visible_time(html_text: str) -> str | None:
    """`YYYY-MM-DD[ HH:MM:SS]` from visible date/time elements, e.g. qbitai's
    `<span class="date">2026-10-21</span><span class="time">10:37:39</span>`."""
    found = [
        (m.start(), m.group(3).lower(), strip_html(m.group(4)))
        for m in _DATE_TIME_ELEMENT_RE.finditer(html_text)
    ]
    for i, (start, classes, text) in enumerate(found):
        date = _VISIBLE_DATE_RE.search(text) if "date" in classes else None
        if date is None:
            continue
        year, month, day = date.groups()
        out = f"{year}-{int(month):02d}-{int(day):02d}"
        for pos, other, other_text in found[i + 1 :]:
            if pos - start > VISIBLE_TIME_WINDOW:
                break
            clock = _VISIBLE_CLOCK_RE.search(other_text) if "time" in other else None
            if clock:
                hour, minute, second = clock.groups("00")
                return f"{out} {int(hour):02d}:{minute}:{second}"
        return out
    return None


def _publish_time(html_text: str, meta: dict[str, str], tz: tzinfo) -> datetime | None:
    """The first publish time found: WeChat `ct`, then the usual markup, most explicit first."""
    ct = _wechat(html_text, "ct")
    candidates: list[object] = [int(ct)] if ct else []
    candidates.append(meta.get("article:published_time"))
    ld = _JSON_LD_DATE_RE.search(html_text)
    candidates.append(ld.group(1) if ld else None)
    candidates += [meta.get(key) for key in _META_TIME_KEYS]
    tag = _TIME_TAG_RE.search(html_text)
    candidates.append((tag.group(1) or tag.group(2)) if tag else None)
    candidates.append(_visible_time(html_text))  # last: a date shown on the page, no zone
    return next((t for t in (parse_time(c, tz) for c in candidates) if t is not None), None)


def is_captcha_page(final_url: str, html_text: str) -> bool:
    return CAPTCHA_MARKER in final_url or CAPTCHA_MARKER in html_text


def parse_article_page(html_text: str, final_url: str, tz: tzinfo) -> Candidate:
    """Title / outlet / time / description of one article page (WeChat or ordinary)."""
    meta = _meta(html_text)
    title_m = _TITLE_RE.search(html_text)
    title = (
        _wechat(html_text, "title")
        or meta.get("og:title", "")
        or (html.unescape(title_m.group(1)) if title_m else "")
    )
    source = _wechat(html_text, "source") or meta.get("og:site_name", "") or domain_of(final_url)
    published = _publish_time(html_text, meta, tz)
    snippet = (
        _wechat(html_text, "desc") or meta.get("og:description", "") or meta.get("description", "")
    )
    return {
        "url": final_url,
        "title": strip_html(title),
        "source": source,
        "author": meta.get("author", ""),
        "published_at": published.isoformat() if published else "",
        "snippet": strip_html(snippet),
        "image": meta.get("og:image", ""),
    }
