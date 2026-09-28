"""Archivable finance chart deliverables bound to an existing run snapshot."""

from __future__ import annotations

import json
from typing import Any

from foundry.analysis import _hash, _safe_text
from foundry.errors import FoundryError

FORBIDDEN_KEYS = {
    "path",
    "url",
    "file",
    "preview_path",
    "preview_digest",
    "artifact_path",
    "deliverable_path",
    "allowedRoot",
    "dataset_id",
}
SCRATCH_MARKERS = ("artifacts/preview", "locator scratch", "file://")


def reject_forbidden_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise FoundryError("chart spec must be an object")
    extra = FORBIDDEN_KEYS.intersection(spec)
    if extra:
        raise FoundryError("chart deliverable cannot take a path, preview handle, or dataset_id")
    blob = json.dumps(spec, ensure_ascii=False)
    if any(marker in blob for marker in SCRATCH_MARKERS):
        raise FoundryError("locator scratch cannot be registered as a chart")


def series_from_run(run: dict) -> dict[str, Any]:
    result = run.get("result") or {}
    if not isinstance(result, dict):
        raise FoundryError("chart run result must be an object")
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise FoundryError("chart series requires columns and rows")
    return {"columns": columns, "rows": rows}


def snapshot_hashes_from_run(run: dict) -> dict[str, str]:
    hashes = run.get("input_hashes") or {}
    if not isinstance(hashes, dict) or not hashes:
        raise FoundryError("chart requires snapshot hashes from the bound run")
    if any(not isinstance(value, str) or not value for value in hashes.values()):
        raise FoundryError("chart snapshot hashes must be strings")
    return dict(hashes)


def normalize_chart(spec: dict, *, run: dict) -> dict[str, Any]:
    reject_forbidden_spec(spec)
    if run.get("execution_status") not in {"succeeded", "success"}:
        raise FoundryError("chart requires a successful run")
    bindings = run.get("bindings") or {}
    if not isinstance(bindings, dict) or not bindings:
        raise FoundryError("chart bindings are required")
    if spec.get("bindings") == {}:
        raise FoundryError("chart bindings are required")
    if spec.get("bindings") and spec["bindings"] != bindings:
        raise FoundryError("chart bindings must match the bound run")
    series = series_from_run(run)
    hashes = snapshot_hashes_from_run(run)
    filters = spec.get("filters") if isinstance(spec.get("filters"), dict) else (run.get("finance_spec") or {}).get("filters") or {}
    assumptions = spec.get("assumptions") if isinstance(spec.get("assumptions"), list) else run.get("assumptions") or []
    parent_id = spec.get("parent_id")
    if parent_id is not None and not isinstance(parent_id, str):
        raise FoundryError("chart parent_id must be a string")
    payload = {
        "run_id": run["id"],
        "snapshot_hashes": hashes,
        "snapshot_hash": _hash(hashes),
        "series": series,
        "filters": filters,
        "assumptions": assumptions,
        "bindings": dict(bindings),
        "parent_id": parent_id,
        "label": _safe_text(spec.get("label") or "归档图", "chart label", maximum=200),
    }
    payload["content_hash"] = _hash(
        {
            "run_id": payload["run_id"],
            "snapshot_hashes": hashes,
            "series": series,
            "filters": filters,
            "assumptions": assumptions,
        }
    )
    return payload


def verify_snapshots(store, record: dict) -> None:
    hashes = record.get("snapshot_hashes") or {}
    bindings = record.get("bindings") or {}
    if not hashes or not bindings:
        raise FoundryError("chart snapshot is unavailable")
    for alias, dataset_id in bindings.items():
        try:
            dataset = store.analysis.read_dataset(dataset_id)
        except FoundryError as exc:
            raise FoundryError("chart snapshot is unavailable") from exc
        expected = hashes.get(alias)
        if expected is None or dataset.get("data_hash") != expected:
            raise FoundryError("chart snapshot is unavailable")
