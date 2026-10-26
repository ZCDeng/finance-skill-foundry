"""Frozen professional identity and amount-evidence boundaries."""
import pytest
import json

from foundry.analysis import AnalysisStore
from foundry.finance_explanations import prepare_explanation
from foundry.finance_requirements import check_requirements, save_requirements
from foundry.task import TaskStore
from test_finance_requirements import _run, _claim, spec
from foundry.finance_service import FinanceStore
from foundry.errors import FoundryError
from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS, TEMPLATE_METRICS, rule_identity, profile_route


@pytest.mark.parametrize("metric", ["closing_cash", "open_amount", "closing_debt"])
def test_empty_engine_amount_sources_never_answer_cash_ar_debt(tmp_path, metric):
    analysis = AnalysisStore(TaskStore(tmp_path / "var").create(title="来源门禁"))
    save_requirements(analysis, spec(items=[{"id": "amount", "metric": metric}]))
    run = _run(analysis, result={"columns": ["metric_key", "value"], "rows": [
        {"metric_key": metric, "value": "12", "source_rows": []}]})
    result = check_requirements(analysis, {"run_ids": [run["id"]], "claims": [
        _claim(run, row=0, column="value", value="12")]})
    assert result["items"][0]["status"] != "answered"
    fact = prepare_explanation(analysis, [run])["facts"][0]
    assert fact["source_trace"]["provenance_status"] == "unverified"
    assert fact["evidence_eligibility"]["counts_as_amount_evidence"] is False


def _profile_case(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="专业口径")
    service = FinanceStore(task, actor="manager")
    path = tmp_path / "inputs.json"
    path.write_text('[{"amount":"10"}]')
    dataset = service.analysis.add_dataset(path, name="数据")
    profile = {"schema_version": 1, "basis": "management", "basis_version": "management-v1", "purpose": "forecast",
               "fiscal_year_start": "2026-01-01", "early_adoption": False,
               "effective_period": {"start": "2026-01", "end": "2026-12"},
               "functional_currency": "CNY", "presentation_currency": "CNY", "presentation_unit": "元",
               "entity_scope": "O1", "policies": {}}
    context = service.save_context({"bindings": {"actual": dataset["id"]},
                                    "scopes": {"actual": {"organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}},
                                    "reporting_profile": profile})
    return service, context


def test_partial_confirmation_does_not_approve_whole_profile_and_actor_is_trusted(tmp_path):
    service, context = _profile_case(tmp_path)
    assert context["reporting_profile"]["basis"] == "management"
    assistant = FinanceStore(service.task)
    with pytest.raises(FoundryError, match="manager"):
        assistant.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS), "actor": "manager"})
    service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": ["functional_currency"]})
    assert rule_identity(service, context, ["driver.source_binding"])["professional_status"] == "awaiting_profile_confirmation"
    confirmed = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    identity = rule_identity(service, context, ["driver.source_binding"])
    assert identity["professional_status"] == "supported"
    service.finance_profile_revoke({"id": confirmed["id"], "reason": "期间需重核"})
    assert rule_identity(service, context, ["driver.source_binding"])["professional_status"] == "awaiting_profile_confirmation"


def test_profile_same_scope_inherits_but_changed_month_requires_confirmation(tmp_path):
    service, context = _profile_case(tmp_path)
    service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    same = service.save_context({"parent_id": context["id"], "bindings": context["bindings"], "scopes": context["scopes"]})
    assert same["reporting_profile"] == context["reporting_profile"]
    assert rule_identity(service, same, ["driver.source_binding"])["professional_status"] == "supported"
    later = service.save_context({"parent_id": context["id"], "bindings": context["bindings"],
                                  "scopes": {"actual": {**context["scopes"]["actual"], "period": "2026-10"}}})
    assert rule_identity(service, later, ["driver.source_binding"])["professional_status"] == "awaiting_profile_confirmation"
    assert rule_identity(service, same, [])["rule_fingerprint"] == rule_identity(service, later, [])["rule_fingerprint"]


@pytest.mark.parametrize("annual,early,version,expected", [
    ("2026-01-01", False, "IAS1", "IAS1"), ("2026-01-01", True, "IFRS18", "IFRS18"),
    ("2026-04-01", False, "IAS1", "IAS1"), ("2027-01-01", False, "IFRS18", "IFRS18"),
])
def test_ifrs_route_uses_annual_start_and_confirmed_adoption(annual, early, version, expected):
    profile = {"basis": "IFRS", "basis_version": version, "purpose": "management", "early_adoption": early,
               "fiscal_year_start": annual}
    assert profile_route(profile, confirmed_fields=["early_adoption"]) == {"status": "supported", "standard": expected}
    assert profile_route({**profile, "purpose": "statutory"}, confirmed_fields=["early_adoption"])["status"] == "unsupported_professional_route"
    if annual < "2027-01-01":
        assert profile_route(profile)["status"] == "awaiting_profile_confirmation"
        assert profile_route({**profile, "early_adoption": "unknown"}, confirmed_fields=["early_adoption"])["status"] == "awaiting_profile_confirmation"


def test_native_vmp_source_facts_requirements_and_completion(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="E01 三因素"))
    rows = [{"product": p, "scenario": scenario, "quantity": q, "price": price, "quantity_unit": "件",
             "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}
            for p, scenario, q, price in [("A", "budget", "50", "10"), ("B", "budget", "50", "20"),
                                           ("A", "actual", "72", "12"), ("B", "actual", "48", "18")]]
    path = tmp_path / "basket.json"
    path.write_text(json.dumps(rows))
    dataset = service.analysis.add_dataset(path, name="篮子")
    context = service.save_context({"bindings": {"basket": dataset["id"]}, "scopes": {"basket": {
        "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}}})
    requirement = service.analysis_requirements_save({"context_id": context["id"], "question": "量结构价差异",
        "items": [{"id": "vmp", "metric": "price_quantity", "dimensions": {"method": "volume_mix_price"}}]})
    run = service.explain_variance({"context_id": context["id"], "kind": "price_quantity", "method": "volume_mix_price",
                                    "actual_scenario": "actual", "baseline_scenario": "budget"})
    assert run["execution_status"] == "succeeded", run.get("error")
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    columns = ("total_variance", "volume_contribution", "mix_contribution", "price_contribution")
    assert [run["result"]["rows"][0][key] for key in columns] == ["228", "300", "-120", "48"]
    facts = [fact for fact in prepared["facts"] if fact["column"] in columns]
    assert len(facts) == 4 and all(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts)
    facts += [fact for fact in prepared["facts"] if fact["column"] == "residual"]
    claims = [{"basis": "calculation", "run_id": run["id"], "row": 0, "column": fact["column"],
               "value": fact["value"], "fact_id": fact["id"]} for fact in facts]
    checked = check_requirements(service.analysis, {"requirements_id": requirement["id"], "run_ids": [run["id"]], "claims": claims})
    assert checked["coverage"]["status"] == "pass", checked
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join(f"{fact['column']}: {{{{fact:{fact['id']}}}}}" for fact in facts), "claims": claims})
    assert draft["completion"]["status"] == "complete", draft["completion"]


def _template_case(tmp_path, *, confirm=True, direct=False, shortfall=False, approve_boundaries=True):
    from test_finance_three_statement import template_parts
    service, seed = _profile_case(tmp_path)
    scenario, context, datasets = template_parts()
    for alias, dataset in datasets.items():
        if shortfall and alias == "template_inputs":
            next(row for row in dataset["rows"] if row["input_name"] == "capex")["amount"] = "140"
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps(dataset["rows"]))
        context["bindings"][alias] = service.analysis.add_dataset(path, name=alias)["id"]
    context["reporting_profile"] = {**seed["reporting_profile"], "entity_scope": "Synthetic Fixture Co"}
    context = service.save_context(context)
    if confirm:
        service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    if direct:
        from test_finance_three_statement import BASE_VALUES
        scenario["inputs"]["values"] = BASE_VALUES
        scenario["inputs"]["source_bindings"] = {k: v for k, v in scenario["inputs"]["source_bindings"].items() if k.startswith("boundary.")}
    saved = service.save_scenario({"context_id": context["id"], "kind": "driver_model", "label": "来源三表", "inputs": scenario["inputs"]})
    if approve_boundaries:
        from foundry.finance_driver_templates import BOUNDARY_INPUTS
        service.finance_profile_confirm({"context_id": context["id"], "scenario_id": saved["id"],
                                         "confirmed_model_boundaries": list(BOUNDARY_INPUTS)})
    requirement = service.analysis_requirements_save({"context_id": context["id"], "question": "管理预测三表",
        "items": [{"id": key, "metric": key, "dimensions": {"template_id": scenario["inputs"]["template_id"], "scenario_id": saved["id"]},
                   "requires_drilldown": False} for key in sorted(TEMPLATE_METRICS)]})
    run = service.run_scenario({"scenario_id": saved["id"]})
    assert run["execution_status"] == "succeeded", run.get("error")
    return service, context, requirement, run


@pytest.mark.parametrize("shortfall", [False, True])
def test_registered_three_statements_source_to_completion(tmp_path, capsys, shortfall):
    service, context, requirement, run = _template_case(tmp_path, shortfall=shortfall)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    metrics = {item["metric"] for item in requirement["items"]}
    facts = [fact for fact in prepared["facts"] if fact["column"] == "value"
             and run["result"]["rows"][fact["row"]].get("metric_key") in metrics]
    assert len(facts) == 13
    assert all(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts), facts
    claims = [{"basis": "calculation", "run_id": run["id"], "row": fact["row"], "column": "value",
               "value": fact["value"], "fact_id": fact["id"]} for fact in facts]
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "管理预测\n" + "\n".join(f"{{{{fact:{fact['id']}}}}}" for fact in facts), "claims": claims})
    assert draft["completion"]["status"] == "complete", draft
    confirmation = service._list("profile_confirmations")[-1]
    service.finance_profile_revoke({"id": confirmation["id"], "reason": "口径待修订"})
    assert service.analysis.completion_in_view(draft["completion"], None)["status"] == "awaiting_manager"
    from foundry.cli import main
    assert main(["--var", str(tmp_path / "var"), "--task", service.task.id, "analysis-state"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert next(item for item in state["completions"] if item["id"] == draft["completion"]["id"])["status"] == "awaiting_manager"
    assert next(item for item in state["drafts"] if item["id"] == draft["id"])["quality"]["status"] == "needs_attention"
    # Immutable history keeps the original decision; public views re-evaluate its current authority.
    assert next(item for item in service.analysis.state()["completions"] if item["id"] == draft["completion"]["id"])["status"] == "complete"
    assert service.analysis.draft_in_view(service.analysis.get_draft(draft["id"]), None)["professional_reason"] == "awaiting_model_boundary_confirmation"
    close = service.finance_close_status({})
    assert "文稿的专业口径或模型边界批准已变化，请复核并重新计算" in close["blocking"]
    checked = check_requirements(service.analysis, {"requirements_id": requirement["id"], "run_ids": [run["id"]], "claims": claims})
    assert checked["coverage"]["status"] != "pass"
    assert not any(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in
                   service.prepare_explanation({"run_ids": [run["id"]]})["facts"])


@pytest.mark.parametrize("confirm,direct,boundaries", [(False, False, True), (True, True, True), (True, False, False)])
def test_balanced_unconfirmed_or_direct_template_is_readable_but_not_evidence(tmp_path, confirm, direct, boundaries):
    service, context, requirement, run = _template_case(tmp_path, confirm=confirm, direct=direct, approve_boundaries=boundaries)
    assert any(row.get("metric_key") == "closing_cash" and row["value"] == "90" for row in run["result"]["rows"])
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    assert not any(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts)


def test_related_control_rule_change_invalidates_only_its_lineage(tmp_path, monkeypatch):
    from test_finance_formula_controls import _task, _pack, _side
    from foundry.finance_professional import RULES
    from foundry.finance_controls import control_key, applies_to
    from foundry.finance_close_status import _controls_block
    analysis, assistant, manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="月结")
    formula = {"kind": "formula", "formula": "dso", "label": "DSO", "unit": "天", "tolerance": "1",
        "inputs": {"ar_end": _side(pack, "05·资产负债表", "B2"), "contract_assets_end": _side(pack, "05·资产负债表", "B3"),
                   "revenue_py_full": _side(pack, "01·看板", "D2"), "revenue_py": _side(pack, "01·看板", "C2"), "revenue": _side(pack, "01·看板", "B2")},
        "right": _side(pack, "01·看板", "B3")}
    plain = {"kind": "tie_out", "label": "纯算术", "left": _side(pack, "01·看板", "B2"), "right": _side(pack, "01·看板", "B2"), "tolerance": "0"}
    saved = manager.finance_controls_save({"controls": [formula, plain], "confirm": True})["controls"]
    manager.finance_controls_run({})
    decision = manager.finance_control_disposition_save({"control_id": saved[0]["id"], "decision": "waived", "reason": "已核验", "decided_by_name": "经理"})
    monkeypatch.setitem(RULES, "cash.collection_screen", (2, frozenset()))
    listing = manager.finance_controls_list({})["controls"]
    assert listing[0]["issue"]["blocking"]
    assert listing[1]["result"]["status"] == "pass" and not listing[1]["issue"]
    assert _controls_block(listing)["state"] == "blocked"
    assistant.finance_controls_run({})
    heads = manager.finance_controls_list({})["controls"]
    successor = next(row for row in heads if row["control"].get("formula") == "dso")
    assert successor["state"] == "proposed" and successor["parent_id"] == saved[0]["id"]
    assert control_key(successor["control"]) == control_key(saved[0]["control"])
    assert not applies_to(decision, successor["result"])
    confirmed = manager.finance_controls_confirm({"id": successor["id"]})
    manager.finance_controls_run({"ids": [confirmed["id"]]})
    assert manager.finance_controls_list({})["summary"]["blocking"] == 1  # the fresh difference is undecided


def test_profile_and_boundary_status_respect_snapshot_ceiling(tmp_path):
    service, context, requirement, run = _template_case(tmp_path)
    from foundry.finance_professional import requirement_rule_identity
    visible = set(context["bindings"].values())
    full = FinanceStore(service.task, snapshot_ids=visible)
    scenario_id = run["result"]["scenario_id"]
    status = full.finance_profile_status({"context_id": context["id"], "scenario_id": scenario_id})
    assert status["professional_status"] == "supported"
    assert set(status["model_boundary_preview"]["source_hashes"]) == set(context["bindings"])
    hidden = visible - {context["bindings"]["model_boundary"]}
    restricted = FinanceStore(service.task, snapshot_ids=hidden)
    assert context["id"] not in {item["id"] for item in restricted.list_finance_context()["contexts"]}
    with pytest.raises(FoundryError):
        restricted.finance_profile_status({"context_id": context["id"], "scenario_id": scenario_id})
    with pytest.raises(FoundryError):
        restricted.prepare_explanation({"run_ids": [run["id"]]})
    assert requirement_rule_identity(service.analysis, requirement, allowed=hidden)["professional_status"] == "professional_context_unavailable"


def test_restricted_control_read_ignores_unrelated_hidden_context_for_arithmetic(tmp_path):
    from test_finance_formula_controls import _task, _pack, _side
    analysis, assistant, manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="可见月结")
    hidden_path = tmp_path / "hidden.json"
    hidden_path.write_text('[{"amount":"20"}]')
    hidden = analysis.add_dataset(hidden_path, name="隐藏来源")
    context = manager.save_context({"bindings": {"visible": pack["id"], "hidden": hidden["id"]}})
    control = {"kind": "tie_out", "label": "纯算术", "left": _side(pack, "01·看板", "B2"),
               "right": _side(pack, "01·看板", "B2"), "tolerance": "0"}
    manager.finance_controls_save({"control": control, "context_id": context["id"], "confirm": True})
    manager.finance_controls_run({})
    restricted = FinanceStore(manager.task, snapshot_ids=[pack["id"]])
    listing = restricted.finance_controls_list({})
    assert listing["controls"][0]["result"]["status"] == "pass"
    assert not listing["controls"][0]["issue"]
    dependent = restricted._control_rule_identity({"kind": "formula", "formula": "dso"}, context["id"])
    assert dependent["professional_status"] == "professional_context_unavailable"
    assert dependent["rule_fingerprint"] is None


@pytest.mark.parametrize("kind", ["profile", "boundary"])
def test_revoking_latest_approval_never_revives_an_older_approval(tmp_path, kind):
    service, context, requirement, run = _template_case(tmp_path)
    from foundry.finance_driver_templates import BOUNDARY_INPUTS
    confirmation = service.finance_profile_confirm({"context_id": context["id"], **(
        {"scenario_id": run["result"]["scenario_id"], "confirmed_model_boundaries": list(BOUNDARY_INPUTS)}
        if kind == "boundary" else {"confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})})
    service.finance_profile_revoke({"id": confirmation["id"], "reason": "撤销最新批准"})
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    assert not any(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts)
    assert service.finance_profile_status({"context_id": context["id"], "scenario_id": run["result"]["scenario_id"]})["professional_status"] != "supported"


def test_pinned_profile_reference_cannot_bypass_a_newer_revocation(tmp_path):
    service, context = _profile_case(tmp_path)
    old = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    pinned = service.save_context({"parent_id": context["id"], "bindings": context["bindings"],
                                  "scopes": context["scopes"], "profile_confirmation_id": old["id"]})
    assert rule_identity(service, pinned, ["driver.source_binding"])["professional_status"] == "supported"
    latest = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    service.finance_profile_revoke({"id": latest["id"], "reason": "停止使用该口径"})
    assert rule_identity(service, pinned, ["driver.source_binding"])["professional_status"] == "awaiting_profile_confirmation"
