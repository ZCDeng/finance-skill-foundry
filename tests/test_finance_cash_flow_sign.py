"""Positive cash stock cannot qualify an assertion about the sign of period flows."""
from copy import deepcopy
import json

import pytest

from foundry.analysis import _hash
from foundry.finance_claim_semantics import check_claim_semantics
from foundry.finance_scenarios import forecast_cash_13_weeks
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


SCOPE = {"ledger": "L", "organization": "O", "currency": "CNY", "unit": "万元"}


def cash_run(*, opening="300", receipts="50", payments="80", run_id="run"):
    result = forecast_cash_13_weeks(opening_cash=opening, start_date="2026-10-01", actual_cutoff="2026-09-30",
        receipts=[{**SCOPE, "id": "R", "date": "2026-10-02", "amount": receipts}],
        payments=[{**SCOPE, "id": "P", "date": "2026-10-03", "amount": payments}], scope=SCOPE)
    result.update(domain="foundry.finance.scenario_result.v1", scenario_id="cash-scenario")
    run = {"id": run_id, "engine": "finance", "execution_status": "succeeded", "result": result, "output_hash": _hash(result)}
    facts = [{"id": f"{run_id}-closing-{i}", "run_id": run_id, "row": i, "column": "closing_cash",
              "value": row["closing_cash"], "unit": "万元", "semantics": {"metric": "closing_cash"},
              "evidence_eligibility": {"status": "source_verified", "counts_as_amount_evidence": True}}
             for i, row in enumerate(result["rows"])]
    return run, facts


def sign_issues(body, facts, runs):
    return [issue for issue in check_claim_semantics(body, facts, runs=runs)
            if issue["code"] == "cash_flow_sign_mismatch"]


@pytest.mark.parametrize("opening,receipts,payments,wrong,right", [
    ("300", "50", "80", "正", "负"),
    ("-300", "80", "50", "负", "正"),
    ("300", "50", "50", "正", "零"),
])
def test_sign_uses_receipts_less_payments_not_positive_or_negative_closing_cash(opening, receipts, payments, wrong, right):
    run, facts = cash_run(opening=opening, receipts=receipts, payments=payments)
    wrong_body = f"第一周（2026-10-01 至 2026-10-07）期末现金为{facts[0]['value']}万元，资金流为{wrong}。"
    issues = sign_issues(wrong_body, facts, [run])
    assert len(issues) == 1
    assert issues[0]["net_cash_flow"] == str(int(receipts) - int(payments))
    assert issues[0]["row"] == 0 and issues[0]["run_id"] == run["id"]
    assert sign_issues(wrong_body.replace(f"资金流为{wrong}", f"资金流为{right}"), facts, [run]) == []


@pytest.mark.parametrize("body", [
    "第一周不能声称资金流为正。", "第一周如果资金流为正，再研究分配。",
    "第一周的期末现金为270万元，并不代表资金流为正。", "第一周资金流为正的说法不正确。",
    "第一周资金流为正吗？", "第一周现金余额为正。",
    "第一周只有资金流为正时才考虑分配。", "第一周仅当资金流为正才考虑分配。",
    "第一周资金流为正的假设尚未验证。", "Week 1 cannot say net cash flow is positive.",
    "Week 1 net cash flow is positive is incorrect.",
    "第一周经营现金流为正。", "第一周自由现金流为正。", "Week 1 operating net cash flow is positive.",
    "第一周资金流为正常。", "第一周资金流为正增长。",
    "第一周经营活动现金流为正。", "第一周筹资现金流为正。", "第一周投资现金流为正。",
    "第一周非现金流为正。", "第一周经营活动产生的现金流为正。",
    "第一周经营活动现金流另列，现金流为正。", "第一周经营活动：现金流为正。",
    "Week 1 financing net cash flow is positive.", "Week 1 investing net cash flow is positive.",
    "第一周资金流为正是未经验证的假设。",
])
def test_negation_hypothesis_and_balance_assertions_are_not_flow_sign_claims(body):
    run, facts = cash_run()
    assert sign_issues(body, facts, [run]) == []


def test_week_scope_does_not_borrow_a_different_week_or_run():
    run, facts = cash_run()
    assert sign_issues("第二周资金流为零。", facts, [run]) == []
    assert sign_issues("第一周资金流为正。", facts, [run])
    assert sign_issues("第二周资金流为正。", facts[:1], [run]) == []
    assert sign_issues("第一周（2026-10-08 至 2026-10-14）资金流为正。", facts, [run]) == []
    assert sign_issues("资金流为正。", facts, [run]) == []
    other, other_facts = cash_run(receipts="80", payments="50", run_id="other")
    assert sign_issues("第一周资金流为正。", facts + other_facts, [run, other]) == []
    assert sign_issues("第一周资金流为正。", facts, [other]) == []


def test_unclassified_total_flow_remains_checked_after_a_classified_topic():
    run, facts = cash_run()
    assert sign_issues("第一周总净现金流为正。", facts, [run])
    assert sign_issues("第一周总净现金流为负。", facts, [run]) == []
    assert sign_issues("第一周经营活动现金流另列，整周净现金流为正。", facts, [run])


def test_only_hash_bound_finance_result_with_cited_row_can_supply_sign_proof():
    run, facts = cash_run()
    for mutation in ("hash", "engine", "execution", "fact_value", "arithmetic"):
        altered, altered_facts = deepcopy(run), deepcopy(facts)
        if mutation == "hash":
            altered["output_hash"] = "forged"
        if mutation == "engine":
            altered["engine"] = "sql"
        if mutation == "execution":
            altered["execution_status"] = "failed"
        if mutation == "fact_value":
            altered_facts[0]["value"] = "999"
        if mutation == "arithmetic":
            altered["result"]["rows"][0]["receipts"] = "999"
            altered["output_hash"] = _hash(altered["result"])
        assert sign_issues("第一周资金流为正。", altered_facts[:1], [altered]) == [], mutation


def test_real_saved_cash_draft_rejects_wrong_sign_and_retains_failed_version(tmp_path, monkeypatch):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="现金存量与流量"))
    bindings = {}
    for alias, amount in (("receipts", "50"), ("payments", "80")):
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps([{**SCOPE, "id": alias, "date": "2026-10-02", "amount": amount}]))
        bindings[alias] = service.analysis.add_dataset(path, name=alias)["id"]
    context = service.save_context({"bindings": bindings, "scopes": {alias: SCOPE for alias in bindings}})
    scenario = service.save_scenario({"context_id": context["id"], "kind": "cash_13_weeks", "inputs": {
        "scope": SCOPE, "opening_cash": "300", "start_date": "2026-10-01", "actual_cutoff": "2026-09-30"}})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded", run.get("error")
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    balance = next(fact for fact in prepared["facts"] if fact["row"] == 0 and fact["column"] == "closing_cash")
    spec = {"run_ids": [run["id"]], "body": "第一周（2026-10-01 至 2026-10-07）期末现金为{{fact:"
            + balance["id"] + "}}，资金流为正。"}
    bad = service.save_explanation_draft(spec)
    assert any(issue["code"] == "cash_flow_sign_mismatch" for issue in bad["quality"]["issues"])
    assert bad["completion"]["status"] != "complete"
    good = service.save_explanation_draft({**spec, "parent_id": bad["id"], "body": spec["body"].replace("资金流为正", "资金流为负")})
    assert not any(issue["code"] == "cash_flow_sign_mismatch" for issue in good["quality"]["issues"])
    assert service.analysis._get("drafts", bad["id"])["body"] == bad["body"]
    from foundry import finance_claim_semantics
    with monkeypatch.context() as old:
        old.setattr(finance_claim_semantics, "CLAIM_SEMANTICS_VERSION", 16)
        old.setattr(finance_claim_semantics, "_cash_flow_sign_issues", lambda *args: [])
        historical = service.save_explanation_draft({**spec, "body": "历史版本：" + spec["body"]})
    assert historical["quality"]["claim_semantics_version"] == 16
    path = service.analysis._object_path("drafts", historical["id"])
    before = path.read_bytes()
    current = service.analysis.draft_in_view(service.analysis.get_draft(historical["id"]), None)
    assert any(issue["code"] == "cash_flow_sign_mismatch" for issue in current["quality"]["issues"])
    assert path.read_bytes() == before
