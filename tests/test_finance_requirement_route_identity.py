"""A requested grain does not turn a derived metric into a ledger account."""
from copy import deepcopy

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_requirements import check_requirements, save_requirements
from foundry.task import TaskStore
from test_finance_requirements import (
    _claim, _claims_for_columns, _control_rows, _finance_service_from_rows,
    _script_run, _verify_run_column, _workbook,
)


SCOPE = {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元"}


def ledger_case(tmp_path):
    rows = _control_rows([("actual", "cash", "132"), ("budget", "cash", "100")])
    return _finance_service_from_rows(tmp_path, {"ledger": rows}, {"ledger": SCOPE}, title="route-identity")


@pytest.mark.parametrize("grain", [{"periods": ["2026-09"]}, {"organizations": ["O1"]},
                                    {"periods": ["2026-09"], "scenarios": ["actual", "budget"]}])
@pytest.mark.parametrize("method", [None, "price_quantity", "base_weights_with_interaction"])
def test_price_quantity_grain_keeps_method_evidence_and_verified_input_gap(tmp_path, grain, method):
    service, context, bindings = ledger_case(tmp_path)
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "bindings": bindings, "scope": SCOPE,
        "question": "解释量价变化；数量或单价缺失时不得以总额冒充分解",
        "items": [{"id": "pq", "metric": "price_quantity", "requires_drilldown": True,
                   **grain, **({"dimensions": {"method": method}} if method else {})}],
    })
    support = requirement["support"]["items"][0]
    assert support["status"] == "requires_input"
    paths = support.get("accepted_evidence", []) + [p["path"] for p in support.get("blocked_evidence", [])]
    assert "run_metric_result_set" not in paths
    assert "run_metric_account_total" not in paths
    assert not support.get("execution_specs")
    assert ("method_run" if method == "price_quantity" else "price_quantity_bridge") in paths
    if method == "price_quantity":
        assert support["evidence"] == "method_run"
    checked = check_requirements(service.analysis, {"requirements_id": requirement["id"], "run_ids": [], "claims": []})
    offered = checked["items"][0]["evidence_paths"]
    assert not any(p["path"].startswith("run_metric") for p in offered["accepted"] + offered["blocked"])
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "body": "量价分解需补充数量与单价资料。"})
    assert draft["completion"]["status"] == "awaiting_input"
    assert draft["completion"]["original_requirements_completed"] is False
    assert service.analysis._get("requirements", requirement["id"])["items"] == requirement["items"]


@pytest.mark.parametrize("metric", ["difference", "gl_subledger_difference", "custom_balance"])
def test_derived_metric_with_periods_never_advertises_a_nonexistent_account(tmp_path, metric):
    service, context, bindings = ledger_case(tmp_path)
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "bindings": bindings, "scope": SCOPE,
        "question": "核验派生金额，不改变原指标身份",
        "items": [{"id": "derived", "metric": metric, "periods": ["2026-09"]}],
    })
    before = deepcopy(requirement)
    support = requirement["support"]["items"][0]
    assert not support.get("execution_specs")
    assert "run_metric_result_set" not in support.get("accepted_evidence", [])
    result = check_requirements(service.analysis, {"requirements_id": requirement["id"], "run_ids": [], "claims": []})
    item = result["items"][0]
    assert item["status"] != "answered"
    assert not any(p["path"].startswith("run_metric") for p in
                   item["evidence_paths"]["accepted"] + item["evidence_paths"]["blocked"])
    assert service.analysis._get("requirements", requirement["id"]) == before


def test_real_source_account_still_has_native_result_set_and_source_checked_completion(tmp_path):
    service, context, bindings = ledger_case(tmp_path)
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "bindings": bindings, "scope": SCOPE,
        "question": "核验 cash 科目的实际与预算", "items": [
            {"id": "cash", "metric": "cash", "periods": ["2026-09"], "scenarios": ["actual", "budget"],
             "requires_drilldown": True}],
    })
    support = requirement["support"]["items"][0]
    assert support["accepted_evidence"] == ["run_metric_result_set"]
    assert support["execution_specs"][0]["spec"]["metric"] == {"kind": "account_total", "accounts": ["cash"]}
    run = service.run_metric({"context_id": context["id"], "metric": {"kind": "account_total", "accounts": ["cash"]}})
    _verify_run_column(service, run, "amount")
    result = check_requirements(service.analysis, {"requirements_id": requirement["id"], "run_ids": [run["id"]],
                                                   "claims": _claims_for_columns(run, "amount")})
    assert result["coverage"]["status"] == "pass"
    assert result["items"][0]["provenance_status"] == "verified"


@pytest.mark.parametrize("source_identity", ["default_alias", "field_map", "account_map"])
def test_real_source_account_identity_uses_the_engine_field_and_account_maps(tmp_path, source_identity):
    rows = _control_rows([("actual", "cash", "132"), ("budget", "cash", "100")])
    for row in rows:
        account = row.pop("management_account")
        row[{"default_alias": "管理科目", "field_map": "ledger_account", "account_map": "account_code"}[source_identity]] = (
            "1001" if source_identity == "account_map" else account)
    service, _, bindings = _finance_service_from_rows(tmp_path, {"ledger": rows}, {"ledger": SCOPE}, title="mapped-route")
    context_spec = {"bindings": bindings, "scopes": {"ledger": SCOPE}}
    if source_identity == "field_map":
        context_spec["policies"] = {"ledger": {"field_map": {"management_account": "ledger_account"}}}
    elif source_identity == "account_map":
        mapping = service.save_account_map({"rows": [{"account_code": "1001", "management_account": "cash"}]})
        context_spec["account_map_id"] = mapping["id"]
    context = service.save_context(context_spec)
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "bindings": bindings, "scope": SCOPE,
        "question": "核验源科目现金，不绕过集合来源检查", "items": [
            {"id": "cash", "metric": "cash", "periods": ["2026-09"], "scenarios": ["actual", "budget"]}],
    })
    assert requirement["support"]["items"][0]["accepted_evidence"] == ["run_metric_result_set"]
    assert requirement["support"]["items"][0]["status"] == "requires_execution"
    run = service.run_metric({"context_id": context["id"], "metric": {"kind": "account_total", "accounts": ["cash"]}})
    checked_spec = {"requirements_id": requirement["id"], "run_ids": [run["id"]],
                    "claims": _claims_for_columns(run, "amount")}
    assert check_requirements(service.analysis, checked_spec)["items"][0]["status"] == "pending"
    _verify_run_column(service, run, "amount")
    assert check_requirements(service.analysis, checked_spec)["items"][0]["status"] == "answered"


def derived_case(tmp_path, metric, *, reported_metric=None, period="2026-09", column="value"):
    analysis = AnalysisStore(TaskStore(tmp_path / "var").create(title="派生差额来源复算"))
    source = _workbook(analysis, tmp_path, "reconciliation", {"对账": {"A1": 150, "B1": 50}})
    requirement = save_requirements(analysis, {
        "question": "核验总账与子账的差额；金额不证明会计确认依据", "bindings": {"source": source["id"]},
        "scope": {"ledger": "L1", "currency": "CNY", "unit": "万元"},
        "items": [{"id": "derived", "metric": metric, "periods": ["2026-09"], "organizations": ["O1"],
                   "requires_drilldown": True}],
    })
    run = _script_run(analysis, {"source": source}, [{"metric_key": reported_metric or metric, column: "100",
        "period": period, "organization": "O1", "currency": "CNY", "unit": "万元"}], suffix="derived")
    def location(cell):
        return {"dataset_id": source["id"], "source_hash": source["source_hash"], "sheet": "对账", "range": cell}
    recipe = {"id": "difference", "kind": "diff", "left": location("A1"), "right": location("B1"),
              "claim": {"run_id": run["id"], "row": 0, "column": column}}
    base = {"requirements_id": requirement["id"], "run_ids": [run["id"]],
            "claims": [_claim(run, row=0, column=column, value="100")]}
    return analysis, requirement, base, recipe


@pytest.mark.parametrize("metric", ["difference", "gl_subledger_difference", "arbitrary_output_alias"])
def test_derived_period_amount_requires_exact_identity_and_source_recomputed_difference(tmp_path, metric):
    analysis, requirement, base, recipe = derived_case(tmp_path, metric)
    unproved = check_requirements(analysis, base)
    assert unproved["items"][0]["status"] != "answered"
    answered = check_requirements(analysis, {**base, "evidence_recipes": [recipe]})
    item = answered["items"][0]
    assert item["status"] == "answered", item
    assert item["provenance_status"] == "verified"
    assert item["locations"][0]["evidence"]["evidence_basis"] == "source_calculation"
    assert item["locations"][0]["evidence"]["mapping_review"] == "unreviewed"
    assert requirement["items"][0]["metric"] == metric


@pytest.mark.parametrize("mutation", ["identity", "period", "source_hash", "computed_value"])
def test_matching_amount_cannot_override_derived_identity_period_or_source_proof(tmp_path, mutation):
    analysis, _, base, recipe = derived_case(tmp_path, "gl_subledger_difference",
        reported_metric="unrelated_alias" if mutation == "identity" else None,
        period="2026-08" if mutation == "period" else "2026-09")
    if mutation == "source_hash":
        recipe["left"]["source_hash"] = "0" * 64
    if mutation == "computed_value":
        recipe["right"]["range"] = "A1"
    result = check_requirements(analysis, {**base, "evidence_recipes": [recipe]})
    assert result["items"][0]["status"] != "answered"
    assert result["coverage"]["status"] == "needs_attention"


@pytest.mark.parametrize("metric", ["difference", "arbitrary_output_alias"])
def test_named_output_column_is_not_a_source_calculation(tmp_path, metric):
    analysis, _, base, recipe = derived_case(tmp_path, metric, column=metric)
    assert check_requirements(analysis, base)["items"][0]["status"] != "answered"
    recipe["right"]["range"] = "A1"  # The column name cannot make the actual zero difference equal 100.
    assert check_requirements(analysis, {**base, "evidence_recipes": [recipe]})["items"][0]["status"] != "answered"
