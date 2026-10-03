from __future__ import annotations

from pathlib import Path

import pytest

from foundry.errors import FoundryError
from test_finance_controls import _ar_pack, _side, _task


def _broken(tmp_path: Path):
    """A confirmed control over the F-01 shape, run once: one open difference of 11,655."""
    task, analysis, assistant, manager = _task(tmp_path)
    close = analysis.add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=[3525, 5355, 6930, 7020, 5400, 5550], total=22125), name="月结")
    control = manager.finance_controls_save({"confirm": True, "control": {
        "kind": "subtotal", "label": "坏账分项", "left": _side(close, "08·AR", "D5:D10"), "right": _side(close, "08·AR", "D11")}})["controls"][0]
    assistant.finance_controls_run({})
    return task, analysis, assistant, manager, close, control


def _issue(store, control_id):
    return next(row for row in store.finance_controls_list({})["controls"] if row["id"] == control_id)["issue"]


def test_an_undecided_difference_holds_the_close(tmp_path):
    _task_obj, _analysis, assistant, _manager, _close, control = _broken(tmp_path)
    assert _issue(assistant, control["id"]) == {"state": "open", "blocking": True}
    assert assistant.finance_controls_list({})["summary"]["blocking"] == 1


def test_accepting_a_difference_needs_a_reason_and_the_manager(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "x"})
    with pytest.raises(FoundryError, match="requires a reason"):
        manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived"})
    decided = manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "总计与总账一致，分项口径待下月修正"})
    assert decided["difference"] == "11655" and decided["decided_by"] == "manager"
    issue = _issue(assistant, control["id"])
    assert issue["state"] == "waived" and issue["blocking"] is False
    assert assistant.finance_controls_list({})["summary"]["blocking"] == 0


def test_waiting_on_the_preparer_or_a_reimport_still_holds_the_close(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    with pytest.raises(FoundryError, match="name who confirms"):
        manager.finance_control_disposition_save({"control_id": control["id"], "decision": "pending_external", "reason": "发编制方"})
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "pending_external", "reason": "发编制方确认分项计提比例", "counterparty": "账套编制方"})
    assert _issue(assistant, control["id"])["state"] == "pending_external"
    assert _issue(assistant, control["id"])["blocking"] is True
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "corrected", "reason": "编制方已改脚本"})
    assert _issue(assistant, control["id"]) | {"disposition": None} == {"state": "awaiting_reimport", "blocking": True, "disposition": None}


def test_a_decision_does_not_carry_over_to_a_different_difference(tmp_path):
    _task_obj, _analysis, assistant, manager, close, control = _broken(tmp_path)
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知"})
    # The manager widens the tolerance a little: still a break, but now a new version whose result was not decided.
    widened = manager.finance_controls_save({"control": {**control["control"], "tolerance": "10"}})["controls"][0]
    assistant.finance_controls_run({})
    issue = _issue(assistant, widened["id"])
    assert issue["state"] == "open" and issue["blocking"] is True


def test_a_changed_difference_reopens_the_question(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    decided = manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知"})
    from foundry.finance_controls import applies_to

    assert applies_to(decided, {"status": "break", "difference": "11655", "source_hashes": decided["source_hashes"]})
    assert not applies_to(decided, {"status": "break", "difference": "11000", "source_hashes": decided["source_hashes"]})
    assert not applies_to(decided, {"status": "break", "difference": "11655", "source_hashes": {"x": "y"}})
    assert not applies_to(decided, {"status": "pass", "difference": "0", "source_hashes": decided["source_hashes"]})


def test_a_second_review_when_the_task_requires_one(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.finance_control_settings_save({"require_second_review": True})
    manager.finance_control_settings_save({"require_second_review": True})
    decided = manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知", "decided_by_name": "张会计"})
    assert _issue(assistant, control["id"])["state"] == "awaiting_review"
    with pytest.raises(FoundryError, match="someone other"):
        manager.finance_control_disposition_review({"id": decided["id"], "reviewer": "张会计"})
    manager.finance_control_disposition_review({"id": decided["id"], "reviewer": "李经理"})
    issue = _issue(assistant, control["id"])
    assert issue["state"] == "waived" and issue["disposition"]["reviewer"] == "李经理"


def test_by_default_one_person_can_accept_a_difference(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    assert assistant.finance_controls_list({})["settings"] == {"require_second_review": False}
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知"})
    assert _issue(assistant, control["id"])["state"] == "waived"


def test_nothing_to_decide_on_a_passing_or_unconfirmed_control(tmp_path):
    _task_obj, analysis, assistant, manager = _task(tmp_path)
    close = analysis.add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=[2069, 3144, 4069, 4122, 3171, 5550], total=22125), name="月结")
    passing = manager.finance_controls_save({"confirm": True, "control": {"label": "ok", "left": _side(close, "08·AR", "D5:D10"), "right": _side(close, "08·AR", "D11")}})["controls"][0]
    proposed = assistant.finance_controls_save({"control": {"label": "p", "left": _side(close, "08·AR", "B5:B10"), "right": _side(close, "08·AR", "B11")}})["controls"][0]
    assistant.finance_controls_run({})
    with pytest.raises(FoundryError, match="no difference"):
        manager.finance_control_disposition_save({"control_id": passing["id"], "decision": "waived", "reason": "x"})
    with pytest.raises(FoundryError, match="only a confirmed"):
        manager.finance_control_disposition_save({"control_id": proposed["id"], "decision": "waived", "reason": "x"})


def test_a_confirmed_control_never_run_holds_the_close(tmp_path):
    _task_obj, analysis, assistant, manager = _task(tmp_path)
    close = analysis.add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=[2069, 3144, 4069, 4122, 3171, 5550], total=22125), name="月结")
    control = manager.finance_controls_save({"confirm": True, "control": {"label": "ok", "left": _side(close, "08·AR", "D5:D10"), "right": _side(close, "08·AR", "D11")}})["controls"][0]
    assert _issue(assistant, control["id"]) == {"state": "not_run", "blocking": True}


def test_the_confirmation_sheet_lists_where_each_difference_was_read(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "pending_external", "reason": "请确认分项计提比例", "counterparty": "编制方"})
    sheet = assistant.finance_control_confirmation_sheet({})
    assert sheet["count"] == 1
    assert "月结 · 08·AR!D5:D10，合计 33780" in sheet["markdown"]
    assert "差额：11655" in sheet["markdown"] and "待外部确认；请确认分项计提比例" in sheet["markdown"]
    header, row = sheet["tsv"].strip().split("\n")
    assert header.split("\t")[0] == "序号" and row.split("\t")[6] == "11655"


def test_a_named_decider_cannot_review_their_own_acceptance_in_any_spelling(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    manager.finance_control_settings_save({"require_second_review": True})
    with pytest.raises(FoundryError, match="must name who accepts"):
        manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知"})
    decided = manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知", "decided_by_name": "Zhang"})
    for same in ("Zhang ", " zhang", "ZHANG"):
        with pytest.raises(FoundryError, match="someone other"):
            manager.finance_control_disposition_review({"id": decided["id"], "reviewer": same})
    with pytest.raises(FoundryError, match="name the reviewer"):
        manager.finance_control_disposition_review({"id": decided["id"], "reviewer": "   "})


def test_an_acceptance_made_before_review_was_required_must_be_decided_again_with_a_name(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    decided = manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知"})
    manager.finance_control_settings_save({"require_second_review": True})
    assert _issue(assistant, control["id"])["state"] == "awaiting_review"
    with pytest.raises(FoundryError, match="names no one"):
        manager.finance_control_disposition_review({"id": decided["id"], "reviewer": "李经理"})


def test_switching_review_off_does_not_clear_an_acceptance_waiting_on_it(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    manager.finance_control_settings_save({"require_second_review": True})
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "已知", "decided_by_name": "张会计"})
    manager.finance_control_settings_save({"require_second_review": False})
    assert _issue(assistant, control["id"])["state"] == "awaiting_review"


def test_a_range_that_cannot_be_read_is_corrected_never_accepted_and_goes_on_the_sheet(tmp_path):
    from openpyxl import Workbook

    _task_obj, analysis, assistant, manager = _task(tmp_path)
    path = tmp_path / "text.xlsx"
    book = Workbook()
    book.active.title = "S"
    for row in (["项目", "金额"], ["甲", 100], ["乙", "1,200"], ["丙", 50], ["合计", 150]):
        book.active.append(row)
    book.save(path)
    dataset = analysis.add_dataset(path, name="文字数字")
    control = manager.finance_controls_save({"confirm": True, "control": {"kind": "subtotal", "label": "x", "left": _side(dataset, "S", "B2:B4"), "right": _side(dataset, "S", "B5")}})["controls"][0]
    assistant.finance_controls_run({})
    for decision in ("waived", "pending_external"):
        with pytest.raises(FoundryError, match="can only be corrected"):
            manager.finance_control_disposition_save({"control_id": control["id"], "decision": decision, "reason": "无所谓", "counterparty": "编制方"})
    sheet = assistant.finance_control_confirmation_sheet({})
    assert sheet["count"] == 1 and "读不出" in sheet["markdown"]


def test_the_sheet_leaves_out_accepted_and_passing_controls(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "waived", "reason": "内部已知"})
    assert assistant.finance_control_confirmation_sheet({})["count"] == 0


def test_a_corrected_file_lets_the_old_control_be_retired_and_the_close_clear(tmp_path):
    _task_obj, analysis, assistant, manager, _close, control = _broken(tmp_path)
    manager.finance_control_disposition_save({"control_id": control["id"], "decision": "corrected", "reason": "编制方已改"})
    analysis.add_dataset(_ar_pack(tmp_path / "v2.xlsx", provisions=[2069, 3144, 4069, 4122, 3171, 5550], total=22125), name="月结")
    assert _issue(assistant, control["id"])["state"] == "stale"
    fresh = [row["control"] for row in assistant.finance_controls_propose({})["suggestions"]]
    manager.finance_controls_save({"confirm": True, "origin": "suggested", "controls": fresh})
    assistant.finance_controls_run({})
    assert assistant.finance_controls_list({})["summary"]["blocking"] == 1
    manager.finance_controls_retire({"id": control["id"], "reason": "已换用修正后的资料"})
    assert assistant.finance_controls_list({})["summary"]["blocking"] == 0


def test_pasted_text_cannot_become_a_formula_or_a_fake_item(tmp_path):
    from foundry.finance_controls import confirmation_sheet

    row = {
        "control": {"label": '=HYPERLINK("http://x","点我")'},
        "result": {"status": "break", "difference": "-5", "left": {"dataset_id": "d", "sheet": "S", "range": "A1", "value": "1"},
                   "right": {"dataset_id": "d", "sheet": "S", "range": "A2", "value": "6"}},
        "issue": {"state": "open", "disposition": {"reason": "第一行\r第二行\n## 3. 伪造条目"}},
    }
    sheet = confirmation_sheet([row], {"d": "月结"})
    cells = sheet["tsv"].strip().split("\n")[1].split("\t")
    assert cells[1].startswith("'=HYPERLINK")
    assert cells[6] == "-5"  # an amount stays a number
    assert "\r" not in sheet["tsv"] and "\n## 3." not in sheet["markdown"]
