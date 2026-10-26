"""Management P&L adjustments: persist, authorize, and apply named confirmed rows."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.analysis import _safe_text
from foundry.errors import FoundryError
from foundry.finance_model import _diag

ALLOWED_BASIS = {"user_assumption", "professional_judgment", "source_fact"}
IGNORE_NOT_CONFIRMED = "not_confirmed"
IGNORE_SUPERSEDED = "superseded"
IGNORE_PERIOD = "period_not_in_run"
APPROVAL_SUPERSEDED = "adjustment_approval_superseded"
DEPENDENCY_UNAVAILABLE = "adjustment_dependency_unavailable"


def current_cell_problem(analysis, run, row, column, *, allowed=None):
    """Current approval of this cell; the immutable calculation remains historical.

    Only adjusted_total consumes approvals, and only those applied to this row.
    Neither a pending replacement nor a different scope changes book amounts.
    """
    if (column != "adjusted_total" or run.get("engine") != "finance"
            or (run.get("result") or {}).get("metric_id") != "management_pnl"):
        return None
    applied = row.get("applied_adjustment_ids") or []
    if not applied:
        return None
    from foundry.finance_service import FinanceStore

    service = FinanceStore(analysis.task, snapshot_ids=allowed)
    try:
        service._authorize(run.get("bindings") or {})
        originals = [service._read("adjustments", key) for key in applied]
        for original in originals:
            if (original.get("context_id") != run.get("finance_context_id")
                    or original.get("bindings") != run.get("bindings")
                    or original.get("include_in_management_pnl") is not True
                    or not _matches_period(row, original.get("effective_period"))):
                return DEPENDENCY_UNAVAILABLE
        # Metadata only discovers potentially related records. It never grants
        # evidence: each approval and every traversed parent is integrity-checked.
        # An unrelated damaged record must not invalidate this cell.
        root = analysis._inside(analysis.root / service._folder("adjustments"))
        candidates = []
        for path in root.glob("*.json"):
            try:
                candidate = json.loads(path.read_text(encoding="utf8"))
            except (OSError, ValueError):
                continue
            if (isinstance(candidate, dict) and candidate.get("context_id") == run.get("finance_context_id")
                    and candidate.get("bindings") == run.get("bindings")
                    and candidate.get("include_in_management_pnl") is True):
                candidates.append(candidate)
        for original in originals:
            for candidate in candidates:
                if (candidate.get("effective_period") != original.get("effective_period")
                        or not set(candidate.get("accounts") or []) & set(original.get("accounts") or [])
                        or candidate.get("seq", 0) <= original.get("seq", 0)):
                    continue
                current = service._read("adjustments", candidate["id"])
                seen = set()
                while current.get("parent_id"):
                    parent_id = current["parent_id"]
                    if parent_id in seen:
                        return DEPENDENCY_UNAVAILABLE
                    seen.add(parent_id)
                    if parent_id == original["id"]:
                        return APPROVAL_SUPERSEDED
                    current = service._read("adjustments", parent_id)
        return None
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return DEPENDENCY_UNAVAILABLE


def current_reference_issues(analysis, spec, *, allowed=None, facts=None):
    """Check actual cell references, including recipe claims, without run-wide staleness."""
    locations = set()
    for claim in [*(spec.get("claims") or []),
                  *((recipe.get("claim") or {}) for recipe in spec.get("evidence_recipes") or []
                    if isinstance(recipe, dict))]:
        if (isinstance(claim, dict) and claim.get("column") == "adjusted_total"
                and isinstance(claim.get("run_id"), str) and type(claim.get("row")) is int):
            locations.add((claim.get("run_id"), claim.get("row"), "adjusted_total"))
    selected = {key for key in spec.get("fact_ids") or [] if isinstance(key, str)}
    try:
        if facts is None and selected:
            from foundry.finance_explanations import _facts_for_run, _materiality

            facts = []
            for key in dict.fromkeys(spec.get("run_ids") or []):
                run = analysis.get_run(key)
                if (run.get("engine") != "finance" or (run.get("result") or {}).get("metric_id") != "management_pnl"
                        or not any(row.get("applied_adjustment_ids") for row in (run.get("result") or {}).get("rows") or []
                                   if isinstance(row, dict))):
                    continue
                if allowed is not None and not set((run.get("bindings") or {}).values()) <= set(allowed):
                    raise FoundryError("adjustment dependency unavailable")
                facts.extend(_facts_for_run(run, _materiality(spec.get("materiality") or {}), analysis=analysis))
        locations.update((fact["run_id"], fact["row"], fact["column"]) for fact in facts or []
                         if fact.get("id") in selected and fact.get("column") == "adjusted_total")
        reasons = set()
        for run_id, row_index, column in locations:
            run = analysis.get_run(run_id)
            if type(row_index) is not int or row_index < 0:
                raise FoundryError("adjustment dependency unavailable")
            row = run["result"]["rows"][row_index]
            problem = current_cell_problem(analysis, run, row, column, allowed=allowed)
            if problem:
                reasons.add(problem)
    except (FoundryError, OSError, KeyError, TypeError, ValueError, IndexError):
        reasons = {DEPENDENCY_UNAVAILABLE}
    messages = {
        APPROVAL_SUPERSEDED: "引用的调整后金额所依赖的批准已被同范围的新批准替代；请按当前批准重新计算，历史结果保留。",
        DEPENDENCY_UNAVAILABLE: "引用的调整后金额所依赖的批准无法核验；请恢复获授权的依赖后重新验证。",
    }
    return [{"code": reason, "severity": "error", "message": messages[reason]} for reason in sorted(reasons)]


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
    # A row that a newer row already replaced no longer occupies its accounts;
    # only the live head of each parent_id chain can conflict.
    superseded = {row["parent_id"] for row in existing if isinstance(row.get("parent_id"), str)}
    for row in existing:
        if row.get("id") == record.get("id") or row.get("id") in superseded:
            continue
        if row.get("effective_period") != period:
            continue
        if not accounts.intersection(row.get("accounts") or []):
            continue
        if parent_id == row.get("id"):
            continue
        raise FoundryError("overlapping adjustment accounts require a parent_id on the replaced row")


def mark_superseded(records: list[dict]) -> list[dict]:
    """Annotate every row that a newer row replaced through parent_id."""
    replaced: dict[str, str] = {}
    for row in records:
        parent_id = row.get("parent_id")
        if isinstance(parent_id, str) and parent_id:
            replaced[parent_id] = row["id"]
    marked = []
    for row in records:
        child = replaced.get(row["id"])
        marked.append({**row, "superseded_by": child} if child else {k: v for k, v in row.items() if k != "superseded_by"})
    return marked


def _ancestor_ids(row: dict, by_id: dict[str, dict]) -> set[str]:
    seen: set[str] = set()
    parent_id = row.get("parent_id")
    while isinstance(parent_id, str) and parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent_id = (by_id.get(parent_id) or {}).get("parent_id")
    return seen


def select_applied(
    named_ids: list[str],
    records: list[dict],
    *,
    periods: set[str] | None,
) -> tuple[list[dict], list[dict]]:
    """Return (applied, ignored). Unknown ids fail loudly; skipped ids carry a reason."""
    by_id = {row["id"]: row for row in records}
    unknown = [str(item) for item in named_ids if item not in by_id]
    if unknown:
        raise FoundryError(f"unknown adjustment ids: {', '.join(unknown)}")
    named = [by_id[item] for item in dict.fromkeys(named_ids)]
    confirmed_named = [row for row in named if row.get("include_in_management_pnl")]
    superseded = set()
    for row in confirmed_named:
        superseded |= _ancestor_ids(row, by_id)
    applied: list[dict] = []
    ignored: list[dict] = []
    for row in named:
        if not row.get("include_in_management_pnl"):
            ignored.append({"id": row["id"], "reason": IGNORE_NOT_CONFIRMED})
            continue
        if row["id"] in superseded:
            ignored.append({"id": row["id"], "reason": IGNORE_SUPERSEDED})
            continue
        period = str(row.get("effective_period") or "")
        if periods is not None and period not in periods:
            ignored.append({"id": row["id"], "reason": IGNORE_PERIOD, "effective_period": period})
            continue
        applied.append(row)
    return applied, ignored


def apply_to_metric(result: dict, adjustments: list[dict], ignored: list[dict] | None = None) -> dict:
    ignored = list(ignored or [])
    if not adjustments:
        if not ignored:
            return result
        return _annotate_ignored(result, ignored)

    raw_rows = list(result.get("rows") or [])
    row_records = [row for row in raw_rows if isinstance(row, dict)]

    by_period: dict[str, list[dict]] = {}
    for row in adjustments:
        by_period.setdefault(str(row.get("effective_period") or ""), []).append(row)

    impact_by_row: dict[int, Decimal] = {}
    ids_by_row: dict[int, list[str]] = {}
    synthetic: list[dict] = []
    for period, group in by_period.items():
        impact = sum((_dec(row.get("profit_impact")) for row in group), Decimal("0"))
        ids = [row["id"] for row in group]
        matching = [row for row in row_records if _matches_period(row, period)]
        target = None
        if len(matching) == 1:
            target = matching[0]
        elif len(matching) > 1:
            untitled = [row for row in matching if not str(row.get("organization") or "").strip()]
            if untitled:
                target = untitled[0]
        if target is not None:
            key = id(target)
            impact_by_row[key] = impact_by_row.get(key, Decimal("0")) + impact
            ids_by_row.setdefault(key, []).extend(ids)
            continue
        if not matching:
            continue
        source_sum = sum((_source_of(row) for row in matching), Decimal("0"))
        extra: dict[str, Any] = {
            "source_total": _money(source_sum),
            "adjusted_total": _money(source_sum + impact),
            "applied_adjustment_ids": ids,
        }
        if period:
            extra["period"] = period
        synthetic.append(extra)

    rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            rows.append(row)
            continue
        source = _source_of(row)
        impact = impact_by_row.get(id(row), Decimal("0"))
        rows.append(
            {
                **row,
                "source_total": _money(source),
                "adjusted_total": _money(source + impact),
                "applied_adjustment_ids": list(ids_by_row.get(id(row), [])),
            }
        )
    rows.extend(synthetic)

    columns = list(result.get("columns") or [])
    for name in ("source_total", "adjusted_total"):
        if name not in columns:
            columns.append(name)
    updated = {**result, "columns": columns, "rows": rows, "applied_adjustment_ids": [row["id"] for row in adjustments]}
    return _annotate_ignored(updated, ignored) if ignored else updated


def _annotate_ignored(result: dict, ignored: list[dict]) -> dict:
    diagnostics = list(result.get("diagnostics") or [])
    for item in ignored:
        diagnostics.append(
            _diag(
                "warning",
                f"adjustment_{item['reason']}",
                f"adjustment {item['id']} was named but not applied: {item['reason']}",
            )
        )
    return {**result, "diagnostics": diagnostics, "ignored_adjustments": ignored}


def _matches_period(row: dict, period: str) -> bool:
    row_period = str(row.get("period") or "").strip()
    return not (period and row_period and row_period != period)


def _source_of(row: dict) -> Decimal:
    for key in ("profit", "source_total"):
        value = row.get(key)
        if value not in (None, ""):
            return _dec(value)
    return Decimal("0")


def run_periods(context: dict, result: dict | None = None) -> set[str] | None:
    """Periods a run covers: every row period plus the context scope period."""
    periods: set[str] = set()
    for row in (result or {}).get("rows") or []:
        if isinstance(row, dict) and str(row.get("period") or "").strip():
            periods.add(str(row["period"]).strip())
    for scope in (context.get("scopes") or {}).values():
        if isinstance(scope, dict) and scope.get("period"):
            periods.add(str(scope["period"]).strip())
    return periods or None


def _dec(value: Any) -> Decimal:
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"invalid adjustment decimal: {value}") from exc


def _money(value: Any) -> str:
    return format(_dec(value), "f")
