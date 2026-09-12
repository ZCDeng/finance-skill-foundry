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
    assert row["numerator_exact"] == "70"
    assert row["denominator_exact"] == "120"
    assert Decimal(row["ratio_exact"]) == Decimal("70") / Decimal("120")
    assert row["display_value"] == "58.33%"
    assert row["semantics"]["numerator_accounts"] == ["cost"]
    assert row["semantics"]["denominator_accounts"] == ["revenue"]
    assert row["semantics"]["account_signs"] == {"cost": "1", "revenue": "1"}


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


def _ledger_rows(entries: list[tuple[str, str, str]]) -> list[dict]:
    """(科目代码, 借贷, 金额) as a ledger export spells them."""
    return [
        {
            "科目代码": code,
            "借贷": side,
            "金额": amount,
            "期间": "2026-08",
            "币种": "CNY",
            "单位": "元",
        }
        for code, side, amount in entries
    ]


def _normalized(entries: list[tuple[str, str, str]], mapping: dict[str, str]) -> dict:
    return normalize_finance_dataset(
        _dataset("ledger", _ledger_rows(entries)),
        {
            "ledger": "华宸物业",
            "organization": "集团合并",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
        },
        account_map={"rows": [
            {"account_code": code, "management_account": account}
            for code, account in mapping.items()
        ]},
    )


def test_a_closing_voucher_cancels_the_entry_it_reverses() -> None:
    """月末结转 debits revenue to close the month; it is not a second sale.

    Summing magnitudes by a sign read off the account counted the debit as
    another credit, so revenue came back at twice the month, with the run green
    and no diagnostic to notice.
    """
    normalized = _normalized(
        [
            ("6001", "credit", "400"),   # 确认收入
            ("6001", "debit", "400"),    # 月末结转至本年利润
            ("6401", "debit", "300"),
            ("6401", "credit", "300"),
        ],
        {"6001": "revenue", "6401": "cost"},
    )
    result = evaluate_metric(normalized, {"kind": "management_pnl"})
    row = result["rows"][0]
    assert Decimal(row["revenue"]) == Decimal("0")
    assert Decimal(row["cost"]) == Decimal("0")
    # And it says why a month of activity nets to nothing.
    netted = [d for d in result["diagnostics"] if d["code"] == "account_nets_to_zero"]
    assert {d["message"].split()[0] for d in netted} == {"revenue", "cost"}


def test_the_balances_still_read_the_way_they_always_did() -> None:
    """A trial balance carries each account once, on its own side."""
    normalized = _normalized(
        [("6001", "credit", "400"), ("6401", "debit", "300"), ("6602", "debit", "50")],
        {"6001": "revenue", "6401": "cost", "6602": "expense"},
    )
    row = evaluate_metric(normalized, {"kind": "management_pnl"})["rows"][0]
    assert Decimal(row["revenue"]) == Decimal("400")
    assert Decimal(row["cost"]) == Decimal("300")
    assert Decimal(row["expense"]) == Decimal("50")
    assert Decimal(row["profit"]) == Decimal("50")


def test_a_row_that_names_no_side_says_the_sign_was_assumed() -> None:
    """A budget export carries an amount and nothing about direction."""
    rows = [
        {"account_code": "6001", "amount": "400", "period": "2026-08", "currency": "CNY", "unit": "元"},
        {"account_code": "6401", "amount": "300", "period": "2026-08", "currency": "CNY", "unit": "元"},
    ]
    normalized = normalize_finance_dataset(
        _dataset("budget", rows),
        {"ledger": "华宸物业", "organization": "集团合并", "period": "2026-08",
         "currency": "CNY", "unit": "元", "scenario": "budget"},
        account_map={"rows": [
            {"account_code": "6001", "management_account": "revenue"},
            {"account_code": "6401", "management_account": "cost"},
        ]},
    )
    result = evaluate_metric(normalized, {"kind": "management_pnl"})
    row = result["rows"][0]
    # Unchanged arithmetic: the account is the only thing left to read a sign from.
    assert Decimal(row["revenue"]) == Decimal("400")
    assert Decimal(row["cost"]) == Decimal("300")
    assumed = next(d for d in result["diagnostics"] if d["code"] == "amount_direction_assumed")
    assert assumed["severity"] == "warning"
    assert "2 of 2" in assumed["message"]


def test_a_metric_that_produced_no_line_is_not_a_quiet_success() -> None:
    normalized = _normalized([("6001", "credit", "400")], {"9999": "revenue"})
    result = evaluate_metric(normalized, {"kind": "management_pnl"})
    assert result["rows"] == []
    empty = next(d for d in result["diagnostics"] if d["code"] == "empty_result")
    # Error severity is what marks the run incomplete downstream.
    assert empty["severity"] == "error"
    assert "1 fact rows" in empty["message"]
