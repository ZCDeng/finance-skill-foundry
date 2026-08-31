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


# --- what a whole-table total is allowed to mean ---------------------------
#
# The rule these pin came out of a real close: a `city_pl` carrying nine
# measures for 50 city companies answered three different questions with the
# same number, and that number had square metres and project counts added into
# yuan. See `undefined_total`.


def test_one_measure_has_a_total() -> None:
    from foundry.caliber import undefined_total

    headers = ["account_code", "unit_id", "amount"]
    rows = [("1122", "C01", 10), ("1122", "C02", 20)]
    assert undefined_total("ar", headers, rows) is None


def test_several_measures_have_no_total() -> None:
    from foundry.caliber import undefined_total

    headers = ["account_code", "unit_id", "amount"]
    rows = [("6001", "C01", 10), ("1122", "C01", 20), ("9001", "C01", 30)]
    problem = undefined_total("city_pl", headers, rows)
    assert problem is not None
    # Names the table, how many measures, and the two ways out.
    assert "city_pl" in problem
    assert "3 account codes" in problem
    assert "6001" in problem and "1122" in problem
    assert "one account per table" in problem
    assert "map" in problem


def test_the_account_cut_puts_each_measure_in_its_own_part() -> None:
    from foundry.caliber import undefined_total

    headers = ["account_code", "amount"]
    rows = [("6001", 10), ("1122", 20)]
    assert undefined_total("t", headers, rows, split_by="account_code") is None


def test_any_other_cut_still_mixes_them_inside_each_part() -> None:
    from foundry.caliber import undefined_total

    headers = ["account_code", "region", "amount"]
    rows = [("6001", "east", 10), ("1122", "east", 20)]
    problem = undefined_total("t", headers, rows, split_by="region")
    assert problem is not None
    assert "split by region" in problem


def test_a_count_is_a_count_whatever_the_accounts_are() -> None:
    from foundry.caliber import undefined_total

    # No `amount`, so the aggregate is COUNT(*), and rows are rows.
    headers = ["account_code", "note"]
    rows = [("6001", "a"), ("1122", "b")]
    assert undefined_total("t", headers, rows) is None


def test_a_table_with_no_account_column_carries_one_measure() -> None:
    from foundry.caliber import undefined_total

    assert undefined_total("t", ["amount"], [(10,), (20,)]) is None


def test_a_blank_account_beside_a_real_one_is_two_things() -> None:
    from foundry.caliber import undefined_total

    # Half the rows attributed and half not is not one measure either, and the
    # blank is named rather than dropped so the message says what was found.
    problem = undefined_total("t", ["account_code", "amount"], [("6001", 10), ("", 20)])
    assert problem is not None
    assert "(blank)" in problem


def test_the_message_does_not_list_every_account_in_a_wide_table() -> None:
    from foundry.caliber import undefined_total

    rows = [(f"{6000 + i}", 1) for i in range(9)]
    problem = undefined_total("t", ["account_code", "amount"], rows)
    assert problem is not None
    assert "9 account codes" in problem
    assert "+3 more" in problem


def test_accounts_are_reported_in_the_order_the_table_holds_them() -> None:
    from foundry.caliber import accounts_in

    headers = ["account_code", "amount"]
    rows = [("6001", 1), ("1122", 2), ("6001", 3)]
    assert accounts_in(headers, rows) == ["6001", "1122"]
