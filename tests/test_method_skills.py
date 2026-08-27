from __future__ import annotations

import json
from pathlib import Path

from foundry.method_skills import BUNDLED_IDS, bundled_skill_files, method_root
from foundry.probe import skill_contains_questions

ROOT = Path(__file__).resolve().parents[1]


def test_four_method_skills_ship_in_package() -> None:
    files = bundled_skill_files()
    assert tuple(files) == BUNDLED_IDS
    for skill_id, path in files.items():
        assert path.is_file(), skill_id
        text = path.read_text()
        assert f"name: {skill_id}" in text
        assert "FOUNDRY.md" in text
        assert "CONNECTORS.md" in text


def test_method_skills_are_not_this_window_questions() -> None:
    root = method_root()
    assert (root / "FOUNDRY.md").is_file()
    assert (root / "NOTICE").is_file()
    for skill_id, path in bundled_skill_files().items():
        assert skill_contains_questions(path.parent) is False, skill_id
    assert skill_contains_questions(root) is False


def test_dsh_bundle_declares_method_skills() -> None:
    data = json.loads((ROOT / "dsh-plugin" / "package.json").read_text())
    declared = data["dsh"]["foundry"]["methodSkills"]
    assert declared["dir"] == "../method"
    assert declared["ids"] == list(BUNDLED_IDS)
