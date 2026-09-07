"""Bounded, lossless table ingestion for analysis snapshots."""

from __future__ import annotations

import csv
import io
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

from foundry.errors import FoundryError

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 256
NUMERIC = re.compile(r"^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
DECIMAL_TYPE = re.compile(r"^DECIMAL\(38,(\d|[12]\d|3[0-8])\)$")
SUPPORTED = {".csv", ".json", ".xlsx", ".md", ".txt"}


def load_json(text: str) -> Any:
    def bad(value):
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        return json.loads(text, parse_float=Decimal, parse_constant=bad)
    except (ValueError, TypeError) as exc:
        raise FoundryError(f"invalid JSON: {exc}") from exc


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise FoundryError("non-finite numeric value")
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def _open_xlsx_archive(data: bytes) -> ZipFile:
    archive = ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in archive.infolist()) > MAX_SOURCE_BYTES * 4:
        archive.close()
        raise FoundryError("workbook expands beyond the source limit")
    return archive


def _xlsx_workbook(data: bytes) -> dict:
    archive = _open_xlsx_archive(data)
    try:
        book = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        try:
            sheets = []
            for sheet in book.worksheets:
                rows = sheet.max_row or 0
                columns = sheet.max_column or 0
                if columns > MAX_COLUMNS or rows > MAX_ROWS + 1:
                    raise FoundryError("worksheet exceeds row/column limits")
                sheets.append({"name": sheet.title, "rows": rows, "columns": columns})
            return {
                "kind": "workbook",
                "schema": [],
                "rows": [],
                "row_count": 0,
                "workbook": {"sheets": sheets},
                "transformation": {
                    "format": "xlsx",
                    "basis": "source_fact",
                    "mode": "workbook_snapshot",
                    "sheet_count": len(sheets),
                    "row_locator": "workbook sheet directory; bind a worksheet range before tabular calculation",
                },
            }
        finally:
            book.close()
    finally:
        archive.close()


def _xlsx(data: bytes, metadata: dict) -> tuple[list[str], list[dict], dict]:
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with _open_xlsx_archive(data) as archive:
        book = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        try:
            sheet_name = metadata.get("sheet") or book.sheetnames[0]
            if sheet_name not in book.sheetnames:
                raise FoundryError(f"no worksheet: {sheet_name}")
            sheet = book[sheet_name]
            if (sheet.max_column or 0) > MAX_COLUMNS or (
                sheet.max_row or 0
            ) > MAX_ROWS + 1:
                raise FoundryError("worksheet exceeds row/column limits")
            workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets = workbook_xml.find("s:sheets", ns)
            rid = next(
                s.attrib[
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                ]
                for s in sheets
                if s.attrib["name"] == sheet_name
            )
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            target = next(r.attrib["Target"] for r in rels if r.attrib["Id"] == rid)
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            raw_cells = {}
            for _, cell in ET.iterparse(
                io.BytesIO(archive.read(member)), events=("end",)
            ):
                if cell.tag != "{" + ns["s"] + "}c":
                    continue
                v, formula = cell.find("s:v", ns), cell.find("s:f", ns)
                if formula is not None and (v is None or v.text is None):
                    raise FoundryError(
                        f"formula has no cached value at {sheet_name}!{cell.attrib.get('r')}"
                    )
                if cell.attrib.get("t") == "e":
                    raise FoundryError(
                        f"worksheet error at {sheet_name}!{cell.attrib.get('r')}"
                    )
                if cell.attrib.get("t", "n") == "n" and v is not None and v.text:
                    raw_cells[cell.attrib["r"]] = Decimal(v.text)
                cell.clear()
            rows = []
            source_row_numbers = []
            headers = None
            for number, cells in enumerate(sheet.iter_rows(), start=1):
                if number > MAX_ROWS + 1:
                    raise FoundryError("dataset exceeds row limit")
                values = [
                    c.value
                    if getattr(c, "is_date", False)
                    else raw_cells.get(getattr(c, "coordinate", ""), c.value)
                    for c in cells
                ]
                if headers is None:
                    headers = [str(v).strip() if v is not None else "" for v in values]
                elif any(v is not None for v in values):
                    rows.append(dict(zip(headers, values)))
                    source_row_numbers.append(number)
            return (
                headers or [],
                rows,
                {
                    "sheet": sheet_name,
                    "header_row": 1,
                    "numeric_parser": "xlsx-original-xml-decimal",
                    "formulas": "cached-values-required",
                    "source_row_numbers": source_row_numbers,
                },
            )
        finally:
            book.close()


def parse_source(data: bytes, suffix: str, metadata: dict) -> dict:
    if suffix not in SUPPORTED:
        raise FoundryError(
            f"unsupported format {suffix}; supported: CSV, XLSX, JSON, Markdown and TXT"
        )
    if len(data) > MAX_SOURCE_BYTES:
        raise FoundryError("source exceeds 32 MiB limit")
    try:
        if suffix in {".md", ".txt"}:
            text = data.decode("utf-8-sig")
            paragraphs = []
            for match in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, flags=re.S):
                paragraphs.append(
                    {
                        "paragraph": len(paragraphs) + 1,
                        "line": text[: match.start()].count("\n") + 1,
                        "text": match.group(0).strip(),
                    }
                )
            return {
                "kind": "background",
                "text": text,
                "paragraphs": paragraphs,
                "schema": [],
                "row_count": 0,
                "transformation": {
                    "format": suffix[1:],
                    "encoding": "utf-8",
                    "basis": "source_fact",
                },
            }
        transformation = {
            "format": suffix[1:],
            "numeric_parser": "decimal",
            "row_locator": "data row index + 2 (one-based header row)",
        }
        workbook = None
        mode = None
        if suffix == ".csv":
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
            headers = reader.fieldnames or []
            rows = []
            for row in reader:
                if None in row:
                    raise FoundryError("CSV row has more fields than its header")
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise FoundryError("dataset exceeds row limit")
        elif suffix == ".xlsx":
            mode = metadata.get("mode")
            if mode is not None and mode not in {"table", "workbook"}:
                raise FoundryError("XLSX mode must be table or workbook")
            if mode == "workbook":
                return _xlsx_workbook(data)
            workbook = _xlsx_workbook(data) if not metadata.get("sheet") else None
            if (
                mode != "table"
                and workbook is not None
                and workbook["transformation"]["sheet_count"] > 1
            ):
                return workbook
            headers, rows, detail = _xlsx(data, metadata)
            transformation.update(detail)
        else:
            parsed = load_json(data.decode("utf-8-sig"))
            rows = parsed.get("rows") if isinstance(parsed, dict) else parsed
            if not isinstance(rows, list) or not all(
                isinstance(row, dict) for row in rows
            ):
                raise FoundryError(
                    "table JSON must be an array of objects or {rows:[objects]}"
                )
            headers = list(dict.fromkeys(key for row in rows for key in row))
            transformation["row_locator"] = "one-based JSON row index"
        if not headers or len(headers) > MAX_COLUMNS or len(rows) > MAX_ROWS:
            raise FoundryError("dataset requires 1–256 columns and at most 100000 rows")
        if any(not isinstance(h, str) or not h.strip() for h in headers) or len(
            {h.casefold() for h in headers}
        ) != len(headers):
            raise FoundryError(
                "column names must be nonempty and unique (case insensitive)"
            )
        schema, normalized = [], [{h: None for h in headers} for _ in rows]
        explicit = metadata.get("column_types") or {}
        for header in headers:
            values = [row.get(header) for row in rows]
            nonempty = [v for v in values if v is not None and v != ""]
            requested = explicit.get(header)
            numeric = bool(nonempty) and all(
                not isinstance(v, bool) and NUMERIC.fullmatch(str(v).strip())
                for v in nonempty
            )
            if requested == "VARCHAR":
                numeric = False
            elif requested and not DECIMAL_TYPE.fullmatch(str(requested)):
                raise FoundryError(
                    f"unsupported column type: {requested}; use VARCHAR or DECIMAL(38,scale)"
                )
            elif requested and not numeric and nonempty:
                raise FoundryError(f"non-numeric value in decimal column {header}")
            dtype = requested or "VARCHAR"
            if numeric:
                decimals = [Decimal(str(v).strip()) for v in nonempty]
                scale = max(max(-v.as_tuple().exponent, 0) for v in decimals)
                integer_digits = max(max(v.adjusted() + 1, 0) for v in decimals)
                if requested:
                    requested_scale = int(DECIMAL_TYPE.fullmatch(requested).group(1))
                    if requested_scale < scale:
                        raise FoundryError(
                            f"column {header} would lose decimal precision"
                        )
                    scale = requested_scale
                if integer_digits + scale > 38:
                    raise FoundryError(f"column {header} exceeds DECIMAL(38) precision")
                dtype = f"DECIMAL(38,{scale})"
            for dest, value in zip(normalized, values):
                if value is None or value == "":
                    dest[header] = None
                elif numeric:
                    dest[header] = format(Decimal(str(value).strip()), "f")
                elif isinstance(value, (list, dict)):
                    raise FoundryError(
                        f"nested value in column {header}; tabular scalar values required"
                    )
                else:
                    dest[header] = (
                        value.isoformat() if hasattr(value, "isoformat") else str(value)
                    )
            schema.append(
                {
                    "name": header,
                    "type": dtype,
                    "nullable": any(v is None or v == "" for v in values),
                }
            )
        grain = metadata.get("grain") or []
        if not isinstance(grain, list) or any(g not in headers for g in grain):
            raise FoundryError("grain must name existing columns")
        return {
            "kind": "table",
            "schema": schema,
            "rows": normalized,
            "row_count": len(rows),
            "transformation": transformation,
        }
    except FoundryError:
        raise
    except (
        ValueError,
        UnicodeError,
        KeyError,
        OSError,
        InvalidOperation,
        BadZipFile,
        csv.Error,
        ET.ParseError,
    ) as exc:
        raise FoundryError(f"cannot parse {suffix} source: {exc}") from exc
