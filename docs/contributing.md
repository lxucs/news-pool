# Contributing

Code conventions and the rules that keep the architecture intact. Working agreements for AI
coding agents — environment, testing, git — are in [`../AGENTS.md`](../AGENTS.md).

## Code conventions

- Full type annotations; `pyright` must be clean. Every module starts with
  `from __future__ import annotations`.
- `ruff format` and `ruff check` before calling work done.
- Skill code is **Python 3.9 compatible**: no `match`, no `zip(strict=)`, no
  `dataclass(slots=/kw_only=)`, no `X | Y` outside annotations, no 3.10+ standard-library APIs.
- Match the comment density of surrounding code. Comment *why*, not *what*.
- Prefer small, focused modules. Past ~400 lines *of code* a module is usually doing two things.

## Architecture rules

- **Scripts decide nothing semantic.** Relevance, grouping, scores and summaries are the agent's,
  written to files the scripts validate. Never add an LLM API call.
- **The pool only grows.** Item files and finalized runs are written once, through
  `files.write_*_atomic`, and a finalized run is never edited. No shared mutable index: derive
  views from finalized manifests.
- **One home per rule.** In news-digest: URL / time / timezone normalization lives in
  `normalize.py`; HTTP in `net.py`; payload parsing in `adapters.py` (pure: text in, rows out);
  the pool contract (runs, coverage, seen, windows, commit) in `pool.py`. In news-viewer: reading
  the pool in `poolread.py`; the item index and every list/search query in `index.py`; the user's
  data and its migrations in `userdb.py`; routing and request checks in `api.py` (a pure
  function, tested without sockets); the server process in `lifecycle.py`.
- **The viewer only reads the pool.** It writes nothing outside `<pool>/viewer/` and never
  imports `newsdigest`.
- **A news-digest command is `register(sub)` plus `cmd_*(args) -> int`** in its module, listed in
  `cli.COMMAND_MODULES`. news-viewer's four commands (`up`, `serve`, `down`, `status`) live in its
  `cli.py`.
- **Failures map to exit codes** (`errors.py`): raise `UsageError` (1), `ValidationFailed` (3) or
  `AllSourcesFailed` (4). `cli.main` maps a `PermissionError` (an unwritable pool) to 1; anything
  else becomes 5, with a traceback in `nd-error.log`. `SKILL.md`
  tells the agent what to do for each code, so a new kind of failure uses an existing code or
  updates `SKILL.md`. news-viewer uses 1 (`UsageError`) and 5 (`StartFailed`, internal errors).

## Schema changes

The pool format is a contract with the viewer. When a field of an item, manifest, `run.json`,
`triage.json` or `enriched-*.jsonl` changes:

1. bump `SCHEMA_VERSION` in `newsdigest/__init__.py` if existing readers would break;
2. update `news-digest/references/schema.md`, and `SKILL.md` if the agent writes that field;
3. update the viewer in the same change (`news-viewer/scripts/newsviewer/poolread.py`,
   `index.py`) and keep the contract test in `tests/test_viewer_index.py` passing.

## Configuration

### No hardcoded values

Anything a user might tune comes from `news-digest/references/defaults.json` (overridable in a
profile), not a literal mid-function: windows, limits, timeouts, retries, truncation lengths,
thresholds, user agents.

The viewer's tunables are in `news-viewer/references/defaults.json`, overridable in
`<pool>/viewer/config.json`; the page gets its own (`heartbeat_s`, `page_size`) from `/api/meta`.

```python
# Wrong — buried, undiscoverable, unchangeable without an edit
snippet = snippet[:800]

# Right
snippet = snippet[: int(settings["snippet_max_chars"])]
```

A literal is fine for a genuine protocol or schema constant: an API endpoint and its documented
maxima, a schema enum (`REGIONS`), the id length. Make it a named module constant, with a comment
when it is not obvious which kind it is.

### Nothing sensitive is committed

See AGENTS.md, "Configuration hygiene". In docs and examples use obvious placeholders —
`/path/to/pool`, `https://api.example.com` — never a value copied from a running environment.

## Output

The scripts are command-line tools whose output an agent reads, so the output *is* the interface:

- `console.say` for progress (`[nd] …` / `[nv] …` on stdout), `console.warn` for non-blocking notes,
  `console.error` (stderr) for failures. No bare `print` elsewhere, and no `logging` setup.
- One line per fact. A successful step ends with `next: …` naming the exact next command.
- An error says what is wrong, where (`file:line`, id, field), and what is expected.
- **Nothing sensitive is printed.** Never print a credential, a cookie or a private endpoint; if
  one ever becomes configurable, print the environment variable's *name*, not its value.

## The viewer's page

- No build step: plain HTML, CSS and native JS modules; Vue is the vendored ES-module build
  (`static/vendor/README.md` says how to upgrade it).
- Fetched text is untrusted: never `v-html` or `innerHTML`; links and images only through
  `safeUrl` (http/https), opened with `rel="noopener noreferrer"`.
- Client tunables come from `/api/meta`, not literals.
- No `URLSearchParams` and no HTML entities in templates: the JS check runs under a bare
  JavaScriptCore shell, with no browser APIs and no DOM.

## Python 3.9

The skill must run on the macOS system Python. Before finishing a change to skill code, run the
suite on it, from a throwaway environment outside the repository:

```bash
uv venv /tmp/nd-py39 --python /usr/bin/python3
uv pip install --python /tmp/nd-py39/bin/python pytest
/tmp/nd-py39/bin/python -m pytest -q -p no:cacheprovider
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

Run them and read the output before claiming work is done.
