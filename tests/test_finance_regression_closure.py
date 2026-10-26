"""Source scopes and request-local reads preserve current review and integrity gates."""
import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.finance_transaction_reviews import has_transaction
from foundry.task import TaskStore
from test_finance_transaction_reviews import decide


def old_receivable(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="Synthetic old receivable"), actor="manager")
    scope = {"organization": "Engineering City", "period": "2026-09", "currency": "CNY", "unit": "元"}
    row = {**scope, "transaction_id": "SYN-AR-53", "transaction_type": "old_ar_collection",
           "recognition_date": "2026-09-30", "amount": "53", "opening_receivable": "173",
           "receivable_origin_period": "2026-08", "policy_id": "settle_existing_receivable_v1",
           "policy_reference": "synthetic-existing-receivable-policy", "policy_effective_from": "2026-01-01",
           "policy_effective_to": "2026-12-31", "policy_transaction_type": "old_ar_collection"}
    path = tmp_path / "source.json"
    path.write_text(json.dumps([row]))
    source = service.analysis.add_dataset(path, name="Old receivable")
    context = service.save_context({"bindings": {"source": source["id"]}, "scopes": {"source": scope}})
    requirement = service.analysis_requirements_save({"context_id": context["id"], "question": "Review settlement",
        "items": [{"id": "review", "metric": "transaction_review", "requires_drilldown": False}]})
    inputs = {"scope": scope, "source_bindings": {name: {"alias": "source", "column": name,
        "aggregation": "single", "selector": {"transaction_id": row["transaction_id"]}, "scope": scope,
        "period": scope["period"], "currency": "CNY", "unit": "元"} for name in set(row) - set(scope)},
        "proposed_entries": {"cash_delta": "53", "receivables_delta": "-53", "revenue_delta": "0", "profit_delta": "0"}}
    scenario = service.save_scenario({"context_id": context["id"], "kind": "transaction_review",
                                     "label": "Synthetic settlement", "inputs": inputs})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded" and run["result"]["status"] == "pass"
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    assert not any(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts)
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join("{{fact:" + fact["id"] + "}}" for fact in facts)})
    assert draft["completion"]["status"] == "awaiting_manager"
    return service, source, row, run, draft


def test_transaction_presence_reuses_only_verified_runs_in_the_current_reader_task(tmp_path, monkeypatch):
    service, source, _, run, draft = old_receivable(tmp_path)
    reads = []
    original = service.analysis.get_run
    monkeypatch.setattr(service.analysis, "get_run", lambda key: reads.append(key) or original(key))
    cache = {}
    assert has_transaction(service.analysis, draft, allowed={source["id"]}, cache=cache)
    assert has_transaction(service.analysis, draft, allowed={source["id"]}, cache=cache)
    assert reads == [run["id"]]
    with pytest.raises(FoundryError, match="outside"):
        has_transaction(service.analysis, draft, allowed=set(), cache=cache)
    other = AnalysisStore(TaskStore(tmp_path / "other").create(title="Other task"))
    with pytest.raises(FoundryError, match="task"):
        has_transaction(other, draft, allowed={source["id"]}, cache=cache)
    assert has_transaction(service.analysis, draft, allowed={source["id"]}, cache={})
    assert reads == [run["id"], run["id"]]


@pytest.mark.parametrize("change", ["revocation", "epoch", "source"])
def test_native_review_stays_current_while_immutable_run_reads_share_cache(tmp_path, change):
    service, source, row, run, draft = old_receivable(tmp_path)
    approved = decide(service, draft)
    assert approved["completion"]["status"] == "complete"
    allowed, cache = {source["id"]}, {}
    before = service.analysis._object_path("drafts", draft["id"]).read_bytes()
    assert service.analysis.completion_in_view(approved["completion"], allowed, cache=cache)["status"] == "complete"
    if change == "revocation":
        service.finance_transaction_review_revoke({"review_id": approved["review"]["id"], "reason": "Synthetic withdrawal"})
    elif change == "epoch":
        service.finance_rule_epoch_advance({"rule_id": "accounting.transaction_recognition", "expected_epoch": 0,
                                          "reason": "Synthetic rule review"})
    else:
        replacement = tmp_path / "replacement.json"
        replacement.write_text(json.dumps([{**row, "amount": "54"}]))
        new = service.analysis.add_dataset(replacement, name="Old receivable")
        allowed.add(new["id"])
    assert service.analysis.completion_in_view(approved["completion"], allowed, cache=cache)["status"] != "complete"
    assert service.analysis._object_path("drafts", draft["id"]).read_bytes() == before
    denied = FinanceStore(service.task, snapshot_ids=[], session_id="narrow")
    with pytest.raises(FoundryError):
        denied.finance_transaction_review_prepare({"draft_id": draft["id"]})
    with pytest.raises(FoundryError):
        FinanceStore(TaskStore(tmp_path / "other").create(title="Other"), actor="manager").finance_transaction_review_prepare(
            {"draft_id": draft["id"]})
    assert service.analysis.get_run(run["id"])["result"]["evidence_eligible"] is False


def test_corrupt_native_run_is_historical_only_and_current_receipt_fails_closed(tmp_path):
    service, source, _, run, draft = old_receivable(tmp_path)
    approved = decide(service, draft)
    stored = service.analysis.get_draft(draft["id"])
    path = service.analysis._object_path("runs", run["id"])
    corrupted = json.loads(path.read_text())
    corrupted["output_hash"] = "0" * 64
    path.write_text(json.dumps(corrupted))
    assert service.analysis.draft_in_view(stored, None) is stored
    assert service.analysis.completion_in_view(approved["completion"], None)["status"] != "complete"
    with pytest.raises(FoundryError):
        has_transaction(service.analysis, draft, allowed={source["id"]}, cache={})
    with pytest.raises(FoundryError):
        service.save_explanation_draft({"draft_id": draft["id"]})


def test_reference_city_scope_retains_real_organizations_and_conflicting_scope_still_fails(tmp_path):
    from foundry.sample_reference import COMPANY, MONTH_CLOSE, Reference
    from foundry.sample_task import create_sample_task

    var = tmp_path / "var"
    sample = Reference(TaskStore(var).get(create_sample_task(var)["id"]))
    sample.datasets = {MONTH_CLOSE: sample.datasets[MONTH_CLOSE]}
    sample.confirm_structures()
    run = sample.collection_health()
    assert run["execution_status"] == "succeeded", run.get("error")
    context = sample.manager._read("contexts", run["finance_context_id"])
    assert context["scopes"]["kpi"]["organization"] == COMPANY
    assert "organization" not in context["scopes"]["city"]
    assert all(context["scopes"]["city"][key] == context["scopes"]["kpi"][key]
               for key in ("period", "currency", "unit"))
    scenario = sample.manager._read("scenarios", run["result"]["scenario_id"])
    wrong_context = sample.manager.save_context({"bindings": context["bindings"], "scopes": {
        **context["scopes"], "city": {**context["scopes"]["city"], "organization": COMPANY}}})
    wrong = sample.manager.save_scenario({"context_id": wrong_context["id"], "kind": scenario["kind"],
        "label": "Explicitly inconsistent organization", "inputs": scenario["inputs"]})
    refused = sample.manager.run_scenario({"scenario_id": wrong["id"]})
    assert refused["execution_status"] == "failed"
    assert "source organization" in refused["error"] and "conflicts" in refused["error"]
