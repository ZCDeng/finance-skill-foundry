from __future__ import annotations

import json

import pytest

from foundry.cli import main
from foundry.errors import FoundryError
from foundry.method_skills import (
    BUNDLED_IDS,
    bundled_skill_manifest,
    read_method_resource,
)


def test_bundled_skill_manifest_names_root_ids_and_hashes() -> None:
    manifest = bundled_skill_manifest()
    assert manifest["exists"] is True
    assert manifest["ids"] == list(BUNDLED_IDS)
    assert manifest["source"] in {"repo", "package"}
    assert manifest["missing"] == []

    skills = {item["id"]: item for item in manifest["skills"]}  # type: ignore[index]
    assert set(skills) == set(BUNDLED_IDS)
    for skill_id in BUNDLED_IDS:
        item = skills[skill_id]
        assert item["exists"] is True
        assert item["file"].endswith(f"{skill_id}/SKILL.md")
        assert len(item["sha256"]) == 64
        assert item["bytes"] > 0


def test_cli_method_skills_json_prints_manifest(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--var", str(tmp_path / "var"), "method-skills", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ids"] == list(BUNDLED_IDS)
    assert out["exists"] is True
    assert all(len(item["sha256"]) == 64 for item in out["skills"])


def test_read_method_resource_allows_shared_docs_and_returns_content() -> None:
    foundry_doc = read_method_resource("financial-statements", "FOUNDRY.md")
    assert foundry_doc["skill"] == "financial-statements"
    assert foundry_doc["resource"] == "FOUNDRY.md"
    assert len(foundry_doc["sha256"]) == 64
    assert "analysis" in foundry_doc["content"]

    connectors = read_method_resource("variance-analysis", "CONNECTORS.md")
    assert connectors["resource"] == "CONNECTORS.md"
    assert "SQL" in connectors["content"]


def test_read_method_resource_refuses_unknown_skills_and_paths() -> None:
    with pytest.raises(FoundryError, match="unknown method skill"):
        read_method_resource("not-a-skill", "FOUNDRY.md")
    with pytest.raises(FoundryError, match="not allowed"):
        read_method_resource("financial-statements", "../FOUNDRY.md")
    with pytest.raises(FoundryError, match="not allowed"):
        read_method_resource("financial-statements", "README.md")
