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
    todo = next(row for row in _overview(store.var_root, capsys)["tasks"])["todo"]
    assert {"kind": "collection", "text": "收费明细「应收明细」的列还没确认", "target": "billing"} in todo

    BillingDetailStore(task, actor="assistant").caliber_propose({"exclude_related": True}, "关联方不计")
    todo = next(row for row in _overview(store.var_root, capsys)["tasks"])["todo"]
    assert {"kind": "collection", "text": "收缴率口径有一版建议（第 1 版）等你确认", "target": "billing"} in todo


def test_no_billing_details_no_collection_to_dos(tmp_path, capsys):
    store = TaskStore(tmp_path / "var")
    store.create(title="无明细", period="2026-08")
    [row] = _overview(store.var_root, capsys)["tasks"]
    assert not [item for item in row["todo"] if item["kind"] == "collection"]


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
