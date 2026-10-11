"""总览 and 成果库 read every task in one process, and decide nothing the per-task reads do not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.billing_detail import BillingDetailStore
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.task import TaskStore


def _json(capsys) -> object:
    return json.loads(capsys.readouterr().out)


def _overview(var: Path, capsys) -> dict:
    assert main(["--var", str(var), "overview"]) == 0
    return _json(capsys)


def test_a_task_with_no_files_says_so_and_points_at_the_materials_page(tmp_path, capsys):
    var = tmp_path / "var"
    TaskStore(var).create(title="8 月月结", period="2026-08")
    result = _overview(var, capsys)
    [row] = result["tasks"]
    assert row["headline"]["state"] == "not_ready"
    assert [block["key"] for block in row["blocks"]] == ["scope", "source", "structure", "controls", "exceptions", "review"]
    assert {"kind": "source", "text": "还没有资料", "target": "datasets"} in row["todo"]
    assert {"kind": "scope", "text": "期间未确认", "target": "scope"} in row["todo"]
    assert result["todo_count"] == len(row["todo"])
    # What the steps after 勾稽 read (steps.ts): nothing yet.
    assert row["work"] == {"runs": [], "cards": [], "drafts": 0, "datasets": 0}
    # Each block keeps its rows for the step's line on 总览.
    scope = next(block for block in row["blocks"] if block["key"] == "scope")
    assert {"text": "期间未确认", "blocking": True, "attention": False, "target": "scope"} in scope["items"]
    assert row["health"] is None and row["tried"] == []
    assert row["active_at"] == row["task"]["created_at"]


def test_the_work_digest_carries_what_the_step_rules_read_of_each_run():
    from foundry.overview import _role

    assert _role({"result_role": "Activity", "result": {"role": "business"}}) == "activity"
    assert _role({"result": {"result_role": None, "role": "Business"}}) == "business"
    assert _role({"result": {}}) == ""
    # The first one set wins, even when it is empty, as `??` reads it.
    assert _role({"run_role": "", "activity_role": "activity"}) == ""


def test_only_active_tasks_newest_period_first(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    july = store.create(title="7 月", period="2026-07")
    august = store.create(title="8 月", period="2026-08")
    store.create(title="6 月", period="2026-06").set_lifecycle_status("archived")
    store.create(title="5 月", period="2026-05").set_lifecycle_status("trashed")
    rows = _overview(store.var_root, capsys)["tasks"]
    assert [row["task"]["id"] for row in rows] == [august.id, july.id]


def test_one_unreadable_task_does_not_hide_the_others(tmp_path, capsys, monkeypatch):
    from foundry.finance_service import FinanceStore

    store = TaskStore(tmp_path / "var")
    broken = store.create(title="坏的", period="2026-08")
    fine = store.create(title="好的", period="2026-07")
    original = FinanceStore.finance_close_status

    def status(self, spec=None):
        if self.task.id == broken.id:
            raise FoundryError("记录损坏")
        return original(self, spec)

    monkeypatch.setattr(FinanceStore, "finance_close_status", status)
    rows = {row["task"]["id"]: row for row in _overview(store.var_root, capsys)["tasks"]}
    assert rows[broken.id]["error"] == "记录损坏" and rows[broken.id]["todo"] == []
    assert rows[fine.id]["headline"]["state"] == "not_ready"



def test_a_task_with_unreadable_windows_is_one_error_row(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    broken = store.create(title="坏的", period="2026-08")
    fine = store.create(title="好的", period="2026-07")
    broken.windows_path.write_text("{not json\n", encoding="utf-8")
    rows = {row["task"]["id"]: row for row in _overview(store.var_root, capsys)["tasks"]}
    assert rows[broken.id]["error"].startswith("读取失败") and rows[broken.id]["task"]["title"] == "坏的"
    assert rows[fine.id]["headline"]["state"] == "not_ready"

def _detail(root: Path, kind: str, name: str, lines: list[str]) -> Path:
    path = root / f"{name}.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_billing_details_and_caliber_waiting_on_the_manager_are_to_dos(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    task = store.create(title="收缴率", period="2026-08")
    billing = BillingDetailStore(task, actor="manager")
    source = _detail(tmp_path, "receivable", "应收", ["应收单号,房产编号,收费项目,账期,应收净额", "B1,P1,物业费,2026-08,100"])
    billing.add("receivable", [source], name="应收明细")
    row = next(row for row in _overview(store.var_root, capsys)["tasks"])
    assert {"kind": "collection", "text": "收费明细「应收明细」的列还没确认", "target": "billing"} in row["todo"]
    # A 收费明细 added: 收缴率 down to the bill is no longer one to try.
    assert row["tried"] == ["billing"]

    BillingDetailStore(task, actor="assistant").caliber_propose({"exclude_related": True}, "关联方不计")
    todo = next(row for row in _overview(store.var_root, capsys)["tasks"])["todo"]
    assert {"kind": "collection", "text": "收缴率口径有一版建议（第 1 版）等你确认", "target": "billing"} in todo


def test_no_billing_details_no_collection_to_dos(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    store.create(title="无明细", period="2026-08")
    [row] = _overview(store.var_root, capsys)["tasks"]
    assert not [item for item in row["todo"] if item["kind"] == "collection"]


def test_the_cockpit_reads_the_radar_the_features_used_and_each_run_s_question(tmp_path, capsys):
    from test_dashboards import _board, _gap, _scenario

    manager, run, _ = _board(tmp_path)
    [row] = _overview(tmp_path / "var", capsys)["tasks"]
    # 回款健康's 风险雷达, by light: 经营分析's line. Nothing on the board yet, so nothing tried.
    assert row["health"] == {"run_id": run["id"], "levels": {"green": 1}}
    assert row["tried"] == []
    [digest] = row["work"]["runs"]
    assert digest["scenario_kind"] == "collection_health" and digest["analysis_id"] == run["analysis_id"] and digest["label"]

    manager.dashboard_save({"parent_id": None, "cards": [_gap(run), _scenario(run)]})
    [row] = _overview(tmp_path / "var", capsys)["tasks"]
    assert row["tried"] == ["scenario"]
    # 倒推 and 敏感性表 count as one: working back from a target.
    board = manager.dashboard_read({})["dashboard"]
    goal = {**_scenario(run), "kind": "goal", "title": "倒推", "select": {"match": {"entity": "集团", "scenario": "本期"}, "goal": "collection"}}
    manager.dashboard_save({"parent_id": board["id"], "cards": [*board["cards"], goal]})
    [row] = _overview(tmp_path / "var", capsys)["tasks"]
    assert row["tried"] == ["scenario", "goal"]


def test_a_task_was_last_worked_on_when_its_newest_record_or_conversation_was(tmp_path):
    from foundry.overview import _active_at

    task = TaskStore(tmp_path / "var").create(title="8 月", period="2026-08")
    row = {"created_at": "2026-10-01T08:00:00Z", "restored_at": None}
    assert _active_at(task, row, ([], [])) == "2026-10-01T08:00:00Z"
    runs = [{"created_at": "2026-10-03T08:00:00Z"}, {"created_at": "2026-10-05T08:00:00Z"}]
    assert _active_at(task, row, (runs, [{"created_at": "2026-10-04T08:00:00Z"}])) == "2026-10-05T08:00:00Z"
    # A conversation opened after the last record counts too.
    task.record_session("s1", role="analysis")
    assert _active_at(task, row, (runs,)) == task.sessions()[0]["opened_at"]


def test_library_lists_drafts_of_every_task_but_the_trashed(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    kept = store.create(title="归档的", period="2026-07")
    AnalysisStore(kept).save_draft({"title": "7 月说明", "body": "正文"})
    kept.set_lifecycle_status("archived")
    gone = store.create(title="回收站的", period="2026-06")
    AnalysisStore(gone).save_draft({"title": "6 月说明", "body": "正文"})
    gone.set_lifecycle_status("trashed")
    assert main(["--var", str(store.var_root), "library"]) == 0
    rows = _json(capsys)
    assert [(row["type"], row["task"]["id"], row["draft"]["title"]) for row in rows] == [("draft", kept.id, "7 月说明")]
    assert rows[0]["key"] == f"draft:{rows[0]['draft']['draft_id']}"


def test_library_detail_carries_the_text_the_checks_and_every_version(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    task = store.create(title="8 月", period="2026-08")
    analysis = AnalysisStore(task)
    first = analysis.save_draft({"title": "月结说明", "body": "第一段"})
    second = analysis.save_draft({"parent_id": first["id"], "body": "第一段改了"})
    assert main(["--var", str(store.var_root), "--task", task.id, "library-detail", "--draft", second["id"]]) == 0
    detail = _json(capsys)
    assert detail["draft"]["body"] == "第一段改了" and detail["draft"]["revision"] == 2
    assert detail["draft"]["parent_id"] == first["id"]
    assert [row["revision"] for row in detail["versions"]] == [1, 2]
    assert [check["key"] for check in detail["checks"]] == ["execution", "numeric_citation", "source_validation", "professional_review"]
    assert detail["rests_on"] == []


def test_library_detail_refuses_a_draft_the_task_does_not_hold(tmp_path):
    store = TaskStore(tmp_path / "var")
    task = store.create(title="8 月")
    with pytest.raises(FoundryError, match="no draft"):
        from foundry.overview import library_detail

        library_detail(task, "0" * 32)


def test_workbook_output_path_takes_an_id_and_nothing_else(tmp_path):
    from foundry.overview import workbook_output_path

    task = TaskStore(tmp_path / "var").create(title="8 月")
    with pytest.raises(FoundryError, match="not a workbook output id"):
        workbook_output_path(task, "../../etc/passwd")
    with pytest.raises(FoundryError, match="no workbook output"):
        workbook_output_path(task, "a" * 32)


def test_a_conversation_cannot_read_the_desktop_views(tmp_path, capsys):
    var = tmp_path / "var"
    TaskStore(var).create(title="8 月")
    assert main(["--var", str(var), "--session", "sess-1", "overview"]) != 0
