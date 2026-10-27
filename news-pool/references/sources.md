# 来源接口说明

`nd.py` 内置的来源全部免 API key。端点于 2026-10-20 核验，示例 profile 的订阅源于 2026-10-26 核验；失效时更新本文件和对应的 `feeds.json`。

## 三类来源

| 类型 | 来源 id | 收 query 吗 | 说明 |
|---|---|---|---|
| 订阅式 | `feeds.json` 里的每个源、`wscn` | 不收 | 丢掉没有正文的条目，取最新的 N 条（`per_source_limit`，默认 10），按时间窗过滤，相关性由 triage 判断 |
| 检索式 | `gnews`、`hn`、`gdelt` | 收 | 每条 query 单独请求，每条最多 N 条（`per_query_limit`，默认 10；和 `per_source_limit` 分开，总量随 query 数成倍增长），结果合并去重。条目基本没有正文，仍交给 triage，见「没有正文的条目」 |
| 手动 | `links`（`fetch --links`）、`manual`（agent 写入 `candidates/manual.jsonl`） | — | `links` 不受时间窗限制，页面没有描述的跳过；`manual` 用本次运行的整体时间窗，没有 `snippet` 的行丢掉 |

## 内置适配器

| id | 端点 | 时间过滤 | 要点 |
|---|---|---|---|
| `rss` | `feeds.json` 中每个源的 `url` | 无，靠时间窗 | 兼容 RSS 2.0 / RSS 1.0 / Atom；按响应头或 XML 声明解码（GBK 源可用）。只暴露最新若干条：取到的不满 `per_source_limit` 条、最早一条又比时间窗起点新时，`prepare` 会警告漏了条目（取满了是 profile 有意设的上限，不警告） |
| `wscn` | `https://api-one.wallstcn.com/apiv1/content/articles?limit=N` | `display_time`（Unix 秒） | 华尔街见闻。站点无公开 RSS，这是其前端在用的 JSON 接口；会返回重复条目，已按 URL 去重。`limit` 最多 35（2026-10-26 实测：超过 35 时 `data` 是空字符串），所以每次都拿最新的 35 条，丢掉没有正文的之后再取 `per_source_limit` 条 |
| `gnews` | `https://news.google.com/rss/search?q=<query> when:<1h/12h/1d/7d>&hl=..&gl=..&ceid=..` | `when:` 只有这四档，取能覆盖时间窗的最小一档，再由 `prepare` 精确过滤 | 中文覆盖好。**不带摘要**（description 只是标题加媒体名，已清空）；**链接是 Google 跳转地址**：`leads` 会尝试解析到原站，但 2026-10-26 实测解析不到（页面停在 Google 上，要靠 JS 跳转），所以 Google News 当不了有正文的 primary |
| `hn` | `https://hn.algolia.com/api/v1/search_by_date?query=..&tags=story&numericFilters=created_at_i>A,created_at_i<B,points>=N` | 秒级，精确 | 偏英文技术社区，常有国内源没有的一手报道。只要至少 `hn.min_points` 分（默认 10，0 表示不限）的帖子：刚提交、没人投票的大多是 Show HN 之类的噪声；代价是运行时还没攒够分的帖子会错过（`window.overlap_hours` 内提交的，下次运行还能再赶上）。多数条目没有摘要，`leads` 会抓外链页面的描述。`source` 取外链域名（HN 只是聚合平台，按域名判 tier 才准）。默认不启用，要用就 `start --only hn` 或在 profile 的 `sources` 里加上 |
| `gdelt` | `https://api.gdeltproject.org/api/v2/doc/doc?query=..&mode=ArtList&format=json&timespan=..&maxrecords=..&sort=DateDesc` | `timespan`，最小 15 分钟 | 多语种国际覆盖。**限流严**（约每 5 秒一次，常 429），默认不启用；多条 query 之间间隔 `gdelt.min_interval_s` 秒。**拒绝过短的关键词**（如单独的 `AI`，返回纯文本错误，记为失败） |

## 没有正文的条目

没有正文就写不出摘要，所以这类条目尽早丢掉，不让 agent 白做后面的工作：

- 订阅源的条目没有正文（description / content 为空）时，`fetch` 直接跳过，不计入 `per_source_limit`。
- `links` 页面没有描述、`manual.jsonl` 的行没有 `snippet` 时，分别在 `fetch` 和 `prepare` 丢掉。
- 检索源（gnews、hn、gdelt）的条目通常只有标题，仍交给 triage：它们可以和订阅源的报道归进同一个事件，作为「同一事件的其他报道」。对保留下来的事件，`leads` 会给素材短于 `leads.min_snippet_chars` 的 primary 抓原文页面的 og / meta 描述（最多 `leads.max` 条），写进 `enrich_input.json` 的 `text`；抓了仍然没有的，事件记进 `enrich_input.json` 的 `no_text`，不写摘要、不落盘（每日运行把它记为已处理，之后不再出现）。Google News 的链接解析不到原站，所以 `prepare` 在 `triage_input.json` 里把没有正文的 Google News 条目标成 `related_only`：它们只能当同一事件的其他报道，当不了 primary（事件里有别的 member 可选时，`check` 拒绝它当 primary），只有它报道的新闻留不下来。

## 微信公众号

没有可用的按话题检索途径。公众号文章页 `mp.weixin.qq.com/s/...` 有时能抓到标题、公众号名、发布时间和摘要，但也常被重定向到微信的验证码页（`wappoc_appmsgcaptcha`）：这时该链接会被跳过并打印警告 `link blocked by a captcha page`，不会进入候选。要收录就把链接逐行写进一个文本文件，`fetch --run <run> --links <文件>`；被跳过的链接请让用户提供其他来源（转载页、标题加摘要）。

## 订阅源维护

- 源列表在 `references/feeds.json`；profile 里放一份同名文件即整体覆盖。示例 profile 都自带一份。
- 每个源要有唯一的 `id`（小写字母、数字、`_`、`-`）和中文 `name`，用户点名来源时靠它们对应。
- 失效的源不要删：标 `"enabled": false`，在 `note` 里写明原因和日期。

## 用 RSSHub 订阅没有 RSS 的站点

微博、B 站、知乎这类站点没有 RSS。[RSSHub](https://docs.rsshub.app) 是一个开源服务，能把它们转成 RSS。公共实例 `rsshub.app` 经常用不了（2026-10-20 实测 SSL 失败），建议在本机用 Docker 跑一个：

```bash
docker run -d --name rsshub -p 1200:1200 diygod/rsshub:chromium-bundled
```

微博和 B 站的路由要靠浏览器渲染，所以用带 Chromium 的镜像；只用不需要浏览器的路由（例如知乎日报）时，`diygod/rsshub` 就够了。然后把路由当作普通订阅源，写进 profile 的 `feeds.json`：

```json
{"id": "weibo_someone", "name": "某博主的微博", "url": "http://localhost:1200/weibo/user/<uid>"},
{"id": "bili_someone", "name": "某 UP 主的投稿", "url": "http://localhost:1200/bilibili/user/video/<uid>"},
{"id": "zhihu_daily", "name": "知乎日报", "url": "http://localhost:1200/zhihu/daily"}
```

- `<uid>` 换成对方主页里的用户 id。全部路由和参数见 RSSHub 文档。
- 有些路由可以配 cookie（例如微博的 `WEIBO_COOKIES`、知乎热榜的 `ZHIHU_COOKIES`），按 RSSHub 文档用环境变量传给容器。cookie 是用户的登录凭据：只放在 RSSHub 的配置里，不要写进 profile。
- 设置了 `HTTP_PROXY` / `HTTPS_PROXY` 时，把 `localhost` 加进 `NO_PROXY`，否则请求会绕到代理上。
- 公众号的路由大多依赖第三方服务，2026-10-20 核查时在官方实例上都用不了；公众号的其他途径见「微信公众号」一节。
