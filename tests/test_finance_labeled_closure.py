"""A labelled profit equation is valid only for one fully cited source bridge."""
from copy import deepcopy

import pytest

from foundry.finance_explanations import _body_closure_check, _body_numbers
from test_finance_explanations import service as service


BODY = "利润影响合计 = 收入 20 万元 + 成本 -10 万元 + 费用 -5 万元 = 利润 5 万元，桥闭合。"


@pytest.fixture
def bridge(service):
    store, context = service
    store.analysis_requirements_save({
        "context_id": context["id"], "question": "解释实际预算利润差异",
        "items": [{"id": "profit", "metric": "profit", "dimensions": {
            "method": "profit_bridge", "actual_scenario": "actual", "baseline_scenario": "budget"}}],
    })
    run = store.explain_variance({"context_id": context["id"]})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    facts = [fact for fact in prepared["facts"] if fact["column"] == "contribution"]
    return store, context, run, facts, prepared["evidence_groups"]


@pytest.mark.parametrize("body", [
    BODY,
    BODY.replace("利润影响合计", "利润贡献合计"),
    BODY.replace("20 万元", "+20.0 万元").replace("-10", "−10").replace("-5", "－5"),
    "## 闭合关系\n\n" + BODY,
    BODY.replace("，桥闭合。", "\n下一段"),
])
def test_labeled_profit_closure_reaches_native_completion(bridge, body):
    store, context, run, facts, groups = bridge
    parsed = _body_closure_check(body, facts, groups)
    assert parsed["issues"] == []
    assert parsed["token_positions"] == {token["start"] for token in _body_numbers(body)}
    draft_spec = {"body": body, "run_ids": [run["id"]], "fact_ids": [fact["id"] for fact in facts]}
    draft = store.save_explanation_draft(draft_spec)
    assert draft["completion"]["status"] == "complete", draft["explanation_check"]["issues"]
    checked = store.validate_explanation({"draft_id": draft["id"]})
    assert checked["status"] == "pass", checked["issues"]


@pytest.mark.parametrize("body", [
    BODY.replace("= 利润 5", "= 利润 -5"),
    BODY.replace("成本 -10", "成本 +10").replace("费用 -5", "费用 +5").replace("= 利润 5", "= 利润 35"),
    BODY.replace("成本 -10", "成本 -5").replace("费用 -5", "费用 -10"),
    BODY.replace("成本 -10", "收入 -10"),
    BODY.replace("= 利润 5", "= 收入 5"),
    BODY.replace("万元", "元"),
    BODY.replace("成本 -10 万元", "成本 -10 亿元"),
    BODY.replace("20 万元", "120 万元").replace("-10 万元", "70 万元")
        .replace("-5 万元", "20 万元").replace("= 利润 5", "= 利润 210"),
])
def test_labeled_closure_cannot_hide_wrong_values_labels_or_units(bridge, body):
    store, context, run, facts, groups = bridge
    parsed = _body_closure_check(body, facts, groups)
    assert not parsed["token_positions"]
    assert any(issue["code"] == "body_closure_mismatch" for issue in parsed["issues"]), parsed
    checked = store.validate_explanation({"body": body, "run_ids": [run["id"]],
                                          "fact_ids": [fact["id"] for fact in facts]})
    assert checked["status"] == "needs_attention"


@pytest.mark.parametrize("missing_index", range(4))
def test_labeled_closure_requires_every_contribution_reference(bridge, missing_index):
    store, context, run, facts, groups = bridge
    cited = [fact for index, fact in enumerate(facts) if index != missing_index]
    parsed = _body_closure_check(BODY, cited, groups)
    assert not parsed["token_positions"]
    assert any(issue["code"] == "body_closure_mismatch" for issue in parsed["issues"])


@pytest.mark.parametrize("mode", ["missing_group", "partial_group", "failed_closure", "unverified_fact", "actual_only"])
def test_labeled_closure_requires_a_complete_verified_contribution_group(bridge, mode):
    store, context, run, facts, groups = bridge
    facts, groups = deepcopy(facts), deepcopy(groups)
    if mode == "missing_group":
        groups = []
    elif mode == "partial_group":
        groups[0]["status"] = "partial"
    elif mode == "failed_closure":
        groups[0]["closure"]["status"] = "closure_mismatch"
    elif mode == "unverified_fact":
        facts[0]["evidence_eligibility"]["counts_as_amount_evidence"] = False
    else:
        prepared = store.prepare_explanation({"run_ids": [run["id"]]})
        facts = [fact for fact in prepared["facts"] if fact["column"] == "actual"]
    parsed = _body_closure_check(BODY, facts, groups)
    assert not parsed["token_positions"]
    assert any(issue["code"] == "body_closure_mismatch" for issue in parsed["issues"])


@pytest.mark.parametrize("mode", ["two_complete_groups", "cross_group_references"])
def test_labeled_closure_cannot_select_or_assemble_groups_by_same_numbers(bridge, mode):
    store, context, run, facts, groups = bridge
    second = store.explain_variance({"context_id": context["id"]})
    other = store.prepare_explanation({"run_ids": [second["id"]]})
    other_facts = [fact for fact in other["facts"] if fact["column"] == "contribution"]
    cited = [*facts, *other_facts] if mode == "two_complete_groups" else [*facts[:2], *other_facts[2:]]
    parsed = _body_closure_check(BODY, cited, [*groups, *other["evidence_groups"]])
    assert not parsed["token_positions"]
    assert any(issue["code"] == "body_closure_mismatch" for issue in parsed["issues"])


@pytest.mark.parametrize("body", [
    BODY + "成本实际为 -10 万元。",
    BODY.replace("成本 -10", "成本实际 -10"),
    BODY.replace("利润影响合计 = ", "利润影响合计。\n"),
])
def test_labeled_closure_never_propagates_impact_to_actual_values_or_another_sentence(bridge, body):
    store, context, run, facts, groups = bridge
    checked = store.validate_explanation({"body": body, "run_ids": [run["id"]],
                                          "fact_ids": [fact["id"] for fact in facts]})
    assert checked["status"] == "needs_attention"
    assert any(issue["code"] == "fact_direction_mismatch" for issue in checked["issues"])
