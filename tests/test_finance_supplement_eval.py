"""Counterexamples for independent provider scoring and unsolved public seeds."""
from copy import deepcopy

import pytest

from tools import finance_supplement_eval as runner


def sample():
    names = [f"metric_{i}" for i in range(13)]
    checks = [f"check_{i}" for i in range(12)]
    contract = {"required_metrics": names, "required_model_checks": checks,
                "template_id": "test-template", "scope": {"organization": "Fixture", "period": "2026-10", "currency": "CNY", "unit": "元", "ledger": "ledger", "scenario": "forecast"},
                "limits": {"timeout_seconds": 420, "max_tool_turns": 80}}
    rows = [{"metric_key": key, "value": str(i), "period": "2026-10", "organization": "Fixture", "currency": "CNY", "unit": "元",
             "source_rows": [{"dataset_id": "source"}], "source_binding_ids": [f"boundary.{j}" for j in range(8)]}
            for i, key in enumerate(names)]
    bindings = {f"input_{i}": {"source_rows": [{"dataset_id": "source"}], "ledger": "ledger", "scenario": "forecast"} for i in range(16)}
    bindings.update({f"boundary.{i}": {"source_rows": [{"dataset_id": "source"}], "ledger": "ledger", "scenario": "forecast"} for i in range(8)})
    result = {"scenario_id": "scenario", "input_hash": "inputs", "template_id": "test-template", "rows": rows,
              "source_binding_status": {"all_sources_verified": True, "bindings": bindings},
              "model_checks": [{"id": name, "status": "pass", "source_rows": [{"dataset_id": "source"}]} for name in checks],
              "model_boundary": [{"name": str(i), "value": "0"} for i in range(8)]}
    run = {"id": "run", "engine": "finance", "execution_status": "succeeded", "result": result,
           "output_hash": runner.base.canonical_hash(result)}
    claims = [{"basis": "calculation", "run_id": "run", "row": i, "column": "value", "value": str(i)} for i in range(13)]
    draft = {"id": "draft", "run_ids": ["run"], "claims": claims,
             "explanation_check": {"requirements": {"items": [{"metric": key, "status": "answered"} for key in names]}}}
    state = {"requirements": [{"items": [{"metric": key} for key in names]}], "runs": [run], "scenarios": [{"id": "scenario", "input_hash": "inputs", "inputs": {"period": "2026-10", "scope": contract["scope"]}}]}
    row = {"completed": True, "duration_ms": 1000, "calls": [{}], "final_draft": draft, "provider_retries": []}
    return contract, state, row


def test_extra_guards_accept_full_native_shape():
    contract, state, row = sample()
    assert runner.supplement_problems(state, row, contract) == []


def test_internally_valid_invented_dataset_is_not_original_public_source():
    contract, state, row = sample()
    seed = {"datasetIds": {"template_inputs": "source", "model_boundary": "source"}}
    assert runner.supplement_problems(state, row, contract, seed) == []
    run = state["runs"][0]
    run["result"]["source_binding_status"]["bindings"]["input_0"]["source_rows"][0]["dataset_id"] = "invented"
    run["output_hash"] = runner.base.canonical_hash(run["result"])
    assert "native_source_not_from_frozen_public_seed" in runner.supplement_problems(state, row, contract, seed)


@pytest.mark.parametrize("mutation", ["one_requirement", "repeated_check", "bad_check", "unbound", "no_boundary",
                                      "wrong_scope", "script", "output_hash", "partial_citation", "timeout", "too_many_tools", "wrong_metric"])
def test_base_score_pass_cannot_mask_incomplete_native_contract(mutation):
    contract, state, row = sample()
    run = state["runs"][0]
    if mutation == "one_requirement":
        state["requirements"][0]["items"] = state["requirements"][0]["items"][:1]
    elif mutation == "repeated_check":
        run["result"]["model_checks"][-1] = deepcopy(run["result"]["model_checks"][0])
    elif mutation == "bad_check":
        run["result"]["model_checks"][0]["status"] = "fail"
    elif mutation == "unbound":
        run["result"]["source_binding_status"]["all_sources_verified"] = False
    elif mutation == "no_boundary":
        run["result"]["model_boundary"].pop()
    elif mutation == "wrong_scope":
        run["result"]["rows"][0]["period"] = "2026-09"
    elif mutation == "script":
        run["engine"] = "analysis-script"
    elif mutation == "output_hash":
        run["output_hash"] = "forged"
    elif mutation == "partial_citation":
        row["final_draft"]["claims"].pop()
    elif mutation == "timeout":
        row["duration_ms"] = 420001
    elif mutation == "too_many_tools":
        row["calls"] = [{}] * 81
    elif mutation == "wrong_metric":
        run["result"]["rows"][0]["metric_key"] = "metric_1"
    if mutation != "output_hash":
        run["output_hash"] = runner.base.canonical_hash(run["result"])
    assert runner.supplement_problems(state, row, contract)


def test_private_control_fields_never_project_to_runtime_seed():
    seed = {"id": "s", "taskId": "t", "question": "Public task", "precondition": {"private": True}, "oracle": "secret"}
    with pytest.raises(ValueError, match="unexpected"):
        runner.runtime_seed(seed)
    seed.pop("oracle")
    assert runner.runtime_seed(seed) == {"id": "s", "taskId": "t", "question": "Public task"}


@pytest.mark.parametrize("collection", ["requirements", "runs", "drafts", "completions"])
def test_seed_rejects_precomputed_state_even_if_summary_says_empty(collection):
    with pytest.raises(ValueError, match="unsolved"):
        runner.assert_unsolved({collection: [{"id": "precomputed"}]})


def test_hidden_precomputed_record_cannot_hide_behind_empty_public_state(tmp_path):
    runner.assert_unsolved({})
    path = tmp_path / "runs/.hidden/result.json"
    path.parent.mkdir(parents=True)
    path.write_text('{}')
    with pytest.raises(ValueError, match="unsolved on disk"):
        runner.assert_unsolved_files(tmp_path)


def test_slot_rollup_rejects_duplicate_success_and_mixed_candidates():
    slots = [{"candidate": "a", "suite": "professional_supplement_v2", "family": "E18", "case": "SUP-A", "variant": "independent", "repeat": i} for i in range(1, 4)]
    attempts = [{"slot": slot, "score": {"status": "passed"}, "task_id": str(i), "session_id": str(i)} for i, slot in enumerate(slots)]
    assert runner.rollup(slots, attempts)["status"] == "passed"
    assert runner.rollup(slots, attempts + [deepcopy(attempts[0])])["status"] == "failed"
    attempts[1]["slot"] = {**attempts[1]["slot"], "candidate": "other"}
    assert runner.rollup(slots, attempts)["status"] == "failed"


def test_same_task_or_session_cannot_count_as_independent_repetitions():
    slots = [{"candidate": "a", "suite": "professional_supplement_v2", "family": "E18", "case": "SUP-A", "variant": "independent", "repeat": i} for i in range(1, 4)]
    attempts = [{"slot": slot, "score": {"status": "passed"}, "task_id": "same", "session_id": str(i)} for i, slot in enumerate(slots)]
    assert runner.rollup(slots, attempts)["status"] == "failed"


@pytest.mark.parametrize("field", ["ledger", "scenario"])
def test_same_numbers_with_foreign_source_scope_are_rejected(field):
    contract, state, row = sample()
    run = state["runs"][0]
    for proof in run["result"]["source_binding_status"]["bindings"].values():
        proof[field] = "foreign"
    run["output_hash"] = runner.base.canonical_hash(run["result"])
    assert "native_source_scope_differs_from_frozen_contract" in runner.supplement_problems(state, row, contract)


@pytest.mark.parametrize("elapsed", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_elapsed_time_is_explicitly_rejected(elapsed):
    contract, state, row = sample()
    row["duration_ms"] = elapsed
    assert "runtime_duration_outside_contract" in runner.supplement_problems(state, row, contract)


@pytest.mark.parametrize("field", ["id", "slot", "attempt", "task_id", "session_id", "input_sha256"])
def test_observation_must_match_each_seed_identity(field):
    seed = {"id": "case", "slot": {"case": "a"}, "attempt": 1, "taskId": "t", "sessionId": "s", "inputSha256": "h"}
    row = {"id": "case", "slot": {"case": "a"}, "attempt": 1, "task_id": "t", "session_id": "s", "input_sha256": "h"}
    assert runner.observation_identity_problems(row, seed) == []
    row[field] = "foreign"
    assert runner.observation_identity_problems(row, seed) == ["observation_identity_mismatch:" + field]
