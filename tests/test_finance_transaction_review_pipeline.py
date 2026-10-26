"""Independent observer counterexamples; no product or provider calls."""
from copy import deepcopy
from pathlib import Path

import pytest

from tools import verify_finance_transaction_review_pipeline as driver


def proof():
    draft_id = "draft-1"
    receipt = {"id": "receipt-1", "draft_id": draft_id, "status": "complete"}
    requirements = {"requirements_id": "req-1", "coverage": {"status": "pass"},
                    "original_requirements_completed": True,
                    "items": [{"id": "transaction", "status": "answered", "counts_as_amount_evidence": False}]}
    validation = {"status": "pass", "requirements": requirements}
    return {"draft_id": draft_id, "requirements_id": "req-1",
            "validation": {"returncode": 0, "value": validation},
            "refresh": {"returncode": 0, "value": {"id": draft_id, "completion": receipt}},
            "current_draft": {"id": draft_id, "quality": validation},
            "current_completion": receipt,
            "prepared": {"draft_id": draft_id, "current_status": "approved",
                         "eligibility": {"eligible": True, "scope": "transaction_review_only",
                                         "counts_as_amount_evidence": False, "posting_authorized": False}}}


def test_actual_same_draft_complete_evidence_passes():
    assert driver.completion_problems(proof()) == []


@pytest.mark.parametrize("mutation", ["labels", "refusal", "receipt", "different_draft", "coverage",
                                      "amount", "posting", "unanswered", "quality", "refresh", "ineligible"])
def test_completion_cannot_be_inferred_from_labels_or_partial_evidence(mutation):
    value = deepcopy(proof())
    if mutation == "labels":
        value = {"status": "pass", "accepted": True, "complete": True}
    elif mutation == "refusal":
        value["validation"]["returncode"] = 1
    elif mutation == "receipt":
        value["current_completion"] = None
    elif mutation == "different_draft":
        value["current_completion"]["draft_id"] = "another"
    elif mutation == "coverage":
        value["validation"]["value"]["requirements"]["original_requirements_completed"] = False
    elif mutation in {"amount", "posting"}:
        field = "counts_as_amount_evidence" if mutation == "amount" else "posting_authorized"
        value["prepared"]["eligibility"][field] = True
    elif mutation == "unanswered":
        value["validation"]["value"]["requirements"]["items"][0]["status"] = "unanswered"
    elif mutation == "quality":
        value["current_draft"]["quality"]["status"] = "needs_attention"
    elif mutation == "refresh":
        value["refresh"]["returncode"] = 1
    elif mutation == "ineligible":
        value["prepared"]["eligibility"]["eligible"] = False
    assert driver.completion_problems(value)


def test_refusal_needs_actual_cli_failure_and_relevant_error():
    assert driver.refusal_matches({"returncode": 2, "stderr": "manager actor required"}, "manager")
    assert not driver.refusal_matches({"returncode": 0, "value": {"status": "refused"}}, "manager")
    assert not driver.refusal_matches({"returncode": 2, "stderr": "unknown command"}, "manager")


@pytest.mark.parametrize("after", [{"old": "same", "new_review": "new"}, {"old": "changed"}, {}])
def test_refusal_cannot_append_or_modify_a_record(after):
    assert driver.refused_history_problems({"old": "same"}, after)
    assert not driver.refused_history_problems({"old": "same"}, {"old": "same"})


def test_history_preserves_json_and_xlsx_excluding_only_named_counters_and_locks(tmp_path):
    for name in ("analysis/sequence.json", ".lock", "analysis/completion.lock", "analysis/drafts/a.json",
                 "inputs/a.xlsx", "inputs/sequence.json", "inputs/business.lock"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original")
    before = driver.history_hashes(tmp_path)
    assert set(before) == {"analysis/drafts/a.json", "inputs/a.xlsx", "inputs/sequence.json", "inputs/business.lock"}
    (tmp_path / "inputs/a.xlsx").write_bytes(b"changed")
    assert driver.changed_history(before, driver.history_hashes(tmp_path)) == ["inputs/a.xlsx"]


def test_call_sequence_restoration_and_duplicate_guard(tmp_path):
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / "002-first.json").write_text('{"sequence": 2}')
    (calls / "011-second.json").write_text('{"sequence": 11}')
    assert driver.existing_sequence(tmp_path) == 11
    (calls / "011-duplicate.json").write_text('{"sequence": 11}')
    with pytest.raises(ValueError, match="duplicate"):
        driver.existing_sequence(tmp_path)


def test_new_output_never_overwrites_existing_evidence(tmp_path):
    target = tmp_path / "result.json"
    driver.write_new(target, {"first": True})
    with pytest.raises(FileExistsError):
        driver.write_new(target, {"replacement": True})
    assert 'first' in target.read_text()


def test_pinned_original_driver_and_contract_are_loaded():
    module, contract = driver.load_inputs()
    assert module.file_hash(Path(module.__file__)) == driver.ORIGINAL_SHA256
    assert sum(len(case["controls"]) for case in contract["cases"]) == 5


def test_partial_or_blanket_refusal_cannot_satisfy_full_gate():
    _, contract = driver.load_inputs()
    stages = [{"stage": name, "status": "pass"} for name in contract["required_stages"]]
    families = [{"id": "M07", "status": "pass", "controls": [{"status": "pass", "stages": stages}],
                 "mutant": {"status": "pass", "stages": [
                     {"stage": "mutant_approval_refused", "status": "pass"},
                     {"stage": "mutant_rejection_auditable", "status": "pass"}]}}]
    assert driver.suite_status(families, contract, ["M07"]) == "partial_pass"
    assert driver.suite_status(families, contract, ["M07", "M08", "M09"]) == "fail"
    families[0]["controls"][0]["status"] = "refused"
    assert driver.suite_status(families, contract, ["M07"]) == "fail"


def test_labels_without_required_stage_evidence_cannot_pass():
    _, contract = driver.load_inputs()
    family = {"id": "M07", "status": "pass", "controls": [{"status": "pass"}], "mutant": {"status": "pass"}}
    assert driver.suite_status([family], contract, ["M07"]) == "fail"


def test_revocation_cannot_leave_an_older_receipt_complete():
    observation = {"draft_id": "d", "current_completion": {"id": "r2", "draft_id": "d", "status": "awaiting_manager"},
                   "state": {"completions": [{"id": "r1", "draft_id": "d", "status": "complete"}]}}
    assert driver.incomplete_problems(observation)


def test_restored_cli_refuses_existing_next_sequence_before_subprocess(tmp_path):
    module, _ = driver.load_inputs()
    cli = driver.restore_cli(module, "/not-a-real-foundry", tmp_path, "task")
    driver.write_new(tmp_path / "calls/001-old-call.json", {"sequence": 1})
    with pytest.raises(FileExistsError):
        cli.call("must-not-run")


@pytest.mark.parametrize("tamper", [None, "event", "authority", "implementation", "other_rule"])
def test_epoch_proof_requires_event_identity_authority_and_unchanged_other_rules(tamper):
    before = {"rules": [{"rule_id": "r", "epoch": 0, "epoch_record_id": None, "implementation_version": "v1"},
                        {"rule_id": "other", "epoch": 0}]}
    event = {"rule_epoch": {"id": "event", "rule_id": "r", "epoch": 1, "previous_epoch": 0,
                            "parent_id": None, "implementation_version": "v1", "changed_by": "manager", "session_id": None}}
    after = deepcopy(before)
    after["rules"][0].update(epoch=1, epoch_record_id="event")
    if tamper == "event":
        after["rules"][0]["epoch_record_id"] = "fake"
    elif tamper == "authority":
        event["rule_epoch"]["changed_by"] = "assistant"
    elif tamper == "implementation":
        after["rules"][0]["implementation_version"] = "v2"
    elif tamper == "other_rule":
        after["rules"][1]["epoch"] = 1
    assert bool(driver.epoch_problems("r", before, event, after)) is bool(tamper)
