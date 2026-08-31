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


def test_large_integer_amount_stays_exact(tmp_path: Path) -> None:
    from foundry.query import query_locked

    drop = tmp_path / "drop"
    value = 9007199254740993
    window = WindowStore(tmp_path / "var").create()
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text(f"account_code,amount\n1001,{value}\n")
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[{"id": "gl", "path": gl}],
        drop_dir=drop,
    )
    window.lock()
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    brief = emit_brief(window)
    assert str(value) in brief
    assert str(value) in window.workpaper_path.read_text()
    assert str(value) in query_locked(window, "GL 合计", required_table_ids=["gl"], question_id="q1")


def test_unsafe_xlsx_numeric_amount_refuses(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    value = 9007199254740993
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="unsafe xlsx numeric precision"):
        window.import_tables(
            coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
            named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", value]])}],
            drop_dir=drop,
        )


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
    with pytest.raises(LockRefused):
        record_questions(window, [{"id": "q1", "text": "x", "required_table_ids": ["gl"]}])
    with pytest.raises(LockRefused):
        emit_brief(window)


def test_source_edit_does_not_change_brief(tmp_path: Path) -> None:
    _, window, drop = _locked_gl_ar(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    first = emit_brief(window)
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 999]])
    assert emit_brief(window) == first
    assert window.brief_path.read_text() == first


def test_question_schema_and_state_gate(tmp_path: Path) -> None:
    _, window, _ = _locked_gl_ar(tmp_path)
    with pytest.raises(LockRefused, match="required_table_ids"):
        record_questions(window, [{"id": "q1", "text": "GL", "required_table_ids": []}])
    record_questions(window, [{"id": "q1", "text": "GL", "required_table_ids": ["gl"]}])
    with pytest.raises(LockRefused, match="already recorded"):
        record_questions(window, [{"id": "q2", "text": "AR", "required_table_ids": ["ar"]}])
    first = emit_brief(window)
    assert emit_brief(window) == first
    assert window.brief_path.read_text() == first


def test_brief_idempotent_after_followup_preserves_schedules(tmp_path: Path) -> None:
    from foundry.query import query_locked

    _, window, _ = _locked_gl_ar(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    first = emit_brief(window)
    query_locked(window, "AR 追问", required_table_ids=["ar"])
    schedules_before = window.schedules_path.read_text()
    assert emit_brief(window) == first
    assert window.schedules_path.read_text() == schedules_before


# --- a brief will not carry a figure nobody can derive ---------------------


def _two_measure_window(tmp_path: Path):
    """A window whose one named table holds revenue and receivables together."""
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(
            drop / "coa.xlsx",
            ["account_code", "account_name"],
            [["6001", "营业收入"], ["1122", "应收账款"]],
        ),
        named=[
            {
                "id": "city_pl",
                "path": _xlsx(
                    drop / "city_pl.xlsx",
                    ["account_code", "unit_id", "amount"],
                    [["6001", "C01", 100], ["1122", "C01", 30]],
                ),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    return window


def test_brief_refuses_a_table_holding_more_than_one_measure(tmp_path: Path) -> None:
    """The defect this closes shipped a number and called it 我重算.

    A `city_pl` carrying nine measures answered three different questions with
    889,003.9147 -- square metres and project counts added into yuan -- and
    nothing refused, because nothing looked.
    """
    window = _two_measure_window(tmp_path)
    record_questions(
        window, [{"id": "q-op", "text": "营业利润是多少", "required_table_ids": ["city_pl"]}]
    )
    with pytest.raises(LockRefused) as caught:
        emit_brief(window)
    message = str(caught.value)
    # Which question, which table, and what to do about it.
    assert "q-op" in message
    assert "city_pl" in message
    assert "2 account codes" in message
    assert "one account per table" in message


def test_the_refusal_leaves_the_window_locked_rather_than_briefed(tmp_path: Path) -> None:
    # A refused brief must not latch the state, or the fix would have nowhere
    # to run: `emit_brief` only recomputes from `Locked`.
    window = _two_measure_window(tmp_path)
    record_questions(
        window, [{"id": "q-op", "text": "营业利润是多少", "required_table_ids": ["city_pl"]}]
    )
    with pytest.raises(LockRefused):
        emit_brief(window)
    assert window.state == "Locked"
    assert not window.brief_path.exists()


def test_one_measure_across_many_units_still_briefs(tmp_path: Path) -> None:
    # The shape the kit's own fixtures use, and the shape the rule is written
    # to leave alone: one account, any number of units, one number out.
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1122", "应收账款"]]),
        named=[
            {
                "id": "ar",
                "path": _xlsx(
                    drop / "ar.xlsx",
                    ["account_code", "unit_id", "amount"],
                    [["1122", "C01", 40], ["1122", "C02", 60]],
                ),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    record_questions(
        window, [{"id": "q-ar", "text": "应收合计", "required_table_ids": ["ar"]}]
    )
    assert "100" in emit_brief(window)


def test_a_map_gives_every_account_a_node_and_the_total_back(tmp_path: Path) -> None:
    # The other way out named in the refusal. With a map the operator has said
    # what each account rolls into, so the cut is defined and the brief reports
    # it per node rather than as one mixed sum.
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(
            drop / "coa.xlsx",
            ["account_code", "account_name"],
            [["6001", "营业收入"], ["1122", "应收账款"]],
        ),
        map=_xlsx(
            drop / "map.xlsx",
            ["source_account_code", "analysis_node_id", "analysis_node_name"],
            [["6001", "rev", "收入"], ["1122", "ar", "应收"]],
        ),
        named=[
            {
                "id": "city_pl",
                "path": _xlsx(
                    drop / "city_pl.xlsx",
                    ["account_code", "unit_id", "amount"],
                    [["6001", "C01", 100], ["1122", "C01", 30]],
                ),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    record_questions(
        window,
        [{"id": "q-node", "text": "按节点看", "required_table_ids": ["city_pl", "map"]}],
    )
    brief = emit_brief(window)
    assert "100" in brief and "30" in brief
