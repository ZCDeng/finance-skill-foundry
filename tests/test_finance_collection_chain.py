"""Collection identities survive requirements, native calculation and saved receipts."""
import json
from decimal import Decimal

import pytest

from foundry.finance_service import FinanceStore
from foundry.finance_requirements import check_requirements
from foundry.task import TaskStore


KEYS = ("collection_rate_current", "collection_rate_total")
COMPONENTS = {"current_due": "240", "current_collection": "180", "opening_ar": "160", "arrears_collection": "40"}


def collection_chain(tmp_path, *, components=None, source_overrides=None, manual=None, requires_drilldown=True):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="收缴率来源闭环"))
    scope = {"organization": "服务公司", "period": "2026-08", "currency": "CNY", "unit": "元"}
    path = tmp_path / "components.json"
    path.write_text(json.dumps([
        {**scope, "component": name, "amount": value, **(source_overrides or {}).get(name, {})}
        for name, value in (components if components is not None else COMPONENTS).items()
    ], ensure_ascii=False))
    dataset = service.analysis.add_dataset(path, name="收缴构成")
    context = service.save_context({"bindings": {"collections": dataset["id"]}, "scopes": {"collections": scope}})
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "question": "分别核对当年账单与包含期初欠款的收缴情况",
        "items": [{"id": key, "metric": "ratio", "label": key,
                   "dimensions": {"metric_key": key}, "requires_drilldown": requires_drilldown}
                  for key in KEYS],
    })
    scenario = service.save_scenario({"context_id": context["id"], "kind": "collection_health", "label": "收缴构成复算",
        "inputs": {"entities": [{"name": "服务公司", "values": {
            key: ((manual or {})[key] if key in (manual or {}) else
                  {"alias": "collections", "match": {"component": key}, "column": "amount"})
            for key in (components if components is not None else COMPONENTS)
        }}]}})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    return service, requirement, run, dataset


def draft_for(service, requirement, run, *, selected=KEYS):
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    wanted_rows = {index for index, row in enumerate(run["result"]["rows"])
                   if row["metric_key"] in selected and row["scenario"] == "本期"}
    selected_facts = [f for f in facts if f["column"] == "value" and f["row"] in wanted_rows]
    for index in wanted_rows:
        service.drilldown_fact({"run_id": run["id"], "row": index, "column": "value"})
    return service.save_explanation_draft({
        "requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join(f"{run['result']['rows'][f['row']]['metric_label']}：{Decimal(f['value']) * 100:.2f}%" for f in selected_facts),
        "claims": [{"basis": "calculation", "run_id": run["id"], "row": f["row"], "column": "value",
                    "value": f["value"], "fact_id": f["id"],
                    "presentation": {"decimal_places": 2, "scale": "percent", "rounding": "half_up"}}
                   for f in selected_facts],
    })


def test_two_native_rates_have_distinct_cited_identity_and_persistent_completion(tmp_path):
    service, requirement, run, dataset = collection_chain(tmp_path)
    assert requirement["semantic_fingerprint"]
    assert requirement["bindings"] == {"collections": dataset["id"]}
    assert run["execution_status"] == "succeeded", run.get("error")
    assert run["requirements_semantic_fingerprint"] == requirement["semantic_fingerprint"]
    rows = {r["metric_key"]: r for r in run["result"]["rows"]}
    assert {key: rows[key]["value"] for key in KEYS} == {KEYS[0]: "0.75", KEYS[1]: "0.55"}
    assert all(rows[key]["unit"] == "ratio" for key in KEYS)
    assert [len(rows[key]["source_rows"]) for key in KEYS] == [2, 4]
    draft = draft_for(service, requirement, run)
    assert draft["quality"]["status"] == "pass", draft["quality"]
    assert draft["completion"]["status"] == "complete", draft["completion"]
    assert draft["completion"]["requirements_semantic_fingerprint"] == requirement["semantic_fingerprint"]
    assert service.validate_explanation({"draft_id": draft["id"]})["status"] == "pass"
    saved = service.analysis._get("drafts", draft["id"])
    assert saved["content_hash"] == draft["content_hash"]
    assert service.analysis.completion_in_view(draft["completion"], None)["status"] == "complete"


@pytest.mark.parametrize("selected", [(KEYS[0],), (KEYS[1],)])
@pytest.mark.parametrize("equal_rates", [False, True])
def test_one_cited_ratio_cannot_answer_both_registered_identities(tmp_path, selected, equal_rates):
    components = {**COMPONENTS, "opening_ar": "0", "arrears_collection": "0"} if equal_rates else COMPONENTS
    service, requirement, run, _ = collection_chain(tmp_path, components=components)
    assert run["execution_status"] == "succeeded", run.get("error")
    index, row = next((i, r) for i, r in enumerate(run["result"]["rows"]) if r["metric_key"] == selected[0])
    checked = check_requirements(service.analysis, {
        "requirements_id": requirement["id"], "run_ids": [run["id"]],
        "claims": [{"basis": "calculation", "run_id": run["id"], "row": index,
                    "column": "value", "value": row["value"]}],
    })
    assert checked["coverage"]["status"] != "pass"
    assert {item["id"] for item in checked["items"] if item["status"] == "answered"} == set(selected)
    # Saving adds the engine's evidence appendix, including the other ratio and
    # its own claim. Completion is legitimate only with both distinct saved cells.
    draft = draft_for(service, requirement, run, selected=selected)
    assert draft["completion"]["status"] == "complete"
    cited = {run["result"]["rows"][claim["row"]]["metric_key"] for claim in draft["claims"]}
    assert set(KEYS) <= cited


def test_zero_denominator_keeps_unanswered_requirement(tmp_path):
    service, requirement, run, _ = collection_chain(tmp_path, components={**COMPONENTS, "current_due": "0"})
    assert run["execution_status"] == "succeeded", run.get("error")
    assert not any(r["metric_key"] == KEYS[0] for r in run["result"]["rows"])
    draft = draft_for(service, requirement, run)
    assert draft["completion"]["status"] != "complete"


@pytest.mark.parametrize("requires_drilldown", [True, False])
def test_manual_component_cannot_complete_source_bound_requirement(tmp_path, requires_drilldown):
    service, requirement, run, _ = collection_chain(
        tmp_path, manual={"current_due": "999"}, requires_drilldown=requires_drilldown)
    assert run["execution_status"] == "succeeded"
    draft = draft_for(service, requirement, run)
    assert draft["completion"]["status"] != "complete"
    assert all(item["status"] != "answered" for item in draft["quality"]["requirements"]["items"])


@pytest.mark.parametrize("field,value", [("currency", "USD"), ("period", "2025-08"), ("organization", "另一公司")])
def test_declared_context_cannot_hide_conflicting_source_scope(tmp_path, field, value):
    _, _, run, _ = collection_chain(tmp_path, source_overrides={"current_due": {field: value}})
    assert run["execution_status"] != "succeeded"
