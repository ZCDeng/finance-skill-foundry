from __future__ import annotations

import pytest

from foundry.finance_close_status import close_status

SCOPE = {"period": "2026-08", "organization": "华宸物业", "unit": "万元", "currency": "CNY"}
DATASETS = [{"id": "d1", "name": "月结", "source_hash": "a" * 64}]
PASSING = {"state": "confirmed", "control": {"label": "坏账分项"}, "result": {"status": "pass"}, "issue": None}
RUN = {"execution_status": "succeeded", "seq": 10}
CLEAN_DRAFT = {"seq": 11, "explanation_check": {"status_dimensions": {
    "execution": {"status": "pass"}, "numeric_citation": {"status": "pass"},
    "source_validation": {"status": "pass"}, "professional_review": {"status": "unreviewed"}}}}


def _status(**overrides):
    facts = dict(archived=False, scope=SCOPE, scope_seq=5, datasets=DATASETS, superseded=0, pending_structures=[],
                 controls=[PASSING], runs=[RUN], draft=CLEAN_DRAFT)
    facts.update(overrides)
    return close_status(**facts)


def _break(state, *, blocking=True, status="break"):
    return {"state": "confirmed", "control": {"label": "坏账分项"}, "result": {"status": status, "difference": "11655"},
            "issue": {"state": state, "blocking": blocking, "disposition": {"reason": "已知"}}}


def test_everything_the_system_checks_clear_reads_ready_for_the_manager_never_done():
    headline = _status()["headline"]
    assert headline == {"state": "ready_for_review", "text": "可提交经理复核"}
    assert "完成" not in headline["text"] and "通过" not in headline["text"]


@pytest.mark.parametrize("missing", ["period", "organization", "unit", "currency"])
def test_a_scope_field_left_blank_holds_everything(missing):
    result = _status(scope={**SCOPE, missing: ""})
    assert result["headline"]["state"] == "not_ready"
    assert result["headline"]["text"] == "尚未准备：还有 1 项必须确认"


def test_no_files_and_unconfirmed_structures_are_not_ready():
    assert _status(datasets=[])["headline"]["state"] == "not_ready"
    assert _status(pending_structures=["月结"])["headline"]["text"] == "尚未准备：还有 1 项必须确认"


def test_ready_to_calculate_before_anything_has_run():
    assert _status(runs=[], draft=None)["headline"] == {"state": "calculable", "text": "可计算：范围和结构已确认"}
    assert _status(runs=[{"execution_status": "failed", "seq": 3}], draft=None)["headline"]["state"] == "calculable"


def test_ready_to_calculate_still_names_the_differences_that_will_hold_the_close():
    result = _status(runs=[], draft=None, controls=[_break("open"), _break("pending_external"), _break("waived", blocking=False)])
    assert result["headline"] == {"state": "calculable", "text": "可计算：范围和结构已确认",
                                  "detail": "2 项差异仍挡住月结，处理完才能提交复核"}
    assert "detail" not in _status(runs=[], draft=None)["headline"]


def test_differences_still_open_say_how_many_source_conflicts_remain():
    result = _status(controls=[_break("open"), _break("pending_external")])
    assert result["headline"] == {"state": "needs_review", "text": "需要复核：计算完成，但有 2 项来源冲突"}


@pytest.mark.parametrize("state", ["open", "pending_external", "awaiting_reimport", "awaiting_review"])
def test_every_undecided_or_waiting_difference_holds_the_close(state):
    assert _status(controls=[_break(state)])["headline"]["state"] == "needs_review"


def test_an_accepted_difference_no_longer_holds_it_but_stays_visible():
    result = _status(controls=[_break("waived", blocking=False)])
    assert result["headline"]["state"] == "ready_for_review"
    exceptions = next(block for block in result["blocks"] if block["key"] == "exceptions")
    assert exceptions["state"] == "attention" and "已接受差异（已知）" in exceptions["items"][0]["text"]


@pytest.mark.parametrize("state", ["stale", "not_run"])
def test_a_control_on_old_data_or_never_run_is_not_an_old_green(state):
    row = {"state": "confirmed", "control": {"label": "坏账分项"}, "result": {"status": "stale"} if state == "stale" else None,
           "issue": {"state": state, "blocking": True}}
    assert _status(controls=[row])["headline"]["state"] == "needs_review"


def test_no_confirmed_control_means_nothing_has_been_tied_out():
    assert _status(controls=[])["headline"]["state"] == "needs_review"
    proposed = {**PASSING, "state": "proposed"}
    assert _status(controls=[proposed])["headline"]["state"] == "needs_review"


@pytest.mark.parametrize("dimension,status", [
    ("execution", "failed"), ("numeric_citation", "needs_attention"), ("source_validation", "needs_attention"),
    ("source_validation", "not_configured"), ("numeric_citation", "not_configured"),
])
def test_executed_is_not_cited_and_cited_is_not_sourced(dimension, status):
    draft = {"seq": 11, "explanation_check": {"status_dimensions": {
        **CLEAN_DRAFT["explanation_check"]["status_dimensions"], dimension: {"status": status}}}}
    assert _status(draft=draft)["headline"]["state"] == "needs_review"


def test_a_draft_older_than_the_latest_calculation_or_missing_holds_it():
    assert _status(draft={**CLEAN_DRAFT, "seq": 9})["headline"]["state"] == "needs_review"
    assert _status(draft=None)["headline"]["state"] == "needs_review"


def test_a_scope_changed_after_the_calculation_asks_for_a_rerun():
    result = _status(scope_seq=12)
    assert result["headline"]["state"] == "needs_review"
    assert "范围在上次计算之后改过，请重新计算" in result["blocking"]


def test_an_archived_task_says_so_whatever_it_held():
    assert _status(archived=True, controls=[_break("open")])["headline"]["state"] == "archived"


def test_six_blocks_in_order_and_the_professional_review_is_left_to_a_person():
    result = _status()
    assert [block["label"] for block in result["blocks"]] == ["范围", "来源", "结构", "控制", "异常", "复核"]
    review = result["blocks"][-1]
    assert review["items"][-1]["text"] == "经理尚未复核（提交后由经理完成）" and not review["items"][-1]["blocking"]


def test_the_store_answers_for_a_task_with_nothing_in_it(tmp_path):
    from foundry.finance_service import FinanceStore
    from foundry.task import TaskStore

    task = TaskStore(tmp_path / "var").create(title="空")
    status = FinanceStore(task).finance_close_status({})
    assert status["headline"]["state"] == "not_ready"
    assert "还没有资料" in status["blocking"]


def test_a_control_that_cannot_be_read_holds_the_close_after_correction_is_chosen():
    row = {"state": "confirmed", "control": {"label": "坏账分项"}, "result": {"status": "error"},
           "issue": {"state": "awaiting_reimport", "blocking": True}}
    result = _status(controls=[row])
    assert result["headline"]["state"] == "needs_review"
    assert "坏账分项：读不出，待重新导入修正后的资料" in result["blocking"]
    # A read failure is not a source conflict.
    assert "来源冲突" not in result["headline"]["text"]


def test_a_file_added_after_the_calculation_asks_for_a_rerun():
    result = _status(datasets=[*DATASETS, {"id": "d2", "name": "新资料", "source_hash": "b" * 64, "seq": 30}])
    assert "上次计算之后又加了资料，请重新计算" in result["blocking"]


def test_a_calculation_on_a_replaced_snapshot_asks_for_a_rerun():
    result = _status(runs=[{**RUN, "id": "r1", "bindings": {"actual": "old"}}], replaced={"old"},
                     draft={**CLEAN_DRAFT, "run_ids": ["r1"]})
    assert result["headline"]["state"] == "needs_review"
    assert "最近一次计算读的是已被更新的旧资料，请重新计算" in result["blocking"]


def test_a_draft_citing_an_older_run_of_the_same_calculation_holds_it():
    runs = [{"id": "r0", "analysis_id": "a", "execution_status": "succeeded", "seq": 4},
            {"id": "r1", "analysis_id": "a", "execution_status": "succeeded", "seq": 10}]
    assert _status(runs=runs, draft={**CLEAN_DRAFT, "run_ids": ["r0"]})["headline"]["state"] == "needs_review"
    assert _status(runs=runs, draft={**CLEAN_DRAFT, "run_ids": ["r1"]})["headline"]["state"] == "ready_for_review"


def test_the_conflict_count_counts_only_differences():
    result = _status(controls=[_break("open")], draft=None)
    assert result["headline"]["text"] == "需要复核：计算完成，但还有 2 项待处理"


@pytest.mark.parametrize("value", [["", " "], "   ", [], {}, None])
def test_a_scope_field_that_names_nothing_is_not_confirmed(value):
    assert _status(scope={**SCOPE, "organization": value})["headline"]["state"] == "not_ready"


def test_organization_is_not_asked_of_files_that_name_none():
    assert _status(scope={**SCOPE, "organization": ""}, organization_required=False)["headline"]["state"] == "ready_for_review"
    assert _status(scope={**SCOPE, "organization": ["华东", ""]})["headline"]["state"] == "ready_for_review"


def test_a_failed_run_after_the_last_success_is_flagged():
    result = _status(runs=[RUN, {"execution_status": "failed", "seq": 11}], draft={**CLEAN_DRAFT, "seq": 12})
    review = result["blocks"][-1]
    assert any(item["text"] == "最近一次计算没有成功" for item in review["items"])
