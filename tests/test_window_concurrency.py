from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.errors import WindowBusy
from foundry.locking import exclusive
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
    return _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])


def _gl(drop: Path, *, amount: int = 100) -> Path:
    return _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", amount]])


@pytest.fixture(autouse=True)
def _short_lock_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("foundry.window.LIFECYCLE_LOCK_TIMEOUT", 0.2)


def test_import_refuses_while_another_holder_has_the_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    with exclusive(window.lifecycle_lock_path, timeout=0.2):
        with pytest.raises(WindowBusy):
            window.import_tables(
                coa=_coa(drop),
                named=[{"id": "gl", "path": _gl(drop)}],
                drop_dir=drop,
            )
    assert window.state == "Open"
    assert not window.catalog_path().exists()
    assert not window.lock_path.exists()


def test_lock_refuses_while_another_holder_has_the_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    with exclusive(window.lifecycle_lock_path, timeout=0.2):
        with pytest.raises(WindowBusy):
            window.lock()
    assert window.state == "Imported"
    assert json.loads(window.lock_path.read_text())["locked"] is False


def test_reimport_refuses_while_another_holder_has_the_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.lock()
    with exclusive(window.lifecycle_lock_path, timeout=0.2):
        with pytest.raises(WindowBusy):
            window.reimport(
                coa=_coa(drop),
                named=[{"id": "gl", "path": _gl(drop, amount=3)}],
                drop_dir=drop,
            )
    assert store.current().id == window.id
    assert [path.name for path in store.windows_dir.iterdir()] == [window.id]
    assert window.query("SELECT amount FROM gl")[0][0] == 100


def test_import_holds_the_window_lock_across_the_whole_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import foundry.window as window_module

    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    real_load_tabular = window_module.load_tabular
    contended: list[bool] = []

    def probe_the_lock(path: Path):  # type: ignore[no-untyped-def]
        try:
            with exclusive(window.lifecycle_lock_path, timeout=0.05):
                contended.append(False)
        except WindowBusy:
            contended.append(True)
        return real_load_tabular(path)

    monkeypatch.setattr(window_module, "load_tabular", probe_the_lock)
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    assert contended and all(contended), "window lock was not held for the whole import"


def test_close_releases_both_connections_and_the_window_stays_usable(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.lock()
    assert window.query("SELECT amount FROM gl")[0][0] == 100
    assert window._ro_con is not None

    window.close()
    assert window._ro_con is None
    assert window._write_con is None
    assert window.query("SELECT amount FROM gl")[0][0] == 100
    window.close()


def test_window_context_manager_closes_the_read_connection(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.lock()
    window.close()

    with store.get(window.id) as reader:
        assert reader.query("SELECT amount FROM gl")[0][0] == 100
        assert reader._ro_con is not None
    assert reader._ro_con is None


def test_close_releases_the_write_connection_before_lock(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    window.write_sql("UPDATE gl SET amount = 7")
    assert window._write_con is not None

    window.close()
    assert window._write_con is None
