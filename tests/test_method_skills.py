from __future__ import annotations

import json
from pathlib import Path

from foundry import tags as tags_module
from foundry.method_skills import BUNDLED_IDS, bundled_skill_files, method_root
from foundry.probe import skill_contains_questions

ROOT = Path(__file__).resolve().parents[1]


def _tag_vocabulary() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(tags_module).items()
        if name.isupper() and isinstance(value, str)
    }


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


def test_foundry_md_documents_every_output_tag() -> None:
    vocabulary = _tag_vocabulary()
    assert vocabulary, "foundry.tags exposes no tag constants"
    text = (method_root() / "FOUNDRY.md").read_text(encoding="utf-8")
    missing = sorted(f"{name}={value}" for name, value in vocabulary.items() if value not in text)
    assert missing == [], f"tags undocumented in FOUNDRY.md: {missing}"


def test_dsh_bundle_declares_method_skills() -> None:
    data = json.loads((ROOT / "dsh-plugin" / "package.json").read_text())
    declared = data["dsh"]["foundry"]["methodSkills"]
    assert declared["dir"] == "../method"
    assert declared["ids"] == list(BUNDLED_IDS)
