"""Management P&L adjustments: persist, authorize, and apply named confirmed rows."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.analysis import _safe_text
from foundry.errors import FoundryError

ALLOWED_BASIS = {"user_assumption", "professional_judgment", "source_fact"}


def normalize_adjustment(spec: dict, *, context: dict, bindings: dict) -> dict:
    if not isinstance(spec, dict):
        raise FoundryError("finance adjustment spec must be an object")
    if not bindings:
        raise FoundryError("adjustment bindings are required")
    label = _safe_text(spec.get("label"), "adjustment label", required=True, maximum=200)
    note = _safe_text(spec.get("note") or "", "adjustment note", maximum=4000)
    basis = spec.get("basis") or "professional_judgment"
    if basis not in ALLOWED_BASIS:
        raise FoundryError("adjustment basis is not allowed")
    locator = spec.get("locator")
    if locator is not None and not isinstance(locator, dict):
        raise FoundryError("adjustment locator must be an object")
    if basis == "source_fact" and not locator:
        raise FoundryError("source_fact adjustments require an authorized locator")
    if locator:
        from foundry.finance_locators import _sanitize_locator

        extra = {"path", "url", "file", "allowedRoot", "preview_path", "preview_digest"} & set(locator)
        if extra:
            raise FoundryError("adjustment locator cannot take a path or preview handle")
        locator = _sanitize_locator(dict(locator))
        dataset_id = locator.get("dataset_id")
        if dataset_id not in bindings.values():
            raise FoundryError("adjustment locator is outside authorized snapshots")
    accounts = spec.get("accounts") or []
    if not isinstance(accounts, list) or not accounts or any(not isinstance(item, str) or not item.strip() for item in accounts):
        raise FoundryError("adjustment accounts must be a non-empty string list")
    parent_id = spec.get("parent_id")
    if parent_id is not None and not isinstance(parent_id, str):
        raise FoundryError("adjustment parent_id must be a string")
    return {
        "context_id": context["id"],
        "label": label,
        "amount": _money(spec.get("amount")),
        "profit_impact": _money(spec.get("profit_impact")),
        "accounts": [item.strip() for item in accounts],
        "effective_period": _safe_text(
            spec.get("effective_period"), "effective_period", required=True, maximum=32
        ),
        "include_in_management_pnl": False,
        "basis": basis,
        "note": note,
        "locator": locator,
        "parent_id": parent_id,
        "bindings": dict(bindings),
    }


def reject_overlapping_save(record: dict, existing: list[dict]) -> None:
    accounts = set(record["accounts"])
    period = record["effective_period"]
    parent_id = record.get("parent_id")
    for row in existing:
        if row.get("id") == record.get("id"):
            continue
        if row.get("effective_period") != period:
            continue
        if not accounts.intersection(row.get("accounts") or []):
            continue
        if parent_id == row.get("id"):
            continue
        raise FoundryError("overlapping adjustment accounts require a parent_id on the replaced row")


def select_applied(
    named_ids: list[str],
    records: list[dict],
    *,
    period: str | None,
) -> list[dict]:
    by_id = {row["id"]: row for row in records}
    named = [by_id[item] for item in named_ids if item in by_id]
    named_set = {row["id"] for row in named}
    applied = []
    for row in named:
        if not row.get("include_in_management_pnl"):
            continue
        if period and row.get("effective_period") != period:
            continue
        if any(child.get("parent_id") == row["id"] and child["id"] in named_set for child in named):
            continue
        applied.append(row)
    return applied


def apply_to_metric(result: dict, adjustments: list[dict]) -> dict:
    if not adjustments:
        return result
    impact = sum((_dec(row.get("profit_impact")) for row in adjustments), Decimal("0"))
    columns = list(result.get("columns") or [])
    for name in ("source_total", "adjusted_total"):
        if name not in columns:
            columns.append(name)
    ids = [item["id"] for item in adjustments]
    periods = {str(row.get("effective_period") or "") for row in adjustments}
    period = next(iter(periods)) if len(periods) == 1 else ""

    def source_of(row: dict) -> Decimal:
        return _dec(row.get("profit") or row.get("source_total") or "0")

    def matches_period(row: dict) -> bool:
        row_period = str(row.get("period") or "").strip()
        return not (period and row_period and row_period != period)

    raw_rows = list(result.get("rows") or [])
    matching = [row for row in raw_rows if isinstance(row, dict) and matches_period(row)]
    target = None
    if len(matching) == 1:
        target = matching[0]
    elif len(matching) > 1:
        untitled = [row for row in matching if not str(row.get("organization") or "").strip()]
        if untitled:
            target = untitled[0]

    rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            rows.append(row)
            continue
        source = source_of(row)
        hit = target is not None and row is target
        rows.append(
            {
                **row,
                "source_total": _money(source),
                "adjusted_total": _money(source + (impact if hit else Decimal("0"))),
                "applied_adjustment_ids": ids if hit else [],
            }
        )
    if matching and target is None:
        source_sum = sum((source_of(row) for row in matching), Decimal("0"))
        extra: dict[str, Any] = {
            "source_total": _money(source_sum),
            "adjusted_total": _money(source_sum + impact),
            "applied_adjustment_ids": ids,
        }
        if period:
            extra["period"] = period
        rows.append(extra)
    return {**result, "columns": columns, "rows": rows}


def run_period(context: dict) -> str | None:
    for scope in (context.get("scopes") or {}).values():
        if isinstance(scope, dict) and scope.get("period"):
            return str(scope["period"])
    return None


def _dec(value: Any) -> Decimal:
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"invalid adjustment decimal: {value}") from exc


def _money(value: Any) -> str:
    return format(_dec(value), "f")
