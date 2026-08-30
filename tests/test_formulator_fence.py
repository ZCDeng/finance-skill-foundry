from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

import importlib.util

from foundry.errors import LockRefused
from foundry.launch_formulator import (
    launch_formulator,
    launch_spec,
    purge_formulator_home,
    stop_formulator,
    stop_lease,
    write_connectors,
)
from foundry.window import WindowStore

_LOADER = Path(__file__).resolve().parents[1] / "formulator-plugin" / "locked_catalog_data_loader.py"
_SPEC = importlib.util.spec_from_file_location("locked_catalog_data_loader", _LOADER)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
LockedCatalogLoader = _MOD.LockedCatalogLoader


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
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    window.lock()
    return store, window


def test_loader_lists_only_locked_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    tables = {item["name"]: item["metadata"]["row_count"] for item in loader.list_tables()}
    assert tables["gl"] == 1
    assert loader.list_tables()[0]["metadata"]["columns"][0]["name"]
    assert "notes" not in tables
    hashes = window.hashes()
    loader.fetch_table("gl")
    assert window.hashes() == hashes


def test_loader_requires_fixed_window_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _ = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.delenv("FOUNDRY_WINDOW_ID", raising=False)
    with pytest.raises(LockRefused, match="FOUNDRY_WINDOW_ID"):
        LockedCatalogLoader()


def test_loader_stays_bound_to_launch_window_after_current_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    drop = tmp_path / "drop2"
    next_window = window.reimport(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 9]])}],
        drop_dir=drop,
    )
    next_window.lock()
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    table_names = {item["name"] for item in loader.list_tables()}
    assert "gl" in table_names
    assert "ar" not in table_names


def test_loader_projection_size_and_required_columns_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    assert loader.fetch_table("gl", columns=["amount"], limit=1) == [(100.0,)]
    pytest.importorskip("pyarrow")
    arrow = loader.fetch_data_as_arrow("gl", {"columns": ["amount"], "required_columns": ["amount"], "size": 1})
    assert arrow.column_names == ["amount"]
    assert arrow.num_rows == 1
    with pytest.raises(LockRefused, match="required columns"):
        loader.fetch_data_as_arrow("gl", {"required_columns": ["missing"]})
    with pytest.raises(LockRefused, match="unsupported import options"):
        loader.fetch_data_as_arrow("gl", {"filter": {"amount": 100}})


def test_loader_refuses_before_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused):
        loader.list_tables()


def test_refresh_connector_and_starter_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused):
        loader.refresh()
    with pytest.raises(LockRefused):
        loader.load_connector("mysql")
    with pytest.raises(LockRefused):
        loader.starter_questions()


def test_over_cap_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    monkeypatch.setenv("FOUNDRY_MAX_IMPORT_ROWS", "0")
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused, match="MAX_IMPORT_ROWS"):
        loader.list_tables()


def test_launch_uses_plugin_dir_and_per_window_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    bin_dir = Path(__file__).resolve().parents[1] / ".venv" / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    spec = launch_spec(window)
    assert "--disable-database" not in spec["argv"]
    assert "--disable-data-connectors" not in spec["argv"]
    assert Path(spec["env"]["DATA_FORMULATOR_HOME"]) == window.store.formulator_dir / window.id
    assert spec["env"]["DF_PLUGIN_DIR"].endswith("formulator-plugin")
    assert spec["env"]["FOUNDRY_WINDOW_ID"] == window.id
    home = Path(spec["home"])
    assert not home.exists()
    connectors = yaml.safe_load(write_connectors(home).read_text())
    assert connectors["connectors"][0]["type"] == "locked_catalog"
    assert connectors["connectors"][0]["auto_connect"] is True
    before = window.hashes()
    stop_lease(window)
    purge_formulator_home(window)
    assert window.hashes() == before
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_missing_binary_fails_without_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    with pytest.raises(LockRefused, match="Data Formulator binary"):
        launch_formulator(window)
    assert not window.handles_path.exists()
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_dry_run_does_not_register_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    bin_dir = Path(__file__).resolve().parents[1] / ".venv" / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FOUNDRY_SKIP_FORMULATOR_EXEC", "1")
    launch_formulator(window)
    assert not window.handles_path.exists()


def test_stop_refuses_to_kill_unrelated_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text(str(os.getpid()))
    window.register_handle("formulator")
    with pytest.raises(LockRefused, match="does not belong"):
        stop_formulator(window)
    assert not home.exists()


def test_stop_cleans_corrupt_pid_and_handle(tmp_path: Path) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text("not-a-pid\n")
    window.register_handle("formulator")

    with pytest.raises(LockRefused, match="pid is invalid"):
        stop_formulator(window)

    assert not home.exists()
    assert "formulator" not in window.handles_path.read_text()


def test_purge_refuses_active_formulator_lease(tmp_path: Path) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text("123\n")
    window.register_handle("formulator")

    with pytest.raises(LockRefused, match="stop-formulator"):
        purge_formulator_home(window)

    assert home.exists()
