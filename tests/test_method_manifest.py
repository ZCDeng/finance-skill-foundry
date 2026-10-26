from __future__ import annotations

import json
import hashlib

import pytest

from foundry.cli import main
from foundry.errors import FoundryError
from foundry.method_skills import (
    BUNDLED_IDS,
    BUNDLED_PACKS,
    METHOD_RESOURCE_NAMES,
    bundled_skill_manifest,
    method_root,
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

    visuals = read_method_resource("financial-statements", "report-visuals.md")
    assert visuals["resource"] == "report-visuals.md"
    assert "reportVisual" in visuals["content"]


def test_read_method_resource_refuses_unknown_skills_and_paths() -> None:
    with pytest.raises(FoundryError, match="unknown method skill"):
        read_method_resource("not-a-skill", "FOUNDRY.md")
    with pytest.raises(FoundryError, match="not allowed"):
        read_method_resource("financial-statements", "../FOUNDRY.md")
    with pytest.raises(FoundryError, match="not allowed"):
        read_method_resource("financial-statements", "README.md")


@pytest.mark.parametrize("skill_id", BUNDLED_IDS + BUNDLED_PACKS)
@pytest.mark.parametrize("resource", ["accounting-basis.md", "close-checklist.md", "model-checks.md", "forecast-models.md"])
def test_every_existing_entry_can_read_professional_guidance(skill_id, resource):
    result = read_method_resource(skill_id, resource)
    assert result["skill"] == skill_id and result["resource"] == resource
    assert result["sha256"] == hashlib.sha256(result["content"].encode()).hexdigest()
    assert result["content"].startswith("# ")


def test_manifest_binds_guidance_and_separates_implementation_from_professional_evidence():
    manifest = bundled_skill_manifest()
    resources = {item["resource"]: item for item in manifest["resources"]}
    assert set(resources) == set(METHOD_RESOURCE_NAMES)
    for item in resources.values():
        assert item["exists"] is True
        assert item["sha256"] == hashlib.sha256((method_root() / item["resource"]).read_bytes()).hexdigest()
    support = manifest["support_matrix"]
    assert support["sha256"] == hashlib.sha256((method_root() / "support-matrix.json").read_bytes()).hexdigest()
    entries = support["content"]["entries"]
    assert {entry["method_id"] for entry in entries} == {f"F{number:02d}" for number in range(1, 13)}
    for entry in entries:
        assert entry["basis"] and entry["report_purpose"] and entry["effective_period"]
        assert entry["evidence"]["live_model"]["status"] == "not_evaluated"
        assert entry["evidence"]["human_professional"]["status"] == "not_reviewed"
        assert entry["professional_release"] is False


def test_model_checks_have_complete_identified_coverage_and_no_blanket_pass():
    text = (method_root() / "model-checks.md").read_text()
    for number in range(1, 25):
        assert f"| K{number:02d} |" in text
    for field in ("check_id", "expected", "actual", "difference", "tolerance", "coverage", "not_applicable", "unavailable", "stale"):
        assert field in text
    assert "缓存" in text and "真实重算" in text and "不能标为 pass" in text
