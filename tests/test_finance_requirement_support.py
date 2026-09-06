import json

import pytest

from foundry.finance_service import FinanceStore
from foundry.finance_requirement_support import assess_requirement_support
from foundry.task import TaskStore


@pytest.fixture
def support_store(tmp_path):
    store = FinanceStore(TaskStore(tmp_path / "var").create(title="量价资料检查"))
    source = tmp_path / "amounts.json"
    source.write_text(json.dumps([{"product": "商品C", "amount": "132", "unit": "元"}]))
    dataset = store.analysis.add_dataset(source, name="金额表")
    return store, dataset


def _save_requirement(store, dataset, **overrides):
    return store.analysis_requirements_save({
        "question": "解释量价变化", "bindings": {"source": dataset["id"]},
        "items": [{"id": "pq", "metric": "price_quantity", "requires_drilldown": True}],
        **overrides,
    })


def test_requirements_report_snapshot_bound_gap_and_preserve_question(support_store):
    store, dataset = support_store
    requirement = _save_requirement(store, dataset, support={"items": []})
    report = requirement["support"]["items"][0]
    assert requirement["question"] == "解释量价变化"
    assert report["status"] == "requires_input"
    assert report["missing_inputs"][0]["columns"] == ["quantity", "price"]
    assert report["sources"][0]["dataset_id"] == dataset["id"]
    assert report["sources"][0]["source_hash"] == dataset["source_hash"]
    assert "字段映射" in report["next_action"]
    assert report == store.analysis._get("requirements", requirement["id"])["support"]["items"][0]


def test_native_alias_is_reported_without_rewriting_user_metric(support_store):
    store, dataset = support_store
    requirement = _save_requirement(store, dataset, items=[{"id": "ratio", "metric": "variance_ratio"}])
    assert requirement["items"][0]["metric"] == "variance_ratio"
    assert requirement["support"]["items"][0]["canonical_metric"] == "ratio"
    assert any(item["metric"] == "control_totals" for item in store.list_finance_context()["requirement_metric_catalog"])


def test_unrecognized_metric_returns_path_without_erasing_obligation(support_store):
    store, dataset = support_store
    requirement = _save_requirement(store, dataset, items=[{"id": "custom", "metric": "custom_formula"}])
    report = requirement["support"]["items"][0]
    assert report["status"] == "unrecognized"
    assert "SQL/Python" in report["next_action"]
    assert requirement["items"][0]["id"] == "custom"


def test_verified_gap_ends_reply_but_not_original_analysis(support_store):
    store, dataset = support_store
    _save_requirement(store, dataset)
    draft = store.save_explanation_draft({"body": "量价分解需先补齐资料或说明字段映射。"})
    assert "## 待补资料" in draft["body"]
    assert "quantity/price" in draft["body"]
    completion = draft["completion"]
    assert completion["status"] == "awaiting_input"
    assert completion["response_status"] == "ended_with_limitations"
    assert completion["repair_allowed"] is False
    assert completion["original_requirements_completed"] is False
    quality = draft["explanation_check"]
    assert quality["requirements"]["coverage"]["status"] == "needs_attention"
    assert quality["requirements"]["items"][0]["status"] == "missing_data"
    edited = store.save_explanation_draft({"parent_id": draft["id"], "body": "经理将补充数量明细。"})
    assert edited["id"] != draft["id"]
    assert edited["body"].count("## 待补资料") == 1
    assert store.save_explanation_draft({"parent_id": draft["id"], "body": "经理将补充数量明细。"})["id"] == edited["id"]


def test_gap_does_not_hide_other_unanswered_requirements(support_store):
    store, dataset = support_store
    _save_requirement(store, dataset, items=[{"id": "pq", "metric": "price_quantity"},
                                           {"id": "profit", "metric": "profit"}])
    draft = store.save_explanation_draft({"body": "需要补充量价资料。"})
    assert draft["completion"]["status"] != "awaiting_input"
    assert draft["completion"]["original_requirements_completed"] is False


def test_gap_does_not_hide_invented_financial_number(support_store):
    store, dataset = support_store
    _save_requirement(store, dataset)
    draft = store.save_explanation_draft({"body": "收入增长了999万元，但需补量价资料。"})
    assert draft["completion"]["status"] != "awaiting_input"
    assert any(issue["code"] == "uncited_number" for issue in draft["explanation_check"]["issues"])


def test_corrupt_snapshot_cannot_prove_inputs_are_absent(support_store):
    store, dataset = support_store
    requirement = _save_requirement(store, dataset)
    folder = store.analysis.root / "datasets" / dataset["id"]
    (folder / "data.json").write_text("{}")
    report = assess_requirement_support(store.analysis, requirement)["items"][0]
    assert report["status"] == "unverified"
    assert "missing_inputs" not in report
    draft = store.save_explanation_draft({"body": "等待资料。"})
    assert draft["completion"]["status"] != "awaiting_input"
    assert "## 待补资料" not in draft["body"]


def test_missing_bindings_and_fabricated_report_do_not_end_reply(support_store):
    store, dataset = support_store
    _save_requirement(store, dataset, bindings={}, support={"items": [{"status": "requires_input"}]})
    draft = store.save_explanation_draft({"body": "资料不足。"})
    assert draft["completion"]["status"] != "awaiting_input"


def test_available_fields_cannot_be_overridden_by_client_gap(support_store, tmp_path):
    store, _dataset = support_store
    source = tmp_path / "quantity.json"
    source.write_text(json.dumps([{"quantity": "12", "price": "11"}]))
    dataset = store.analysis.add_dataset(source, name="量价表")
    requirement = _save_requirement(store, dataset, support={"status": "requires_input"})
    assert requirement["support"]["items"][0]["status"] == "requires_execution"
    draft = store.save_explanation_draft({"body": "模型声称没有量价字段。"})
    assert draft["completion"]["status"] != "awaiting_input"


@pytest.mark.parametrize("metric", ["amount", "revenue"])
def test_explicit_price_quantity_method_checks_inputs(support_store, metric):
    store, dataset = support_store
    requirement = _save_requirement(store, dataset, items=[{
        "id": "pq", "metric": metric,
        "dimensions": {"method": "base_weights_with_interaction"},
    }])
    assert requirement["support"]["items"][0]["status"] == "requires_input"
    draft = store.save_explanation_draft({"body": "需补充量价资料或映射。"})
    assert draft["completion"]["status"] == "awaiting_input"


def test_plain_amount_is_not_assumed_to_require_price_quantity(support_store):
    store, dataset = support_store
    requirement = _save_requirement(store, dataset, items=[{"id": "amount", "metric": "amount"}])
    assert requirement["support"]["items"][0]["status"] == "requires_execution"
    assert "missing_inputs" not in requirement["support"]["items"][0]
