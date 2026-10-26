"""Native volume/mix/price evidence must answer the requested comparison scopes."""
from copy import deepcopy
import json

import pytest

from foundry.finance_requirements import (
    _path_text,
    _price_quantity_requirement_matches,
    check_requirements,
)
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


COLUMNS = ("total_variance", "volume_contribution", "mix_contribution", "price_contribution")
DIMENSIONS = {"method": "volume_mix_price", "actual_scenario": "actual", "baseline_scenario": "budget"}


def _native_vmp(tmp_path, dimensions):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="VMP 比较口径"))
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}
    rows = [
        {**scope, "product": product, "scenario": scenario, "quantity": quantity,
         "price": price, "quantity_unit": "件"}
        for product, scenario, quantity, price in [
            ("A", "budget", "50", "10"), ("B", "budget", "50", "20"),
            ("A", "actual", "72", "12"), ("B", "actual", "48", "18"),
        ]
    ]
    path = tmp_path / "basket.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    dataset = service.analysis.add_dataset(path, name="篮子")
    context = service.save_context({"bindings": {"basket": dataset["id"]}, "scopes": {"basket": scope}})
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "question": "按要求的实际和基准情景解释量结构价差异",
        "items": [{"id": "vmp", "metric": "price_quantity", "dimensions": dimensions}],
    })
    run = service.explain_variance({"context_id": context["id"], "kind": "price_quantity",
                                    **DIMENSIONS})
    assert run["execution_status"] == "succeeded", run.get("error")
    assert [run["result"]["rows"][0][key] for key in COLUMNS] == ["228", "300", "-120", "48"]
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    facts = [fact for fact in prepared["facts"] if fact["column"] in (*COLUMNS, "residual")]
    claims = [{"basis": "calculation", "run_id": run["id"], "row": fact["row"],
               "column": fact["column"], "value": fact["value"], "fact_id": fact["id"]} for fact in facts]
    body = "\n".join(f"{fact['column']}: {{{{fact:{fact['id']}}}}}" for fact in facts)
    draft_spec = {"requirements_id": requirement["id"], "run_ids": [run["id"]], "claims": claims, "body": body}
    return service, run, prepared, draft_spec


@pytest.mark.parametrize("dimensions,answered", [
    (DIMENSIONS, True),
    ({**DIMENSIONS, "actual_scenario": "budget"}, False),
    ({**DIMENSIONS, "baseline_scenario": "actual"}, False),
    ({**DIMENSIONS, "actual_scenario": "budget", "baseline_scenario": "actual"}, False),
    ({**DIMENSIONS, "baseline_scenario": "forecast"}, False),
])
def test_native_vmp_scenario_requirement_reaches_current_completion(tmp_path, dimensions, answered):
    service, run, prepared, draft_spec = _native_vmp(tmp_path, dimensions)
    checked = check_requirements(service.analysis, draft_spec)
    assert (checked["items"][0]["status"] == "answered") is answered, checked
    draft = service.save_explanation_draft(draft_spec)
    assert (draft["completion"]["status"] == "complete") is answered, draft["completion"]
    validation = service.validate_explanation(draft_spec)
    assert (validation["requirements"]["items"][0]["status"] == "answered") is answered
    if answered:
        assert validation["status"] == "pass", validation
        assert checked["original_requirements_completed"] is True


@pytest.mark.parametrize("scope_name,scope_value,flat_value", [
    ("actual_scope", {"scenario": "budget"}, "actual"),
    ("baseline_scope", {"scenario": "actual"}, "budget"),
    ("actual_scope", {"scenario": ["actual", "budget"]}, "actual"),
    ("baseline_scope", {"scenario": ["actual", "budget"]}, "budget"),
    ("actual_scope", {}, "actual"),
    ("baseline_scope", None, "budget"),
    ("actual_scope", {"scenario": "actual"}, "budget"),
    ("baseline_scope", {"scenario": "budget"}, "actual"),
])
def test_vmp_flat_scenario_cannot_override_missing_wrong_or_mixed_scope(tmp_path, scope_name, scope_value, flat_value):
    service, run, prepared, draft_spec = _native_vmp(tmp_path, DIMENSIONS)
    group = next(group for group in prepared["evidence_groups"] if group["group_type"] == "price_quantity_bridge")
    row = deepcopy(run["result"]["rows"][0])
    row[scope_name] = scope_value
    row[scope_name.replace("_scope", "_scenario")] = flat_value
    assert not _price_quantity_requirement_matches(
        {"metric": "price_quantity", "dimensions": DIMENSIONS}, run, row, group,
    )


@pytest.mark.parametrize("method,expected,absent", [
    ("volume_mix_price", ("volume_contribution", "mix_contribution"), ("quantity_contribution", "interaction")),
    ("quantity_then_price", ("quantity_contribution", "interaction"), ("volume_contribution", "mix_contribution")),
    ("base_weights_with_interaction", ("quantity_contribution", "interaction"), ("volume_contribution", "mix_contribution")),
])
def test_bridge_guidance_names_its_actual_method_columns(method, expected, absent):
    text = _path_text({"path": "price_quantity_bridge", "method": method}, "metric_key 和 value")
    assert all(column in text for column in (*expected, "total_variance", "price_contribution")), text
    assert all(column not in text for column in absent), text


def test_unpinned_bridge_guidance_distinguishes_both_column_contracts():
    text = _path_text({"path": "price_quantity_bridge", "methods": [
        "quantity_then_price", "base_weights_with_interaction", "volume_mix_price",
    ]}, "metric_key 和 value")
    assert all(column in text for column in (*COLUMNS, "quantity_contribution", "interaction")), text
