# 新闻池格式（schema_version 2.1）

新闻池是 skill 与阅读器之间的约定。位置：`--pool` > 环境变量 `NEWS_POOL_DIR` > `~/.news-pool`。

## 目录

```
<pool>/
  profile/                     用户的 profile（config.json、feeds.json 等）
  items/<yymmdd>/<yymmdd>.<slug>.<id>.json
                               每个保留事件一个文件，写入后不再改
  runs/<run_id>/               一次运行；finalize 之后不再改
    run.json                   运行参数、各源时间窗与抓取结果、状态与阶段
    candidates/<source>.jsonl  各来源的原始候选
    records.json               prepare 之后的规范化候选
    triage_input.json  triage.json  leads.json  enrich_input.json  enriched-<n>.jsonl
    manifest.json              本次运行的有序摘要（阅读器的入口）
    seen.txt                   本次运行标记为已处理的 id
    errors.json                最近一次校验失败的完整错误列表（通过后删除）
    nd-error.log               脚本内部错误的 traceback（如果出过错）
  viewer/                      阅读器（news-viewer）自己的数据：viewer.db（星标、已读、隐藏、笔记、收藏夹）等；skill 不读写
```

## 约定

- **只增不改**：条目文件和已 finalize 的运行只写一次，全部原子写入。
- **阅读器的索引 = 所有 `status: finalized` 的运行的 `manifest.json`**。没有被任何 finalized manifest 引用的条目文件是孤儿（来自中途失败的运行），忽略即可。
- 阅读器从 `run.json` 只读 `status` 和 `created_at`（= 条目的 `collected_at`）；`run.json` 的其他字段是 skill 内部的，随时可能变。
- **`id`**：规范化 URL 的 sha1 前 12 位十六进制，永久稳定。阅读器的已读 / 收藏等标记以 id 为键，存在 `<pool>/viewer/` 里；skill 从不读写它。
- **条目文件命名**：`items/<抓取日>/<发布日>.<slug>.<id>.json`。抓取日是 `collected_at` 的
  `%y%m%d`，发布日是 `published_at` 的 `%y%m%d`；slug 由 `title_zh` 生成：小写，保留字母数字与
  CJK 字符，其余连续字符折叠成一个 `-`，最长 `item_slug_max_chars`（默认 40）字，全空则用
  `untitled`。id 保证文件名唯一；文件名是给人看的，阅读器用 manifest 的 `file` 字段定位条目文件。
- **2.0 → 2.1**：新增条目字段 `synopsis`、条目文件命名规则、manifest 条目的 `file` 字段。
  2.0 写出的条目文件（`items/<id>.json`）仍然有效：旧运行的 manifest 没有 `file`，阅读器回退到
  按 id 找文件。
- **运行类型**：`daily`（按 profile 的 interests 筛选，推进各源的时间窗）与 `adhoc`（带 `--query` / `--focus`；不推进时间窗）。
- **seen.txt**：每行 `<id> kept` 或 `<id> dropped`。daily 运行把经过 triage 的 id 全部写入；adhoc 运行只写 `kept`。新的 daily 运行跳过所有已 finalize 运行里出现过的 id；adhoc 运行只跳过 `kept`。
- **时间窗按来源计算**：某来源的覆盖终点 = 成功抓取过它的、已 finalize 的 daily 运行里最晚的窗口终点；新窗口从这里减去 `window.overlap_hours` 开始，最长 `window.max_hours`。没被选中或抓取失败的来源不前进。
- 时间一律是带时区偏移的 ISO 8601（默认 +08:00）。JSON 为 UTF-8。

## 条目

| 字段 | 说明 |
|---|---|
| `schema_version` | `"2.1"` |
| `id` | 见上 |
| `run_id` / `run_kind` / `profile` | 产生它的运行 |
| `title` | 原标题（英文源保留英文） |
| `title_zh` | 展示用中文标题（中文原文就是原标题） |
| `language` | `zh` / `en` |
| `summary` | 一句话摘要，≤ 60 字 |
| `synopsis` | 展开细节的一段话（发生了什么、关键数字、现状或后续），软目标 ≤ 250 字 |
| `key_points` | 3 条要点，每条 ≤ 30 字 |
| `why_it_matters` | 可为空 |
| `category` | 取自 `categories.json` |
| `tags` | 受控词表优先，最多 10 个 |
| `region` | `CN` / `US` / `EU` / `JP` / `GLOBAL`，或空 |
| `entities` | `{companies, people, products}`，都是字符串列表 |
| `source` | `{id, name, domain, url, author, tier}`。`id` 是抓到它的来源（feed id、`wscn`、`gnews`、`hn`、`gdelt`、`links`、`manual`），`name` 是发布方，`tier` 1–3（1 最权威） |
| `published_at` / `collected_at` | 发布时间 / 所在运行的开始时间 |
| `cover_image` | `{url}`，没有图时为空串 |
| `metrics` | `{importance, novelty, sentiment}`；importance（0–1）是主排序键 |
| `flags` | `{is_breaking, is_opinion, needs_review}` |
| `related` | 同一事件的其他报道：`[{id, title, source_name, url, published_at, language}]`，标题保持原文 |
| `llm` | `{model, skill_version, confidence}` |

## manifest.json

```json
{
  "schema_version": "2.1", "run_id": "20261021-083015", "kind": "daily", "profile": "ai-zh",
  "focus": "", "queries": ["AI 大模型"],
  "window": {"start": "…", "end": "…", "tz": "+08:00"},
  "sources": {"qbitai": {"start": "…", "end": "…", "ok": true, "fetched": 10, "error": "", "oldest": "…"}},
  "finalized_at": "…",
  "stats": {"candidates": 412, "new": 236, "events": 31, "items": 24, "by_category": {"AI": 15}},
  "warnings": [],
  "items": [{"id": "…", "file": "261021/261020.苹果发布m5芯片.a1b2c3d4e5f6.json", "rank": 1,
             "title_zh": "…", "summary": "…", "category": "AI",
             "importance": 0.82, "source_name": "…", "published_at": "…", "url": "…",
             "related_count": 2}]
}
```

`items` 按 importance 降序、同分时发布时间新的在前；`rank` 从 1 开始。阅读器展示一次运行只需要这个文件，点开详情再按条目的 `file` 字段读条目文件（旧运行的 manifest 没有 `file`，回退到 `items/<id>.json`）。

## agent 写的文件

`triage.json` 与 `enriched-<n>.jsonl` 的格式和规则见 `SKILL.md`；`nd.py check` 逐条校验。
