from __future__ import annotations

import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.sample_marker import marker_path, uses_sample_shelf
from foundry.sample_task import (
    KINDS,
    create_next_month_sample,
    create_sample_task,
    export_pack,
    pack_dir,
    pack_manifest,
    remove_samples,
    sample_status,
)
from foundry.task import TaskStore

AUGUST = "华宸物业_2026年08月_月结财务套表_GL-AP-AR-CF.xlsx"


def _task(var, made):
    return TaskStore(var).get(made["id"])


def _confirm(task, name):
    manager = FinanceStore(task, actor="manager")
    dataset = next(row for row in AnalysisStore(task).state()["datasets"] if row["name"] == name)
    proposal = manager.structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]
    manager.structure_proposal_confirm({"dataset_id": dataset["id"], "revision": proposal["revision"]})


def test_the_practice_task_is_made_once_per_pack_and_reused(tmp_path):
    var = tmp_path / "var"
    first = create_sample_task(var)
    again = create_sample_task(var)
    assert first["created"] is True and again == {"id": first["id"], "created": False}
    assert [task.meta()["title"] for task in TaskStore(var).list("active")] == [KINDS["practice"]]
    marker = json.loads(marker_path(_task(var, first)).read_text(encoding="utf-8"))
    assert marker == {"sample": True, "pack": "huachen", "version": pack_manifest()["version"], "kind": "practice", "ready": True}


def test_it_files_the_whole_pack_and_never_touches_another_task(tmp_path):
    var = tmp_path / "var"
    real = TaskStore(var).create(title="华东区 8 月回款")
    sample = create_sample_task(var)
    assert sample["id"] != real.id
    assert AnalysisStore(real).state()["datasets"] == []
    names = sorted(row["name"] for row in AnalysisStore(_task(var, sample)).state()["datasets"])
    assert names == sorted(pack_manifest()["practice"])


def test_the_practice_task_asks_for_its_structure_like_a_real_import(tmp_path):
    task = _task(tmp_path / "var", create_sample_task(tmp_path / "var"))
    service = FinanceStore(task)
    assert service.finance_readiness({})["blocked"][0]["reason"] == "pending_structure"
    structure = next(block for block in service.finance_close_status({})["blocks"] if block["key"] == "structure")
    assert structure["state"] == "blocked"


def test_a_practice_structure_never_prefills_a_real_pack(tmp_path):
    var = tmp_path / "var"
    _confirm(_task(var, create_sample_task(var)), AUGUST)
    assert (var / "structure_templates_sample").is_dir() and not (var / "structure_templates").exists()

    real = TaskStore(var).create(title="9 月月结")
    dataset = AnalysisStore(real).add_dataset(pack_dir() / AUGUST.replace("08月", "09月"), name="9 月")
    assert not FinanceStore(real).structure_propose(dataset["id"], source="assistant").get("template_matches")

    # The practice September still finds the practice August's shapes.
    september = _task(var, create_next_month_sample(var))
    dataset = AnalysisStore(september).state()["datasets"][0]
    proposal = FinanceStore(september).structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]
    assert len(proposal["template_matches"]) >= 9


def test_a_half_made_practice_task_goes_to_the_trash_and_is_not_reused(tmp_path):
    var = tmp_path / "var"
    first = create_sample_task(var)
    path = marker_path(_task(var, first))
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "ready": False}), encoding="utf-8")
    again = create_sample_task(var)
    assert again["created"] is True and again["id"] != first["id"]
    assert _task(var, first).lifecycle_status() == "trashed"


def test_status_flags_an_older_practice_task_and_remove_trashes_only_practice_tasks(tmp_path):
    var = tmp_path / "var"
    store = TaskStore(var)
    real = store.create(title=KINDS["practice"])  # the title alone makes nothing a practice task
    legacy = store.create(title="示例：月结练习（合成数据）")
    marker_path(legacy).write_text(json.dumps({"sample": True, "dataset": "示例集团_2026年06月_月结套表"}), encoding="utf-8")
    practice = create_sample_task(var)
    status = sample_status(var)
    assert status["outdated"] is True
    assert {row["id"]: row["kind"] for row in status["tasks"]} == {legacy.id: "legacy", practice["id"]: "practice"}

    assert sorted(remove_samples(var)["trashed"]) == sorted([legacy.id, practice["id"]])
    assert real.lifecycle_status() == "active"
    assert sample_status(var)["outdated"] is False
    assert remove_samples(var)["trashed"] == []


def test_export_copies_the_files_into_a_new_folder_and_never_overwrites(tmp_path):
    exported = export_pack(tmp_path / "示例资料")
    assert sorted(path.name for path in (tmp_path / "示例资料").iterdir()) == sorted(exported["files"])
    with pytest.raises(FoundryError):
        export_pack(tmp_path / "示例资料")


def test_the_cli_prints_the_task_and_marks_practice_tasks_in_the_list(tmp_path, capsys):
    var = str(tmp_path / "var")
    assert main(["--var", var, "task-sample"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["created"] is True and len(printed["id"]) == 32
    TaskStore(tmp_path / "var").create(title="真实任务")
    assert main(["--var", var, "task-list"]) == 0
    listed = {row["title"]: (row["sample"], row["sample_outdated"], row["sample_ready"]) for row in json.loads(capsys.readouterr().out)}
    assert listed == {KINDS["practice"]: ("practice", False, True), "真实任务": (None, False, True)}
    assert main(["--var", var, "task-sample-status"]) == 0
    assert json.loads(capsys.readouterr().out)["outdated"] is False


def test_the_older_practice_task_keeps_the_shelf_its_templates_are_on(tmp_path):
    store = TaskStore(tmp_path / "var")
    legacy = store.create(title="示例：月结练习（合成数据）")
    marker_path(legacy).write_text(json.dumps({"sample": True, "dataset": "示例集团_2026年06月_月结套表"}), encoding="utf-8")
    damaged = store.create(title="示例")
    marker_path(damaged).write_text("{", encoding="utf-8")
    assert uses_sample_shelf(legacy) is False
    assert uses_sample_shelf(damaged) is True
    assert uses_sample_shelf(store.create(title="真实任务")) is False


def test_a_remembered_shape_the_file_cannot_fill_leaves_the_import_standing(tmp_path):
    # 月度收入 and 上年同期对比 share a shape; the second holds #REF!. Once the first is remembered, the
    # next import offers the shape for both, cannot read the second, and leaves both to the manager.
    var = tmp_path / "var"
    formula = next(name for name in pack_manifest()["practice"] if "公式体检" in name)
    first = _task(var, create_sample_task(var))
    manager = FinanceStore(first, actor="manager")
    dataset = next(row for row in AnalysisStore(first).state()["datasets"] if row["name"] == formula)
    proposal = manager.structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]
    manager.structure_proposal_confirm({"dataset_id": dataset["id"], "revision": proposal["revision"],
                                        "sheets": [s for s in proposal["sheets"] if s["sheet"] == "月度收入"]})

    remove_samples(var)
    second = _task(var, create_sample_task(var))
    service = FinanceStore(second)
    names = [row["name"] for row in AnalysisStore(second).state()["datasets"]]
    assert sorted(names) == sorted(pack_manifest()["practice"])  # nothing filed half-way
    dataset = next(row for row in AnalysisStore(second).state()["datasets"] if row["name"] == formula)
    assert service.dataset_structure_state(dataset["id"]) != "confirmed"
