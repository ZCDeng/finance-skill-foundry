from __future__ import annotations

import json
from pathlib import Path

from foundry.brief import emit_brief
from foundry.launch_formulator import launch_spec, stop_lease, write_connectors
from foundry.probe import mark_done, run_probe
from foundry.questions import record_questions
from foundry.window import WindowStore
from openpyxl import Workbook


def _authored_skill_text() -> str:
    return """# method

This skill is an F2 finance method skill.

It follows FOUNDRY.md and CONNECTORS.md, reads only the locked period brief,
uses query-locked for follow-up calculations, and labels anything outside the
locked window as 稿外追问.
"""


def _write_contract(skill: Path) -> None:
    (skill / "foundry.json").write_text(
        json.dumps(
            {
                "schema": "finance-skill-foundry/f2-skill@1",
                "capability": "f2-period-analysis",
                "period_tools": ["import", "lock", "record-questions", "emit-brief", "query-locked"],
                "safety": {
                    "questions_in_window": True,
                    "no_read_document_books": True,
                    "tag_followups": True,
                },
                "method_docs": ["FOUNDRY.md", "CONNECTORS.md"],
            }
        )
    )


def _xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def test_successor_brief_does_not_answer_prior_questions(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    a1 = store.create()
    a1.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    a1.lock()
    record_questions(a1, [{"id": "a1q", "text": "A1 独家问题", "required_table_ids": ["gl"]}])
    a1_brief = emit_brief(a1)
    assert "A1 独家问题" in a1_brief

    skill = tmp_path / "skills" / "a4"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_authored_skill_text())
    _write_contract(skill)
    mark_done(skill, tmp_path / "var-probe", Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke")

    a4 = store.create()
    a4.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    a4.lock()
    record_questions(a4, [{"id": "a4q", "text": "A4 新问题", "required_table_ids": ["gl"]}])
    a4_brief = emit_brief(a4)
    assert "A4 新问题" in a4_brief
    assert "A1 独家问题" not in a4_brief


def test_successor_formulator_home_does_not_list_prior_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    a1 = store.create()
    a1.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    a1.lock()
    first_spec = launch_spec(a1)
    write_connectors(Path(first_spec["home"]))
    assert (store.formulator_dir / a1.id).exists()
    stop_lease(a1)
    a4 = store.create()
    a4.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 9]])}],
        drop_dir=drop,
    )
    a4.lock()
    spec = launch_spec(a4)
    assert a1.id not in spec["home"]
    assert not (store.formulator_dir / a1.id).exists()


def test_successor_without_prior_window_runs_fixture_loop(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(_authored_skill_text())
    _write_contract(skill)
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke"
    mark_done(skill, tmp_path / "var", fixtures)
    assert run_probe(tmp_path / "var-f2", fixtures) == 0
