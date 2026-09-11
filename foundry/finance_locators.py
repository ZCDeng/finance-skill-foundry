"""Path-free source locators for authorized finance snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from foundry.analysis import _hash
from foundry.errors import FoundryError


KIND_BY_SUFFIX = {
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".json": "json",
    ".md": "md",
    ".txt": "txt",
    ".pdf": "pdf",
}
PATH_MARKERS = ("/", "\\", "file://", "http://", "https://")
FORBIDDEN_ARGS = {"dataset_id", "path", "url", "file", "allowedRoot", "preview_path"}


def build_source_locator(
    dataset: dict,
    source_row: int,
    *,
    field: str = "amount",
    report_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    transformation = dataset.get("transformation") or {}
    suffix = Path(str(dataset.get("source_file") or "")).suffix.lower()
    kind = str(transformation.get("format") or KIND_BY_SUFFIX.get(suffix) or "json")
    if kind == "markdown":
        kind = "md"
    locator: dict[str, Any] = {
        "dataset_id": str(dataset.get("id") or dataset.get("dataset_id") or ""),
        "source_hash": str(dataset.get("source_hash") or ""),
        "kind": kind,
        "source_row": int(source_row),
        "preview_available": kind in {"xlsx", "csv", "json", "md", "txt"},
        "sheet": "",
    }
    if kind == "xlsx":
        sheet = str(transformation.get("sheet") or "")
        locator["sheet"] = sheet
        letter = _column_letter_for_field(transformation.get("header_columns"), field)
        if letter and sheet:
            locator["excel_range"] = f"{sheet}!{letter}{source_row}"
    if kind == "pdf":
        registered = report_source_ids or set()
        locator["preview_available"] = bool(
            locator["dataset_id"] in registered or locator["source_hash"] in registered
        )
    return _sanitize_locator(locator)


def open_source_locator(store, spec: dict | None) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise FoundryError("open_source_locator requires an object")
    if FORBIDDEN_ARGS & set(spec):
        raise FoundryError("open_source_locator arguments must be fact_id or run_id,row,column")
    keys = set(spec)
    if keys == {"fact_id"}:
        return _open_fact(store, spec["fact_id"])
    extra = keys - {"run_id", "row", "column"}
    if "run_id" in spec and "row" in spec and not extra:
        return _open_run_cell(store, spec)
    raise FoundryError("open_source_locator arguments must be fact_id or run_id,row,column")


def _column_letter_for_field(header_columns: Any, field: str) -> str:
    if not isinstance(header_columns, dict):
        return ""
    aliases = (field, "amount", "金额")
    for alias in aliases:
        letter = str(header_columns.get(alias) or "").strip()
        if letter.isalpha():
            return letter.upper()
    return ""


def _open_fact(store, fact_id: Any) -> dict[str, Any]:
    if not isinstance(fact_id, str) or not fact_id:
        return {"status": "locator_forbidden"}
    for run in store.analysis.state().get("runs") or []:
        try:
            self_run = store.analysis.get_run(run["id"])
            store._authorize(self_run.get("bindings") or {})
        except FoundryError:
            continue
        fact = _fact_on_run(self_run, fact_id)
        if fact is None:
            continue
        return _payload_from_fact(store, self_run, fact)
    return {"status": "locator_forbidden"}


def _open_run_cell(store, spec: dict) -> dict[str, Any]:
    try:
        run = store.analysis.get_run(str(spec["run_id"]))
        store._authorize(run.get("bindings") or {})
    except FoundryError:
        return {"status": "locator_forbidden"}
    index = spec.get("row")
    column = spec.get("column")
    rows = run.get("result", {}).get("rows") or []
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(rows):
        return {"status": "locator_unavailable"}
    row = rows[index]
    refs = row.get("evidence", {}).get(column, row.get("source_rows", [])) if column else row.get("source_rows", [])
    locator = _locator_from_refs(refs)
    if not locator:
        return {"status": "locator_unavailable"}
    return _authorized_payload(store, run, locator)


def _fact_on_run(run: dict, fact_id: str) -> dict | None:
    from foundry.finance_explanations import _facts_for_run

    for fact in _facts_for_run(run, {}):
        if fact.get("id") == fact_id:
            return fact
    return None


def _payload_from_fact(store, run: dict, fact: dict) -> dict[str, Any]:
    locator = (fact.get("source_trace") or {}).get("source_locator")
    if not isinstance(locator, dict) or not locator:
        refs = (fact.get("source_trace") or {}).get("source_rows") or []
        locator = _locator_from_refs(refs)
    if not locator:
        return {"status": "locator_unavailable"}
    return _authorized_payload(store, run, locator)


def _locator_from_refs(refs: Any) -> dict[str, Any] | None:
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("source_locator"), dict):
            return ref["source_locator"]
    return None


def _authorized_payload(store, run: dict, locator: dict) -> dict[str, Any]:
    dataset_id = str(locator.get("dataset_id") or "")
    bindings = run.get("bindings") or {}
    if dataset_id not in bindings.values():
        return {"status": "locator_forbidden"}
    try:
        store._authorize(bindings)
        dataset = store.analysis.read_dataset(dataset_id)
    except FoundryError:
        return {"status": "locator_forbidden"}
    if locator.get("source_hash") and locator["source_hash"] != dataset.get("source_hash"):
        return {"status": "locator_forbidden"}
    clean = _sanitize_locator(dict(locator))
    handle = _hash(
        {
            "source_hash": clean.get("source_hash"),
            "excel_range": clean.get("excel_range"),
            "source_row": clean.get("source_row"),
            "kind": clean.get("kind"),
        }
    )
    return {
        "status": "ok",
        "locator": clean,
        "preview": {"available": bool(clean.get("preview_available")), "handle": handle},
    }


def _sanitize_locator(locator: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in locator.items():
        if key in {"path", "url", "file", "allowedRoot"}:
            continue
        if isinstance(value, str) and any(marker in value for marker in PATH_MARKERS):
            continue
        clean[key] = value
    return clean
