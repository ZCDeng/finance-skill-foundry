from __future__ import annotations

from pathlib import Path

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
