"""Explicit native output identities keep their grain contract, not account routing."""
from copy import deepcopy

import pytest

from foundry.analysis import _hash
from foundry.errors import FoundryError
from foundry.finance_driver_templates import OUTPUT_SEMANTICS, TEMPLATE_ID
from foundry.finance_requirements import _result_set_kind, check_requirements
from test_finance_runtime_ordering import setup_case, task_bytes
from test_finance_requirements import _run


PERIOD = "2026-11"


def items(scenario_id, *, pin=True):
    return [{"id": metric, "metric": metric, "periods": [PERIOD], "requires_drilldown": False,
             "dimensions": {"template_id": TEMPLATE_ID, "scenario_id": scenario_id,
                            **({"metric_key": metric} if pin else {})}}
            for metric in OUTPUT_SEMANTICS]


def native_case(tmp_path, *, pin=True):
    manager, service, context, scenario = setup_case(tmp_path, scenario_name="management-forecast")
    request = {"context_id": context["id"], "question": "Read the exact registered monthly statement outputs",
               "scope": {**scenario["inputs"]["scope"], "period": PERIOD},
               "items": items(scenario["id"], pin=pin)}
    requirement = service.analysis_requirements_save(request)
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    return manager, service, context, scenario, request, requirement, run


def claims(run):
    return [{"basis": "calculation", "run_id": run["id"], "row": index, "column": "value", "value": row["value"]}
            for index, row in enumerate(run["result"]["rows"]) if row.get("metric_key") in OUTPUT_SEMANTICS]


@pytest.mark.parametrize("metric", OUTPUT_SEMANTICS)
def test_registered_output_is_not_inferred_to_be_a_ledger_account(metric):
    item = next(item for item in items("declared-scenario") if item["metric"] == metric)
    before = deepcopy(item)
    assert _result_set_kind(item) is None
    assert item == before


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("pin", [False, True])
def test_singleton_same_month_closes_real_source_bound_requirements_and_save(tmp_path, short, pin):
    _, service, _, _, request, requirement, run = native_case(tmp_path, pin=pin)
    stored_before = service.analysis._get("requirements", requirement["id"])
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    assert prepared["draft_template"] is not None
    saved = service.save_explanation_draft(prepared["save_template_spec"] if short else prepared["draft_template"])
    checked = saved["quality"]["requirements"]
    assert checked["coverage"]["status"] == "pass", checked["items"]
    assert len(checked["items"]) == 13 and all(item["status"] == "answered" for item in checked["items"])
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert saved["completion"]["status"] == "complete"
    assert service.validate_explanation({"draft_id": saved["id"]})["status"] == "pass"
    assert service.analysis._get("requirements", requirement["id"]) == stored_before
    assert all(item["periods"] == [PERIOD] for item in checked["items"])
    assert stored_before["scope"] == request["scope"]
    for row in run["result"]["rows"]:
        if row.get("metric_key") in OUTPUT_SEMANTICS:
            assert row["period"] == PERIOD
            assert row["value_kind"] == OUTPUT_SEMANTICS[row["metric_key"]][2]


@pytest.mark.parametrize("periods", [["2026-10"], ["2026-10", PERIOD], ["2026-11-30"], ["2026-01:2026-11"]])
def test_conflicting_global_month_is_rejected_before_any_requirement_write(tmp_path, periods):
    _, service, _, _, request, requirement, _ = native_case(tmp_path)
    changed = {**deepcopy(request), "parent_id": requirement["id"]}
    for item in changed["items"]:
        item["periods"] = periods
    before = task_bytes(service)
    with pytest.raises(FoundryError, match="periods conflict with scope.period"):
        service.analysis_requirements_save(changed)
    assert task_bytes(service) == before


@pytest.mark.parametrize("field,values", [
    ("periods", ["2026-10"]), ("periods", ["2026-10", PERIOD]),
    ("periods", ["2026-11-30"]), ("periods", ["2026-01:2026-11"]),
    ("organizations", ["Other Co"]), ("organizations", ["Ordering Engineering Co", "Other Co"]),
    ("scenarios", ["other-forecast"]), ("scenarios", ["management-forecast", "other-forecast"]),
])
def test_native_route_still_requires_every_exact_period_organization_and_scenario(tmp_path, field, values):
    manager, service, context, scenario, request, requirement, _ = native_case(tmp_path)
    changed = {**deepcopy(request), "parent_id": requirement["id"], "scope": {"currency": "CNY", "unit": "元"}}
    for item in changed["items"]:
        item[field] = values
    current = service.analysis_requirements_save(changed)
    # The trusted manager may inspect arithmetic for a request the runtime cannot fulfill.
    run = manager.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    checked = check_requirements(service.analysis, {"requirements_id": current["id"], "run_ids": [run["id"]], "claims": claims(run)})
    assert checked["coverage"]["status"] == "needs_attention"
    assert all(item["status"] == "pending" for item in checked["items"])
    assert all(item[field] == values for item in checked["items"])
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    facts = [fact for fact in prepared["facts"] if fact.get("column") == "value"
             and fact.get("semantics", {}).get("metric") in OUTPUT_SEMANTICS]
    assert len(facts) == 13 and all(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts)
    draft = service.save_explanation_draft({"requirements_id": current["id"], "run_ids": [run["id"]],
        "body": "\n".join("{{fact:%s}}" % fact["id"] for fact in facts)})
    assert draft["completion"]["status"] != "complete"
    assert service.analysis._get("requirements", current["id"])["items"] == current["items"]


@pytest.mark.parametrize("mutation", ["fake_template", "wrong_scenario", "wrong_metric", "stock_as_flow", "flow_as_stock"])
def test_same_month_does_not_erase_explicit_template_scenario_metric_or_stock_flow_identity(tmp_path, mutation):
    manager, service, _, scenario, request, requirement, _ = native_case(tmp_path)
    changed = {**deepcopy(request), "parent_id": requirement["id"]}
    target = next(item for item in changed["items"] if item["metric"] == ("net_income" if mutation == "flow_as_stock" else "closing_cash"))
    if mutation == "fake_template":
        target["dimensions"]["template_id"] = "unregistered_statement_template"
    elif mutation == "wrong_scenario":
        target["dimensions"]["scenario_id"] = "different-scenario"
    elif mutation == "wrong_metric":
        target["metric"] = target["dimensions"]["metric_key"] = "not_a_registered_output"
    else:
        target["dimensions"]["value_kind"] = "stock" if mutation == "flow_as_stock" else "flow"
    current = service.analysis_requirements_save(changed)
    run = manager.run_scenario({"scenario_id": scenario["id"]})
    checked = check_requirements(service.analysis, {"requirements_id": current["id"], "run_ids": [run["id"]], "claims": claims(run)})
    item = next(item for item in checked["items"] if item["id"] == target["id"])
    assert item["status"] != "answered"
    assert checked["coverage"]["status"] == "needs_attention"


def test_sql_copy_of_native_cells_cannot_gain_native_evidence_qualification(tmp_path):
    _, service, _, _, _, requirement, native = native_case(tmp_path)
    result = deepcopy(native["result"])
    for row in result["rows"]:
        row["scenario_id"] = result["scenario_id"]
    sql = _run(service.analysis, engine="sql", result=result, output_hash=_hash(result),
               bindings=native["bindings"], finance_scope=native["finance_scope"],
               input_hashes=native["input_hashes"], source_hashes=native["source_hashes"],
               finance_context_id=native["finance_context_id"],
               requirements_rule_identity=native.get("requirements_rule_identity"))
    assert sql["output_hash"] == _hash(sql["result"])
    checked = check_requirements(service.analysis, {"requirements_id": requirement["id"], "run_ids": [sql["id"]], "claims": claims(sql)})
    assert checked["coverage"]["status"] == "needs_attention"
    assert all(item["status"] != "answered" for item in checked["items"])
    reasons = [location.get("evidence", {}).get("not_counted_reason") for item in checked["items"] for location in item["locations"]]
    assert reasons == ["template_evidence_not_qualified"] * 13


@pytest.mark.parametrize("dimensions", [
    {}, {"template_id": "fake", "scenario_id": "scenario"},
    {"template_id": TEMPLATE_ID}, {"template_id": TEMPLATE_ID, "scenario_id": ""},
    {"template_id": TEMPLATE_ID, "scenario_id": "scenario", "metric_key": "net_income"},
])
def test_unregistered_or_conflicting_declarations_keep_account_result_set_routing(dimensions):
    assert _result_set_kind({"metric": "closing_cash", "periods": [PERIOD], "dimensions": dimensions}) == "account_total"


def test_real_account_and_control_total_routing_remain_separate():
    assert _result_set_kind({"metric": "cash", "periods": [PERIOD]}) == "account_total"
    assert _result_set_kind({"metric": "control_totals", "periods": [PERIOD],
                             "dimensions": {"template_id": TEMPLATE_ID, "scenario_id": "scenario"}}) == "control_totals"
