from __future__ import annotations

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
