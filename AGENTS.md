# AGENTS.md

Working agreements for AI coding agents in this repository.

**Read [docs/contributing.md](docs/contributing.md) before writing code.** It holds the code
conventions, the architecture rules, and the rules against hardcoded values and leaky output. This
file covers what the project is, environment, configuration hygiene, testing, and git.

## What this project is

Two skills, joined by one on-disk contract:

- **`news-digest/`** is an agent skill (`SKILL.md` plus scripts) that a general harness (Codex,
  WorkBuddy, Claude Code, …) runs, roughly daily. The scripts do the deterministic work: fetch,
  normalize, dedup, validate, write. The harness agent does the judgement and the writing (triage,
  summaries) by reading and writing JSON files. **The scripts never call an LLM API.**
- **`news-viewer/`** is the reader, also a skill. `nv.py up` starts (or reuses) a small server on
  127.0.0.1 and prints a URL; the page reads the pool and lets the user search and mark items
  (star, read, hide, notes, collections). It stops itself when idle. **It never imports
  `newsdigest`**: the pool format is the only interface between the two.
- **The pool** (`~/.news-pool` by default) is the contract between them. Item files and finalized
  run manifests are written once; the viewer's index is the set of finalized manifests; user marks
  belong to the viewer, in `<pool>/viewer/viewer.db`. The format is specified in
  [`news-digest/references/schema.md`](news-digest/references/schema.md).

## Layout

```
news-digest/            the skill; symlinked or copied into a harness's skills directory
  SKILL.md              agent-facing workflow (Chinese)
  scripts/nd.py         entry point; scripts/newsdigest/ is the implementation
  references/           defaults, feeds, categories, tags, tiers, and agent-facing rules
  examples/             example profile and sample candidates
news-viewer/            the reader skill; installed the same way
  SKILL.md              agent-facing instructions (Chinese)
  scripts/nv.py         entry point; scripts/newsviewer/ is the implementation
  scripts/newsviewer/static/   the page: HTML, CSS, JS modules, vendored Vue (no build step)
  references/           defaults.json
tests/                  offline suite; tests/fixtures/ holds captured real payloads
docs/                   contributing guide
```

## Environment

Two environments, on purpose:

- **Both skills run on whatever Python the harness has: Python ≥ 3.9, standard library only.** A
  third-party import anywhere under `news-digest/` or `news-viewer/` is a bug — a skill must work
  when copied to a machine with nothing installed. The macOS system Python (3.9) is the floor to
  check against. The one third-party file is the vendored Vue browser build in
  `news-viewer/scripts/newsviewer/static/vendor/` (pinned and checksummed; see its README): the
  browser loads it, nothing installs it.
- **Development uses uv**, with the project-local `.venv` in the repository root:

```bash
uv sync                 # create/update .venv (pytest, ruff, pyright)
uv run pytest           # run tests
uv run python news-digest/scripts/nd.py --help
```

`uv run` selects `.venv` automatically. Do not create other environments, and do not
`pip install` into the ambient interpreter. `pyproject.toml` holds development tooling only; the
project has no runtime dependencies.

## Configuration hygiene

**Nothing sensitive goes in a committed file.** No API keys or tokens, no personal absolute paths
(`/Users/...`, `/home/...`), no private URLs, hostnames, emails or account ids — in config, the
feed list, `SKILL.md`, references, docs, tests, fixtures, or examples.

- The user's real configuration is their profile, which lives **in the pool, outside the repo**
  (`<pool>/profile/`). The repo needs no local override layer.
- Committed examples use values that are obviously examples (`/path/to/pool`,
  `https://api.example.com`) or genuinely public ones (public feed URLs).
- Captured fixtures are public responses. Remove anything personal (an email, a token in a URL) by
  dropping the entry that contains it, not by editing values.

If a feature ever needs a secret, read it from an environment variable whose *name* is a config
key, and never write the value anywhere — output included (see contributing.md).

## Testing is offline

**The automated suite never touches the network.** `tests/conftest.py` makes any socket connection
fail and points `NEWS_POOL_DIR` at a temporary directory, so no test reaches a server or a real
pool.

Adapter tests run against payloads **captured from the live endpoints** (`tests/fixtures/`, with
source and capture date in its README), trimmed but otherwise unedited. Do not hand-write an API
payload from memory: that tests the parser against your assumptions. Agent-written files
(`triage.json`, `enriched-*.jsonl`) are the exception — tests write those by hand, because an
agent writes them by hand.

Viewer tests drive the API (`api.App.handle`) and the HTTP handler in-process; no test binds or
connects a socket. On macOS, `tests/test_viewer_static.py` also runs the page's JS modules under
the system JavaScriptCore shell (`jsc`) to check syntax, imports and every template; elsewhere
that one test is skipped. The page itself is checked by hand in a browser.

Real end-to-end runs against live sources are **manual, done by the user**. Do not add tests that
use the network, and do not ask the user for credentials to run the suite.

## Git

**Do not create commits unless explicitly asked.** This includes `git commit`,
`git commit --amend`, and anything else that writes history. Do not push, create branches, or open
PRs on your own initiative.

Read-only git is always fine: `git status`, `git diff`, `git log`, `git show`, `git blame`.

Leave finished work in the working tree and say what changed. The user commits.

## Before claiming work is done

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

When code under either skill changed, also run the suite once on Python 3.9 (contributing.md,
"Python 3.9").
Run the commands and read the output — do not infer success from having written the code. If
something fails, say so with the output. If part of the scope was skipped, say that explicitly.
