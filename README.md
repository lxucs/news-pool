# news-pool

在 AI agent 的 harness（Codex、WorkBuddy、Claude Code 等）里每天收集新闻，再在浏览器里阅读。

两个 skill，靠同一份磁盘格式衔接：

- **`news-digest/`** 负责收新闻。对 harness 说"抓今天的新闻"，脚本从订阅源（RSS、华尔街见闻）和检索源（Google News、Hacker News、GDELT）抓取候选；agent 按你的兴趣筛选，把报道同一件事的归到一起，打分，写中文摘要；结果追加进本地的新闻池。
- **`news-viewer/`** 负责读新闻。对 harness 说"打开新闻"，它在本机启动一个小服务，给你一个地址：在浏览器里阅读、搜索、星标、隐藏不感兴趣的、写笔记、整理收藏夹。

脚本不调用任何大模型 API，也不需要 API key：判断和写作由 harness 里的 agent 完成，脚本只做抓取、去重、校验和落盘。

## 安装

把两个 skill 目录链接（或复制）进 harness 的 skills 目录，例如：

```bash
ln -s /path/to/news-pool/news-digest /path/to/your-harness/skills/news-digest
ln -s /path/to/news-pool/news-viewer /path/to/your-harness/skills/news-viewer
```

只需要 Python 3.9 或更新的版本，不用安装任何依赖。抓取需要联网，沙箱型 harness 可能会请你放行；阅读器只监听 127.0.0.1。

## 使用

**收新闻**：对 agent 说"抓今天的新闻""只跑量子位和 HN""看看最近关于 Sora 的新闻"或"把这几个链接收进来"。第一次使用时，agent 会创建新闻池和 profile，并问你关注什么；以后想调整，就改 `<pool>/profile/config.json` 里的 `interests`（要什么、不要什么）和 `queries`（检索词）。

**读新闻**：说"打开新闻"（或者自己运行 `python3 /path/to/news-pool/news-viewer/scripts/nv.py up`），打开它打印的地址。在页面里按 `?` 查看快捷键。阅读器空闲两小时后自动退出，下次再打开即可。

数据都在新闻池里（默认 `~/.news-pool`，设置环境变量 `NEWS_POOL_DIR` 可以换位置）：

| 位置 | 内容 |
|---|---|
| `<pool>/profile/` | 你的 profile：兴趣、检索词、来源 |
| `<pool>/items/` | 条目：每条新闻一个 JSON 文件，写入后不再修改 |
| `<pool>/runs/` | 每次运行的目录；`manifest.json` 是这次运行收进来的条目列表 |
| `<pool>/viewer/` | 阅读器的数据：星标、已读、隐藏、笔记和收藏夹都在 `viewer.db` 里 |

格式的完整说明见 [`news-digest/references/schema.md`](news-digest/references/schema.md)。

## 开发

```bash
uv sync          # 创建开发环境（pytest、ruff、pyright）
uv run pytest    # 离线测试，不联网
```

开发约定见 [AGENTS.md](AGENTS.md) 和 [docs/contributing.md](docs/contributing.md)。
