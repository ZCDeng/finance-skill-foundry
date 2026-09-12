"""Path-free source locators for authorized finance snapshots."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from foundry.analysis import _hash, _new
from foundry.errors import FoundryError
from foundry.locking import exclusive
from foundry.task import sha256_bytes


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
DEFAULT_AMOUNT_ALIASES = ("amount", "金额")
DEBIT_CREDIT_ALIASES = ("借方", "贷方", "debit", "credit")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FACT_ID = re.compile(r"^[0-9a-f]{16,64}$")


def build_source_locator(
    dataset: dict,
    source_row: int,
    *,
    field: str = "amount",
    report_source_ids: set[str] | None = None,
    aliases: tuple[str, ...] | list[str] | None = None,
    row: dict | None = None,
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
        # A table derived from a confirmed structure records, per row, the column
        # the amount actually came from — a 借方/贷方 pair puts it on a different
        # side from one line to the next, which a header map cannot express.
        letter = _row_column_letter(transformation, source_row) or _column_letter_for_field(
            transformation.get("header_columns"), _alias_candidates(field, aliases), row
        )
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


def _alias_candidates(field: str, aliases: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Header names that may hold the located amount, most specific first."""
    ordered: list[str] = []
    for name in (field, *(aliases or ()), *DEFAULT_AMOUNT_ALIASES, *DEBIT_CREDIT_ALIASES):
        text = str(name or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    return tuple(ordered)


def _row_column_letter(transformation: Any, source_row: int) -> str:
    if not isinstance(transformation, dict):
        return ""
    structure = transformation.get("structure")
    if not isinstance(structure, dict):
        return ""
    row_columns = structure.get("row_columns")
    if not isinstance(row_columns, dict):
        return ""
    letter = str(row_columns.get(str(source_row)) or "").strip()
    return letter.upper() if letter.isalpha() else ""


def _column_letter_for_field(header_columns: Any, candidates: tuple[str, ...], row: dict | None) -> str:
    if not isinstance(header_columns, dict):
        return ""
    present: list[tuple[str, str]] = []
    for name in candidates:
        letter = str(header_columns.get(name) or "").strip()
        if letter.isalpha():
            present.append((name, letter.upper()))
    if not present:
        return ""
    if isinstance(row, dict):
        # A debit/credit export has one populated side per line; point at it.
        for name, letter in present:
            if row.get(name) not in (None, ""):
                return letter
    return present[0][1]


def fact_index_dir(store) -> Path:
    return store.analysis._inside(store.analysis.root / "finance" / "fact_index")


def record_fact_index(store, facts: list[dict]) -> None:
    """Remember which run a prepared fact came from so a click does not rescan every run."""
    entries: dict[str, str] = {}
    for fact in facts:
        fact_id = str(fact.get("id") or "")
        run_id = str(fact.get("run_id") or "")
        if FACT_ID.fullmatch(fact_id) and run_id:
            entries[fact_id] = run_id
    if not entries:
        return
    root = fact_index_dir(store)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive(store.task.lock_path, timeout=10):
        for fact_id, run_id in entries.items():
            path = root / f"{fact_id}.json"
            if path.exists():
                continue
            store.analysis._write_locked(path, _new(store.task, fact_id=fact_id, run_id=run_id))


def _indexed_run_id(store, fact_id: str) -> str:
    path = fact_index_dir(store) / f"{fact_id}.json"
    if not path.is_file():
        return ""
    try:
        return str(store.analysis._read(path).get("run_id") or "")
    except FoundryError:
        return ""


def _open_fact(store, fact_id: Any) -> dict[str, Any]:
    if not isinstance(fact_id, str) or not FACT_ID.fullmatch(fact_id):
        return {"status": "locator_forbidden"}
    run_ids = [run["id"] for run in reversed(store.analysis.state().get("runs") or [])]
    indexed = _indexed_run_id(store, fact_id)
    if indexed in run_ids:
        run_ids.remove(indexed)
        run_ids.insert(0, indexed)
    for run_id in run_ids:
        try:
            run = store.analysis.get_run(run_id)
            store._authorize(run.get("bindings") or {})
        except FoundryError:
            continue
        fact = _fact_on_run(run, fact_id)
        if fact is None:
            continue
        return _payload_from_fact(store, run, fact)
    return {"status": "locator_forbidden"}


def _open_run_cell(store, spec: dict) -> dict[str, Any]:
    try:
        run = store.analysis.get_run(str(spec["run_id"]))
        store._authorize(run.get("bindings") or {})
    except FoundryError:
        return {"status": "locator_forbidden"}
    index = spec.get("row")
    column = spec.get("column")
    if column is not None and not isinstance(column, str):
        raise FoundryError("open_source_locator column must be a string")
    rows = run.get("result", {}).get("rows") or []
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(rows):
        return {"status": "locator_unavailable"}
    row = rows[index]
    if not isinstance(row, dict):
        return {"status": "locator_unavailable"}
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    refs = evidence.get(column, row.get("source_rows", [])) if column else row.get("source_rows", [])
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
        if key in {"path", "url", "file", "allowedRoot", "preview_path", "preview_digest"}:
            continue
        if isinstance(value, str) and any(marker in value for marker in PATH_MARKERS):
            continue
        clean[key] = value
    return clean


def stage_source_locator_preview(store, spec: dict | None) -> Path:
    """Copy authorized source bytes into digest-named scratch. Path stays in-process."""
    payload = open_source_locator(store, spec)
    if payload.get("status") != "ok":
        raise FoundryError(str(payload.get("status") or "locator_unavailable"))
    locator = payload.get("locator") or {}
    if not locator.get("preview_available"):
        raise FoundryError("preview_unavailable")
    kind = locator.get("kind")
    if kind not in {"xlsx", "csv"}:
        raise FoundryError("preview_unavailable")
    dataset_id = str(locator.get("dataset_id") or "")
    digest = str(locator.get("source_hash") or "")
    if not dataset_id or not DIGEST.fullmatch(digest):
        raise FoundryError("locator_forbidden")
    data, suffix = _authorized_source_bytes(store, dataset_id, digest)
    dest_dir = store.task.artifacts_dir / "preview" / digest
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest}{suffix}"
    dest.write_bytes(data)
    resolved = dest.resolve()
    scratch = dest_dir.resolve()
    analysis_root = store.analysis.root.resolve()
    if analysis_root == resolved or analysis_root in resolved.parents:
        raise FoundryError("locator_forbidden")
    if resolved.parent != scratch:
        raise FoundryError("locator_forbidden")
    return dest


def _authorized_source_bytes(store, dataset_id: str, digest: str) -> tuple[bytes, str]:
    folder = store.analysis._inside(store.analysis.root / "datasets" / dataset_id)
    metadata = store.analysis._read(folder / "meta.json")
    source_file = str(metadata.get("source_file") or "")
    source_path = store.analysis._inside(folder / source_file)
    data = source_path.read_bytes()
    if sha256_bytes(data) != digest or str(metadata.get("source_hash") or "") != digest:
        raise FoundryError("locator_forbidden")
    suffix = Path(source_file).suffix.lower() or ".xlsx"
    return data, suffix
