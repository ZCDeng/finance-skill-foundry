"""Remember a confirmed structure so next month's file needs no second look.

A month-end pack arrives in the same shape every period. Once the manager has
said what a sheet is, the next file that matches that shape can be read the same
way. A template records the shape — the roles its columns carry, in order,
under that sheet's name — and how often it has proved right. A structure the
manager withdrew loses weight, and at zero it stops matching.
"""

from __future__ import annotations

import re
from typing import Any

from foundry.errors import FoundryError

# How close a sheet must sit to a remembered shape before it is the same table.
MATCH_THRESHOLD = 0.85
WEIGHT_CEILING = 8
PUBLIC_FIELDS = ("id", "signature", "sheet_pattern", "weight", "disabled")
DIGITS = re.compile(r"\d+")


def signature_for(sheet: dict[str, Any]) -> str:
    """The ordered column roles a sheet carries, which is what makes it itself."""
    return "|".join(
        f"{column.get('role')}:{column.get('display') or column.get('header') or ''}"
        for column in sheet.get("columns") or []
    )


def sheet_pattern(name: str) -> str:
    """Sheet names carry the period; the pattern is the name without it."""
    return DIGITS.sub("#", str(name or ""))


def _roles(sheet: dict[str, Any]) -> list[str]:
    return [str(column.get("role") or "") for column in sheet.get("columns") or []]


def _headers(sheet: dict[str, Any]) -> list[str]:
    return [
        str(column.get("display") or column.get("header") or "")
        for column in sheet.get("columns") or []
    ]


def similarity(sheet: dict[str, Any], template: dict[str, Any]) -> float:
    """Blend header overlap, column order and the sheet's own name."""
    stored = template.get("declaration") or {}
    left, right = set(_headers(sheet)), set(_headers(stored))
    if not left or not right:
        return 0.0
    jaccard = len(left & right) / len(left | right)
    roles_a, roles_b = _roles(sheet), _roles(stored)
    width = max(len(roles_a), len(roles_b))
    ordered = (
        sum(1 for a, b in zip(roles_a, roles_b) if a == b) / width if width else 0.0
    )
    named = 1.0 if sheet_pattern(sheet.get("sheet", "")) == template.get("sheet_pattern") else 0.0
    return round(0.5 * jaccard + 0.35 * ordered + 0.15 * named, 4)


def differences(sheet: dict[str, Any], template: dict[str, Any]) -> list[str]:
    """What a remembered shape does not answer for in this sheet."""
    stored = template.get("declaration") or {}
    found: list[str] = []
    if _headers(sheet) != _headers(stored):
        found.append("columns")
    if _roles(sheet) != _roles(stored):
        found.append("roles")
    stored_pairs = {
        pair.get("label"): (pair.get("direction") or {}).get("kind")
        for pair in stored.get("amount_pairs") or []
    }
    sheet_pairs = {
        pair.get("label"): (pair.get("direction") or {}).get("kind")
        for pair in sheet.get("amount_pairs") or []
    }
    if stored_pairs != sheet_pairs:
        found.append("amount_pairs")
    if sorted(sheet.get("fill_down_columns") or []) != sorted(
        stored.get("fill_down_columns") or []
    ):
        found.append("fill_down_columns")
    return found


def live_templates(store) -> list[dict[str, Any]]:
    return [
        row
        for row in store._list("structure_templates")
        if not row.get("disabled") and row.get("weight", 0) > 0
    ]


def apply_matching_templates(
    store, sheets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pre-fill each sheet from the closest remembered shape, and say how close."""
    templates = live_templates(store)
    if not templates:
        return sheets, []
    prepared: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for sheet in sheets:
        if sheet.get("decision") != "table":
            prepared.append(sheet)
            continue
        scored = sorted(
            ((similarity(sheet, template), template) for template in templates),
            key=lambda item: (item[0], item[1].get("weight", 0)),
            reverse=True,
        )
        score, template = scored[0]
        if score < MATCH_THRESHOLD:
            prepared.append(sheet)
            continue
        gaps = differences(sheet, template)
        filled = dict(sheet)
        if gaps:
            # A remembered shape that does not fit exactly is a starting point,
            # never a decision: the card opens pre-filled.
            filled["prefill"] = template.get("declaration")
        else:
            stored = template.get("declaration") or {}
            filled = {
                **stored,
                "sheet": sheet["sheet"],
                # Rows move every month; only the engine can say where they are now.
                "excluded_rows": sheet.get("excluded_rows") or [],
                "title_rows": sheet.get("title_rows") or [],
                "header_row": sheet.get("header_row"),
                "scope_hints": sheet.get("scope_hints") or {},
            }
        filled["template_id"] = template["id"]
        prepared.append(filled)
        matches.append(
            {
                "sheet": sheet["sheet"],
                "template_id": template["id"],
                "score": score,
                "differences": gaps,
                "auto_apply": not gaps,
            }
        )
    return prepared, matches


def remember_declaration(store, sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep what the manager settled, one record per shape rather than per month."""
    kept: list[dict[str, Any]] = []
    for sheet in sheets:
        if sheet.get("decision") != "table":
            continue
        signature = signature_for(sheet)
        pattern = sheet_pattern(sheet.get("sheet", ""))
        existing = next(
            (
                row
                for row in store._list("structure_templates")
                if row.get("signature") == signature
                and row.get("sheet_pattern") == pattern
            ),
            None,
        )
        if existing is not None:
            kept.append(_reweigh(store, existing, +1))
            continue
        kept.append(
            store._write(
                "structure_templates",
                signature=signature,
                sheet_pattern=pattern,
                declaration=sheet,
                weight=1,
                disabled=False,
                bindings={},
            )
        )
    return kept


def demote_declaration(store, sheets: list[dict[str, Any]]) -> None:
    """A withdrawn structure is evidence against the shape it came from."""
    for sheet in sheets:
        signature = signature_for(sheet)
        pattern = sheet_pattern(sheet.get("sheet", ""))
        for row in store._list("structure_templates"):
            if row.get("signature") == signature and row.get("sheet_pattern") == pattern:
                _reweigh(store, row, -1)


def _reweigh(store, template: dict[str, Any], delta: int) -> dict[str, Any]:
    weight = max(0, min(WEIGHT_CEILING, int(template.get("weight", 0)) + delta))
    updated = {
        **template,
        "weight": weight,
        "disabled": bool(template.get("disabled")) or weight == 0,
    }
    _overwrite(store, updated)
    return updated


def disable_template(store, template_id: str) -> dict[str, Any]:
    template = store._read("structure_templates", template_id)
    updated = {**template, "weight": 0, "disabled": True}
    _overwrite(store, updated)
    return public_template(updated)


def _overwrite(store, record: dict[str, Any]) -> None:
    """A template is a live tally, not a filed version: it is rewritten in place."""
    from foundry.analysis import _hash
    from foundry.fsutil import write_json_atomic
    from foundry.locking import exclusive

    path = store._path("structure_templates", record["id"])
    payload = {key: value for key, value in record.items() if key != "_integrity_hash"}
    payload["_integrity_hash"] = _hash(payload)
    with exclusive(store.task.lock_path, timeout=10):
        write_json_atomic(path, payload)


def public_template(record: dict[str, Any]) -> dict[str, Any]:
    item = {key: record.get(key) for key in PUBLIC_FIELDS}
    declaration = record.get("declaration") or {}
    item["sheet"] = declaration.get("sheet", "")
    item["columns"] = len(declaration.get("columns") or [])
    return item
