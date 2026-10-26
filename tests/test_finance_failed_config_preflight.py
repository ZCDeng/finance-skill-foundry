"""Invalid model configuration has a failed audit record, never an executed result."""
from copy import deepcopy

import pytest

from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from test_finance_runtime_ordering import setup_case, register, task_bytes


ERRORS = {
    "formula": "registered template formulas and model boundaries cannot be overridden",
    "reference": "driver binding requires matching rows and exactly one row for single",
}


def invalid_scenario(manager, context, scenario, mutation):
    inputs = deepcopy(scenario["inputs"])
    if mutation == "formula":
        inputs["drivers"] = [{"name": "net_income", "formula": "revenue + operating_expense + depreciation"}]
    else:
        inputs["source_bindings"]["revenue"]["selector"] = {"input_name": "missing_reference"}
    return manager.save_scenario({"context_id": context["id"], "kind": "driver_model",
                                  "label": "Invalid candidate", "inputs": inputs})


@pytest.mark.parametrize("mutation", ERRORS)
@pytest.mark.parametrize("has_old_requirements", [False, True])
@pytest.mark.parametrize("entry", ["scenario", "revision"])
def test_invalid_configuration_is_failed_visible_and_non_citable(tmp_path, monkeypatch, mutation, has_old_requirements, entry):
    import foundry.finance_scenario_service as calculations

    manager, runtime, context, scenario = setup_case(tmp_path)
    old = register(runtime, context, scenario) if has_old_requirements else None
    invalid = invalid_scenario(manager, context, scenario, mutation)
    requests_before = deepcopy(manager.analysis._list("requirements"))
    confirmations_before = deepcopy(manager._list("profile_confirmations"))
    calls = []
    def never_calculate(*args, **kwargs):
        calls.append(True)
        raise AssertionError("a failed config must not enter the calculator")
    monkeypatch.setattr(calculations, "calculate_scenario", never_calculate)
    spec = {"scenario_id": invalid["id"]}
    revision = manager._save_revision(context, "scenario", spec) if entry == "revision" else None
    run = runtime.run_revision(revision) if revision else runtime.run_scenario(spec)
    assert calls == []
    assert run["execution_status"] == "failed"
    assert run["error"] == ERRORS[mutation]
    assert run["error_phase"] == "configuration_preflight"
    assert run["requirements_validation"] == "not_evaluated_invalid_configuration"
    assert run["result"] == {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    assert run["output_hash"] is None
    assert run["reproducibility_status"] == "unverified" and run["completeness"] == "incomplete"
    assert run["review_status"] == "unreviewed"
    assert run["requirements_id"] == (old["id"] if old else None)
    assert run["requirements_semantic_fingerprint"] is None
    assert run["professional_identity"] is None
    assert "requirements_rule_identity" not in run
    assert manager.analysis._list("requirements") == requests_before
    assert manager._list("profile_confirmations") == confirmations_before
    assert runtime.analysis.get_run(run["id"])["error"] == ERRORS[mutation]
    with pytest.raises(FoundryError, match="successful run"):
        runtime.prepare_explanation({"run_ids": [run["id"]]})
    with pytest.raises(FoundryError, match="successful run"):
        runtime.save_explanation_draft({"body": "候选结果要求后端验证。", "run_ids": [run["id"]],
                                       "requirements_id": old["id"] if old else None, "claims": []})
    assert runtime.analysis._list("drafts") == []


@pytest.mark.parametrize("entry", ["scenario", "revision"])
@pytest.mark.parametrize("requirements", ["missing", "different_scenario"])
def test_valid_configuration_still_requires_current_requirements_before_any_execution_or_write(tmp_path, monkeypatch, entry, requirements):
    import foundry.finance_scenario_service as calculations

    manager, runtime, context, scenario = setup_case(tmp_path)
    if requirements == "different_scenario":
        register(runtime, context, scenario)
        scenario = manager.save_scenario({"context_id": context["id"], "kind": "driver_model",
                                          "label": "Another valid scenario", "inputs": deepcopy(scenario["inputs"])})
    spec = {"scenario_id": scenario["id"]}
    revision = manager._save_revision(context, "scenario", spec) if entry == "revision" else None
    before = task_bytes(runtime)
    calls = []
    monkeypatch.setattr(calculations, "calculate_scenario", lambda *a, **k: calls.append(True))
    with pytest.raises(FoundryError, match="analysis_requirements_save"):
        runtime.run_revision(revision) if revision else runtime.run_scenario(spec)
    assert calls == []
    assert task_bytes(runtime) == before


@pytest.mark.parametrize("mutation", ERRORS)
@pytest.mark.parametrize("entry", ["scenario", "revision"])
def test_unreadable_source_is_refused_before_configuration_diagnostics(tmp_path, monkeypatch, mutation, entry):
    manager, _, context, scenario = setup_case(tmp_path)
    invalid = invalid_scenario(manager, context, scenario, mutation)
    runtime = FinanceStore(manager.task, snapshot_ids=[], session_id="unauthorized-runtime")
    spec = {"scenario_id": invalid["id"]}
    revision = manager._save_revision(context, "scenario", spec) if entry == "revision" else None
    before = task_bytes(manager)
    def forbidden_read(*args, **kwargs):
        raise AssertionError("must authorize sources before reading their contents")
    monkeypatch.setattr(runtime.analysis, "read_dataset", forbidden_read)
    with pytest.raises(FoundryError, match="outside this session context") as exc:
        runtime.run_revision(revision) if revision else runtime.run_scenario(spec)
    assert "missing_reference" not in str(exc.value) and "overridden" not in str(exc.value)
    assert task_bytes(manager) == before
