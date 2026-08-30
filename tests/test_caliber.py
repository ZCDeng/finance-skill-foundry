from __future__ import annotations

from decimal import Decimal
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


def test_csv_amount_import_preserves_decimal_precision(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    coa = drop / "coa.csv"
    coa.write_text("account_code,account_name\n1001,Cash\n", encoding="utf-8")
    gl = drop / "gl.csv"
    gl.write_text("account_code,amount\n1001,9007199254740993.37\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=coa, named=[{"id": "gl", "path": gl}], drop_dir=drop)
    window.lock()
    value = window.query("SELECT SUM(amount) FROM gl")[0][0]
    assert value == Decimal("9007199254740993.37")


def test_json_named_table_imports_object_rows(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    drop.mkdir()
    coa = drop / "coa.csv"
    coa.write_text("account_code,account_name\n1001,Cash\n", encoding="utf-8")
    gl = drop / "gl.json"
    gl.write_text('[{"account_code":"1001","amount":"1.25"}]\n', encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=coa, named=[{"id": "gl", "path": gl}], drop_dir=drop)
    window.lock()
    assert window.query("SELECT SUM(amount) FROM gl")[0][0] == Decimal("1.25")


def test_units_derived_aux_is_tagged_apart_from_a_supplied_aux_file(tmp_path: Path) -> None:
    import json

    from foundry.catalog import file_hash

    drop = tmp_path / "drop"
    units = _xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]])
    derived = WindowStore(tmp_path / "var-derived").create()
    derived.import_tables(
        coa=_coa(drop),
        units=units,
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    derived.lock()
    derived_aux = json.loads(derived.lock_path.read_text())["aux"]
    assert derived_aux["derived_from"] == "units"
    assert "source_hash" not in derived_aux
    derived_hashes = derived.hashes()
    assert derived_hashes["aux_kind"] == "derived"
    assert derived_hashes["aux_derived_from"] == "units"
    assert derived_hashes["aux"] == derived_aux["loaded_hash"]

    aux_file = _xlsx(
        drop / "aux.xlsx",
        ["dim_id", "dim_name", "member_id", "member_name"],
        [["unit", "Unit", "OU1", "North"]],
    )
    supplied = WindowStore(tmp_path / "var-supplied").create()
    supplied.import_tables(
        coa=_coa(drop),
        aux=aux_file,
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    supplied.lock()
    supplied_aux = json.loads(supplied.lock_path.read_text())["aux"]
    assert "derived_from" not in supplied_aux
    supplied_hashes = supplied.hashes()
    assert supplied_hashes["aux_kind"] == "source"
    assert supplied_hashes["aux_derived_from"] is None
    assert supplied_hashes["aux"] == file_hash(aux_file)


def test_a_pre_migration_manifest_still_labels_its_aux_as_derived(tmp_path: Path) -> None:
    """#35 -- windows locked before derived_from existed carry no marker.

    hashes() classifies from the absent source digest, and the workpaper must
    read that classification instead of only the newer explicit key.
    """
    import json

    from foundry.workpaper import render_workpaper

    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.lock()
    manifest = json.loads(window.lock_path.read_text())
    del manifest["aux"]["derived_from"]
    window.lock_path.write_text(json.dumps(manifest))

    hashes = window.hashes()
    assert hashes["aux_derived_from"] is None
    assert hashes["aux_kind"] == "derived"
    paper = render_workpaper({"window_id": window.id, "hashes": hashes, "items": []})
    assert f"aux(derived)={hashes['aux']}" in paper
