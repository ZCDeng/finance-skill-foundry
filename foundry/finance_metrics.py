"""Deterministic finance metric evaluation over normalized facts."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any

from foundry.display_numbers import display_amount, display_percent

FLOW_SIGNS = {"revenue": Decimal("1"), "cost": Decimal("-1"), "expense": Decimal("-1")}
"""Which way a bare amount moves profit, for rows that never say which side.

A source that carries no 借贷 column and no balance direction hands over a
magnitude and nothing else, so the account itself is the only thing left to read
the sign from. Where a row does say its side, that reading is wrong: a month-end
transfer debits revenue to close it out, and counting the debit as another
credit reports the month twice.
"""
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
    if not result["rows"] and kind != "control_totals":
        # Nothing failed, so the run is not failed -- but a metric that produced
        # no line at all answered no question, and a green run with an empty
        # table reads as "the number is nothing". Error severity is what marks
        # the run incomplete, which is the house signal for "do not build on it".
        diagnostics.append(
            _diag(
                "error",
                "empty_result",
                f"{kind} produced no rows from {len(rows)} fact rows"
                if rows
                else f"{kind} had no fact rows to read",
            )
        )
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
    undirected = 0
    counted = 0
    gross: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
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
        # A row that knows its side is summed by that side. 结转 vouchers debit
        # revenue to close the month, and the debit has to cancel the credit it
        # reverses; reading the sign off the account instead would count the
        # month twice, silently and with the run still green.
        if _states_its_side(row):
            contribution = -_dec(row["signed_amount"])
        else:
            undirected += 1
            contribution = _dec(row["amount"]) * signs.get(str(account), Decimal("1"))
        bucket[str(account)] += contribution
        bucket["source_rows"][str(account)].append(row["source"])
        gross[str(account)] += abs(contribution)
        counted += 1
    for account in sorted(wanted):
        net = sum((b[account] for b in buckets.values()), Decimal("0"))
        if gross[account] and not net:
            # Every entry met its reversal. On a journal that is what a closed
            # month looks like: the 结转 vouchers move the P&L accounts to
            # 本年利润, so the period's movement really is nil. Saying so beats
            # handing back a zero that looks like no activity.
            diagnostics.append(
                _diag(
                    "warning",
                    "account_nets_to_zero",
                    f"{account} nets to zero over {gross[account]} of gross movement; "
                    "a journal that includes the month-end 结转 vouchers cancels "
                    "itself, and the balances rather than the entries are what a "
                    "period P&L reads",
                )
            )
    if undirected:
        diagnostics.append(
            _diag(
                "warning",
                "amount_direction_assumed",
                f"{undirected} of {counted} rows carry no 借贷 or balance direction; "
                "their sign was taken from the management account, which cannot "
                "tell a reversal from an entry",
            )
        )
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
                "numerator_exact": _money(bucket["numerator"]),
                "denominator_exact": _money(denominator),
                "ratio_exact": None if ratio is None else _money(ratio),
                "numerator_display": _display_amount(bucket["numerator"], bucket["unit"]),
                "denominator_display": _display_amount(denominator, bucket["unit"]),
                "ratio_display": None if ratio is None else _display_percent(ratio),
                "display_value": None if ratio is None else _display_percent(ratio),
                "semantics": {
                    "metric_kind": "ratio",
                    "numerator_accounts": sorted(numerator_accounts),
                    "denominator_accounts": sorted(denominator_accounts),
                    "account_signs": {
                        account: _money(signs.get(account, Decimal("1")))
                        for account in sorted(numerator_accounts | denominator_accounts)
                    },
                    "precision": "exact_decimal",
                    "display_policy": "ratio_percent_2dp",
                },
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
            "numerator_exact",
            "denominator_exact",
            "ratio_exact",
            "display_value",
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


def _states_its_side(row: dict) -> bool:
    """Whether this row says which side it sits on, rather than a bare magnitude."""
    if row.get("debit_credit") or row.get("account_direction"):
        return True
    return (row.get("policies") or {}).get("amount_sign") == "debit_positive"


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


def _display_amount(value: Decimal, unit: str | None) -> str:
    amount = display_amount(value)
    return f"{amount} {unit}" if unit else amount


def _display_percent(value: Decimal) -> str:
    return display_percent(value)


def _diag(severity: str, code: str, message: str, **extra: Any) -> dict:
    return {"severity": severity, "code": code, "message": message, **extra}
