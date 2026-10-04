"""Evidence labels, the overall evidence posture, and dataset as-of/period freshness."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.evidence_labels import (
    FRESHNESS,
    LABELS,
    POSTURES,
    RULES_VERSION,
    dataset_freshness,
    evidence_posture,
    label_counts,
    label_evidence,
)
from foundry.finance_readiness import _currency, dataset_currency
from foundry.finance_service import FinanceStore
from foundry.source_refresh import SourceRefreshService, SourceScope
from foundry.task import TaskStore

ROOT = Path(__file__).resolve().parents[1]
RUN, SQL_RUN, OLD_RUN = "a" * 32, "b" * 32, "c" * 32
DATA, TEXT, REFRESH = "d" * 32, "e" * 32, "f" * 32


def _fact(fact_id: str, *, run_id: str = RUN, row: int = 0, column: str = "actual", value: str = "120") -> dict:
    return {"id": fact_id, "run_id": run_id, "row": row, "column": column, "value": value,
            "scope": {"actual": {"period": "2026-09"}, "budget": {"period": "2026-09"}}}


FACTS = [_fact("1" * 64), _fact("2" * 64, row=1, value="70"), _fact("3" * 64, run_id=SQL_RUN, column="total", value="5")]
RUNS = {
    RUN: {"id": RUN, "engine": "finance", "execution_status": "succeeded", "bindings": {"actual": DATA},
          "source_hashes": {"actual": "9" * 64}},
    SQL_RUN: {"id": SQL_RUN, "execution_status": "succeeded", "bindings": {"ledger": DATA},
              "source_hashes": {"ledger": "9" * 64}},
}
DATASETS = {
    DATA: {"name": "8月总账", "source_hash": "9" * 64, "standardized": False, "as_of": None, "period": "2026-09",
           "freshness": {"state": "current", "reasons": []}},
    TEXT: {"name": "经营说明", "source_hash": "8" * 64, "standardized": False, "freshness": {"state": "unknown", "reasons": []}},
    REFRESH: {"name": "ERP 刷新", "source_hash": "7" * 64, "standardized": True, "freshness": {"state": "current", "reasons": []}},
}


def _labels(**overrides) -> list[dict]:
    inputs = dict(claims=[], fact_ids=[], facts=FACTS, evidence_groups=[], issues=[], requirements={},
                  recipe_results=[], consistency_results=[], runs=RUNS, older_runs=set(), row_estimates={},
                  datasets=DATASETS)
    inputs.update(overrides)
    return label_evidence(**inputs)


def _one(labels: list[dict], kind: str, **match) -> dict:
    found = [entry for entry in labels if entry["key"]["kind"] == kind
             and all(entry["key"].get(name) == value for name, value in match.items())]
    assert len(found) == 1, (kind, match, labels)
    return found[0]


def _codes(entry: dict) -> list[str]:
    return [reason["code"] for reason in entry["reasons"]]


# --- one case per label rule ---------------------------------------------------------------------------------


def test_the_twelve_labels_and_five_postures_are_the_ones_the_manager_reads():
    assert list(LABELS) == [
        "fact_source_reported", "fact_provider_standardized", "derived_calculation", "management_claim",
        "analyst_interpretation", "assumption_user_provided", "assumption_inferred", "estimate", "stale_source",
        "contradicted_source", "missing_required_source", "unknown",
    ]
    assert LABELS["estimate"] == "估算" and LABELS["contradicted_source"] == "矛盾来源"
    assert POSTURES == {"decision_grade": "可决策", "research_grade": "研究级", "preliminary": "初步",
                        "assumption_led": "假设主导", "unsupported": "无法支持"}
    assert FRESHNESS == {"current": "当前", "source_stale": "资料过期", "period_mismatch": "期间不符", "unknown": "未声明"}


def test_a_source_fact_claim_on_a_file_is_source_reported_and_on_a_refresh_is_standardized():
    labels = _labels(claims=[{"basis": "source_fact", "dataset_id": TEXT, "paragraph": 2},
                             {"basis": "source_fact", "dataset_id": REFRESH}])
    first, second = labels
    assert first["label"] == "fact_source_reported" and first["text"] == "来源原文"
    assert first["source_refs"] == [{"dataset_id": TEXT, "source_hash": "8" * 64, "paragraph": 2}]
    assert second["label"] == "fact_provider_standardized"


def test_a_recipe_matched_to_the_original_cell_is_source_reported():
    recipe = {"status": "pass", "evidence_class": "source_value", "claim": {"run_id": SQL_RUN, "row": 0, "column": "total"},
              "location": {"sheet": "利润表", "range": "C5"},
              "source_refs": [{"dataset_id": DATA, "source_hash": "9" * 64, "sheet": "利润表", "range": "C5"}]}
    fact = _one(_labels(fact_ids=["3" * 64], recipe_results=[recipe]), "fact", fact_id="3" * 64)
    assert fact["label"] == "fact_source_reported"
    assert "来源复算：与原表利润表!C5一致" in [reason["text"] for reason in fact["reasons"]]
    assert fact["source_refs"][0] == {"dataset_id": DATA, "source_hash": "9" * 64, "sheet": "利润表", "range": "C5"}


def test_finance_engine_totals_are_standardized_and_a_sql_result_is_derived():
    labels = _labels(fact_ids=["1" * 64, "3" * 64])
    assert _one(labels, "fact", fact_id="1" * 64)["label"] == "fact_provider_standardized"
    derived = _one(labels, "fact", fact_id="3" * 64)
    assert derived["label"] == "derived_calculation" and _codes(derived) == ["run_calculation"]
    assert _one(labels, "fact", fact_id="1" * 64)["period"] == "2026-09"


def test_a_consistency_assertion_from_a_source_text_is_a_management_claim_and_without_one_an_interpretation():
    sourced = {"rule_id": "r1", "label": "各区域均超 100 万", "status": "pass",
               "assertion_source": {"kind": "text", "reference": {"dataset_id": TEXT, "source_hash": "8" * 64, "paragraph": 1}}}
    written = {"rule_id": "r2", "label": "费用可控", "status": "pass"}
    labels = _labels(consistency_results=[sourced, written])
    assert _one(labels, "assertion", rule_id="r1")["label"] == "management_claim"
    assert _one(labels, "assertion", rule_id="r1")["source_refs"] == [{"dataset_id": TEXT, "source_hash": "8" * 64, "paragraph": 1}]
    assert _one(labels, "assertion", rule_id="r2")["label"] == "analyst_interpretation"


def test_judgment_and_assumption_claims_keep_what_the_writer_said_they_are():
    labels = _labels(claims=[{"basis": "professional_judgment", "reason": "季节性"},
                             {"basis": "user_assumption", "reason": "9 月回款"}])
    assert [entry["label"] for entry in labels] == ["analyst_interpretation", "assumption_user_provided"]


@pytest.mark.parametrize(("basis", "label"), [("user_assumption", "assumption_user_provided"),
                                              ("professional_judgment", "analyst_interpretation")])
def test_an_assumption_or_judgment_that_cites_a_fact_stays_what_the_writer_said(basis, label):
    """Review: a user_assumption claim carrying a fact's run/row/column/value took the fact's 标准化数据 label."""
    claim = {"basis": basis, "fact_id": "1" * 64, "run_id": RUN, "row": 0, "column": "actual", "value": "120",
             "reason": "按合同节点假设回款"}
    labels = _labels(claims=[claim])
    assert labels[0]["label"] == label and labels[0]["base_label"] == label
    assert labels[0]["key"]["fact_id"] == "1" * 64
    assert _one(labels, "fact", fact_id="1" * 64)["label"] == "fact_provider_standardized"
    # The claim is an item of its own, so the assumption is counted rather than folded into the fact.
    assert label_counts(labels) == {"fact_provider_standardized": 1, label: 1}
    # A problem with the cell it cites still shows, over the writer's basis.
    stale = _labels(claims=[claim], older_runs={RUN})[0]
    assert stale["label"] == "stale_source" and stale["base_label"] == label


def test_script_output_or_a_coefficient_recipe_is_unknown_until_a_source_recipe_backs_it():
    """Review: an unverified python run and a coefficient-only recipe were labelled 派生计算 and reached 可决策."""
    script = {**RUNS[SQL_RUN], "id": SQL_RUN, "engine": "python", "reproducibility_status": "unverified"}
    runs = {**RUNS, SQL_RUN: script}
    claim = {"basis": "calculation", "fact_id": "3" * 64, "run_id": SQL_RUN, "row": 0, "column": "total", "value": "5"}
    labels = _labels(claims=[claim], runs=runs)
    assert [labels[0]["label"], _one(labels, "fact", fact_id="3" * 64)["label"]] == ["unknown", "unknown"]
    assert _codes(labels[0]) == ["run_script"]
    assert evidence_posture(labels, PASSED)["level"] == "preliminary"
    # A refreshed, standardized input does not make a script's output traced either.
    refreshed = {**script, "bindings": {"ledger": REFRESH}}
    assert _one(_labels(fact_ids=["3" * 64], runs={**RUNS, SQL_RUN: refreshed}), "fact", fact_id="3" * 64)["label"] == "unknown"

    def recipe(evidence_class):
        return {"status": "pass", "evidence_class": evidence_class, "claim": {"run_id": SQL_RUN, "row": 0, "column": "total"},
                "source_refs": []}

    backed = _one(_labels(fact_ids=["3" * 64], runs=runs, recipe_results=[recipe("source_calculation")]), "fact", fact_id="3" * 64)
    assert backed["label"] == "derived_calculation" and _codes(backed)[0] == "recipe_source_calculation"
    # A recipe that only proves a free coefficient traces nothing, on a script or on SQL,
    coefficient = _one(_labels(fact_ids=["3" * 64], recipe_results=[recipe("coefficient_unbound")]), "fact", fact_id="3" * 64)
    assert coefficient["label"] == "unknown" and _codes(coefficient) == ["recipe_coefficient"]
    # unless a stronger basis applies,
    either = _labels(fact_ids=["3" * 64], recipe_results=[recipe("coefficient_unbound"), recipe("source_value")])
    assert _one(either, "fact", fact_id="3" * 64)["label"] == "fact_source_reported"
    engine = {"status": "pass", "evidence_class": "coefficient_unbound", "claim": {"run_id": RUN, "row": 0, "column": "actual"},
              "source_refs": []}
    assert _one(_labels(fact_ids=["1" * 64], recipe_results=[engine]), "fact", fact_id="1" * 64)["label"] == "fact_provider_standardized"
    # and the decision-grade wording claims no recomputation.
    sql = evidence_posture(_labels(fact_ids=["3" * 64]), PASSED)
    assert sql["level"] == "decision_grade" and "可复算" not in sql["drivers"][0]["text"]


def test_a_row_reading_as_an_estimate_is_inferred_unless_the_requirements_declare_it():
    inferred = _labels(fact_ids=["3" * 64], row_estimates={(SQL_RUN, 0): [{"source": "text", "field": "说明"}]})
    entry = _one(inferred, "fact", fact_id="3" * 64)
    assert entry["label"] == "assumption_inferred" and "说明" in entry["reasons"][0]["text"]
    declared = _labels(fact_ids=["3" * 64], row_estimates={(SQL_RUN, 0): [
        {"source": "declared", "requirements_id": "0" * 32, "item_id": "rev"}, {"source": "row", "field": "basis"}]})
    assert _one(declared, "fact", fact_id="3" * 64)["label"] == "estimate"


def test_an_estimate_location_or_a_factor_recipe_is_an_estimate():
    location = {"run_id": RUN, "row": 0, "column": "actual", "status": "estimated", "evidence": {"evidence_basis": "estimate"}}
    by_location = _labels(requirements={"items": [{"id": "rev", "status": "estimated", "provenance_status": "inputs_verified",
                                                    "locations": [location]}]})
    assert _one(by_location, "fact", fact_id="1" * 64)["label"] == "estimate"
    recipe = {"status": "pass", "evidence_class": "estimate", "claim": {"run_id": RUN, "row": 1, "column": "actual"},
              "source_refs": []}
    assert _one(_labels(fact_ids=["2" * 64], recipe_results=[recipe]), "fact", fact_id="2" * 64)["label"] == "estimate"


def test_an_older_run_or_a_stale_dataset_is_a_stale_source_that_keeps_its_base():
    older = _one(_labels(fact_ids=["1" * 64], older_runs={RUN}), "fact", fact_id="1" * 64)
    assert older["label"] == "stale_source" and older["text"] == "过期来源"
    assert older["base_label"] == "fact_provider_standardized"
    assert _codes(older) == ["older_run", "engine_finance"]
    stale = {**DATASETS, DATA: {**DATASETS[DATA], "freshness": {"state": "source_stale", "reasons": [
        {"code": "superseded", "text": "已被更新的版本取代（同名重新上传或已发布的刷新）"}]}}}
    entry = _one(_labels(fact_ids=["3" * 64], datasets=stale), "fact", fact_id="3" * 64)
    assert entry["label"] == "stale_source" and entry["base_label"] == "derived_calculation"
    assert "8月总账" in entry["reasons"][0]["text"]
    # A period mismatch is not staleness: a run may read last month's file as its comparison baseline.
    mismatch = {**DATASETS, DATA: {**DATASETS[DATA], "freshness": {"state": "period_mismatch", "reasons": []}}}
    assert _one(_labels(fact_ids=["3" * 64], datasets=mismatch), "fact", fact_id="3" * 64)["label"] == "derived_calculation"


def test_contradictions_are_labelled_and_never_averaged_away():
    recipe = {"status": "mismatch", "evidence_class": None, "claim": {"run_id": RUN, "row": 0, "column": "actual"},
              "location": {"sheet": "利润表", "range": "C5"}, "source_refs": []}
    mismatch = _one(_labels(fact_ids=["1" * 64], recipe_results=[recipe]), "fact", fact_id="1" * 64)
    assert mismatch["label"] == "contradicted_source" and mismatch["base_label"] == "fact_provider_standardized"

    claim = {"basis": "calculation", "fact_id": "1" * 64, "run_id": RUN, "row": 0, "column": "actual", "value": "121"}
    labels = _labels(claims=[claim], fact_ids=["1" * 64])
    assert labels[0]["label"] == "contradicted_source" and "fact_claim_mismatch" in _codes(labels[0])
    assert _one(labels, "fact", fact_id="1" * 64)["label"] == "fact_provider_standardized"

    group = {"id": "g", "closure": {"status": "closure_mismatch"}, "members": [{"fact_id": "2" * 64}]}
    assert _one(_labels(fact_ids=["2" * 64], evidence_groups=[group]), "fact", fact_id="2" * 64)["label"] == "contradicted_source"
    assertion = _one(_labels(consistency_results=[{"rule_id": "r", "label": "均超阈值", "status": "mismatch"}]), "assertion", rule_id="r")
    assert assertion["label"] == "contradicted_source" and assertion["base_label"] == "analyst_interpretation"
    revision = {"code": "revision_numeric_regression", "new_run_id": RUN, "column": "actual", "old_value": "120", "new_value": "125",
                "business_key": "revenue"}
    assert _one(_labels(issues=[revision]), "revision")["label"] == "contradicted_source"


def test_each_calculation_claim_is_checked_against_the_run_cell_on_its_own():
    """Review: one mismatching claim on a cell marked every claim on that cell 矛盾来源."""
    runs = {**RUNS, SQL_RUN: {**RUNS[SQL_RUN], "result": {"rows": [{"total": "5.00"}]}}}
    claims = [{"basis": "calculation", "run_id": SQL_RUN, "row": 0, "column": "total", "value": "5"},
              {"basis": "calculation", "run_id": SQL_RUN, "row": 0, "column": "total", "value": "6"}]
    issues = [{"code": "claim_value_mismatch", "run_id": SQL_RUN, "row": 0, "column": "total", "expected": "6", "actual": "5.00"}]
    right, wrong = _labels(claims=claims, issues=issues, runs=runs, facts=[])[:2]
    assert right["label"] == "unknown" and "claim_value_mismatch" not in _codes(right)
    assert wrong["label"] == "contradicted_source" and "claim_value_mismatch" in _codes(wrong)


def test_malformed_source_read_failures_are_read_as_the_requirements_check_reads_them():
    """Review: a non-list value or a non-string item id raised TypeError in the preview and the save."""
    items = [{"id": "rev", "label": "收入", "status": "answered", "provenance_status": "verified", "locations": []}]
    for failures in (5, "rev", [{"requirement_item_id": ["rev"]}], [7, None]):
        assert not [entry for entry in _labels(requirements={"items": items}, source_read_failures=failures)
                    if entry["key"]["kind"] == "requirement"], failures
    failed = _one(_labels(requirements={"items": items}, source_read_failures=[{"item_id": "rev"}]), "requirement")
    assert _codes(failed) == ["requirement_source_failed"]


def test_missing_required_sources_name_what_is_missing():
    issues = [{"code": "missing_required_fact", "fact_id": "2" * 64}]
    uncited = _one(_labels(fact_ids=["1" * 64], issues=issues), "fact", fact_id="2" * 64)
    assert uncited["label"] == "missing_required_source" and uncited["base_label"] == "fact_provider_standardized"
    gone = _one(_labels(fact_ids=["9" * 64]), "fact", fact_id="9" * 64)
    assert gone["label"] == "missing_required_source" and _codes(gone) == ["fact_missing"]
    items = [{"id": "profit", "label": "利润", "status": "pending", "provenance_status": "pending", "locations": []},
             {"id": "rev", "label": "收入", "status": "answered", "provenance_status": "verified", "locations": []}]
    requirement = _one(_labels(requirements={"items": items}), "requirement", requirement_item_id="profit")
    assert requirement["label"] == "missing_required_source"
    assert _codes(requirement) == ["requirement_unanswered", "requirement_source_pending"]
    assert not [entry for entry in _labels(requirements={"items": items}) if entry["key"].get("requirement_item_id") == "rev"]
    unreadable = {"status": "unreadable", "claim": {"run_id": RUN, "row": 0, "column": "actual"}, "source_refs": []}
    assert _one(_labels(fact_ids=["1" * 64], recipe_results=[unreadable]), "fact", fact_id="1" * 64)["label"] == "missing_required_source"
    partial = {"id": "g", "status": "partial", "members": [{"fact_id": "1" * 64}]}
    assert _one(_labels(fact_ids=["1" * 64], evidence_groups=[partial]), "fact", fact_id="1" * 64)["label"] == "missing_required_source"


def test_unknown_is_what_nothing_backs():
    labels = _labels(claims=[{"basis": "source_fact"}, {"basis": "made_up"}],
                     issues=[{"code": "uncited_number", "text": "999", "position": 4}])
    assert [entry["label"] for entry in labels] == ["unknown", "unknown", "unknown"]
    assert _one(labels, "number")["key"] == {"kind": "number", "text": "999", "position": 4}


def test_precedence_shows_the_worst_and_keeps_the_base():
    recipe = {"status": "mismatch", "claim": {"run_id": RUN, "row": 0, "column": "actual"}, "source_refs": []}
    issues = [{"code": "missing_required_fact", "fact_id": "1" * 64}]
    entry = _one(_labels(recipe_results=[recipe], older_runs={RUN}, issues=issues), "fact", fact_id="1" * 64)
    assert entry["label"] == "contradicted_source" and entry["base_label"] == "fact_provider_standardized"
    assert _codes(entry)[:3] == ["recipe_mismatch", "required_fact_uncited", "older_run"]
    entry = _one(_labels(older_runs={RUN}, issues=issues), "fact", fact_id="1" * 64)
    assert entry["label"] == "missing_required_source"


def test_labels_come_in_a_fixed_order_whatever_order_the_records_arrive_in():
    claims = [{"basis": "user_assumption"}, {"basis": "calculation", "fact_id": "3" * 64, "run_id": SQL_RUN, "row": 0,
                                            "column": "total", "value": "5"}]
    issues = [{"code": "uncited_number", "text": "8", "position": 9}, {"code": "uncited_number", "text": "7", "position": 2}]
    first = _labels(claims=claims, fact_ids=["2" * 64, "1" * 64], issues=issues)
    again = _labels(claims=claims, fact_ids=["1" * 64, "2" * 64], issues=issues, facts=list(reversed(FACTS)))
    assert first == again
    kinds = [(entry["key"]["kind"], entry["key"].get("claim_index"), entry["key"].get("fact_id")) for entry in first]
    assert kinds[:5] == [("claim", 0, None), ("claim", 1, "3" * 64), ("fact", None, "1" * 64),
                         ("fact", None, "2" * 64), ("fact", None, "3" * 64)]


# --- posture ---------------------------------------------------------------------------------------------------


def _entry(label: str, index: int) -> dict:
    return {"key": {"kind": "claim", "claim_index": index}, "label": label}


PASSED = {"coverage": {"status": "pass"}, "provenance": {"status": "pass"}}


@pytest.mark.parametrize(("labels", "checks", "level"), [
    (["fact_source_reported", "derived_calculation", "fact_provider_standardized"], PASSED, "decision_grade"),
    (["derived_calculation", "derived_calculation", "analyst_interpretation"], PASSED, "research_grade"),
    (["derived_calculation", "derived_calculation", "estimate"], PASSED, "research_grade"),
    (["derived_calculation", "estimate", "assumption_inferred", "fact_source_reported"], PASSED, "assumption_led"),
    (["derived_calculation", "assumption_user_provided"], PASSED, "assumption_led"),
    (["derived_calculation", "stale_source"], PASSED, "preliminary"),
    (["derived_calculation", "unknown"], PASSED, "preliminary"),
    (["derived_calculation"], {"coverage": {"status": "needs_attention"}, "provenance": {"status": "pass"}}, "preliminary"),
    (["derived_calculation"], {"coverage": {"status": "not_assessed"}, "provenance": {"status": "not_assessed"}}, "preliminary"),
    (["derived_calculation"], {"coverage": {"status": "pass_with_accepted_estimates"},
                               "provenance": {"status": "pass_with_accepted_estimates"}}, "decision_grade"),
    ([], PASSED, "preliminary"),
    (["estimate", "estimate", "contradicted_source"], PASSED, "unsupported"),
    (["fact_source_reported", "missing_required_source"], PASSED, "unsupported"),
])
def test_posture_thresholds(labels, checks, level):
    posture = evidence_posture([_entry(label, index) for index, label in enumerate(labels)], checks)
    assert posture["level"] == level and posture["text"] == POSTURES[level]
    assert posture["rules_version"] == RULES_VERSION == "1"
    assert posture["drivers"] and all(set(driver) == {"code", "text"} for driver in posture["drivers"])


def test_a_claim_and_the_fact_it_cites_count_once_by_the_worse_label():
    labels = [
        {"key": {"kind": "claim", "claim_index": 0, "fact_id": "1" * 64}, "label": "contradicted_source"},
        {"key": {"kind": "fact", "fact_id": "1" * 64}, "label": "derived_calculation"},
        {"key": {"kind": "claim", "claim_index": 1}, "label": "assumption_user_provided"},
        {"key": {"kind": "claim", "claim_index": 2, "fact_id": "2" * 64}, "label": "derived_calculation"},
        {"key": {"kind": "fact", "fact_id": "2" * 64}, "label": "derived_calculation"},
    ]
    assert label_counts(labels) == {"derived_calculation": 1, "assumption_user_provided": 1, "contradicted_source": 1}
    # Without the contradiction there are three items, not five: one assumption is not yet half of them,
    labels[0]["label"] = "derived_calculation"
    assert evidence_posture(labels, PASSED)["counts"] == {"derived_calculation": 2, "assumption_user_provided": 1}
    assert evidence_posture(labels, PASSED)["level"] == "research_grade"
    # and with one cited fact fewer it is.
    assert evidence_posture(labels[:3], PASSED)["level"] == "assumption_led"


# --- dataset freshness (never the clock) -----------------------------------------------------------------------


@pytest.mark.parametrize(("kwargs", "state", "codes"), [
    ({"period": "2026-08", "task_period": "2026-08"}, "current", []),
    ({"period": "2026-07", "task_period": "2026-08"}, "period_mismatch", ["period_differs"]),
    ({"period": "2026", "period_kind": "annual", "task_period": "2026-08"}, "current", []),
    ({"period": "2026-08", "as_of": "2026-08-20", "task_period": "2026-08"}, "source_stale", ["as_of_before_period_end"]),
    ({"period": "2026-08", "as_of": "2026-09-05", "task_period": "2026-08"}, "current", []),
    ({"as_of": "2026-08-31", "period_kind": "as_of", "task_period": "2026-08"}, "current", []),
    ({"as_of": "2026-08-15", "period_kind": "as_of", "task_period": "2026-08"}, "source_stale", ["as_of_before_period_end"]),
    ({"as_of": "2026-07-31", "period_kind": "as_of", "task_period": "2026-08"}, "period_mismatch", ["as_of_before_period"]),
    ({"as_of": "2026-09-30", "period_kind": "as_of", "task_period": "2026-08"}, "period_mismatch", ["as_of_after_period"]),
    ({"period": "2026-08", "task_period": "", "superseded": True}, "source_stale", ["superseded"]),
    ({"period": "2026-07", "task_period": "2026-08", "superseded": True}, "source_stale", ["superseded", "period_differs"]),
    ({"period": "2026-08", "task_period": ""}, "unknown", ["no_task_period"]),
    ({"period": "", "task_period": "2026-08"}, "unknown", ["no_dataset_period"]),
    ({"period": "八月", "task_period": "2026-08"}, "unknown", ["period_unreadable"]),
    ({"period": "2026年8月", "task_period": "2026-08"}, "current", []),
    ({"period": "2026-03", "task_period": "2026-01:2026-08"}, "period_mismatch", ["period_differs"]),
    # Last month's complete file, dated at or after its own close, is another period, never stale.
    ({"period": "2026-08", "as_of": "2026-08-31", "task_period": "2026-09"}, "period_mismatch", ["period_differs"]),
    ({"period": "2026-08", "as_of": "2026-09-03", "task_period": "2026-09"}, "period_mismatch", ["period_differs"]),
    # Cut before its own close: still a mismatch, with the incompleteness said beside it.
    ({"period": "2026-08", "as_of": "2026-08-20", "task_period": "2026-09"}, "period_mismatch",
     ["period_differs", "as_of_before_own_period_end"]),
    # A year-to-date file covers the task month: as of before the month closes, it is stale.
    ({"period": "2026", "as_of": "2026-08-31", "task_period": "2026-09"}, "source_stale", ["as_of_before_period_end"]),
    ({"period": "2026", "as_of": "2026-10-02", "task_period": "2026-09"}, "current", []),
])
def test_dataset_freshness_states(kwargs, state, codes):
    found = dataset_freshness(**{"period": None, "as_of": None, "period_kind": None, "superseded": False, **kwargs})
    assert found["state"] == state
    assert [reason["code"] for reason in found["reasons"]] == codes
    assert all(reason["text"] for reason in found["reasons"])


def test_freshness_reads_no_clock(monkeypatch):
    """A 2020 close with a 2020 file is current, whatever today is; a missing task period stays unknown."""
    import foundry.evidence_labels as labels

    class Exploding:
        @staticmethod
        def today():
            raise AssertionError("the clock is not a business date")

    monkeypatch.setattr(labels, "date", type("FrozenDate", (labels.date,), {"today": Exploding.today}))
    assert dataset_freshness(period=None, as_of="2020-01-31", period_kind="as_of", task_period="2020-01",
                             superseded=False)["state"] == "current"
    assert dataset_freshness(period="2020-01", as_of=None, period_kind="month", task_period=None,
                             superseded=False)["state"] == "unknown"
    assert "now(" not in Path(labels.__file__).read_text() and "today(" not in Path(labels.__file__).read_text()


def test_as_of_comes_from_the_confirmed_title_or_a_refresh_cutoff_and_nothing_else():
    hinted = {"id": "x", "transformation": {"structure": {"declaration": {"scope_hints": {
        "period": "", "granularity": "as_of", "as_of_date": "2026-08-31"}}}}}
    found = _currency(hinted, "", task_period="2026-08", superseded=set())
    assert (found["as_of"], found["as_of_source"], found["period_kind"]) == ("2026-08-31", "title", "as_of")
    assert found["freshness"]["state"] == "current"
    refreshed = {"id": "y", "metadata": {"source_refresh": {"scope": {"period": "2026-08", "cutoff_at": "2026-08-25T00:00:00Z"}}}}
    found = _currency(refreshed, "2026-08", task_period="2026-08", superseded=set())
    assert (found["as_of"], found["as_of_source"], found["period_kind"]) == ("2026-08-25", "source_refresh", "month")
    assert found["freshness"]["state"] == "source_stale"
    # Rows without a period column: the refresh is for its scope's period, and the cutoff completes that period.
    no_column = {"id": "r", "metadata": {"source_refresh": {"scope": {"period": "2026-08", "cutoff_at": "2026-09-05T00:00:00Z"}}}}
    found = _currency(no_column, "", task_period="2026-08", superseded=set())
    assert (found["period"], found["as_of"], found["period_kind"]) == ("2026-08", "2026-09-05", "month")
    assert found["freshness"] == {"state": "current", "reasons": []}
    later = _currency(no_column, "", task_period="2026-09", superseded=set())["freshness"]
    assert later["state"] == "period_mismatch" and [reason["code"] for reason in later["reasons"]] == ["period_differs"]
    no_period = {"id": "s", "metadata": {"source_refresh": {"scope": {"cutoff_at": "2026-09-05T00:00:00Z"}}}}
    found = _currency(no_period, "", task_period="2026-08", superseded=set())
    assert found["period_kind"] is None and found["freshness"]["state"] == "unknown"
    bare = _currency({"id": "z", "created_at": "2026-08-01T00:00:00Z"}, "", task_period="2026-08", superseded=set())
    assert (bare["as_of"], bare["as_of_source"], bare["period_kind"]) == (None, None, None)
    assert bare["freshness"]["state"] == "unknown"
    assert _currency({"id": "z"}, "2026-08", task_period="2026-08", superseded={"z"})["freshness"]["state"] == "source_stale"


# --- readiness report ------------------------------------------------------------------------------------------


def _readiness_task(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="时效")
    return task, AnalysisStore(task), FinanceStore(task)


def _ledger(path: Path, period: str) -> Path:
    path.write_text(f"period,account_code,management_account,amount,currency\n{period},6001,revenue,100,CNY\n", encoding="utf-8")
    return path


def _corrected(path: Path) -> Path:
    path.write_text("period,account_code,management_account,amount,currency\n2026-08,6001,revenue,101,CNY\n", encoding="utf-8")
    return path


def _period(store: FinanceStore, dataset_id: str, period: str = "2026-08") -> None:
    store.analysis_requirements_save({"question": "八月月结", "scope": {"period": period},
                                      "bindings": {"ledger": dataset_id}, "items": []})


def _rows(store: FinanceStore) -> dict[str, dict]:
    return {row["name"]: row for row in store.finance_readiness({})["datasets"]}


def test_readiness_without_a_task_period_says_unknown_instead_of_guessing(tmp_path):
    _task_obj, analysis, store = _readiness_task(tmp_path)
    analysis.add_dataset(_ledger(tmp_path / "aug.csv", "2026-08"), name="8月总账")
    row = _rows(store)["8月总账"]
    assert row["as_of"] is None and row["as_of_source"] is None and row["period_kind"] == "month"
    assert row["freshness"] == {"state": "unknown", "reasons": [
        {"code": "no_task_period", "text": "分析期间还没确认，无法判断时效"}]}


def test_readiness_marks_a_period_mismatch_and_a_current_file(tmp_path):
    _task_obj, analysis, store = _readiness_task(tmp_path)
    august = analysis.add_dataset(_ledger(tmp_path / "aug.csv", "2026-08"), name="8月总账")
    analysis.add_dataset(_ledger(tmp_path / "jul.csv", "2026-07"), name="7月总账")
    _period(store, august["id"])
    rows = _rows(store)
    assert rows["8月总账"]["freshness"] == {"state": "current", "reasons": []}
    assert rows["7月总账"]["freshness"]["state"] == "period_mismatch"
    assert rows["7月总账"]["freshness"]["reasons"][0]["text"] == "资料期间 2026-07 与分析期间 2026-08 不同"


def test_readiness_marks_a_superseded_upload_as_stale(tmp_path):
    _task_obj, analysis, store = _readiness_task(tmp_path)
    old = analysis.add_dataset(_ledger(tmp_path / "v1.csv", "2026-08"), name="8月总账")
    path = tmp_path / "v2.csv"
    path.write_text("period,account_code,management_account,amount,currency\n2026-08,6001,revenue,101,CNY\n", encoding="utf-8")
    new = analysis.add_dataset(path, name="8月总账")
    _period(store, new["id"])
    by_id = {row["dataset_id"]: row for row in store.finance_readiness({})["datasets"]}
    assert by_id[old["id"]]["freshness"]["state"] == "source_stale"
    assert [reason["code"] for reason in by_id[old["id"]]["freshness"]["reasons"]] == ["superseded"]
    assert by_id[new["id"]]["freshness"]["state"] == "current"


def _refresh(task, tmp_path: Path, *, period: str = "2026-08", cutoff: str = "2026-09-05T00:00:00Z", name: str = "ERP 总账",
             amount: int = 20):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["document_id", "line_id", "account_code", "amount"])
    sheet.append(["JV-1", "1", "6001", 100])
    sheet.append(["JV-1", "2", "6001", amount])
    path = tmp_path / f"erp-{period}-{amount}.xlsx"
    book.save(path)
    scope = SourceScope(source_id="erp", tenant_id="t", ledger_id="l", organization_id="o", period=period,
                        currency="CNY", cutoff_at=cutoff)
    return SourceRefreshService(task).refresh_file(path, scope=scope, name=name)


@pytest.mark.parametrize(("task_period", "state"), [("2026-08", "current"), ("2026-09", "period_mismatch")])
def test_a_source_refresh_without_a_period_column_is_judged_by_its_scope_period(tmp_path, task_period, state):
    """Review: the refresh for the task month read as 期间不符 and last month's as 资料过期."""
    task, _analysis, store = _readiness_task(tmp_path)
    refreshed = _refresh(task, tmp_path)
    _period(store, refreshed["dataset_id"], task_period)
    (row,) = store.finance_readiness({})["datasets"]
    assert (row["period"], row["as_of"], row["as_of_source"], row["period_kind"]) == ("2026-08", "2026-09-05", "source_refresh", "month")
    assert row["freshness"]["state"] == state
    assert "as_of_before_period_end" not in [reason["code"] for reason in row["freshness"]["reasons"]]


def test_a_same_named_file_of_another_period_is_a_period_mismatch_not_superseded(tmp_path):
    """Review: monthly packs share sheet and file names; last month's 利润表 read as replaced by this month's."""
    _task_obj, analysis, store = _readiness_task(tmp_path)
    august = analysis.add_dataset(_ledger(tmp_path / "aug.csv", "2026-08"), name="利润表")
    september = analysis.add_dataset(_ledger(tmp_path / "sep.csv", "2026-09"), name="利润表")
    _period(store, september["id"], "2026-09")
    by_id = {row["dataset_id"]: row for row in store.finance_readiness({})["datasets"]}
    assert by_id[september["id"]]["freshness"] == {"state": "current", "reasons": []}
    assert by_id[august["id"]]["freshness"]["state"] == "period_mismatch"
    assert [reason["code"] for reason in by_id[august["id"]]["freshness"]["reasons"]] == ["period_differs"]
    # A corrected August upload still replaces the first August file, and nothing else.
    path = tmp_path / "aug-v2.csv"
    path.write_text("period,account_code,management_account,amount,currency\n2026-08,6001,revenue,101,CNY\n", encoding="utf-8")
    corrected = analysis.add_dataset(path, name="利润表")
    by_id = {row["dataset_id"]: row for row in store.finance_readiness({})["datasets"]}
    assert [reason["code"] for reason in by_id[august["id"]]["freshness"]["reasons"]] == ["superseded", "period_differs"]
    assert by_id[september["id"]]["freshness"]["state"] == "current"
    assert by_id[corrected["id"]]["freshness"]["state"] == "period_mismatch"
    # The draft side reads the same rule.
    found = dataset_currency(analysis, [august["id"], september["id"]], task_period="2026-09")
    assert found[august["id"]]["freshness"]["state"] == "source_stale"
    assert found[september["id"]]["freshness"]["state"] == "current"


def test_a_session_judges_freshness_only_by_the_files_it_may_read(tmp_path):
    task, analysis, store = _readiness_task(tmp_path)
    older = analysis.add_dataset(_ledger(tmp_path / "v1.csv", "2026-08"), name="8月总账")
    analysis.add_dataset(_corrected(tmp_path / "v2.csv"), name="8月总账")
    _period(store, older["id"])
    every = {row["dataset_id"]: row for row in store.finance_readiness({})["datasets"]}
    assert every[older["id"]]["freshness"]["state"] == "source_stale"
    # Granted only the first upload, the session neither opens the newer one nor learns it exists.
    session = FinanceStore(task, snapshot_ids=[older["id"]])
    row = {row["dataset_id"]: row for row in session.finance_readiness({})["datasets"]}[older["id"]]
    assert row["freshness"] == {"state": "current", "reasons": []}
    assert dataset_currency(analysis, [older["id"]], task_period="2026-08", allowed={older["id"]})[older["id"]]["freshness"]["state"] == "current"
    assert dataset_currency(analysis, [older["id"]], task_period="2026-08")[older["id"]]["freshness"]["state"] == "source_stale"


def test_the_assistant_draft_tool_judges_freshness_only_by_the_files_its_session_may_read(tmp_path, capsys):
    task, analysis, store = _readiness_task(tmp_path)
    older = analysis.add_dataset(_ledger(tmp_path / "v1.csv", "2026-08"), name="8月总账")
    _period(store, older["id"])
    task.record_session("sess", role="analysis")
    analysis.add_dataset(_corrected(tmp_path / "v2.csv"), name="8月总账")
    spec = {"title": "八月说明", "body": "收入 100。",
            "claims": [{"basis": "source_fact", "dataset_id": older["id"], "text": "收入 100"}]}
    assert main(["--var", str(tmp_path / "var"), "--session", "sess", "analysis-draft",
                 "--spec", json.dumps(spec, ensure_ascii=False)]) == 0
    check = json.loads(capsys.readouterr().out)["explanation_check"]
    # The newer upload is outside the session: it neither makes the cited file stale nor shows up.
    assert check["dataset_freshness"][older["id"]]["freshness"] == {"state": "current", "reasons": []}
    assert _one(check["evidence_labels"], "claim")["label"] == "fact_source_reported"


def test_a_refresh_outside_the_session_does_not_make_its_prior_snapshot_stale(tmp_path):
    task, analysis, store = _readiness_task(tmp_path)
    first = _refresh(task, tmp_path)
    second = _refresh(task, tmp_path, cutoff="2026-09-06T00:00:00Z", amount=21)
    assert second["dataset_id"] not in {None, first["dataset_id"]}
    assert dataset_currency(analysis, [first["dataset_id"]], task_period="2026-08")[first["dataset_id"]]["freshness"]["state"] == "source_stale"
    alone = dataset_currency(analysis, [first["dataset_id"]], task_period="2026-08", allowed={first["dataset_id"]})
    assert alone[first["dataset_id"]]["freshness"]["state"] != "source_stale"


def test_the_readiness_cli_carries_freshness(tmp_path, capsys):
    task, analysis, store = _readiness_task(tmp_path)
    dataset = analysis.add_dataset(_ledger(tmp_path / "jul.csv", "2026-07"), name="7月总账")
    _period(store, dataset["id"])
    assert main(["--var", str(tmp_path / "var"), "--task", task.id, "finance-readiness"]) == 0
    row = json.loads(capsys.readouterr().out)["datasets"][0]
    assert row["freshness"]["state"] == "period_mismatch" and row["period_kind"] == "month"


# --- drafts: both paths, parity, staleness ---------------------------------------------------------------------


@pytest.fixture
def finance(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="证据标签")
    analysis = AnalysisStore(task)
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{scenario}.json"
        path.write_text(json.dumps([
            {"account_code": code, "management_account": account, "amount": amount, "period": "2026-09"}
            for code, account, amount in zip(("6001", "6401", "6601"), ("revenue", "cost", "expense"), amounts)
        ]))
        bindings[scenario] = analysis.add_dataset(path, name=scenario)["id"]
    store = FinanceStore(task)
    context = store.save_context({"bindings": bindings, "scopes": {
        alias: {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元", "scenario": alias}
        for alias in bindings}})
    store.analysis_requirements_save({"context_id": context["id"], "question": "解释利润",
                                      "items": [{"id": "profit", "metric": "profit", "requires_drilldown": True}]})
    return store, context, tmp_path


def test_a_source_backed_draft_is_decision_grade_and_the_posture_is_not_a_status(finance):
    store, context, _tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]]})
    check = draft["explanation_check"]
    posture = check["evidence_posture"]
    assert posture["level"] == "decision_grade" and posture["text"] == "可决策"
    assert set(posture["counts"]) == {"fact_provider_standardized"}
    assert check["status"] == "pass" and draft["quality"] == check
    # Beside the statuses, never in them: no dimension, check or issue speaks for it.
    assert set(check["status_dimensions"]) == {"execution", "numeric_citation", "source_validation", "professional_review"}
    assert set(check["checks"]) == {"numbers", "coverage", "provenance"}
    assert not [issue for issue in check["issues"] if "label" in str(issue.get("code")) or "posture" in str(issue.get("code"))]
    assert draft["completion"]["issue_fingerprint"] == store.save_explanation_draft(
        {"body": "请再看计算依据。", "run_ids": [run["id"]]})["completion"]["issue_fingerprint"]
    freshness = check["dataset_freshness"]
    assert {row["name"] for row in freshness.values()} == {"actual", "budget"}
    assert {row["freshness"]["state"] for row in freshness.values()} == {"current"}
    assert {row["state"] for row in freshness.values()} == {"current"}
    assert all(row["period"] == "2026-09" for row in freshness.values())


def test_preview_and_saved_draft_agree(finance):
    store, context, _tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    draft = store.save_explanation_draft({
        "body": "利润超预算，另有 999 万元待确认。", "run_ids": [run["id"]],
        "claims": [{"basis": "user_assumption", "reason": "9 月回款按合同节点"},
                   {"basis": "professional_judgment", "reason": "季节性"}],
    })
    preview = store.validate_explanation({"draft_id": draft["id"]})
    for key in ("evidence_labels", "evidence_posture", "dataset_freshness"):
        assert preview[key] == draft["explanation_check"][key], key
    assert any(entry["key"]["kind"] == "number" for entry in preview["evidence_labels"])
    assert preview["evidence_posture"]["level"] == "preliminary"


def test_labels_or_a_posture_the_caller_sends_are_ignored(finance, capsys):
    store, context, tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    forged = {"evidence_labels": [{"key": {"kind": "claim", "claim_index": 0}, "label": "fact_source_reported"}],
              "evidence_posture": {"level": "decision_grade", "text": "可决策"},
              "dataset_freshness": {"x": {"freshness": {"state": "current"}}}}
    claim = {"basis": "user_assumption", "reason": "按合同", "label": "fact_source_reported"}
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]], "claims": [claim], **forged})
    check = draft["explanation_check"]
    assumption = next(entry for entry in check["evidence_labels"] if entry["key"].get("basis") == "user_assumption")
    assert assumption["label"] == "assumption_user_provided"
    assert check["evidence_posture"]["level"] == "research_grade"
    assert "x" not in check["dataset_freshness"]
    task_id = store.task.id
    assert main(["--var", str(tmp / "var"), "--task", task_id, "validate-explanation", "--spec",
                 json.dumps({"draft_id": draft["id"], **forged})]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["evidence_posture"] == check["evidence_posture"]
    assert preview["evidence_labels"] == check["evidence_labels"]


def test_a_draft_citing_an_older_run_of_the_same_calculation_is_stale(finance):
    store, context, _tmp = finance
    old = store.explain_variance({"context_id": context["id"]})
    store.analysis.run_analysis(old["analysis_id"])
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [old["id"]]})
    facts = [entry for entry in draft["explanation_check"]["evidence_labels"] if entry["key"]["kind"] == "fact"]
    assert facts and all(entry["label"] == "stale_source" for entry in facts)
    assert all(entry["base_label"] == "fact_provider_standardized" for entry in facts)
    assert draft["explanation_check"]["evidence_posture"]["level"] == "preliminary"
    assert {"code": "stale_source", "text": f"过期来源 {len(facts)} 项"} in draft["explanation_check"]["evidence_posture"]["drivers"]


def test_rerunning_the_same_public_finance_call_makes_the_earlier_run_stale(finance):
    store, context, _tmp = finance
    first = store.explain_variance({"context_id": context["id"]})
    again = store.explain_variance({"context_id": context["id"]})
    # Each public call files its own revision; the calculation is the same.
    assert first["analysis_id"] != again["analysis_id"] and first["code_hash"] == again["code_hash"]
    stale = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [first["id"]]})
    assert {entry["label"] for entry in stale["explanation_check"]["evidence_labels"] if entry["key"]["kind"] == "fact"} == {"stale_source"}
    current = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [again["id"]]})
    assert "stale_source" not in {entry["label"] for entry in current["explanation_check"]["evidence_labels"]}
    # A different calculation on the same context is not a rerun of this one.
    metric = store.run_metric({"context_id": context["id"], "metric": {"kind": "gross_profit"}})
    assert metric["code_hash"] != again["code_hash"]
    assert "stale_source" not in {entry["label"] for entry in
                                  store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [again["id"]]})["explanation_check"]["evidence_labels"]}


def test_a_sourced_assertion_on_a_replaced_file_is_a_stale_source(tmp_path):
    from foundry.evidence_labels import draft_evidence

    _task, analysis, _store = _readiness_task(tmp_path)
    older = analysis.add_dataset(_ledger(tmp_path / "v1.csv", "2026-08"), name="经营说明")
    analysis.add_dataset(_corrected(tmp_path / "v2.csv"), name="经营说明")
    result = {"rule_id": "r1", "label": "均超阈值", "status": "pass",
              "assertion_source": {"kind": "text", "reference": {"dataset_id": older["id"], "paragraph": 1}}}
    found = draft_evidence(analysis, {"facts": [], "checks": {}}, claims=[], fact_ids=[], runs={},
                           evidence_report={}, consistency_report={"results": [result]})
    assertion = _one(found["evidence_labels"], "assertion", rule_id="r1")
    assert assertion["label"] == "stale_source" and assertion["base_label"] == "management_claim"
    assert older["id"] in found["dataset_freshness"]
    assert _one(_labels(consistency_results=[result], datasets={older["id"]: {"name": "经营说明", "freshness": {"state": "current"}}}),
                "assertion", rule_id="r1")["label"] == "management_claim"


def test_a_draft_on_a_run_that_read_a_superseded_snapshot_is_stale(finance):
    store, context, tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    path = tmp / "actual-v2.json"
    path.write_text(json.dumps([{"account_code": "6001", "management_account": "revenue", "amount": 121, "period": "2026-09"}]))
    store.analysis.add_dataset(path, name="actual")
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]]})
    actual_id = run["bindings"]["actual"]
    assert draft["explanation_check"]["dataset_freshness"][actual_id]["freshness"]["state"] == "source_stale"
    fact = next(entry for entry in draft["explanation_check"]["evidence_labels"] if entry["key"]["kind"] == "fact")
    assert fact["label"] == "stale_source" and "actual" in fact["reasons"][0]["text"]


def test_a_draft_on_last_months_refresh_is_a_period_mismatch_not_a_stale_source(tmp_path):
    task, analysis, store = _readiness_task(tmp_path)
    refreshed = _refresh(task, tmp_path)
    saved = analysis.save_analysis({"question": "合计", "sql": "SELECT SUM(CAST(amount AS DECIMAL(18,2))) AS total FROM ledger",
                                    "bindings": {"ledger": refreshed["dataset_id"]}})
    run = analysis.run_analysis(saved["id"])
    _period(store, refreshed["dataset_id"], "2026-09")
    draft = store.save_explanation_draft({"body": "合计见计算依据。", "run_ids": [run["id"]], "claims": [
        {"basis": "calculation", "run_id": run["id"], "row": 0, "column": "total", "value": run["result"]["rows"][0]["total"]}]})
    check = draft["explanation_check"]
    assert check["dataset_freshness"][refreshed["dataset_id"]]["state"] == "period_mismatch"
    assert check["dataset_freshness"][refreshed["dataset_id"]]["period"] == "2026-08"
    assert not [entry for entry in check["evidence_labels"] if entry["label"] == "stale_source"]
    assert {entry["label"] for entry in check["evidence_labels"]} == {"derived_calculation"}


def test_an_assumption_claim_on_a_fact_keeps_the_draft_from_decision_grade(finance):
    store, context, _tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    fact = store.prepare_explanation({"run_ids": [run["id"]]})["facts"][0]
    claim = {"basis": "user_assumption", "reason": "按合同节点假设回款", "fact_id": fact["id"],
             **{key: fact[key] for key in ("run_id", "row", "column", "value")}}
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]], "claims": [claim]})
    posture = draft["explanation_check"]["evidence_posture"]
    assert posture["level"] == "research_grade" and posture["counts"]["assumption_user_provided"] == 1
    assert store.validate_explanation({"draft_id": draft["id"]})["evidence_posture"] == posture


def test_malformed_source_read_failures_do_not_break_the_preview_or_the_cli(finance, capsys):
    store, context, tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]]})
    assert store.validate_explanation({"draft_id": draft["id"], "source_read_failures": [{"requirement_item_id": ["x"]}]})["evidence_posture"]
    assert main(["--var", str(tmp / "var"), "--task", store.task.id, "validate-explanation", "--spec",
                 json.dumps({"draft_id": draft["id"], "source_read_failures": 5})]) == 0
    assert json.loads(capsys.readouterr().out)["evidence_posture"]["level"]


def test_assistant_and_manager_read_the_same_labels(finance, capsys):
    store, context, tmp = finance
    run = store.explain_variance({"context_id": context["id"]})
    draft = store.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]]})
    answers = []
    for actor in ("assistant", "manager"):
        assert main(["--var", str(tmp / "var"), "--task", store.task.id, "--actor", actor, "validate-explanation",
                     "--spec", json.dumps({"draft_id": draft["id"]})]) == 0
        answers.append(json.loads(capsys.readouterr().out)["evidence_posture"])
    assert answers[0] == answers[1] == draft["explanation_check"]["evidence_posture"]


# --- the label map the app shows -------------------------------------------------------------------------------


def _ts_map(source: str, name: str) -> dict[str, str]:
    block = re.search(rf"export const {name}[^=]*=\s*\{{(.*?)\}}", source, re.S)
    assert block, name
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))


def test_the_app_label_map_is_this_one():
    source = (ROOT / "app" / "src" / "views" / "analysis" / "evidenceLabels.ts").read_text(encoding="utf-8")
    assert _ts_map(source, "EVIDENCE_LABELS") == LABELS
    assert list(_ts_map(source, "EVIDENCE_LABELS")) == list(LABELS)
    assert _ts_map(source, "EVIDENCE_POSTURES") == POSTURES
    assert _ts_map(source, "FRESHNESS_TEXT") == FRESHNESS
