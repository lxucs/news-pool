---
name: news-viewer
description: 新闻阅读器：在浏览器里阅读新闻池（news-digest 收进来的新闻，默认 ~/.news-pool），可以搜索、星标、隐藏不感兴趣的、写笔记、整理收藏夹。用户说"打开新闻""打开阅读器""看看收进来的新闻""看我的收藏 / 笔记"时使用；要抓取新的新闻用 news-digest。
---

# news-viewer：在浏览器里读新闻池

脚本只用 Python ≥ 3.9 标准库，不用安装任何东西，也不联网：页面只在本机 `127.0.0.1` 上提供。

## 完整用法：news-digest 收，news-viewer 读

新闻池里的新闻都由 **news-digest** skill 收进来；本 skill 只负责读和标记，不抓新闻。

- 新闻池不存在（`nv.py up` 退出码 1，提示 `no news pool`），或页面显示"新闻池里还没有新闻"：先用 news-digest 抓一次（"抓今天的新闻"）。第一次使用时，它会问用户关注什么，并建好 profile。
- 用户要新的新闻（"抓今天的新闻""看看最近关于 X 的新闻"）：交给 news-digest。那次运行落盘之后，用 `nv.py up --run <运行目录或 run_id>` 直接打开它；阅读器已经开着时不用重启，刷新页面就能看到。
- 用户想改关注点或加订阅源：这些在 news-digest 的 profile 里（`<pool>/profile/`），按 news-digest 的 SKILL.md 改。

## 打开阅读器

1. 运行 `python3 <skill_dir>/scripts/nv.py up`（Windows 用 `python`）。`<skill_dir>` 是本文件所在的目录，用绝对路径。
   - 刚跑完 news-digest、要直接看这次的结果：加 `--run <运行目录或 run_id>`。
   - harness 跑在用户自己的电脑上、用户希望直接弹出浏览器：加 `--browser`。
2. 输出里 `[nv] url: http://127.0.0.1:…` 那一行就是地址，原样交给用户。
3. 服务在后台运行，没有页面在看时空闲一段时间（默认 120 分钟）后自动退出。再次需要时重新 `nv.py up`；已经在运行就直接复用，不会开第二个。

## 其他命令

- `nv.py status`：是否在运行、地址。
- `nv.py down`：立刻停止。
- `nv.py serve`：前台运行（Ctrl-C 停止）。如果 harness 在命令结束时会杀掉后台进程（地址打不开），请用户在自己的终端里运行 `nv.py up` 或 `nv.py serve`。

## 退出码

| 码 | 含义 | 你该做什么 |
|---|---|---|
| 0 | 成功 | 把 url 交给用户 |
| 1 | 用法错误：新闻池不存在、端口或 `--run` 不对、`<pool>/viewer/config.json` 写坏了、`<pool>/viewer` 不可写 | 按提示改；新闻池不存在就先用 news-digest 抓新闻 |
| 5 | 服务没能启动，或脚本内部错误 | 把那行错误和日志路径（`<pool>/viewer/server.log` 或 `nv-error.log`）告诉用户；**不要改脚本** |

## 用户的数据

星标、已读、隐藏、笔记、收藏夹都存在 `<pool>/viewer/viewer.db`，跟新闻池放在一起。不要手动改它，也不要改新闻池里的其他文件。

## 配置

可选的 `<pool>/viewer/config.json` 覆盖 `references/defaults.json` 里的任何键，例如 `{"port": 8800, "idle_minutes": 240}`；`idle_minutes` 为 0 表示不自动退出。
