"""Source-bound authoring aids retain undefined, sign, currency and date boundaries."""
from copy import deepcopy
import json

import pytest

from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from test_finance_explanations import service  # noqa: F401
from test_finance_non_numeric_outcomes import BODY, zero_case


def test_undefined_rates_offer_a_verified_limitation_template(tmp_path):
    store, requirement, run, _ = zero_case(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    assert prepared["draft_template"]["body"].startswith(BODY)
    assert prepared["draft_template"]["claims"] == []
    assert prepared["facts"] == []
    saved = store.save_explanation_draft(prepared["save_template_spec"])
    assert saved["completion"]["stop_reason"] == "verified_undefined_result"
    assert saved["completion"]["repair_allowed"] is False
    assert saved["completion"]["original_requirements_completed"] is False
    assert saved["completion"]["requirements_id"] == requirement["id"]
    assert "原数值要求未完成" in saved["final_response"]


@pytest.mark.parametrize("mode", ["manual", "partial", "mixed", "new_requirement", "denied"])
def test_undefined_template_does_not_hide_missing_or_mixed_evidence(tmp_path, mode):
    options = {"manual": {"manual": {"current_due": "0"}},
               "partial": {"components": {"current_due": "0", "current_collection": "0"}},
               "mixed": {"components": {"current_due": "0", "current_collection": "0",
                                         "opening_ar": "100", "arrears_collection": "50"}}}
    store, requirement, run, _ = zero_case(tmp_path, **options.get(mode, {}))
    if mode == "new_requirement":
        store.analysis_requirements_save({"context_id": requirement["context_id"],
            "parent_id": requirement["id"], "question": "新的期间范围", "scope": {"period": "2025-08"},
            "items": requirement["items"]})
    if mode == "denied":
        from foundry.finance_non_numeric_outcomes import prepare_undefined_draft
        assert prepare_undefined_draft(store.analysis, [run], allowed=set()) is None
    else:
        prepared = store.prepare_explanation({"run_ids": [run["id"]]})
        assert prepared["draft_template"] is None


@pytest.mark.parametrize("body", [
    "闭合公式：利润影响合计 = 收入 20 万元 + 成本 -10 万元 + 费用 -5 万元 = 5 万元。",
    "核实成本对利润的拖累 -10 万元背后的原因；核实费用对利润的拖累 -5 万元背后的原因。",
    "利润桥精确闭合：收入 +20、成本 −10、费用 −5，合计 +5。",
    "利润桥：成本增加 10 万元。",
    "利润桥：费用增加 5 万元。",
    "利润桥：成本比预算增加 10 万元。",
    "利润桥：成本 -10 万元，费用 -5 万元。",
    "利润桥：成本 -10 万元,费用 -5 万元。",
])
def test_profit_effect_scope_is_preserved_for_components(service, body):  # noqa: F811
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    facts = store.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    checked = store.validate_explanation({"run_ids": [run["id"]], "body": body,
                                         "fact_ids": [f["id"] for f in facts]})
    assert not [i for i in checked["issues"] if i["code"] in {
        "fact_direction_mismatch", "fact_label_mismatch", "fact_metric_semantics_mismatch"}], checked["issues"]


@pytest.mark.parametrize("body", [
    "闭合公式：利润影响合计 = 收入 20 万元 + 成本 10 万元 + 费用 -5 万元 = 5 万元。",
    "闭合公式：利润影响合计 = 收入 20 万元 + 成本 -10 万元 + 费用 -5 万元 = -5 万元。",
    "成本增加 -10 万元。",
    "核实成本对利润的拖累 10 万元背后的原因。",
    "费用对利润的贡献为 5 万元。",
    "利润桥：成本减少 -10 万元。",
    "利润桥：成本减少 10 万元。",
    "利润桥：费用减少 5 万元。",
    "利润影响合计 = 成本减少 10 万元。",
    "利润桥：成本对利润的拉动 -10 万元。",
    "利润桥：成本比预算减少 10 万元。",
    "利润桥：减少成本 10 万元。",
    "利润桥：成本 -10 万元，费用减少 5 万元。",
    "利润桥：成本 -10 万元，费用 +5 万元。",
    "利润桥：成本 -10 万元。费用变动：费用 -5 万元。",
])
def test_wrong_cost_or_profit_effect_sign_is_still_rejected(service, body):  # noqa: F811
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    facts = store.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    checked = store.validate_explanation({"run_ids": [run["id"]], "body": body,
                                         "fact_ids": [f["id"] for f in facts]})
    assert any(i["code"] in {"fact_direction_mismatch", "profit_bridge_closure_mismatch",
                             "fact_metric_semantics_mismatch"} for i in checked["issues"]), checked["issues"]


def multi_currency_aging(tmp_path, *, drilldown=True, usd_amount="20"):
    store = FinanceStore(TaskStore(tmp_path / "var").create(title="Currency-separated aging"))
    source = tmp_path / "invoices.json"
    source.write_text(json.dumps([{"ledger": "L", "organization": "O", "unit": "元",
        "currency": currency, "id": "invoice-" + currency, "customer": "客户D",
        "issue_date": "2026-07-01", "due_date": "2026-07-31", "amount": amount}
        for currency, amount in [("CNY", "100"), ("USD", usd_amount)]]))
    dataset = store.analysis.add_dataset(source, name="invoices")
    context = store.save_context({"bindings": {"invoices": dataset["id"]},
        "scopes": {"invoices": {"ledger": "L", "organization": "O", "unit": "元"}}})
    requirement = store.analysis_requirements_save({"context_id": context["id"],
        "question": "两币种账龄分别列示，不混加；下钻人民币来源",
        "items": [{"id": currency, "metric": "open_amount", "dimensions": {"currency": currency},
                   "requires_drilldown": currency == "CNY"} for currency in ("CNY", "USD")]})
    runs = []
    for currency in ("CNY", "USD"):
        scenario = store.save_scenario({"context_id": context["id"], "kind": "receivables_aging",
            "inputs": {"invoices_alias": "invoices", "as_of": "2026-08-15",
                       "scope": {"ledger": "L", "organization": "O", "currency": currency, "unit": "元"}}})
        runs.append(store.run_scenario({"scenario_id": scenario["id"]}))
    if drilldown:
        for index, row in enumerate(runs[0]["result"]["rows"]):
            store.drilldown_fact({"run_id": runs[0]["id"], "row": index, "column": "open_amount"})
    return store, requirement, runs


def test_two_aging_runs_have_separate_verified_audit_appendices(tmp_path):
    store, _, runs = multi_currency_aging(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    assert prepared["draft_template"] is not None, prepared["diagnostics"]
    saved = store.save_explanation_draft(prepared["save_template_spec"])
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert saved["completion"]["status"] == "complete", saved["completion"]
    appendix = saved["evidence_appendix"]
    assert "invoice-CNY | 2026-07-31 | 15" in appendix
    assert "invoice-USD | 2026-07-31 | 15" in appendix
    assert "100 | CNY | 元" in appendix and "20 | USD | 元" in appendix
    assert {claim["run_id"] for claim in saved["claims"]} == {r["id"] for r in runs}
    assert store.validate_explanation({"draft_id": saved["id"]})["status"] == "pass"


def test_aging_template_keeps_requested_drilldown_pending(tmp_path):
    store, _, runs = multi_currency_aging(tmp_path, drilldown=False)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    assert prepared["draft_template"] is None


@pytest.mark.parametrize("mode", ["duplicate", "denied", "changed_result", "changed_source"])
def test_multi_aging_audit_requires_current_distinct_authorized_runs(tmp_path, mode):
    from foundry.finance_native_drafts import prepare_aging_audit_metadata
    store, _, runs = multi_currency_aging(tmp_path)
    candidates = deepcopy(runs)
    allowed = None
    if mode == "duplicate":
        candidates = [runs[0], runs[0]]
    elif mode == "denied":
        allowed = set()
    elif mode == "changed_result":
        candidates[1]["result"]["detail_rows"][0]["overdue_days"] = 999
    else:
        candidates[1]["source_hashes"] = {"invoices": "invented"}
    assert prepare_aging_audit_metadata(store.analysis, candidates, allowed=allowed) is None


@pytest.mark.parametrize("mutation", ["dict", "days", "amount", "scope"])
def test_multi_aging_metadata_cannot_be_forged_by_a_model(tmp_path, mutation):
    from foundry.finance_native_drafts import render_aging_audit_appendix
    store, _, runs = multi_currency_aging(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    metadata = deepcopy(prepared["aging_audit_metadata"])
    if mutation == "dict":
        metadata = json.loads(json.dumps(metadata))
    elif mutation == "days":
        metadata["audits"][0]["detail_rows"][0]["overdue_days"] = 999
    elif mutation == "amount":
        metadata["audits"][0]["detail_rows"][0]["open_amount"] = "999"
    else:
        metadata["audits"][0]["scope"]["currency"] = "USD"
    assert render_aging_audit_appendix(metadata) == ""


def test_manual_aging_days_and_cross_currency_sum_still_need_evidence(tmp_path):
    store, _, runs = multi_currency_aging(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    spec = {**prepared["save_template_spec"], "qualitative_note": "逾期 999 天，合计 120 元。"}
    saved = store.save_explanation_draft(spec)
    assert saved["completion"]["status"] != "complete"
    assert any(i["code"] == "uncited_number" for i in saved["quality"]["issues"])


@pytest.mark.parametrize("body", [
    "人民币与美元合计 100 元。",
    "两币种合计 100 元。",
    "CNY 与 USD 合计 100 元。",
    "跨币种余额总计 20 元。",
    "两币种合计 100。",
    "CNY 与 USD 合计 100。",
    "合计 100 元。",
    "美元合计 100 元。",
    "人民币与欧元合计 100 元。",
    "人民币与美元并非不能合计 100 元。",
])
def test_matching_amount_cannot_justify_a_cross_currency_total(tmp_path, body):
    store, _, runs = multi_currency_aging(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    saved = store.save_explanation_draft({**prepared["save_template_spec"], "qualitative_note": body})
    assert saved["completion"]["status"] != "complete"
    assert any(i["code"] == "fact_currency_mismatch" for i in saved["quality"]["issues"])


@pytest.mark.parametrize("body", [
    "人民币余额 100 元，美元余额 20 元。",
    "人民币合计 100 元；美元合计 20 元。",
    "两币种不能直接合计；人民币余额 100 元，美元余额 20 元。",
    "人民币与美元不能合计为 100 元。",
    "余额 100 元人民币，余额 20 元美元。",
    "余额 100 CNY，余额 20 USD。",
])
def test_separate_currency_amounts_and_explicit_cautions_remain_valid(tmp_path, body):
    store, _, runs = multi_currency_aging(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    saved = store.save_explanation_draft({**prepared["save_template_spec"], "qualitative_note": body})
    assert saved["completion"]["status"] == "complete", saved["quality"]["issues"]


@pytest.mark.parametrize("body", [
    "人民币余额 20 元，美元余额 100 元。",
    "CNY 余额 20，USD 余额 100。",
    "欧元余额 100 元。",
    "余额 20 元人民币，余额 100 元美元。",
    "余额 20 CNY，余额 100 USD。",
])
def test_explicit_currency_identity_must_match_non_aggregate_amounts(tmp_path, body):
    store, _, runs = multi_currency_aging(tmp_path)
    prepared = store.prepare_explanation({"run_ids": [r["id"] for r in runs]})
    saved = store.save_explanation_draft({**prepared["save_template_spec"], "qualitative_note": body})
    assert saved["completion"]["status"] != "complete"
    assert any(i["code"] == "fact_currency_mismatch" for i in saved["quality"]["issues"])


def test_explicit_currency_identity_also_applies_to_one_currency_run(tmp_path):
    store, _, runs = multi_currency_aging(tmp_path)
    facts = store.prepare_explanation({"run_ids": [runs[0]["id"]]})["facts"]
    checked = store.validate_explanation({"run_ids": [runs[0]["id"]], "body": "美元余额 100 元。",
                                         "fact_ids": [f["id"] for f in facts]})
    assert any(i["code"] == "fact_currency_mismatch" for i in checked["issues"])


@pytest.mark.parametrize("currency", ["CNY", "USD"])
def test_fact_token_retains_currency_identity_when_amounts_are_equal(tmp_path, currency):
    store, requirement, runs = multi_currency_aging(tmp_path, usd_amount="100")
    prepared = store.prepare_explanation({"run_ids": [run["id"] for run in runs]})
    fact = next(f for f in prepared["facts"] if f["metric_identity"]["currency"] == currency and f["value"] == "100")
    saved = store.save_explanation_draft({"title": "币种引用", "requirements_id": requirement["id"],
        "run_ids": [run["id"] for run in runs],
        "body": "人民币余额 " + fact["reference_template"]["body_token"] + " 元。",
        "fact_ids": [f["id"] for f in prepared["facts"]]})
    mismatch = any(i["code"] == "fact_currency_mismatch" for i in saved["quality"]["issues"])
    assert mismatch is (currency == "USD"), saved["quality"]["issues"]
    assert (saved["completion"]["status"] == "complete") is (currency == "CNY")
