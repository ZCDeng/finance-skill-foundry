"""Public-only adapter coverage: no scorer imports, oracle reads or model calls."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "tests/fixtures/finance_evals/professional/public"
SPEC = importlib.util.spec_from_file_location("public_coverage_adapters", ROOT / "tools/finance_professional_adapters.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
ADDED = {"E02", "E05", "E06", "E07", "E09", "E11", "E13", "E14", "E15", "E16", "E17",
         "E20", "E21", "E24", "E25", "E28", "E29", "E30", "E32"}
CASES = sorted(p.stem for p in PUBLIC.glob("*.json") if p.stem.split("--")[0] in ADDED)


def case(case_id):
    return json.loads((PUBLIC / f"{case_id}.json").read_text())


def adapted(case_id):
    return A.adapt(case(case_id))


def rows(public, dataset):
    return next(d["rows"] for d in public["datasets"] if d["name"] == dataset)


def test_all_missing_families_have_method_and_resource_routes():
    assert ADDED <= A.FAMILIES
    assert A.FAMILIES == set(A.METHODS) == set(A.RESOURCES)
    for family in A.FAMILIES:
        assert (ROOT / "method" / A.METHODS[family] / "SKILL.md").is_file()
        assert "FOUNDRY.md" in A.RESOURCES[family]
        assert all((ROOT / "method" / resource).is_file() for resource in A.RESOURCES[family])


@pytest.mark.parametrize("case_id", CASES)
def test_every_public_fact_and_locator_survives_without_acceptance_claim(case_id):
    original = case(case_id)
    untouched = deepcopy(original)
    public, trace = A.adapt(original)
    assert original == untouched
    assert trace["public_sha256"] == A.digest(original)
    assert trace["output_sha256"] == A.digest(public)
    facts = rows(public, "public_facts")
    assert [{k: r[k] for k in ("name", "value")} for r in facts] == original["data"]
    assert [r["source_row"] for r in facts] == list(range(1, len(facts) + 1))
    assert [r["source_field"] for r in facts] == [r["name"] for r in original["data"]]
    assert trace["readiness"]["acceptance_readiness"] == "not_verified"
    assert "readiness" not in public
    assert "oracle" not in json.dumps(public).lower()
    for dataset in public["datasets"]:
        for row in dataset["rows"]:
            assert row["source_field"] in {r["name"] for r in original["data"]}
            assert original["data"][row["source_row"] - 1]["name"] == row["source_field"]


@pytest.mark.parametrize("case_id,field", [("E07--policy_missing", "approved_rates"),
    ("E13--missing_month", "march"), ("E14--fx_missing", "rate"),
    ("E15--start_missing", "approved_start"), ("E30--missing_driver", "volume"),
    ("E32--missing_input", "cost")])
def test_missing_facts_are_never_imputed_zero(case_id, field):
    public, _ = adapted(case_id)
    assert next(r for r in rows(public, "public_facts") if r["name"] == field)["value"] == "missing"
    numeric = [r for d in public["datasets"] if d["name"] != "public_facts" for r in d["rows"]]
    assert not any(r["source_field"] == field and ("amount" in r or "numeric_value" in r) for r in numeric)


def test_product_vectors_preserve_noncomparable_product_without_invented_budget():
    public, trace = adapted("E02--new_product")
    basket = rows(public, "price_quantity")
    assert [(r["scenario"], r["product"], r["quantity"], r["price"]) for r in basket] == [
        ("budget", "A", "10", "10"), ("actual", "A", "10", "11"), ("actual", "B", "5", "12")]
    assert "B_base_price" in trace["readiness"]["missing_business_fields"]
    assert all("contribution" not in key for r in basket for key in r)
    for row in basket:
        text = dict((r["name"], r["value"]) for r in case("E02--new_product")["data"])[row["source_field"]]
        assert text[row["source_character_start"]:row["source_character_end"]] == row["source_literal"]


def test_reconciliation_preserves_duplicate_keys_and_unapproved_grouping_gap():
    public, _ = adapted("E11--duplicate_key")
    assert [r["transaction_key"] for r in rows(public, "left_transactions")] == ["T1", "T1"]
    assert len(rows(public, "right_transactions")) == 1
    public, trace = adapted("E11--one_to_many")
    assert "grouping_rule" in trace["readiness"]["missing_business_fields"]
    assert {r["transaction_key"] for r in rows(public, "right_transactions")} == {"T1a", "T1b"}
    assert all("matched" not in r and "group_id" not in r for d in public["datasets"] for r in d["rows"])


def test_actual_budget_components_are_source_inputs_not_profit_answers():
    public, trace = adapted("E32--correct_method")
    financials = rows(public, "financial_components")
    assert [(r["scenario"], r["account"], r["amount"]) for r in financials] == [
        ("actual", "revenue", "120"), ("actual", "cost", "60"), ("actual", "expense", "10"),
        ("budget", "revenue", "100"), ("budget", "cost", "50"), ("budget", "expense", "10")]
    assert all(r["account"] != "profit" for r in financials)
    assert trace["readiness"]["route"] == "source_bound_profit_variance"


def test_scalar_parameters_do_not_acquire_money_or_approval_semantics():
    public, _ = adapted("E16--base")
    assert {r["input"]: r["numeric_value"] for r in rows(public, "numeric_inputs")} == {
        "monthly_pay": "50000", "paid_FTE": "10", "forecast_FTE": "12"}
    assert all(not {"amount", "approved", "currency", "unit", "period"} & row.keys()
               for row in rows(public, "numeric_inputs"))
    public, _ = adapted("E07--policy_present")
    assert next(r for r in rows(public, "public_facts") if r["name"] == "approved_rates")["value"] == "1%,10%"
    assert all("confirmed_by" not in row for dataset in public["datasets"] for row in dataset["rows"])


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_nonfinite_scalar_is_not_silently_converted_to_missing(value):
    original = case("E32--complete_input")
    original["data"][0]["value"] = value
    with pytest.raises(ValueError, match="finite"):
        A.adapt(original)


@pytest.mark.parametrize("case_id", ["E32--no_method", "E32--wrong_method", "E32--late_read", "E32--failed_read"])
def test_declared_trace_is_not_current_runtime_method_evidence(case_id):
    public, trace = adapted(case_id)
    assert rows(public, "public_facts")[0]["value"] == case(case_id)["data"][0]["value"]
    assert trace["readiness"]["permitted_end_state"] == "assessment_of_supplied_trace_not_current_session_method_order_proof"


def test_public_value_perturbation_changes_only_supplied_inputs():
    original = case("E20--base")
    original["data"][0]["value"] = "123.45"
    public, _ = A.adapt(original)
    assert rows(public, "numeric_inputs")[0]["numeric_value"] == "123.45"
    assert {r["input"] for r in rows(public, "numeric_inputs")} == {r["name"] for r in original["data"]}


@pytest.mark.parametrize("case_id", ["E18--base", "E19--new_cash_sale", "E19--old_ar_collected"])
def test_limited_management_bridge_does_not_grant_registered_template(case_id):
    public, trace = adapted(case_id)
    plan = trace["readiness"]
    assert plan["runtime_readiness"] == "candidate_limited_management_bridge"
    assert plan["registered_template_readiness"] == "blocked_template_preconditions"
    assert "eight_explicit_boundary_sources" in plan["missing_business_fields"]
    values = {r["name"]: r["value"] for r in case(case_id)["data"]}
    for row in rows(public, "model_inputs"):
        assert values[row["account"]] == row["amount"]
        assert not {"period", "organization", "approved", "boundary"} & row.keys()


@pytest.mark.parametrize("case_id", [c for c in CASES if c.startswith(("E28--", "E29--"))]
                         + ["E30--next_month", "E09--next_january"])
def test_runtime_cases_require_real_precondition_before_provider(case_id):
    public, trace = adapted(case_id)
    plan = trace["readiness"]
    assert plan["runtime_readiness"] == "candidate_with_explicit_state_bootstrap"
    assert plan["runtime_preconditions"]["required_evidence"]
    assert plan["bootstrap"].startswith("explicit_synthetic_public_")
    assert len(rows(public, "public_facts")) == len(case(case_id)["data"])
    if case_id == "E28--engine_available":
        assert "target_engine_recalculation_receipt" in plan["runtime_preconditions"]["required_evidence"]


@pytest.mark.parametrize("mutation", ["private_top_level", "private_context", "duplicate", "non_string", "private_row"])
def test_adapter_rejects_nonpublic_or_ambiguous_contract(mutation):
    original = case("E20--base")
    if mutation == "private_top_level":
        original["oracle"] = {"answer": "100"}
    elif mutation == "private_context":
        original["context"]["expected"] = "100"
    elif mutation == "duplicate":
        original["data"].append(dict(original["data"][0]))
    elif mutation == "non_string":
        original["data"][0]["value"] = 80
    else:
        original["data"][0]["private_note"] = "answer"
    with pytest.raises(ValueError):
        A.adapt(original)


@pytest.mark.parametrize("case_id,field,bad", [
    ("E02--priced_product", "actual", "A:10@11;B:missing@12"),
    ("E11--duplicate_key", "left", "T1:100;garbage"),
    ("E32--correct_method", "actual", "revenue=120,cost=60,expense=missing")])
def test_malformed_structured_facts_fail_without_partial_normalization(case_id, field, bad):
    original = case(case_id)
    next(r for r in original["data"] if r["name"] == field)["value"] = bad
    with pytest.raises(ValueError):
        A.adapt(original)


def test_public_adapter_never_opens_private_files(monkeypatch):
    originals = [case(c) for c in CASES]
    def denied(*_args, **_kwargs):
        raise AssertionError("adapter attempted filesystem access")
    monkeypatch.setattr("builtins.open", denied)
    monkeypatch.setattr(Path, "open", denied)
    for original in originals:
        A.adapt(original)
