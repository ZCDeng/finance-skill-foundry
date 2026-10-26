"""Completion requires a verified requirements proof, including historical reads."""
import json

import pytest

from foundry import finance_completion
from foundry.analysis import _hash
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def ratio_case(tmp_path, *, bound=True, items=True):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="完成指纹"))
    source = tmp_path / "ledger.json"
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-08",
             "currency": "CNY", "unit": "元", "scenario": "actual"}
    source.write_text(json.dumps([
        {**scope, "account_code": "1", "management_account": "revenue", "amount": "100"},
        {**scope, "account_code": "2", "management_account": "cost", "amount": "30"},
    ]))
    dataset = service.analysis.add_dataset(source, name="已授权台账")
    context = service.save_context({
        "bindings": {"actual": dataset["id"]},
        "scopes": {"actual": scope},
    })
    requirement = service.analysis_requirements_save({
        "question": "核对成本率", **({"bindings": context["bindings"]} if bound else {}),
        "items": [{"id": "cost_ratio", "metric": "ratio", "requires_drilldown": False}] if items else [],
    })
    run = service.run_metric({
        "context_id": context["id"],
        "metric": {"kind": "ratio", "numerator_accounts": ["cost"],
                   "denominator_accounts": ["revenue"], "filters": {"scenario": "actual"}},
    })
    assert run["execution_status"] == "succeeded"
    return service, requirement, run, context


def save_draft(service, run):
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    return service.save_explanation_draft({
        "run_ids": [run["id"]],
        "body": "核对结果：" + "；".join("{{fact:%s}}" % fact["id"] for fact in facts),
    })


def assert_unverified(receipt):
    assert receipt["status"] == "needs_requirements", receipt
    assert receipt["response_status"] != "complete"
    assert receipt["original_requirements_completed"] is False
    action = next(a for a in receipt["actions"] if a["code"] == "requirements_fingerprint_unverified")
    assert "来源" in action["message"] and "重新运行" in action["message"]


def rewrite_test_record(path, record):
    """Simulate old or semantically corrupted records only in a synthetic task."""
    record = {k: v for k, v in record.items() if k != "_integrity_hash"}
    path.write_text(json.dumps({**record, "_integrity_hash": _hash(record)}))


def test_unbound_requirements_cannot_complete_even_with_correct_cited_calculation(tmp_path):
    service, requirement, run, _ = ratio_case(tmp_path, bound=False)
    assert requirement["bindings"] == {}
    assert requirement["semantic_fingerprint"] is None
    assert run["requirements_semantic_fingerprint"] is None
    draft = save_draft(service, run)
    assert draft["quality"]["status"] == "pass", draft["quality"]
    assert_unverified(draft["completion"])


@pytest.mark.parametrize("mutation", ["missing", "forged", "basis"])
def test_nonempty_but_invalid_requirements_proof_does_not_complete(tmp_path, mutation):
    service, requirement, run, _ = ratio_case(tmp_path)
    changed = dict(requirement)
    if mutation == "basis":
        changed["semantic_basis"] = {**changed["semantic_basis"], "question": "另一问题"}
    else:
        changed["semantic_fingerprint"] = None if mutation == "missing" else "f" * 64
    # Corrupt only this test's record while retaining valid storage integrity.
    rewrite_test_record(service.analysis._object_path("requirements", requirement["id"]), changed)
    assert service.analysis.fingerprint_in_view(changed, None) is None
    draft = save_draft(service, run)
    assert_unverified(draft["completion"])


def test_valid_bound_completion_and_replay_remain_idempotent(tmp_path):
    service, requirement, run, context = ratio_case(tmp_path)
    draft = save_draft(service, run)
    receipt = draft["completion"]
    assert receipt["status"] == "complete", receipt
    assert receipt["requirements_semantic_fingerprint"] == requirement["semantic_fingerprint"]
    stored = service.analysis.get_draft(draft["id"])
    again = finance_completion.record_completion(service.analysis, stored, stored["explanation_check"])
    assert again["id"] == receipt["id"]
    assert len(service.analysis._list("completions")) == 1
    for allowed in (None, set(context["bindings"].values())):
        assert service.analysis.completion_in_view(receipt, allowed)["status"] == "complete"


def test_unverified_completion_replay_is_idempotent(tmp_path):
    service, _, run, _ = ratio_case(tmp_path, bound=False)
    draft = save_draft(service, run)
    stored = service.analysis.get_draft(draft["id"])
    again = finance_completion.record_completion(service.analysis, stored, stored["explanation_check"])
    assert_unverified(again)
    assert again["id"] == draft["completion"]["id"]
    assert len(service.analysis._list("completions")) == 1


def test_lost_proof_cannot_replay_a_previous_complete_receipt(tmp_path):
    service, requirement, run, _ = ratio_case(tmp_path)
    draft = save_draft(service, run)
    assert draft["completion"]["status"] == "complete"
    changed = {**requirement, "semantic_fingerprint": None}
    rewrite_test_record(service.analysis._object_path("requirements", requirement["id"]), changed)
    stored = service.analysis.get_draft(draft["id"])
    again = finance_completion.record_completion(service.analysis, stored, stored["explanation_check"])
    assert_unverified(again)
    assert again["id"] != draft["completion"]["id"]
    assert finance_completion.record_completion(service.analysis, stored, stored["explanation_check"])["id"] == again["id"]


def test_unbound_requirements_without_data_can_be_saved_but_remain_pending(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="待来源"))
    requirement = service.analysis_requirements_save({
        "question": "核对利润", "items": [{"id": "profit", "metric": "profit"}],
    })
    assert requirement["bindings"] == {}
    assert requirement["semantic_fingerprint"] is None
    draft = service.save_explanation_draft({"body": "需要提供实际来源后核对。"})
    assert_unverified(draft["completion"])
    assert service.analysis._get("requirements", requirement["id"])["bindings"] == {}


def test_bound_new_requirement_does_not_relabel_unbound_old_run(tmp_path):
    service, requirement, run, context = ratio_case(tmp_path, bound=False)
    current = service.analysis_requirements_save({
        "parent_id": requirement["id"], "context_id": context["id"],
        "question": requirement["question"], "items": requirement["items"],
    })
    assert current["semantic_fingerprint"]
    draft = save_draft(service, run)
    assert draft["completion"]["status"] != "complete"
    assert any(a["code"] == "requirements_run_outdated" for a in draft["completion"]["actions"])


def test_no_items_remains_unassessed_without_invented_source(tmp_path):
    service, requirement, run, _ = ratio_case(tmp_path, bound=False, items=False)
    assert requirement["bindings"] == {}
    draft = save_draft(service, run)
    assert draft["completion"]["status"] == "needs_requirements"
    assert not any(a["code"] == "requirements_fingerprint_unverified" for a in draft["completion"]["actions"])


def test_verified_missing_inputs_remain_awaiting_input(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="待输入"))
    path = tmp_path / "amounts.json"
    path.write_text(json.dumps([{"amount": "25", "unit": "元"}]))
    source = service.analysis.add_dataset(path, name="仅金额")
    requirement = service.analysis_requirements_save({
        "question": "解释量价变化", "bindings": {"source": source["id"]},
        "items": [{"id": "pq", "metric": "price_quantity", "requires_drilldown": True}],
    })
    assert requirement["semantic_fingerprint"]
    draft = service.save_explanation_draft({"body": "需要补充数量与单价资料。"})
    assert draft["completion"]["status"] == "awaiting_input"
    assert draft["completion"]["response_status"] == "ended_with_limitations"
    assert not draft["completion"]["original_requirements_completed"]


@pytest.mark.parametrize("bound", [False, True])
def test_old_receipt_is_rechecked_without_mutating_history_or_narrowing_authority(tmp_path, bound):
    service, _, run, context = ratio_case(tmp_path, bound=bound)
    draft = save_draft(service, run)
    receipt = {**draft["completion"], "completion_policy_version": 14,
               "status": "complete", "response_status": "complete", "stop_reason": "complete",
               "original_requirements_completed": True, "repair_allowed": False, "actions": []}
    path = service.analysis._object_path("completions", receipt["id"])
    rewrite_test_record(path, receipt)
    before = {p: p.read_bytes() for p in service.analysis.root.rglob("*.json")}
    stored = service.analysis._get("completions", receipt["id"])
    assert stored["status"] == "complete"
    for allowed in (None, set(context["bindings"].values())):
        view = service.analysis.completion_in_view(stored, allowed)
        if bound:
            assert view["status"] == "complete"
        else:
            assert_unverified(view)
            assert view["historical_status"] == "complete"
            assert view["current_completion_policy_version"] >= 15
        assert service.analysis.completion_in_view(stored, allowed) == view
    assert service.analysis.completion_in_view(stored, set()) is None
    assert all(p.read_bytes() == data for p, data in before.items())
    assert {p for p in service.analysis.root.rglob("*.json")} == set(before)
