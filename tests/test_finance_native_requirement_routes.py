"""Native requirement identity must match actual comparison scopes, never labels."""
import pytest

from foundry.finance_requirements import check_requirements
from test_finance_native_drafts import native_case, native_result


def claim_spec(case):
    _, _, requirement, run, prepared = case
    return {"requirements_id": requirement["id"], "run_ids": [run["id"]],
            "claims": [fact["reference_template"]["claim"] for fact in prepared["facts"]
                       if fact["column"] in {"actual", "baseline", "total_variance", "quantity_contribution",
                                             "price_contribution", "interaction", "residual",
                                             "volume_contribution", "mix_contribution"}]}


@pytest.mark.parametrize("method", ["quantity_then_price", "base_weights_with_interaction", "volume_mix_price"])
def test_explicit_native_comparison_identity_answers_its_exact_original_requirement(tmp_path, method):
    case = native_case(tmp_path, method=method, dimensions={"method": method,
        "actual_scenario": "actual", "baseline_scenario": "budget"})
    checked = check_requirements(case[0].analysis, claim_spec(case))
    assert checked["items"][0]["status"] == "answered", checked
    assert checked["original_requirements_completed"] is True


@pytest.mark.parametrize("method", ["price_quantity", "unknown_method"])
def test_metric_name_or_unknown_method_is_not_inferred_to_be_base_weights(tmp_path, method):
    case = native_case(tmp_path, method="base_weights_with_interaction", dimensions={"method": method})
    checked = check_requirements(case[0].analysis, claim_spec(case))
    assert checked["items"][0]["status"] == "pending"
    assert native_result(case)["draft_template"] is None


@pytest.mark.parametrize("dimension,value", [("actual_scenario", "budget"), ("baseline_scenario", "actual"),
                                             ("product", "another product")])
def test_contradictory_comparison_or_product_does_not_receive_template(tmp_path, dimension, value):
    case = native_case(tmp_path, dimensions={"method": "quantity_then_price", dimension: value})
    assert check_requirements(case[0].analysis, claim_spec(case))["items"][0]["status"] == "pending"
    assert native_result(case)["draft_template"] is None


def test_aging_cutoff_is_not_used_as_a_missing_period_requirement(tmp_path):
    case = native_case(tmp_path, aging=True)
    service, _, requirements, run, _ = case
    revised = service.analysis_requirements_save({"parent_id": requirements["id"],
        "question": requirements["question"], "context_id": requirements["context_id"],
        "scope": {**requirements["scope"], "period": "2026-09-30"}, "items": requirements["items"]})
    assert revised["scope"]["period"] == "2026-09-30"
    assert all("period" not in row for row in run["result"]["rows"])
    assert native_result(case)["draft_template"] is None


@pytest.mark.parametrize("method", ["quantity_then_price", "base_weights_with_interaction"])
@pytest.mark.parametrize("metadata", [{"actual_scenario": "budget"},
    {"baseline_scope": {"scenario": "actual"}}, {"actual_scope": "untyped-label"}])
def test_standard_comparison_identity_rejects_existing_conflicting_row_metadata(tmp_path, method, metadata):
    from foundry.finance_requirements import _price_quantity_requirement_matches

    case = native_case(tmp_path, method=method, dimensions={"method": method,
        "actual_scenario": "actual", "baseline_scenario": "budget"})
    _, _, requirements, run, prepared = case
    row = run["result"]["rows"][0]
    item, group = requirements["items"][0], prepared["evidence_groups"][0]
    assert _price_quantity_requirement_matches(item, run, row, group)
    assert not _price_quantity_requirement_matches(item, run, {**row, **metadata}, group)
