"""发布用的清单和布局：`.claude-plugin/marketplace.json` 要列出仓库里的每一个 skill（Claude Code
插件和 `npx skills` 都读它）；SKILL.md 的 frontmatter 带上 SkillHub 要的字段；收新闻和读新闻
两部分只通过新闻池的格式衔接，代码互不 import。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import newsdigest
import newsviewer
from newsdigest.paths import SKILL_DIR

REPO = SKILL_DIR.parent
SCRIPTS = SKILL_DIR / "scripts"
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
FRONT_MATTER_FIELDS = ["name", "slug", "displayName", "version", "description"]
# 每一部分的代码，以及它不能 import 的另一部分的包
PARTS = [
    ([SCRIPTS / "nd.py", *sorted((SCRIPTS / "newsdigest").glob("*.py"))], "newsviewer"),
    ([SCRIPTS / "nv.py", *sorted((SCRIPTS / "newsviewer").glob("*.py"))], "newsdigest"),
]


def _front_matter(skill_md: Path) -> dict[str, str]:
    front = skill_md.read_text(encoding="utf-8").split("---")[1]
    fields = (line.partition(": ") for line in front.strip().splitlines())
    return {key: value for key, _, value in fields}


def _imported_packages(path: Path) -> set[str]:
    """文件里绝对 import 的顶层包名；相对 import（`from . import x`）留在本包里，不算。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_marketplace_lists_every_skill() -> None:
    manifest = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    (plugin,) = manifest["plugins"]
    on_disk = sorted(f"./{p.parent.name}" for p in REPO.glob("*/SKILL.md"))
    assert sorted(plugin["skills"]) == on_disk


def test_skill_names_match_their_directories() -> None:
    for skill_md in REPO.glob("*/SKILL.md"):
        assert _front_matter(skill_md)["name"] == skill_md.parent.name, skill_md


def test_front_matter_has_the_skillhub_fields_and_the_package_versions() -> None:
    front = _front_matter(SKILL_DIR / "SKILL.md")
    assert list(front) == FRONT_MATTER_FIELDS
    assert all(front.values())
    assert front["slug"] == front["name"]
    assert front["version"] == newsdigest.__version__ == newsviewer.__version__


def test_imported_packages_sees_absolute_imports_only(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text(
        "import os.path\nfrom newsdigest.paths import SKILL_DIR\nfrom . import api\n",
        encoding="utf-8",
    )
    assert _imported_packages(src) == {"os", "newsdigest"}


def test_collecting_and_reading_never_import_each_other() -> None:
    for files, other in PARTS:
        assert len(files) > 1
        for path in files:
            assert other not in _imported_packages(path), path.relative_to(REPO)
