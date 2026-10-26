# AGENTS.md

本仓库里 AI 编码 agent 的工作约定。

**写代码之前先读 [docs/contributing.md](docs/contributing.md)。** 那里是代码规范、架构规则，以及禁止写死数值、禁止输出泄露信息的规则。本文件讲项目是什么、开发环境、配置卫生、测试和 git。

## 项目是什么

两个 skill，靠同一份磁盘格式衔接：

- **`news-digest/`** 是一个 agent skill（`SKILL.md` 加脚本），由通用的 harness（Codex、WorkBuddy、Claude Code……）运行，大约每天一次。脚本做确定性的工作：抓取、规范化、去重、校验、写入。判断和写作（triage、摘要）由 harness 里的 agent 完成，方式是读写 JSON 文件。**脚本从不调用大模型 API。**
- **`news-viewer/`** 是阅读器，也是一个 skill。`nv.py up` 在 127.0.0.1 上启动（或复用）一个小服务并打印地址；页面读取新闻池，用户可以搜索和标记条目（星标、已读、隐藏、笔记、收藏夹）。空闲时它自动退出。**它从不 import `newsdigest`**：新闻池的格式是两者之间唯一的接口。
- **新闻池**（默认 `~/.news-pool`）就是两者之间的约定。条目文件和已 finalize 的运行的 manifest 只写一次；阅读器的索引就是所有已 finalize 的 manifest；用户标记归阅读器所有，存在 `<pool>/viewer/viewer.db`。格式规定在 [`news-digest/references/schema.md`](news-digest/references/schema.md)。

## 目录

```
news-digest/            skill 本体；以符号链接或复制的方式放进 harness 的 skills 目录
  SKILL.md              给 agent 的流程说明
  scripts/nd.py         入口；实现在 scripts/newsdigest/
  references/           默认值、订阅源、类别、标签、来源分级，以及给 agent 的规则
  examples/             示例 profile 和候选样例
news-viewer/            阅读器 skill；安装方式相同
  SKILL.md              给 agent 的说明
  scripts/nv.py         入口；实现在 scripts/newsviewer/
  scripts/newsviewer/static/   页面：HTML、CSS、JS 模块、内置的 Vue（没有构建步骤）
  references/           defaults.json
tests/                  离线测试；tests/fixtures/ 存放从线上接口抓取的真实响应
docs/                   贡献指南
```

## 环境

两套环境，有意为之：

- **两个 skill 都跑在 harness 自带的 Python 上：Python ≥ 3.9，只用标准库。** `news-digest/` 或 `news-viewer/` 下出现任何第三方 import 都是 bug——skill 复制到一台什么都没装的机器上也必须能用。以 macOS 自带的 Python（3.9）为下限来检查。唯一的第三方文件是 `news-viewer/scripts/newsviewer/static/vendor/` 里内置的 Vue 浏览器构建（固定版本并校验 sha256，见该目录的 README）：它由浏览器加载，不需要安装。
- **开发用 uv**，使用仓库根目录下项目本地的 `.venv`：

```bash
uv sync                 # 创建 / 更新 .venv（pytest、ruff、pyright）
uv run pytest           # 跑测试
uv run python news-digest/scripts/nd.py --help
```

`uv run` 会自动选用 `.venv`。不要创建别的环境，也不要往系统自带的解释器里 `pip install`。`pyproject.toml` 只放开发工具；项目没有运行时依赖。

## 配置卫生

**提交的文件里不能有任何敏感信息。** 不能有 API key 或 token，不能有个人的绝对路径（`/Users/...`、`/home/...`），不能有私有的 URL、主机名、邮箱或账号 id——配置、订阅源列表、`SKILL.md`、references、文档、测试、fixture、示例里都不行。

- 用户的真实配置是用户自己的 profile，放在**新闻池里、仓库之外**（`<pool>/profile/`）。仓库不需要本地覆盖配置。
- 提交的示例要么用一看就是示例的值（`/path/to/pool`、`https://api.example.com`），要么用确实公开的值（公开的订阅源 URL）。
- 抓取下来的 fixture 是公开的响应。要去掉其中的个人信息（邮箱、URL 里的 token），就删掉包含它的整个条目，不要改值。

如果将来某个功能需要密钥，就从环境变量读取，配置项里写的是环境变量的*名字*；密钥的值永远不写到任何地方，输出也不行（见 contributing.md）。

## 测试是离线的

**自动化测试从不访问网络。** `tests/conftest.py` 让任何 socket 连接都失败，并把 `NEWS_POOL_DIR` 指向临时目录，所以没有测试会连到服务器或真实的新闻池。

adapter 测试用的是**从线上接口抓取的真实响应**（`tests/fixtures/`，来源和抓取日期见其中的 README），只做了裁剪，内容没有改动。不要凭记忆手写 API 响应：那是在拿你自己的假设测解析器。agent 写的文件（`triage.json`、`enriched-*.jsonl`）是例外——测试手写它们，因为 agent 本来就是手写的。

阅读器的测试在进程内驱动 API（`api.App.handle`）和 HTTP handler；没有测试会绑定或连接 socket。在 macOS 上，`tests/test_viewer_static.py` 还会用系统自带的 JavaScriptCore shell（`jsc`）运行页面的 JS 模块，检查语法、import 和每一个模板；其他平台上跳过这一项。页面本身由人在浏览器里检查。

对线上来源的真实端到端运行**由用户手动进行**。不要添加联网的测试，也不要为了跑测试向用户要凭据。

## Git

**除非明确要求，否则不要创建提交。** 包括 `git commit`、`git commit --amend` 以及其他任何写入历史的操作。不要主动 push、建分支或开 PR。

只读的 git 命令随时可以用：`git status`、`git diff`、`git log`、`git show`、`git blame`。

提交信息用中文（常见的英文术语、标识符、命令照写）：一行标题，空一行，再分条写改了什么。

完成的工作留在工作区里，说明改了什么。由用户来提交。

## 宣布完成之前

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

任一 skill 下的代码有改动时，还要在 Python 3.9 上跑一遍测试（见 contributing.md 的「Python 3.9」一节）。

要真的运行这些命令并读输出——不要因为代码写完了就推断它能通过。有失败就如实说，并附上输出。如果跳过了一部分范围，要明确说出来。
