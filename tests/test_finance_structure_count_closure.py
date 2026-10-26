"""Live r5 count wording regressions backed by actual authorized native results."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from foundry import finance_explanations as explanations
from foundry.analysis import _hash
from foundry.finance_driver_templates import OUTPUT_SEMANTICS, TEMPLATE_ID, TEMPLATE_INPUTS
from test_finance_runtime_ordering import register, setup_case


PASS_CAUTION = "12项模型检查全部通过不等于所有差额均为零，仍需专业复核。"
SOURCE_OUTPUTS = "核查结果：13项需求全部有引擎输出且来源可追溯。"


@pytest.fixture(scope="module")
def actual_basis(tmp_path_factory):
    manager, runtime, context, scenario = setup_case(
        tmp_path_factory.mktemp("actual-count-proof"), scenario_name="management-forecast")
    requirement = register(runtime, context, scenario, items=[
        {"id": metric, "metric": metric,
         "dimensions": {"metric_key": metric, "template_id": TEMPLATE_ID, "scenario_id": scenario["id"]},
         "requires_drilldown": False} for metric in OUTPUT_SEMANTICS])
    run = runtime.run_scenario({"scenario_id": scenario["id"]})
    prepared = runtime.prepare_explanation({"run_ids": [run["id"]]})
    proofs = {p["kind"]: p for p in prepared["structure_counts"]}
    assert {"model_checks", "required_metrics"} <= set(proofs)
    assert proofs["model_checks"]["count"] == 12
    assert proofs["model_checks"]["all_pass"] is True
    assert proofs["required_metrics"]["count"] == 13
    assert proofs["required_metrics"]["source_bound"] is True
    for proof in proofs.values():
        assert proof["run_id"] == run["id"]
        assert proof["requirements_id"] == requirement["id"] == run["requirements_id"]
        assert proof["output_hash"] == run["output_hash"] == _hash(run["result"])
        assert proof["count"] == len(proof["member_ids"]) == len(set(proof["member_ids"]))
    assert any(check["difference"] != "0" for check in run["result"]["model_checks"])
    return SimpleNamespace(manager=manager, runtime=runtime, context=context, scenario=scenario,
                           requirement=requirement, run=run, prepared=prepared)


def parse(basis, body, prepared=None, requirement_id=None):
    return explanations._structure_count_spans(
        body, basis.prepared if prepared is None else prepared,
        basis.requirement["id"] if requirement_id is None else requirement_id)


@pytest.mark.parametrize("body", [PASS_CAUTION, SOURCE_OUTPUTS])
def test_actual_native_proof_accepts_confirmed_r5_count_wording(actual_basis, body):
    basis = actual_basis
    saved = basis.runtime.save_explanation_draft({
        "use_prepared_template": True, "run_ids": [basis.run["id"]],
        "requirements_id": basis.requirement["id"], "qualitative_note": body})
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert saved["completion"]["status"] == "complete"
    assert all(item["status"] == "answered" for item in saved["explanation_check"]["requirements"]["items"])
    spans, issues = parse(basis, body)
    assert not issues
    assert [body[a:b] for a, b in spans] == ["12" if body == PASS_CAUTION else "13"]
    assert explanations._body_numbers(body, ignored_spans=spans) == []


@pytest.mark.parametrize("body", [PASS_CAUTION.replace("12", "13"), SOURCE_OUTPUTS.replace("13", "12")])
def test_wrong_count_does_not_borrow_actual_native_proof(actual_basis, body):
    spans, issues = parse(actual_basis, body)
    assert not spans and issues


@pytest.mark.parametrize("body", [PASS_CAUTION, SOURCE_OUTPUTS])
@pytest.mark.parametrize("invalid", ["missing", "duplicate", "different_requirement", "two_actual_runs"])
def test_r5_wording_needs_single_current_unambiguous_proof(actual_basis, body, invalid):
    basis = actual_basis
    prepared = deepcopy(basis.prepared)
    requirement_id = basis.requirement["id"]
    if invalid == "missing":
        prepared["structure_counts"] = []
    elif invalid == "duplicate":
        prepared["structure_counts"] *= 2
    elif invalid == "different_requirement":
        requirement_id = "different-requirement"
    else:
        second = basis.runtime.run_scenario({"scenario_id": basis.scenario["id"]})
        assert second["id"] != basis.run["id"]
        prepared = basis.runtime.prepare_explanation({"run_ids": [basis.run["id"], second["id"]]})
        assert prepared["structure_counts"] == []
    spans, issues = parse(basis, body, prepared, requirement_id)
    assert not spans and issues


@pytest.mark.parametrize("invalid", ["scope_period", "scope_scenario", "source_unverified", "unreadable_requirement"])
def test_source_output_label_cannot_certify_unbound_or_inaccessible_members(actual_basis, invalid):
    basis = actual_basis
    requirement, run = deepcopy(basis.requirement), deepcopy(basis.run)
    if invalid == "scope_period":
        requirement["scope"]["period"] = "2027-01"
    elif invalid == "scope_scenario":
        requirement["scope"]["scenario"] = "actual"
    elif invalid == "source_unverified":
        run["result"]["source_binding_status"]["all_sources_verified"] = False
        run["output_hash"] = _hash(run["result"])
    else:
        requirement["bindings"]["unreadable"] = "private-snapshot"
    # Mutate only in-memory copies of actual native records; no stored history changes.
    analysis = SimpleNamespace(_get=lambda kind, identifier: requirement,
                               run_in_view=basis.runtime.analysis.run_in_view)
    prepared = {"structure_counts": explanations._structure_counts(
        analysis, [run], basis.prepared["facts"], allowed=basis.runtime.allowed)}
    spans, issues = parse(basis, SOURCE_OUTPUTS, prepared)
    assert not spans and issues


@pytest.mark.parametrize("invalid", ["failed_check", "duplicate_check"])
def test_cautious_pass_label_still_needs_every_unique_check_to_pass(actual_basis, invalid):
    basis = actual_basis
    run = deepcopy(basis.run)
    if invalid == "failed_check":
        run["result"]["model_checks"][0]["status"] = "fail"
    else:
        run["result"]["model_checks"][0]["id"] = run["result"]["model_checks"][1]["id"]
    run["output_hash"] = _hash(run["result"])
    prepared = {"structure_counts": explanations._structure_counts(
        basis.runtime.analysis, [run], basis.prepared["facts"], allowed=basis.runtime.allowed)}
    spans, issues = parse(basis, PASS_CAUTION, prepared)
    assert not spans and issues


@pytest.mark.parametrize("body", [
    "现金为12项模型检查全部通过不等于所有差额均为零。",
    "现金13项需求全部有引擎输出且来源可追溯。",
    "13项需求全部有引擎输出且来源可追溯万元。",
    "12项模型检查全部通过不等于所有差额均为零万元。",
    "12项模型检查全部通过（实际与期望差异均为0）。",
    "12项模型检查全部通过所有差额均为零。",
    "12项模型检查全部通过不等于所有差额均为零并批准过账。",
])
def test_r5_count_labels_do_not_certify_money_or_false_compound_assertions(actual_basis, body):
    spans, issues = parse(actual_basis, body)
    assert not spans and issues


@pytest.mark.parametrize("body", [PASS_CAUTION, SOURCE_OUTPUTS])
def test_neighboring_amounts_and_boundary_zero_remain_financial(actual_basis, body):
    body += "收入931元，边界金额0，比例12%，公式13=12+1。"
    spans, _ = parse(actual_basis, body)
    remaining = [item["text"] for item in explanations._body_numbers(body, ignored_spans=spans)]
    assert remaining[-6:] == ["931", "0", "12%", "13", "12", "1"]


def test_actual_save_keeps_unreferenced_financial_amount_blocked(actual_basis):
    basis = actual_basis
    saved = basis.runtime.save_explanation_draft({
        "use_prepared_template": True, "run_ids": [basis.run["id"]],
        "requirements_id": basis.requirement["id"], "qualitative_note": "未引用收入931元。"})
    assert saved["quality"]["status"] == "needs_attention"
    assert saved["completion"]["status"] != "complete"
    assert any(issue["code"] == "uncited_number" and issue.get("text") == "931"
               for issue in saved["quality"]["issues"])


MANAGER_CAUTION = "12项model_checks均通过不替代经理认可，仍须专业复核。"
INPUT_LIMIT = "仅限已确认的八项零边界与16项来源绑定输入有效；仍需专业复核。"


@pytest.mark.parametrize("body,token", [(MANAGER_CAUTION, "12"), (INPUT_LIMIT, "16")])
def test_r7_actual_source_count_and_manager_caution_save_cleanly(actual_basis, body, token):
    basis = actual_basis
    saved = basis.runtime.save_explanation_draft({
        "use_prepared_template": True, "run_ids": [basis.run["id"]],
        "requirements_id": basis.requirement["id"], "qualitative_note": body})
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert saved["completion"]["status"] == "complete"
    spans, issues = parse(basis, body)
    assert not issues and [body[a:b] for a, b in spans] == [token]
    assert not explanations._body_numbers(body, ignored_spans=spans)


def test_r7_source_input_proof_lists_actual_members_without_amount_qualification(actual_basis):
    basis = actual_basis
    proof = next(p for p in basis.prepared["structure_counts"] if p["kind"] == "source_bound_inputs")
    assert proof["count"] == len(TEMPLATE_INPUTS)
    assert set(proof["member_ids"]) == set(TEMPLATE_INPUTS)
    assert proof["source_bound"] is True
    assert proof["counts_as_amount_evidence"] is False
    assert proof["source_dataset_ids"] == sorted(set(basis.context["bindings"].values()))
    input_rows = {i for i, row in enumerate(basis.run["result"]["rows"]) if row.get("source") == "input"}
    inspection = basis.runtime.prepare_explanation({"run_ids": [basis.run["id"]], "fact_view": "inspection"})
    input_facts = [f for f in inspection["facts"] if f["row"] in input_rows]
    assert input_facts and all(f["evidence_eligibility"]["counts_as_amount_evidence"] is False for f in input_facts)


@pytest.mark.parametrize("body", [MANAGER_CAUTION, INPUT_LIMIT])
@pytest.mark.parametrize("invalid", ["wrong_count", "missing", "duplicate", "other_requirement", "multiple_runs"])
def test_r7_new_count_forms_cannot_borrow_wrong_or_ambiguous_proof(actual_basis, body, invalid):
    basis = actual_basis
    prepared = deepcopy(basis.prepared)
    requirement_id = basis.requirement["id"]
    if invalid == "wrong_count":
        body = body.replace("12项", "13项").replace("16项", "17项")
    elif invalid == "missing":
        prepared["structure_counts"] = []
    elif invalid == "duplicate":
        prepared["structure_counts"] *= 2
    elif invalid == "other_requirement":
        requirement_id = "other-requirement"
    else:
        prepared["structure_counts"] = explanations._structure_counts(
            basis.runtime.analysis, [basis.run, deepcopy(basis.run)], basis.prepared["facts"],
            allowed=basis.runtime.allowed)
    spans, _ = parse(basis, body, prepared, requirement_id)
    assert not spans and explanations._body_numbers(body, ignored_spans=spans)


@pytest.mark.parametrize("invalid", [
    "failed_check", "duplicate_check", "missing_check", "unverified", "duplicate_input", "missing_input",
    "missing_binding", "wrong_binding_id", "missing_source_rows", "unbound_source", "source_row_mismatch",
    "input_value_mismatch", "driver_state_mismatch", "source_period", "source_currency", "source_unit",
    "source_organization", "source_scenario", "source_ledger", "scope_conflict", "output_hash",
    "requirement_scope", "unreadable_requirement", "unauthorized_run", "malformed_row", "malformed_driver",
    "input_and_source_period_drift",
])
def test_source_input_count_requires_complete_authorized_native_proof(actual_basis, invalid):
    basis = actual_basis
    run, req = deepcopy(basis.run), deepcopy(basis.requirement)
    result = run["result"]
    # Stored JSON has independent top-level and nested result arrays.
    result["model_checks"] = deepcopy(result["model_checks"])
    row = next(row for row in result["rows"] if row.get("driver") == "opening_cash")
    proof = result["source_binding_status"]["bindings"]["opening_cash"]
    if invalid == "failed_check":
        result["model_checks"][0]["status"] = "fail"
    elif invalid == "duplicate_check":
        result["model_checks"][0]["id"] = result["model_checks"][1]["id"]
    elif invalid == "missing_check":
        result["model_checks"].pop()
    elif invalid == "unverified":
        proof["status"] = "unverified"
    elif invalid == "duplicate_input":
        result["rows"].append(deepcopy(row))
    elif invalid == "missing_input":
        result["rows"].remove(row)
    elif invalid == "missing_binding":
        result["source_binding_status"]["bindings"].pop("opening_cash")
    elif invalid == "wrong_binding_id":
        row["source_binding_ids"] = ["opening_receivables"]
    elif invalid == "missing_source_rows":
        proof["source_rows"] = []
    elif invalid == "unbound_source":
        proof["source_rows"][0]["dataset_id"] = "private-unbound-dataset"
        row["source_rows"] = deepcopy(proof["source_rows"])
        result["source_binding_status"]["drivers"]["opening_cash"]["source_rows"] = deepcopy(proof["source_rows"])
    elif invalid == "source_row_mismatch":
        row["source_rows"][0]["row_index"] = 999
    elif invalid == "input_value_mismatch":
        row["value"] = "999"
    elif invalid == "driver_state_mismatch":
        result["source_binding_status"]["drivers"]["opening_cash"]["source_binding_ids"] = ["revenue"]
    elif invalid.startswith("source_"):
        proof[invalid.removeprefix("source_")] = "wrong-scope"
    elif invalid == "scope_conflict":
        run["finance_scope"]["inputs"]["scenario"] = "actual"
    elif invalid == "requirement_scope":
        req["scope"]["currency"] = "USD"
    elif invalid == "unreadable_requirement":
        req["bindings"]["private"] = "private-unbound-dataset"
    elif invalid == "unauthorized_run":
        run["bindings"]["private"] = "private-unbound-dataset"
    elif invalid == "malformed_row":
        result["rows"].append("malformed-input-row")
    elif invalid == "malformed_driver":
        row["driver"] = ["opening_cash"]
    elif invalid == "input_and_source_period_drift":
        row["period"] = "2027-02"
        proof["period"] = "2027-01"
    run["output_hash"] = "wrong-hash" if invalid == "output_hash" else _hash(result)
    analysis = SimpleNamespace(_get=lambda kind, identifier: req,
                               run_in_view=basis.runtime.analysis.run_in_view)
    counts = explanations._structure_counts(analysis, [run], basis.prepared["facts"], allowed=basis.runtime.allowed)
    assert not any(p["kind"] == "source_bound_inputs" for p in counts)
    spans, _ = parse(basis, INPUT_LIMIT, {"structure_counts": counts})
    assert not spans


@pytest.mark.parametrize("body", [
    "现金为16项来源绑定输入有效。", "16项来源绑定输入有效万元。", "16项来源绑定输入有效并授权过账。",
    "16项来源绑定输入均为0。", "16项来源绑定输入金额合计。", "12项model_checks均通过替代经理认可。",
    "12项model_checks均通过不替代经理认可并已获准过账。",
])
def test_r7_source_counts_never_waive_financial_values_or_approval_claims(actual_basis, body):
    spans, _ = parse(actual_basis, body)
    assert not spans and explanations._body_numbers(body, ignored_spans=spans)


def test_r7_input_count_keeps_adjacent_input_amount_unqualified(actual_basis):
    body = INPUT_LIMIT + "期初现金160元，16万元，边界0。"
    spans, _ = parse(actual_basis, body)
    remaining = [item["text"] for item in explanations._body_numbers(body, ignored_spans=spans)]
    assert remaining[-3:] == ["160", "16", "0"]
