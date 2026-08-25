from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import duckdb
from openpyxl import load_workbook

from foundry.errors import LockRefused


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_hash(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    payload = json.dumps({"headers": headers, "rows": rows}, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def load_tabular(path: Path) -> tuple[list[str], list[tuple[Any, ...]]]:
    if not path.is_file():
        raise LockRefused(f"named file is unreadable: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        try:
            raw_headers = next(reader)
        except StopIteration as exc:
            raise LockRefused(f"empty named file: {path}") from exc
        headers = [_normalize(h) for h in raw_headers]
        rows = [tuple(row) for row in reader]
        return headers, rows
    if suffix in {".xlsx", ".xlsm"}:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            raise LockRefused(f"empty named file: {path}")
        iterator = ws.iter_rows(values_only=True)
        try:
            raw_headers = next(iterator)
        except StopIteration as exc:
            raise LockRefused(f"empty named file: {path}") from exc
        headers = [_normalize(str(h or "")) for h in raw_headers]
        rows = [tuple(cell if cell is not None else "" for cell in row) for row in iterator]
        wb.close()
        return headers, rows
    raise LockRefused(f"unsupported import format: {path.suffix}")


def require_columns(headers: list[str], required: list[str], label: str) -> None:
    have = set(headers)
    missing = [col for col in required if col not in have]
    if missing:
        raise LockRefused(f"{label} missing columns {missing}")


def quote_ident(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return f'"{cleaned}"'


def _column_type(rows: list[tuple[Any, ...]], index: int) -> str:
    values = [row[index] for row in rows if row[index] not in (None, "")]
    if values and all(isinstance(v, bool) for v in values):
        return "BOOLEAN"
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return "DOUBLE"
    return "VARCHAR"


def write_table(con: duckdb.DuckDBPyConnection, table: str, headers: list[str], rows: list[tuple[Any, ...]]) -> None:
    if rows:
        cols = ", ".join(f"{quote_ident(h)} {_column_type(rows, i)}" for i, h in enumerate(headers))
    else:
        cols = ", ".join(f"{quote_ident(h)} VARCHAR" for h in headers)
    con.execute(f"CREATE OR REPLACE TABLE {quote_ident(table)} ({cols})")
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(headers))
    con.executemany(f"INSERT INTO {quote_ident(table)} VALUES ({placeholders})", rows)


def checkpoint_and_close(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CHECKPOINT")
    con.close()
