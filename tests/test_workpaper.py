from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.caliber import cut_fact_by_map
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


def _locked_with_map(tmp_path: Path):
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"], ["2001", "AR"]]),
        map=_xlsx(
            drop / "map.xlsx",
            ["source_account_code", "analysis_node_id", "analysis_node_name", "dim_id", "member_id"],
            [
                ["1001", "north", "North cash", "unit", "OU1"],
                ["1001", "south", "South cash", "unit", "OU2"],
            ],
        ),
        named=[
            {
                "id": "gl",
                "path": _xlsx(
                    drop / "gl.xlsx",
                    ["account_code", "unit_id", "amount"],
                    [["1001", "OU1", 70], ["1001", "OU2", 30]],
                ),
            },
            {"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["2001", 40]])},
        ],
        drop_dir=drop,
    )
    window.lock()
    return window


def test_cut_lists_conflict_and_unmapped_lines() -> None:
    cut = cut_fact_by_map(
        ["account_code", "unit_id", "amount"],
        [("1001", "OU1", 40), ("2001", "OU1", 10)],
        ["source_account_code", "analysis_node_id", "analysis_node_name", "dim_id", "member_id"],
        [
            ("1001", "a", "A", "unit", ""),
            ("1001", "b", "B", "", "OU1"),
        ],
    )
    assert cut.conflict == 40
    assert cut.unmapped == 10
    assert cut.claimed == 50
    assert cut.recomputed == 50
    kinds = {line.match: line for line in cut.lines}
    assert kinds["冲突"].conflict_nodes == ("a", "b")
    assert kinds["未对照"].account == "2001"


def test_brief_writes_reviewable_workpaper(tmp_path: Path) -> None:
    window = _locked_with_map(tmp_path)
    record_questions(
        window,
        [
            {"id": "q-gl", "text": "GL 合计", "required_table_ids": ["gl"]},
            {"id": "q-map", "text": "按分析节点看贡献", "required_table_ids": ["gl", "map"]},
            {"id": "q-cf", "text": "现金流", "required_table_ids": ["cash_flow"]},
        ],
    )
    emit_brief(window)
    assert window.workpaper_path.exists()
    assert window.schedules_path.exists()
    paper = window.workpaper_path.read_text()
    assert "本期计算底稿" in paper
    assert "不是模型起草" in paper
    assert "归档 Excel 不是底稿" in paper
    assert "north" in paper
    assert "1001" in paper
    assert "unit/OU1" in paper
    assert "70" in paper
    assert "全辅助命中" in paper
    assert "not-in-this-window" in paper
    assert "稿外追问" not in window.brief_path.read_text()
    payload = json.loads(window.schedules_path.read_text())
    mapped = next(item for item in payload["items"] if item["id"] == "q-map")
    assert mapped["claimed"] == 100
    assert mapped["recomputed"] == 100
    assert {tuple(line["dims"][0]) for line in mapped["lines"]} == {("unit", "OU1"), ("unit", "OU2")}
    assert sum(line["amount"] for line in mapped["lines"]) == 100


def test_followup_appends_tagged_schedule(tmp_path: Path) -> None:
    window = _locked_with_map(tmp_path)
    record_questions(window, [{"id": "q-gl", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    before = json.loads(window.schedules_path.read_text())
    answer = query_locked(window, "按分析节点拆 GL", required_table_ids=["gl"], split_by="analysis_node")
    assert answer.startswith("稿外追问")
    after = json.loads(window.schedules_path.read_text())
    assert len(after["items"]) == len(before["items"]) + 1
    extra = after["items"][-1]
    assert extra["origin"] == "followup"
    assert extra["id"] == "followup-1"
    assert "稿外追问" in extra["tag"]
    assert any(line["account"] == "1001" and line["amount"] == 70 for line in extra["lines"])
    paper = window.workpaper_path.read_text()
    assert "followup-1" in paper
    assert "稿外追问" in paper
    assert "稿外追问" not in window.brief_path.read_text()


def test_on_brief_map_query_does_not_duplicate_schedule(tmp_path: Path) -> None:
    window = _locked_with_map(tmp_path)
    record_questions(
        window,
        [{"id": "q-map", "text": "按分析节点看贡献", "required_table_ids": ["gl", "map"]}],
    )
    emit_brief(window)
    before = json.loads(window.schedules_path.read_text())
    query_locked(window, "按分析节点拆 GL", required_table_ids=["gl"], split_by="analysis_node")
    after = json.loads(window.schedules_path.read_text())
    assert [item["id"] for item in after["items"]] == [item["id"] for item in before["items"]]


def test_source_edit_does_not_change_workpaper(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = _locked_with_map(tmp_path)
    record_questions(window, [{"id": "q-gl", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    first = window.workpaper_path.read_text()
    _xlsx(drop / "gl.xlsx", ["account_code", "unit_id", "amount"], [["1001", "OU1", 1]])
    emit_brief(window)
    assert window.workpaper_path.read_text() == first
