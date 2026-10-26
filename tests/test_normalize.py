from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from newsdigest.normalize import (
    canonicalize_url,
    contains_run,
    detect_lang,
    domain_of,
    normalize_title,
    parse_time,
    parse_tz,
    slugify_title,
    strip_html,
    title_tokens,
    url_id,
)

CST = timezone(timedelta(hours=8))


def test_canonicalize_drops_tracking_www_fragment_and_sorts_query() -> None:
    url = "http://WWW.Reuters.com/tech/a/?utm_source=x&b=2&fbclid=y&a=1#top"
    assert canonicalize_url(url) == "https://reuters.com/tech/a?a=1&b=2"


def test_canonicalize_adds_scheme_and_keeps_root_path() -> None:
    assert canonicalize_url("example.com") == "https://example.com/"


def test_url_id_is_stable_12_hex() -> None:
    a = url_id(canonicalize_url("https://www.reuters.com/x/?utm_medium=social"))
    b = url_id(canonicalize_url("https://reuters.com/x"))
    assert a == b and len(a) == 12 and int(a, 16) >= 0


def test_domain_of_strips_www_and_port() -> None:
    assert domain_of("https://www.Example.com:8443/a") == "example.com"
    assert domain_of("not a url") == ""


@pytest.mark.parametrize(
    "value, expected",
    [
        (1792476000, datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)),
        ("1792476000000", datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)),
        ("2026-10-20T09:30:00+08:00", datetime(2026, 10, 20, 9, 30, tzinfo=CST)),
        ("2026-10-20T01:30:00Z", datetime(2026, 10, 20, 1, 30, tzinfo=timezone.utc)),
        ("2026-10-20T09:30:00+0800", datetime(2026, 10, 20, 9, 30, tzinfo=CST)),
        ("Tue, 20 Oct 2026 01:30:00 GMT", datetime(2026, 10, 20, 1, 30, tzinfo=timezone.utc)),
        ("2026/10/20 09:30:00", datetime(2026, 10, 20, 9, 30, tzinfo=CST)),
        ("2026-10-20 09:30", datetime(2026, 10, 20, 9, 30, tzinfo=CST)),
        # Python 3.9 的 fromisoformat 只接受 3 位或 6 位小数秒。
        ("2026-10-20T09:30:00.5+08:00", datetime(2026, 10, 20, 9, 30, 0, 500000, tzinfo=CST)),
        ("2026-10-20T09:30:00.1234+08:00", datetime(2026, 10, 20, 9, 30, 0, 123400, tzinfo=CST)),
        (
            "2026-10-20T09:30:00.1234567Z",
            datetime(2026, 10, 20, 9, 30, 0, 123456, tzinfo=timezone.utc),
        ),
        ("2026-10-21 08:00:00 +0800", datetime(2026, 10, 21, 8, 0, tzinfo=CST)),
    ],
)
def test_parse_time_accepts_common_shapes(value: object, expected: datetime) -> None:
    got = parse_time(value, CST)
    assert got is not None and got.tzinfo is not None
    assert got == expected


@pytest.mark.parametrize("value", [None, "", "yesterday", True, {"a": 1}, 0])
def test_parse_time_rejects_garbage(value: object) -> None:
    assert parse_time(value, CST) is None


@pytest.mark.parametrize(
    "text, hours", [("+08:00", 8), ("+0800", 8), ("+8", 8), ("-05:30", -5.5), ("UTC", 0)]
)
def test_parse_tz(text: str, hours: float) -> None:
    assert parse_tz(text).utcoffset(None) == timedelta(hours=hours)


def test_parse_tz_rejects_names() -> None:
    with pytest.raises(ValueError):
        parse_tz("Asia/Shanghai")


def test_normalize_title_ignores_punctuation_and_case() -> None:
    assert normalize_title("OpenAI 发布新模型！") == normalize_title("openai发布新模型")


def test_normalize_title_strips_curly_quotes() -> None:
    assert normalize_title("“A” ‘b’") == normalize_title("ab")
    assert normalize_title("OpenAI 发布“新”模型") == normalize_title("OpenAI发布新模型")


def test_detect_lang() -> None:
    assert detect_lang("OpenAI 发布新一代推理模型") == "zh"
    assert detect_lang("Anthropic raises $5B at a $200B valuation") == "en"


@pytest.mark.parametrize(
    "text, lang",
    [
        ("OpenAI发布GPT-5", "zh"),  # 带品牌名的中文短标题
        ("苹果发布iPhone 17 Pro Max", "zh"),
        ("Apple 发布 new models launch", "en"),  # 英文标题里夹着几个 CJK 字符
        ("发 OpenAI", "en"),  # 只有一个 CJK 字符不够
        ("", "en"),
    ],
)
def test_detect_lang_counts_cjk_against_latin_words(text: str, lang: str) -> None:
    assert detect_lang(text) == lang


def test_strip_html_removes_tags_and_unescapes() -> None:
    assert strip_html("<p>A&amp;B <b>bold</b></p>\n\n x") == "A&B bold x"


def test_slugify_keeps_cjk_lowercases_and_dash_joins() -> None:
    assert slugify_title("OpenAI 发布 GPT-5，性能提升 2 倍", 40) == (
        "openai-发布-gpt-5-性能提升-2-倍"
    )
    assert slugify_title("  ---苹果！！发布---  ", 40) == "苹果-发布"
    assert slugify_title("GPT-5", 40) == "gpt-5"


def test_slugify_caps_and_trims_a_trailing_dash() -> None:
    assert slugify_title("abc--def", 4) == "abc"
    assert slugify_title("苹果发布m5芯片性能怪兽级续", 6) == "苹果发布m5"


def test_slugify_falls_back_when_nothing_is_left() -> None:
    assert slugify_title("？！……", 40) == "untitled"
    assert slugify_title("", 40) == "untitled"


def test_title_tokens_are_latin_words_digits_and_cjk_chars() -> None:
    assert title_tokens("苹果发布M5芯片") == ("苹", "果", "发", "布", "m5", "芯", "片")
    assert title_tokens("OpenAI 发布 GPT-5，性能提升 2 倍") == (
        "openai", "发", "布", "gpt5", "性", "能", "提", "升", "2", "倍",
    )  # fmt: skip


def test_contains_run_requires_consecutive_tokens() -> None:
    assert contains_run(("a", "b"), ("x", "a", "b"))
    assert contains_run(("a", "b"), ("a", "b"))
    assert not contains_run(("a", "b"), ("xa", "b"))  # 不能跨越 token 边界
    assert not contains_run(("a", "b"), ("a", "x", "b"))  # 分散的，不连续
    assert not contains_run((), ("a",))
