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
    """The table the manager circled, or what went wrong finding it.

    All three of these used to answer "unauthorized selection", which sent the
    reader looking for a permission problem when the draft simply had no table
    in it. Only the workbook binding check below is about authorization.
    """
    document = draft.get("document") or {}
    tables = tables_in(document.get("content") or [])
    block_id = spec.get("block_id")
    if not isinstance(block_id, str) or not block_id.strip():
        raise FoundryError("circle-select needs the caption or id of the table to change")
    wanted = block_id.strip()
    for table in tables:
        attrs = table.get("attrs") or {}
        if wanted in {str(attrs.get("caption") or ""), str(attrs.get("id") or "")}:
            return table
    if not tables:
        raise FoundryError("this draft has no table to circle")
    captions = sorted(
        name
        for table in tables
        for name in [
            str((table.get("attrs") or {}).get("caption") or "")
            or str((table.get("attrs") or {}).get("id") or "")
        ]
        if name
    )
    raise FoundryError(
        f"no table in this draft is called {wanted}"
        + (f"; it has {'、'.join(captions)}" if captions else "")
    )


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
