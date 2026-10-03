from __future__ import annotations

import json

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.finance_service import FinanceStore
from foundry.sample_task import SAMPLE_DATASET, SAMPLE_TITLE, create_sample_task
from foundry.task import TaskStore


def test_the_practice_task_is_made_once_and_reused(tmp_path):
    first = create_sample_task(tmp_path / "var")
    again = create_sample_task(tmp_path / "var")
    assert first["created"] is True and again == {"id": first["id"], "created": False}
    tasks = TaskStore(tmp_path / "var").list("active")
    assert [task.meta()["title"] for task in tasks] == [SAMPLE_TITLE]


def test_it_never_touches_another_task(tmp_path):
    store = TaskStore(tmp_path / "var")
    real = store.create(title="华东区 8 月回款")
    before = AnalysisStore(real).state()["datasets"]
    sample = create_sample_task(tmp_path / "var")
    assert sample["id"] != real.id
    assert AnalysisStore(real).state()["datasets"] == before == []
    names = [row["name"] for row in AnalysisStore(store.get(sample["id"])).state()["datasets"]]
    assert names == [SAMPLE_DATASET]


def test_the_practice_pack_names_a_past_month_and_carries_one_break_to_practise_on(tmp_path):
    task = TaskStore(tmp_path / "var").get(create_sample_task(tmp_path / "var")["id"])
    service = FinanceStore(task)
    # Like any import, nothing is proposed until the manager confirms the structure.
    assert service.finance_readiness({})["blocked"][0]["reason"] == "pending_structure"
    manager = FinanceStore(task, actor="manager")
    dataset_id = AnalysisStore(task).state()["datasets"][0]["id"]
    proposal = manager.structure_proposal_list({"dataset_id": dataset_id})
    proposal = (proposal.get("proposals") or [proposal])[0] if isinstance(proposal, dict) else proposal[0]
    manager.structure_proposal_confirm({"dataset_id": dataset_id, "revision": proposal["revision"]})
    proposed = service.finance_readiness({})["proposed_scope"]
    assert (proposed["period"], proposed["currency"]) == ("2026-06", "人民币")
    previews = {row["control"]["label"]: row["preview"] for row in service.finance_controls_propose({})["suggestions"]}
    breaks = {label: preview["difference"] for label, preview in previews.items() if preview["status"] != "pass"}
    assert breaks == {"02·应收账龄 · 坏账准备：分项合计 = 合计": "50"}
    assert service.finance_close_status({})["headline"]["state"] == "not_ready"


def test_the_cli_prints_the_task_as_json(tmp_path, capsys):
    assert main(["--var", str(tmp_path / "var"), "task-sample"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["created"] is True and len(printed["id"]) == 32


def test_the_practice_task_asks_for_its_structure_like_a_real_import(tmp_path):
    task = TaskStore(tmp_path / "var").get(create_sample_task(tmp_path / "var")["id"])
    structure = next(block for block in FinanceStore(task).finance_close_status({})["blocks"] if block["key"] == "structure")
    assert structure["state"] == "blocked"


def test_a_real_task_with_the_same_title_is_never_reused(tmp_path):
    store = TaskStore(tmp_path / "var")
    real = store.create(title=SAMPLE_TITLE)
    sample = create_sample_task(tmp_path / "var")
    assert sample["created"] is True and sample["id"] != real.id


def test_two_quick_requests_make_one_task(tmp_path):
    import subprocess
    import sys

    var = tmp_path / "var"
    command = [sys.executable, "-m", "foundry.cli", "--var", str(var), "task-sample"]
    first, second = subprocess.Popen(command, stdout=subprocess.PIPE), subprocess.Popen(command, stdout=subprocess.PIPE)
    ids = {json.loads(first.communicate()[0])["id"], json.loads(second.communicate()[0])["id"]}
    assert len(ids) == 1
    assert len(TaskStore(var).list("active")) == 1
