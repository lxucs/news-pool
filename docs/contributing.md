# 贡献指南

代码规范，以及让架构不走样的规则。给 AI 编码 agent 的工作约定（环境、测试、git）在 [`../AGENTS.md`](../AGENTS.md)。

## 代码规范

- 类型注解写全；`pyright` 必须零报错。每个模块都以 `from __future__ import annotations` 开头。
- 宣布完成之前跑 `ruff format` 和 `ruff check`。
- skill 代码**兼容 Python 3.9**：不用 `match`，不用 `zip(strict=)`，不用 `dataclass(slots=/kw_only=)`，注解以外不用 `X | Y`，不用 3.10 及以上版本才有的标准库 API。
- 注释、docstring 和文档写中文，和 `SKILL.md` 一致；标识符用英文。ruff 按显示宽度计算行长，一个汉字算 2 列，中文注释按 100 列换行（中文没有空格，超长的行 ruff 不一定报出来）。Markdown 里的中文段落不要硬换行：换行会在汉字之间渲染出空格。
- 唯一的英文文档是 `README.en.md`，它是 `README.md` 的英文版：改其中一个时同步改另一个。README 用的截图放在 `docs/images/`。
- 注释的密度跟周围的代码保持一致。注释写*为什么*，不写*做了什么*。
- 模块宜小而专。一个模块的代码超过约 400 行，通常说明它在做两件事。

## 架构规则

- **脚本不做任何语义判断。** 相关性、分组、打分和摘要都归 agent：agent 写进文件，脚本校验。永远不要加大模型 API 调用。
- **新闻池只增不改。** 条目文件和已 finalize 的运行只写一次，一律经由 `files.write_*_atomic`；已 finalize 的运行永远不再修改。不要维护共享的可变索引：视图从已 finalize 的 manifest 推导出来。
- **每条规则只有一个归属。** news-digest 里：URL、时间和时区的规范化在 `normalize.py`；HTTP 在 `net.py`；响应解析在 `adapters.py`（纯函数：文本进，行出）；新闻池的约定（运行、覆盖范围、seen、时间窗、提交）在 `pool.py`。news-viewer 里：读新闻池在 `poolread.py`；条目索引和所有列表、搜索查询在 `index.py`；用户数据及其迁移在 `userdb.py`；路由和请求检查在 `api.py`（纯函数，测试不需要 socket）；服务进程在 `lifecycle.py`。
- **阅读器只读新闻池。** 它只在 `<pool>/viewer/` 里写东西，也从不 import `newsdigest`。
- **news-digest 的一个命令 = 所在模块里的 `register(sub)` 加 `cmd_*(args) -> int`**，并列入 `cli.COMMAND_MODULES`。news-viewer 的四个命令（`up`、`serve`、`down`、`status`）都在它的 `cli.py` 里。
- **失败映射到退出码**（`errors.py`）：抛出 `UsageError`（1）、`ValidationFailed`（3）或 `AllSourcesFailed`（4）。`cli.main` 把 `PermissionError`（新闻池不可写）映射为 1；其他异常一律是 5，traceback 写进 `nd-error.log`。`SKILL.md` 告诉 agent 每个退出码该怎么处理，所以新的失败类型要么沿用已有的退出码，要么同时更新 `SKILL.md`。news-viewer 用 1（`UsageError`）和 5（`StartFailed`、内部错误）。

## 改格式

新闻池的格式是和阅读器之间的约定。条目、manifest、`run.json`、`triage.json` 或 `enriched-*.jsonl` 的字段有变化时：

1. 如果现有的读取方会因此出错，提升 `newsdigest/__init__.py` 里的 `SCHEMA_VERSION`；
2. 更新 `news-digest/references/schema.md`；如果这个字段由 agent 来写，也更新 `SKILL.md`；
3. 在同一次改动里更新阅读器（`news-viewer/scripts/newsviewer/poolread.py`、`index.py`），并保证 `tests/test_viewer_index.py` 里的契约测试通过。

## 配置

### 不写死数值

用户可能想调的值都从 `news-digest/references/defaults.json` 读取（可以在 profile 里覆盖），不要在函数中间写字面量：时间窗、上限、超时、重试、截断长度、阈值、User-Agent。

阅读器的可调参数在 `news-viewer/references/defaults.json`，可以在 `<pool>/viewer/config.json` 里覆盖；页面自己用的参数（`heartbeat_s`、`page_size`）从 `/api/meta` 获取。

```python
# 错：埋在代码里，找不到，不改代码就改不了
snippet = snippet[:800]

# 对
snippet = snippet[: int(settings["snippet_max_chars"])]
```

真正的协议常量或格式常量可以写成字面量：API 端点及其文档规定的上限、格式里的枚举（`REGIONS`）、id 的长度。把它定义成有名字的模块常量；看不出属于哪一类时，加一行注释说明。

### 不提交敏感信息

见 AGENTS.md 的「配置卫生」。文档和示例里用一看就是占位的值——`/path/to/pool`、`https://api.example.com`——永远不要用从运行环境里复制来的值。

## 输出

脚本是命令行工具，读输出的是 agent，所以输出*就是*接口：

- 进度用 `console.say`（stdout 上的 `[nd] …` / `[nv] …`），不阻断流程的提示用 `console.warn`，失败用 `console.error`（stderr）。其他地方不要裸用 `print`，也不要配置 `logging`。
- 一行一个事实。成功的步骤以 `next: …` 结尾，写出下一条要运行的确切命令。
- 错误要说明哪里不对、在哪里（`file:line`、id、字段）、期望的是什么。
- 输出用英文：`SKILL.md` 原样引用了其中一些行（`next:`、`no new candidates`、`[nv] url:` 等），改输出时同步改 `SKILL.md`。
- **不打印任何敏感信息。** 永远不要打印凭据、cookie 或私有端点；如果将来它们变得可配置，打印环境变量的*名字*，不打印值。

## 阅读器的页面

- 没有构建步骤：纯 HTML、CSS 和原生 JS 模块；Vue 用内置的 ES 模块构建（`static/vendor/README.md` 说明怎么升级）。
- 界面文字用中文。
- 抓来的文本不可信：永远不用 `v-html` 或 `innerHTML`；链接和图片一律经过 `safeUrl`（只允许 http 和 https），用 `rel="noopener noreferrer"` 打开。
- 页面的可调参数来自 `/api/meta`，不写字面量。
- 不用 `URLSearchParams`，模板里不用 HTML 实体：JS 检查跑在裸的 JavaScriptCore shell 里，没有浏览器 API，也没有 DOM。

## Python 3.9

skill 必须能在 macOS 自带的 Python 上运行。改完 skill 代码、收尾之前，在它上面跑一遍测试，用仓库之外的一次性环境：

```bash
uv venv /tmp/nd-py39 --python /usr/bin/python3
uv pip install --python /tmp/nd-py39/bin/python pytest
/tmp/nd-py39/bin/python -m pytest -q -p no:cacheprovider
```

## 检查

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

运行它们并读完输出，再宣布完成。

GitHub CI（`.github/workflows/ci.yml`）在 push 到 main 和每个 PR 上跑同样的检查：测试在 Linux 上用 Python 3.9 和 3.15 各跑一遍，在 macOS 上再跑一遍（页面 JS 的 `jsc` 检查只在 macOS 上运行）。CI 不能代替本地检查。
