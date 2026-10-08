"""收费明细: billing detail too large for a dataset, read into DuckDB, and the collection rates it supports.

A property-management company's billing system exports receivables (房产 × 收费项目 × 账期) and
receipts by the hundred thousand rows a month. A dataset holds 100,000 rows read cell by cell; a
detail table holds up to 5,000,000, streamed from one or more CSV files (UTF-8 or GBK) straight into
a DuckDB file beside the original bytes. Every row keeps which file and which line it came from.

Nothing is computed from a column until the manager has confirmed what each column is: the
assistant may propose a mapping, only the manager confirms it (the same rule as table structures).

The rates follow industry-common practice (方案 notes/billing-detail-collection-plan-20261008.md):
amounts not households, receivables net of waivers, receipts attributed to the bill's 账期 and never
to the day they arrived, prepayments counted only once applied to a bill that has fallen due, void
bills left out, red-letter reversals netted with their originals. Where companies differ the
difference is a parameter of the run (total_method, year_start_month, related_owners), never a branch.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import re
import shutil
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import duckdb

from foundry.analysis_data import decode_text
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.structure_proposal import normalize_header
from foundry.structure_records import MANAGER, resolve_source
from foundry.task import Task, now_iso

MAX_DETAIL_ROWS = 5_000_000
MAX_DETAIL_FILES = 32
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
SNIFF_BYTES = 1024 * 1024
SAMPLE_LINES = 10

# The standard columns of each kind of detail, with the names billing systems export them under.
# The first name is the one the guide and the templates use.
FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "receivable": {
        "bill_id": ("应收单号", "账单号", "账单编号", "应收单据号"),
        "property_id": ("房产编号", "房号编码", "资源编号"),
        "fee_item": ("收费项目", "费项", "收费科目"),
        "period": ("账期", "所属账期", "计费月份", "费用所属期"),
        "amount_gross": ("应收原额", "应收金额", "计费金额"),
        "waiver": ("减免额", "减免金额", "优惠金额"),
        "amount_net": ("应收净额", "实际应收"),
        "due_date": ("到期日", "应收日期"),
        "status": ("单据状态", "状态"),
        "project": ("项目", "项目名称", "管理处"),
        "customer_type": ("客户性质", "客户类型"),
    },
    "receipt": {
        "receipt_id": ("收款单号", "收据号", "实收单号"),
        "date": ("收款日期", "实收日期", "缴费日期"),
        "bill_id": ("应收单号", "账单号", "账单编号"),
        "amount": ("收款金额", "实收金额", "本次收款"),
        "property_id": ("房产编号", "房号编码"),
        "method": ("收款方式", "支付方式"),
        "nature": ("款项性质", "收款性质", "款项类别"),
    },
    "property": {
        "property_id": ("房产编号", "房号编码", "资源编号"),
        "project": ("项目", "项目名称", "项目编码"),
        "city": ("城市公司", "所属组织"),
        "nature": ("房产性质",),
        "type": ("房产类型",),
        "owner": ("产权归属", "产权性质"),
        "area": ("计费面积", "建筑面积"),
        "state": ("空间状态", "房产状态"),
    },
}
REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    # Each entry is one requirement; a tuple of several fields is met by any of them.
    "receivable": (("bill_id",), ("property_id",), ("period",), ("amount_net", "amount_gross")),
    "receipt": (("date",), ("bill_id",), ("amount",)),
    "property": (("property_id",),),
}
KIND_LABELS = {"receivable": "应收明细", "receipt": "实收明细", "property": "房产主数据"}
# Who carries the bill's dimensions: grouping by a property field needs the property master.
GROUP_FIELDS = {"fee_item": "receivable", "project": "receivable", "customer_type": "receivable",
                "city": "property", "nature": "property", "type": "property", "owner": "property"}
TOTAL_METHODS = ("bounded", "all_receipts")
DEFAULT_RELATED_OWNERS = ("地产",)


# --- reading the files ------------------------------------------------------------------------


def _sniff_encoding(path: Path) -> str:
    """UTF-8 or GB18030, judged on the first megabyte (decode_text's rule, a split character allowed)."""
    with path.open("rb") as handle:
        head = handle.read(SNIFF_BYTES)
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            codecs.getincrementaldecoder(encoding)().decode(head, final=False)
        except UnicodeDecodeError:
            continue
        if encoding == "gb18030":
            return "gb18030"
        # Valid UTF-8 can still be GBK (decode_text); judge on whole lines only.
        cut = head[: head.rfind(b"\n") + 1] or head
        try:
            return decode_text(cut)[1]
        except UnicodeDecodeError:
            return "gb18030"
    raise FoundryError(f"{path.name}: neither UTF-8 nor GBK text")


def _header(path: Path, encoding: str) -> list[str]:
    with path.open("r", encoding="utf-8-sig" if encoding == "utf-8" else encoding, newline="") as handle:
        row = next(csv.reader(handle), None)
    names = [normalize_header(cell) for cell in row or []]
    if len(names) < 2 or not all(names):
        raise FoundryError(f"{path.name}: the first line must be the column names, none of them blank")
    if len(set(names)) != len(names):
        repeated = sorted({name for name in names if names.count(name) > 1})
        raise FoundryError(f"{path.name}: column names repeat: {'、'.join(repeated)}")
    return names


def _utf8_copy(path: Path, encoding: str, target: Path) -> Path:
    """The file as UTF-8 for DuckDB, which reads no GBK; the original bytes are kept as they came."""
    if encoding == "utf-8":
        return path
    with path.open("r", encoding=encoding, newline="") as source, target.open("w", encoding="utf-8", newline="") as out:
        shutil.copyfileobj(source, out, 1024 * 1024)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def propose_mapping(kind: str, columns: list[str]) -> dict[str, str]:
    """Each standard field the headers name outright, by the names billing systems use."""
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for field, aliases in FIELDS[kind].items():
        found = next((name for alias in aliases for name in columns if name == alias and name not in taken), None)
        if found:
            mapping[field] = found
            taken.add(found)
    return mapping


# --- the store --------------------------------------------------------------------------------


class BillingDetailStore:
    """Detail tables and collection runs of one task, under ``analysis/details``."""

    def __init__(self, task: Task, *, actor: str | None = None):
        self.task = task
        self.actor = resolve_source(actor)
        self.root = task.root / "analysis" / "details"
        if not self.root.resolve().is_relative_to(task.root.resolve()):
            raise FoundryError("detail path escapes this task")

    # Adding.

    def add(self, kind: str, paths: list[Path], *, name: str) -> dict:
        if kind not in FIELDS:
            raise FoundryError(f"detail kind must be one of: {', '.join(FIELDS)}")
        name = str(name or "").strip()
        if not name or len(name) > 200:
            raise FoundryError("detail name is required, at most 200 characters")
        paths = [Path(path) for path in paths]
        if not paths or len(paths) > MAX_DETAIL_FILES:
            raise FoundryError(f"a detail table takes 1 to {MAX_DETAIL_FILES} CSV files")
        for path in paths:
            if path.suffix.lower() != ".csv":
                raise FoundryError(f"{path.name}: a detail table is read from CSV files; save the sheet as CSV first")
            if not path.is_file():
                raise FoundryError(f"detail source not found: {path.name}")
            if path.stat().st_size > MAX_FILE_BYTES:
                raise FoundryError(f"{path.name}: each file can be at most 2 GiB")
        detail_id = uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".staging-{detail_id}"
        staging.mkdir()
        try:
            record = self._load(kind, name, paths, detail_id, staging)
            with exclusive(self.task.lock_path, timeout=10):
                staging.rename(self.root / detail_id)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return self.get(record["id"])

    def _load(self, kind: str, name: str, paths: list[Path], detail_id: str, folder: Path) -> dict:
        files: list[dict] = []
        columns: list[str] | None = None
        for index, path in enumerate(paths):
            encoding = _sniff_encoding(path)
            header = _header(path, encoding)
            if columns is None:
                columns = header
            elif header != columns:
                raise FoundryError(f"{path.name}: its columns differ from {paths[0].name}; every file of one table needs the same columns")
            stored = f"source-{index + 1:02d}.csv"
            shutil.copyfile(path, folder / stored)
            files.append({"name": path.name, "source_file": stored, "bytes": path.stat().st_size,
                          "sha256": _sha256(folder / stored), "encoding": encoding})
        assert columns is not None
        names = [f"c{number}" for number in range(1, len(columns) + 1)]
        database = folder / "detail.duckdb"
        connection = duckdb.connect(str(database))
        try:
            # One thread keeps each file's rows in file order, so row_number() is the line in the file.
            connection.execute("SET threads TO 1")
            column_list = ", ".join(f"{column} VARCHAR" for column in names)
            connection.execute(f"CREATE TABLE raw (_file INTEGER, _line BIGINT, {column_list})")
            for index, entry in enumerate(files):
                readable = _utf8_copy(folder / entry["source_file"], entry["encoding"], folder / "reading.csv")
                columns_spec = "{" + ", ".join(f"'{column}': 'VARCHAR'" for column in names) + "}"
                connection.execute(
                    f"INSERT INTO raw SELECT ?, row_number() OVER () + 1, * FROM read_csv(?, header = true, "
                    f"columns = {columns_spec}, delim = ',', quote = '\"', escape = '\"', strict_mode = false, "
                    f"null_padding = true, parallel = false)",
                    [index, str(readable)],
                )
                entry["rows"] = connection.execute("SELECT count(*) FROM raw WHERE _file = ?", [index]).fetchone()[0]
                if readable != folder / entry["source_file"]:
                    readable.unlink()
                total = sum(item.get("rows", 0) for item in files)
                if total > MAX_DETAIL_ROWS:
                    raise FoundryError(f"a detail table holds at most {MAX_DETAIL_ROWS:,} rows; split it by period or city")
        except duckdb.Error as exc:
            raise FoundryError(f"cannot read the CSV: {exc}") from exc
        finally:
            connection.close()
        record = {
            "id": detail_id,
            "task_id": self.task.id,
            "kind": kind,
            "name": name,
            "created_at": now_iso(),
            "added_ns": time.time_ns(),
            "added_by": self.actor,
            "files": files,
            "columns": columns,
            "row_count": sum(entry["rows"] for entry in files),
            "proposal": {"mapping": propose_mapping(kind, columns), "by": "system", "at": now_iso()},
            "confirmation": None,
        }
        record["database_sha256"] = _sha256(database)
        write_json_atomic(folder / "meta.json", record)
        return record

    # Reading.

    def _folder(self, detail_id: Any) -> Path:
        text = str(detail_id or "")
        if not re.fullmatch(r"[0-9a-f]{32}", text):
            raise FoundryError("detail id must be 32 hex characters")
        folder = self.root / text
        if not (folder / "meta.json").is_file():
            raise FoundryError(f"no detail table {text}")
        return folder

    def get(self, detail_id: Any) -> dict:
        meta = json.loads((self._folder(detail_id) / "meta.json").read_text(encoding="utf-8"))
        return {**meta, "missing": self._missing(meta["kind"], self._mapping(meta))}

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        rows = [self.get(folder.name) for folder in sorted(self.root.iterdir())
                if folder.is_dir() and not folder.name.startswith(".") and (folder / "meta.json").is_file()]
        return sorted(rows, key=lambda row: row["added_ns"])

    @staticmethod
    def _mapping(meta: dict) -> dict[str, str]:
        chosen = meta.get("confirmation") or meta.get("proposal") or {}
        return dict(chosen.get("mapping") or {})

    @staticmethod
    def _missing(kind: str, mapping: dict[str, str]) -> list[str]:
        return ["/".join(FIELDS[kind][field][0] for field in options)
                for options in REQUIRED[kind] if not any(field in mapping for field in options)]

    # Proposing and confirming what each column is.

    def _checked_mapping(self, meta: dict, mapping: Any) -> dict[str, str]:
        if not isinstance(mapping, dict):
            raise FoundryError("mapping must be an object of standard field to column name")
        fields = FIELDS[meta["kind"]]
        clean: dict[str, str] = {}
        for field, column in mapping.items():
            if field not in fields:
                raise FoundryError(f"{KIND_LABELS[meta['kind']]} has no field {field}; fields: {', '.join(fields)}")
            column = normalize_header(column)
            if column not in meta["columns"]:
                raise FoundryError(f"no column {column} in this detail table")
            if column in clean.values():
                raise FoundryError(f"column {column} is mapped twice")
            clean[field] = column
        missing = self._missing(meta["kind"], clean)
        if missing:
            raise FoundryError(f"still unmapped: {'、'.join(missing)}")
        return clean

    def propose(self, detail_id: Any, mapping: Any) -> dict:
        folder = self._folder(detail_id)
        with exclusive(self.task.lock_path, timeout=10):
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            meta["proposal"] = {"mapping": self._checked_mapping(meta, mapping), "by": self.actor, "at": now_iso()}
            write_json_atomic(folder / "meta.json", meta)
        return self.get(detail_id)

    def confirm(self, detail_id: Any, mapping: Any = None) -> dict:
        """The manager's word on what each column is; with no mapping given, the latest proposal."""
        if self.actor != MANAGER:
            raise FoundryError("only the manager confirms what a detail table's columns are; propose the mapping instead")
        folder = self._folder(detail_id)
        with exclusive(self.task.lock_path, timeout=10):
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            chosen = (meta.get("proposal") or {}).get("mapping") if mapping is None else mapping
            meta["confirmation"] = {"mapping": self._checked_mapping(meta, chosen), "by": MANAGER, "at": now_iso()}
            write_json_atomic(folder / "meta.json", meta)
        return self.get(detail_id)

    # The collection run.

    def collection_run(self, spec: Any) -> dict:
        if not isinstance(spec, dict):
            raise FoundryError("collection spec must be an object")
        params = _params(spec)
        metas = {}
        for kind in ("receivable", "receipt", "property"):
            if spec.get(kind) in (None, "") and kind == "property":
                continue
            meta = self.get(spec.get(kind))
            if meta["kind"] != kind:
                raise FoundryError(f"{kind} must be a {KIND_LABELS[kind]} detail table, not {KIND_LABELS[meta['kind']]}")
            if not meta.get("confirmation"):
                raise FoundryError(f"{meta['name']}: the manager has not confirmed its columns yet")
            metas[kind] = meta
        for field in params["group_by"]:
            if GROUP_FIELDS[field] not in metas or field not in metas[GROUP_FIELDS[field]]["confirmation"]["mapping"]:
                raise FoundryError(f"grouping by {field} needs that column confirmed in the {KIND_LABELS[GROUP_FIELDS[field]]}")
        if params["exclude_related"] and ("property" not in metas or "owner" not in metas["property"]["confirmation"]["mapping"]):
            raise FoundryError("leaving related parties out needs the property master's 产权归属 column")
        connection = duckdb.connect(":memory:")
        try:
            for kind, meta in metas.items():
                path = str(self._folder(meta["id"]) / "detail.duckdb").replace("'", "''")
                connection.execute(f"ATTACH '{path}' AS {kind} (READ_ONLY)")
            result = _compute(connection, metas, params)
        except duckdb.Error as exc:
            raise FoundryError(f"collection run failed: {exc}") from exc
        finally:
            connection.close()
        run = {
            "id": uuid.uuid4().hex,
            "task_id": self.task.id,
            "created_at": now_iso(),
            "run_by": self.actor,
            "params": params,
            "inputs": {kind: {"id": meta["id"], "name": meta["name"], "database_sha256": meta["database_sha256"],
                              "mapping": meta["confirmation"]["mapping"],
                              "files": [{"name": entry["name"], "sha256": entry["sha256"]} for entry in meta["files"]]}
                       for kind, meta in metas.items()},
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "result": result,
        }
        runs = self.root / "runs"
        with exclusive(self.task.lock_path, timeout=10):
            runs.mkdir(parents=True, exist_ok=True)
            write_json_atomic(runs / f"{run['id']}.json", run)
        return run


# --- the calculation --------------------------------------------------------------------------


def _params(spec: dict) -> dict:
    as_of = str(spec.get("as_of") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise FoundryError("as_of is the statistics date, YYYY-MM-DD")
    start = spec.get("year_start_month", 1)
    if not isinstance(start, int) or not 1 <= start <= 12:
        raise FoundryError("year_start_month is 1 to 12 (7 for a July-to-June service year)")
    method = spec.get("total_method", "bounded")
    if method not in TOTAL_METHODS:
        raise FoundryError(f"total_method is one of: {', '.join(TOTAL_METHODS)}")
    related = spec.get("related_owners", list(DEFAULT_RELATED_OWNERS))
    if not isinstance(related, list) or not all(isinstance(item, str) and item.strip() for item in related):
        raise FoundryError("related_owners is a list of 产权归属 values")
    group_by = spec.get("group_by", [])
    if not isinstance(group_by, list) or any(field not in GROUP_FIELDS for field in group_by) or len(group_by) > 2:
        raise FoundryError(f"group_by takes up to two of: {', '.join(GROUP_FIELDS)}")
    reported = spec.get("reported", {})
    if not isinstance(reported, dict) or any(key not in ("collection_rate_current", "collection_rate_total") for key in reported):
        raise FoundryError("reported takes collection_rate_current and collection_rate_total, as rates (0.9214)")
    return {"as_of": as_of, "year_start_month": start, "total_method": method,
            "related_owners": [item.strip() for item in related], "exclude_related": bool(spec.get("exclude_related", False)),
            "group_by": list(group_by), "reported": {key: str(Decimal(str(value))) for key, value in reported.items()}}


def _column(meta: dict, field: str, table: str) -> str | None:
    column = meta["confirmation"]["mapping"].get(field)
    return None if column is None else f"{table}.c{meta['columns'].index(column) + 1}"


def _amount(expression: str) -> str:
    """A money cell as DECIMAL: thousands separators dropped, (1,234.00) read as negative, anything else NULL."""
    cleaned = f"replace(replace(replace(trim({expression}), ',', ''), '，', ''), '¥', '')"
    return (f"CASE WHEN regexp_matches({cleaned}, '^\\(.*\\)$') "
            f"THEN -TRY_CAST(trim({cleaned}, '()') AS DECIMAL(20,2)) ELSE TRY_CAST({cleaned} AS DECIMAL(20,2)) END")


def _month(expression: str) -> str:
    """A 账期 as the first day of its month: 2026-08, 2026/8, 202608, 2026年8月 and full dates all read."""
    text = f"trim({expression})"
    return (f"CASE WHEN regexp_matches({text}, '^\\d{{6}}$') "
            f"THEN TRY_CAST(substr({text}, 1, 4) || '-' || substr({text}, 5, 2) || '-01' AS DATE) "
            f"ELSE TRY_CAST(regexp_extract({text}, '^(\\d{{4}})\\D+\\d', 1) || '-' "
            f"|| lpad(regexp_extract({text}, '^\\d{{4}}\\D+(\\d{{1,2}})', 1), 2, '0') || '-01' AS DATE) END")


def _date(expression: str) -> str:
    text = f"trim({expression})"
    pattern = "^(\\d{4})\\D?(\\d{1,2})\\D?(\\d{1,2})"
    return (f"TRY_CAST(regexp_extract({text}, '{pattern}', 1) || '-' || lpad(regexp_extract({text}, '{pattern}', 2), 2, '0') "
            f"|| '-' || lpad(regexp_extract({text}, '{pattern}', 3), 2, '0') AS DATE)")


def _text(expression: str | None) -> str:
    return "NULL" if expression is None else f"nullif(trim({expression}), '')"


def _prepare(connection, metas: dict, params: dict) -> None:
    """Tables of the raw text with every field typed, built once per run: bills, receipts, properties."""
    rv = metas["receivable"]
    col = lambda field: _column(rv, field, "r")  # noqa: E731
    gross = _amount(col("amount_gross")) if col("amount_gross") else "NULL"
    waiver = _amount(col("waiver")) if col("waiver") else "NULL"
    net = _amount(col("amount_net")) if col("amount_net") else f"({gross}) - coalesce({waiver}, 0)"
    status = _text(col("status"))
    connection.execute(f"""
        CREATE TEMP TABLE bill_lines AS SELECT
            r._file AS file, r._line AS line,
            {_text(col('bill_id'))} AS bill_id, {_text(col('property_id'))} AS property_id,
            {_text(col('fee_item'))} AS fee_item, {_text(col('project'))} AS project,
            {_text(col('customer_type'))} AS customer_type,
            {_month(col('period'))} AS period, {gross} AS gross, {waiver} AS waiver, {net} AS net,
            coalesce(contains({status}, '作废'), false) AS void, coalesce(contains({status}, '冲红'), false) AS red
        FROM receivable.raw AS r""")
    # One bill per 应收单号: a red-letter line nets with its original; a void bill counts for nothing.
    connection.execute("""
        CREATE TEMP TABLE bills AS SELECT bill_id, any_value(property_id) AS property_id, any_value(fee_item) AS fee_item,
            any_value(project) AS project, any_value(customer_type) AS customer_type, min(period) AS period,
            sum(gross) AS gross, sum(waiver) AS waiver, sum(net) AS net
        FROM bill_lines WHERE NOT void AND bill_id IS NOT NULL AND period IS NOT NULL AND net IS NOT NULL
        GROUP BY bill_id""")
    rc = metas["receipt"]
    col = lambda field: _column(rc, field, "p")  # noqa: E731
    connection.execute(f"""
        CREATE TEMP TABLE receipts AS SELECT p._file AS file, p._line AS line,
            {_text(col('bill_id'))} AS bill_id, {_date(col('date'))} AS date, {_amount(col('amount'))} AS amount,
            {_text(col('method'))} AS method, {_text(col('nature'))} AS nature
        FROM receipt.raw AS p""")
    if "property" in metas:
        pm = metas["property"]
        col = lambda field: _column(pm, field, "h")  # noqa: E731
        owners = ", ".join("'" + owner.replace("'", "''") + "'" for owner in params["related_owners"])
        connection.execute(f"""
            CREATE TEMP TABLE properties AS SELECT {_text(col('property_id'))} AS property_id,
                {_text(col('city'))} AS city, {_text(col('nature'))} AS nature, {_text(col('type'))} AS type,
                {_text(col('owner'))} AS owner, coalesce({_text(col('owner'))} IN ({owners}), false) AS related
            FROM property.raw AS h""")
    else:
        connection.execute("CREATE TEMP TABLE properties AS SELECT NULL::VARCHAR AS property_id, NULL::VARCHAR AS city, "
                           "NULL::VARCHAR AS nature, NULL::VARCHAR AS type, NULL::VARCHAR AS owner, false AS related WHERE false")
    # Every receipt against its bill, placed by the bill's 账期 relative to the statistics year.
    connection.execute("""
        CREATE TEMP TABLE placed AS SELECT x.*, b.period, b.property_id, b.fee_item, b.project, b.customer_type,
            CASE WHEN b.bill_id IS NULL THEN 'unmatched'
                 WHEN b.period < getvariable('year_start') THEN 'arrears'
                 WHEN b.period > getvariable('as_of_month') THEN 'advance'
                 ELSE 'current' END AS place
        FROM receipts AS x LEFT JOIN bills AS b USING (bill_id)
        WHERE x.date IS NOT NULL AND x.amount IS NOT NULL AND x.date <= getvariable('as_of')""")


def _figures(connection, where_bill: str, where_receipt: str, params: dict) -> dict:
    """The rates over the bills and receipts the two conditions keep."""
    one = lambda sql: connection.execute(sql).fetchone()  # noqa: E731
    current_bills = f"b.period BETWEEN getvariable('year_start') AND getvariable('as_of_month') AND {where_bill}"
    receivable, gross, waiver, households = one(
        f"SELECT coalesce(sum(net), 0), sum(gross), coalesce(sum(waiver), 0), count(DISTINCT property_id) "
        f"FROM bills AS b LEFT JOIN properties AS h USING (property_id) WHERE {current_bills}")
    month_receivable = one(f"SELECT coalesce(sum(net), 0) FROM bills AS b LEFT JOIN properties AS h USING (property_id) "
                           f"WHERE b.period = getvariable('as_of_month') AND {where_bill}")[0]
    arrears_billed = one(f"SELECT coalesce(sum(net), 0) FROM bills AS b LEFT JOIN properties AS h USING (property_id) "
                         f"WHERE b.period < getvariable('year_start') AND {where_bill}")[0]
    sums = dict(connection.execute(
        f"SELECT place || CASE WHEN date < getvariable('year_start') THEN ':before' ELSE ':within' END, sum(amount) "
        f"FROM placed AS b LEFT JOIN properties AS h USING (property_id) WHERE {where_receipt} GROUP BY 1").fetchall())
    month_collected = one(f"SELECT coalesce(sum(amount), 0) FROM placed AS b LEFT JOIN properties AS h USING (property_id) "
                          f"WHERE b.place = 'current' AND b.period = getvariable('as_of_month') AND {where_receipt}")[0]
    settled = one(f"""
        WITH owed AS (SELECT property_id, sum(net) AS net FROM bills AS b LEFT JOIN properties AS h USING (property_id)
                      WHERE {current_bills} GROUP BY property_id HAVING sum(net) > 0),
             paid AS (SELECT property_id, sum(amount) AS paid FROM placed AS b LEFT JOIN properties AS h USING (property_id)
                      WHERE b.place = 'current' AND {where_receipt} GROUP BY property_id)
        SELECT count(*), count(*) FILTER (WHERE coalesce(paid, 0) >= net) FROM owed LEFT JOIN paid USING (property_id)""")
    got = lambda key: sums.get(key) or Decimal(0)  # noqa: E731
    collected = got("current:before") + got("current:within")
    arrears_opening = arrears_billed - got("arrears:before")
    arrears_collected = got("arrears:within")
    advance = got("advance:before") + got("advance:within") + got("unmatched:before") + got("unmatched:within")
    if params["total_method"] == "bounded":
        total = _rate(collected + arrears_collected, receivable + arrears_opening)
    else:
        within = sum((value or Decimal(0)) for key, value in sums.items() if key.endswith(":within"))
        total = _rate(within, receivable)
    return {
        "receivable": _money(receivable), "collected": _money(collected),
        "collection_rate_current": _rate(collected, receivable),
        "month_receivable": _money(month_receivable), "month_collected": _money(month_collected),
        "collection_rate_month": _rate(month_collected, month_receivable),
        "arrears_opening": _money(arrears_opening), "arrears_collected": _money(arrears_collected),
        "arrears_recovery_rate": _rate(arrears_collected, arrears_opening),
        "collection_rate_total": total,
        "outstanding": _money(receivable - collected + arrears_opening - arrears_collected),
        "advance_balance": _money(advance),
        "waiver": _money(waiver), "waiver_rate": _rate(waiver, gross) if gross is not None else None,
        "households": settled[0], "households_settled": settled[1], "household_rate": _rate(Decimal(settled[1]), Decimal(settled[0])),
        "properties_billed": households,
    }


def _money(value: Any) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _rate(numerator: Any, denominator: Any) -> str | None:
    numerator, denominator = Decimal(numerator or 0), Decimal(denominator or 0)
    if denominator == 0:
        return None
    return str((numerator / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _lines(connection, metas: dict, kind: str, sql: str) -> list[str]:
    """Where to look, as 「file name 第 n 行」, for the first few rows a finding is about."""
    files = metas[kind]["files"]
    return [f"{files[file]['name']} 第 {line} 行" for file, line in connection.execute(f"{sql} ORDER BY file, line LIMIT {SAMPLE_LINES}").fetchall()]


def _issue(connection, metas, kind: str, code: str, where: str, amount: str, view: str) -> dict | None:
    count, total = connection.execute(f"SELECT count(*), coalesce(sum({amount}), 0) FROM {view} WHERE {where}").fetchone()
    if not count:
        return None
    return {"code": code, "rows": count, "amount": _money(total),
            "lines": _lines(connection, metas, kind, f"SELECT file, line FROM {view} WHERE {where}")}


def _compute(connection, metas: dict, params: dict) -> dict:
    as_of = params["as_of"]
    year, month = int(as_of[:4]), int(as_of[5:7])
    start_year = year if month >= params["year_start_month"] else year - 1
    connection.execute(f"SET VARIABLE as_of = DATE '{as_of}'")
    connection.execute(f"SET VARIABLE as_of_month = DATE '{as_of[:7]}-01'")
    connection.execute(f"SET VARIABLE year_start = DATE '{start_year}-{params['year_start_month']:02d}-01'")
    _prepare(connection, metas, params)
    has_property = "property" in metas
    main_bill = "NOT coalesce(h.related, false)" if params["exclude_related"] else "true"
    figures = _figures(connection, main_bill, main_bill, params)
    for key, value in params["reported"].items():
        mine = figures.get(key)
        figures.setdefault("reported", {})[key] = {
            "reported": value, "computed": mine,
            "difference_points": None if mine is None else str(((Decimal(mine) - Decimal(value)) * 100).quantize(Decimal("0.01"))),
        }
    result: dict[str, Any] = {
        "window": {"year_start": f"{start_year}-{params['year_start_month']:02d}", "as_of": as_of, "as_of_period": as_of[:7]},
        "figures": figures,
    }
    if has_property and "owner" in metas["property"]["confirmation"]["mapping"]:
        result["related"] = {"owners": params["related_owners"],
                             "only": _figures(connection, "coalesce(h.related, false)", "coalesce(h.related, false)", params),
                             "excluded": _figures(connection, "NOT coalesce(h.related, false)", "NOT coalesce(h.related, false)", params)}
    if params["group_by"]:
        dims = [f"{'h' if GROUP_FIELDS[field] == 'property' else 'b'}.{field}" for field in params["group_by"]]
        keys = connection.execute(
            f"SELECT DISTINCT {', '.join(dims)} FROM bills AS b LEFT JOIN properties AS h USING (property_id) "
            f"WHERE b.period BETWEEN getvariable('year_start') AND getvariable('as_of_month') ORDER BY ALL").fetchall()
        groups = []
        for key in keys:
            condition = " AND ".join(f"{dim} IS NOT DISTINCT FROM {_literal(value)}" for dim, value in zip(dims, key))
            groups.append({"key": dict(zip(params["group_by"], key)),
                           "figures": _figures(connection, f"{main_bill} AND {condition}", f"{main_bill} AND {condition}", params)})
        result["groups"] = groups
    result["quality"] = [issue for issue in (
        _issue(connection, metas, "receivable", "void_bills", "void", "net", "bill_lines"),
        _issue(connection, metas, "receivable", "red_letter_lines", "red", "net", "bill_lines"),
        _issue(connection, metas, "receivable", "unreadable_bill_lines", "NOT void AND (bill_id IS NULL OR period IS NULL OR net IS NULL)",
               "0", "bill_lines"),
        _issue(connection, metas, "receipt", "unreadable_receipts", "date IS NULL OR amount IS NULL", "0", "receipts"),
        _issue(connection, metas, "receipt", "receipts_without_bill", "place = 'unmatched'", "amount", "placed"),
        _issue(connection, metas, "receivable", "bills_without_property",
               "NOT void AND property_id NOT IN (SELECT property_id FROM properties WHERE property_id IS NOT NULL)", "net", "bill_lines")
        if has_property else None,
    ) if issue]
    if "nature" in metas["receipt"]["confirmation"]["mapping"]:
        # What the billing system called a receipt, against where its bill's 账期 puts it.
        result["labels"] = [issue for issue in (
            _issue(connection, metas, "receipt", "advance_labelled_current", "place = 'advance' AND contains(nature, '当期')", "amount", "placed"),
            _issue(connection, metas, "receipt", "arrears_labelled_current", "place = 'arrears' AND date >= getvariable('year_start') AND contains(nature, '当期')", "amount", "placed"),
        ) if issue]
    return result


def _literal(value: Any) -> str:
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


# --- the CLI ----------------------------------------------------------------------------------

COMMANDS = {"detail-add", "detail-list", "detail-read", "detail-propose", "detail-confirm", "collection-run", "collection-run-read"}


def add_parsers(sub) -> None:
    p = sub.add_parser("detail-add", help="收费明细: one table from one or more CSV files, into DuckDB")
    p.add_argument("--kind", choices=sorted(FIELDS), required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--path", action="append", required=True)
    sub.add_parser("detail-list")
    p = sub.add_parser("detail-read")
    p.add_argument("--detail", required=True)
    for command in ("detail-propose", "detail-confirm"):
        p = sub.add_parser(command)
        p.add_argument("--detail", required=True)
        p.add_argument("--mapping", required=command == "detail-propose", help="JSON: standard field -> column name")
    p = sub.add_parser("collection-run", help="当期收缴率、清欠率、综合收缴率 from confirmed detail tables")
    p.add_argument("--spec", required=True)
    p = sub.add_parser("collection-run-read")
    p.add_argument("--run", required=True)


def dispatch(args) -> bool:
    if args.cmd not in COMMANDS:
        return False
    from foundry.context import resolve_context

    context = resolve_context(Path(args.var), session_id=args.session or None, task_id=args.task or None)
    if context.task is None:
        raise FoundryError("detail tables belong to a task")
    store = BillingDetailStore(context.task, actor=getattr(args, "actor", "") or None)
    if args.cmd == "detail-add":
        if context.session_id:
            raise FoundryError("detail tables are added from the window, not from a session")
        result = store.add(args.kind, [Path(path).expanduser() for path in args.path], name=args.name)
    elif args.cmd == "detail-list":
        result = store.list()
    elif args.cmd == "detail-read":
        result = store.get(args.detail)
    elif args.cmd == "detail-propose":
        result = store.propose(args.detail, _object(args.mapping, "mapping"))
    elif args.cmd == "detail-confirm":
        result = store.confirm(args.detail, None if args.mapping is None else _object(args.mapping, "mapping"))
    elif args.cmd == "collection-run":
        result = store.collection_run(_object(args.spec, "collection spec"))
    else:
        if not re.fullmatch(r"[0-9a-f]{32}", str(args.run)):
            raise FoundryError("run id must be 32 hex characters")
        path = store.root / "runs" / f"{args.run}.json"
        if not path.is_file():
            raise FoundryError(f"no collection run {args.run}")
        result = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False))
    return True


def _object(text: str, label: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FoundryError(f"{label} must be JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise FoundryError(f"{label} must be a JSON object")
    return value
