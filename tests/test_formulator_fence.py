from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

import importlib.util

from foundry.errors import LockRefused
from foundry.launch_formulator import launch_spec, purge_formulator_home, stop_lease
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
    loader = LockedCatalogLoader()
    tables = {item["name"]: item["rows"] for item in loader.list_tables()}
    assert tables["gl"] == 1
    assert "notes" not in tables
    hashes = window.hashes()
    loader.fetch_table("gl")
    assert window.hashes() == hashes


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
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused):
        loader.list_tables()


def test_refresh_connector_and_starter_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _ = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused):
        loader.refresh()
    with pytest.raises(LockRefused):
        loader.load_connector("mysql")
    with pytest.raises(LockRefused):
        loader.starter_questions()


def test_over_cap_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _ = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_MAX_IMPORT_ROWS", "0")
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused, match="MAX_IMPORT_ROWS"):
        loader.list_tables()


def test_launch_uses_plugin_dir_and_per_window_home(tmp_path: Path) -> None:
    _, window = _locked(tmp_path)
    spec = launch_spec(window)
    assert "--disable-database" not in spec["argv"]
    assert "--disable-data-connectors" not in spec["argv"]
    assert Path(spec["env"]["DATA_FORMULATOR_HOME"]) == window.store.formulator_dir / window.id
    assert spec["env"]["DF_PLUGIN_DIR"].endswith("formulator-plugin")
    connectors = yaml.safe_load((Path(spec["home"]) / "connectors.yaml").read_text())
    assert connectors["connectors"][0]["type"] == "locked_catalog"
    assert connectors["connectors"][0]["auto_connect"] is True
    before = window.hashes()
    stop_lease(window)
    purge_formulator_home(window)
    assert window.hashes() == before
    assert not (window.store.formulator_dir / window.id).exists()
