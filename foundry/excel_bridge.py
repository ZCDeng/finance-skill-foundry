"""Local HTTPS bridge for the Office.js Excel taskpane.

The bridge is intentionally small: Office.js owns workbook selection, binding,
recalculation, and save; foundry owns immutable snapshots, finance contexts,
metric runs, and authorization. Browser requests never name local filesystem
paths and never send code for execution.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hmac
import json
import mimetypes
import os
import re
import ssl
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from foundry.analysis import AnalysisStore, _hash
from foundry.analysis_data import json_value
from foundry.context import resolve_context
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.sheet import survives_a_cell
from foundry.task import Task, TaskStore, now_iso

BRIDGE_SCHEMA = 1
DEFAULT_PORT = 8765
STATIC_FILES = {
    "/": "taskpane.html",
    "/taskpane.html": "taskpane.html",
    "/taskpane.js": "taskpane.js",
    "/taskpane.css": "taskpane.css",
    "/manifest.xml": "manifest.xml",
    "/icon.png": "icon.png",
    "/icon.svg": "icon.svg",
}
RESOURCE_PACKAGE = "foundry"
ROLES = {"input", "output"}
RESOLUTIONS = {"apply", "keep"}
MAX_BINDINGS = 64
MAX_FIELDS = 256
MAX_ROWS = 100_000
MAX_CELLS = 20_000
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_TELEMETRY = 500
A1 = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})$")
ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf8")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FoundryError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str, *, maximum: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise FoundryError(f"{label} must be nonempty text")
    return value.strip()


def _safe_id(value: Any, label: str) -> str:
    text = _require_text(value, label, maximum=128)
    if not all(c.isalnum() or c in "._-" for c in text):
        raise FoundryError(f"{label} contains unsupported characters")
    return text


def _safe_alias(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().replace("-", "_")
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    if not text or not text[0].isalpha():
        text = fallback
    if not ALIAS.fullmatch(text):
        raise FoundryError(f"invalid binding alias: {text}")
    return text


def _cell_hash(cell: dict[str, Any]) -> str:
    return _hash(
        {
            "address": cell.get("address"),
            "value": cell.get("value"),
            "valueType": cell.get("valueType"),
            "numberFormat": cell.get("numberFormat"),
            "formula": cell.get("formula"),
        }
    )


def _column_index(letters: str) -> int:
    value = 0
    for char in letters.upper():
        value = value * 26 + ord(char) - 64
    return value


def _split_address(address: str) -> tuple[str | None, str]:
    if "!" not in address:
        return None, address.replace("$", "")
    sheet, cell = address.rsplit("!", 1)
    return sheet.strip("'"), cell.replace("$", "")


def _parse_cell(cell: str) -> tuple[int, int]:
    match = A1.fullmatch(cell)
    if not match:
        raise FoundryError(f"invalid cell address: {cell}")
    return _column_index(match.group(1)), int(match.group(2))


def _address_in_binding(address: str, binding: dict[str, Any]) -> bool:
    sheet, cell = _split_address(address)
    bound_sheet, bound_range = _split_address(binding["address"])
    if sheet and sheet != binding["worksheet"]:
        return False
    if bound_sheet and bound_sheet != binding["worksheet"]:
        return False
    start, end = (bound_range.split(":", 1) + [bound_range])[:2]
    col, row = _parse_cell(cell)
    min_col, min_row = _parse_cell(start)
    max_col, max_row = _parse_cell(end)
    if min_col > max_col:
        min_col, max_col = max_col, min_col
    if min_row > max_row:
        min_row, max_row = max_row, min_row
    return min_col <= col <= max_col and min_row <= row <= max_row


def _normalize_field(field: Any) -> dict[str, str]:
    field = _require_object(field, "field")
    name = _require_text(field.get("name"), "field name", maximum=128)
    policy = str(field.get("policy") or field.get("type") or "text")
    if policy not in {"text", "identifier", "long_identifier", "amount", "decimal", "normal_amount", "date", "boolean"}:
        raise FoundryError(f"unsupported field policy: {policy}")
    return {
        "name": name,
        "policy": policy,
        "type": "decimal" if policy in {"amount", "decimal", "normal_amount"} else "text",
        "unit": str(field.get("unit") or ""),
    }


def _normalize_binding(binding: Any) -> dict[str, Any]:
    binding = _require_object(binding, "binding")
    role = str(binding.get("role") or "input")
    if role not in ROLES:
        raise FoundryError("binding role must be input or output")
    fields = [_normalize_field(field) for field in binding.get("fields") or []]
    if not fields or len(fields) > MAX_FIELDS:
        raise FoundryError("binding requires 1-256 fields")
    if len({field["name"].casefold() for field in fields}) != len(fields):
        raise FoundryError("binding field names must be unique")
    headers = binding.get("headers") or [field["name"] for field in fields]
    if not isinstance(headers, list) or not all(isinstance(v, str) for v in headers):
        raise FoundryError("binding headers must be text")
    address = _require_text(binding.get("address"), "binding address", maximum=512)
    baseline_cells = binding.get("baseline_cells") or {}
    if not isinstance(baseline_cells, dict) or len(baseline_cells) > MAX_CELLS:
        raise FoundryError("baseline cells must be a bounded object")
    baseline_hashes = {}
    for address_key, cell in baseline_cells.items():
        address_text = _require_text(address_key, "baseline address", maximum=64)
        baseline_hashes[address_text] = _cell_hash(_require_object(cell, "baseline cell"))
    return {
        "id": _safe_id(binding.get("id"), "binding id"),
        "name": _require_text(binding.get("name") or binding.get("id"), "binding name", maximum=200),
        "role": role,
        "writable": bool(binding.get("writable")) and role == "output",
        "address": address,
        "worksheet": _require_text(binding.get("worksheet"), "worksheet", maximum=128),
        "binding_type": str(binding.get("binding_type") or "matrix"),
        "headers": headers,
        "fields": fields,
        "header": bool(binding.get("header", True)),
        "dedicated_area": bool(binding.get("dedicated_area", role == "output")),
        "baseline_hashes": baseline_hashes,
        "created_at": now_iso(),
    }


def _decimal_cell(value: Any, field: dict[str, Any]) -> tuple[Any, str, str]:
    if value is None or value == "":
        return None, "empty", "General"
    if field["type"] != "decimal":
        text = str(value)
        literal = text.startswith(("=", "+", "-", "@")) or bool(re.fullmatch(r"0[0-9]+", text))
        return text, "text", "@" if literal else "General"
    if isinstance(value, bool):
        raise FoundryError("boolean is not a decimal value")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"invalid decimal value: {value}") from exc
    if not amount.is_finite():
        raise FoundryError("non-finite numeric value")
    if survives_a_cell(amount):
        return int(amount) if amount == amount.to_integral_value() else float(amount), "number", "General"
    return format(amount, "f"), "text", "@"


def _rows_from_grid(binding: dict[str, Any], values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or len(values) > MAX_ROWS + 1:
        raise FoundryError("binding values must be a bounded matrix")
    if not all(isinstance(row, list) for row in values):
        raise FoundryError("binding values must be a matrix")
    start = 1 if binding.get("header", True) else 0
    headers = [str(v or "").strip() for v in (values[0] if start and values else binding["headers"])]
    if len(headers) > MAX_FIELDS:
        raise FoundryError("binding has too many columns")
    field_names = [field["name"] for field in binding["fields"]]
    positions = []
    lowered = {name.casefold(): index for index, name in enumerate(headers)}
    for name in field_names:
        if name.casefold() not in lowered:
            raise FoundryError(f"binding header missing field: {name}")
        positions.append(lowered[name.casefold()])
    rows: list[dict[str, Any]] = []
    for raw in values[start:]:
        if len(raw) > MAX_FIELDS:
            raise FoundryError("binding row has too many columns")
        if not any(value not in (None, "") for value in raw):
            continue
        rows.append({name: (raw[pos] if pos < len(raw) else None) for name, pos in zip(field_names, positions)})
    return rows


@dataclass(frozen=True)
class BridgeTokenAuthority:
    secret: bytes

    def issue(self, *, task_id: str, session_id: str, ttl_seconds: int = 3600) -> str:
        if ttl_seconds <= 0:
            raise FoundryError("token ttl must be positive")
        payload = {
            "schema_version": BRIDGE_SCHEMA,
            "task_id": task_id,
            "session_id": session_id,
            "expires_at": int(time.time()) + ttl_seconds,
            "nonce": uuid.uuid4().hex,
        }
        body = _b64(_json_bytes(payload))
        signature = _b64(hmac.new(self.secret, body.encode("ascii"), sha256).digest())
        return f"{body}.{signature}"

    def verify(self, token: str) -> dict[str, Any]:
        try:
            body, signature = token.split(".", 1)
        except ValueError as exc:
            raise FoundryError("invalid bridge token") from exc
        expected = _b64(hmac.new(self.secret, body.encode("ascii"), sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise FoundryError("invalid bridge token")
        try:
            payload = json.loads(_unb64(body).decode("utf8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise FoundryError("invalid bridge token") from exc
        if payload.get("schema_version") != BRIDGE_SCHEMA:
            raise FoundryError("invalid bridge token")
        if int(payload.get("expires_at") or 0) < int(time.time()):
            raise FoundryError("bridge token expired")
        _require_text(payload.get("task_id"), "token task id", maximum=64)
        _require_text(payload.get("session_id"), "token session id", maximum=200)
        return payload


class ExcelBridgeApp:
    def __init__(self, *, var_root: Path, token_authority: BridgeTokenAuthority, static_root: Path | None = None):
        self.var_root = Path(var_root)
        self.token_authority = token_authority
        self.static_root = static_root or Path(__file__).resolve().parent.parent / "excel-addin"

    def handle(self, method: str, target: str, headers: dict[str, str] | None = None, body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
        headers = headers or {}
        try:
            parsed = urlparse(target)
            if parsed.path.startswith("/api/"):
                return self._json_response(self._api(method, parsed.path, headers, body))
            if method != "GET":
                raise FoundryError("static assets are read-only")
            return self._static(parsed.path, parse_qs(parsed.query))
        except FoundryError as exc:
            return self._json_response({"error": {"code": "refused", "message": str(exc)}}, HTTPStatus.BAD_REQUEST)
        except Exception:  # pragma: no cover - last-resort server boundary
            return self._json_response({"error": {"code": "internal_error", "message": "internal bridge error"}}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _json_response(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> tuple[int, dict[str, str], bytes]:
        data = _json_bytes(payload)
        return int(status), {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}, data

    def _static_bytes(self, name: str) -> tuple[bytes, str]:
        try:
            resource = resources.files(RESOURCE_PACKAGE).joinpath("resources", "excel-addin", name)
            if resource.is_file():
                return resource.read_bytes(), name
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            pass
        source = (self.static_root / name).resolve()
        if not source.is_relative_to(self.static_root.resolve()) or not source.is_file():
            raise FoundryError("static asset unavailable")
        return source.read_bytes(), source.name

    def _static(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, str], bytes]:
        name = STATIC_FILES.get(path)
        if not name:
            raise FoundryError("unknown static asset")
        if name == "manifest.xml":
            port = int((query.get("port") or [DEFAULT_PORT])[0])
            data = generate_manifest(port=port).encode("utf8")
            content_type = "application/xml; charset=utf-8"
        else:
            data, source_name = self._static_bytes(name)
            content_type = mimetypes.guess_type(source_name)[0] or "application/octet-stream"
        return int(HTTPStatus.OK), {"Content-Type": content_type, "Cache-Control": "no-store"}, data

    def _api(self, method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        token = self._bearer(headers)
        context = self._context(token)
        payload = self._body(body)
        if method == "GET" and path == "/api/context":
            return self._context_payload(context)
        if method == "POST" and path == "/api/register-workbook":
            return self._register_workbook(context, payload)
        if method == "POST" and path == "/api/telemetry":
            assert context.task is not None
            return {"telemetry": self._record_telemetry(context, payload)}
        if method == "POST" and path == "/api/register-bindings":
            return self._register_bindings(context, payload)
        if method == "POST" and path == "/api/import-binding":
            return self._import_binding(context, payload)
        if method == "POST" and path == "/api/run-metric":
            return self._run_metric(context, payload)
        if method == "POST" and path == "/api/preview-output":
            return self._preview_output(context, payload)
        if method == "POST" and path == "/api/apply-output":
            return self._apply_output(context, payload)
        if method == "POST" and path == "/api/ack-output":
            return self._ack_output(context, payload)
        raise FoundryError("unknown bridge endpoint")

    def _bearer(self, headers: dict[str, str]) -> str:
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        if not auth.startswith("Bearer "):
            raise FoundryError("bridge token is required")
        return auth.removeprefix("Bearer ").strip()

    def _body(self, body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        if len(body) > MAX_BODY_BYTES:
            raise FoundryError("request body is too large")
        try:
            return _require_object(json.loads(body.decode("utf8")), "request body")
        except (UnicodeDecodeError, ValueError) as exc:
            raise FoundryError("request body must be JSON") from exc

    def _context(self, token: str):
        payload = self.token_authority.verify(token)
        context = resolve_context(self.var_root, task_id=payload["task_id"], session_id=payload["session_id"])
        if context.task is None or context.task.id != payload["task_id"]:
            raise FoundryError("bridge token task does not match context")
        return context

    def _finance(self, task: Task, context):
        from foundry.finance_service import FinanceStore

        return FinanceStore(
            task,
            snapshot_ids=context.snapshot_ids,
            session_id=context.session_id,
            context_revision=context.context_revision,
        )

    def _state_path(self, task: Task) -> Path:
        path = task.root / "analysis" / "excel_bridge" / "state.json"
        if not path.resolve().is_relative_to(task.root.resolve()):
            raise FoundryError("bridge state path escapes task")
        return path

    def _empty_state(self, task: Task) -> dict[str, Any]:
        return {
            "schema_version": BRIDGE_SCHEMA,
            "task_id": task.id,
            "workbooks": {},
            "telemetry": [],
        }

    def _read_state(self, task: Task) -> dict[str, Any]:
        path = self._state_path(task)
        if not path.exists():
            return self._empty_state(task)
        try:
            state = json.loads(path.read_text(encoding="utf8"))
        except ValueError as exc:
            raise FoundryError("bridge state is invalid") from exc
        if state.get("schema_version") != BRIDGE_SCHEMA:
            raise FoundryError("bridge state version is unsupported")
        digest = state.pop("_integrity_hash", None)
        if state.get("task_id") != task.id or digest != _hash(state):
            raise FoundryError("bridge state integrity check failed")
        state.setdefault("workbooks", {})
        state.setdefault("telemetry", [])
        return state

    def _write_state(self, task: Task, state: dict[str, Any]) -> None:
        state = json_value(state)
        state["schema_version"] = BRIDGE_SCHEMA
        state["task_id"] = task.id
        state.setdefault("workbooks", {})
        state.setdefault("telemetry", [])
        with exclusive(task.lock_path, timeout=10):
            record = dict(state)
            record["_integrity_hash"] = _hash(record)
            write_json_atomic(self._state_path(task), record)


    def _default_workbook(self, workbook_id: str) -> dict[str, Any]:
        return {
            "id": workbook_id,
            "name": "",
            "url_hash": "",
            "created_at": now_iso(),
            "host": {},
            "bindings": {},
            "preauthorized_areas": {},
            "input_snapshots": {},
            "previews": {},
        }

    def _workbook_id(self, payload: dict[str, Any], *, required: bool = True) -> str:
        value = payload.get("workbook_id")
        if not value and not required:
            return "unbound"
        return _safe_id(value, "workbook id")

    def _workbook(self, state: dict[str, Any], context, workbook_id: str, *, create: bool = False) -> dict[str, Any]:
        """The calling session's record of this workbook, placed in ``state`` so that writing ``state`` keeps it.

        The workbook id lives in the workbook's own document settings, so every session that opens one file sends
        the same id. Each session keeps its own record, under "<session id>/<workbook id>" (a workbook id never
        holds "/"), and a workbook it has no record of is refused as one never registered. A record under the bare
        workbook id was written before records were kept per session (_unowned_workbook)."""
        key = self._workbook_key(context, workbook_id)
        workbook = state["workbooks"].get(key) or self._unowned_workbook(state, context, workbook_id)
        if not workbook:
            if not create:
                raise FoundryError("workbook is not registered")
            workbook = self._default_workbook(workbook_id)
        state["workbooks"][key] = workbook
        return workbook

    def _workbook_key(self, context, workbook_id: str) -> str:
        return f"{context.session_id}/{workbook_id}"

    def _unowned_workbook(self, state: dict[str, Any], context, workbook_id: str) -> dict[str, Any] | None:
        """The calling session's share of the record under the bare workbook id, which every session that opened the
        file wrote into before records were kept per session: the imports it filed there itself and may read, with
        their input bindings, in a record of its own. The rest names no owner and stays behind: the name, address
        and host the last session registered, output bindings with their areas and baselines, and previews. A
        record holding none of the session's imports is none of its own. The share is a copy and the bare record is
        never rewritten, so each session that filed into it takes up its own."""
        workbook = state["workbooks"].get(workbook_id)
        if not workbook:
            return None
        allowed = set(context.snapshot_ids)
        inputs = {key: row for key, row in (workbook.get("input_snapshots") or {}).items()
                  if row.get("dataset_id") in allowed and self._filed_by_session(context, row.get("dataset_id"))}
        if not inputs:
            return None
        bindings = {key: row for key, row in (workbook.get("bindings") or {}).items()
                    if key in inputs and row.get("role") == "input"}
        return copy.deepcopy({**self._default_workbook(workbook_id), "bindings": bindings, "input_snapshots": inputs})

    def _filed_by_session(self, context, dataset_id: Any) -> bool:
        """Whether the calling session's own import filed this dataset: each import writes its upload into the
        session's folder (_upload_path) and the dataset keeps that file's name as its source_name."""
        try:
            analysis = AnalysisStore(context.task)
            meta = analysis._read(analysis.root / "datasets" / _safe_id(dataset_id, "dataset id") / "meta.json")
            upload = self._upload_path(context.task, context.session_id, Path(str(meta.get("source_name") or "")).stem)
        except FoundryError:
            return False
        return upload.is_file()

    def _session_workbooks(self, state: dict[str, Any], context) -> list[dict[str, Any]]:
        """Every workbook the calling session has a record of (_workbook), by id."""
        found = []
        for workbook_id in {key.rpartition("/")[2] for key in state["workbooks"]}:
            workbook = state["workbooks"].get(self._workbook_key(context, workbook_id)) or self._unowned_workbook(
                state, context, workbook_id)
            if workbook:
                found.append(workbook)
        return sorted(found, key=lambda row: row["id"])

    def _record_telemetry(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex,
            "at": now_iso(),
            "session_id": context.session_id,
            "event": _require_text(payload.get("event"), "telemetry event", maximum=100),
            "workbook_id": str(payload.get("workbook_id") or ""),
            "host": _require_object(payload.get("host") or {}, "host"),
            "details": _require_object(payload.get("details") or {}, "telemetry details"),
        }
        state = self._read_state(context.task)
        state.setdefault("telemetry", []).append(event)
        # Each session keeps its own latest events: another session's never push them out. Events written before
        # they named their session stay for the operator's tools, bounded as they were.
        mine = [row for row in state["telemetry"] if row.get("session_id") == context.session_id]
        dropped = {row["id"] for row in mine[:-MAX_TELEMETRY]}
        state["telemetry"] = [row for row in state["telemetry"] if row.get("id") not in dropped]
        self._write_state(context.task, state)
        return event

    def _register_workbook(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None
        workbook_id = self._workbook_id(payload)
        state = self._read_state(context.task)
        workbook = self._workbook(state, context, workbook_id, create=True)
        workbook["name"] = str(payload.get("name") or workbook.get("name") or "")
        if payload.get("url"):
            workbook["url_hash"] = sha256(str(payload.get("url") or "").encode("utf8")).hexdigest()
        workbook["host"] = _require_object(payload.get("host") or workbook.get("host") or {}, "host")
        workbook.setdefault("bindings", {})
        workbook.setdefault("preauthorized_areas", {})
        workbook.setdefault("input_snapshots", {})
        workbook.setdefault("previews", {})
        self._write_state(context.task, state)
        return {"workbook": workbook}

    def _authorized_finance_runs(self, task: Task, context) -> list[dict[str, Any]]:
        allowed = set(context.snapshot_ids)
        runs = []
        # As the session reads them (AnalysisStore.run_in_view): a requirements version outside it pins none of them.
        for run in AnalysisStore(task).state(allowed)["runs"]:
            if (
                run.get("engine") == "finance"
                and run.get("execution_status") == "succeeded"
                and set((run.get("bindings") or {}).values()) <= allowed
            ):
                runs.append(run)
        return runs

    def _context_payload(self, context) -> dict[str, Any]:
        assert context.task is not None
        state = self._read_state(context.task)
        finance = self._finance(context.task, context).list_finance_context()
        finance["runs"] = self._authorized_finance_runs(context.task, context)
        return {
            "task_id": context.task.id,
            "session_id": context.session_id,
            "context_revision": context.context_revision,
            "snapshot_ids": list(context.snapshot_ids),
            "workbooks": self._session_workbooks(state, context),
            "telemetry": [event for event in state.get("telemetry", []) if event.get("session_id") == context.session_id][-50:],
            "finance": finance,
        }

    def _register_bindings(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None
        workbook_id = self._workbook_id(payload)
        bindings = payload.get("bindings")
        if not isinstance(bindings, list) or not bindings or len(bindings) > MAX_BINDINGS:
            raise FoundryError("bindings must be a nonempty bounded array")
        state = self._read_state(context.task)
        workbook = self._workbook(state, context, workbook_id, create=True)
        for raw in bindings:
            binding = _normalize_binding(raw)
            workbook["bindings"][binding["id"]] = binding
            if binding["role"] == "output" and binding["dedicated_area"]:
                workbook["preauthorized_areas"][binding["id"]] = {
                    "binding_id": binding["id"],
                    "address": binding["address"],
                    "worksheet": binding["worksheet"],
                    "fields": binding["fields"],
                    "authorized_at": now_iso(),
                }
        self._write_state(context.task, state)
        return {"workbook": workbook, "bindings": sorted(workbook["bindings"].values(), key=lambda row: row["id"])}

    def _binding(self, context, workbook_id: str, binding_id: str, *, role: str | None = None) -> dict[str, Any]:
        workbook = self._workbook(self._read_state(context.task), context, workbook_id)
        binding = workbook.get("bindings", {}).get(_safe_id(binding_id, "binding id"))
        if not binding:
            raise FoundryError("binding is not registered")
        if role and binding["role"] != role:
            raise FoundryError(f"binding must be {role}")
        return binding

    def _upload_path(self, task: Task, session_id: str, name: str) -> Path:
        folder = task.root / "analysis" / ".excel-bridge-uploads" / _safe_id(session_id, "session id")
        path = folder / f"{_safe_id(name, 'upload name')}.json"
        if not path.resolve().is_relative_to(task.root.resolve()):
            raise FoundryError("upload path escapes task")
        return path

    def _import_binding(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None and context.session_id is not None
        if any(row.get("session_id") == context.session_id and row.get("parent_session_id") for row in context.task.sessions()):
            raise FoundryError("a child session cannot import new Excel snapshots")
        workbook_id = self._workbook_id(payload)
        binding = _normalize_binding(payload["binding"]) if "binding" in payload else self._binding(context, workbook_id, payload.get("binding_id"), role="input")
        if binding["role"] != "input":
            raise FoundryError("only input bindings can be imported")
        rows = _rows_from_grid(binding, payload.get("values"))
        dataset_payload = {"rows": rows}
        digest = _hash({"binding": binding, "rows": rows, "at": now_iso()})[:16]
        path = self._upload_path(context.task, context.session_id, f"{binding['id']}-{digest}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_json_bytes(dataset_payload))
        analysis = AnalysisStore(context.task)
        dataset = analysis.add_dataset(
            path,
            name=str(payload.get("name") or binding["name"]),
            metadata={
                "source": "officejs-binding",
                "binding_id": binding["id"],
                "binding_address": binding["address"],
                "worksheet": binding["worksheet"],
            },
            allowed=set(context.snapshot_ids),
        )
        state = self._read_state(context.task)
        workbook = self._workbook(state, context, workbook_id, create=True)
        workbook["bindings"][binding["id"]] = binding
        alias = _safe_alias(payload.get("alias") or binding["id"], "actual")
        scope = _require_object(payload.get("scope") or {}, "scope")
        policy = _require_object(payload.get("policy") or {}, "policy")
        workbook["input_snapshots"][binding["id"]] = {
            "alias": alias,
            "dataset_id": dataset["id"],
            "binding_id": binding["id"],
            "imported_at": now_iso(),
            "scope": scope,
            "policy": policy,
        }
        # The session's own record holds only imports it filed: nothing another session imported joins its context.
        latest_snapshot_ids = [row["dataset_id"] for row in workbook["input_snapshots"].values()]
        merged_snapshot_ids = list(dict.fromkeys([*context.snapshot_ids, *latest_snapshot_ids]))
        updated = context.task.update_session_context(context.session_id, snapshot_ids=merged_snapshot_ids)
        self._write_state(context.task, state)
        refreshed = resolve_context(self.var_root, task_id=context.task.id, session_id=context.session_id)
        finance = self._finance(context.task, refreshed)
        finance_bindings = {row["alias"]: row["dataset_id"] for row in workbook["input_snapshots"].values()}
        if len(set(finance_bindings.values())) != len(finance_bindings):
            raise FoundryError("finance context requires distinct latest input snapshots")
        finance_context = finance.save_context(
            {
                "name": str(payload.get("context_name") or f"{binding['name']} finance context"),
                "bindings": finance_bindings,
                "scopes": {row["alias"]: row.get("scope") or {} for row in workbook["input_snapshots"].values()},
                "policies": {row["alias"]: row.get("policy") or {} for row in workbook["input_snapshots"].values()},
            }
        )
        return {"dataset": dataset, "session": updated, "finance_context": finance_context, "binding": binding, "workbook": workbook}

    def _run_metric(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None
        spec = _require_object(payload.get("spec") or payload, "metric spec")
        if "context_id" not in spec:
            contexts = self._finance(context.task, context).list_finance_context()["contexts"]
            if not contexts:
                raise FoundryError("no finance context is available")
            spec = {**spec, "context_id": contexts[-1]["id"]}
        metric = spec.get("metric")
        if not isinstance(metric, dict):
            raise FoundryError("metric spec requires metric object")
        return {"run": self._finance(context.task, context).run_metric(spec)}

    def _preview_output(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None
        workbook_id = self._workbook_id(payload)
        binding = self._binding(context, workbook_id, payload.get("binding_id"), role="output")
        if not binding.get("writable") or not binding.get("dedicated_area"):
            raise FoundryError("output binding must be a writable dedicated area")
        writes = payload.get("writes")
        if not isinstance(writes, list) or len(writes) > MAX_CELLS:
            raise FoundryError("writes must be a bounded array")
        current = payload.get("current_cells")
        if not isinstance(current, dict):
            raise FoundryError("current_cells must map addresses to cell snapshots")
        allowed_fields = {field["name"] for field in binding["fields"]}
        cells = []
        for write in writes:
            write = _require_object(write, "write")
            address = _require_text(write.get("address"), "write address", maximum=64)
            field = _require_text(write.get("field"), "write field", maximum=128)
            if field not in allowed_fields:
                raise FoundryError(f"write field is outside output binding: {field}")
            if not _address_in_binding(address, binding):
                raise FoundryError(f"write target outside output binding: {address}")
            if address not in current:
                raise FoundryError(f"current cell snapshot is missing: {address}")
            baseline = str(binding.get("baseline_hashes", {}).get(address) or "")
            current_hash = _cell_hash(_require_object(current[address], "current cell"))
            conflict = bool(baseline and baseline != current_hash)
            field_def = next(item for item in binding["fields"] if item["name"] == field)
            new_value, cell_type, number_format = _decimal_cell(write.get("value"), field_def)
            cells.append(
                {
                    "address": address,
                    "field": field,
                    "old_value": current[address].get("value"),
                    "new_value": new_value,
                    "cell_type": cell_type,
                    "number_format": number_format,
                    "baseline_hash": baseline,
                    "current_hash": current_hash,
                    "conflict": conflict,
                }
            )
        preview = {
            "schema_version": BRIDGE_SCHEMA,
            "id": uuid.uuid4().hex,
            "workbook_id": workbook_id,
            "binding_id": binding["id"],
            "binding_address": binding["address"],
            "created_at": now_iso(),
            "cells": cells,
            "conflicts": [cell for cell in cells if cell["conflict"]],
            "output_hash": payload.get("output_hash"),
        }
        state = self._read_state(context.task)
        self._workbook(state, context, workbook_id)["previews"][preview["id"]] = preview
        self._write_state(context.task, state)
        return {"preview": preview}

    def _apply_output(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None
        state = self._read_state(context.task)
        workbook_id = self._workbook_id(payload)
        current = payload.get("current_cells")
        if not isinstance(current, dict):
            raise FoundryError("current_cells must map addresses to cell snapshots")
        preview_id = _safe_id(payload.get("preview_id"), "preview id")
        workbook = self._workbook(state, context, workbook_id)
        preview = workbook.get("previews", {}).get(preview_id)
        if not preview:
            raise FoundryError("preview is unavailable")
        if payload.get("binding_id") and payload.get("binding_id") != preview["binding_id"]:
            raise FoundryError("binding changed since preview")
        binding = self._binding(context, workbook_id, preview["binding_id"], role="output")
        if binding["address"] != preview.get("binding_address"):
            raise FoundryError("binding range changed since preview")
        if binding["id"] not in workbook.get("preauthorized_areas", {}):
            raise FoundryError("output binding area is not preauthorized")
        resolutions = _require_object(payload.get("resolutions") or {}, "resolutions")
        for key, value in resolutions.items():
            _require_text(key, "resolution address", maximum=64)
            if value not in RESOLUTIONS:
                raise FoundryError("cell resolution must be apply or keep")
        preview_addresses = {cell["address"] for cell in preview["cells"]}
        raw_selected = payload.get("selected_addresses")
        if raw_selected is None:
            selected = set(preview_addresses)
        else:
            if not isinstance(raw_selected, list) or len(raw_selected) > MAX_CELLS:
                raise FoundryError("selected_addresses must be a bounded list")
            selected = {_require_text(address, "selected address", maximum=64) for address in raw_selected}
            outside = sorted(selected - preview_addresses)
            if outside:
                raise FoundryError(f"selected address is not in preview: {outside[0]}")
        applied = []
        kept = []
        for cell in preview["cells"]:
            if cell["address"] not in current:
                raise FoundryError(f"current cell snapshot is missing: {cell['address']}")
            if _cell_hash(_require_object(current[cell["address"]], "current cell")) != cell["current_hash"]:
                raise FoundryError(f"cell changed since preview: {cell['address']}")
            if cell["address"] not in selected:
                kept.append(cell)
                continue
            choice = resolutions.get(cell["address"], "apply")
            if cell["conflict"] and cell["address"] not in resolutions:
                raise FoundryError(f"conflict at {cell['address']} requires explicit resolution")
            if choice == "keep":
                kept.append(cell)
            else:
                applied.append({
                    "address": cell["address"],
                    "field": cell["field"],
                    "value": cell["new_value"],
                    "cell_type": cell["cell_type"],
                    "number_format": cell["number_format"],
                })
        preview["authorized_applied"] = applied
        self._write_state(context.task, state)
        return {"binding": binding, "applied": applied, "kept": kept, "preview_id": preview_id}

    def _expected_cell_value_matches(self, expected: Any, actual: Any) -> bool:
        if expected is None:
            return actual is None or actual == ""
        if isinstance(expected, bool):
            return actual is expected
        if isinstance(expected, int | float | Decimal):
            try:
                return Decimal(str(actual)) == Decimal(str(expected))
            except (InvalidOperation, ValueError, TypeError):
                return False
        return str(actual) == str(expected)

    def _ack_output(self, context, payload: dict[str, Any]) -> dict[str, Any]:
        assert context.task is not None
        state = self._read_state(context.task)
        workbook_id = self._workbook_id(payload)
        preview_id = _safe_id(payload.get("preview_id"), "preview id")
        workbook = self._workbook(state, context, workbook_id)
        preview = workbook.get("previews", {}).get(preview_id)
        if not preview:
            raise FoundryError("preview is unavailable")
        if payload.get("binding_id") and payload.get("binding_id") != preview["binding_id"]:
            raise FoundryError("binding changed since preview")
        binding = self._binding(context, workbook_id, preview["binding_id"], role="output")
        if binding["address"] != preview.get("binding_address"):
            raise FoundryError("binding range changed since preview")
        cells = payload.get("cells")
        if not isinstance(cells, list) or len(cells) > MAX_CELLS:
            raise FoundryError("ack cells must be a bounded array")
        authorized = {cell["address"]: cell for cell in preview.get("authorized_applied") or []}
        updated = []
        for raw in cells:
            cell = _require_object(raw, "ack cell")
            address = _require_text(cell.get("address"), "ack address", maximum=64)
            expected = authorized.get(address)
            if expected is None:
                raise FoundryError(f"ack address was not authorized for write: {address}")
            if not _address_in_binding(address, binding):
                raise FoundryError(f"ack address outside output binding: {address}")
            if not self._expected_cell_value_matches(expected["value"], cell.get("value")):
                raise FoundryError(f"ack cell value does not match authorized write: {address}")
            binding["baseline_hashes"][address] = _cell_hash(cell)
            updated.append(address)
        workbook["bindings"][binding["id"]] = binding
        self._write_state(context.task, state)
        return {"preview_id": preview_id, "binding_id": binding["id"], "updated_baselines": updated}


def generate_manifest(*, port: int = DEFAULT_PORT, addin_id: str = "b3e2c8f7-6c1d-4cc5-b73d-c7e9d7d9d9a1") -> str:
    if not 1 <= int(port) <= 65535:
        raise FoundryError("manifest port is invalid")
    base = f"https://localhost:{int(port)}"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
  xmlns:ov="http://schemas.microsoft.com/office/taskpaneappversionoverrides"
  xsi:type="TaskPaneApp">
  <Id>{addin_id}</Id>
  <Version>0.1.0.0</Version>
  <ProviderName>Finance Skill Foundry</ProviderName>
  <DefaultLocale>en-US</DefaultLocale>
  <DisplayName DefaultValue="Finance Foundry"/>
  <Description DefaultValue="Import bound Excel ranges into immutable finance snapshots and write approved outputs back to bound areas."/>
  <IconUrl DefaultValue="{base}/icon.png"/>
  <HighResolutionIconUrl DefaultValue="{base}/icon.png"/>
  <SupportUrl DefaultValue="https://localhost:{int(port)}/taskpane.html"/>
  <AppDomains><AppDomain>{base}</AppDomain></AppDomains>
  <Hosts><Host Name="Workbook"/></Hosts>
  <DefaultSettings><SourceLocation DefaultValue="{base}/taskpane.html"/></DefaultSettings>
  <Permissions>ReadWriteDocument</Permissions>
  <VersionOverrides xmlns="http://schemas.microsoft.com/office/taskpaneappversionoverrides" xsi:type="VersionOverridesV1_0">
    <Hosts>
      <Host xsi:type="Workbook">
        <DesktopFormFactor>
          <GetStarted>
            <Title resid="GetStarted.Title"/>
            <Description resid="GetStarted.Description"/>
            <LearnMoreUrl resid="GetStarted.Url"/>
          </GetStarted>
          <FunctionFile resid="Taskpane.Url"/>
          <ExtensionPoint xsi:type="PrimaryCommandSurface">
            <OfficeTab id="TabHome">
              <Group id="Foundry.Group">
                <Label resid="Foundry.GroupLabel"/>
                <Icon>
                  <bt:Image size="16" resid="Icon.16"/>
                  <bt:Image size="32" resid="Icon.32"/>
                  <bt:Image size="80" resid="Icon.80"/>
                </Icon>
                <Control xsi:type="Button" id="Foundry.Open">
                  <Label resid="Foundry.OpenLabel"/>
                  <Supertip>
                    <Title resid="Foundry.OpenLabel"/>
                    <Description resid="Foundry.OpenTip"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="Icon.16"/>
                    <bt:Image size="32" resid="Icon.32"/>
                    <bt:Image size="80" resid="Icon.80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <TaskpaneId>ButtonId1</TaskpaneId>
                    <SourceLocation resid="Taskpane.Url"/>
                  </Action>
                </Control>
              </Group>
            </OfficeTab>
          </ExtensionPoint>
        </DesktopFormFactor>
      </Host>
    </Hosts>
    <Resources>
      <bt:Images>
        <bt:Image id="Icon.16" DefaultValue="{base}/icon.png"/>
        <bt:Image id="Icon.32" DefaultValue="{base}/icon.png"/>
        <bt:Image id="Icon.80" DefaultValue="{base}/icon.png"/>
      </bt:Images>
      <bt:Urls>
        <bt:Url id="Taskpane.Url" DefaultValue="{base}/taskpane.html"/>
        <bt:Url id="GetStarted.Url" DefaultValue="https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-workbooks"/>
      </bt:Urls>
      <bt:ShortStrings>
        <bt:String id="GetStarted.Title" DefaultValue="Finance Foundry is ready"/>
        <bt:String id="Foundry.GroupLabel" DefaultValue="Finance Foundry"/>
        <bt:String id="Foundry.OpenLabel" DefaultValue="Open Foundry"/>
      </bt:ShortStrings>
      <bt:LongStrings>
        <bt:String id="GetStarted.Description" DefaultValue="Bind an input range, import a snapshot, run a metric, and apply reviewed outputs to a dedicated bound area."/>
        <bt:String id="Foundry.OpenTip" DefaultValue="Open the Finance Foundry task pane."/>
      </bt:LongStrings>
    </Resources>
  </VersionOverrides>
</OfficeApp>
"""


class _Handler(BaseHTTPRequestHandler):
    app: ExcelBridgeApp

    def do_GET(self) -> None:  # noqa: N802
        self._reply(*self.app.handle("GET", self.path, dict(self.headers), b""))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._reply(
                int(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
                {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
                _json_bytes({"error": {"code": "refused", "message": "request body is too large"}}),
            )
            return
        self._reply(*self.app.handle("POST", self.path, dict(self.headers), self.rfile.read(length)))

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _reply(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _load_secret(secret_file: Path | None = None) -> str:
    if secret_file is not None:
        try:
            secret = secret_file.read_text(encoding="utf8").strip()
        except OSError as exc:
            raise FoundryError("bridge secret file is unavailable") from exc
    else:
        secret = os.environ.get("FOUNDRY_EXCEL_BRIDGE_SECRET", "").strip()
    if len(secret) < 32:
        raise FoundryError("bridge secret must be supplied by env or file and contain at least 32 characters")
    return secret


def serve_https(*, var_root: Path, secret: str, port: int, certfile: Path, keyfile: Path, static_root: Path | None = None) -> None:
    if not certfile.is_file() or not keyfile.is_file():
        raise FoundryError("HTTPS certfile and keyfile are required")
    authority = BridgeTokenAuthority(secret.encode("utf8"))
    app = ExcelBridgeApp(var_root=var_root, token_authority=authority, static_root=static_root)
    handler = type("ExcelBridgeHandler", (_Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certfile), str(keyfile))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


def _arg_var(args: argparse.Namespace) -> Path:
    value = getattr(args, "var", None)
    if not value:
        raise FoundryError("excel bridge command needs --var")
    return Path(value)


def _cmd_token(args: argparse.Namespace) -> int:
    task = TaskStore(_arg_var(args)).get(args.task)
    task.record_session(args.excel_bridge_session, role="analysis")
    token = BridgeTokenAuthority(_load_secret(Path(args.secret_file) if args.secret_file else None).encode("utf8")).issue(
        task_id=task.id,
        session_id=args.excel_bridge_session,
        ttl_seconds=args.ttl,
    )
    print(json.dumps({"token": token, "task_id": task.id, "session_id": args.excel_bridge_session}, ensure_ascii=False))
    return 0


def _cmd_manifest(args: argparse.Namespace) -> int:
    print(generate_manifest(port=args.port))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    serve_https(
        var_root=_arg_var(args),
        secret=_load_secret(Path(args.secret_file) if args.secret_file else None),
        port=args.port,
        certfile=Path(args.certfile),
        keyfile=Path(args.keyfile),
        static_root=Path(args.static_root) if args.static_root else None,
    )
    return 0


def add_parsers(sub: argparse._SubParsersAction) -> None:
    manifest = sub.add_parser("excel-bridge-manifest", allow_abbrev=False)
    manifest.add_argument("--port", type=int, default=DEFAULT_PORT)
    manifest.set_defaults(excel_bridge_func=_cmd_manifest)

    token = sub.add_parser("excel-bridge-token", allow_abbrev=False)
    token.add_argument("--var", default=argparse.SUPPRESS)
    token.add_argument("--task", required=True)
    token.add_argument("--session", dest="excel_bridge_session", required=True)
    token.add_argument("--secret-file")
    token.add_argument("--ttl", type=int, default=3600)
    token.set_defaults(excel_bridge_func=_cmd_token)

    serve = sub.add_parser("excel-bridge-serve", allow_abbrev=False)
    serve.add_argument("--var", default=argparse.SUPPRESS)
    serve.add_argument("--secret-file")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--certfile", required=True)
    serve.add_argument("--keyfile", required=True)
    serve.add_argument("--static-root")
    serve.set_defaults(excel_bridge_func=_cmd_serve)


def dispatch(args: argparse.Namespace) -> bool:
    func = getattr(args, "excel_bridge_func", None)
    if func is None:
        return False
    func(args)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Office.js Excel bridge for Finance Skill Foundry", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    add_parsers(sub)
    aliases = {
        "manifest": "excel-bridge-manifest",
        "token": "excel-bridge-token",
        "serve": "excel-bridge-serve",
    }
    supplied = list(argv if argv is not None else os.sys.argv[1:])
    if supplied and supplied[0] in aliases:
        supplied[0] = aliases[supplied[0]]
    args = parser.parse_args(supplied)
    try:
        return 0 if dispatch(args) else 3
    except FoundryError as exc:
        print(str(exc))
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
