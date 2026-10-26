"""Professional approval covers every input consumed by the standard router."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

from foundry.errors import FoundryError
from foundry.finance_driver_templates import BOUNDARY_INPUTS
from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS, TEMPLATE_METRICS, rule_identity
from test_finance_professional_protocol import _profile_case
from test_finance_runtime_ordering import setup_case


ROUTED_RULES = ("driver.source_binding", "statements.linked_management", "cash.functional_currency_balance")
FULL_FIELDS = sorted(BASE_FIELDS | STANDARD_FIELDS)


def child_context(service, context, **changes):
    return service.save_context({
        "parent_id": context["id"], "bindings": context["bindings"], "scopes": context["scopes"],
        "reporting_profile": {**context["reporting_profile"], **changes},
    })


def approve(service, context):
    return service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": FULL_FIELDS})


@pytest.mark.parametrize("rule", ROUTED_RULES)
@pytest.mark.parametrize("field,value", [
    ("basis", "CAS"), ("basis_version", "management-v2"),
    ("fiscal_year_start", "2027-01-01"), ("early_adoption", True),
])
def test_every_routing_input_requires_exact_confirmation_and_changes_identity(tmp_path, rule, field, value):
    service, context = _profile_case(tmp_path)
    old = approve(service, context)
    baseline = rule_identity(service, context, [rule])
    changed = child_context(service, context, **{field: value})
    identity = rule_identity(service, changed, [rule])
    assert identity["professional_status"] == "awaiting_profile_confirmation"
    assert identity["rule_basis"]["confirmation_id"] is None
    assert identity["rule_basis"]["fields"][field] == value
    assert identity["rule_fingerprint"] != baseline["rule_fingerprint"]
    assert baseline["rule_basis"]["confirmation_id"] == old["id"]
    assert set(identity["required_profile_fields"]) == BASE_FIELDS | STANDARD_FIELDS


@pytest.mark.parametrize("rule", ROUTED_RULES)
def test_base_only_legacy_approval_requires_explicit_reconfirmation_without_rewriting(tmp_path, rule):
    service, context = _profile_case(tmp_path)
    old = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS)})
    path = service._path("profile_confirmations", old["id"])
    before = path.read_bytes()
    assert rule_identity(service, context, [rule])["professional_status"] == "awaiting_profile_confirmation"
    assert service._list("profile_confirmations") == [old]
    fresh = approve(service, context)
    identity = rule_identity(service, context, [rule])
    assert identity["professional_status"] == ("awaiting_model_boundary_confirmation" if rule == "statements.linked_management" else "supported")
    assert identity["rule_basis"]["confirmation_id"] == fresh["id"]
    assert path.read_bytes() == before


def test_cas_approval_cannot_be_pinned_to_ifrs_child(tmp_path):
    service, seed = _profile_case(tmp_path)
    cas = child_context(service, seed, basis="CAS", basis_version="CAS-2026")
    approval = approve(service, cas)
    ifrs = service.save_context({
        "parent_id": cas["id"], "bindings": cas["bindings"], "scopes": cas["scopes"],
        "profile_confirmation_id": approval["id"],
        "reporting_profile": {**cas["reporting_profile"], "basis": "IFRS", "basis_version": "IAS1"},
    })
    status = service.finance_profile_status({"context_id": ifrs["id"]})
    assert status["professional_status"] == "awaiting_profile_confirmation"
    assert status["rule_basis"]["confirmation_id"] is None
    assert service.finance_profile_status({"context_id": cas["id"]})["professional_status"] == "supported"


@pytest.mark.parametrize("changes", [{}, {"policies": {"depreciation_start": "following_month"}}])
@pytest.mark.parametrize("rule", ROUTED_RULES)
def test_unchanged_or_unrelated_policy_child_reuses_exact_approval(tmp_path, rule, changes):
    service, context = _profile_case(tmp_path)
    approve(service, context)
    before = rule_identity(service, context, [rule])
    child = child_context(service, context, **changes)
    assert rule_identity(service, child, [rule]) == before


@pytest.mark.parametrize("rules", [[], ["variance.volume_mix_price"], ["cash.collection_screen"], ["accounting.transaction_recognition"]])
def test_arithmetic_identities_ignore_profile_changes_revocation_and_unrelated_epoch(tmp_path, rules):
    service, context = _profile_case(tmp_path)
    approval = approve(service, context)
    before = rule_identity(service, context, rules)
    changed = child_context(service, context, basis="IFRS", basis_version="IAS1", early_adoption="unknown")
    service.finance_profile_revoke({"id": approval["id"], "reason": "Synthetic profile review"})
    service.finance_rule_epoch_advance({"rule_id": "accounting.depreciation_start", "expected_epoch": 0,
                                      "reason": "Synthetic unrelated policy review"})
    assert rule_identity(service, changed, rules) == before
    assert before["rule_basis"] == {}
    assert before["professional_status"] == "supported"


def test_expanded_partial_and_cross_task_approvals_remain_denied(tmp_path):
    service, context = _profile_case(tmp_path)
    approval = approve(service, context)
    expanded = child_context(service, context, entity_scope="O1 and O2")
    service.finance_profile_confirm({"context_id": expanded["id"], "confirmed_fields": ["entity_scope"]})
    assert service.finance_profile_status({"context_id": expanded["id"]})["professional_status"] == "awaiting_profile_confirmation"
    other, other_context = _profile_case(tmp_path / "other")
    for foreign_id in (approval["id"], "f" * 32):
        with pytest.raises(FoundryError):
            other.save_context({"parent_id": other_context["id"], "bindings": other_context["bindings"],
                                "scopes": other_context["scopes"], "profile_confirmation_id": foreign_id})


def _scenario(service, context, original):
    return service.save_scenario({"context_id": context["id"], "kind": "driver_model",
                                  "label": "Routing dependency engineering case", "inputs": original["inputs"]})


def _requirements(service, context, scenario, previous=None):
    return service.analysis_requirements_save({
        "context_id": context["id"], "question": "Source-bound management statement outputs",
        "scope": {**scenario["inputs"]["scope"], "period": scenario["inputs"]["period"]},
        "items": [{"id": key, "metric": key, "requires_drilldown": False,
                   "dimensions": {"template_id": scenario["inputs"]["template_id"], "scenario_id": scenario["id"]}}
                  for key in sorted(TEMPLATE_METRICS)],
        **({"parent_id": previous["id"], "change_reason": "Explicitly register current profile and boundary approval"} if previous else {}),
    })


def _draft_spec(run, prepared, requirements_id):
    facts = [fact for fact in prepared["facts"] if fact["column"] == "value"
             and run["result"]["rows"][fact["row"]].get("metric_key") in TEMPLATE_METRICS]
    assert len(facts) == len(TEMPLATE_METRICS)
    return {"requirements_id": requirements_id, "run_ids": [run["id"]],
            "body": "\n".join(f"{{{{fact:{fact['id']}}}}}" for fact in facts),
            "claims": [{"basis": "calculation", "run_id": run["id"], "row": fact["row"],
                        "column": "value", "value": fact["value"], "fact_id": fact["id"]} for fact in facts]}


def _run_and_draft(service, scenario):
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded", run.get("error")
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    draft = service.save_explanation_draft(_draft_spec(run, prepared, run["requirements_id"]))
    return run, prepared, draft


def test_cas_to_ifrs_requires_new_profile_and_boundary_approval_then_fresh_completion(tmp_path):
    service, _, seed, seed_scenario = setup_case(tmp_path)
    cas = child_context(service, seed, basis="CAS", basis_version="CAS-2026")
    old_approval = approve(service, cas)
    scenario = _scenario(service, cas, seed_scenario)
    service.finance_profile_confirm({"context_id": cas["id"], "scenario_id": scenario["id"],
                                     "confirmed_model_boundaries": list(BOUNDARY_INPUTS)})
    requirement = _requirements(service, cas, scenario)
    run, prepared, draft = _run_and_draft(service, scenario)
    assert draft["completion"]["status"] == "complete", draft
    # Pin immutable artifacts and archived source bytes; sequence counters and
    # derived fact caches are mutable bookkeeping, not historical evidence.
    folders = ("datasets", "revisions", "runs", "requirements", "drafts", "completions",
               "finance/contexts", "finance/scenarios", "finance/profile_confirmations")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for folder in folders
              for p in (service.analysis.root / folder).rglob("*") if p.is_file()}

    ifrs = child_context(service, cas, basis="IFRS", basis_version="IAS1")
    successor = _scenario(service, ifrs, scenario)
    status = service.finance_profile_status({"context_id": ifrs["id"], "scenario_id": successor["id"]})
    assert status["professional_status"] == "awaiting_profile_confirmation"
    assert status["rule_basis"]["confirmation_id"] is None
    current_requirement = _requirements(service, ifrs, successor, requirement)
    current = service.save_explanation_draft({**_draft_spec(run, prepared, current_requirement["id"]),
                                              "parent_id": draft["id"]})
    assert current["completion"]["status"] != "complete"
    assert current["completion"]["reused_run_ids"] == []
    assert service.validate_explanation({"draft_id": draft["id"]})["status"] == "needs_attention"

    # Verify the public CLI reads the same persisted refusal in a new process.
    cli = subprocess.run([sys.executable, "-B", "-m", "foundry.cli", "--var", str(tmp_path / "var"),
                          "--task", service.task.id, "finance-profile-status", "--spec",
                          json.dumps({"context_id": ifrs["id"]})], text=True, capture_output=True,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["professional_status"] == "awaiting_profile_confirmation"

    fresh_approval = approve(service, ifrs)
    assert fresh_approval["id"] != old_approval["id"]
    status = service.finance_profile_status({"context_id": ifrs["id"], "scenario_id": successor["id"]})
    assert status["professional_route"] == {"status": "supported", "standard": "IAS1"}
    assert status["professional_status"] == "awaiting_model_boundary_confirmation"
    boundary_requirement = _requirements(service, ifrs, successor, current_requirement)
    _, _, blocked = _run_and_draft(service, successor)
    assert blocked["completion"]["status"] != "complete"
    assert service.analysis.completion_in_view(blocked["completion"], None)["professional_reason"] == "awaiting_model_boundary_confirmation"

    service.finance_profile_confirm({"context_id": ifrs["id"], "scenario_id": successor["id"],
                                     "confirmed_model_boundaries": list(BOUNDARY_INPUTS)})
    fresh_requirement = _requirements(service, ifrs, successor, boundary_requirement)
    fresh_run, _, fresh_draft = _run_and_draft(service, successor)
    assert fresh_run["requirements_id"] == fresh_requirement["id"]
    assert fresh_draft["completion"]["status"] == "complete", fresh_draft
    assert fresh_run["professional_identity"]["rule_fingerprint"] != run["professional_identity"]["rule_fingerprint"]
    assert not [str(path) for path, digest in before.items() if hashlib.sha256(path.read_bytes()).hexdigest() != digest]
    assert service.analysis.completion_in_view(draft["completion"], None)["status"] == "complete"
