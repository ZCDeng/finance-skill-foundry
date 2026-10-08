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
    # Detail tables the scenarios read: invoices and their collections, cash events,
    # price/quantity rows. Named here so a confirmed table carries the field names
    # receivables_aging, cash_13_weeks and the price/quantity bridge look for.
    "invoice_id": ("发票号", "发票号码", "账单号", "账单编号", "invoice_id"),
    "due_date": ("到期日", "到期日期", "应收日期", "due_date"),
    "issue_date": ("开票日期", "账单日期", "issue_date", "invoice_date"),
    "effective_date": ("回款日期", "收款日期", "核销日期", "effective_date"),
    "product": ("业态", "产品", "product"),
    "quantity": ("数量", "计费面积", "quantity"),
    "price": ("单价", "price"),
    "posting_status": ("过账状态", "posting_status"),
    "status": ("状态", "status"),
    "scenario": ("情景", "scenario"),
    "kind": ("收付类型", "回款类型", "kind"),
    "event_id": ("流水号", "id", "activity_id", "event_id"),
}
# Aliases that name a column only when they are the whole header. `id` at the end
# of ledger_id or 单据ID is not a cash event's id, and `kind` ends many words.
EXACT_ONLY_ALIASES = frozenset({"id", "kind"})
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
ANNUAL_IN_TITLE = re.compile(r"20\d{2}\s*(?:年度|全年)")
AS_OF_DATE_IN_TITLE = re.compile(r"基准日\s*(20\d{2})[-./年]\s*(\d{1,2})[-./月]\s*(\d{1,2})")
CURRENCY_IN_TITLE = re.compile(r"(?:币种|原币)[:：\s]*([A-Za-z]{3}|人民币)")
# A parenthetical at the end qualifies the column, it does not name it:
# 「年化合同金额（万元）」 is a 金额 reported in 万元.
TRAILING_QUALIFIER = re.compile(r"[（(][^（()）]*[)）]\s*$")
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
    presentation = _is_presentation_sheet(name, grid)
    candidates = _header_candidates(grid)
    if not candidates:
        return _excluded(name, "presentation_sheet" if presentation else "no_header")
    blocks = _table_blocks(grid, candidates)
    if not blocks:
        return _excluded(name, "presentation_sheet" if presentation else "no_header")
    selected = max(blocks, key=lambda block: (block["score"], -block["header_row"]))
    header_row = selected["header_row"]
    columns = selected["columns"]
    pairs = selected["amount_pairs"]
    title_rows = [number for number in sorted(grid) if number < selected["start_row"]]
    table = {
        "sheet": name,
        "decision": "table",
        "reason": None,
        "header_row": header_row,
        "title_rows": title_rows,
        "columns": columns,
        "amount_pairs": pairs,
        "excluded_rows": selected["excluded_rows"],
        "fill_down_columns": selected["fill_down_columns"],
        "scope_hints": _scope_hints(grid, title_rows),
        "table_blocks": blocks,
        "selected_block_id": selected["id"],
        "start_row": selected["start_row"],
        "end_row": selected["end_row"],
        "start_column": selected["start_column"],
        "end_column": selected["end_column"],
        "numeric_coverage": selected["numeric_coverage"],
        "preview": selected["preview"],
        "confidence": selected["confidence"],
        # Whether this is a data table and whether anything can be derived from
        # it are two questions. A 区域经营损益表 is plainly a table -- one row per
        # region, numbers across -- while none of its column names mean anything
        # to a ledger vocabulary. Saying "not a table" would be false; offering
        # a checkbox that throws when ticked would be worse.
        "blocked_reason": None if _carries_data(columns, pairs) else "unreadable_columns",
    }
    if presentation:
        # A cover, KPI board or benchmark page is set aside by default, but a KPI board
        # is often the only place a pack states its headline figures. What was read off
        # it stays on the proposal so the manager can adopt it as a table herself.
        return {**table, "decision": "excluded", "reason": "presentation_sheet",
                "blocked_reason": "presentation_sheet", "adoptable": table["blocked_reason"] is None}
    return table


def _custom_table(name: str, grid: dict[int, dict[str, Any]], reason: str) -> dict[str, Any]:
    first = min(grid)
    last = max(grid)
    first_col = min((letter for row in grid.values() for letter in row), key=_letter_index, default="A")
    last_col = max((letter for row in grid.values() for letter in row), key=_letter_index, default="A")
    return {
        "sheet": name,
        "decision": "table",
        "reason": reason,
        "header_row": None,
        "title_rows": [],
        "columns": [],
        "amount_pairs": [],
        "excluded_rows": [],
        "fill_down_columns": [],
        "scope_hints": {"period": "", "currency": "", "unit": ""},
        "table_blocks": [],
        "selected_block_id": None,
        "start_row": first,
        "end_row": last,
        "start_column": first_col,
        "end_column": last_col,
        "numeric_coverage": {
            "numeric_columns_total": 0,
            "numeric_columns_included": 0,
            "numeric_columns_excluded": 0,
            "retained_cell_coverage": 0.0,
            "metadata_only": True,
        },
        "preview": _preview(grid, first),
        "confidence": 0.0,
        "blocked_reason": reason,
    }


def _propose_block(grid: dict[int, dict[str, Any]], block: dict[str, Any]) -> dict[str, Any] | None:
    header_row = block["header_row"]
    bounded = _bounded_grid(grid, block)
    columns = _columns(bounded, header_row)
    if len(columns) < MIN_HEADER_COLUMNS:
        return None
    pairs = _amount_pairs(columns)
    excluded = _excluded_rows(bounded, header_row, columns)
    _annotate_columns(bounded, header_row, columns, excluded)
    coverage = _numeric_coverage(bounded, header_row, columns, excluded)
    _apply_direction(bounded, header_row, columns, pairs, excluded)
    confidence = _confidence(columns, pairs, header_row)
    return {
        "id": block["id"],
        "header_row": header_row,
        "start_row": block["start_row"],
        "end_row": block["end_row"],
        "start_column": block["start_column"],
        "end_column": block["end_column"],
        "score": block["score"],
        "columns": columns,
        "amount_pairs": pairs,
        "excluded_rows": excluded,
        "fill_down_columns": _fill_down_columns(bounded, header_row, columns, excluded),
        "numeric_coverage": coverage,
        "preview": _preview(grid, header_row),
        "confidence": confidence,
        "blocked_reason": None if _carries_data(columns, pairs) else "unreadable_columns",
    }


def _carries_data(
    columns: list[dict[str, Any]], pairs: list[dict[str, Any]]
) -> bool:
    """Whether anything on this sheet survives into a derived table.

    The snapshot builder keeps a column for every named role and folds each
    借贷 pair into one amount with its side; a column it cannot name is dropped.
    A sheet where everything is dropped yields no table at all, and the two
    modules must agree on that -- `test_every_proposed_table_can_be_derived`
    holds them together.
    """
    return bool(pairs or any(column.get("include", True) for column in columns))


def _excluded(name: str, reason: str, **read: Any) -> dict[str, Any]:
    """A sheet set aside before any structure was read out of it."""
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
        "table_blocks": [],
        "selected_block_id": None,
        "numeric_coverage": {
            "numeric_columns_total": 0,
            "numeric_columns_included": 0,
            "numeric_columns_excluded": 0,
            "retained_cell_coverage": 0.0,
            "metadata_only": True,
        },
        "preview": [],
        "confidence": 0.0,
        "blocked_reason": reason,
        **read,
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
    candidates = _header_candidates(grid)
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (item["score"], -item["header_row"]))
    return int(best["header_row"])


def _header_candidates(grid: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that can plausibly start an independent table block."""
    candidates: list[dict[str, Any]] = []
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
        known = sum(1 for letter in labels if _role_for(normalize_header(grid[number][letter])) != "unknown")
        numeric_below = sum(
            1
            for n in sorted(following)[:8]
            for letter in labels
            if _is_numeric(grid[n].get(letter))
        )
        roles = {_role_for(normalize_header(grid[number][letter])) for letter in labels}
        has_amount_pair = "debit" in roles and "credit" in roles
        if not (known >= MIN_HEADER_COLUMNS or numeric_below > 0 or has_amount_pair):
            continue
        candidates.append(
            {
                "header_row": number,
                "labels": labels,
                "score": len(labels) * 10 + overlap * 3 + known * 4 + min(numeric_below, len(labels) * 2),
            }
        )
    return candidates


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
                "source_letter": letter,
                "header": str(value),
                "display": header,
                "stable_name": _stable_name(letter, header),
                "role": role,
                "include": True,
                "exclusion_reason": "",
                "numeric": False,
                "pair": None,
                "direction": None,
                "direction_basis": None,
            }
        )
    return columns


def _stable_name(letter: str, header: str) -> str:
    cleaned = re.sub(r"\W+", "_", header, flags=re.UNICODE).strip("_")
    return f"col_{letter}_{cleaned or 'column'}"


def _annotate_columns(
    grid: dict[int, dict[str, Any]],
    header_row: int,
    columns: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> None:
    skip = {item["row"] for item in excluded}
    for column in columns:
        letter = column["letter"]
        values = [
            grid[number].get(letter)
            for number in sorted(grid)
            if number > header_row and number not in skip and letter in grid[number]
        ]
        column["numeric"] = any(_is_numeric(value) for value in values)


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _numeric_coverage(
    grid: dict[int, dict[str, Any]],
    header_row: int,
    columns: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> dict[str, Any]:
    numeric = [column for column in columns if column.get("numeric")]
    included = [column for column in numeric if column.get("include", True)]
    column_letters = {column["letter"] for column in columns}
    included_letters = {column["letter"] for column in columns if column.get("include", True)}
    skip = {item["row"] for item in excluded}
    total_cells = 0
    retained_cells = 0
    for number in sorted(grid):
        if number <= header_row or number in skip:
            continue
        for letter in grid[number]:
            if letter not in column_letters:
                continue
            total_cells += 1
            if letter in included_letters:
                retained_cells += 1
    return {
        "numeric_columns_total": len(numeric),
        "numeric_columns_included": len(included),
        "numeric_columns_excluded": len(numeric) - len(included),
        "retained_cell_coverage": round(retained_cells / total_cells, 4) if total_cells else 0.0,
        "metadata_only": len(included) == 0,
    }


def _table_blocks(grid: dict[int, dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explicit block rectangles derived from adjacent candidate headers."""
    blocks: list[dict[str, Any]] = []
    ordered = sorted(candidates, key=lambda item: item["header_row"])
    max_row = max(grid)
    for index, candidate in enumerate(ordered):
        labels = sorted(candidate["labels"], key=_letter_index)
        if not labels:
            continue
        next_header = ordered[index + 1]["header_row"] if index + 1 < len(ordered) else None
        end_row = (next_header - 1) if next_header is not None else max_row
        block = {
            "id": f"block_{len(blocks) + 1}",
            "header_row": candidate["header_row"],
            "start_row": candidate["header_row"],
            "end_row": end_row,
            "start_column": labels[0],
            "end_column": labels[-1],
            "score": candidate["score"],
        }
        proposed = _propose_block(grid, block)
        if proposed is not None:
            blocks.append(proposed)
    return blocks


def _bounded_grid(grid: dict[int, dict[str, Any]], block: dict[str, Any]) -> dict[int, dict[str, Any]]:
    start_col = _letter_index(block["start_column"])
    end_col = _letter_index(block["end_column"])
    bounded: dict[int, dict[str, Any]] = {}
    for number, row in grid.items():
        if number < block["start_row"] or number > block["end_row"]:
            continue
        clipped = {
            letter: value
            for letter, value in row.items()
            if start_col <= _letter_index(letter) <= end_col
        }
        if clipped:
            bounded[number] = clipped
    return bounded


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
    # An alias counts only where the compound's head noun sits, at the end:
    # 供应商类别 is a kind of 类别 and 城市公司 a kind of 公司. An alias anywhere
    # earlier modifies something else -- 期间费用 is a kind of 费用, not an
    # accounting period -- and taking the role from it would file an amount in a
    # column named period, which reads as data rather than as a bad guess.
    tail = TRAILING_QUALIFIER.sub("", header).strip().casefold()
    for role, aliases in ROLE_ALIASES.items():
        if any(tail.endswith(alias.casefold()) for alias in aliases
               if len(alias) > 1 and alias not in EXACT_ONLY_ALIASES):
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
    granularity = ""
    as_of_date = ""
    if ANNUAL_IN_TITLE.search(blob):
        granularity = "annual"
    elif found_as_of := AS_OF_DATE_IN_TITLE.search(blob):
        as_of_date = f"{found_as_of.group(1)}-{int(found_as_of.group(2)):02d}-{int(found_as_of.group(3)):02d}"
        granularity = "as_of"
    elif not PERIOD_SPAN_IN_TITLE.search(blob):
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
    result = {"period": period, "currency": currency, "unit": unit}
    if granularity:
        result["granularity"] = granularity
    if as_of_date:
        result["as_of_date"] = as_of_date
    if "BUD" in blob or "预算" in blob:
        result["scenario"] = "budget"
    if "LE" in blob or "滚动预测" in blob:
        result["forecast"] = "LE"
    return result


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
