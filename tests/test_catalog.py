from __future__ import annotations

import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula

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


def _xlsx_with_cached_formula(path: Path) -> Path:
    """A workbook whose formula carries the computed value Excel would cache."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["account_code", "amount"])
    ws.append(["001001", 100])
    ws["A3"] = "001001"
    ws["B3"] = "=50*2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    sheet = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(path) as archive:
        payload = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    # openpyxl writes the empty cached value as `<v></v>` under lxml and `<v />`
    # without it, and which one you get depends on whether something else in the
    # environment happened to pull lxml in. This test passed for years in a
    # checkout where the optional `formulator` extra had, and failed the first
    # time it ran against a clean `pip install -e .[dev]`.
    empty = next(
        (form for form in (b"<f>50*2</f><v></v>", b"<f>50*2</f><v />") if form in payload[sheet]),
        None,
    )
    assert empty is not None, f"no empty cached value to replace in {payload[sheet][:400]!r}"
    cached = payload[sheet].replace(empty, b"<f>50*2</f><v>200</v>")
    assert cached != payload[sheet]
    payload[sheet] = cached
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    return path


def test_uncached_xlsx_formula_refuses_import(tmp_path: Path) -> None:
    """A formula no spreadsheet ever evaluated must not import as a blank amount."""
    drop = tmp_path / "drop"
    gl = drop / "gl.xlsx"
    _xlsx(gl, ["account_code", "amount"], [["001001", 100], ["001001", "=50*2"]])
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="uncached xlsx formula") as caught:
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    assert "B3" in str(caught.value)


def test_uncached_xlsx_array_formula_refuses_import(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["account_code", "amount"])
    ws.append(["001001", 100])
    ws["A3"] = "001001"
    ws["B3"] = ArrayFormula("B3", "=SUM(B2:B2)")
    gl.parent.mkdir(parents=True, exist_ok=True)
    wb.save(gl)
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="uncached xlsx formula"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])


def test_cached_xlsx_formula_imports_its_computed_value(tmp_path: Path) -> None:
    """The refusal must not fire on the everyday case: Excel cached the result."""
    drop = tmp_path / "drop"
    gl = _xlsx_with_cached_formula(drop / "gl.xlsx")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    window.lock()
    assert window.query("SELECT SUM(amount) FROM gl")[0][0] == Decimal("300")


def test_blank_csv_lines_are_not_ragged_rows(tmp_path: Path) -> None:
    drop = tmp_path / "drop"
    gl = drop / "gl.csv"
    gl.parent.mkdir(parents=True, exist_ok=True)
    gl.write_text("account_code,amount\n001001,100\n\n001002,50\n\n", encoding="utf-8")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    window.lock()
    assert window.query("SELECT COUNT(*), SUM(amount) FROM gl")[0] == (2, Decimal("150"))


def test_cleared_xlsx_row_does_not_reach_the_lock(tmp_path: Path) -> None:
    """A row cleared in Excel but not deleted must not become a phantom source row."""
    drop = tmp_path / "drop"
    gl = drop / "gl.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["account_code", "amount"])
    ws.append(["001001", 100])
    ws.append(["001002", 50])
    ws["A3"] = None
    ws["B3"] = None
    gl.parent.mkdir(parents=True, exist_ok=True)
    wb.save(gl)
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    window.lock()
    assert window.query("SELECT COUNT(*) FROM gl")[0][0] == 1
    assert window.query("SELECT account_code, amount FROM gl")[0] == ("001001", Decimal("100"))


def _xlsx_with_blank_result_formula(path: Path) -> Path:
    """A workbook whose formula Excel evaluated to an empty string.

    Excel writes ``t="str"`` with an empty ``<v>`` for ``=IF(...,"",...)``.
    openpyxl's data_only load reports ``None`` for that cell, exactly as it
    does for a formula nothing ever evaluated, so only the sheet XML separates
    "blank on purpose" from "never computed".
    """
    _xlsx(path, ["account_code", "note", "amount"], [["001001", "x", 100]])
    sheet = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(path) as archive:
        payload = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    body = (
        b'<row r="2"><c r="A2" t="inlineStr"><is><t>001001</t></is></c>'
        b'<c r="B2" t="str"><f>IF(A2=1001,"","x")</f><v></v></c>'
        b'<c r="C2" t="n"><v>100</v></c></row>'
    )
    start = payload[sheet].index(b'<row r="2">')
    end = payload[sheet].index(b"</row>", start) + len(b"</row>")
    payload[sheet] = payload[sheet][:start] + body + payload[sheet][end:]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    return path


def test_formula_cached_as_blank_still_imports(tmp_path: Path) -> None:
    """=IF(cond,"",...) is an everyday shape; re-saving in Excel cannot fix it."""
    drop = tmp_path / "drop"
    gl = _xlsx_with_blank_result_formula(drop / "gl.xlsx")
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": gl}])
    window.lock()
    assert window.query("SELECT account_code, note, amount FROM gl") == [("001001", "", Decimal("100"))]
