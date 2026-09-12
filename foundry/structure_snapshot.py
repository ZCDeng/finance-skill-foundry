"""Turn a confirmed structure declaration into a calculable table.

The declaration says which sheet, which header row, what each column is, which
rows are not data, and which columns carry a value only on a group's first
line. This module applies it: it drops the section and subtotal rows, fills the
grouping keys down, folds a 借方/贷方 pair into one amount with its side, and
renames each column to its canonical role — while recording, for every derived
row and column, the cell in the original workbook it came from, so a figure can
still be clicked back to 借方!G24 rather than to a row number in a copy.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from foundry.analysis_data import (
    MAX_COLUMNS,
    MAX_ROWS,
    build_table_payload,
    read_exact_numerics,
)
from foundry.errors import FoundryError
from foundry.structure_proposal import normalize_header
from foundry.workbook_bindings import open_workbook_bytes

# The column name each role takes in the derived table. These are the names the
# finance field map already knows, so a derived table needs no special casing.
CANONICAL_NAMES = {
    "account_code": "account_code",
    "account_name": "account_name",
    "management_account": "management_account",
    "category": "category",
    "direction": "account_direction",
    "amount": "amount",
    "doc_id": "doc_id",
    "line_id": "line_id",
    "date": "date",
    "summary": "summary",
    "period": "period",
    "currency": "currency",
    "unit": "unit",
    "organization": "organization",
    "ledger": "ledger",
}
AMOUNT_COLUMN = "amount"
DC_COLUMN = "dc_flag"
DEBIT = "借"
CREDIT = "贷"
CREDIT_CATEGORIES = ("收入", "权益", "负债")
DEBIT_CATEGORIES = ("成本", "费用", "资产")


def derive_table(data: bytes, declaration: dict[str, Any]) -> dict[str, Any]:
    """Build the payload for a table snapshot from workbook bytes plus a declaration."""
    sheet_name = declaration.get("sheet")
    header_row = declaration.get("header_row")
    if not sheet_name or not isinstance(header_row, int) or header_row < 1:
        raise FoundryError("structure declaration requires a sheet and a header row")
    columns = declaration.get("columns") or []
    if not columns:
        raise FoundryError("structure declaration requires at least one column")

    book = open_workbook_bytes(data, data_only=True)
    try:
        if sheet_name not in book.sheetnames:
            raise FoundryError(f"no worksheet: {sheet_name}")
        sheet = book[sheet_name]
        if (sheet.max_column or 0) > MAX_COLUMNS or (sheet.max_row or 0) > MAX_ROWS + 1:
            raise FoundryError("worksheet exceeds row/column limits")
        grid = _grid(sheet, read_exact_numerics(data, sheet_name))
    finally:
        book.close()

    excluded = {int(item["row"]) for item in declaration.get("excluded_rows") or []}
    fill_down = list(declaration.get("fill_down_columns") or [])
    pair = _primary_pair(declaration)
    headers = _derived_headers(columns, pair)

    rows: list[dict[str, Any]] = []
    source_rows: list[int] = []
    row_columns: dict[str, str] = {}
    fill_provenance: dict[str, list[int]] = {}
    carried: dict[str, Any] = {}

    for number in sorted(grid):
        if number <= header_row:
            continue
        raw = grid[number]
        for letter in fill_down:
            if raw.get(letter) not in (None, ""):
                carried[letter] = raw[letter]
        if number in excluded:
            continue
        row: dict[str, Any] = {name: None for name in headers}
        filled_here: list[str] = []
        for column in columns:
            letter = column["letter"]
            role = column.get("role")
            if role in {"debit", "credit"} or role == "unknown":
                continue
            name = CANONICAL_NAMES.get(role)
            if not name:
                continue
            value = raw.get(letter)
            if value in (None, "") and letter in fill_down and letter in carried:
                value = carried[letter]
                filled_here.append(name)
            row[name] = value
        if pair is not None:
            amount, side, letter = _amount_for(raw, pair, row, declaration)
            if amount is None:
                continue
            row[AMOUNT_COLUMN] = amount
            row[DC_COLUMN] = side
            row_columns[str(number)] = letter
        if all(value in (None, "") for value in row.values()):
            continue
        rows.append(row)
        source_rows.append(number)
        for name in filled_here:
            fill_provenance.setdefault(name, []).append(number)

    transformation = {
        "format": "xlsx",
        "numeric_parser": "xlsx-original-xml-decimal",
        "formulas": "cached-values-required",
        "sheet": sheet_name,
        "header_row": header_row,
        "source_row_numbers": source_rows,
        # Original letters, so a locator still points at the file's own columns.
        "header_columns": {
            column["header"] or column["letter"]: column["letter"] for column in columns
        },
        "structure": {
            "declaration": declaration,
            "derived_from": declaration.get("derived_from"),
            "excluded_rows": sorted(excluded),
            "fill_provenance": fill_provenance,
            "row_columns": row_columns,
            "amount_column_letters": _pair_letters(pair),
        },
    }
    payload = build_table_payload(headers, rows, transformation, {})
    payload["derived_headers"] = headers
    return payload


def _grid(sheet, exact: dict[str, Decimal]) -> dict[int, dict[str, Any]]:
    from foundry.analysis_data import _column_letter

    grid: dict[int, dict[str, Any]] = {}
    for number, cells in enumerate(sheet.iter_rows(), start=1):
        row: dict[str, Any] = {}
        for cell in cells:
            coordinate = getattr(cell, "coordinate", "") or ""
            value = (
                cell.value
                if getattr(cell, "is_date", False)
                else exact.get(coordinate, cell.value)
            )
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            letter = _column_letter(cell)
            if letter:
                row[letter] = value
        if row:
            grid[number] = row
    return grid


def _primary_pair(declaration: dict[str, Any]) -> dict[str, Any] | None:
    pairs = declaration.get("amount_pairs") or []
    if not pairs:
        return None
    primary = next((pair for pair in pairs if pair.get("primary")), pairs[0])
    if (primary.get("direction") or {}).get("kind") == "undecided":
        raise FoundryError("structure declaration has an undecided debit/credit side")
    return primary


def _pair_letters(pair: dict[str, Any] | None) -> list[str]:
    return [pair["debit"], pair["credit"]] if pair else []


def _derived_headers(
    columns: list[dict[str, Any]], pair: dict[str, Any] | None
) -> list[str]:
    headers: list[str] = []
    for column in columns:
        role = column.get("role")
        if role in {"debit", "credit", "unknown"}:
            continue
        name = CANONICAL_NAMES.get(role)
        if not name or name in headers:
            continue
        headers.append(name)
    if pair is not None:
        for name in (AMOUNT_COLUMN, DC_COLUMN):
            if name not in headers:
                headers.append(name)
    if not headers:
        raise FoundryError("structure declaration yields no usable column")
    return headers


def undeclarable_reason(declaration: dict[str, Any]) -> str | None:
    """Why this declaration cannot become a table, or None if it can.

    The proposal engine asks the same question of a sheet before offering it,
    but a declaration can also arrive from a tool call or a hand-edited card,
    and those never passed the engine. This is the one place that answers it,
    so a refusal reads the same on both doors.
    """
    columns = declaration.get("columns") or []
    if not columns:
        return "no column was declared"
    try:
        _derived_headers(columns, _primary_pair(declaration))
    except FoundryError:
        return "no column carries a role the table can keep"
    return None


def _amount_for(
    raw: dict[str, Any],
    pair: dict[str, Any],
    row: dict[str, Any],
    declaration: dict[str, Any],
) -> tuple[Any, str | None, str]:
    """The amount for this row, which side it sits on, and the column it came from."""
    debit_letter, credit_letter = pair["debit"], pair["credit"]
    debit, credit = raw.get(debit_letter), raw.get(credit_letter)
    kind = (pair.get("direction") or {}).get("kind")

    if kind == "by_populated_side":
        if debit not in (None, "") and credit in (None, ""):
            return debit, DEBIT, debit_letter
        if credit not in (None, "") and debit in (None, ""):
            return credit, CREDIT, credit_letter
        return None, None, ""

    side = None
    if kind == "by_category":
        side = _side_from_category(row.get("category"))
    elif kind == "by_direction_column":
        side = _side_from_direction(row.get("account_direction"))
    elif kind == "fixed":
        side = DEBIT if pair["direction"].get("side") == "debit" else CREDIT
    if side is None:
        # No basis for this row; the populated side is the only honest answer.
        if debit not in (None, "") and credit in (None, ""):
            return debit, DEBIT, debit_letter
        if credit not in (None, "") and debit in (None, ""):
            return credit, CREDIT, credit_letter
        return None, None, ""
    if side == DEBIT:
        return (debit, DEBIT, debit_letter) if debit not in (None, "") else (None, None, "")
    return (credit, CREDIT, credit_letter) if credit not in (None, "") else (None, None, "")


def _side_from_category(value: Any) -> str | None:
    text = normalize_header(value)
    if not text:
        return None
    if any(marker in text for marker in CREDIT_CATEGORIES):
        return CREDIT
    if any(marker in text for marker in DEBIT_CATEGORIES):
        return DEBIT
    return None


def _side_from_direction(value: Any) -> str | None:
    text = normalize_header(value)
    if text.startswith(("借", "debit", "Debit", "DEBIT")):
        return DEBIT
    if text.startswith(("贷", "credit", "Credit", "CREDIT")):
        return CREDIT
    return None
