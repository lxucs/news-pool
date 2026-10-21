# 来源接口说明

`nd.py` 内置的来源全部免 API key。端点于 2026-10-20 核验；失效时更新本文件和 `feeds.json`。

## 三类来源

| 类型 | 来源 id | 收 query 吗 | 说明 |
|---|---|---|---|
| 订阅式 | `feeds.json` 里的每个源、`wscn` | 不收 | 拉最新 N 条（`per_source_limit`），按时间窗过滤，相关性由 triage 判断 |
| 检索式 | `gnews`、`hn`、`gdelt` | 收 | 每条 query 单独请求，结果合并去重 |
| 手动 | `links`（`fetch --links`）、`manual`（agent 写入 `candidates/manual.jsonl`） | — | `links` 不受时间窗限制；`manual` 用本次运行的整体时间窗 |

## 内置适配器

| id | 端点 | 时间过滤 | 要点 |
|---|---|---|---|
| `rss` | `feeds.json` 中每个源的 `url` | 无，靠时间窗 | 兼容 RSS 2.0 / RSS 1.0 / Atom；按响应头或 XML 声明解码（GBK 源可用）。只暴露最新若干条：最早一条都比时间窗起点新时，`prepare` 会警告漏了条目 |
| `wscn` | `https://api-one.wallstcn.com/apiv1/content/articles?limit=N` | `display_time`（Unix 秒） | 华尔街见闻。站点无公开 RSS，这是其前端在用的 JSON 接口；会返回重复条目，已按 URL 去重 |
| `gnews` | `https://news.google.com/rss/search?q=<query> when:<1h/12h/1d/7d>&hl=..&gl=..&ceid=..` | `when:` 只有这四档，取能覆盖时间窗的最小一档，再由 `prepare` 精确过滤 | 中文覆盖好。**不带摘要**（description 只是标题加媒体名，已清空）；**链接是 Google 跳转地址**，`leads` 会尝试解析到原站，解析不了就保留跳转链接 |
| `hn` | `https://hn.algolia.com/api/v1/search_by_date?query=..&tags=story&numericFilters=created_at_i>A,created_at_i<B` | 秒级，精确 | 技术 / AI 信噪比高，偏英文社区；多数条目没有摘要。`source` 取外链域名（HN 只是聚合平台，按域名判 tier 才准） |
| `gdelt` | `https://api.gdeltproject.org/api/v2/doc/doc?query=..&mode=ArtList&format=json&timespan=..&maxrecords=..&sort=DateDesc` | `timespan`，最小 15 分钟 | 多语种国际覆盖。**限流严**（约每 5 秒一次，常 429），默认不启用；多条 query 之间间隔 `gdelt.min_interval_s` 秒。**拒绝过短的关键词**（如单独的 `AI`，返回纯文本错误，记为失败） |

## 摘要素材不足

gnews 和 hn 的条目通常没有摘要。triage 只需要标题；对保留下来的事件，`leads` 会给摘要短于 `leads.min_snippet_chars` 的 primary 抓原文页面的 og / meta 描述（最多 `leads.max` 条），写进 `enrich_input.json` 的 `text`。

## 微信公众号

没有可用的按话题检索途径。公众号文章页 `mp.weixin.qq.com/s/...` 有时能抓到标题、公众号名、发布时间和摘要，但也常被重定向到微信的验证码页（`wappoc_appmsgcaptcha`）：这时该链接会被跳过并打印警告 `link blocked by a captcha page`，不会进入候选。要收录就把链接逐行写进一个文本文件，`fetch --run <run> --links <文件>`；被跳过的链接请让用户提供其他来源（转载页、标题加摘要）。

## 订阅源维护

- 源列表在 `references/feeds.json`；profile 里放一份同名文件即整体覆盖。
- 每个源要有唯一的 `id`（小写字母、数字、`_`、`-`）和中文 `name`，用户点名来源时靠它们对应。
- 失效的源不要删：标 `"enabled": false`，在 `note` 里写明原因和日期。
