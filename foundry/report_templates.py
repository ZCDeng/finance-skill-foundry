"""Bundled and task-published company report templates."""

from __future__ import annotations

import io
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName

from foundry.errors import FoundryError
from foundry.resources import resource_dir

TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PUBLIC_FIELDS = ("template_id", "label", "kind")
WORD_KINDS = {"word"}
EXCEL_KINDS = {"excel"}
ALLOWED_SUFFIX = {".docx": "word", ".xlsx": "excel"}
TEMPLATE_MAX_BYTES = 25 * 1024 * 1024


def bundled_template_dir() -> Path:
    return resource_dir("templates")


def excel_brief_template_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Brief"
    sheet["A2"] = "利润"
    sheet["A3"] = "量差"
    sheet["A4"] = "价差"
    sheet["A5"] = "结构/费用"
    sheet["A6"] = "合计"
    sheet["B2"] = 0
    sheet["B3"] = 0
    sheet["B4"] = 0
    sheet["B5"] = 0
    sheet["B6"] = "=SUM(B2:B5)"
    for row in range(2, 6):
        sheet[f"B{row}"].number_format = "0.00"
    sheet["B6"].number_format = "0.00"
    workbook.defined_names.add(DefinedName("Profit", attr_text="'Brief'!$B$2"))
    workbook.defined_names.add(DefinedName("Volume", attr_text="'Brief'!$B$3"))
    workbook.defined_names.add(DefinedName("Price", attr_text="'Brief'!$B$4"))
    workbook.defined_names.add(DefinedName("Mix", attr_text="'Brief'!$B$5"))
    workbook.defined_names.add(DefinedName("Total", attr_text="'Brief'!$B$6"))
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def named_range_names(data: bytes) -> list[str]:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=False)
    except Exception as exc:
        raise FoundryError("excel template snapshot is not a readable workbook") from exc
    try:
        return [str(name) for name in workbook.defined_names.keys()]
    finally:
        workbook.close()


def values_from_run(run: dict, names: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map named ranges onto one authorized run row; unmatched names stay unfilled."""
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    rows = [row for row in (result.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        raise FoundryError("run has no result rows to fill the template")
    lookup: dict[str, Any] = {}
    for row in rows:
        metric = str(row.get("metric") or "").strip()
        if metric:
            for key in ("contribution", "amount", "value", "variance"):
                if row.get(key) not in (None, ""):
                    lookup.setdefault(metric.casefold(), row[key])
                    break
    total = rows[0] if len(rows) == 1 else next(
        (row for row in rows if not str(row.get("organization") or "").strip()), rows[0]
    )
    for key, value in total.items():
        lookup.setdefault(str(key).casefold(), value)
    values: dict[str, str] = {}
    unfilled: list[str] = []
    for name in names:
        value = lookup.get(name.casefold())
        if value in (None, "") or isinstance(value, (dict, list, bool)):
            unfilled.append(name)
            continue
        try:
            values[name] = format(Decimal(str(value)), "f")
        except (InvalidOperation, ValueError):
            unfilled.append(name)
    return values, unfilled


def apply_excel_named_ranges(data: bytes, values: dict[str, str]) -> bytes:
    if not isinstance(values, dict) or not values:
        raise FoundryError("excel template values must come from an authorized run")
    payload = dict(values)
    try:
        workbook = load_workbook(io.BytesIO(data))
    except Exception as exc:
        raise FoundryError("excel template snapshot is not a readable workbook") from exc
    defined = {name: workbook.defined_names.get(name) for name in payload}
    missing = [name for name, item in defined.items() if item is None]
    if missing:
        raise FoundryError(f"excel template is missing named ranges: {', '.join(missing)}")
    for name, raw in payload.items():
        try:
            amount = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise FoundryError(f"excel template value for {name} must be an amount") from exc
        definition = defined[name]
        destinations = list(definition.destinations) if definition is not None else []
        if not destinations:
            raise FoundryError(f"excel template named range {name} has no destination")
        sheet_name, coord = destinations[0]
        cell = workbook[sheet_name][coord.split(":")[0]]
        cell.value = amount
        cell.data_type = "n"
        cell.number_format = "0.00"
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def public_item(record: dict[str, Any]) -> dict[str, str]:
    return {key: str(record[key]) for key in PUBLIC_FIELDS}


def bundled_templates() -> list[dict[str, str]]:
    items = []
    root = bundled_template_dir()
    for path in sorted(root.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        items.append(public_item(record))
    items.append({"template_id": "management-brief-xlsx-v1", "label": "经营简报 Excel", "kind": "excel"})
    return items


def bundled_document(template_id: str) -> dict[str, Any]:
    path = bundled_template_dir() / f"{template_id}.json"
    if not path.is_file():
        raise FoundryError("unknown report template")
    record = json.loads(path.read_text(encoding="utf-8"))
    document = record.get("document")
    if not isinstance(document, dict):
        raise FoundryError("bundled template document is invalid")
    return document


def bundled_excel_bytes(template_id: str) -> bytes:
    if template_id != "management-brief-xlsx-v1":
        raise FoundryError("unknown report template")
    path = bundled_template_dir() / "management-brief.xlsx"
    return path.read_bytes() if path.is_file() else excel_brief_template_bytes()


def metadata_from_scope(scope: dict[str, Any] | None) -> dict[str, str]:
    scope = scope if isinstance(scope, dict) else {}
    return {
        "ledger": str(scope.get("ledger") or ""),
        "organization": str(scope.get("organization") or ""),
        "company": str(scope.get("company") or ""),
        "period": str(scope.get("period") or ""),
        "currency": str(scope.get("currency") or ""),
        "unit": str(scope.get("unit") or ""),
    }


def reject_pptx(path: Path, data: bytes) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".pptx" or b"ppt/presentation" in data[: 64 * 1024]:
        raise FoundryError("pptx templates are not supported")
    kind = ALLOWED_SUFFIX.get(suffix)
    if kind is None:
        raise FoundryError("company templates must be Word or Excel files")
    if kind == "excel":
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                names = " ".join(archive.namelist())
        except BadZipFile as exc:
            raise FoundryError("invalid Excel template archive") from exc
        if "xl/" not in names:
            raise FoundryError("excel template snapshot is not a readable workbook")
    if kind == "word":
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                names = " ".join(archive.namelist())
        except BadZipFile as exc:
            raise FoundryError("invalid Word template archive") from exc
        if "word/" not in names:
            raise FoundryError("word template snapshot is not a readable document")
    return kind


def assert_template_id(value: Any) -> str:
    text = str(value or "")
    if not TEMPLATE_ID.fullmatch(text):
        raise FoundryError("template_id is invalid")
    return text
