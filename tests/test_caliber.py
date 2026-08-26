from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.errors import LockRefused
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


def _coa(drop: Path) -> Path:
    return _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"], ["2001", "AP"]])


def _gl(drop: Path) -> Path:
    return _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])


def test_lock_without_aux_or_map(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.lock()
    names = window.table_names()
    assert "coa" in names
    assert "gl" in names
    assert "aux" not in names
    assert "map" not in names


def test_units_shortcut_writes_aux(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.lock()
    names = window.table_names()
    assert "units" in names
    assert "aux" in names
    rows = window.query("SELECT dim_id, member_id, member_name FROM aux")
    assert ("unit", "OU1", "North") in rows


def test_empty_provided_aux_refuses(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="aux is empty"):
        window.import_tables(
            coa=_coa(drop),
            aux=_xlsx(drop / "aux.xlsx", ["dim_id", "dim_name", "member_id", "member_name"], []),
            named=[{"id": "gl", "path": _gl(drop)}],
        )


def test_map_locks_and_lists_orphans(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    mapping = _xlsx(
        drop / "map.xlsx",
        ["source_account_code", "analysis_node_id", "analysis_node_name"],
        [["1001", "cash", "Cash node"], ["9999", "ghost", "Ghost"]],
    )
    window.import_tables(coa=_coa(drop), map=mapping, named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.lock()
    codes = [row[0] for row in window.query("SELECT source_account_code FROM map")]
    assert codes == ["1001"]
    assert any(item == "map:orphan:9999" for item in window.extras())
    before = window.hashes()
    _xlsx(
        drop / "map.xlsx",
        ["source_account_code", "analysis_node_id", "analysis_node_name"],
        [["1001", "changed", "Changed"]],
    )
    after = window.hashes()
    assert before["map"] == after["map"]


def test_map_conflict_refuses(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    mapping = _xlsx(
        drop / "map.xlsx",
        ["source_account_code", "analysis_node_id", "analysis_node_name"],
        [["1001", "a", "A"], ["1001", "b", "B"]],
    )
    with pytest.raises(LockRefused, match="map conflict"):
        window.import_tables(coa=_coa(drop), map=mapping, named=[{"id": "gl", "path": _gl(drop)}])


def test_map_required_question_without_map_is_not_in_window(tmp_path: Path) -> None:
    from foundry.brief import emit_brief
    from foundry.questions import record_questions

    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.lock()
    record_questions(
        window,
        [
            {"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]},
            {"id": "q2", "text": "按分析节点看贡献", "required_table_ids": ["gl", "map"]},
        ],
    )
    text = emit_brief(window)
    assert "not-in-this-window" in text or "不在本窗口" in text
    assert "GL" in text or "gl" in text
