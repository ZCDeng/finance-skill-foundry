"""Recorded 改口径 from a task-local selection handle."""

from __future__ import annotations

from foundry.errors import FoundryError

FORBIDDEN_KEYS = {
    "path",
    "url",
    "file",
    "dataset_id",
    "preview_path",
    "preview_digest",
    "artifact_path",
    "deliverable_path",
}


def reject_forbidden_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise FoundryError("circle-select spec must be an object")
    extra = FORBIDDEN_KEYS.intersection(spec)
    if extra:
        raise FoundryError("circle-select cannot take a path, dataset_id, or preview handle")


def tables_in(node) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("type") == "table":
            found.append(node)
        for child in node.get("content") or []:
            found.extend(tables_in(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(tables_in(child))
    return found


def match_draft_table(draft: dict, spec: dict) -> dict:
    document = draft.get("document") or {}
    tables = tables_in(document.get("content") or [])
    block_id = spec.get("block_id")
    if block_id is None and spec.get("range") and tables:
        return tables[0]
    for index, table in enumerate(tables):
        attrs = table.get("attrs") or {}
        if str(block_id) in {str(attrs.get("caption") or ""), str(attrs.get("id") or ""), str(index)}:
            return table
    raise FoundryError("unauthorized selection")


def authorize_workbook(store, spec: dict, context: dict) -> dict:
    from foundry.finance_files import FinanceFiles

    binding_id = spec.get("binding_id")
    if not isinstance(binding_id, str) or not binding_id:
        raise FoundryError("workbook circle-select requires binding_id")
    files = FinanceFiles(store.task, snapshot_ids=store.allowed)
    binding = files._binding(binding_id)
    if binding.get("dataset_id") not in set((context.get("bindings") or {}).values()):
        raise FoundryError("unauthorized selection")
    return binding
