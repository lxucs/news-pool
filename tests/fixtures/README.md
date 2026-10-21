# Adapter fixtures

Real responses captured once from the live endpoints on 2026-10-21 (the day of capture), then
trimmed: feeds to their first 3 entries, JSON APIs to their first 3 records, article pages to their
`<title>`, `<meta>` tags, the `var …` lines the parser reads and every element whose `class`
contains `date` or `time` (start tag through closing tag, one line each). Nothing that remains was
edited; the only removal is listed under "Scrubbing" below.
To re-capture, download the same URLs into a scratch directory outside the repo and trim the same
way; never edit the values that remain.

| File | Captured from | Notes |
|---|---|---|
| `rss_qbitai.xml` | https://www.qbitai.com/feed | RSS 2.0. Author in `<dc:creator>` (CDATA), `<description>` is a one-line teaser, no `<content:encoded>` |
| `atom_v2ex.xml` | https://v2ex.com/index.xml | Atom. Links are `rel="alternate"` on `www.v2ex.com` (the feed redirects there); body in `<content type="html">`; author in `<author><name>` |
| `rss_sina.xml` | https://rss.sina.com.cn/tech/rollnews.xml | declared encoding: UTF-8 (`<?xml … encoding="utf-8"?>`; the HTTP header is `Content-Type: text/xml` with no charset), so this is not a GBK case. The feed is stale: its entries date from 2018-09-23 and pubDate ends in `GMT`. Item links are `go.rss.sina.com.cn/redirect.php?url=…` wrappers; `<author>` is the constant `WWW.SINA.COM.CN`; descriptions start with full-width spaces |
| `gnews_search.xml` | Google News RSS search, q=人工智能 when:1d | RSS 2.0. Titles end in ` - <outlet>`; `<source url=…>` holds the outlet name; `<description>` is escaped HTML that only repeats the headline and outlet; links are `news.google.com/rss/articles/…` redirects |
| `hn_search.json` | HN Algolia search_by_date, query=AI | `hits[]`. The first hit is an Ask HN post: no `url`, text in `story_text` (HTML with `&#x27;`/`&#x2F;` entities). `created_at_i` is epoch seconds |
| `wscn_articles.json` | api-one.wallstcn.com articles, limit=5 | `data.items[]`; `display_time` is epoch seconds; the 2nd and 3rd items are the same article (the API repeats entries) |
| `gdelt_artlist.json` | GDELT DOC 2.0 ArtList, query=AI | not captured — rate-limited (HTTP 429 on three of four attempts); the one HTTP 200 reply was a plain-text "keyword too short" error for `query=AI`, so a re-capture needs a longer keyword. `parse_gdelt` is therefore untested against a real payload |
| `article_weixin.html` | a public mp.weixin.qq.com article | not captured — every `mp.weixin.qq.com/s?…` link in the AIHOT feed (three tried) redirects to WeChat's captcha page (`/mp/wappoc_appmsgcaptcha`) instead of the article, and no other captured feed contains a WeChat link |
| `article_qbitai.html` | https://www.qbitai.com/2026/10/504608.html, re-captured on 2026-10-21 (an earlier trim kept only title/meta/`var` lines and so lost the date) | the `<title>` carries a ` &#8211; 量子位` suffix; `og:title`, `og:site_name`, `og:description`, `og:image` are present; there is no `article:published_time`, no `description` meta, no `author` meta (only `og:author`), no JSON-LD and no `<time datetime>`. The publish time is visible only as `<span class="date">2026-10-21</span>` followed by `<span class="time">10:37:39</span>` in `div.article_info` (Beijing time, matching the feed's `pubDate` of 02:37:39 +0000); six more `class="time"` spans from the related-article list below the article hold bare dates (`2024-03-12`, …). The page has no WeChat `var …` lines, so none are kept |

## Scrubbing

Every fixture was searched for emails, tokens, session ids, cookies and absolute paths.
One value was found and removed by deleting its whole element, not by editing it:
the `<webMaster>…</webMaster>` element (a Google role mailbox) from the channel header of
`gnews_search.xml`. The parsers do not read it. Public usernames (V2EX, Hacker News), author
display names (wallstcn) and outlet names are kept.
