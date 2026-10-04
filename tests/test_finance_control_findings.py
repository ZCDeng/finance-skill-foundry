from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.errors import FoundryError
from test_finance_controls import _ar_pack, _side, _task

BROKEN = [3525, 5355, 6930, 7020, 5400, 5550]  # 坏账分项 adds up to 33780 against a 合计 of 22125
BALANCED = [2069, 3144, 4069, 4122, 3171, 5550]


def _control(close, label="坏账分项"):
    return {"kind": "subtotal", "label": label, "left": _side(close, "08·AR", "D5:D10"), "right": _side(close, "08·AR", "D11")}


def _broken(tmp_path: Path):
    task, analysis, assistant, manager = _task(tmp_path)
    close = analysis.add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=BROKEN, total=22125), name="月结")
    control = manager.finance_controls_save({"confirm": True, "control": _control(close)})["controls"][0]
    assistant.finance_controls_run({})
    return task, analysis, assistant, manager, close, control


def _row(store, control_id):
    return next(row for row in store.finance_controls_list({})["controls"] if row["id"] == control_id)


def test_the_assistant_only_suggests_and_the_manager_decides(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    assert _row(assistant, control["id"])["finding"] == {"set_by_manager": False}
    saved = assistant.finance_control_finding_save({"control_id": control["id"], "finding_type": "source_conflict", "note": "分项与合计取自两次导出"})
    assert saved["set_by"] == "assistant" and saved["difference"] == "11655" and saved["status"] == "break"
    assert _row(assistant, control["id"])["finding"] == {
        "set_by_manager": False, "suggested_type": "source_conflict", "suggested_type_label": "来源矛盾",
        "suggested_note": "分项与合计取自两次导出",
    }
    # The manager answers with another type: hers is the type, and the answered suggestion is not offered again.
    manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "formula_control", "note": "合计公式漏了一行"})
    assert _row(assistant, control["id"])["finding"] == {
        "set_by_manager": True, "type": "formula_control", "type_label": "公式或控制缺陷", "note": "合计公式漏了一行",
    }
    # A later suggestion never overrides her type; it is only offered.
    assistant.finance_control_finding_save({"control_id": control["id"], "finding_type": "unsupported_assumption"})
    finding = _row(manager, control["id"])["finding"]
    assert finding["type"] == "formula_control" and finding["suggested_type"] == "unsupported_assumption"
    # Her later record overrides her earlier one, and adopting the suggestion clears it.
    manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "unsupported_assumption"})
    assert _row(manager, control["id"])["finding"] == {"set_by_manager": True, "type": "unsupported_assumption", "type_label": "无依据假设"}


def test_saying_the_same_thing_twice_keeps_one_record(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    first = manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "not_updated"})
    again = manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "not_updated"})
    assert again["id"] == first["id"]
    changed = manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "not_updated", "note": "合同台账停在七月"})
    assert changed["id"] != first["id"] and changed["parent_id"] == first["id"]


def test_a_suggestion_made_before_confirmation_survives_it(tmp_path):
    _task_obj, analysis, assistant, manager = _task(tmp_path)
    close = analysis.add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=BROKEN, total=22125), name="月结")
    proposed = assistant.finance_controls_save({"control": _control(close)})["controls"][0]
    assistant.finance_controls_run({})
    assistant.finance_control_finding_save({"control_id": proposed["id"], "finding_type": "basis_difference", "note": "分项含已核销"})
    confirmed = manager.finance_controls_confirm({"id": proposed["id"]})
    assert confirmed["id"] != proposed["id"]
    # Confirmed but not yet run: there is no current difference to type.
    assert _row(assistant, confirmed["id"])["finding"] is None
    assistant.finance_controls_run({})
    assert _row(assistant, confirmed["id"])["finding"]["suggested_type"] == "basis_difference"
    manager.finance_control_finding_save({"control_id": confirmed["id"], "finding_type": "basis_difference"})
    # A manager edit makes a new version of the same check; the same difference keeps its type.
    renamed = manager.finance_controls_save({"control": {**_control(close), "label": "坏账准备分项"}})["controls"][0]
    assert renamed["id"] != confirmed["id"] and renamed["state"] == "confirmed"
    assistant.finance_controls_run({})
    finding = _row(assistant, renamed["id"])["finding"]
    assert finding["type"] == "basis_difference" and finding["set_by_manager"] is True


def test_a_finding_about_another_difference_is_outdated_not_current():
    from foundry.finance_controls import control_finding

    hashes = {"d1": "a" * 64}
    result = {"status": "break", "difference": "11655", "source_hashes": hashes}
    row = {"state": "confirmed", "control": {"label": "坏账分项"}, "result": result}
    about = lambda difference, set_by, finding_type, seq: {
        "status": "break", "difference": difference, "source_hashes": hashes, "set_by": set_by, "finding_type": finding_type, "seq": seq}
    assert control_finding(row, [about("11000", "manager", "source_conflict", 1)]) == {"set_by_manager": False, "outdated": True}
    # A suggestion about the current difference is still offered beside an outdated decision.
    assert control_finding(row, [about("11000", "manager", "source_conflict", 1), about("11655", "assistant", "not_updated", 2)]) == {
        "set_by_manager": False, "outdated": True, "suggested_type": "not_updated", "suggested_type_label": "未更新"}
    # A suggestion about another difference is simply not current.
    assert control_finding(row, [about("11000", "assistant", "not_updated", 1)]) == {"set_by_manager": False}
    assert control_finding({**row, "result": {**result, "source_hashes": {"d1": "b" * 64}}}, [about("11655", "manager", "not_updated", 1)])["outdated"] is True
    # No difference at all: passing, stale, never run or retired.
    for other in ({"status": "pass", "difference": "0", "source_hashes": hashes}, {"status": "stale"}, None):
        assert control_finding({**row, "result": other}, [about("11655", "manager", "not_updated", 1)]) is None
    assert control_finding({**row, "state": "retired"}, [about("11655", "manager", "not_updated", 1)]) is None


def test_only_a_current_difference_takes_one_of_the_five_types(tmp_path):
    task, analysis, assistant, manager, close, control = _broken(tmp_path)
    for store in (assistant, manager):
        with pytest.raises(FoundryError, match="finding type must be one of formula_control, source_conflict, unsupported_assumption, not_updated, basis_difference"):
            store.finance_control_finding_save({"control_id": control["id"], "finding_type": "rounding"})
        with pytest.raises(FoundryError, match="finding type must be one of"):
            store.finance_control_finding_save({"control_id": control["id"]})
        with pytest.raises(FoundryError, match="finding requires control_id"):
            store.finance_control_finding_save({"finding_type": "not_updated"})
        with pytest.raises(FoundryError, match="finding note is too long"):
            store.finance_control_finding_save({"control_id": control["id"], "finding_type": "not_updated", "note": "长" * 501})
    good = analysis.add_dataset(_ar_pack(tmp_path / "ok.xlsx", provisions=BALANCED, total=22125), name="另一套")
    passing = manager.finance_controls_save({"confirm": True, "control": _control(good, "相符分项")})["controls"][0]
    assistant.finance_controls_run({})
    never_run = manager.finance_controls_save({"confirm": True, "control": {**_control(good, "余额"), "left": _side(good, "08·AR", "B5:B10"), "right": _side(good, "08·AR", "B11")}})["controls"][0]
    for control_id in (passing["id"], never_run["id"]):
        with pytest.raises(FoundryError, match="only a current difference can be given a finding type"):
            manager.finance_control_finding_save({"control_id": control_id, "finding_type": "not_updated"})
    manager.finance_controls_retire({"id": passing["id"], "reason": "不再检查"})
    with pytest.raises(FoundryError, match="not the latest version or does not exist"):
        assistant.finance_control_finding_save({"control_id": passing["id"], "finding_type": "not_updated"})
    # A re-uploaded pack leaves the old control reading old bytes: stale, not a difference to type.
    analysis.add_dataset(_ar_pack(tmp_path / "v2.xlsx", provisions=BROKEN, total=33780), name="月结")
    assert _row(manager, control["id"])["result"]["status"] == "stale"
    with pytest.raises(FoundryError, match="only a current difference"):
        manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "not_updated"})


def test_the_confirmation_sheet_says_the_type_or_that_it_is_only_suggested(tmp_path):
    _task_obj, _analysis, assistant, manager, _close, control = _broken(tmp_path)
    assistant.finance_control_finding_save({"control_id": control["id"], "finding_type": "source_conflict"})
    sheet = assistant.finance_control_confirmation_sheet({})
    header, row = sheet["tsv"].strip().split("\n")
    assert header.split("\t")[8:] == ["问题类型", "说明"]
    assert row.split("\t")[6] == "11655" and row.split("\t")[8] == "助手建议：来源矛盾"
    assert "- 问题类型：助手建议：来源矛盾" in sheet["markdown"]
    manager.finance_control_finding_save({"control_id": control["id"], "finding_type": "not_updated"})
    sheet = assistant.finance_control_confirmation_sheet({})
    assert sheet["tsv"].strip().split("\n")[1].split("\t")[8] == "未更新"
    assert "- 问题类型：未更新" in sheet["markdown"]


def test_an_untyped_difference_leaves_the_column_blank_and_cells_stay_text():
    from foundry.finance_controls import confirmation_sheet

    row = {
        "control": {"label": "=SUM(A1)"},
        "result": {"status": "break", "difference": "-5", "left": {"dataset_id": "d", "sheet": "S", "range": "A1", "value": "1"},
                   "right": {"dataset_id": "d", "sheet": "S", "range": "A2", "value": "6"}},
        "issue": {"state": "open"},
        "finding": {"set_by_manager": False},
    }
    cells = confirmation_sheet([row], {"d": "月结"})["tsv"].rstrip("\n").split("\n")[1].split("\t")
    assert cells[1] == "'=SUM(A1)" and cells[8] == "" and len(cells) == 10
    assert "问题类型" not in confirmation_sheet([row], {"d": "月结"})["markdown"]


def test_the_cli_records_a_suggestion_unstamped_and_a_decision_as_the_manager(tmp_path, capsys):
    from foundry.cli import main
    from foundry.finance_requirements import save_requirements

    task, analysis, _assistant, _manager, _close, control = _broken(tmp_path)
    save_requirements(analysis, {"question": "八月月结", "scope": {"period": "2026-08", "unit": "万元", "currency": "CNY"}, "items": []})
    root = str(tmp_path / "var")

    def call(*args, actor=None):
        code = main(["--var", root, "--task", task.id, *(["--actor", actor] if actor else []), *args])
        captured = capsys.readouterr()
        return code, (json.loads(captured.out) if code == 0 else captured.err)

    code, suggested = call("finance-control-finding-save", "--spec", json.dumps({"control_id": control["id"], "finding_type": "source_conflict"}))
    assert code == 0 and suggested["set_by"] == "assistant"
    code, decided = call("finance-control-finding-save", "--spec", json.dumps({"control_id": control["id"], "finding_type": "basis_difference"}), actor="manager")
    assert code == 0 and decided["set_by"] == "manager" and decided["parent_id"] == suggested["id"]
    code, listed = call("finance-controls-list", "--spec", "{}")
    assert listed["controls"][0]["finding"]["type"] == "basis_difference"
    code, refused = call("finance-control-finding-save", "--spec", json.dumps({"control_id": control["id"], "finding_type": "guess"}))
    assert code == 3 and "finding type must be one of" in refused
    code, status = call("finance-close-status")
    assert code == 0 and status["conclusion"]["level"] == "not_usable"
    assert status["conclusion"]["reasons"] == [{"text": "坏账分项：差额 11655，口径不同，差异待处理", "target": "controls"}]
    assert [(book["name"], book["text"]) for book in status["conclusion"]["workbooks"]] == [("月结", "不可用")]
