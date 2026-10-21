# news-pool

A daily news collection you run from an AI agent harness, and (soon) a viewer to read it.

- **`news-digest/`** is an agent skill. Ask your harness for today's news and it fetches from RSS
  feeds and search sources; the agent picks, groups, scores and summarizes (in Chinese) what
  matches your interests, and the result is appended to a local pool.
- **The viewer** (not built yet) will read the pool and let you read and mark items.

## Install the skill

Link the skill directory into your harness's skills directory, for example:

```bash
ln -s /path/to/news-pool/news-digest /path/to/your-harness/skills/news-digest
```

The scripts need Python 3.9 or newer and nothing else. Fetching needs network access; a sandboxed
harness may ask you to allow it.

## Use

Ask the agent things like "抓今天的新闻", "只跑量子位和 HN" or "看看最近关于 Sora 的新闻". On
first use it creates the pool and a profile; edit `interests` in the profile to say what to keep.

The pool lives in `~/.news-pool` (set `NEWS_POOL_DIR` to move it). Its format is documented in
[`news-digest/references/schema.md`](news-digest/references/schema.md).

## Develop

See [AGENTS.md](AGENTS.md) and [docs/contributing.md](docs/contributing.md).
