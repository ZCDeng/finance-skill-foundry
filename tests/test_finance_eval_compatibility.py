"""Compatibility checks for server-signed requirements and named ratio cells."""
from copy import deepcopy

import pytest

from test_finance_evals import _dataset_state, _semantic_requirement
from test_finance_professional_eval import E, RESOURCES, events, lawful_state


def scenario_requirement():
    record = _semantic_requirement("req2", 10)
    record["items"][0]["scenarios"] = ["actual"]
    record["semantic_basis"]["items"][0]["scenarios"] = ["actual"]
    record["semantic_fingerprint"] = E.legacy._sha(record["semantic_basis"])
    return record


def test_r4_preserves_server_signed_scenarios():
    record = scenario_requirement()
    datasets = {"dataset-a": _dataset_state()}
    E.legacy._verify_r4_requirement_semantics(record, "test requirement", datasets)
    assert E.legacy._r4_requirement_fingerprint(record, datasets) == record["semantic_fingerprint"]


@pytest.mark.parametrize("field,value", [
    ("organizations", ["O2", "O1", "O2"]),
    ("scenarios", ["budget", "actual", "actual"]),
    ("grain_basis", [{"scenarios": ["actual"], "basis": "unavailable", "reason": "not supplied"}]),
])
def test_r4_preserves_existing_optional_server_semantics(field, value):
    record = _semantic_requirement("req2", 10)
    record["items"][0][field] = value
    canonical = sorted(set(value)) if field != "grain_basis" else value
    record["semantic_basis"]["items"][0][field] = canonical
    record["semantic_fingerprint"] = E.legacy._sha(record["semantic_basis"])
    E.legacy._verify_r4_requirement_semantics(record, "test requirement", {"dataset-a": _dataset_state()})


@pytest.mark.parametrize("tamper", ["changed_field", "changed_basis", "omitted_basis"])
def test_r4_rejects_tampered_scenario_semantics(tamper):
    record = scenario_requirement()
    if tamper == "changed_field":
        record["items"][0]["scenarios"] = ["budget"]
    elif tamper == "changed_basis":
        record["semantic_basis"]["items"][0]["scenarios"] = ["budget"]
    else:
        del record["semantic_basis"]["items"][0]["scenarios"]
    with pytest.raises(AssertionError, match="semantic_basis"):
        E.legacy._verify_r4_requirement_semantics(record, "test requirement", {"dataset-a": _dataset_state()})


def test_r4_rejects_run_bound_to_different_scenario_fingerprint():
    state, row = lawful_state([{"current_year_collection_rate": "0.9"}], [
        {"basis": "calculation", "run_id": "r", "row": 0, "column": "current_year_collection_rate", "value": "0.9"}])
    record = scenario_requirement()
    state["requirements"] = [record]
    state["runs"][0]["requirements_semantic_fingerprint"] = record["semantic_fingerprint"]
    assert E.legal_workflow(state, row)["completed"] is True
    prior_fingerprint = record["semantic_fingerprint"]
    record["items"][0]["scenarios"] = ["budget"]
    record["semantic_basis"]["items"][0]["scenarios"] = ["budget"]
    record["semantic_fingerprint"] = E.legacy._sha(record["semantic_basis"])
    assert record["semantic_fingerprint"] != prior_fingerprint
    result = E.legal_workflow(state, row)
    assert result["completed"] is False
    assert "selected run semantic fingerprint" in result["reason"]


def ratio_artifact(metric="current_year_collection_rate", value="0.9", *, column_form=False):
    rows = [{metric: value}] if column_form else [{"metric_key": metric, "value": value}]
    column = metric if column_form else "value"
    return lawful_state(rows, [{"basis": "calculation", "run_id": "r", "row": 0, "column": column, "value": value}])


@pytest.mark.parametrize("metric", ["current", "collection_rate_current", "current_year_collection_rate", "current_collection_rate"])
@pytest.mark.parametrize("column_form", [False, True])
def test_current_collection_aliases_match_only_cited_named_cells(metric, column_form):
    state, row = ratio_artifact(metric, column_form=column_form)
    result = E.score_professional_artifact(state, {"numeric_checks": [{"metric": "current", "expected": "0.9"}]}, row)
    assert result["status"] == "passed", result


@pytest.mark.parametrize("metric", ["prior_year_collection_rate", "collection_rate_total", "unrelated", "current_year_collection_rate_extra", "current_collection_rate_extra"])
def test_equal_amount_does_not_create_collection_metric_alias(metric):
    state, row = ratio_artifact(metric)
    result = E.score_professional_artifact(state, {"numeric_checks": [{"metric": "current", "expected": "0.9"}]}, row)
    assert result["status"] == "failed"
    assert "missing_cited_metric:current" in result["numeric_errors"]


def test_current_collection_alias_still_rejects_wrong_value():
    state, row = ratio_artifact(value="0.5")
    result = E.score_professional_artifact(state, {"numeric_checks": [{"metric": "current", "expected": "0.9"}]}, row)
    assert result["status"] == "failed"
    assert "wrong_metric:current" in result["numeric_errors"]


@pytest.mark.parametrize("metric", ["comprehensive", "collection_rate_total", "comprehensive_collection_rate"])
@pytest.mark.parametrize("column_form", [False, True])
def test_comprehensive_collection_aliases_match_cited_named_cells(metric, column_form):
    state, row = ratio_artifact(metric, "0.5", column_form=column_form)
    result = E.score_professional_artifact(state, {"numeric_checks": [{"metric": "comprehensive", "expected": "0.5"}]}, row)
    assert result["status"] == "passed", result


@pytest.mark.parametrize("metric", ["current_year_collection_rate", "arrears_recovery_rate", "collection_rate_gap", "comprehensive_collection_rate_extra"])
def test_comprehensive_collection_rejects_other_metrics_with_same_value(metric):
    state, row = ratio_artifact(metric, "0.5")
    result = E.score_professional_artifact(state, {"numeric_checks": [{"metric": "comprehensive", "expected": "0.5"}]}, row)
    assert result["status"] == "failed"
    assert "missing_cited_metric:comprehensive" in result["numeric_errors"]


def test_uncited_correct_collection_cell_cannot_fill_metric():
    state, row = ratio_artifact("unrelated")
    state["runs"][0]["result"]["rows"].append({"metric_key": "current_year_collection_rate", "value": "0.9"})
    result = E.score_professional_artifact(state, {"numeric_checks": [{"metric": "current", "expected": "0.9"}]}, row)
    assert result["status"] == "failed"
    assert "missing_cited_metric:current" in result["numeric_errors"]


def test_compatibility_does_not_waive_reading_method_resource():
    trace = deepcopy(events())
    for event in trace[:2]:
        event.update(name="skill", arguments={"name": "variance-analysis"})
    result = E.skill_first(trace, session="s", resources=RESOURCES)
    assert result["status"] == "failed"
    assert result["failures"] == ["resource_not_read_before_calculation:method-resource"]


@pytest.mark.parametrize("read_foundry", [False, True])
def test_e03_requires_both_method_resources_before_calculation(read_foundry):
    resources = [
        {"tool": "skill", "arguments": {"name": "cash"}, "sha256": "skill-hash"},
        {"tool": "method-resource", "arguments": {"skill": "cash", "resource": "FOUNDRY.md"}, "sha256": "foundry-hash"},
        {"tool": "method-resource", "arguments": {"skill": "cash", "resource": "model-checks.md"}, "sha256": "checks-hash"},
    ]
    trace = []
    for resource in resources[:2 if read_foundry else 1]:
        start = {"phase": "start", "seq": len(trace) + 1, "call_id": resource["sha256"], "session_id": "s",
                 "name": resource["tool"], "arguments": resource["arguments"], "arguments_sha256": "args"}
        trace += [start, {**start, "phase": "end", "seq": start["seq"] + 1, "content_sha256": resource["sha256"], "is_error": False}]
    trace.append({"phase": "start", "seq": len(trace) + 1, "call_id": "calc", "session_id": "s", "name": "explain_variance", "arguments_sha256": "calc"})
    result = E.skill_first(trace, session="s", resources=resources)
    assert result["status"] == "failed"
    assert result["failures"] == ["resource_not_read_before_calculation:method-resource"] * (1 if read_foundry else 2)
