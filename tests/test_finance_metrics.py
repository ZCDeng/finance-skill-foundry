from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from foundry.finance_metrics import evaluate_metric
from foundry.finance_model import normalize_finance_dataset

FIXTURES = Path(__file__).parent / "fixtures" / "finance_baseline" / "scenarios"


def _csv(name: str) -> list[dict]:
    with (FIXTURES / name).open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _dataset(name: str, rows: list[dict]) -> dict:
    return {"id": name, "name": name, "rows": rows, "metadata": {"fixture": name}}


def _combine(*normalized: dict) -> dict:
    return {
        "domain": {"output": "foundry.finance.normalized.v1"},
        "rows": [row for item in normalized for row in item["rows"]],
        "diagnostics": [diag for item in normalized for diag in item["diagnostics"]],
        "control_totals": [
            row for item in normalized for row in item["control_totals"]
        ],
    }


def test_management_pnl_by_org_period_and_scenario_with_budget_variance() -> None:
    actual = normalize_finance_dataset(
        _dataset("service-ledger", _csv("service_ledger.csv")),
        {
            "ledger": "service-co",
            "organization": "华东",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "万元",
            "scenario": "actual",
        },
    )
    budget = normalize_finance_dataset(
        _dataset("service-budget", _csv("service_budget.csv")),
        {
            "ledger": "service-co",
            "organization": "华东",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "万元",
            "scenario": "budget",
        },
    )
    result = evaluate_metric(
        _combine(actual, budget),
        {
            "id": "management-pnl",
            "kind": "management_pnl",
            "dimensions": ["organization", "period"],
            "scenario_bindings": {"actual": "actual", "budget": "budget"},
        },
    )

    rows = {
        (row["scenario"], row["organization"], row["period"]): row
        for row in result["rows"]
    }
    assert Decimal(rows[("actual", "华东", "2026-08")]["profit"]) == Decimal("30")
    assert rows[("actual", "华东", "2026-08")]["ledger"] == "service-co"
    assert Decimal(rows[("budget", "华东", "2026-08")]["profit"]) == Decimal("25")
    assert Decimal(rows[("actual", "华东", "2026-08")]["profit"]) - Decimal(
        rows[("budget", "华东", "2026-08")]["profit"]
    ) == Decimal("5")
    assert (
        rows[("actual", "华东", "2026-08")]["evidence"]["profit"][0]["dataset_id"]
        == "service-ledger"
    )


def test_ratio_recomputes_from_numerator_and_denominator_not_prior_ratios() -> None:
    normalized = normalize_finance_dataset(
        _dataset("service-ledger", _csv("service_ledger.csv")),
        {
            "ledger": "service-co",
            "organization": "华东",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "万元",
            "scenario": "actual",
        },
    )
    result = evaluate_metric(
        normalized,
        {
            "id": "cost-rate",
            "kind": "ratio",
            "dimensions": ["organization", "period"],
            "numerator_accounts": ["cost"],
            "denominator_accounts": ["revenue"],
            "filters": {"scenario": "actual"},
        },
    )

    row = result["rows"][0]
    assert Decimal(row["numerator"]) == Decimal("70")
    assert Decimal(row["denominator"]) == Decimal("120")
    assert Decimal(row["ratio"]) == Decimal("70") / Decimal("120")


def test_stock_accounts_are_not_summed_across_periods() -> None:
    rows = [
        {
            "ledger": "x",
            "organization": "总部",
            "period": "2026-07",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "cash",
            "amount": "100",
            "source_row": "1",
        },
        {
            "ledger": "x",
            "organization": "总部",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "cash",
            "amount": "110",
            "source_row": "2",
        },
    ]
    normalized = normalize_finance_dataset(_dataset("balances", rows), {"ledger": "x"})
    result = evaluate_metric(
        normalized,
        {
            "id": "cash-balance",
            "kind": "account_total",
            "dimensions": ["organization"],
            "accounts": ["cash"],
            "account_behavior": {"cash": "stock"},
        },
    )

    assert [row["period"] for row in result["rows"]] == ["2026-07", "2026-08"]
    assert {row["scenario"] for row in result["rows"]} == {"actual"}
    assert [Decimal(row["amount"]) for row in result["rows"]] == [
        Decimal("100"),
        Decimal("110"),
    ]
    assert any(d["code"] == "stock_period_not_summed" for d in result["diagnostics"])


def test_control_totals_remain_split_by_currency_and_unit() -> None:
    normalized = normalize_finance_dataset(
        _dataset("multi-org", _csv("multi_org_ledger.csv")),
        {"ledger": "group-co", "period": "2026-08", "unit": "元"},
    )
    result = evaluate_metric(normalized, {"id": "controls", "kind": "control_totals"})

    currencies = {row["currency"] for row in result["rows"]}
    assert currencies == {"CNY", "USD"}
    assert any(d["code"] == "mixed_currency" for d in result["diagnostics"])


def test_price_quantity_fixture_can_be_preaggregated_without_join_fanout() -> None:
    normalized = normalize_finance_dataset(
        _dataset("commerce", _csv("commerce_ledger.csv")),
        {
            "ledger": "commerce-co",
            "organization": "总部",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
        },
    )
    result = evaluate_metric(
        normalized,
        {
            "id": "commerce-pnl",
            "kind": "management_pnl",
            "dimensions": ["organization", "period"],
            "scenario_bindings": {"actual": "actual", "budget": "budget"},
        },
    )

    rows = {row["scenario"]: row for row in result["rows"]}
    assert Decimal(rows["actual"]["revenue"]) == Decimal("132")
    assert Decimal(rows["budget"]["revenue"]) == Decimal("100")
    assert Decimal(rows["actual"]["profit"]) == Decimal("42")
    assert Decimal(rows["budget"]["profit"]) == Decimal("25")


def test_metrics_partition_by_ledger_unless_aggregate_is_explicit() -> None:
    rows = [
        {
            "ledger": "a",
            "organization": "总部",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "10",
        },
        {
            "ledger": "b",
            "organization": "总部",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "90",
        },
    ]
    normalized = normalize_finance_dataset(
        _dataset("two-ledgers", rows), {"organization": "总部"}
    )
    partitioned = evaluate_metric(
        normalized,
        {
            "kind": "management_pnl",
            "dimensions": ["organization"],
            "scenario_bindings": {"actual": "actual"},
        },
    )
    aggregate = evaluate_metric(
        normalized,
        {
            "kind": "management_pnl",
            "dimensions": ["organization"],
            "aggregate_dimensions": True,
            "scenario_bindings": {"actual": "actual"},
        },
    )

    assert [Decimal(row["revenue"]) for row in partitioned["rows"]] == [
        Decimal("10"),
        Decimal("90"),
    ]
    assert [Decimal(row["revenue"]) for row in aggregate["rows"]] == [Decimal("100")]


def test_metrics_exclude_inactive_source_refresh_rows() -> None:
    rows = [
        {
            "ledger": "x",
            "organization": "总部",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "100",
            "source_status": "active",
            "source": {"source_row": 1},
        },
        {
            "ledger": "x",
            "organization": "总部",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "200",
            "source_status": "VOIDED",
            "source": {"source_row": 2},
        },
        {
            "ledger": "x",
            "organization": "总部",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "300",
            "source_status": "duplicate_pull",
            "source": {"source_row": 3},
        },
        {
            "ledger": "x",
            "organization": "总部",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "400",
            "source_status": "deleted",
            "source": {"source_row": 4},
        },
    ]
    normalized = {
        "rows": rows,
        "diagnostics": [
            {"severity": "info", "code": "inactive_source_row", "message": "preserved"}
        ],
        "control_totals": [
            {
                "ledger": "x",
                "organization": "总部",
                "period": "2026-09",
                "currency": "CNY",
                "unit": "元",
                "scenario": "actual",
                "management_account": "revenue",
                "amount": "100",
                "signed_amount": "100",
                "row_count": 1,
            }
        ],
    }

    pnl = evaluate_metric(
        normalized,
        {
            "kind": "management_pnl",
            "dimensions": ["organization"],
            "scenario_bindings": {"actual": "actual"},
        },
    )
    total = evaluate_metric(
        normalized,
        {
            "kind": "account_total",
            "dimensions": ["organization"],
            "accounts": ["revenue"],
        },
    )
    ratio = evaluate_metric(
        normalized,
        {
            "kind": "ratio",
            "dimensions": ["organization"],
            "numerator_accounts": ["revenue"],
            "denominator_accounts": ["revenue"],
        },
    )

    assert Decimal(pnl["rows"][0]["revenue"]) == Decimal("100")
    assert Decimal(total["rows"][0]["amount"]) == Decimal("100")
    assert Decimal(ratio["rows"][0]["numerator"]) == Decimal("100")
    assert any(diag["code"] == "inactive_source_row" for diag in pnl["diagnostics"])
