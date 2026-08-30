"""Regression for #11: the brief and a follow-up must pick the same source table."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.caliber import source_table_id
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.window import WindowStore


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


def _locked_with_coa_first(tmp_path: Path):
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    window.lock()
    return window


def test_selector_skips_master_tables() -> None:
    assert source_table_id(["coa", "gl"]) == "gl"
    assert source_table_id(["gl", "coa"]) == "gl"
    assert source_table_id(["coa"]) == "coa"


def test_followup_reuses_the_brief_source_table(tmp_path: Path) -> None:
    """A question authored as ["coa", "gl"] is answered from gl on both paths.

    Taking required_table_ids[0] verbatim answered from coa, which has no amount
    column, so the aggregate fell back to COUNT(*) = 1 and the citation lookup
    missed -- a row count stamped 稿外追问 / 我重算 and persisted as a recompute.
    """
    window = _locked_with_coa_first(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["coa", "gl"]}])
    brief = emit_brief(window)
    assert "gl 锁库汇总 100" in brief

    answer = query_locked(
        window, "GL 合计", required_table_ids=["coa", "gl"], question_id="q1"
    )

    assert answer.startswith("报表声称")
    assert "→ 100" in answer
    assert "稿外追问" not in answer
    assert window.state == "Briefed"
    assert not window.followup_path.exists()
