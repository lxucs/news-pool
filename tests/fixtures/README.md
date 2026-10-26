# adapter 的 fixture

2026-10-21 从线上接口抓取一次的真实响应，之后只做了裁剪：订阅源保留前 3 条，JSON 接口保留前 3 条记录，文章页面保留 `<title>`、`<meta>` 标签、解析器会读的 `var …` 行，以及每个 `class` 含 `date` 或 `time` 的元素（从开始标签到结束标签，各占一行）。留下的内容都没有改动；唯一删掉的东西列在下面的「去除个人信息」里。

重新抓取时，把同样的 URL 下载到仓库之外的临时目录，再按同样的方式裁剪；永远不要改留下来的值。

| 文件 | 抓取自 | 说明 |
|---|---|---|
| `rss_qbitai.xml` | https://www.qbitai.com/feed | RSS 2.0。作者在 `<dc:creator>` 里（CDATA）；`<description>` 是一行导语；没有 `<content:encoded>` |
| `atom_v2ex.xml` | https://v2ex.com/index.xml | Atom。链接是 `www.v2ex.com` 上的 `rel="alternate"`（订阅源会重定向到那里）；正文在 `<content type="html">`；作者在 `<author><name>` |
| `rss_sina.xml` | https://rss.sina.com.cn/tech/rollnews.xml | 声明的编码是 UTF-8（`<?xml … encoding="utf-8"?>`；HTTP 头是不带 charset 的 `Content-Type: text/xml`），所以不是 GBK 的例子。这个订阅源已经停更：条目日期是 2018-09-23，pubDate 以 `GMT` 结尾。条目链接是 `go.rss.sina.com.cn/redirect.php?url=…` 形式的跳转；`<author>` 固定是 `WWW.SINA.COM.CN`；description 以全角空格开头 |
| `gnews_search.xml` | Google News RSS 搜索，q=人工智能 when:1d | RSS 2.0。标题以 ` - <媒体名>` 结尾；`<source url=…>` 里是媒体名；`<description>` 是转义过的 HTML，只重复标题和媒体名；链接是 `news.google.com/rss/articles/…` 跳转 |
| `hn_search.json` | HN Algolia search_by_date，query=AI | `hits[]`。第一条是 Ask HN 帖子：没有 `url`，正文在 `story_text`（含 `&#x27;`/`&#x2F;` 实体的 HTML）。`created_at_i` 是 epoch 秒 |
| `wscn_articles.json` | api-one.wallstcn.com 文章接口，limit=5 | `data.items[]`；`display_time` 是 epoch 秒；第 2、3 条是同一篇文章（接口会重复返回） |
| `gdelt_artlist.json` | GDELT DOC 2.0 ArtList，query=AI | 没有抓到——被限流（四次里三次 HTTP 429）；唯一一次 HTTP 200 返回的是纯文本的 `query=AI` "keyword too short" 错误，所以重新抓取要用更长的关键词。因此 `parse_gdelt` 还没有用真实响应测过 |
| `article_weixin.html` | 一篇公开的 mp.weixin.qq.com 文章 | 没有抓到——AIHOT 订阅源里的 `mp.weixin.qq.com/s?…` 链接（试了三个）都跳转到微信的验证码页（`/mp/wappoc_appmsgcaptcha`）而不是文章，其他抓到的订阅源里也没有微信链接 |
| `article_qbitai.html` | https://www.qbitai.com/2026/10/504608.html，2026-10-21 重新抓取（之前的裁剪只留了标题、meta 和 `var` 行，丢了日期） | `<title>` 带 ` &#8211; 量子位` 后缀；有 `og:title`、`og:site_name`、`og:description`、`og:image`；没有 `article:published_time`，没有 `description` meta，没有 `author` meta（只有 `og:author`），没有 JSON-LD，也没有 `<time datetime>`。发布时间只出现在 `div.article_info` 里的 `<span class="date">2026-10-21</span>` 和紧随其后的 `<span class="time">10:37:39</span>`（北京时间，与订阅源的 `pubDate` 02:37:39 +0000 一致）；文章下方相关文章列表里另有六个 `class="time"` 的 span，只有日期（`2024-03-12`……）。页面里没有微信的 `var …` 行，所以一行都没留 |

## 去除个人信息

每个 fixture 都搜过邮箱、token、session id、cookie 和绝对路径。只发现一处，处理方式是删掉整个元素，而不是改值：`gnews_search.xml` 频道头里的 `<webMaster>…</webMaster>` 元素（一个 Google 的职能邮箱）。解析器不读它。公开的用户名（V2EX、Hacker News）、作者署名（华尔街见闻）和媒体名都保留了。
