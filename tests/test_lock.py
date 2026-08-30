from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from foundry.errors import LockRefused, WindowBusy
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


def _coa(dir_path: Path) -> Path:
    return _xlsx(
        dir_path / "coa.xlsx",
        ["account_code", "account_name"],
        [["1001", "Cash"], ["2001", "AP"]],
    )


def _units(dir_path: Path) -> Path:
    return _xlsx(
        dir_path / "units.xlsx",
        ["unit_id", "unit_name"],
        [["OU1", "North"], ["OU2", "South"]],
    )


def _gl(dir_path: Path, *, amount: int = 100) -> Path:
    return _xlsx(
        dir_path / "gl.xlsx",
        ["account_code", "amount"],
        [["1001", amount]],
    )


def _ar(dir_path: Path) -> Path:
    return _xlsx(
        dir_path / "ar.xlsx",
        ["account_code", "amount"],
        [["1001", 40]],
    )


def test_lock_ignores_source_edit_without_reimport(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    coa = _coa(drop)
    units = _units(drop)
    gl = _gl(drop, amount=100)
    ar = _ar(drop)
    window.import_tables(
        coa=coa,
        units=units,
        named=[{"id": "gl", "path": gl}, {"id": "ar", "path": ar}],
        drop_dir=drop,
    )
    window.lock()
    before = window.hashes()
    rows_before = window.query("SELECT amount FROM gl")
    _gl(drop, amount=999)
    after = window.hashes()
    rows_after = window.query("SELECT amount FROM gl")
    assert before["coa"] == after["coa"]
    assert before["named"]["gl"] == after["named"]["gl"]
    assert rows_before == rows_after
    assert rows_after[0][0] == 100
    with pytest.raises(LockRefused):
        window.lock()


def test_empty_named_list_refuses_lock(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused):
        window.import_tables(coa=_coa(drop), units=_units(drop), named=[], drop_dir=drop)
        window.lock()


def test_zero_row_named_table_refuses_lock(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    empty = _xlsx(drop / "empty.xlsx", ["account_code", "amount"], [])
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused):
        window.import_tables(
            coa=_coa(drop),
            units=_units(drop),
            named=[{"id": "gl", "path": empty}],
            drop_dir=drop,
        )
        window.lock()


def test_extra_file_listed_and_absent_from_catalog(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    extra = _xlsx(drop / "notes.xlsx", ["note"], [["ignore"]])
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}, {"id": "ar", "path": _ar(drop)}],
        drop_dir=drop,
    )
    window.lock()
    extras = window.extras()
    assert any(Path(item).name == extra.name for item in extras)
    names = window.table_names()
    assert "notes" not in names
    assert "gl" in names


def test_loaded_hash_mismatch_refuses_lock(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.write_sql("UPDATE gl SET amount = 0")
    with pytest.raises(LockRefused, match="hash"):
        window.lock()


def test_source_hash_mismatch_refuses_lock_for_master_tables(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    units = _units(drop)
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=units,
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    _xlsx(units, ["unit_id", "unit_name"], [["OU9", "Changed"]])
    with pytest.raises(LockRefused, match="source hash"):
        window.lock()


def test_master_loaded_hash_mismatch_refuses_lock(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.write_sql("UPDATE coa SET account_name = 'Changed'")
    with pytest.raises(LockRefused, match="coa"):
        window.lock()


def test_lock_refuses_incomplete_manifest_metadata(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    manifest = json.loads(window.lock_path.read_text())
    del manifest["named"]["gl"]["loaded_hash"]
    window.lock_path.write_text(json.dumps(manifest))

    with pytest.raises(LockRefused, match="manifest metadata"):
        window.lock()


def test_lock_refuses_tables_not_declared_in_manifest(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.write_sql("CREATE TABLE injected(secret VARCHAR)")

    with pytest.raises(LockRefused, match="catalog tables do not match manifest"):
        window.lock()


def test_reimport_failure_keeps_current_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.lock()
    with pytest.raises(LockRefused):
        window.reimport(
            coa=_coa(drop),
            units=_units(drop),
            named=[{"id": "gl", "path": drop / "missing.xlsx"}],
            drop_dir=drop,
        )
    assert store.current().id == window.id


def test_window_id_path_traversal_is_refused(tmp_path: Path) -> None:
    store = WindowStore(tmp_path / "var")
    with pytest.raises(LockRefused):
        store.get("../current")


def test_table_identifier_collision_refuses_import(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="collision"):
        window.import_tables(
            coa=_coa(drop),
            units=_units(drop),
            named=[
                {"id": "a-b", "path": _gl(drop)},
                {"id": "a_b", "path": _ar(drop)},
            ],
            drop_dir=drop,
        )


def test_csv_amount_is_decimal_but_account_code_remains_text(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text("account_code,amount\n1001,2.50\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), units=_units(drop), named=[{"id": "gl", "path": gl}], drop_dir=drop)
    window.lock()
    assert window.query("SELECT account_code, SUM(amount) FROM gl GROUP BY account_code") == [("1001", 2.5)]
    con = duckdb.connect(str(window.catalog_path()), read_only=True)
    try:
        described = {row[0]: row[1] for row in con.execute('DESCRIBE "gl"').fetchall()}
    finally:
        con.close()
    assert described["account_code"] == "VARCHAR"
    assert described["amount"].startswith("DECIMAL")


def test_identifier_collision_refused(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    bad = _xlsx(drop / "bad.xlsx", ["a-b", "a_b"], [[1, 2]])
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="identifier collision"):
        window.import_tables(coa=_coa(drop), units=_units(drop), named=[{"id": "gl", "path": bad}], drop_dir=drop)


def test_reopen_write_after_lock_fails(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.lock()
    with pytest.raises(LockRefused):
        window.write_sql("CREATE TABLE injected(x INTEGER)")


def test_killed_import_leaves_no_lockable_catalog(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    missing = drop / "missing.xlsx"
    with pytest.raises(LockRefused):
        window.import_tables(
            coa=_coa(drop),
            units=_units(drop),
            named=[
                {"id": "gl", "path": _gl(drop)},
                {"id": "ar", "path": missing},
            ],
            drop_dir=drop,
        )
    assert window.state == "Open"
    assert not window.catalog_path().exists()
    with pytest.raises(LockRefused):
        window.lock()


def test_reader_blocks_new_writer(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    window.lock()
    handle = window.register_handle("reader")
    try:
        with pytest.raises(WindowBusy):
            window.reimport(
                coa=_coa(drop),
                units=_units(drop),
                named=[{"id": "gl", "path": _gl(drop, amount=3)}],
                drop_dir=drop,
            )
    finally:
        handle.release()
    next_window = window.reimport(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop, amount=3)}],
        drop_dir=drop,
    )
    next_window.lock()
    assert next_window.id != window.id
    assert store.current().id == next_window.id
    assert window.query("SELECT amount FROM gl")[0][0] == 100
    assert next_window.query("SELECT amount FROM gl")[0][0] == 3


def test_import_after_brief_is_refused_and_leaves_the_window_untouched(tmp_path: Path) -> None:
    from foundry.brief import emit_brief
    from foundry.questions import record_questions

    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop, amount=100)}],
        drop_dir=drop,
    )
    window.lock()
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    brief_before = emit_brief(window)
    manifest_before = json.loads(window.lock_path.read_text())
    facts_before = (window.root / "brief_facts.json").read_text()

    with pytest.raises(LockRefused, match="import only before lock"):
        window.import_tables(
            coa=_coa(drop),
            units=_units(drop),
            named=[{"id": "gl", "path": _gl(drop, amount=999)}],
            drop_dir=drop,
        )

    assert window.state == "Briefed"
    assert json.loads(window.lock_path.read_text()) == manifest_before
    assert json.loads(window.lock_path.read_text())["locked"] is True
    assert window.brief_path.read_text() == brief_before
    assert (window.root / "brief_facts.json").read_text() == facts_before
    assert window.query("SELECT amount FROM gl")[0][0] == 100


def test_hyphenated_named_id_locks_because_manifest_matches_duckdb(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    period = _xlsx(drop / "ar-2024-08.xlsx", ["account_code", "amount"], [["1001", 40]])
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "ar-2024-08", "path": period}],
        drop_dir=drop,
    )
    manifest = json.loads(window.lock_path.read_text())
    assert list(manifest["named"]) == ["ar_2024_08"]

    window.lock()
    assert "ar_2024_08" in window.table_names()
    assert window.query("SELECT amount FROM ar_2024_08")[0][0] == 40


def test_source_replaced_mid_parse_refuses_the_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import foundry.window as window_module

    drop = tmp_path / "drop"
    gl = _gl(drop, amount=100)
    real_load_tabular = window_module.load_tabular

    def swap_after_parse(path: Path):  # type: ignore[no-untyped-def]
        headers, rows = real_load_tabular(path)
        if Path(path) == gl:
            _xlsx(gl, ["account_code", "amount"], [["1001", 999]])
        return headers, rows

    monkeypatch.setattr(window_module, "load_tabular", swap_after_parse)
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="source changed during import"):
        window.import_tables(
            coa=_coa(drop),
            units=_units(drop),
            named=[{"id": "gl", "path": gl}],
            drop_dir=drop,
        )
    assert window.state == "Open"
    assert not window.catalog_path().exists()
