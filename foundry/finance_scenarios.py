"""Pure finance scenario calculations.

This module deliberately has no persistence, runner, payment, or journal-posting
entry points. Callers pass versioned records in and receive structured tables,
evidence, assumptions, and warnings back.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import defaultdict, deque
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.errors import FoundryError

REDUCTION_KINDS = {"payment", "allocation", "credit", "writeoff"}
OPERATORS = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant)
BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
UNARY_OPS = (ast.UAdd, ast.USub)
IDENTITY_FIELDS = ("ledger", "organization", "currency", "unit")


def _date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise FoundryError(f"{field} must be an ISO YYYY-MM-DD date") from exc
    raise FoundryError(f"{field} must be an ISO YYYY-MM-DD date")


def _decimal(value: Any, field: str) -> Decimal:
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"{field} must be a finite decimal") from exc


def _money(value: Decimal) -> str:
    return format(value, "f")


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _matches_scope(record: dict, scope: dict[str, Any] | None) -> bool:
    if not scope:
        return True
    aliases = {"organization": "org"}
    for key, expected in scope.items():
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        actual = record.get(key)
        if actual is None and key in aliases:
            actual = record.get(aliases[key])
        if (
            actual in (None, "")
            and key == "unit"
            and not isinstance(expected, (list, tuple, set))
        ):
            continue
        if actual not in values:
            return False
    return True


def _field(record: dict, name: str) -> Any:
    if name == "organization":
        return record.get("organization", record.get("org"))
    return record.get(name)


def _require_scope(scope: dict[str, Any] | None, purpose: str) -> dict[str, Any]:
    if not isinstance(scope, dict) or not scope:
        raise FoundryError(f"{purpose} scope is required")
    return scope


def _require_single_identity_scope(
    scope: dict[str, Any] | None, purpose: str
) -> dict[str, str]:
    scope = _require_scope(scope, purpose)
    selected = {}
    for field in IDENTITY_FIELDS:
        value = scope.get(field)
        if field == "organization" and value is None:
            value = scope.get("org")
        if not isinstance(value, str) or not value:
            raise FoundryError(f"{purpose} scope requires one {field}")
        selected[field] = value
    return selected


def _matches_identity_scope(record: dict, scope: dict[str, Any]) -> bool:
    return all(_field(record, field) == scope[field] for field in IDENTITY_FIELDS)


def _activity_matches_scope(record: dict, scope: dict[str, Any]) -> bool:
    for field in IDENTITY_FIELDS:
        if field not in scope and not (field == "organization" and "org" in scope):
            continue
        expected = scope.get(field, scope.get("org"))
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        actual = _field(record, field)
        if actual in (None, "") and field == "unit" and isinstance(expected, str):
            actual = expected
        if actual not in values:
            return False
    return True


def _missing_activity_identity_field(
    row: dict, field: str, scope: dict[str, Any]
) -> bool:
    value = _field(row, field)
    if value not in (None, ""):
        return False
    return not (
        field == "unit" and isinstance(scope.get("unit"), str) and scope["unit"]
    )


def _identity(
    record: dict, record_type: str, scope: dict[str, Any] | None = None
) -> tuple:
    invoice_id = record.get("invoice_id", record.get("id"))
    if not isinstance(invoice_id, str) or not invoice_id:
        raise FoundryError(f"{record_type} invoice identity must include nonempty id")
    parts = []
    for field in IDENTITY_FIELDS:
        value = _field(record, field)
        if field == "unit" and value in (None, "") and scope:
            scope_unit = scope.get("unit")
            if isinstance(scope_unit, str) and scope_unit:
                value = scope_unit
        if not isinstance(value, str) or not value:
            raise FoundryError(f"{record_type} identity requires {field}")
        parts.append(value)
    return (invoice_id, *parts)


def _issue_date(invoice: dict) -> date | None:
    raw = (
        invoice.get("issue_date")
        or invoice.get("invoice_date")
        or invoice.get("effective_date")
    )
    return _date(raw, "invoice issue_date") if raw is not None else None


def _aging_bucket_id(bucket: dict) -> str:
    """Resolve display-only localization without changing declared boundaries.

    Other names remain custom identifiers, including names resembling a standard
    interval whose declared bounds differ. Never infer a bound from a label.
    """
    standard = {(0, 30): "0-30", (31, 60): "31-60", (61, 90): "61-90", (91, None): "90+"}
    canonical = standard.get((bucket["min"], bucket.get("max")))
    return canonical if canonical and bucket["name"] == canonical + "天" else bucket["name"]


def validate_aging_buckets(buckets: Any) -> None:
    """Validate the canonical inclusive-day bucket contract without rewriting it."""
    if buckets is None:
        return
    if not isinstance(buckets, list) or not buckets:
        raise FoundryError("buckets must be a nonempty list of {name, min, max} objects")
    names = set()
    identities = set()
    next_min = 0
    for index, bucket in enumerate(buckets):
        if (not isinstance(bucket, dict) or set(bucket) - {"name", "min", "max"}
                or not {"name", "min"} <= set(bucket)):
            raise FoundryError("buckets use canonical keys name, min, max; label/min_days/max_days are unsupported")
        name, lower, upper = bucket["name"], bucket["min"], bucket.get("max")
        if not isinstance(name, str) or not name.strip() or name != name.strip() or name == "not_due" or name in names:
            raise FoundryError("buckets names must be unique nonblank text and cannot use reserved not_due")
        if (isinstance(lower, bool) or not isinstance(lower, int) or lower < 0
                or upper is not None and (isinstance(upper, bool) or not isinstance(upper, int) or upper < lower)):
            raise FoundryError("buckets min/max must be nonnegative integer days; max may be null and cannot be below min")
        if lower != next_min:
            raise FoundryError("buckets must start at min 0 and have contiguous inclusive bounds without gaps or overlaps")
        if upper is None and index != len(buckets) - 1:
            raise FoundryError("buckets with max null must be last")
        identity = _aging_bucket_id(bucket)
        if identity in identities:
            raise FoundryError("buckets must resolve to unique machine identities")
        names.add(name)
        identities.add(identity)
        next_min = upper + 1 if upper is not None else None


def _bucket_name(days: int | None, buckets: list[dict] | None = None) -> str:
    if days is None:
        return "not_due"
    for bucket in buckets or [
        {"name": "0-30", "min": 0, "max": 30},
        {"name": "31-60", "min": 31, "max": 60},
        {"name": "61-90", "min": 61, "max": 90},
        {"name": "90+", "min": 91, "max": None},
    ]:
        lower = bucket["min"]
        upper = bucket.get("max")
        if days >= lower and (upper is None or days <= upper):
            return _aging_bucket_id(bucket)
    raise FoundryError(f"no aging bucket covers {days} overdue days")


def _text_list(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FoundryError(f"{field} must be a list of text values")
    cleaned = [item.strip() for item in value if item.strip()]
    if len(cleaned) != len(value):
        raise FoundryError(f"{field} cannot include blank values")
    return cleaned


def _normalize_status_filter(raw: Any) -> dict[str, Any] | None:
    if raw in (None, {}):
        return None
    if not isinstance(raw, dict):
        raise FoundryError("status_filter must be an object")
    field = raw.get("field", "status")
    if not isinstance(field, str) or not field.strip():
        raise FoundryError("status_filter field must be nonempty text")
    include = _text_list(raw.get("include", raw.get("statuses")), "status_filter include")
    exclude = _text_list(
        raw.get("exclude", raw.get("exclude_statuses")), "status_filter exclude"
    )
    if include and exclude:
        raise FoundryError("status_filter cannot combine include and exclude")
    mapping = raw.get("mapping", {})
    if not isinstance(mapping, dict):
        raise FoundryError("status_filter mapping must be an object")
    aliases: dict[str, str] = {}
    canonical_values = set(include or exclude)
    for canonical, values in mapping.items():
        if not isinstance(canonical, str) or not canonical.strip():
            raise FoundryError("status_filter mapping keys must be nonempty text")
        canonical = canonical.strip()
        canonical_values.add(canonical)
        folded_canonical = canonical.casefold()
        if folded_canonical in aliases and aliases[folded_canonical] != canonical:
            raise FoundryError("status_filter mapping aliases must be unique")
        aliases[folded_canonical] = canonical
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise FoundryError("status_filter mapping values must be lists of text")
        for value in values:
            if not value.strip():
                raise FoundryError("status_filter mapping aliases cannot be blank")
            alias = value.strip().casefold()
            if alias in aliases and aliases[alias] != canonical:
                raise FoundryError("status_filter mapping aliases must be unique")
            aliases[alias] = canonical
    return {
        "field": field.strip(),
        "include": include,
        "exclude": exclude,
        "mapping": mapping,
        "aliases": aliases,
        "canonical_values": {value.casefold(): value for value in canonical_values},
    }


def _invoice_status(invoice: dict, status_filter: dict[str, Any] | None) -> dict:
    if not status_filter:
        return {
            "raw_status": None,
            "status": None,
            "included": True,
            "exclusion_reason": None,
        }
    raw_status = _text(invoice.get(status_filter["field"]))
    if not raw_status:
        status = "unknown"
        known = False
        missing = True
    else:
        status = status_filter["aliases"].get(raw_status.casefold())
        if status is None:
            status = status_filter["canonical_values"].get(raw_status.casefold())
        known = status is not None
        if status is None:
            status = "unknown"
        missing = False
    include = status_filter["include"]
    exclude = status_filter["exclude"]
    included = True
    reason = None
    if include and status.casefold() not in {value.casefold() for value in include}:
        included = False
        if missing:
            reason = "missing_status"
        elif not known:
            reason = "unknown_status"
        else:
            reason = "status_not_included"
    elif exclude and status.casefold() in {value.casefold() for value in exclude}:
        included = False
        reason = "status_excluded"
    return {
        "raw_status": raw_status or None,
        "status": status,
        "included": included,
        "exclusion_reason": reason,
    }


def _scope_amount_rows(amounts: dict[tuple[str, str, str, str], Decimal]) -> list[dict]:
    return [
        {
            "ledger": ledger,
            "organization": organization,
            "currency": currency,
            "unit": unit,
            "open_amount": _money(amount),
        }
        for ledger, organization, currency, unit in sorted(amounts)
        for amount in [amounts[(ledger, organization, currency, unit)]]
    ]


def _aging_row_key(*, as_of: str, parts: tuple[Any, ...]) -> str:
    return _hash({"as_of": as_of, "parts": parts})[:16]


def compute_receivables_aging(
    invoices: list[dict],
    activity: list[dict] | None = None,
    *,
    as_of: str | date,
    scope: dict[str, Any] | None = None,
    buckets: list[dict] | None = None,
    status_filter: dict[str, Any] | None = None,
) -> dict:
    """Compute open receivables and aging buckets as of a point in time.

    ``activity`` contains payment, allocation, credit, and writeoff records.
    Only records with ``effective_date <= as_of`` reduce the open balance.
    """

    scope = _require_scope(scope, "receivables aging")
    cutoff = _date(as_of, "as_of")
    validate_aging_buckets(buckets)
    bucket_labels = {"not_due": "not_due"}
    if buckets:
        bucket_labels.update({_aging_bucket_id(bucket): bucket["name"] for bucket in buckets})
    if "period" in scope:
        other_scope = {key: value for key, value in scope.items() if key != "period"}
        if any(_matches_scope(invoice, other_scope) and invoice.get("period") in (None, "")
               for invoice in invoices):
            raise FoundryError("scope.period cannot filter invoices whose source period is missing; as_of is the aging cutoff, "
                               "not a source period. Omit scope.period for unperiodized invoices or bind an explicit source period")
    normalized_status_filter = _normalize_status_filter(status_filter)
    scoped_invoices = []
    future_invoices = []
    identities_by_invoice_id: dict[str, set[tuple]] = defaultdict(set)
    for invoice in invoices:
        identity = _identity(invoice, "invoice", scope)
        identities_by_invoice_id[identity[0]].add(identity)
        if not _matches_scope(invoice, scope):
            continue
        issued = _issue_date(invoice)
        if issued is not None and issued > cutoff:
            future_invoices.append(
                {
                    "invoice_id": identity[0],
                    "ledger": identity[1],
                    "organization": identity[2],
                    "currency": identity[3],
                    "unit": identity[4],
                    "issue_date": issued.isoformat(),
                }
            )
            continue
        scoped_invoices.append((identity, invoice))
    if any(len(identities) > 1 for identities in identities_by_invoice_id.values()):
        for row in activity or []:
            invoice_id = row.get("invoice_id")
            if invoice_id in identities_by_invoice_id and any(
                _missing_activity_identity_field(row, field, scope)
                for field in IDENTITY_FIELDS
            ):
                raise FoundryError(
                    "duplicate invoice ids require activity ledger, organization, currency, and unit"
                )
    invoice_identities = {identity for identity, _invoice in scoped_invoices}
    reductions: dict[tuple, Decimal] = defaultdict(Decimal)
    future_activity = []
    evidence_activity: dict[str, list[dict]] = defaultdict(list)
    overapplied = []
    warnings = []
    seen_activity: dict[tuple, str] = {}

    for row in activity or []:
        invoice_id = row.get("invoice_id")
        if not isinstance(invoice_id, str) or not invoice_id:
            raise FoundryError("activity invoice_id must be nonempty text")
        activity_id = row.get("id")
        if not isinstance(activity_id, str) or not activity_id:
            raise FoundryError("activity id must be nonempty text")
        kind = row.get("kind")
        if kind not in REDUCTION_KINDS:
            raise FoundryError(
                "activity kind must be payment, allocation, credit, or writeoff"
            )
        identity = _identity(row, "activity", scope)
        if identity not in invoice_identities:
            continue
        if not _activity_matches_scope(row, scope):
            raise FoundryError("activity scope does not match receivables aging scope")
        activity_key = (
            row.get("source_system"),
            row.get("tenant"),
            *identity,
            activity_id,
        )
        fingerprint = _stable_json(row)
        if activity_key in seen_activity:
            if seen_activity[activity_key] != fingerprint:
                raise FoundryError("duplicate activity identity has conflicting values")
            warnings.append(f"duplicate activity ignored: {activity_id}")
            continue
        seen_activity[activity_key] = fingerprint
        effective = _date(row.get("effective_date"), "activity effective_date")
        amount = _decimal(row.get("amount"), "activity amount")
        if amount < 0 and not row.get("reversal"):
            raise FoundryError("negative activity amount requires reversal=true")
        signed = amount
        evidence = {
            "id": activity_id,
            "kind": kind,
            "effective_date": effective.isoformat(),
            "amount": _money(signed),
            "ledger": identity[1],
            "organization": identity[2],
            "currency": identity[3],
            "unit": identity[4],
        }
        if effective <= cutoff:
            reductions[identity] += signed
            evidence_activity["|".join(identity)].append(evidence)
        else:
            future_activity.append(evidence | {"invoice_id": invoice_id})

    detail_rows = []
    excluded_detail_rows = []
    summary: dict[tuple[str, str, str, str, str], Decimal] = defaultdict(Decimal)
    included_by_scope: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    excluded_by_scope: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    total_by_scope_before_filter: dict[tuple[str, str, str, str], Decimal] = defaultdict(
        Decimal
    )
    for identity, invoice in scoped_invoices:
        invoice_id, ledger, organization, currency, unit = identity
        due = _date(invoice.get("due_date"), "invoice due_date")
        amount = _decimal(invoice.get("amount"), "invoice amount")
        settled = reductions[identity]
        open_amount = amount - settled
        if open_amount < 0:
            overapplied.append(
                {
                    "invoice_id": invoice_id,
                    "ledger": ledger,
                    "organization": organization,
                    "currency": currency,
                    "unit": unit,
                    "overapplied_amount": _money(-open_amount),
                    "settled_amount": _money(settled),
                    "original_amount": _money(amount),
                }
            )
        if open_amount <= 0:
            continue
        overdue_days = None if due > cutoff else (cutoff - due).days
        bucket = _bucket_name(overdue_days, buckets)
        scope_key = (ledger, organization, currency, unit)
        total_by_scope_before_filter[scope_key] += open_amount
        status = _invoice_status(invoice, normalized_status_filter)
        detail = {
            "result_key": _aging_row_key(as_of=cutoff.isoformat(), parts=identity),
            "invoice_id": invoice_id,
            "customer": invoice.get("customer"),
            "organization": organization,
            "ledger": ledger,
            "currency": currency,
            "unit": unit,
            "as_of": cutoff.isoformat(),
            "due_date": due.isoformat(),
            "original_amount": _money(amount),
            "settled_amount": _money(settled),
            "open_amount": _money(open_amount),
            "overdue_days": overdue_days,
            "bucket": bucket,
            "bucket_label": bucket_labels.get(bucket, bucket),
            "raw_status": status["raw_status"],
            "status": status["status"],
        }
        if status["included"]:
            summary[(ledger, organization, currency, unit, bucket)] += open_amount
            included_by_scope[scope_key] += open_amount
            detail_rows.append(detail)
        else:
            excluded_by_scope[scope_key] += open_amount
            excluded_detail_rows.append(
                detail | {"exclusion_reason": status["exclusion_reason"]}
            )

    ordered_buckets = ["not_due", "0-30", "31-60", "61-90", "90+"]
    if buckets:
        ordered_buckets = ["not_due", *[_aging_bucket_id(bucket) for bucket in buckets]]
    groups = sorted({identity[1:5] for identity, _invoice in scoped_invoices})
    rows = [
        {
            "result_key": _aging_row_key(
                as_of=cutoff.isoformat(),
                parts=(ledger, organization, currency, unit, name),
            ),
            "ledger": ledger,
            "organization": organization,
            "currency": currency,
            "unit": unit,
            "as_of": cutoff.isoformat(),
            "bucket": name,
            "bucket_label": bucket_labels.get(name, name),
            "open_amount": _money(
                summary[(ledger, organization, currency, unit, name)]
            ),
        }
        for ledger, organization, currency, unit in groups
        for name in ordered_buckets
    ]
    total_by_scope = [
        {
            "ledger": ledger,
            "organization": organization,
            "currency": currency,
            "unit": unit,
            "open_amount": _money(
                sum(
                    (
                        summary[(ledger, organization, currency, unit, bucket)]
                        for bucket in ordered_buckets
                    ),
                    Decimal("0"),
                )
            ),
        }
        for ledger, organization, currency, unit in groups
    ]
    return {
        "columns": [
            {"name": "result_key", "type": "string"},
            {"name": "ledger", "type": "string"},
            {"name": "organization", "type": "string"},
            {"name": "currency", "type": "string"},
            {"name": "unit", "type": "string"},
            {"name": "as_of", "type": "date"},
            {"name": "bucket", "type": "string"},
            {"name": "bucket_label", "type": "string"},
            {"name": "open_amount", "type": "decimal"},
        ],
        "rows": rows,
        "detail_columns": [
            {"name": "result_key", "type": "string"},
            {"name": "invoice_id", "type": "string"},
            {"name": "customer", "type": "string"},
            {"name": "organization", "type": "string"},
            {"name": "ledger", "type": "string"},
            {"name": "currency", "type": "string"},
            {"name": "unit", "type": "string"},
            {"name": "as_of", "type": "date"},
            {"name": "due_date", "type": "date"},
            {"name": "open_amount", "type": "decimal"},
            {"name": "overdue_days", "type": "integer"},
            {"name": "bucket", "type": "string"},
            {"name": "bucket_label", "type": "string"},
            {"name": "raw_status", "type": "string"},
            {"name": "status", "type": "string"},
        ],
        "detail_rows": detail_rows,
        "excluded_detail_columns": [
            {"name": "result_key", "type": "string"},
            {"name": "invoice_id", "type": "string"},
            {"name": "customer", "type": "string"},
            {"name": "organization", "type": "string"},
            {"name": "ledger", "type": "string"},
            {"name": "currency", "type": "string"},
            {"name": "unit", "type": "string"},
            {"name": "as_of", "type": "date"},
            {"name": "due_date", "type": "date"},
            {"name": "open_amount", "type": "decimal"},
            {"name": "overdue_days", "type": "integer"},
            {"name": "bucket", "type": "string"},
            {"name": "bucket_label", "type": "string"},
            {"name": "raw_status", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "exclusion_reason", "type": "string"},
        ],
        "excluded_detail_rows": excluded_detail_rows,
        "row_count": len(rows),
        "evidence": {
            "as_of": cutoff.isoformat(),
            "invoice_count": len(detail_rows),
            "activity_applied": dict(evidence_activity),
            "future_activity_ignored": future_activity,
            "future_invoices_ignored": future_invoices,
            "overapplied": overapplied,
            "total_open_amount_by_scope": total_by_scope,
            "status_filter": (
                {
                    "field": normalized_status_filter["field"],
                    "include": normalized_status_filter["include"],
                    "exclude": normalized_status_filter["exclude"],
                    "mapping": normalized_status_filter["mapping"],
                    "status_evaluation_mode": "current_state",
                    "included_open_amount_by_scope": _scope_amount_rows(
                        included_by_scope
                    ),
                    "excluded_open_amount_by_scope": _scope_amount_rows(
                        excluded_by_scope
                    ),
                    "total_scope_open_amount_by_scope": _scope_amount_rows(
                        total_by_scope_before_filter
                    ),
                    "included": detail_rows,
                    "excluded": excluded_detail_rows,
                }
                if normalized_status_filter
                else None
            ),
        },
        "assumptions": [
            {
                "label": "Receivable reductions",
                "source": "declared_activity",
                "value": (
                    "payments, allocations, credits, and writeoffs reduce open "
                    "receivables by effective_date"
                ),
            }
        ],
        "warnings": (
            warnings
            + (
                [
                    "receivables status filter uses current invoice status; historical status as of the aging date is unavailable"
                ]
                if normalized_status_filter
                else []
            )
        ),
    }


def _cash_event(
    row: dict,
    kind: str,
    actual_cutoff: date,
    scenario: dict | None,
    scope: dict[str, str],
) -> dict | None:
    for field in IDENTITY_FIELDS:
        if _field(row, field) in (None, ""):
            raise FoundryError(f"{kind} identity requires {field}")
    if not _matches_identity_scope(row, scope):
        return None
    event_date = _date(row.get("date"), f"{kind} date")
    amount = _decimal(row.get("amount"), f"{kind} amount")
    if amount < 0:
        raise FoundryError(f"{kind} amount must be nonnegative")
    declared_status = row.get("status")
    if declared_status in {"forecast", "planned"} and event_date <= actual_cutoff:
        raise FoundryError(f"{kind} before actual_cutoff cannot be forecast")
    shifted_from = None
    if kind == "receipt" and scenario:
        delay_days = int(scenario.get("delay_receipts_days", 0) or 0)
        if delay_days and event_date > actual_cutoff:
            shifted_from = event_date
            event_date = event_date + timedelta(days=delay_days)
    return {
        "id": row.get("id"),
        "kind": kind,
        "date": event_date,
        "amount": amount,
        "status": "actual" if event_date <= actual_cutoff else "planned",
        "shifted_from": shifted_from,
        "metadata": {
            key: value
            for key, value in row.items()
            if key not in {"id", "date", "amount"}
        },
        "identity": tuple(scope[field] for field in IDENTITY_FIELDS),
    }


def _ignored_cash_event(row: dict, kind: str) -> dict:
    return {
        "id": row.get("id"),
        "kind": kind,
        "date": row.get("date"),
        "amount": str(row.get("amount")),
        "ledger": _field(row, "ledger"),
        "organization": _field(row, "organization"),
        "currency": _field(row, "currency"),
        "unit": _field(row, "unit"),
    }


def forecast_cash_13_weeks(
    *,
    opening_cash: Any,
    start_date: str | date,
    actual_cutoff: str | date,
    receipts: list[dict] | None = None,
    payments: list[dict] | None = None,
    scenario: dict | None = None,
    scope: dict[str, Any] | None = None,
    weeks: int = 13,
) -> dict:
    """Build a 13-week cash forecast without mutating input events."""

    if weeks <= 0:
        raise FoundryError("weeks must be positive")
    forecast_scope = _require_single_identity_scope(scope, "cash forecast")
    start = _date(start_date, "start_date")
    cutoff = _date(actual_cutoff, "actual_cutoff")
    opening = _decimal(opening_cash, "opening_cash")
    events = []
    ignored_events = []
    diagnostics = []
    seen_event_fingerprints: dict[tuple, str] = {}
    for kind, records in (("receipt", receipts or []), ("payment", payments or [])):
        for row in records:
            event = _cash_event(row, kind, cutoff, scenario, forecast_scope)
            if event is None:
                ignored_events.append(_ignored_cash_event(row, kind))
            else:
                event_key = (event["kind"], event["id"], *event["identity"])
                fingerprint = _stable_json(row)
                if event_key in seen_event_fingerprints:
                    if seen_event_fingerprints[event_key] != fingerprint:
                        raise FoundryError(
                            "duplicate cash event identity has conflicting values"
                        )
                    diagnostics.append(
                        {
                            "severity": "info",
                            "code": "duplicate_cash_event_ignored",
                            "message": "duplicate cash event ignored",
                            "event_id": event["id"],
                            "kind": event["kind"],
                        }
                    )
                    continue
                seen_event_fingerprints[event_key] = fingerprint
                events.append(event)
    horizon_end = start + timedelta(days=weeks * 7 - 1)
    rows = []
    opening_balance = opening
    outside_horizon = []
    for index in range(weeks):
        week_start = start + timedelta(days=index * 7)
        week_end = week_start + timedelta(days=6)
        week_events = [
            event for event in events if week_start <= event["date"] <= week_end
        ]
        receipts_amount = sum(
            (event["amount"] for event in week_events if event["kind"] == "receipt"),
            Decimal("0"),
        )
        payments_amount = sum(
            (event["amount"] for event in week_events if event["kind"] == "payment"),
            Decimal("0"),
        )
        closing = opening_balance + receipts_amount - payments_amount
        rows.append(
            {
                "week": index + 1,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "opening_cash": _money(opening_balance),
                "receipts": _money(receipts_amount),
                "payments": _money(payments_amount),
                "closing_cash": _money(closing),
                "event_ids": [event["id"] for event in week_events],
            }
        )
        opening_balance = closing
    for event in events:
        if event["date"] < start or event["date"] > horizon_end:
            outside_horizon.append(
                {
                    "id": event["id"],
                    "kind": event["kind"],
                    "date": event["date"].isoformat(),
                    "amount": _money(event["amount"]),
                }
            )
    point_balances = {}
    running = opening
    for day_offset in range((horizon_end - start).days + 1):
        current = start + timedelta(days=day_offset)
        todays_events = (event for event in events if event["date"] == current)
        for event in sorted(
            todays_events,
            key=lambda item: (item["kind"], str(item["id"])),
        ):
            running += (
                event["amount"] if event["kind"] == "receipt" else -event["amount"]
            )
        point_balances[current.isoformat()] = _money(running)
    return {
        "columns": [
            {"name": "week", "type": "integer"},
            {"name": "week_start", "type": "date"},
            {"name": "week_end", "type": "date"},
            {"name": "opening_cash", "type": "decimal"},
            {"name": "receipts", "type": "decimal"},
            {"name": "payments", "type": "decimal"},
            {"name": "closing_cash", "type": "decimal"},
        ],
        "rows": rows,
        "row_count": len(rows),
        "evidence": {
            "actual_cutoff": cutoff.isoformat(),
            "horizon_start": start.isoformat(),
            "horizon_end": horizon_end.isoformat(),
            "scope": forecast_scope,
            "ignored_events": ignored_events,
            "events": [
                {
                    "id": event["id"],
                    "kind": event["kind"],
                    "date": event["date"].isoformat(),
                    "amount": _money(event["amount"]),
                    "status": event["status"],
                    "shifted_from": (
                        event["shifted_from"].isoformat()
                        if event["shifted_from"]
                        else None
                    ),
                }
                for event in events
            ],
            "outside_horizon": outside_horizon,
            "point_balances": point_balances,
        },
        "assumptions": [
            {
                "label": scenario.get("label", "base") if scenario else "base",
                "source": (
                    scenario.get("source", "declared_inputs")
                    if scenario
                    else "declared_inputs"
                ),
                "value": deepcopy(scenario) if scenario else {},
            }
        ],
        "warnings": [],
        "diagnostics": diagnostics,
    }


def _formula_dependencies(expression: str) -> set[str]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FoundryError(
            "driver formula must be a restricted arithmetic expression"
        ) from exc
    dependencies = set()
    for node in ast.walk(tree):
        if not isinstance(node, OPERATORS + BIN_OPS + UNARY_OPS + (ast.Load,)):
            raise FoundryError("driver formula contains an unsupported operator")
        if isinstance(node, ast.BinOp) and not isinstance(node.op, BIN_OPS):
            raise FoundryError("driver formula contains an unsupported operator")
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, UNARY_OPS):
            raise FoundryError("driver formula contains an unsupported operator")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, str)):
            raise FoundryError(
                "driver formula constants must be decimal strings or integers"
            )
        if isinstance(node, ast.Name):
            dependencies.add(node.id)
    return dependencies


def _eval_formula(expression: str, values: dict[str, Decimal]) -> Decimal:
    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise FoundryError(f"missing driver data: {node.id}")
            return values[node.id]
        if isinstance(node, ast.Constant):
            return _decimal(node.value, "formula constant")
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise FoundryError("driver formula divides by zero")
            return left / right
        raise FoundryError("driver formula contains an unsupported operator")

    return visit(ast.parse(expression, mode="eval"))


def validate_driver_model(
    drivers: list[dict],
    *,
    inputs: dict[str, Any] | None = None,
    manager_assumptions: dict[str, Any] | None = None,
) -> dict:
    """Validate a small declared driver DAG and calculate derived drivers."""

    declared = {}
    for driver in drivers:
        name = driver.get("name")
        if not isinstance(name, str) or not name:
            raise FoundryError("driver name must be nonempty text")
        if name in declared:
            raise FoundryError(f"duplicate driver: {name}")
        formula = driver.get("formula")
        direct = bool(driver.get("direct_assumption"))
        if (formula is None and not direct) or (formula is not None and direct):
            raise FoundryError(
                "driver must declare exactly one formula or direct_assumption"
            )
        declared[name] = deepcopy(driver)

    graph = {name: set() for name in declared}
    formulas = {}
    for name, driver in declared.items():
        if "formula" in driver:
            deps = set(
                driver.get("depends_on") or _formula_dependencies(driver["formula"])
            )
            unknown = deps - set(declared)
            if unknown:
                raise FoundryError(
                    f"driver dependency is undeclared: {sorted(unknown)[0]}"
                )
            formula_deps = _formula_dependencies(driver["formula"])
            if deps != formula_deps:
                raise FoundryError(
                    f"driver {name} dependencies do not match formula references"
                )
            graph[name] = deps
            formulas[name] = driver["formula"]

    incoming = {name: 0 for name in declared}
    outgoing = defaultdict(list)
    for name, deps in graph.items():
        for dep in deps:
            incoming[name] += 1
            outgoing[dep].append(name)
    ready = deque(sorted(name for name, degree in incoming.items() if degree == 0))
    order = []
    while ready:
        name = ready.popleft()
        order.append(name)
        for child in sorted(outgoing[name]):
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if len(order) != len(declared):
        raise FoundryError("driver dependency cycle refused")

    values = {
        key: _decimal(value, f"input {key}") for key, value in (inputs or {}).items()
    }
    formula_inputs = sorted(set(values) & set(formulas))
    if formula_inputs:
        raise FoundryError(
            f"formula driver inputs are not accepted: {', '.join(formula_inputs)}"
        )
    assumptions = []
    manager_assumptions = manager_assumptions or {}
    for name in order:
        driver = declared[name]
        if name in values:
            continue
        if driver.get("direct_assumption"):
            if name not in manager_assumptions:
                raise FoundryError(f"missing driver data: {name}")
            source = manager_assumptions[name]
            if (
                not isinstance(source, dict)
                or "value" not in source
                or not source.get("label")
            ):
                raise FoundryError(
                    f"manager assumption for {name} requires value and label"
                )
            values[name] = _decimal(source["value"], f"manager assumption {name}")
            assumptions.append(
                {
                    "driver": name,
                    "label": source["label"],
                    "source": source.get("source", "manager_direct"),
                    "value": _money(values[name]),
                }
            )
        elif name in formulas:
            values[name] = _eval_formula(formulas[name], values)

    rows = [
        {
            "driver": name,
            "value": _money(values[name]),
            "source": (
                "derived"
                if name in formulas
                else "input"
                if name in (inputs or {})
                else "manager_direct"
            ),
            "formula": formulas.get(name),
            "depends_on": sorted(graph[name]),
        }
        for name in order
    ]
    return {
        "columns": [
            {"name": "driver", "type": "string"},
            {"name": "value", "type": "decimal"},
            {"name": "source", "type": "string"},
            {"name": "formula", "type": "string"},
        ],
        "rows": rows,
        "row_count": len(rows),
        "evidence": {
            "topological_order": order,
            "declared_dependencies": {
                key: sorted(value) for key, value in graph.items()
            },
        },
        "assumptions": assumptions,
        "warnings": [],
    }


def create_child_scenario(
    parent: dict,
    changes: dict,
    *,
    label: str,
    actual_cutoff: str | date | None = None,
) -> dict:
    """Create an immutable child scenario record with serialized parent diffs."""

    if not isinstance(parent, dict) or "id" not in parent:
        raise FoundryError("parent scenario requires an id")
    if not isinstance(changes, dict) or not changes:
        raise FoundryError("scenario changes must be a nonempty object")
    base_inputs = deepcopy(parent.get("inputs", {}))
    child_inputs = deepcopy(base_inputs)
    child_inputs.update(deepcopy(changes))
    parent_hash = parent.get("input_hash") or _hash(base_inputs)
    record = {
        "id": _hash({"parent": parent["id"], "label": label, "changes": changes})[:16],
        "label": label,
        "parent_id": parent["id"],
        "actual_cutoff": (
            _date(actual_cutoff, "actual_cutoff").isoformat()
            if actual_cutoff is not None
            else parent.get("actual_cutoff")
        ),
        "inputs": child_inputs,
        "input_hash": _hash(child_inputs),
        "parent_input_hash": parent_hash,
        "diff": [
            {"key": key, "parent": base_inputs.get(key), "child": child_inputs.get(key)}
            for key in sorted(changes)
        ],
    }
    return record
