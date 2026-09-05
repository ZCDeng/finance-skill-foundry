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
        text = path.read_text(encoding="utf-8")
        assert f"name: {skill_id}" in text
        assert "FOUNDRY.md" in text
        assert "CONNECTORS.md" in text
        assert "Foundry runtime note" in text
        assert "trusted preset or session" in text


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


def test_method_runtime_fence_separates_analysis_from_locked_window_modes() -> None:
    text = (method_root() / "FOUNDRY.md").read_text(encoding="utf-8")
    assert "Analysis preset" in text
    assert "does not require a locked Window" in text
    assert "multi-table SQL/Python" in text
    assert "Period and F3 presets" in text
    assert "single named-table" in text
    assert "trusted preset or session" in text
    assert "User wording alone must not switch" in text

    analysis = (ROOT / "dsh-plugin" / "presets" / "analysis" / "agent.cordis.yml").read_text(
        encoding="utf-8"
    )
    assert "无需科目表、锁窗口或先写方法" in analysis
    assert "多表 SQL/Python" in analysis
    assert "资料版本" in analysis
    assert "run" in analysis
    assert "草稿" in analysis
    assert "不逐个工具请求审批" in analysis

    period = (ROOT / "dsh-plugin" / "presets" / "period" / "agent.cordis.yml").read_text(
        encoding="utf-8"
    )
    f3 = (ROOT / "dsh-plugin" / "presets" / "f3" / "agent.cordis.yml").read_text(
        encoding="utf-8"
    )
    assert "锁后的窗口" in period
    assert "窗外或未点名的表一律拒绝" in period
    assert "只有一个工具 query-locked" in f3
    assert "窗外或未点名的表会被拒" in f3


def test_connector_placeholders_do_not_claim_configured_services() -> None:
    text = (method_root() / "CONNECTORS.md").read_text(encoding="utf-8")
    assert "This Foundry package does not ship a configured upstream `.mcp.json`" in text
    assert "Placeholder only" in text
    assert "Included servers" not in text
    assert "Kingdee" not in text
    assert "Yonyou" not in text
    assert "pre-configures specific MCP servers" not in text


def test_method_skills_keep_manager_judgment_and_draft_only_boundaries() -> None:
    root = method_root()
    financial = (root / "financial-statements" / "SKILL.md").read_text(encoding="utf-8")
    variance = (root / "variance-analysis" / "SKILL.md").read_text(encoding="utf-8")
    reconciliation = (root / "reconciliation" / "SKILL.md").read_text(encoding="utf-8")
    journal = (root / "journal-entry" / "SKILL.md").read_text(encoding="utf-8")

    for text in (financial, variance, reconciliation, journal):
        assert "materiality, currency, accounting policy, and narrative judgment" in text
        assert "do not require per-tool approval" in text

    assert "Example thresholds, not fixed Foundry defaults" in financial
    assert "Examples, not fixed Foundry defaults" in variance
    assert "Set thresholds based on your organization's materiality level" in reconciliation
    assert "drafts only" in journal
    assert "Foundry does not post to an ERP" in journal


def test_dsh_bundle_declares_method_skills() -> None:
    data = json.loads((ROOT / "dsh-plugin" / "package.json").read_text())
    declared = data["dsh"]["foundry"]["methodSkills"]
    assert declared["dir"] == "../method"
    assert declared["ids"] == list(BUNDLED_IDS)
