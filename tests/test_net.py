from __future__ import annotations

import email.message
import io
import urllib.error
import urllib.request

import pytest

from newsdigest import net
from newsdigest.net import FetchError, decode_body, detect_charset, http_get

HTTP = {"retries": 2, "backoff_s": 0, "timeout_s": 1, "user_agent": "test-agent"}


class FakeResp:
    def __init__(self, body: bytes, url: str = "https://final.example.com/a") -> None:
        self._body = body
        self._url = url
        self.status = 200
        self.headers = email.message.Message()
        self.headers["Content-Type"] = "text/xml"

    def __enter__(self) -> FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://a.example.com", code, "err", email.message.Message(), io.BytesIO(b"")
    )


def test_gbk_declared_xml_decodes() -> None:
    body = '<?xml version="1.0" encoding="gb2312"?><rss><t>新浪科技</t></rss>'.encode("gb2312")
    assert "新浪科技" in decode_body(body, "text/xml")


def test_header_charset_wins_over_xml_declaration() -> None:
    body = '<?xml version="1.0" encoding="gb2312"?><t>量子位</t>'.encode()
    assert detect_charset(body, "application/xml; charset=UTF-8") == "utf-8"
    assert "量子位" in decode_body(body, "application/xml; charset=UTF-8")


def test_html_meta_charset() -> None:
    body = '<html><head><meta charset="gbk"></head><body>华尔街见闻</body></html>'.encode("gbk")
    assert "华尔街见闻" in decode_body(body, "text/html")


def test_unknown_charset_falls_back_to_utf8() -> None:
    assert detect_charset(b"x", "text/plain; charset=klingon") == "utf-8"


def test_non_text_codec_falls_back_to_utf8() -> None:
    # codecs.lookup accepts base64/rot13, but they cannot decode a text body
    assert detect_charset(b"x", "text/plain; charset=base64") == "utf-8"
    assert detect_charset(b"x", "text/plain; charset=rot13") == "utf-8"


def test_utf8_bom_is_stripped() -> None:
    assert decode_body("\ufeff标题".encode(), "") == "标题"


def test_http_get_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    agents: list[str | None] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> FakeResp:
        agents.append(req.get_header("User-agent"))
        if len(agents) == 1:
            raise _http_error(429)
        return FakeResp(b"<rss/>")

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    resp = http_get("https://a.example.com/feed", HTTP)
    assert resp.url == "https://final.example.com/a"
    assert resp.text == "<rss/>"
    assert agents == ["test-agent", "test-agent"]


def test_http_get_does_not_retry_404(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> FakeResp:
        calls.append(1)
        raise _http_error(404)

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(FetchError, match="HTTP 404"):
        http_get("https://a.example.com/feed", HTTP)
    assert len(calls) == 1


def test_http_get_reports_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> FakeResp:
        calls.append(1)
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    with pytest.raises(FetchError, match="ConnectionRefusedError"):
        http_get("https://a.example.com/feed", HTTP)
    assert len(calls) == HTTP["retries"] + 1 == 3


@pytest.mark.parametrize("url", ["foo.example.com/x", "/relative"])
def test_http_get_malformed_url_is_fetch_error_without_requests(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    calls: list[int] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> FakeResp:
        calls.append(1)
        return FakeResp(b"")

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    with pytest.raises(FetchError):
        http_get(url, HTTP)
    assert calls == []


def test_http_get_rejects_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> FakeResp:
        calls.append(1)
        return FakeResp(b"")

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(FetchError, match="unsupported URL scheme"):
        http_get("file:///etc/hosts", HTTP)
    assert calls == []
