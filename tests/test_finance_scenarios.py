from copy import deepcopy
from decimal import Decimal

import pytest

from foundry.errors import FoundryError
from foundry.finance_scenarios import (
    compute_receivables_aging,
    create_child_scenario,
    forecast_cash_13_weeks,
    validate_driver_model,
)
import foundry.finance_scenarios as finance_scenarios


SCOPE = {
    "organization": "华东",
    "ledger": "service-co",
    "currency": "CNY",
    "unit": "元",
}


def amount(rows, bucket, currency="CNY"):
    return Decimal(
        next(
            row["open_amount"]
            for row in rows
            if row["bucket"] == bucket and row["currency"] == currency
        )
    )


def test_g4_aging_uses_effective_date_and_preserves_history():
    invoices = [
        {
            "id": "ar-1",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "80",
        },
        {
            "id": "ar-2",
            "customer": "乙客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-20",
            "amount": "20",
        },
    ]
    activity = [
        {
            "id": "pay-after",
            "invoice_id": "ar-1",
            "kind": "payment",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "effective_date": "2026-09-06",
            "amount": "80",
        }
    ]

    result = compute_receivables_aging(
        invoices,
        activity,
        as_of="2026-09-05",
        scope=SCOPE,
    )

    assert amount(result["rows"], "31-60") == Decimal("80")
    assert amount(result["rows"], "not_due") == Decimal("20")
    overdue = next(row for row in result["detail_rows"] if row["invoice_id"] == "ar-1")
    assert overdue["overdue_days"] == 35
    assert result["evidence"]["future_activity_ignored"] == [
        {
            "id": "pay-after",
            "kind": "payment",
            "effective_date": "2026-09-06",
            "amount": "80",
            "ledger": "service-co",
            "organization": "华东",
            "currency": "CNY",
            "unit": "元",
            "invoice_id": "ar-1",
        }
    ]

    later = compute_receivables_aging(
        invoices,
        activity,
        as_of="2026-09-06",
        scope=SCOPE,
    )
    assert amount(later["rows"], "31-60") == Decimal("0")
    assert amount(result["rows"], "31-60") == Decimal("80")


def test_aging_applies_partial_payments_allocations_credits_and_writeoffs():
    invoices = [
        {
            "id": "ar-3",
            "customer": "丙客户",
            "organization": "上海",
            "ledger": "group",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-07-01",
            "due_date": "2026-07-31",
            "amount": "150",
        },
        {
            "id": "ar-4",
            "customer": "丁客户",
            "organization": "北京",
            "ledger": "group",
            "currency": "USD",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-31",
            "amount": "20",
        },
    ]
    activity = [
        {
            "id": "p1",
            "invoice_id": "ar-3",
            "kind": "payment",
            "organization": "上海",
            "ledger": "group",
            "currency": "CNY",
            "effective_date": "2026-08-15",
            "amount": "40",
        },
        {
            "id": "a1",
            "invoice_id": "ar-3",
            "kind": "allocation",
            "organization": "上海",
            "ledger": "group",
            "currency": "CNY",
            "effective_date": "2026-08-20",
            "amount": "10",
        },
        {
            "id": "c1",
            "invoice_id": "ar-3",
            "kind": "credit",
            "organization": "上海",
            "ledger": "group",
            "currency": "CNY",
            "effective_date": "2026-08-25",
            "amount": "5",
        },
        {
            "id": "w1",
            "invoice_id": "ar-3",
            "kind": "writeoff",
            "organization": "上海",
            "ledger": "group",
            "currency": "CNY",
            "effective_date": "2026-09-01",
            "amount": "15",
        },
    ]

    result = compute_receivables_aging(
        invoices,
        activity,
        as_of="2026-09-05",
        scope={"customer": "丙客户", "currency": "CNY", "unit": "元"},
    )

    assert len(result["detail_rows"]) == 1
    assert result["detail_rows"][0]["open_amount"] == "80"
    assert result["detail_rows"][0]["settled_amount"] == "70"
    assert amount(result["rows"], "31-60") == Decimal("80")
    applied = result["evidence"]["activity_applied"]["ar-3|group|上海|CNY|元"]
    assert set(item["kind"] for item in applied) == {
        "payment",
        "allocation",
        "credit",
        "writeoff",
    }


def test_aging_refuses_ambiguous_duplicate_invoice_activity_identity():
    invoices = [
        {
            "id": "same-id",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "80",
        },
        {
            "id": "same-id",
            "customer": "甲客户",
            "organization": "华南",
            "ledger": "other-ledger",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "50",
        },
    ]

    with pytest.raises(FoundryError, match="duplicate invoice ids"):
        compute_receivables_aging(
            invoices,
            [
                {
                    "id": "pay-ambiguous",
                    "invoice_id": "same-id",
                    "kind": "payment",
                    "effective_date": "2026-08-31",
                    "amount": "10",
                }
            ],
            as_of="2026-09-05",
            scope=SCOPE,
        )


def test_aging_keeps_same_invoice_ids_separate_by_ledger_and_currency():
    invoices = [
        {
            "id": "same-id",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "80",
        },
        {
            "id": "same-id",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "USD",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "50",
        },
    ]
    activity = [
        {
            "id": "pay-cny",
            "invoice_id": "same-id",
            "kind": "payment",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "effective_date": "2026-08-31",
            "amount": "30",
        },
        {
            "id": "pay-usd",
            "invoice_id": "same-id",
            "kind": "payment",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "USD",
            "effective_date": "2026-08-31",
            "amount": "10",
        },
    ]

    result = compute_receivables_aging(
        invoices,
        activity,
        as_of="2026-09-05",
        scope={
            "organization": "华东",
            "ledger": "service-co",
            "currency": ["CNY", "USD"],
            "unit": "元",
        },
    )

    assert amount(result["rows"], "31-60", "CNY") == Decimal("50")
    assert amount(result["rows"], "31-60", "USD") == Decimal("40")
    assert result["evidence"]["total_open_amount_by_scope"] == [
        {
            "ledger": "service-co",
            "organization": "华东",
            "currency": "CNY",
            "unit": "元",
            "open_amount": "50",
        },
        {
            "ledger": "service-co",
            "organization": "华东",
            "currency": "USD",
            "unit": "元",
            "open_amount": "40",
        },
    ]


def test_aging_ignores_future_issued_invoices_and_reports_overpayments():
    invoices = [
        {
            "id": "issued",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "80",
        },
        {
            "id": "future",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-09-06",
            "due_date": "2026-09-30",
            "amount": "20",
        },
    ]
    duplicate_payment = {
        "id": "overpay",
        "invoice_id": "issued",
        "kind": "payment",
        "organization": "华东",
        "ledger": "service-co",
        "currency": "CNY",
        "effective_date": "2026-09-01",
        "amount": "100",
    }

    result = compute_receivables_aging(
        invoices,
        [duplicate_payment, duplicate_payment],
        as_of="2026-09-05",
        scope=SCOPE,
    )

    assert amount(result["rows"], "31-60") == Decimal("0")
    assert result["evidence"]["future_invoices_ignored"] == [
        {
            "invoice_id": "future",
            "ledger": "service-co",
            "organization": "华东",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-09-06",
        }
    ]
    assert result["evidence"]["overapplied"] == [
        {
            "invoice_id": "issued",
            "ledger": "service-co",
            "organization": "华东",
            "currency": "CNY",
            "unit": "元",
            "overapplied_amount": "20",
            "settled_amount": "100",
            "original_amount": "80",
        }
    ]
    assert result["warnings"] == ["duplicate activity ignored: overpay"]


def test_aging_refuses_ambiguous_negative_reduction_but_accepts_declared_reversal():
    invoices = [
        {
            "id": "ar-reversal",
            "customer": "甲客户",
            "organization": "华东",
            "ledger": "service-co",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "80",
        }
    ]
    reversal = {
        "id": "reverse-allocation",
        "invoice_id": "ar-reversal",
        "kind": "allocation",
        "organization": "华东",
        "ledger": "service-co",
        "currency": "CNY",
        "effective_date": "2026-09-01",
        "amount": "-10",
    }

    with pytest.raises(FoundryError, match="negative activity"):
        compute_receivables_aging(invoices, [reversal], as_of="2026-09-05", scope=SCOPE)

    result = compute_receivables_aging(
        invoices,
        [{**reversal, "reversal": True}],
        as_of="2026-09-05",
        scope=SCOPE,
    )

    assert amount(result["rows"], "31-60") == Decimal("90")


def test_g3_cash_forecast_baseline_delay_and_weekly_continuity():
    receipts = [
        {
            "id": "r-sept",
            "date": "2026-09-25",
            "amount": "100",
            **SCOPE,
        }
    ]
    payments = [
        {
            "id": "p-quarter",
            "date": "2026-09-30",
            "amount": "60",
            **SCOPE,
        }
    ]

    baseline = forecast_cash_13_weeks(
        opening_cash="50",
        start_date="2026-09-01",
        actual_cutoff="2026-09-05",
        receipts=receipts,
        payments=payments,
        scope=SCOPE,
    )
    delayed = forecast_cash_13_weeks(
        opening_cash="50",
        start_date="2026-09-01",
        actual_cutoff="2026-09-05",
        receipts=receipts,
        payments=payments,
        scenario={
            "label": "conservative",
            "source": "manager_direct",
            "delay_receipts_days": 14,
        },
        scope=SCOPE,
    )

    assert baseline["evidence"]["point_balances"]["2026-09-30"] == "90"
    assert delayed["evidence"]["point_balances"]["2026-09-30"] == "-10"
    assert any(
        event["id"] == "r-sept" and event["date"] == "2026-10-09"
        for event in delayed["evidence"]["events"]
    )
    assert delayed["evidence"]["outside_horizon"] == []
    for previous, current in zip(delayed["rows"], delayed["rows"][1:]):
        assert Decimal(previous["closing_cash"]) == Decimal(current["opening_cash"])
    for row in delayed["rows"]:
        assert Decimal(row["opening_cash"]) + Decimal(row["receipts"]) - Decimal(
            row["payments"]
        ) == Decimal(row["closing_cash"])
    assert receipts == [
        {"id": "r-sept", "date": "2026-09-25", "amount": "100", **SCOPE}
    ]


def test_cash_forecast_requires_single_scope_and_refuses_forecast_before_cutoff():
    with pytest.raises(FoundryError, match="cash forecast scope"):
        forecast_cash_13_weeks(
            opening_cash="50",
            start_date="2026-09-01",
            actual_cutoff="2026-09-05",
            receipts=[],
            payments=[],
        )

    with pytest.raises(FoundryError, match="before actual_cutoff"):
        forecast_cash_13_weeks(
            opening_cash="50",
            start_date="2026-09-01",
            actual_cutoff="2026-09-05",
            receipts=[
                {
                    "id": "r-old-plan",
                    "date": "2026-09-04",
                    "amount": "10",
                    "status": "forecast",
                    **SCOPE,
                }
            ],
            payments=[],
            scope=SCOPE,
        )


def test_cash_forecast_filters_other_scopes_without_mixing_currency():
    result = forecast_cash_13_weeks(
        opening_cash="50",
        start_date="2026-09-01",
        actual_cutoff="2026-09-05",
        receipts=[
            {
                "id": "r-cny",
                "date": "2026-09-08",
                "amount": "20",
                **SCOPE,
            },
            {
                "id": "r-usd",
                "date": "2026-09-08",
                "amount": "999",
                "organization": "华东",
                "ledger": "service-co",
                "currency": "USD",
                "unit": "元",
            },
        ],
        payments=[],
        scope=SCOPE,
    )

    assert result["rows"][1]["receipts"] == "20"
    assert result["rows"][1]["closing_cash"] == "70"
    assert [event["id"] for event in result["evidence"]["events"]] == ["r-cny"]
    assert result["evidence"]["ignored_events"] == [
        {
            "id": "r-usd",
            "kind": "receipt",
            "date": "2026-09-08",
            "amount": "999",
            "ledger": "service-co",
            "organization": "华东",
            "currency": "USD",
            "unit": "元",
        }
    ]
    assert result["evidence"]["scope"] == SCOPE


def test_aging_splits_same_currency_by_ledger_org_and_unit_scope():
    invoices = [
        {
            "id": "ar-l1",
            "customer": "甲客户",
            "organization": "O1",
            "ledger": "L1",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "80",
        },
        {
            "id": "ar-l2",
            "customer": "乙客户",
            "organization": "O2",
            "ledger": "L2",
            "currency": "CNY",
            "unit": "元",
            "issue_date": "2026-08-01",
            "due_date": "2026-08-01",
            "amount": "40",
        },
    ]

    result = compute_receivables_aging(
        invoices,
        [],
        as_of="2026-09-05",
        scope={
            "ledger": ["L1", "L2"],
            "organization": ["O1", "O2"],
            "currency": "CNY",
            "unit": "元",
        },
    )

    grouped = {
        (
            row["ledger"],
            row["organization"],
            row["currency"],
            row["unit"],
            row["bucket"],
        ): row["open_amount"]
        for row in result["rows"]
    }
    assert grouped[("L1", "O1", "CNY", "元", "31-60")] == "80"
    assert grouped[("L2", "O2", "CNY", "元", "31-60")] == "40"
    assert result["evidence"]["total_open_amount_by_scope"] == [
        {
            "ledger": "L1",
            "organization": "O1",
            "currency": "CNY",
            "unit": "元",
            "open_amount": "80",
        },
        {
            "ledger": "L2",
            "organization": "O2",
            "currency": "CNY",
            "unit": "元",
            "open_amount": "40",
        },
    ]
    assert "total_open_amount_by_currency" not in result["evidence"]


def test_cash_forecast_preserves_pre_start_events_outside_horizon_without_double_counting():
    result = forecast_cash_13_weeks(
        opening_cash="50",
        start_date="2026-09-01",
        actual_cutoff="2026-09-05",
        receipts=[
            {"id": "r-before", "date": "2026-08-31", "amount": "20", **SCOPE},
            {"id": "r-in-window", "date": "2026-09-02", "amount": "10", **SCOPE},
        ],
        payments=[],
        scope=SCOPE,
    )

    assert result["rows"][0]["opening_cash"] == "50"
    assert result["rows"][0]["receipts"] == "10"
    assert result["rows"][0]["closing_cash"] == "60"
    assert result["evidence"]["point_balances"]["2026-09-02"] == "60"
    assert result["evidence"]["outside_horizon"] == [
        {"id": "r-before", "kind": "receipt", "date": "2026-08-31", "amount": "20"}
    ]


def test_cash_forecast_dedupes_exact_duplicate_events_and_rejects_conflicts():
    duplicate = {"id": "r-dup", "date": "2026-09-02", "amount": "10", **SCOPE}
    result = forecast_cash_13_weeks(
        opening_cash="50",
        start_date="2026-09-01",
        actual_cutoff="2026-09-05",
        receipts=[duplicate, duplicate],
        payments=[],
        scope=SCOPE,
    )

    assert result["rows"][0]["receipts"] == "10"
    assert result["diagnostics"] == [
        {
            "severity": "info",
            "code": "duplicate_cash_event_ignored",
            "message": "duplicate cash event ignored",
            "event_id": "r-dup",
            "kind": "receipt",
        }
    ]
    with pytest.raises(FoundryError, match="duplicate cash event identity"):
        forecast_cash_13_weeks(
            opening_cash="50",
            start_date="2026-09-01",
            actual_cutoff="2026-09-05",
            receipts=[duplicate, {**duplicate, "amount": "11"}],
            payments=[],
            scope=SCOPE,
        )


def test_cash_forecast_requires_unit_scope_and_does_not_mix_units():
    with pytest.raises(FoundryError, match="scope requires one unit"):
        forecast_cash_13_weeks(
            opening_cash="50",
            start_date="2026-09-01",
            actual_cutoff="2026-09-05",
            receipts=[],
            payments=[],
            scope={key: value for key, value in SCOPE.items() if key != "unit"},
        )

    result = forecast_cash_13_weeks(
        opening_cash="50",
        start_date="2026-09-01",
        actual_cutoff="2026-09-05",
        receipts=[
            {"id": "r-yuan", "date": "2026-09-02", "amount": "10", **SCOPE},
            {
                "id": "r-wanyuan",
                "date": "2026-09-02",
                "amount": "999",
                **{**SCOPE, "unit": "万元"},
            },
        ],
        payments=[],
        scope=SCOPE,
    )

    assert result["rows"][0]["receipts"] == "10"
    assert [event["id"] for event in result["evidence"]["events"]] == ["r-yuan"]
    assert result["evidence"]["ignored_events"][0]["unit"] == "万元"


def test_driver_model_calculates_declared_dag_and_accepts_manager_assumptions():
    drivers = [
        {"name": "volume", "direct_assumption": True},
        {"name": "price", "direct_assumption": True},
        {
            "name": "revenue",
            "formula": "volume * price",
            "depends_on": ["volume", "price"],
        },
        {"name": "collection_rate", "direct_assumption": True},
        {
            "name": "cash_receipts",
            "formula": "revenue * collection_rate",
            "depends_on": ["revenue", "collection_rate"],
        },
    ]

    result = validate_driver_model(
        drivers,
        inputs={"volume": "10", "price": "20"},
        manager_assumptions={
            "collection_rate": {
                "label": "经理保守回款率",
                "source": "manager_direct",
                "value": "0.8",
            }
        },
    )

    by_driver = {row["driver"]: row for row in result["rows"]}
    assert by_driver["revenue"]["value"] == "200"
    assert by_driver["cash_receipts"]["value"] == "160.0"
    assert by_driver["collection_rate"]["source"] == "manager_direct"
    assert result["assumptions"] == [
        {
            "driver": "collection_rate",
            "label": "经理保守回款率",
            "source": "manager_direct",
            "value": "0.8",
        }
    ]


def test_driver_model_refuses_cycles_and_unsafe_formulas():
    with pytest.raises(FoundryError, match="cycle"):
        validate_driver_model(
            [
                {"name": "a", "formula": "b + 1", "depends_on": ["b"]},
                {"name": "b", "formula": "a + 1", "depends_on": ["a"]},
            ],
            inputs={},
        )


def test_driver_model_refuses_explicit_values_for_formula_drivers():
    with pytest.raises(FoundryError, match="formula driver inputs"):
        validate_driver_model(
            [
                {"name": "volume", "direct_assumption": True},
                {"name": "price", "direct_assumption": True},
                {
                    "name": "revenue",
                    "formula": "volume * price",
                    "depends_on": ["volume", "price"],
                },
            ],
            inputs={"volume": "10", "price": "20", "revenue": "999"},
        )
    with pytest.raises(FoundryError, match="unsupported"):
        validate_driver_model(
            [
                {
                    "name": "a",
                    "formula": "__import__('os').system('date')",
                    "depends_on": [],
                }
            ],
            inputs={},
        )
    with pytest.raises(FoundryError, match="dependencies"):
        validate_driver_model(
            [
                {"name": "volume", "direct_assumption": True},
                {"name": "price", "direct_assumption": True},
                {
                    "name": "revenue",
                    "formula": "volume * price",
                    "depends_on": ["volume"],
                },
            ],
            inputs={"volume": "1", "price": "2"},
        )


def test_child_scenario_serializes_diff_and_keeps_parent_inputs_unchanged():
    parent = {
        "id": "base",
        "actual_cutoff": "2026-09-05",
        "inputs": {"delay_receipts_days": 0, "collection_rate": "1.0"},
    }
    before = deepcopy(parent)

    child = create_child_scenario(
        parent,
        {"delay_receipts_days": 14},
        label="conservative",
        actual_cutoff="2026-09-05",
    )

    assert parent == before
    assert child["parent_id"] == "base"
    assert child["actual_cutoff"] == "2026-09-05"
    assert child["inputs"]["delay_receipts_days"] == 14
    assert child["inputs"]["collection_rate"] == "1.0"
    assert child["diff"] == [{"key": "delay_receipts_days", "parent": 0, "child": 14}]
    assert child["parent_input_hash"] != child["input_hash"]


def test_domain_boundary_has_no_payment_submission_or_journal_posting_api():
    public_names = {name for name in dir(finance_scenarios) if not name.startswith("_")}
    forbidden_terms = (
        "submit_payment",
        "payment_submission",
        "post_journal",
        "journal_posting",
    )
    assert not any(name in public_names for name in forbidden_terms)
