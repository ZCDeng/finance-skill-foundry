from decimal import Decimal

import pytest

from foundry.errors import FoundryError
from foundry.finance_variance import (
    explain_variance,
    price_quantity_bridge,
    variance_ratio,
)


def facts():
    rows = []
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        for account, amount in zip(("revenue", "cost", "expense"), amounts):
            rows.append(
                {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": scenario,
                    "management_account": account,
                    "amount": str(amount),
                    "source": {"dataset_id": scenario, "row_index": len(rows)},
                }
            )
    return {"rows": rows}


def test_profit_bridge_closes_and_links_sources():
    out = explain_variance(facts(), {})
    rows = {row["metric"]: row for row in out["rows"]}
    assert [
        rows[m]["contribution"] for m in ("revenue", "cost", "expense", "profit")
    ] == ["20", "-10", "-5", "5"]
    assert sum(
        Decimal(rows[m]["contribution"]) for m in ("revenue", "cost", "expense")
    ) == Decimal(rows["profit"]["contribution"])
    assert rows["cost"]["favorability"] == "unfavorable"
    assert len(rows["profit"]["source_rows"]) == 6


def test_zero_negative_and_missing_budget_policies():
    assert variance_ratio(10, 0)["ratio"] is None
    assert variance_ratio(-5, -10)["ratio"] == "0.5"
    assert variance_ratio(-5, -10, negative_policy="signed_baseline")["ratio"] == "-0.5"
    sample = facts()
    sample["rows"] = sample["rows"][:3]
    out = explain_variance(sample, {})
    assert all(r["contribution"] is None for r in out["rows"])
    assert all(
        r["comparison_status"] == "assumed_zero"
        for r in explain_variance(sample, {"missing_groups_as_zero": True})["rows"]
    )


def test_scope_and_different_grains_do_not_fan_out():
    sample = facts()
    revenue = sample["rows"].pop(0)
    sample["rows"].extend(
        [
            {
                **revenue,
                "amount": "60",
                "source": {"dataset_id": "actual", "row_index": i},
            }
            for i in (7, 8)
        ]
    )
    sample["rows"].append({**revenue, "ledger": "L2", "amount": "999"})
    out = explain_variance(sample, {})
    assert (
        next(r for r in out["rows"] if r["ledger"] == "L1" and r["metric"] == "profit")[
            "contribution"
        ]
        == "5"
    )
    assert all(r["contribution"] is None for r in out["rows"] if r["ledger"] == "L2")


@pytest.mark.parametrize(
    "method,expected",
    [
        ("quantity_then_price", ["20", "12", "0"]),
        ("base_weights_with_interaction", ["20", "10", "2"]),
    ],
)
def test_price_quantity_closure(method, expected):
    rows = [
        {"scenario": "budget", "quantity": "10", "price": "10", "product": "A"},
        {"scenario": "actual", "quantity": "12", "price": "11", "product": "A"},
    ]
    result = price_quantity_bridge(rows, {"method": method})["rows"][0]
    assert [
        result[k]
        for k in ("quantity_contribution", "price_contribution", "interaction")
    ] == expected
    assert result["total_variance"] == "32"
    assert result["residual"] == "0"


def test_amount_only_does_not_invent_price_or_quantity():
    rows = [
        {"scenario": "budget", "amount": "100"},
        {"scenario": "actual", "amount": "132"},
    ]
    result = price_quantity_bridge(rows, {})
    assert result["rows"] == []
    assert result["diagnostics"][0]["code"] == "price_quantity_missing"
    with pytest.raises(FoundryError, match="preaggregate"):
        price_quantity_bridge(rows + [rows[0]], {})


def test_price_quantity_requires_explicit_period_comparison():
    rows = [
        {
            "scenario": "actual",
            "period": "2026-09",
            "quantity": "12",
            "price": "11",
            "product": "A",
        },
        {
            "scenario": "budget",
            "period": "2026-08",
            "quantity": "10",
            "price": "10",
            "product": "A",
        },
    ]
    assert price_quantity_bridge(rows, {})["rows"] == []
    compared = price_quantity_bridge(
        rows,
        {
            "actual_filters": {"period": "2026-09"},
            "baseline_filters": {"period": "2026-08"},
        },
    )
    assert compared["rows"][0]["total_variance"] == "32"
    assert compared["comparison"]["baseline_filters"]["period"] == "2026-08"


def test_same_scenario_period_comparison_pairs_distinct_sides():
    rows = [
        {
            "scenario": "actual",
            "period": period,
            "quantity": q,
            "price": p,
            "product": "A",
        }
        for period, q, p in [("2026-08", "10", "10"), ("2026-09", "12", "11")]
    ]
    result = price_quantity_bridge(
        rows,
        {
            "actual_scenario": "actual",
            "baseline_scenario": "actual",
            "actual_filters": {"period": "2026-09"},
            "baseline_filters": {"period": "2026-08"},
        },
    )
    assert result["rows"][0]["total_variance"] == "32"


def test_nonperiod_side_filter_does_not_merge_months():
    data = facts()
    data["rows"] += [{**row, "period": "2026-08"} for row in data["rows"]]
    out = explain_variance(
        data, {"actual_filters": {"ledger": "L1"}, "baseline_filters": {"ledger": "L1"}}
    )
    assert len([row for row in out["rows"] if row["metric"] == "profit"]) == 2


def test_profit_variance_rejects_non_object_filters():
    with pytest.raises(FoundryError, match="comparison filters must be objects"):
        explain_variance(facts(), {"actual_filters": ["bad"]})


def test_price_quantity_filters_by_account_and_period_without_cross_period_merge():
    rows = [
        {
            "scenario": "actual",
            "period": "2026-09",
            "account_code": "6001",
            "quantity": "12",
            "price": "11",
            "product": "A",
        },
        {
            "scenario": "budget",
            "period": "2026-09",
            "account_code": "6001",
            "quantity": "10",
            "price": "10",
            "product": "A",
        },
        {
            "scenario": "actual",
            "period": "2026-08",
            "account_code": "6001",
            "quantity": "99",
            "price": "99",
            "product": "A",
        },
        {
            "scenario": "budget",
            "period": "2026-08",
            "account_code": "6001",
            "quantity": "99",
            "price": "99",
            "product": "A",
        },
        {
            "scenario": "actual",
            "period": "2026-09",
            "account_code": "6401",
            "quantity": "99",
            "price": "99",
            "product": "A",
        },
        {
            "scenario": "budget",
            "period": "2026-09",
            "account_code": "6401",
            "quantity": "99",
            "price": "99",
            "product": "A",
        },
    ]

    explicit = price_quantity_bridge(
        rows,
        {
            "actual_filters": {"period": "2026-09", "account_code": ["6001"]},
            "baseline_filters": {"period": "2026-09", "account_code": ["6001"]},
        },
    )
    unfiltered = price_quantity_bridge(rows[:4], {})

    assert explicit["rows"][0]["total_variance"] == "32"
    assert "period" not in explicit["columns"]
    assert {row["period"] for row in unfiltered["rows"]} == {"2026-08", "2026-09"}
