"""带重试、按字符集解码的 HTTP GET——唯一会建立网络连接的模块。"""

from __future__ import annotations

import codecs
import http.client
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
ALLOWED_SCHEMES = frozenset({"http", "https"})  # 否则 urlopen 也会打开 file: 和 ftp: 的 URL
SNIFF_BYTES = 2048  # 在响应体开头多少字节内查找 XML 声明或 <meta charset>
_CHARSET_ALIASES = {"gb2312": "gb18030", "gbk": "gb18030", "x-gbk": "gb18030"}
_CT_CHARSET_RE = re.compile(r"charset=[\"']?([A-Za-z0-9_.:-]+)", re.I)
_XML_DECL_RE = re.compile(rb"<\?xml[^>]*encoding=[\"']([A-Za-z0-9_.:-]+)[\"']", re.I)
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_.:-]+)", re.I)


class FetchError(Exception):
    """重试后仍失败的请求；str() 是简短的原因，例如 'HTTP 429'。"""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        return decode_body(self.body, self.content_type)


def http_get(url: str, http_cfg: dict[str, Any], user_agent: str | None = None) -> Response:
    retries = int(http_cfg["retries"])
    backoff = float(http_cfg["backoff_s"])
    timeout = float(http_cfg["timeout_s"])
    headers = {"User-Agent": user_agent or str(http_cfg["user_agent"])}
    reason = "not attempted"
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(backoff * attempt)
        try:
            request = urllib.request.Request(url, headers=headers)
            if request.type not in ALLOWED_SCHEMES:
                reason = f"unsupported URL scheme: {url}"
                break
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                return Response(resp.geturl(), resp.status, content_type, resp.read())
        except urllib.error.HTTPError as exc:
            reason = f"HTTP {exc.code}"
            if exc.code not in RETRY_STATUSES:
                break
        except ValueError as exc:  # URL 格式不对：重试也没用
            reason = f"bad URL: {exc}"
            break
        except (OSError, http.client.HTTPException) as exc:  # URLError、超时、连接被重置
            reason = _describe(exc)
    raise FetchError(reason)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return f"URLError: {type(exc.reason).__name__}: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def detect_charset(body: bytes, content_type: str) -> str:
    """依次取响应头的 charset、XML 声明、<meta charset>，都没有就用 UTF-8。"""
    match = _CT_CHARSET_RE.search(content_type or "")
    name = match.group(1) if match else ""
    if not name:
        head = body[:SNIFF_BYTES]
        sniffed = _XML_DECL_RE.search(head) or _META_CHARSET_RE.search(head)
        name = sniffed.group(1).decode("ascii", "replace") if sniffed else "utf-8"
    name = _CHARSET_ALIASES.get(name.lower(), name.lower())
    try:
        info = codecs.lookup(name)
    except LookupError:
        return "utf-8"
    # base64、rot13 之类是字节到字节的 codec：lookup 能成功，之后解码却会失败
    if not getattr(info, "_is_text_encoding", True):
        return "utf-8"
    return name


def decode_body(body: bytes, content_type: str) -> str:
    if body.startswith(codecs.BOM_UTF8):
        return body[len(codecs.BOM_UTF8) :].decode("utf-8", "replace")
    return body.decode(detect_charset(body, content_type), "replace")
