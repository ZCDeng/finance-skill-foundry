from __future__ import annotations

import pytest

from foundry.errors import FoundryError
from foundry.financial_consistency import consistency_quality_issues, evaluate_consistency_rules


def test_all_absolute_exceed_retains_original_text_sources_and_conflicting_values():
    report = evaluate_consistency_rules([
        {
            "id": "a32-absolute-threshold",
            "label": "A32 数字声明",
            "kind": "all_absolute_exceed",
            "threshold": "0.10",
            "asserted_result": True,
            "assertion_source_id": "a32-text",
            "values": [
                {"id": "revenue-rate", "label": "收入变动率", "value": "-0.0547", "source_id": "revenue-cell"},
                {"id": "profit-rate", "label": "利润变动率", "value": "-0.2246", "source_id": "profit-cell"},
            ],
        }
    ], source_auth={
        "a32-text": {
            "text": "A32 原文：收入、利润变动率均超过10%。",
            "reference": {"dataset_id": "budget", "source_hash": "hash-a", "sheet": "预算09", "range": "A32"},
        },
        "revenue-cell": {"reference": {"dataset_id": "budget", "source_hash": "hash-a", "sheet": "预算09", "range": "B32"}},
        "profit-cell": {"reference": {"dataset_id": "budget", "source_hash": "hash-a", "sheet": "预算09", "range": "C32"}},
    })

    issue = report["issues"][0]
    assert report["summary"] == {"status": "needs_attention", "rule_count": 1, "issue_count": 1}
    assert issue["code"] == "financial_consistency_mismatch"
    assert issue["asserted_result"] is True
    assert issue["computed_result"] is False
    assert issue["threshold"] == "0.10"
    assert issue["original_text"] == "A32 原文：收入、利润变动率均超过10%。"
    assert [value["value"] for value in issue["values"]] == ["-0.0547", "-0.2246"]
    assert issue["values"][0]["source"]["reference"]["range"] == "B32"
    assert consistency_quality_issues(report) == [issue]


def test_all_absolute_exceed_can_consume_evaluated_recipe_results_without_workbook_access():
    report = evaluate_consistency_rules([
        {
            "id": "recipe-backed-threshold",
            "label": "recipe backed",
            "kind": "all_absolute_exceed",
            "threshold": "0.10",
            "asserted_result": True,
            "assertion_source_id": "assertion",
            "values": [
                {"id": "revenue-rate", "label": "收入变动率", "recipe_result_id": "revenue-rate-recipe"},
                {"id": "profit-rate", "label": "利润变动率", "recipe_result_id": "profit-rate-recipe"},
            ],
        }
    ], recipe_report={"results": [
        {"recipe_id": "revenue-rate-recipe", "status": "pass", "actual": "-0.0547", "expected": "-0.0547"},
        {"recipe_id": "profit-rate-recipe", "status": "pass", "actual": "-0.2246", "expected": "-0.2246"},
    ]}, source_auth={"assertion": {"text": "原文断言均超过10%。", "reference": {"sheet": "预算09", "range": "A32"}}})

    assert report["issues"][0]["computed_result"] is False
    assert report["issues"][0]["values"][0]["recipe_result_id"] == "revenue-rate-recipe"


def test_consistency_rules_reject_forged_original_text_or_inline_source_reference():
    forged_rule = {
        "id": "forged",
        "label": "forged",
        "kind": "all_absolute_exceed",
        "threshold": "0.10",
        "asserted_result": True,
        "assertion_source_id": "assertion",
        "original_text": "caller supplied text",
        "values": [{"id": "v", "label": "v", "value": "0.2", "source_id": "value-source"}],
    }
    with pytest.raises(FoundryError, match="source_auth"):
        evaluate_consistency_rules([forged_rule])

    forged_value = {
        "id": "forged-value",
        "label": "forged value",
        "kind": "all_absolute_exceed",
        "threshold": "0.10",
        "asserted_result": True,
        "assertion_source_id": "assertion",
        "values": [{"id": "v", "label": "v", "value": "0.2", "source_id": "value-source", "source_ref": {"sheet": "预算"}}],
    }
    with pytest.raises(FoundryError, match="source_auth"):
        evaluate_consistency_rules([forged_value])


def test_yellow_rule_can_be_declared_separately_without_changing_a32_result():
    report = evaluate_consistency_rules([
        {
            "id": "a32-absolute-threshold",
            "label": "A32 数字声明",
            "kind": "all_absolute_exceed",
            "threshold": "0.10",
            "asserted_result": True,
            "assertion_source_id": "a32-text",
            "values": [
                {"id": "revenue-rate", "label": "收入变动率", "value": "-0.0547", "source_id": "revenue-cell"},
                {"id": "profit-rate", "label": "利润变动率", "value": "-0.2246", "source_id": "profit-cell"},
            ],
        },
        {
            "id": "a25-yellow-threshold",
            "label": "A25 黄灯规则",
            "kind": "all_absolute_exceed",
            "threshold": "0.90",
            "asserted_result": True,
            "assertion_source_id": "a25-text",
            "values": [{"id": "attainment", "label": "达成率", "value": "0.9453", "source_id": "attainment-cell"}],
        },
    ], source_auth={
        "a32-text": {"text": "A32 原文", "reference": {"sheet": "预算09", "range": "A32"}},
        "revenue-cell": {"reference": {"sheet": "预算09", "range": "B32"}},
        "profit-cell": {"reference": {"sheet": "预算09", "range": "C32"}},
        "a25-text": {"text": "A25 原文", "reference": {"sheet": "预算09", "range": "A25"}},
        "attainment-cell": {"reference": {"sheet": "预算09", "range": "B25"}},
    })

    assert [result["rule_id"] for result in report["results"]] == ["a32-absolute-threshold", "a25-yellow-threshold"]
    assert report["results"][0]["status"] == "mismatch"
    assert report["results"][1]["status"] == "pass"
    assert [issue["rule_id"] for issue in report["issues"]] == ["a32-absolute-threshold"]
