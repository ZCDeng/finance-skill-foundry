"""Regressions for the conclusion brief: window attribution, the one-shot
latch, and the one-question-one-table rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.errors import LockRefused
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


def _locked(tmp_path: Path):
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[
            {"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])},
            {"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 40]])},
        ],
        drop_dir=drop,
    )
    window.lock()
    return store, window, drop


def test_brief_names_its_own_window(tmp_path: Path) -> None:
    """#19 -- a follow-up needs the brief's window id, and only the brief carries it."""
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])

    text = emit_brief(window)

    assert f"窗口: {window.id}" in text
    assert f"窗口: {window.id}" in window.workpaper_path.read_text()


def test_followup_answer_names_the_window_it_answered_from(tmp_path: Path) -> None:
    """#19 -- after a re-import `current` is a new window; the answer must say which one it used."""
    store, window, drop = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    nxt = window.reimport(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl2.xlsx", ["account_code", "amount"], [["1001", 7]])}],
        drop_dir=drop,
    )
    nxt.lock()

    historical = query_locked(
        store.get(window.id), "GL 合计", required_table_ids=["gl"], brief_window_id=window.id
    )
    current = query_locked(nxt, "GL 合计", required_table_ids=["gl"])

    assert window.id in historical
    assert nxt.id not in historical
    assert nxt.id in current
    assert window.id not in current


def test_partial_brief_does_not_wedge_the_window(tmp_path: Path) -> None:
    """#38 -- a crash between the two brief writes used to refuse emit-brief forever."""
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    window.brief_path.write_text("# 本期结论稿\n\n(interrupted)\n")

    text = emit_brief(window)

    assert "GL 合计" in text
    assert window.state == "Briefed"
    assert (window.root / "brief_facts.json").exists()
    assert window.schedules_path.exists()
    assert window.workpaper_path.exists()
    assert query_locked(window, "GL 合计", required_table_ids=["gl"]).startswith("报表声称")


def test_partial_brief_facts_do_not_wedge_the_window(tmp_path: Path) -> None:
    """#38 -- the same recovery when only the facts file survived the crash."""
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    (window.root / "brief_facts.json").write_text("[]\n")

    text = emit_brief(window)

    assert "GL 合计" in text
    assert window.state == "Briefed"
    assert query_locked(window, "GL 合计", required_table_ids=["gl"]).startswith("报表声称")


def test_two_named_tables_in_one_question_is_refused_at_record_time(tmp_path: Path) -> None:
    """#18 -- no defined cross-table calculation, so refuse before the brief is drafted."""
    _, window, _ = _locked(tmp_path)

    with pytest.raises(LockRefused) as excinfo:
        record_questions(window, [{"id": "q1", "text": "GL 加 AR", "required_table_ids": ["gl", "ar"]}])

    message = str(excinfo.value)
    assert "q1" in message
    assert "gl" in message and "ar" in message
    assert not window.questions_path.exists()
    assert window.state == "Locked"


def test_master_tables_alongside_one_named_table_stay_allowed(tmp_path: Path) -> None:
    """#18 -- coa/aux/map/units shape the cut; they are not a second fact table."""
    _, window, _ = _locked(tmp_path)

    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["coa", "gl"]}])

    assert window.questions_path.exists()


def test_brief_facts_are_written_before_the_brief(tmp_path: Path, monkeypatch) -> None:
    """#38 -- brief_facts.json is the dependency `query_locked` cites from, so an
    interrupted emit must leave the facts present and no half-written brief.md."""
    import foundry.brief as brief_module

    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    real = brief_module.write_text_atomic

    def interrupt_on_brief(path: Path, text: str) -> None:
        if path == window.brief_path:
            raise KeyboardInterrupt("host kill")
        real(path, text)

    monkeypatch.setattr(brief_module, "write_text_atomic", interrupt_on_brief)
    with pytest.raises(KeyboardInterrupt):
        emit_brief(window)

    assert (window.root / "brief_facts.json").exists()
    assert not window.brief_path.exists()
    assert window.state == "Locked"

    monkeypatch.undo()
    assert "GL 合计" in emit_brief(window)
    assert window.state == "Briefed"
