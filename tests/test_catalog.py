from __future__ import annotations

import json
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
    return _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["001001", "Cash"]])


def test_amounts_use_decimal_without_losing_big_ints(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    amount = "9007199254740993"
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text(f"account_code,amount\n001001,{amount}\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    window.lock()
    code, loaded, total = window.query("SELECT account_code, amount, SUM(amount) OVER () FROM gl")[0]
    assert code == "001001"
    assert loaded == Decimal(amount)
    assert total == Decimal(amount)


def test_dirty_amount_refuses_import(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text("account_code,amount\n001001,not-a-number\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="non-numeric amount"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])


def test_ragged_csv_refuses_import(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text("account_code,amount\n001001\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="ragged row"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])


@pytest.mark.parametrize(
    "payload",
    [
        {"headers": None, "rows": []},
        {"headers": ["account_code"], "rows": None},
        {"headers": ["account_code"], "rows": [1]},
        [{}],
    ],
)
def test_malformed_json_table_is_controlled(tmp_path: Path, payload: object) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.json"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text(json.dumps(payload), encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()

    with pytest.raises(LockRefused, match="JSON table"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_amount_refuses_import(tmp_path: Path, amount: str) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text(f"account_code,amount\n001001,{amount}\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()

    with pytest.raises(LockRefused, match="non-numeric amount"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])


def test_json_dict_rows_keep_original_keys_after_normalization(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.json"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text(json.dumps([{"Account Code": "001001", "Amount": "12.34"}]), encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    window.lock()
    assert window.query("SELECT account_code, amount FROM gl")[0] == ("001001", Decimal("12.34"))


def test_identifier_collisions_refuse_import(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = _xlsx(drop / "gl.xlsx", ["account-code", "account_code"], [["001001", "001001"]])
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="identifier collision"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])

    other = _xlsx(drop / "gl_2.xlsx", ["account_code", "amount"], [["001001", 1]])
    with pytest.raises(LockRefused, match="table identifier collision"):
        window.import_tables(
            coa=_coa(drop),
            named=[{"id": "a-b", "path": other}, {"id": "a_b", "path": other}],
        )


def test_failed_reimport_keeps_previous_current_window(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    first = store.create()
    first.import_tables(
        coa=_coa(drop),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["001001", 1]])}],
    )
    first.lock()
    with pytest.raises(LockRefused):
        first.reimport(coa=_coa(drop), named=[{"id": "gl", "path": drop / "missing.xlsx"}])
    assert store.current().id == first.id
