from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.errors import FoundryError
from foundry.probe import mark_done, run_probe, skill_contains_questions, validate_authored_skill

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke"


def authored_skill_text() -> str:
    return """# method

This skill is an F2 finance method skill.

It follows FOUNDRY.md and CONNECTORS.md, reads only the locked period brief,
uses query-locked for follow-up calculations, and labels anything outside the
locked window as 稿外追问.
"""


def write_contract(skill: Path, *, period_tools: list[str] | None = None) -> None:
    (skill / "foundry.json").write_text(
        json.dumps(
            {
                "schema": "finance-skill-foundry/f2-skill@1",
                "capability": "f2-period-analysis",
                "period_tools": period_tools
                or ["import", "lock", "record-questions", "emit-brief", "query-locked"],
                "safety": {
                    "questions_in_window": True,
                    "no_read_document_books": True,
                    "tag_followups": True,
                },
                "method_docs": ["FOUNDRY.md", "CONNECTORS.md"],
            }
        )
    )


def test_probe_passes_on_fixture_subset(tmp_path: Path) -> None:
    assert run_probe(tmp_path / "var", FIXTURES) == 0


def test_chat_only_skill_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# chat only\n")
    (skill / "questions.md").write_text("1. 利润?\n")
    with pytest.raises(FoundryError, match="questions"):
        mark_done(skill, tmp_path / "var", FIXTURES)


def test_empty_skill_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("")
    with pytest.raises(FoundryError, match="authored instructions"):
        mark_done(skill, tmp_path / "var", FIXTURES)


def test_keyword_pile_chat_shell_without_contract_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "# method\n\nFOUNDRY.md CONNECTORS.md query-locked 稿外追问 import lock emit-brief\n"
    )
    with pytest.raises(FoundryError, match="foundry.json capability contract"):
        validate_authored_skill(skill)


def test_contract_missing_any_f2_tool_fails(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(authored_skill_text())
    write_contract(skill, period_tools=["import", "lock", "record-questions", "emit-brief"])
    with pytest.raises(FoundryError, match="period_tools"):
        validate_authored_skill(skill)


def test_mark_done_after_probe(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(authored_skill_text())
    write_contract(skill)
    mark_done(skill, tmp_path / "var", FIXTURES)


def test_questions_file_detected() -> None:
    assert skill_contains_questions(Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke") is True
