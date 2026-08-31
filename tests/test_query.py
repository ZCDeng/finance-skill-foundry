from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.errors import QueryRefused
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
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"], ["OU2", "South"]]),
        named=[
            {
                "id": "gl",
                "path": _xlsx(
                    drop / "gl.xlsx",
                    ["account_code", "unit_id", "amount"],
                    [["1001", "OU1", 70], ["1001", "OU2", 30]],
                ),
            },
            {"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 40]])},
        ],
        drop_dir=drop,
    )
    window.lock()
    return store, window, drop


def test_followup_not_on_brief_is_tagged(tmp_path: Path) -> None:
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    answer = query_locked(window, "按经营单元拆分 GL", required_table_ids=["gl"], split_by="unit_id")
    assert answer.startswith("稿外追问")
    assert "我重算" in answer


def test_unknown_table_refused(tmp_path: Path) -> None:
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    with pytest.raises(QueryRefused):
        query_locked(window, "FA 净值", required_table_ids=["fa"])


def test_named_not_on_brief_may_recompute(tmp_path: Path) -> None:
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    answer = query_locked(window, "AR 合计", required_table_ids=["ar"])
    assert "稿外追问" in answer
    assert "40" in answer


def test_same_table_same_value_different_question_is_followup(tmp_path: Path) -> None:
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    answer = query_locked(window, "GL 另一个问法", required_table_ids=["gl"])
    assert answer.startswith("稿外追问")
    cited = query_locked(window, "GL 合计", required_table_ids=["gl"])
    assert cited.startswith("报表声称")


def test_question_id_does_not_bypass_required_table_match(tmp_path: Path) -> None:
    """A question_id must never make a mismatched table list cite the brief."""
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)

    with pytest.raises(QueryRefused) as caught:
        query_locked(window, "GL 合计", required_table_ids=["gl", "ar"], question_id="q1")

    assert "报表声称" not in str(caught.value)
    assert not window.followup_path.exists()


# --- #18 a two-table follow-up must not answer from the first table ---------


def test_two_named_tables_refuse_instead_of_answering_from_one(tmp_path: Path) -> None:
    """gl is 100 and ar is 40; 'GL+AR 合计' has no defined caliber, so refuse."""
    _, window, _ = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)

    with pytest.raises(QueryRefused, match="一问一表"):
        query_locked(window, "GL+AR 合计", required_table_ids=["gl", "ar"])
    with pytest.raises(QueryRefused, match="一问一表"):
        query_locked(window, "GL+AR 按经营单元", required_table_ids=["gl", "ar"], split_by="unit_id")

    assert not window.followup_path.exists()
    assert window.state == "Briefed"


def test_query_refuses_before_lock(tmp_path: Path) -> None:
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(QueryRefused):
        query_locked(window, "GL 合计", required_table_ids=["gl"])


def test_historical_brief_window_survives_reimport(tmp_path: Path) -> None:
    store, window, drop = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    nxt = window.reimport(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[
            {
                "id": "gl",
                "path": _xlsx(drop / "gl2.xlsx", ["account_code", "unit_id", "amount"], [["1001", "OU1", 1]]),
            }
        ],
        drop_dir=drop,
    )
    nxt.lock()
    historical = store.get(window.id)
    answer = query_locked(historical, "GL 合计", required_table_ids=["gl"], brief_window_id=window.id)
    assert "100" in answer


def test_decimal_followup_writes_jsonl(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    store = WindowStore(tmp_path / "var")
    window = store.create()
    coa = drop / "coa.csv"
    coa.write_text("account_code,account_name\n1001,Cash\n", encoding="utf-8")
    gl = drop / "gl.csv"
    gl.write_text("account_code,amount\n1001,1.25\n", encoding="utf-8")
    ar = drop / "ar.csv"
    ar.write_text("account_code,amount\n1001,2.50\n", encoding="utf-8")
    window.import_tables(
        coa=coa,
        named=[{"id": "gl", "path": gl}, {"id": "ar", "path": ar}],
        drop_dir=drop,
    )
    window.lock()
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    answer = query_locked(window, "AR 合计", required_table_ids=["ar"])
    assert "2.5" in answer or "2.50" in answer
    payload = json.loads(window.followup_path.read_text().strip())
    assert payload["value"] == "2.5"


def test_split_by_requires_amount_column(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[{"id": "notes", "path": _xlsx(drop / "notes.xlsx", ["account_code", "unit_id"], [["1001", "OU1"]])}],
        drop_dir=drop,
    )
    window.lock()
    record_questions(window, [{"id": "q1", "text": "notes", "required_table_ids": ["notes"]}])
    emit_brief(window)
    with pytest.raises(QueryRefused, match="no amount"):
        query_locked(window, "notes by unit", required_table_ids=["notes"], split_by="unit_id")


# --- #13 follow-up: the operator's spelling must reach the catalog id -------


def _locked_hyphenated(tmp_path: Path):
    """A drop whose file name is an ordinary period name: ar-2024-08.xlsx."""
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[
            {
                "id": "ar-2024-08",
                "path": _xlsx(drop / "ar-2024-08.xlsx", ["account_code", "amount"], [["1001", 40]]),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    return store, window


def test_a_hyphenated_table_answers_under_the_operators_spelling(tmp_path: Path) -> None:
    _, window = _locked_hyphenated(tmp_path)
    assert "ar_2024_08" in window.table_names()

    answer = query_locked(window, "AR 合计", required_table_ids=["ar-2024-08"])
    assert "40" in answer
    assert "稿外追问" in answer


def test_a_hyphenated_table_is_not_reported_missing_by_the_brief(tmp_path: Path) -> None:
    _, window = _locked_hyphenated(tmp_path)
    record_questions(
        window, [{"id": "q1", "text": "AR 合计是多少?", "required_table_ids": ["ar-2024-08"]}]
    )
    brief = emit_brief(window)

    assert "not-in-this-window" not in brief
    assert "40" in brief
    cited = query_locked(window, "AR 合计是多少?", required_table_ids=["ar-2024-08"], question_id="q1")
    assert cited.startswith("报表声称")


# --- a follow-up will not carry one either ---------------------------------
#
# `query-locked` is the only tool the `f3` preset offers, so this is the path a
# leader's question actually travels. Closing the brief and leaving this open
# would put the fence on the door nobody uses.


def _two_measure_locked(tmp_path: Path):
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
                    ["account_code", "region", "amount"],
                    [["6001", "east", 100], ["1122", "east", 30], ["6001", "west", 50]],
                ),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    return window


def test_followup_refuses_a_whole_table_total_over_several_measures(tmp_path: Path) -> None:
    window = _two_measure_locked(tmp_path)
    with pytest.raises(QueryRefused) as caught:
        query_locked(window, "合计多少", required_table_ids=["city_pl"])
    assert "city_pl" in str(caught.value)
    assert "2 account codes" in str(caught.value)


def test_followup_refuses_a_cut_that_still_mixes_them(tmp_path: Path) -> None:
    # `east=130` is revenue plus receivables. Splitting moved the mixing inside
    # each part rather than removing it.
    window = _two_measure_locked(tmp_path)
    with pytest.raises(QueryRefused) as caught:
        query_locked(window, "分区域", required_table_ids=["city_pl"], split_by="region")
    assert "split by region" in str(caught.value)


def test_followup_allows_the_cut_that_separates_them(tmp_path: Path) -> None:
    window = _two_measure_locked(tmp_path)
    answer = query_locked(
        window, "按科目", required_table_ids=["city_pl"], split_by="account_code"
    )
    assert "6001=150" in answer
    assert "1122=30" in answer


def test_followup_still_answers_a_single_measure_table(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1122", "应收账款"]]),
        named=[
            {
                "id": "ar",
                "path": _xlsx(
                    drop / "ar.xlsx",
                    ["account_code", "region", "amount"],
                    [["1122", "east", 40], ["1122", "west", 60]],
                ),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    assert "100" in query_locked(window, "应收合计", required_table_ids=["ar"])
    assert "east=40" in query_locked(
        window, "分区域应收", required_table_ids=["ar"], split_by="region"
    )
