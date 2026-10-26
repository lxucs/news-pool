from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from newsviewer.paths import STATIC_DIR

JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc")
JS_CHECK = Path(__file__).parent / "viewer_js_check.js"
IMPORT_RE = re.compile(r"""import\s[^'"]*?from\s*["'](\.[^"']+)["']|import\s*["'](\.[^"']+)["']""")
VENDOR = STATIC_DIR / "vendor"


def _own_js() -> list[Path]:
    return [p for p in STATIC_DIR.rglob("*.js") if VENDOR not in p.parents]


def test_index_html_references_existing_files() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert refs
    for ref in refs:
        assert (STATIC_DIR / ref).is_file(), ref


def test_every_relative_import_resolves() -> None:
    for js in _own_js():
        for groups in IMPORT_RE.findall(js.read_text(encoding="utf-8")):
            ref = groups[0] or groups[1]
            assert (js.parent / ref).resolve().is_file(), f"{js.name}: {ref}"


def test_the_vendored_vue_matches_its_recorded_checksum() -> None:
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    match = re.search(r"sha256: ([0-9a-f]{64})", readme)
    assert match is not None
    digest = hashlib.sha256((VENDOR / "vue.esm-browser.prod.js").read_bytes()).hexdigest()
    assert digest == match.group(1)
    assert (VENDOR / "LICENSE").is_file()


def test_fetched_text_is_never_rendered_as_html() -> None:
    for js in _own_js():
        text = js.read_text(encoding="utf-8")
        assert "v-html" not in text and "innerHTML" not in text, js.name


@pytest.mark.skipif(not JSC.is_file(), reason="needs macOS's JavaScriptCore shell (jsc)")
def test_modules_parse_and_templates_compile() -> None:
    done = subprocess.run(
        [str(JSC), "-m", str(JS_CHECK)], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0 and done.stdout.strip().endswith("ok"), done.stdout + done.stderr
