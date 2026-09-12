"""Propose a table structure for each worksheet of an uploaded workbook.

A real month-end export is not a table: a title area sits above the header, the
header itself is not row 1, section and subtotal rows are mixed into the data,
amounts arrive as a 借方/贷方 pair, and grouping keys appear only on the first
line of each group. This module reads workbook bytes and proposes, per sheet,
what the table underneath actually is. It decides nothing: the proposal is
reviewed and confirmed by the finance manager (or, on the manager's word, by
the assistant) before anything calculable exists.

Pure by contract: bytes in, proposals out. It reads no task directory and
writes no record.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from foundry.analysis_data import MAX_COLUMNS, MAX_ROWS, _column_letter
from foundry.errors import FoundryError
from foundry.workbook_bindings import open_workbook_bytes

SCHEMA_VERSION = 1

# How far down a sheet the header may sit. Real packs put a title, a scope line
# and a spacer above it; this leaves room for a wordier cover block.
MAX_HEADER_SCAN_ROWS = 20
# A header needs this many labelled columns before it reads as a table header.
MIN_HEADER_COLUMNS = 2

ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "account_code": ("科目代码", "科目编码", "会计科目代码", "account_code"),
    "account_name": ("科目名称", "会计科目", "account_name"),
    "management_account": ("管理科目", "management_account"),
    "category": ("类别", "科目类别", "category"),
    "direction": ("方向", "余额方向", "借贷", "借贷方向", "dc_flag"),
    "amount": ("金额", "发生额", "本期金额", "amount"),
    "doc_id": ("凭证号", "凭证字号", "单据编号", "单据ID", "doc_id"),
    "line_id": ("行号", "分录行号", "line_id"),
    "date": ("日期", "记账日期", "业务日期", "date"),
    "summary": ("摘要", "业务摘要", "summary"),
    "period": ("期间", "会计期间", "所属期间", "period"),
    "currency": ("币种", "原币", "currency"),
    "unit": ("单位", "金额单位", "unit"),
    "organization": ("组织", "机构", "公司", "organization"),
    "ledger": ("账套", "ledger"),
}
# A ledger carries 借方/贷方 once per balance column group, so these roles repeat
# by design; every other role names one column.
REPEATABLE_ROLES = frozenset({"debit", "credit"})
DEBIT_MARKERS = ("借方", "借方金额", "debit")
CREDIT_MARKERS = ("贷方", "贷方金额", "credit")

# A pair whose label mentions the period's own movement is the one a P&L reads.
PRIMARY_PAIR_HINTS = ("本期发生额", "发生额", "本期", "当期")

SECTION_SUFFIXES = ("类科目", "类", "科目")
FOOTER_KEYWORDS = ("合计", "小计", "总计", "累计", "平衡校验", "校验", "说明", "备注", "注：")
SUBTOTAL_KEYWORDS = ("合计", "小计", "总计", "平衡校验")
NOTE_KEYWORDS = ("校验说明", "说明", "备注", "注：")

PERIOD_IN_TITLE = re.compile(r"(20\d{2})\s*[-./年]\s*(\d{1,2})")
# 「2026年1-8月」 is a span, not a period; declaring one month of it would invent scope.
PERIOD_SPAN_IN_TITLE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*[-–—~至]\s*\d{1,2}\s*月")
CURRENCY_IN_TITLE = re.compile(r"(?:币种|原币)[:：\s]*([A-Za-z]{3}|人民币)")
UNIT_IN_TITLE = re.compile(r"(?:金额)?单位[:：\s]*([万亿]?元)")

# Grouping keys that only carry a value on a group's first line.
FILL_DOWN_ROLES = ("doc_id", "date", "summary")

# Sheets that name themselves as presentation rather than data. A cover, a KPI
# board and a benchmark page are table-shaped but are not the books; the sheet's
# own heading is how a manager tells them apart, so it is what we read.
PRESENTATION_MARKERS = ("封面", "编制说明", "看板", "仪表盘", "对标", "假设", "目录", "填报说明")


def propose_workbook_structure(data: bytes) -> dict[str, Any]:
    """Return one structure proposal per worksheet of ``data``."""
    book = open_workbook_bytes(data, data_only=True)
    try:
        sheets = [_propose_sheet(book[name], name) for name in book.sheetnames]
    finally:
        book.close()
    return {"schema_version": SCHEMA_VERSION, "sheets": sheets}


def _propose_sheet(sheet, name: str) -> dict[str, Any]:
    if (sheet.max_column or 0) > MAX_COLUMNS or (sheet.max_row or 0) > MAX_ROWS + 1:
        # One oversized sheet must not cost the manager the rest of the workbook.
        return _excluded(name, "too_large")
    grid = _read_grid(sheet)
    if not grid:
        return _excluded(name, "empty_sheet")
    if _is_presentation_sheet(name, grid):
        return _excluded(name, "presentation_sheet")
    header_row = _find_header_row(grid)
    if header_row is None:
        return _excluded(name, "no_header")
    columns = _columns(grid, header_row)
    if len(columns) < MIN_HEADER_COLUMNS:
        return _excluded(name, "no_header")
    pairs = _amount_pairs(columns)
    title_rows = [number for number in sorted(grid) if number < header_row]
    excluded = _excluded_rows(grid, header_row, columns)
    _apply_direction(grid, header_row, columns, pairs, excluded)
    return {
        "sheet": name,
        "decision": "table",
        "reason": None,
        "header_row": header_row,
        "title_rows": title_rows,
        "columns": columns,
        "amount_pairs": pairs,
        "excluded_rows": excluded,
        "fill_down_columns": _fill_down_columns(grid, header_row, columns, excluded),
        "scope_hints": _scope_hints(grid, title_rows),
        "preview": _preview(grid, header_row),
        "confidence": _confidence(columns, pairs, header_row),
    }


def _excluded(name: str, reason: str) -> dict[str, Any]:
    return {
        "sheet": name,
        "decision": "excluded",
        "reason": reason,
        "header_row": None,
        "title_rows": [],
        "columns": [],
        "amount_pairs": [],
        "excluded_rows": [],
        "fill_down_columns": [],
        "scope_hints": {"period": "", "currency": "", "unit": ""},
        "preview": [],
        "confidence": 0.0,
    }


def _is_presentation_sheet(name: str, grid: dict[int, dict[str, Any]]) -> bool:
    heading = ""
    if grid:
        heading = _leading_text(grid[min(grid)])
    for text in (name, heading):
        if any(marker in normalize_header(text) for marker in PRESENTATION_MARKERS):
            return True
    return False


def _read_grid(sheet) -> dict[int, dict[str, Any]]:
    """Row number -> {column letter: value}, empty cells and rows dropped."""
    grid: dict[int, dict[str, Any]] = {}
    for number, cells in enumerate(sheet.iter_rows(), start=1):
        row: dict[str, Any] = {}
        for cell in cells:
            value = cell.value
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            letter = _column_letter(cell)
            if letter:
                row[letter] = value
        if row:
            grid[number] = row
    return grid


def normalize_header(text: Any) -> str:
    """Header text with line breaks and full-width spaces removed for matching."""
    return re.sub(r"[\s　]+", "", str(text or ""))


def _find_header_row(grid: dict[int, dict[str, Any]]) -> int | None:
    """The labelled row that data follows — not merely the first non-empty one."""
    best: tuple[int, int] | None = None
    for number in sorted(grid):
        if number > MAX_HEADER_SCAN_ROWS:
            break
        labels = [
            letter
            for letter, value in grid[number].items()
            if isinstance(value, str) and normalize_header(value)
        ]
        if len(labels) < MIN_HEADER_COLUMNS:
            continue
        following = [n for n in grid if n > number]
        if not following:
            continue
        # Data under a real header reuses the header's own columns.
        overlap = max(
            (len(set(labels) & set(grid[n])) for n in sorted(following)[:5]),
            default=0,
        )
        if overlap < MIN_HEADER_COLUMNS:
            continue
        score = len(labels)
        if best is None or score > best[1]:
            best = (number, score)
    return best[0] if best else None


def _columns(grid: dict[int, dict[str, Any]], header_row: int) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for letter, value in sorted(grid[header_row].items(), key=lambda item: _letter_index(item[0])):
        header = normalize_header(value)
        if not header:
            continue
        role = _role_for(header)
        if role in REPEATABLE_ROLES:
            pass
        elif role != "unknown" and role in seen:
            # A repeated role cannot be addressed by name; keep the column,
            # leave the role open for the manager.
            role = "unknown"
        elif role != "unknown":
            seen.add(role)
        columns.append(
            {
                "letter": letter,
                "header": str(value),
                "display": header,
                "role": role,
                "pair": None,
                "direction": None,
                "direction_basis": None,
            }
        )
    return columns


def _letter_index(letter: str) -> int:
    index = 0
    for char in letter:
        index = index * 26 + (ord(char) - 64)
    return index


def _role_for(header: str) -> str:
    if _matches(header, DEBIT_MARKERS):
        return "debit"
    if _matches(header, CREDIT_MARKERS):
        return "credit"
    for role, aliases in ROLE_ALIASES.items():
        if header.casefold() in {alias.casefold() for alias in aliases}:
            return role
    for role, aliases in ROLE_ALIASES.items():
        if any(alias in header for alias in aliases if len(alias) > 1):
            return role
    return "unknown"


def _matches(header: str, markers: tuple[str, ...]) -> bool:
    return any(marker in header for marker in markers)


def _amount_pairs(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair each 借方 column with the 贷方 column that shares its label prefix."""
    debits = [column for column in columns if column["role"] == "debit"]
    credits = [column for column in columns if column["role"] == "credit"]
    pairs: list[dict[str, Any]] = []
    used: set[str] = set()
    for debit in debits:
        prefix = _pair_prefix(debit["display"], DEBIT_MARKERS)
        match = next(
            (
                credit
                for credit in credits
                if credit["letter"] not in used
                and _pair_prefix(credit["display"], CREDIT_MARKERS) == prefix
            ),
            None,
        )
        if match is None:
            continue
        used.add(match["letter"])
        pair_id = f"amount_{len(pairs) + 1}"
        debit["pair"] = pair_id
        match["pair"] = pair_id
        pairs.append(
            {
                "id": pair_id,
                "label": prefix or debit["display"],
                "debit": debit["letter"],
                "credit": match["letter"],
                "primary": False,
                "direction": {"kind": "undecided"},
            }
        )
    if pairs:
        primary = next(
            (pair for pair in pairs if any(hint in pair["label"] for hint in PRIMARY_PAIR_HINTS)),
            pairs[0],
        )
        primary["primary"] = True
    return pairs


def _pair_prefix(header: str, markers: tuple[str, ...]) -> str:
    for marker in sorted(markers, key=len, reverse=True):
        if marker in header:
            return header.replace(marker, "")
    return header


def _apply_direction(
    grid: dict[int, dict[str, Any]],
    header_row: int,
    columns: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> None:
    """Propose which side of a 借/贷 pair carries the amount, and say why.

    A category or direction column decides it for a trial balance. A voucher
    list has neither, but leaves the unused side blank, so the populated side
    is the answer on every line. When neither holds, the pair stays undecided
    and the manager sets it — a guess here would change the numbers.
    """
    basis = next(
        (column for column in columns if column["role"] in {"category", "direction"}),
        None,
    )
    skip = {item["row"] for item in excluded}
    data_rows = [n for n in sorted(grid) if n > header_row and n not in skip]
    for pair in pairs:
        if basis is not None:
            pair["direction"] = {
                "kind": "by_category" if basis["role"] == "category" else "by_direction_column",
                "column": basis["letter"],
            }
        elif _one_side_per_row(grid, data_rows, pair):
            pair["direction"] = {"kind": "by_populated_side"}
        else:
            pair["direction"] = {"kind": "undecided"}
    for column in columns:
        if column["role"] not in {"debit", "credit"}:
            continue
        pair = next((item for item in pairs if item["id"] == column["pair"]), None)
        if pair is None or pair["direction"]["kind"] == "undecided":
            column["direction"] = "undecided"
            column["direction_basis"] = None
        else:
            column["direction"] = column["role"]
            column["direction_basis"] = pair["direction"].get("column") or pair["direction"]["kind"]


def _one_side_per_row(
    grid: dict[int, dict[str, Any]], data_rows: list[int], pair: dict[str, Any]
) -> bool:
    """True when no data row fills both sides — the shape a voucher list has."""
    if not data_rows:
        return False
    seen = False
    for number in data_rows:
        row = grid[number]
        debit = row.get(pair["debit"])
        credit = row.get(pair["credit"])
        if debit is not None and credit is not None:
            return False
        if debit is not None or credit is not None:
            seen = True
    return seen


def has_undecided_direction(proposal: dict[str, Any]) -> bool:
    return any(
        pair["direction"].get("kind") == "undecided"
        for pair in proposal.get("amount_pairs") or []
        if pair.get("primary")
    )


def _excluded_rows(
    grid: dict[int, dict[str, Any]], header_row: int, columns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Section headers, subtotals and footnotes — everything that is not a data row."""
    first_letter = columns[0]["letter"] if columns else ""
    value_letters = {
        column["letter"] for column in columns if column["role"] in {"debit", "credit", "amount"}
    }
    key_letters = {
        column["letter"]
        for column in columns
        if column["role"] in {"account_code", "account_name", "management_account"}
    }
    excluded: list[dict[str, Any]] = []
    for number in sorted(grid):
        if number <= header_row:
            continue
        row = grid[number]
        text = str(row.get(first_letter, "") or "").strip()
        reason = None
        if len(row) == 1 and first_letter in row and isinstance(row[first_letter], str):
            sentence = len(text) > 20 or text.endswith(("。", ".", "；", ";"))
            reason = (
                "note"
                if sentence or _matches(normalize_header(text), NOTE_KEYWORDS)
                else "section"
            )
        elif _matches(normalize_header(_leading_text(row)), SUBTOTAL_KEYWORDS):
            reason = "subtotal"
        elif key_letters and not (key_letters & set(row)) and (value_letters & set(row)):
            # An amount with no account of its own is a roll-up line.
            reason = "subtotal"
        if reason:
            excluded.append({"row": number, "text": _leading_text(row), "reason": reason})
    return excluded


def _leading_text(row: dict[str, Any]) -> str:
    for letter in sorted(row, key=_letter_index):
        value = row[letter]
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _fill_down_columns(
    grid: dict[int, dict[str, Any]],
    header_row: int,
    columns: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> list[str]:
    """Columns that carry a value only on the first line of each group."""
    skip = {item["row"] for item in excluded}
    data_rows = [n for n in sorted(grid) if n > header_row and n not in skip]
    if len(data_rows) < 3:
        return []
    filled: list[str] = []
    for column in columns:
        if column["role"] not in FILL_DOWN_ROLES:
            continue
        present = sum(1 for number in data_rows if column["letter"] in grid[number])
        if 0 < present < len(data_rows):
            filled.append(column["letter"])
    return filled


PREVIEW_ROWS_EITHER_SIDE = 3
PREVIEW_CELLS = 4
PREVIEW_CELL_CHARS = 40


def _preview(grid: dict[int, dict[str, Any]], header_row: int) -> list[dict[str, Any]]:
    """The rows around the proposed header, so a wrong guess can be seen and moved.

    The manager is told the header is row 4. Without the text of rows 1 to 7 in
    front of her, correcting that is typing a number blind — which is the Excel
    trip this whole flow exists to remove.
    """
    window = range(
        max(1, header_row - PREVIEW_ROWS_EITHER_SIDE),
        header_row + PREVIEW_ROWS_EITHER_SIDE + 1,
    )
    rows: list[dict[str, Any]] = []
    for number in window:
        row = grid.get(number)
        if row is None:
            continue
        cells = [
            {"letter": letter, "text": _clip(row[letter])}
            for letter in sorted(row, key=_letter_index)[:PREVIEW_CELLS]
        ]
        rows.append({"row": number, "is_header": number == header_row, "cells": cells})
    return rows


def _clip(value: Any) -> str:
    text = str(value if value is not None else "").strip().replace("\n", " ")
    return text if len(text) <= PREVIEW_CELL_CHARS else text[: PREVIEW_CELL_CHARS - 1] + "…"


def _scope_hints(grid: dict[int, dict[str, Any]], title_rows: list[int]) -> dict[str, str]:
    """Period, currency and unit as the title area declares them — never invented."""
    blob = " ".join(
        str(value)
        for number in title_rows
        for value in grid[number].values()
        if value is not None
    )
    period = ""
    if not PERIOD_SPAN_IN_TITLE.search(blob):
        match = PERIOD_IN_TITLE.search(blob)
        if match:
            period = f"{match.group(1)}-{int(match.group(2)):02d}"
    currency = ""
    found = CURRENCY_IN_TITLE.search(blob)
    if found:
        currency = found.group(1)
    elif "人民币" in blob:
        currency = "人民币"
    unit = ""
    found_unit = UNIT_IN_TITLE.search(blob)
    if found_unit:
        unit = found_unit.group(1)
    return {"period": period, "currency": currency, "unit": unit}


def _confidence(
    columns: list[dict[str, Any]], pairs: list[dict[str, Any]], header_row: int
) -> float:
    known = sum(1 for column in columns if column["role"] != "unknown")
    score = known / len(columns) if columns else 0.0
    if pairs and all(pair["direction"]["kind"] == "undecided" for pair in pairs):
        score -= 0.2
    if header_row > 10:
        score -= 0.1
    return round(max(0.0, min(1.0, score)), 2)
