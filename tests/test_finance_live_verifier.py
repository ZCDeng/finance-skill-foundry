"""Protect the live evidence checker from accepting coincidental numbers."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "finance_live_verifier", Path(__file__).resolve().parents[1] / "tools/verify_method_skill_session.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def state(row, status="succeeded"):
    return {"runs": [{"id": "real-run", "execution_status": status, "result": {"rows": [row]}}]}


def test_expense_variance_normalization_preserves_raw_evidence():
    result = verifier.verify_financial_cells(state({
        "profit_var": "5", "revenue_var": "20", "cost_var": "10", "expense_var": "5",
    }), "G1")
    cost = result["cost_contribution"][0]
    assert cost["raw_value"] == "10"
    assert cost["value"] == "-10"
    assert cost["normalization"] == "profit_contribution = -expense_variance"
    assert cost["run_id"] == "real-run"


@pytest.mark.parametrize("invalid", [
    {"profit_var_pct": "5"},
    {"profit_var": "6", "unrelated_profit": "5"},
    {"profit_var": "6", "management_profit": "5"},
    {"cost_var": None, "cost_contribution": "10"},
    {"revenue_var": None, "revenue_var_pct": "20"},
    {"revenue_var": None, "revenue": "20"},
])
def test_wrong_cells_do_not_satisfy_financial_truth(invalid):
    row = {"profit_var": "5", "revenue_var": "20", "cost_var": "10", "expense_var": "5"}
    if "profit_var_pct" in invalid:
        row.pop("profit_var")
    row.update(invalid)
    with pytest.raises(AssertionError):
        verifier.verify_financial_cells(state(row), "G1")


def test_failed_run_cannot_prove_a_correct_number():
    with pytest.raises(AssertionError):
        verifier.verify_financial_cells(state({"total_var": "32", "qty_effect": "20", "price_effect": "12"}, "failed"), "G2")


def test_raw_price_and_quantity_do_not_prove_contributions():
    with pytest.raises(AssertionError):
        verifier.verify_financial_cells(state({"total_var": "32", "quantity": "20", "price": "12"}), "G2")


def test_total_only_draft_does_not_prove_a_complete_bridge():
    result = state({"profit_var": "5", "revenue_var": "20", "cost_var": "10", "expense_var": "5"})
    cells = verifier.verify_financial_cells(result, "G1")
    claims = [{"basis": "calculation", "verification_status": "matches_run", "run_id": "real-run",
               "row": 0, "column": column, "value": value}
              for column, value in result["runs"][0]["result"]["rows"][0].items()]
    result["drafts"] = [{"id": "draft", "run_ids": ["real-run"], "claims": claims[:1]}]
    assert verifier.verified_drafts(result, cells) == []
    result["drafts"][0]["claims"] = claims
    assert verifier.verified_drafts(result, cells)[0]["verified_metric_claims"]["cost_contribution"]["value"] == "-10"
    result["drafts"][0]["run_ids"] = []
    assert verifier.verified_drafts(result, cells) == []


def test_amount_change_and_profit_impact_named_rows_are_equivalent():
    result = state({})
    result["runs"][0]["result"]["rows"] = [
        {"line": "管理利润", "amount_change": "5"},
        {"line": "收入", "profit_impact": "20"},
        {"line": "成本", "profit_impact": "-10"},
        {"line": "费用", "profit_impact": "-5"},
    ]
    cells = verifier.verify_financial_cells(result, "G1")
    assert cells["profit_difference"][0]["column"] == "amount_change"
    assert cells["cost_contribution"][0]["value"] == "-10"
    result["runs"][0]["result"]["rows"][2]["profit_impact"] = "10"
    with pytest.raises(AssertionError):
        verifier.verify_financial_cells(result, "G1")


def test_revenue_change_requires_named_quantity_and_price_effects():
    result = verifier.verify_financial_cells(state({
        "revenue_change": "32", "quantity_effect": "20", "price_effect": "12",
    }), "G2")
    assert result["revenue_difference"][0]["column"] == "revenue_change"
