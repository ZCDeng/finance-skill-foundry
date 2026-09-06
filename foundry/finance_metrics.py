"""Deterministic finance metric evaluation over normalized facts."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any

FLOW_SIGNS = {"revenue": Decimal("1"), "cost": Decimal("-1"), "expense": Decimal("-1")}
FINANCE_IDENTITY = ("ledger", "organization", "period")
INACTIVE_SOURCE_STATUS = {"duplicate_pull", "deleted", "void", "voided"}


def evaluate_metric(normalized: dict, spec: dict) -> dict:
    """Evaluate a small finance metric spec without persistence or side effects."""

    rows = [row for row in normalized.get("rows", []) if isinstance(row, dict)]
    diagnostics = list(normalized.get("diagnostics", []))
    kind = spec.get("kind") or spec.get("type") or "management_pnl"
    if kind == "management_pnl":
        result = _management_pnl(rows, spec, diagnostics)
    elif kind == "ratio":
        result = _ratio(rows, spec, diagnostics)
    elif kind == "account_total":
        result = _account_total(rows, spec, diagnostics)
    elif kind == "control_totals":
        result = _control_totals(normalized, diagnostics)
    else:
        diagnostics.append(
            _diag("error", "unsupported_metric", f"unsupported metric kind: {kind}")
        )
        result = {"columns": [], "rows": []}
    return {
        "domain": {
            "input": "foundry.finance.normalized.v1",
            "output": "foundry.finance.metric.v1",
            "capabilities": ["analysis"],
            "excluded_capabilities": ["posting", "payment_execution"],
        },
        "metric_id": spec.get("id") or kind,
        "columns": result["columns"],
        "rows": result["rows"],
        "diagnostics": diagnostics,
    }


def _management_pnl(rows: list[dict], spec: dict, diagnostics: list[dict]) -> dict:
    dimensions = _dimensions(spec)
    scenario_bindings = spec.get("scenario_bindings") or {}
    if not scenario_bindings:
        diagnostics.append(
            _diag(
                "warning",
                "implicit_scenario_binding",
                "actual/budget/forecast bindings were not explicit",
            )
        )
    signs = {
        **FLOW_SIGNS,
        **{str(k): _dec(v) for k, v in (spec.get("account_signs") or {}).items()},
    }
    wanted = set(spec.get("accounts") or ["revenue", "cost", "expense"])
    buckets: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if not _active_row(row):
            continue
        if not _passes_filters(row, spec.get("filters") or {}):
            continue
        account = row.get("management_account")
        if account not in wanted:
            continue
        scenario = _scenario_label(str(row.get("scenario") or ""), scenario_bindings)
        key = tuple(row.get(dim) for dim in dimensions) + (
            scenario,
            row.get("currency"),
            row.get("unit"),
        )
        bucket = buckets.setdefault(
            key,
            {
                **{dim: row.get(dim) for dim in dimensions},
                "scenario": scenario,
                "currency": row.get("currency"),
                "unit": row.get("unit"),
                "revenue": Decimal("0"),
                "cost": Decimal("0"),
                "expense": Decimal("0"),
                "source_rows": defaultdict(list),
            },
        )
        contribution = _dec(row["amount"]) * signs.get(str(account), Decimal("1"))
        bucket[str(account)] += contribution
        bucket["source_rows"][str(account)].append(row["source"])
    out = []
    for bucket in sorted(
        buckets.values(),
        key=lambda item: tuple(
            str(item.get(dim) or "")
            for dim in (*dimensions, "scenario", "currency", "unit")
        ),
    ):
        profit = bucket["revenue"] + bucket["cost"] + bucket["expense"]
        source_rows = sorted(
            (ref for refs in bucket["source_rows"].values() for ref in refs),
            key=lambda ref: (
                ref.get("dataset_id", ""),
                ref.get("source_row", 0),
                ref.get("row_index", 0),
            ),
        )
        out.append(
            {
                **{dim: bucket.get(dim) for dim in dimensions},
                "scenario": bucket["scenario"],
                "currency": bucket["currency"],
                "unit": bucket["unit"],
                "revenue": _money(bucket["revenue"]),
                "cost": _money(-bucket["cost"]),
                "expense": _money(-bucket["expense"]),
                "profit": _money(profit),
                "source_rows": source_rows,
                "evidence": {
                    "revenue": bucket["source_rows"].get("revenue", []),
                    "cost": bucket["source_rows"].get("cost", []),
                    "expense": bucket["source_rows"].get("expense", []),
                    "profit": source_rows,
                },
            }
        )
    return {
        "columns": [
            *dimensions,
            "scenario",
            "currency",
            "unit",
            "revenue",
            "cost",
            "expense",
            "profit",
        ],
        "rows": out,
    }


def _ratio(rows: list[dict], spec: dict, diagnostics: list[dict]) -> dict:
    dimensions = _dimensions(spec)
    numerator_accounts = {
        str(account) for account in spec.get("numerator_accounts", [])
    }
    denominator_accounts = {
        str(account) for account in spec.get("denominator_accounts", [])
    }
    signs = {
        **{
            account: Decimal("1")
            for account in numerator_accounts | denominator_accounts
        },
        **{str(k): _dec(v) for k, v in (spec.get("account_signs") or {}).items()},
    }
    buckets: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if not _active_row(row):
            continue
        if not _passes_filters(row, spec.get("filters") or {}):
            continue
        account = str(row.get("management_account") or "")
        if account not in numerator_accounts and account not in denominator_accounts:
            continue
        key = tuple(row.get(dim) for dim in dimensions) + (
            row.get("scenario"),
            row.get("currency"),
            row.get("unit"),
        )
        bucket = buckets.setdefault(
            key,
            {
                **{dim: row.get(dim) for dim in dimensions},
                "scenario": row.get("scenario"),
                "currency": row.get("currency"),
                "unit": row.get("unit"),
                "numerator": Decimal("0"),
                "denominator": Decimal("0"),
                "source_rows": [],
            },
        )
        value = _dec(row["amount"]) * signs.get(account, Decimal("1"))
        if account in numerator_accounts:
            bucket["numerator"] += value
        if account in denominator_accounts:
            bucket["denominator"] += value
        bucket["source_rows"].append(row["source"])
    out = []
    for bucket in sorted(
        buckets.values(),
        key=lambda item: tuple(
            str(item.get(dim) or "")
            for dim in (*dimensions, "scenario", "currency", "unit")
        ),
    ):
        denominator = bucket["denominator"]
        if denominator == 0:
            ratio = None
            diagnostics.append(
                _diag(
                    "warning",
                    "ratio_denominator_zero",
                    "ratio denominator is zero",
                    group={dim: bucket.get(dim) for dim in dimensions},
                )
            )
        else:
            ratio = bucket["numerator"] / denominator
        out.append(
            {
                **{dim: bucket.get(dim) for dim in dimensions},
                "scenario": bucket["scenario"],
                "currency": bucket["currency"],
                "unit": bucket["unit"],
                "numerator": _money(bucket["numerator"]),
                "denominator": _money(denominator),
                "ratio": None if ratio is None else _money(ratio),
                "source_rows": bucket["source_rows"],
            }
        )
    return {
        "columns": [
            *dimensions,
            "scenario",
            "currency",
            "unit",
            "numerator",
            "denominator",
            "ratio",
        ],
        "rows": out,
    }


def _account_total(rows: list[dict], spec: dict, diagnostics: list[dict]) -> dict:
    dimensions = _dimensions(spec)
    accounts = {str(account) for account in spec.get("accounts", [])}
    account_behavior = spec.get("account_behavior") or {}
    requested_dimensions = [str(dim) for dim in spec.get("dimensions", [])]
    include_period = "period" in requested_dimensions
    has_stock = any(account_behavior.get(account) == "stock" for account in accounts)
    if has_stock and not include_period:
        dimensions = list(dict.fromkeys([*dimensions, "period"]))
        diagnostics.append(
            _diag(
                "warning",
                "stock_period_not_summed",
                "stock accounts are returned by period instead of summed across periods",
            )
        )
    buckets: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if not _active_row(row):
            continue
        if not _passes_filters(row, spec.get("filters") or {}):
            continue
        account = str(row.get("management_account") or "")
        if accounts and account not in accounts:
            continue
        key = tuple(row.get(dim) for dim in dimensions) + (
            row.get("scenario"),
            row.get("currency"),
            row.get("unit"),
        )
        bucket = buckets.setdefault(
            key,
            {
                **{dim: row.get(dim) for dim in dimensions},
                "scenario": row.get("scenario"),
                "currency": row.get("currency"),
                "unit": row.get("unit"),
                "amount": Decimal("0"),
                "source_rows": [],
            },
        )
        bucket["amount"] += _dec(row["amount"])
        bucket["source_rows"].append(row["source"])
    out = [
        {
            **{dim: bucket.get(dim) for dim in dimensions},
            "scenario": bucket["scenario"],
            "currency": bucket["currency"],
            "unit": bucket["unit"],
            "amount": _money(bucket["amount"]),
            "source_rows": bucket["source_rows"],
        }
        for bucket in sorted(
            buckets.values(),
            key=lambda item: tuple(
                str(item.get(dim) or "")
                for dim in (*dimensions, "scenario", "currency", "unit")
            ),
        )
    ]
    return {
        "columns": [*dimensions, "scenario", "currency", "unit", "amount"],
        "rows": out,
    }


def _control_totals(normalized: dict, diagnostics: list[dict]) -> dict:
    return {
        "columns": [
            "ledger",
            "organization",
            "period",
            "currency",
            "unit",
            "scenario",
            "management_account",
            "amount",
            "signed_amount",
            "row_count",
        ],
        "rows": list(normalized.get("control_totals", [])),
    }


def _passes_filters(row: dict, filters: dict) -> bool:
    for key, expected in filters.items():
        actual = row.get(key)
        if isinstance(expected, (list, tuple, set, frozenset)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _dimensions(spec: dict) -> list[str]:
    requested = [str(dim) for dim in spec.get("dimensions", [])]
    if spec.get("aggregate_dimensions") is True:
        return requested
    return list(dict.fromkeys([*FINANCE_IDENTITY, *requested]))


def _active_row(row: dict) -> bool:
    return (
        str(row.get("source_status") or "active").casefold()
        not in INACTIVE_SOURCE_STATUS
    )


def _scenario_label(value: str, bindings: dict) -> str:
    for label, source in bindings.items():
        if value == source or value == label:
            return str(label)
    return value


def _dec(value: Any) -> Decimal:
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, DivisionByZero, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc


def _money(value: Decimal) -> str:
    return format(value, "f")


def _diag(severity: str, code: str, message: str, **extra: Any) -> dict:
    return {"severity": severity, "code": code, "message": message, **extra}
