# news-pool

A daily news collection you run from an AI agent harness, and a viewer to read it.

- **`news-digest/`** is an agent skill. Ask your harness for today's news and it fetches from RSS
  feeds and search sources; the agent picks, groups, scores and summarizes (in Chinese) what
  matches your interests, and the result is appended to a local pool.
- **`news-viewer/`** is a second skill. Ask it to open the news and it starts a small local server
  and gives you a URL: read the pool in your browser, search it, star, hide, take notes and keep
  collections.

## Install the skills

Link both skill directories into your harness's skills directory, for example:

```bash
ln -s /path/to/news-pool/news-digest /path/to/your-harness/skills/news-digest
ln -s /path/to/news-pool/news-viewer /path/to/your-harness/skills/news-viewer
```

Both need Python 3.9 or newer and nothing else. Fetching needs network access; a sandboxed
harness may ask you to allow it. The viewer only listens on 127.0.0.1.

## Use

Ask the agent things like "抓今天的新闻", "只跑量子位和 HN" or "看看最近关于 Sora 的新闻". On
first use it creates the pool and a profile; edit `interests` in the profile to say what to keep.

To read, ask "打开新闻" (or run `python3 /path/to/news-pool/news-viewer/scripts/nv.py up`
yourself) and open the URL it prints. Press `?` in the page for keyboard shortcuts. The viewer
stops by itself after two idle hours.

The pool lives in `~/.news-pool` (set `NEWS_POOL_DIR` to move it). Its format is documented in
[`news-digest/references/schema.md`](news-digest/references/schema.md); your stars, notes and
collections are in `<pool>/viewer/viewer.db`.

## Develop

See [AGENTS.md](AGENTS.md) and [docs/contributing.md](docs/contributing.md).
