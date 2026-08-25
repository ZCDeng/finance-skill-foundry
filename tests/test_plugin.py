from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

from foundry.errors import FoundryError, QueryRefused
from foundry.host_profile import REQUIRED_TOOLS, HostProfile, host_smoke
from foundry.window import WindowStore

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "dsh-plugin" / "cordis.patch.yml"
PACKAGE = ROOT / "dsh-plugin" / "package.json"
FIXTURES = ROOT / "fixtures" / "period-smoke"


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


def _imported(tmp_path: Path):
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    profile = HostProfile.period()
    profile.execute(
        window,
        "import",
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    return store, window, profile, drop


def test_bundle_declares_cordis_patch() -> None:
    data = json.loads(PACKAGE.read_text())
    assert data["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    patch = yaml.safe_load(PATCH.read_text())
    inserted = patch[0]["insert"][0]
    assert inserted["id"] == "finance-skill-foundry"
    assert inserted["name"] == data["name"]


def test_period_profile_omits_host_writers() -> None:
    data = json.loads(PACKAGE.read_text())
    foundry = data["dsh"]["foundry"]
    assert set(foundry["tools"]) == set(REQUIRED_TOOLS)
    period = foundry["profiles"]["period"]
    assert period["sandbox"] == "read-only"
    assert period["cwd_writable"] is False
    assert set(period["omit"]) >= {"bash", "dsh-tool-fs", "str-replace-editor"}
    assert foundry["profiles"]["f3"]["tools"] == ["query-locked"]


def test_startup_fails_when_tool_missing() -> None:
    with pytest.raises(FoundryError, match="missing tools"):
        HostProfile("period", ["lock"])


def test_startup_fails_if_host_writers_mounted() -> None:
    with pytest.raises(FoundryError, match="host writers"):
        HostProfile("period", [*REQUIRED_TOOLS, "bash"])


def test_f3_cannot_execute_reimport(tmp_path: Path) -> None:
    _, window, period, drop = _imported(tmp_path)
    period.execute(window, "lock")
    f3 = HostProfile.f3()
    with pytest.raises(QueryRefused, match="re-import"):
        f3.execute(
            window,
            "re-import",
            coa=drop / "coa.xlsx",
            units=drop / "units.xlsx",
            named=[{"id": "gl", "path": drop / "gl.xlsx"}],
        )
    with pytest.raises(QueryRefused):
        f3.execute(window, "emit-brief")
    assert f3.deny_path(window.catalog_path()) is True


def test_period_state_gates_query_before_lock(tmp_path: Path) -> None:
    _, window, period, _ = _imported(tmp_path)
    with pytest.raises(QueryRefused, match="query-locked"):
        period.execute(window, "query-locked", text="GL", required_table_ids=["gl"])


def test_host_smoke_invokes_probe(tmp_path: Path) -> None:
    assert host_smoke(tmp_path / "var", FIXTURES) == 0
