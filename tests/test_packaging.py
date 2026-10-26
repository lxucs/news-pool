"""发布用的清单：`.claude-plugin/marketplace.json` 要列出仓库里的每一个 skill（Claude Code 插件
和 `npx skills` 都读它）。"""

from __future__ import annotations

import json
import re

from newsdigest.paths import SKILL_DIR

REPO = SKILL_DIR.parent
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"


def test_marketplace_lists_every_skill() -> None:
    manifest = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    (plugin,) = manifest["plugins"]
    on_disk = sorted(f"./{p.parent.name}" for p in REPO.glob("*/SKILL.md"))
    assert sorted(plugin["skills"]) == on_disk


def test_skill_names_match_their_directories() -> None:
    for skill_md in REPO.glob("*/SKILL.md"):
        front = skill_md.read_text(encoding="utf-8").split("---")[1]
        assert re.search(rf"^name: {skill_md.parent.name}$", front, re.M), skill_md
