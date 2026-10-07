from __future__ import annotations

import re

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
    assert result["headline"]["text"] == "尚未准备：还有 1 项待处理"


def test_no_files_and_unconfirmed_structures_are_not_ready():
    assert _status(datasets=[])["headline"]["state"] == "not_ready"
    assert _status(pending_structures=["月结"])["headline"]["text"] == "尚未准备：还有 1 项待处理"


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


def test_a_file_a_roll_forward_places_in_another_month_asks_for_no_rerun():
    copy = {"id": "d2", "name": "月结（2026-10 滚动）.xlsx", "source_hash": "b" * 64, "seq": 30}
    result = _status(datasets=[*DATASETS, copy], other_months={copy["source_hash"]})
    assert "上次计算之后又加了资料，请重新计算" not in result["blocking"]


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


def test_the_headline_counts_every_row_the_open_blocks_hold():
    # The QA pack: no period, two structures waiting, no confirmed control, a draft older than the run.
    result = _status(scope={**SCOPE, "period": ""}, pending_structures=["月结", "台账"], controls=[],
                     draft={**CLEAN_DRAFT, "seq": 9})
    assert result["headline"] == {"state": "not_ready", "text": "尚未准备：还有 5 项待处理"}
    rows = [item["text"] for block in result["blocks"] for item in block["items"] if item["blocking"]]
    assert result["blocking"] == rows == [
        "期间未确认", "月结 的表结构等你确认", "台账 的表结构等你确认", "还没有确认的勾稽控制", "文稿早于最新一次计算，请按新结果更新"]
    # The conclusion still answers from the inputs and the missing controls, apart from the headline.
    assert [reason["text"] for reason in result["conclusion"]["reasons"]] == [
        "期间未确认", "月结 的表结构等你确认", "台账 的表结构等你确认", "还没有你确认的勾稽控制"]


@pytest.mark.parametrize("facts", [
    dict(scope={**SCOPE, "unit": ""}),
    dict(datasets=[], runs=[], draft=None),
    dict(scope={**SCOPE, "period": ""}, pending_structures=["月结"], controls=[], draft=None),
    dict(controls=[]),
    dict(controls=[_break("open"), _break("pending_external")]),
    dict(controls=[_break("open")], draft=None),
    dict(scope_seq=12, draft={**CLEAN_DRAFT, "seq": 9}),
], ids=["scope", "no-files", "everything", "no-control", "conflicts", "conflict-and-draft", "rerun-and-draft"])
def test_the_headline_number_is_the_blocking_list(facts):
    result = _status(**facts)
    assert result["headline"]["state"] in {"not_ready", "needs_review"}
    number = int(re.search(r"(\d+) 项", result["headline"]["text"]).group(1))
    held = sum(1 for block in result["blocks"] if block["state"] == "blocked" for item in block["items"] if item["blocking"])
    assert number == len(result["blocking"]) == held


def test_a_source_row_is_the_file_name_and_its_digest_only_a_hint():
    source = _status()["blocks"][1]["items"][0]
    assert source["text"] == "月结" and "摘要" not in source["text"]
    assert source["hint"] == "摘要 aaaaaaaaaaaa"
    unhashed = _status(datasets=[{"id": "d1", "name": "月结"}])["blocks"][1]["items"][0]
    assert unhashed["text"] == "月结" and "hint" not in unhashed


# ---- 可用结论: whether the books as they stand can be used, beside the headline -----------------

BOOK = {"id": "b1", "name": "月结套表.xlsx", "source_hash": "b" * 64, "source_file": "source.xlsx"}
LEDGER = {"id": "b2", "name": "合同台账.xlsx", "source_hash": "c" * 64, "source_file": "source.xlsx"}


def _on(row, left="b1", right="b1"):
    return {**row, "control": {**row["control"], "left": {"dataset_id": left}, "right": {"dataset_id": right}}}


def _typed(row, finding_type="source_conflict", label="来源矛盾", *, by_manager=True):
    finding = ({"set_by_manager": True, "type": finding_type, "type_label": label} if by_manager
               else {"set_by_manager": False, "suggested_type": finding_type, "suggested_type_label": label})
    return {**row, "finding": finding}


def _words(conclusion):
    return [conclusion["text"], *(reason["text"] for reason in conclusion["reasons"]),
            *(text for book in conclusion["workbooks"] for text in (book["text"], *(reason["text"] for reason in book["reasons"])))]


def test_every_confirmed_control_passing_is_usable_and_the_headline_is_unchanged():
    result = _status()
    assert result["headline"] == {"state": "ready_for_review", "text": "可提交经理复核"}
    assert result["conclusion"] == {
        "level": "usable", "text": "可用", "reasons": [{"text": "你确认的 1 条控制相符", "target": "controls"}],
        "basis": {"confirmed": 1, "passed": 1, "waived": 0, "open": 0}, "workbooks": [],
    }


@pytest.mark.parametrize("controls,why", [
    ([], "还没有你确认的勾稽控制"),
    ([{**PASSING, "state": "proposed"}], "还没有你确认的勾稽控制"),
    ([PASSING, {"state": "confirmed", "control": {"label": "台账"}, "result": None, "issue": {"state": "not_run", "blocking": True}}], "1 条控制已确认但还没运行"),
    ([{"state": "confirmed", "control": {"label": "台账"}, "result": {"status": "stale"}, "issue": {"state": "stale", "blocking": True}}], "1 条控制还读着旧版本资料：在新版本上确认对应控制后，把旧的停用"),
    ([_break("awaiting_reimport", status="error")], "坏账分项 读不出数"),
])
def test_without_a_confirmed_current_reading_the_answer_is_not_assessable(controls, why):
    conclusion = _status(controls=controls)["conclusion"]
    assert conclusion["level"] == "not_assessable" and conclusion["text"] == "无法判断"
    assert why in [reason["text"] for reason in conclusion["reasons"]]


def test_inputs_still_unconfirmed_make_it_not_assessable_and_say_which():
    conclusion = _status(scope={**SCOPE, "period": ""}, pending_structures=["月结"], controls=[_break("open")])["conclusion"]
    assert conclusion["level"] == "not_assessable"
    assert conclusion["reasons"][:2] == [{"text": "期间未确认", "target": "scope"}, {"text": "月结 的表结构等你确认", "target": "structure"}]
    assert _status(datasets=[])["conclusion"]["reasons"][0] == {"text": "还没有资料", "target": "datasets"}


@pytest.mark.parametrize("state", ["open", "pending_external", "awaiting_reimport", "awaiting_review"])
def test_a_difference_still_held_makes_the_books_not_usable(state):
    conclusion = _status(controls=[PASSING, _typed(_break(state))])["conclusion"]
    assert conclusion["level"] == "not_usable" and conclusion["text"] == "不可用"
    from foundry.finance_close_status import ISSUE_TEXT

    assert conclusion["reasons"] == [{"text": f"坏账分项：差额 11655，来源矛盾，{ISSUE_TEXT[state]}", "target": "controls"}]
    assert conclusion["basis"] == {"confirmed": 2, "passed": 1, "waived": 0, "open": 1}


def test_an_assistant_suggestion_names_no_type_and_moves_no_level():
    suggested = _status(controls=[_typed(_break("open"), by_manager=False)])["conclusion"]
    assert suggested["reasons"][0]["text"] == "坏账分项：差额 11655，未定类型，差异待处理"
    # A type, the manager's or the assistant's, never lifts a difference out of the way.
    for row in (_typed(_break("open")), _typed(_break("open"), "basis_difference", "口径不同"), _break("open")):
        assert _status(controls=[row])["conclusion"]["level"] == "not_usable"
    assert _status(controls=[_typed(_break("waived", blocking=False))])["conclusion"]["level"] == "usable_with_caveats"


def test_a_break_nobody_has_cleared_counts_against_the_books_whatever_its_issue_says():
    untold = {"state": "confirmed", "control": {"label": "坏账分项"}, "result": {"status": "break", "difference": "1"}, "issue": None}
    assert _status(controls=[untold])["conclusion"]["level"] == "not_usable"


def test_an_accepted_difference_leaves_the_books_usable_with_caveats_named():
    waived = _typed(_break("waived", blocking=False), "basis_difference", "口径不同")
    conclusion = _status(controls=[PASSING, waived, _break("waived", blocking=False)])["conclusion"]
    assert conclusion["level"] == "usable_with_caveats" and conclusion["text"] == "带保留可用"
    assert [reason["text"] for reason in conclusion["reasons"]] == [
        "坏账分项：差额 11655，口径不同，已接受差异（已知）", "坏账分项：差额 11655，未定类型，已接受差异（已知）"]
    assert conclusion["basis"] == {"confirmed": 3, "passed": 1, "waived": 2, "open": 0}


def test_each_workbook_is_judged_by_the_controls_that_read_it():
    derived = {**BOOK, "id": "t1", "name": "月结套表 · 08·AR", "metadata": {"derived_from": "b1"}, "transformation": {"structure": {}}}
    csv = {"id": "c1", "name": "科目余额.csv", "source_hash": "d" * 64, "source_file": "source.csv"}
    other = {"id": "b3", "name": "银行流水.xlsx", "source_hash": "e" * 64, "source_file": "source.xlsx"}
    across = _typed(_on(_break("open"), "b2", "b1"))
    result = _status(datasets=[derived, BOOK, LEDGER, csv, other], controls=[_on(PASSING), across])
    books = {book["name"]: book for book in result["conclusion"]["workbooks"]}
    # One line per Excel file: the derived table is the same file, a CSV is not a workbook.
    assert list(books) == ["月结套表.xlsx", "合同台账.xlsx", "银行流水.xlsx"]
    assert books["月结套表.xlsx"]["dataset_id"] == "b1"
    # A tie-out across two workbooks counts against both.
    for name in ("月结套表.xlsx", "合同台账.xlsx"):
        assert books[name]["level"] == "not_usable"
        assert books[name]["reasons"] == [{"text": "坏账分项：差额 11655，来源矛盾，差异待处理", "target": "controls"}]
    assert books["银行流水.xlsx"] == {"dataset_id": "b3", "name": "银行流水.xlsx", "level": "not_assessable", "text": "无法判断",
                                    "reasons": [{"text": "还没有你确认的勾稽控制读到这本工作簿", "target": "controls"}]}
    # Once accepted, the pack and both workbooks it reads are usable with that caveat; the other passes on its own.
    accepted = _on(_break("waived", blocking=False), "b2", "b1")
    books = {book["name"]: book for book in _status(datasets=[BOOK, LEDGER], controls=[_on(PASSING, "b1", "b1"), accepted])["conclusion"]["workbooks"]}
    assert books["月结套表.xlsx"]["level"] == books["合同台账.xlsx"]["level"] == "usable_with_caveats"
    only_ledger = _status(datasets=[BOOK, LEDGER], controls=[_on(PASSING, "b2", "b2"), _on(_break("open"), "b1", "b1")])["conclusion"]
    assert {book["name"]: book["text"] for book in only_ledger["workbooks"]} == {"月结套表.xlsx": "不可用", "合同台账.xlsx": "可用"}
    assert only_ledger["text"] == "不可用"


def test_a_workbook_no_control_reads_keeps_the_pack_from_being_called_usable():
    # One passing control on the 月结套表 says nothing about the 合同台账 beside it.
    conclusion = _status(datasets=[BOOK, LEDGER], controls=[_on(PASSING, "b1", "b1")])["conclusion"]
    assert conclusion["level"] == "not_assessable" and conclusion["text"] == "无法判断"
    assert conclusion["reasons"] == [{"text": "合同台账.xlsx 还没有你确认的勾稽控制读到", "target": "controls"}]
    assert [(book["name"], book["text"]) for book in conclusion["workbooks"]] == [("月结套表.xlsx", "可用"), ("合同台账.xlsx", "无法判断")]
    # A tie-out across both reads both, and with nothing confirmed the pack names that once, not per workbook.
    assert _status(datasets=[BOOK, LEDGER], controls=[_on(PASSING, "b1", "b2")])["conclusion"]["level"] == "usable"
    assert _status(datasets=[BOOK, LEDGER], controls=[])["conclusion"]["reasons"] == [{"text": "还没有你确认的勾稽控制", "target": "controls"}]


def test_a_workbook_a_roll_forward_places_in_another_month_is_not_one_the_pack_waits_on():
    copy = {"id": "c1", "name": "月结套表（2026-09 滚动）.xlsx", "source_hash": "d" * 64, "source_file": "source.xlsx"}
    table = {**BOOK, "id": "t1", "name": "利润表", "metadata": {"derived_from": "b1"}}
    conclusion = _status(datasets=[BOOK, table, copy], controls=[_on(PASSING, "c1", "c1")],
                         other_months={BOOK["source_hash"]})["conclusion"]
    assert conclusion["level"] == "usable"
    assert [book["dataset_id"] for book in conclusion["workbooks"]] == ["c1"]
    # A control that reads it keeps it listed, so what that control finds shows under its own name.
    listed = _status(datasets=[BOOK, copy], controls=[_on(PASSING, "c1", "c1"), _on(PASSING, "b1", "b1")],
                     other_months={BOOK["source_hash"]})["conclusion"]["workbooks"]
    assert [book["dataset_id"] for book in listed] == ["b1", "c1"]
    # Without the roll-forward, the same workbook is one the pack still waits on.
    assert _status(datasets=[BOOK, copy], controls=[_on(PASSING, "c1", "c1")])["conclusion"]["level"] == "not_assessable"


def test_several_passing_controls_read_as_all_agreeing():
    reasons = _status(controls=[PASSING, PASSING])["conclusion"]["reasons"]
    assert reasons == [{"text": "你确认的 2 条控制都相符", "target": "controls"}]


def test_a_table_left_from_a_replaced_workbook_is_not_listed_as_a_workbook():
    # v1 was replaced by a new upload under the same name; its 区域收入 table, named after the sheet,
    # is still current because v2 renamed that sheet, but it is not a workbook of its own.
    new = {**BOOK, "id": "b9", "source_hash": "f" * 64}
    orphan = {**BOOK, "id": "t1", "name": "01·区域收入", "metadata": {"derived_from": "b1"}, "transformation": {"structure": {}}}
    result = _status(datasets=[orphan, new], replaced={"b1"}, controls=[_on(PASSING, "b9", "b9")])
    assert [(book["dataset_id"], book["name"], book["text"]) for book in result["conclusion"]["workbooks"]] == [("b9", "月结套表.xlsx", "可用")]
    # While its workbook is current, the same table still stands for it when it is all the session holds.
    assert [book["dataset_id"] for book in _status(datasets=[orphan], controls=[_on(PASSING, "t1", "t1")])["conclusion"]["workbooks"]] == ["t1"]


def test_a_control_left_on_a_replaced_workbook_says_both_steps_while_the_new_one_passes():
    new = {**BOOK, "id": "b9", "source_hash": "f" * 64}
    stale = _on({"state": "confirmed", "control": {"label": "坏账分项"}, "result": {"status": "stale"},
                 "issue": {"state": "stale", "blocking": True}}, "b1", "b1")
    conclusion = _status(datasets=[new], replaced={"b1"}, controls=[stale, _on(PASSING, "b9", "b9")])["conclusion"]
    # Re-confirming on the new file is done; what still holds the pack is the old control nobody retired.
    assert conclusion["level"] == "not_assessable"
    assert conclusion["reasons"] == [{"text": "1 条控制还读着旧版本资料：在新版本上确认对应控制后，把旧的停用", "target": "controls"}]
    assert [(book["name"], book["text"]) for book in conclusion["workbooks"]] == [("月结套表.xlsx", "可用")]


def test_a_scope_gap_holds_every_workbook_and_a_structure_only_its_own():
    controls = [_on(PASSING, "b1", "b1"), _on(PASSING, "b2", "b2")]
    books = _status(datasets=[BOOK, LEDGER], controls=controls, scope={**SCOPE, "unit": ""})["conclusion"]["workbooks"]
    assert [book["level"] for book in books] == ["not_assessable", "not_assessable"]
    assert all(book["reasons"] == [{"text": "单位未确认", "target": "scope"}] for book in books)
    books = _status(datasets=[BOOK, LEDGER], controls=controls, pending_structures=["合同台账.xlsx"])["conclusion"]["workbooks"]
    assert [(book["name"], book["level"]) for book in books] == [("月结套表.xlsx", "usable"), ("合同台账.xlsx", "not_assessable")]


def test_an_archived_task_is_judged_like_any_other():
    archived = _status(archived=True, controls=[_break("open")])
    assert archived["headline"]["state"] == "archived" and archived["conclusion"]["level"] == "not_usable"
    assert _status(archived=True)["conclusion"]["level"] == "usable"


@pytest.mark.parametrize("controls", [
    [PASSING], [], [_typed(_break("open"))], [_break("waived", blocking=False)], [_break("open", status="error")],
])
def test_the_conclusion_never_says_done_or_passed(controls):
    result = _status(datasets=[BOOK, LEDGER], controls=[_on(row) if row.get("control") else row for row in controls])
    for text in _words(result["conclusion"]):
        assert "完成" not in text and "通过" not in text
