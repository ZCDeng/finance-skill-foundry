"""A fixed management template has explicit, bounded approval, never standard approval."""
from copy import deepcopy
import json

import pytest

from foundry.errors import FoundryError
from foundry.finance_driver_templates import BOUNDARY_INPUTS, TEMPLATE_ID
from foundry.finance_professional import BASE_FIELDS, RULES, STANDARD_FIELDS, artifact_rules_match, rule_identity
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from test_finance_runtime_ordering import register

PAIR = ["driver.source_binding", "statements.linked_management"]


def case(tmp_path, *, fields=BASE_FIELDS, boundary=True, profile_changes=None):
    manager = FinanceStore(TaskStore(tmp_path / "var").create(title="Limited management approval"), actor="manager")
    scope = {"organization": "Approval Engineering Co", "currency": "CNY", "unit": "元"}
    values = dict(opening_cash=160, opening_receivables=80, opening_ppe=300, opening_payables=60,
                  opening_debt=120, opening_equity=360, revenue=210, customer_receipts=190,
                  operating_expense=95, supplier_payments=90, depreciation=15, capex=35,
                  debt_drawdowns=10, debt_principal_repayments=25, dividends_paid=5, closing_restricted_cash=12)
    values.update(dict.fromkeys(BOUNDARY_INPUTS, 0))
    rows = [{**scope, "input_name": key, "amount": str(value),
             "period": "2026-10" if key.startswith("opening_") else "2026-11"} for key, value in values.items()]
    source = tmp_path / "inputs.json"
    source.write_text(json.dumps(rows))
    dataset = manager.analysis.add_dataset(source, name="Independent engineering inputs")
    profile = {"basis": "management", "basis_version": "management-v1", "purpose": "forecast",
               "fiscal_year_start": "2026-01-01", "early_adoption": False,
               "effective_period": {"start": "2026-11", "end": "2026-11"},
               "functional_currency": "CNY", "presentation_currency": "CNY", "presentation_unit": "元",
               "entity_scope": scope["organization"], **(profile_changes or {})}
    context = manager.save_context({"bindings": {"inputs": dataset["id"]}, "scopes": {"inputs": scope},
                                    "reporting_profile": profile})
    approval = manager.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(fields)}) if fields else None
    inputs = {"template_id": TEMPLATE_ID, "period": "2026-11", "scope": scope,
              "source_bindings": {row["input_name"]: {"alias": "inputs", "column": "amount",
                    "selector": {"input_name": row["input_name"]}, "aggregation": "single", "scope": scope,
                    "period": row["period"], "currency": "CNY", "unit": "元"} for row in rows}}
    scenario = manager.save_scenario({"context_id": context["id"], "kind": "driver_model", "label": "Management",
                                      "inputs": inputs})
    approved_boundary = confirm_boundary(manager, context, scenario) if boundary else None
    return manager, context, scenario, approval, approved_boundary


def confirm_boundary(manager, context, scenario):
    return manager.finance_profile_confirm({"context_id": context["id"], "scenario_id": scenario["id"],
                                            "confirmed_model_boundaries": list(BOUNDARY_INPUTS)})


def identity(manager, context, scenario, **kwargs):
    return rule_identity(manager, context, PAIR, scenario_ids=[scenario["id"]], **kwargs)


def test_new_explicit_boundary_and_seven_fields_qualify_only_fixed_template(tmp_path):
    manager, context, scenario, approval, boundary = case(tmp_path)
    current = identity(manager, context, scenario)
    assert current["professional_status"] == "supported"
    assert current["professional_route"] == {"status": "supported", "standard": None, "scope": "registered_management_template"}
    assert set(current["required_profile_fields"]) == BASE_FIELDS
    assert current["rule_basis"]["confirmation_id"] == approval["id"]
    assert boundary["confirmed_fields"] == [] and boundary["field_values"] == {}
    assert "management_template_scope" in boundary
    assert not (set(current["rule_basis"]["fields"]) & STANDARD_FIELDS)
    assert manager.finance_profile_status({"context_id": context["id"]})["professional_status"] == "awaiting_profile_confirmation"
    scoped = manager.finance_profile_status({"context_id": context["id"], "scenario_id": scenario["id"]})
    assert scoped["profile_gap"]["missing_fields"] == []
    requirements = register(manager, context, scenario)
    run = manager.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    assert run["professional_identity"] == current
    assert run["requirements_semantic_fingerprint"] == requirements["semantic_fingerprint"]


@pytest.mark.parametrize("missing", [None, *sorted(BASE_FIELDS)])
def test_boundary_cannot_replace_any_required_field_approval(tmp_path, missing):
    fields = set() if missing is None else BASE_FIELDS - {missing}
    manager, context, scenario, _, _ = case(tmp_path, fields=fields)
    assert identity(manager, context, scenario)["professional_status"] == "awaiting_profile_confirmation"


def test_seven_fields_cannot_replace_boundary_approval(tmp_path):
    manager, context, scenario, _, _ = case(tmp_path, boundary=False)
    assert identity(manager, context, scenario)["professional_status"] != "supported"


@pytest.mark.parametrize("which", ["profile", "boundary", "full_profile"])
def test_revocation_never_falls_back_to_older_narrow_approval(tmp_path, which):
    manager, context, scenario, approval, boundary = case(tmp_path)
    assert identity(manager, context, scenario)["professional_status"] == "supported"
    if which == "full_profile":
        approval = manager.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    manager.finance_profile_revoke({"id": boundary["id"] if which == "boundary" else approval["id"], "reason": "Engineering revocation"})
    assert identity(manager, context, scenario)["professional_status"] != "supported"


@pytest.mark.parametrize("changes", [
    {"basis": "CAS"}, {"basis": "IFRS", "basis_version": "IAS1"}, {"purpose": "statutory"},
    {"basis_version": "management-v2"}, {"policies": {"depreciation_start": "following_month"}},
])
def test_standard_and_policy_routes_keep_eleven_field_gate(tmp_path, changes):
    manager, context, scenario, _, _ = case(tmp_path, profile_changes=changes)
    current = identity(manager, context, scenario)
    assert current["professional_status"] == "awaiting_profile_confirmation"
    assert set(current["required_profile_fields"]) == BASE_FIELDS | STANDARD_FIELDS


@pytest.mark.parametrize("key,value", [("basis", "CAS"), ("basis_version", "management-v2"),
    ("fiscal_year_start", "2027-01-01"), ("early_adoption", True), ("entity_scope", "Other Co")])
def test_marker_binds_entire_profile_even_unrouted_fields(tmp_path, key, value):
    manager, context, scenario, _, _ = case(tmp_path)
    assert identity(manager, context, scenario)["professional_status"] == "supported"
    changed = {**context, "reporting_profile": {**context["reporting_profile"], key: value}}
    assert identity(manager, changed, scenario)["professional_status"] != "supported"


def test_historical_boundary_and_failed_run_never_gain_new_qualification(tmp_path, monkeypatch):
    from foundry.finance_professional import requirement_rule_identity
    manager, context, scenario, _, _ = case(tmp_path, boundary=False)
    original_write = manager._write

    def legacy_write(kind, **values):
        values.pop("management_template_scope", None)
        return original_write(kind, **values)

    with monkeypatch.context() as patch:
        patch.setattr(manager, "_write", legacy_write)
        old_boundary = confirm_boundary(manager, context, scenario)
    requirement = register(manager, context, scenario)
    old_run = manager.run_scenario({"scenario_id": scenario["id"]})
    paths = [manager._path("profile_confirmations", old_boundary["id"]),
             manager.analysis._object_path("requirements", requirement["id"]), manager.analysis._object_path("runs", old_run["id"])]
    before = [path.read_bytes() for path in paths]
    assert old_run["professional_identity"]["professional_status"] == "awaiting_profile_confirmation"
    old_identity = identity(manager, context, scenario)
    new_boundary = confirm_boundary(manager, context, scenario)
    assert identity(manager, context, scenario)["professional_status"] == "supported"
    assert identity(manager, context, scenario, max_seq=new_boundary["seq"]) == old_identity
    assert requirement_rule_identity(manager.analysis, requirement, historical=True) == requirement["semantic_basis"]["professional_identity"]
    assert not artifact_rules_match(old_run, identity(manager, context, scenario))
    runtime = FinanceStore(manager.task, session_id="limited-management-runtime")
    with pytest.raises(FoundryError, match="analysis_requirements_save"):
        runtime.run_scenario({"scenario_id": scenario["id"]})
    fresh = register(runtime, context, scenario, parent_id=requirement["id"],
                     change_reason="Use the newly approved limited management scope")
    rerun = runtime.run_scenario({"scenario_id": scenario["id"]})
    assert rerun["execution_status"] == "succeeded"
    assert rerun["requirements_id"] == fresh["id"] and rerun["id"] != old_run["id"]
    assert [path.read_bytes() for path in paths] == before


def test_scope_cannot_cross_scenario_context_sources_task_or_multiple_scenarios(tmp_path):
    manager, context, scenario, _, _ = case(tmp_path)
    other = manager.save_scenario({"context_id": context["id"], "kind": "driver_model", "label": "Other", "inputs": scenario["inputs"]})
    assert identity(manager, context, other)["professional_status"] != "supported"
    assert rule_identity(manager, context, PAIR, scenario_ids=[scenario["id"], other["id"]])["professional_status"] != "supported"
    child = manager.save_context({"bindings": context["bindings"], "scopes": context["scopes"], "reporting_profile": context["reporting_profile"]})
    assert identity(manager, child, scenario)["professional_status"] != "supported"
    changed = deepcopy(context)
    changed["source_hashes"]["inputs"] = "f" * 64
    assert identity(manager, changed, scenario)["professional_status"] != "supported"
    foreign = FinanceStore(TaskStore(tmp_path / "foreign").create(title="Other task"), actor="manager")
    assert identity(foreign, context, scenario)["professional_status"] != "supported"


@pytest.mark.parametrize("change", ["version", "epoch"])
def test_rule_review_invalidates_existing_narrow_run_and_requirements(tmp_path, monkeypatch, change):
    manager, context, scenario, _, _ = case(tmp_path)
    register(manager, context, scenario)
    run = manager.run_scenario({"scenario_id": scenario["id"]})
    before = identity(manager, context, scenario)
    if change == "version":
        version, fields = RULES[PAIR[0]]
        monkeypatch.setitem(RULES, PAIR[0], (version + 1, fields))
    else:
        manager.finance_rule_epoch_advance({"rule_id": PAIR[0], "expected_epoch": 0, "reason": "Engineering rule review"})
    current = identity(manager, context, scenario)
    assert current["rule_fingerprint"] != before["rule_fingerprint"]
    assert not artifact_rules_match(run, current)


def test_runtime_cannot_forge_manager_scope_or_use_an_unauthorized_source(tmp_path):
    manager, context, scenario, _, _ = case(tmp_path, boundary=False)
    runtime = FinanceStore(manager.task, session_id="untrusted-model")
    with pytest.raises(FoundryError, match="only the manager"):
        runtime.finance_profile_confirm({"context_id": context["id"], "scenario_id": scenario["id"],
            "confirmed_model_boundaries": list(BOUNDARY_INPUTS), "actor": "manager", "management_template_scope": {"version": 1}})
    restricted = FinanceStore(manager.task, snapshot_ids=[], session_id="restricted-model")
    assert identity(restricted, context, scenario)["professional_status"] != "supported"


@pytest.mark.parametrize("scope", [None, {"version": 1, "profile_hash": "different"}])
def test_artifact_cannot_substitute_missing_or_different_qualification_scope(tmp_path, scope):
    manager, context, scenario, _, _ = case(tmp_path)
    current = identity(manager, context, scenario)
    captured = deepcopy(current)
    if scope is None:
        captured["rule_basis"].pop("management_template_scope")
    else:
        captured["rule_basis"]["management_template_scope"] = scope
    assert not artifact_rules_match({"engine": "finance", "professional_identity": captured}, current)
    assert artifact_rules_match({"engine": "finance", "professional_identity": current}, current)
