from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.errors import LockRefused
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


def _locked_gl_ar(tmp_path: Path):
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[
            {"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])},
            {"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 40]])},
        ],
        drop_dir=drop,
    )
    window.lock()
    return store, window, drop


def test_two_answerable_questions_have_conclusions_without_followup_tag(tmp_path: Path) -> None:
    _, window, _ = _locked_gl_ar(tmp_path)
    record_questions(
        window,
        [
            {"id": "q1", "text": "GL 合计是多少?", "required_table_ids": ["gl"]},
            {"id": "q2", "text": "AR 合计是多少?", "required_table_ids": ["ar"]},
        ],
    )
    text = emit_brief(window)
    assert "结论" in text
    assert "稿外追问" not in text
    assert "GL" in text or "gl" in text


def test_partial_brief_marks_missing_table(tmp_path: Path) -> None:
    _, window, _ = _locked_gl_ar(tmp_path)
    record_questions(
        window,
        [
            {"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]},
            {"id": "q2", "text": "现金流", "required_table_ids": ["cash_flow"]},
        ],
    )
    text = emit_brief(window)
    assert "not-in-this-window" in text or "不在本窗口" in text
    assert "结论" in text


def test_zero_questions_refuses_brief_but_keeps_lock(tmp_path: Path) -> None:
    _, window, _ = _locked_gl_ar(tmp_path)
    with pytest.raises(LockRefused):
        emit_brief(window)
    assert window.state == "Locked"


def test_brief_refuses_open_window(tmp_path: Path) -> None:
    window = WindowStore(tmp_path / "var").create()
    record_questions(window, [{"id": "q1", "text": "x", "required_table_ids": ["gl"]}])
    with pytest.raises(LockRefused):
        emit_brief(window)


def test_source_edit_does_not_change_brief(tmp_path: Path) -> None:
    _, window, drop = _locked_gl_ar(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    first = emit_brief(window)
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 999]])
    second = emit_brief(window)
    assert first == second
