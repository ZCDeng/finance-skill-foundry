from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.caliber import MapEntry, cut_fact_by_map, parse_map_entries, resolve_node
from foundry.errors import LockRefused, QueryRefused
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
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
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
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    return window


def test_resolve_prefers_full_aux_over_account_only() -> None:
    entries = parse_map_entries(
        ["source_account_code", "analysis_node_id", "analysis_node_name", "dim_id", "member_id"],
        [
            ("1001", "all", "All cash", "", ""),
            ("1001", "north", "North cash", "unit", "OU1"),
        ],
    )
    hit = resolve_node(entries, "1001", [("unit", "OU1")])
    assert hit is not None
    assert hit.node_id == "north"


def test_resolve_falls_back_to_account_only() -> None:
    entries = [
        MapEntry("1001", "", "", "cash", "Cash"),
        MapEntry("2001", "", "", "ap", "AP"),
    ]
    hit = resolve_node(entries, "1001", [("unit", "OU1")])
    assert hit is not None
    assert hit.node_id == "cash"


def test_resolve_same_priority_conflict() -> None:
    entries = [
        MapEntry("1001", "unit", "", "a", "A"),
        MapEntry("1001", "", "OU1", "b", "B"),
    ]
    with pytest.raises(LockRefused, match="map conflict"):
        resolve_node(entries, "1001", [("unit", "OU1")])


def test_cut_leaves_unmapped_residue() -> None:
    cut = cut_fact_by_map(
        ["account_code", "amount"],
        [("1001", 80), ("2001", 20)],
        ["source_account_code", "analysis_node_id", "analysis_node_name"],
        [("1001", "cash", "Cash")],
    )
    assert cut.claimed == 100
    assert cut.unmapped == 20
    assert cut.nodes == [("cash", "Cash", 80.0)]


def test_brief_map_cut_is_recomputed(tmp_path: Path) -> None:
    window = _locked_with_map(tmp_path)
    record_questions(
        window,
        [{"id": "q1", "text": "按分析节点看贡献", "required_table_ids": ["gl", "map"]}],
    )
    text = emit_brief(window)
    assert "我重算" in text
    assert "north=70" in text
    assert "south=30" in text
    assert "稿外追问" not in text
    assert "报表声称" in text


def test_brief_map_cut_without_map_is_not_in_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    window.lock()
    record_questions(
        window,
        [
            {"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]},
            {"id": "q2", "text": "按分析节点看贡献", "required_table_ids": ["gl", "map"]},
        ],
    )
    text = emit_brief(window)
    assert "not-in-this-window" in text
    assert "GL" in text or "gl" in text


def test_query_analysis_node_split_is_outside(tmp_path: Path) -> None:
    window = _locked_with_map(tmp_path)
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    answer = query_locked(
        window,
        "按分析节点拆 GL",
        required_table_ids=["gl", "map"],
        split_by="analysis_node",
        question_id="q1",
    )
    assert answer.startswith("稿外追问")
    assert "我重算" in answer
    assert "north=70" in answer
    assert "south=30" in answer


def test_query_analysis_node_on_brief_is_recomputed_only(tmp_path: Path) -> None:
    window = _locked_with_map(tmp_path)
    record_questions(
        window,
        [{"id": "q1", "text": "按分析节点看贡献", "required_table_ids": ["gl", "map"]}],
    )
    emit_brief(window)
    answer = query_locked(
        window,
        "按分析节点拆 GL",
        required_table_ids=["gl"],
        split_by="analysis_node",
        question_id="q1",
    )
    assert answer.startswith("我重算")
    assert "稿外追问" not in answer
    assert "north=70" in answer


def test_query_analysis_node_refused_without_map(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    window.lock()
    with pytest.raises(QueryRefused, match="map"):
        query_locked(window, "按分析节点拆 GL", required_table_ids=["gl"], split_by="analysis_node")
