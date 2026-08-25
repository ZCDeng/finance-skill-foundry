from __future__ import annotations

from pathlib import Path

import pytest

from foundry.errors import FoundryError
from foundry.probe import mark_done, run_probe, skill_contains_questions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke"


def test_probe_passes_on_fixture_subset(tmp_path: Path) -> None:
    assert run_probe(tmp_path / "var", FIXTURES) == 0


def test_chat_only_skill_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# chat only\n")
    (skill / "questions.md").write_text("1. 利润?\n")
    with pytest.raises(FoundryError, match="questions"):
        mark_done(skill, tmp_path / "var", FIXTURES)


def test_mark_done_after_probe(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# method\n整理重点: 贡献\n")
    mark_done(skill, tmp_path / "var", FIXTURES)


def test_questions_file_detected() -> None:
    assert skill_contains_questions(Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke") is True
