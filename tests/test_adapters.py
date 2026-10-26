from __future__ import annotations

from datetime import timedelta, timezone

import pytest
from helpers import FIXTURES, fixture_text

from newsdigest.adapters import (
    WSCN_SOURCE_NAME,
    ParseError,
    is_captcha_page,
    parse_article_page,
    parse_feed,
    parse_gdelt,
    parse_gnews,
    parse_hn,
    parse_wscn,
)
from newsdigest.normalize import parse_time

CST = timezone(timedelta(hours=8))


def _assert_rows(rows: list[dict], *, with_source: bool) -> None:
    assert rows, "fixture produced no rows"
    for row in rows:
        assert row["url"].startswith("http")
        assert row["title"].strip()
        assert "\ufffd" not in row["title"], "mojibake: wrong charset"
        assert parse_time(row["published_at"], CST) is not None
        if with_source:
            assert row["source"]


@pytest.mark.parametrize("name", ["rss_qbitai.xml", "atom_v2ex.xml", "rss_sina.xml"])
def test_feed_fixtures_parse(name: str) -> None:
    title, rows = parse_feed(fixture_text(name))
    assert title
    assert len(rows) == 3
    _assert_rows(rows, with_source=False)


def test_atom_links_are_alternate_pages() -> None:
    _, rows = parse_feed(fixture_text("atom_v2ex.xml"))
    assert all("v2ex.com" in row["url"] for row in rows)


def test_gnews_fixture_strips_outlet_suffix() -> None:
    rows = parse_gnews(fixture_text("gnews_search.xml"))
    _assert_rows(rows, with_source=True)
    for row in rows:
        assert not row["title"].endswith(f" - {row['source']}")


def test_hn_fixture_uses_link_domain_as_source() -> None:
    rows = parse_hn(fixture_text("hn_search.json"))
    _assert_rows(rows, with_source=True)
    assert all("." in row["source"] for row in rows)


def test_wscn_fixture() -> None:
    rows = parse_wscn(fixture_text("wscn_articles.json"))
    _assert_rows(rows, with_source=True)
    assert {row["source"] for row in rows} == {WSCN_SOURCE_NAME}


@pytest.mark.skipif(
    not (FIXTURES / "gdelt_artlist.json").exists(), reason="GDELT was rate-limited at capture"
)
def test_gdelt_fixture() -> None:
    _assert_rows(parse_gdelt(fixture_text("gdelt_artlist.json")), with_source=True)


@pytest.mark.skipif(
    not (FIXTURES / "article_weixin.html").exists(), reason="no WeChat article was captured"
)
def test_wechat_article_page() -> None:
    page = parse_article_page(
        fixture_text("article_weixin.html"), "https://mp.weixin.qq.com/s/x", CST
    )
    assert page["title"] and page["source"] and page["snippet"]
    assert parse_time(page["published_at"], CST) is not None


def test_ordinary_article_page_uses_meta_tags() -> None:
    page = parse_article_page(fixture_text("article_qbitai.html"), "https://www.qbitai.com/x", CST)
    assert page["title"]
    assert page["source"]


def test_qbitai_capture_yields_its_visible_date_and_time() -> None:
    # 从线上抓取的页面保留了 `<span class="date">` 和 `<span class="time">`
    # （见 fixtures/README.md）；页面没有机器可读的发布时间，而下方的相关文章列表里
    # 还有别的 `class="time"` span，里面只有日期。
    page = parse_article_page(fixture_text("article_qbitai.html"), "https://www.qbitai.com/x", CST)
    assert page["published_at"] == "2026-10-21T10:37:39+08:00"


def _page(body: str) -> str:
    return f"<html><head><title>T</title></head><body>{body}</body></html>"


# 页面可见日期的兜底解析。第一种是 qbitai 的真实标记，其余是手写的。
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            '<span class="date">2026-10-21</span>\n  <span class="time">10:37:39</span>',
            "2026-10-21T10:37:39+08:00",
        ),
        (
            '<span class="date">2026-10-21</span><span class="time">10:37</span>',
            "2026-10-21T10:37:00+08:00",
        ),
        ('<div class="post-date">2026/10/05</div>', "2026-10-05T00:00:00+08:00"),
        ('<p class="meta-date">发布于 2026年10月5日</p>', "2026-10-05T00:00:00+08:00"),
        ('<i class="date">2026年1月5日</i><i class="time">9:05</i>', "2026-01-05T09:05:00+08:00"),
        # 标签在前且不含日期：取后面的那个日期元素
        (
            '<span class="date-label">发布时间</span><span class="date"><b>2026-10-21</b></span>',
            "2026-10-21T00:00:00+08:00",
        ),
        # 离日期很远的时间元素属于别的内容
        (
            '<span class="date">2026-10-21</span>'
            + "<p>filler text</p>" * 40
            + '<span class="time">10:37</span>',
            "2026-10-21T00:00:00+08:00",
        ),
    ],
    ids=[
        "qbitai-date-and-time",
        "time-without-seconds",
        "slash-date",
        "chinese-date-with-prefix",
        "chinese-date-and-short-time",
        "label-before-the-date",
        "time-too-far-away",
    ],
)
def test_article_page_visible_date_fallback(body: str, expected: str) -> None:
    page = parse_article_page(_page(body), "https://news.example.com/a", CST)
    assert page["published_at"] == expected


def test_machine_readable_time_wins_over_the_visible_date() -> None:
    body = (
        '<time datetime="2026-10-20T09:30:00+08:00">Oct 20</time>'
        '<span class="date">2026-10-21</span><span class="time">10:37:39</span>'
    )
    page = parse_article_page(_page(body), "https://news.example.com/a", CST)
    assert page["published_at"] == "2026-10-20T09:30:00+08:00"


@pytest.mark.parametrize(
    "body",
    [
        "<p>no date anywhere</p>",
        '<span class="date">昨天</span><span class="time">10:37</span>',  # 只有时间不算日期
        '<span class="time">2024-03-12</span>',  # 日期只出现在时间元素里
        '<span class="date">2026-13-45</span>',  # 看着像日期，其实不是
    ],
)
def test_article_page_without_a_date_has_no_publish_time(body: str) -> None:
    page = parse_article_page(_page(body), "https://news.example.com/a", CST)
    assert page["published_at"] == ""


# 普通文章页上常见的发布时间标记。这些页面是按真实标记形态手写的最小文档
# （没有保留带这些标记的抓取页面）。
@pytest.mark.parametrize(
    "head",
    [
        '<script type="application/ld+json">{"@type":"NewsArticle",'
        '"datePublished":"2026-10-20T09:30:00+08:00"}</script>',
        '<meta itemprop="datePublished" content="2026-10-20T09:30:00+08:00">',
        '<meta name="pubdate" content="2026-10-20T09:30:00+08:00">',
        '<meta name="publishdate" content="2026-10-20T09:30:00+08:00">',
        '<meta name="publish-date" content="2026-10-20T09:30:00+08:00">',
        '<meta property="og:release_date" content="2026-10-20T09:30:00+08:00">',
        '<time class="d" datetime="2026-10-20T09:30:00+08:00">Oct 20</time>',
    ],
)
def test_article_page_publish_time_fallbacks(head: str) -> None:
    html = f"<html><head><title>T</title>{head}</head><body></body></html>"
    page = parse_article_page(html, "https://news.example.com/a", CST)
    assert parse_time(page["published_at"], CST) == parse_time("2026-10-20T09:30:00+08:00", CST)


def test_article_published_time_meta_wins_over_fallbacks() -> None:
    html = (
        '<meta property="article:published_time" content="2026-10-20T01:00:00+08:00">'
        '<meta name="pubdate" content="2026-10-19T01:00:00+08:00">'
    )
    page = parse_article_page(html, "https://news.example.com/a", CST)
    assert parse_time(page["published_at"], CST) == parse_time("2026-10-20T01:00:00+08:00", CST)


def test_captcha_page_is_recognised() -> None:
    assert is_captcha_page("https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?x=1", "")
    assert not is_captcha_page("https://www.qbitai.com/x", fixture_text("article_qbitai.html"))


# 反例：遇到拦截页或接口变了时，解析器看到的就是这些内容。
@pytest.mark.parametrize("text", ["<html><body>blocked</body></html>", "plain text, not XML"])
def test_feed_rejects_non_feeds(text: str) -> None:
    with pytest.raises(ParseError):
        parse_feed(text)


@pytest.mark.parametrize(
    "parser, text",
    [(parse_hn, "{}"), (parse_wscn, '{"data": {}}'), (parse_gdelt, "Please limit requests")],
)
def test_json_adapters_reject_unexpected_shapes(parser: object, text: str) -> None:
    with pytest.raises(ParseError):
        parser(text)  # type: ignore[operator]
