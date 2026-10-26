"""Frozen professional counterexamples for the first rules correction batch.

The private development oracle supplies expected values, never the functions under
test. These tests cover model-facing guidance as well as deterministic outputs;
they do not claim live-model or human professional acceptance.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from foundry.collection_metrics import (
    break_even_matrix,
    evaluate_collection_health,
    resolve_entities,
    resolve_params,
)

ROOT = Path(__file__).resolve().parents[1]
ORACLES = ROOT / "tests/fixtures/finance_evals/professional/private/oracles"


def _oracle(case_id):
    record = json.loads((ORACLES / f"{case_id}.json").read_text())
    return {item["metric"]: Decimal(item["expected"]) for item in record["numeric_checks"]}


def _skill(name):
    return (ROOT / "method" / name / "SKILL.md").read_text()


def _rows(values):
    entities = resolve_entities({"entities": [{"name": "E22", "values": values}]}, {})
    result = evaluate_collection_health(entities, resolve_params({}))
    return {(row["metric_key"], row["scenario"]): row for row in result["rows"]}, entities[0]


def test_frozen_cash_counterexample_keeps_threshold_and_gaps_estimated():
    expected = _oracle("E22--break_even_screen")
    values = {"revenue": "100", "cost": "60", "period_expense": "10",
              "collection_rate_current": "0.70", "collection_rate_total": "0.90"}
    values.update({f"{key}_py": value for key, value in list(values.items())})
    rows, _ = _rows(values)
    threshold = rows[("break_even_collection", "本期")]
    assert Decimal(threshold["value"]) == expected["estimated_threshold"] * 100
    # Same operating threshold, but capex still produces a real cash shortfall.
    assert Decimal("0") + Decimal("70") - Decimal("60") - Decimal("10") - Decimal("50") == expected["closing_cash"]
    for key in ("break_even_collection", "collection_gap", "collection_gap_total"):
        for scenario in ("本期", "上年同期", "变动"):
            row = rows[(key, scenario)]
            assert row["estimate"] is True, (key, scenario)
            assert "估算" in row["note"]
        note = rows[(key, "本期")]["note"]
        assert "同口径" in note and "资本开支" in note and "不能证明现金安全" in note
        assert "等于现金经营利润率" not in rows[(key, "本期")]["formula"]


def test_break_even_estimate_propagates_to_sensitivity_and_risk_radar():
    rows, entity = _rows({"revenue": "100", "cost": "60", "period_expense": "10",
                          "collection_rate_current": "0.70", "operating_profit": "30",
                          "revenue_ttm": "1200", "ar_end": "10"})
    assert rows[("risk_score", "本期")]["estimate"] is True
    assert "收支筛查" in rows[("risk_score", "本期")]["note"]
    matrix = break_even_matrix(entity, resolve_params({}))
    assert matrix["estimate"] is True
    assert "不能证明现金安全" in matrix["note"]
    assert "现金经营利润率 =" not in matrix["formula"]


def test_negative_gap_is_a_conditional_signal_not_a_cash_loss_fact():
    rows, _ = _rows({"gross_margin": "0.40", "expense_ratio": "0.10",
                     "collection_rate_current": "0.60"})
    gap = rows[("collection_gap", "本期")]
    assert gap["level"] == "red"
    assert "倒贴现金" not in gap["note"]
    assert "筛查" in gap["note"]


def test_mixed_tax_counterexample_is_recomputed_in_separate_homogeneous_runs():
    expected = _oracle("E04--base")
    gross_due = Decimal(0)
    for factor, cash in (("1.06", "106"), ("1.13", "113")):
        entities = resolve_entities({"entities": [{"name": factor, "values": {
            "revenue": "100", "cash_from_sales": cash}}]}, {})
        result = evaluate_collection_health(entities, resolve_params({"vat_factor": factor}))
        row = next(row for row in result["rows"] if row["metric_key"] == "cash_collection_ratio")
        assert Decimal(row["value"]) == expected["collection_ratio"] * 100
        gross_due += Decimal(cash)
    assert gross_due == expected["gross_due"]


def test_three_factor_guidance_uses_one_named_closed_order():
    text = _skill("variance-analysis")
    assert "Volume Effect = (Va - Vb) * sum(mb_i * pb_i)" in text
    assert "Mix Effect    = Va * sum((ma_i - mb_i) * pb_i)" in text
    assert "Price Effect  = Va * sum(ma_i * (pa_i - pb_i))" in text
    expected = _oracle("E01--base")
    assert expected["volume"] + expected["mix"] + expected["price"] == expected["total"]
    assert "300 - 120 + 48 = 228" in text
    assert "Mix Effect     = Residual" not in text
    assert "zero" in text.lower() and "capability" in text.lower()


def test_collection_guidance_does_not_assume_comprehensive_rate_is_higher():
    text = _skill("cash")
    expected = _oracle("E03--base")
    assert expected["comprehensive"] < expected["current"]
    assert "higher, lower, or equal" in text
    assert "reads higher" not in text
    assert "zero denominator" in text
    assert "vat_factor" in text and "homogeneous" in text
    assert "revenue × 1.06" not in text


def test_statutory_guidance_routes_by_basis_purpose_and_effective_period():
    text = " ".join(_skill("financial-statements").split())
    assert "CAS 31" in text and "direct method" in text
    assert "IFRS 18" in text and "2027-01-01" in text and "early adoption" in text
    assert "IAS 1" in text and "US GAAP" in text
    assert "reporting purpose" in text and "effective period" in text
    assert "full compliance" in text
    assert "### Income Statement (ASC 220 / IAS 1)" not in text


@pytest.mark.parametrize("case_id", ["E08--reverse_then_book", "E08--settle_accrual"])
def test_accrual_guidance_preserves_both_complete_nonduplicating_paths(case_id):
    text = _skill("journal-entry")
    expected = _oracle(case_id)
    assert expected["december_expense"] == 100 and expected["january_net_expense"] == 0
    assert "Reverse then book" in text and "Settle the accrual" in text
    assert "Do not mix" in text
    assert "accruals should auto-reverse" not in text
    assert "functional currency" in text


def test_reconciliation_separates_bank_timing_from_unrecorded_obligations():
    text = _skill("reconciliation")
    assert "typically 1-5 business days" not in text
    assert "already recorded in the GL" in text
    assert "unrecorded obligation" in text
    assert "pending approval" in text
    assert "cut-off" in text
