from __future__ import annotations

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.sample_reference import DECIDER
from foundry.sample_task import KINDS, create_reference_task, create_sample_task, sample_status
from foundry.task import TaskStore

AUGUST = "华宸物业_2026年08月_月结财务套表_GL-AP-AR-CF.xlsx"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    var = tmp_path_factory.mktemp("reference") / "var"
    made = create_reference_task(var)
    return var, TaskStore(var).get(made["id"]), made


def test_the_reference_task_walks_the_whole_route(built):
    _, task, made = built
    assert made["created"] is True and task.meta()["title"] == KINDS["reference"]
    blocks = {block["key"]: block for block in FinanceStore(task, actor="manager").finance_close_status({})["blocks"]}
    assert {key: block["state"] for key, block in blocks.items()} == {
        "source": "done", "structure": "done", "scope": "done", "controls": "done",
        # Two differences wait on 合同管理部 and 应收会计: the example shows a close as it usually stands.
        "exceptions": "blocked", "review": "done",
    }
    waiting = [item["text"] for item in blocks["exceptions"]["items"] if "待外部确认" in item["text"]]
    assert len(waiting) == 2 and any("-2793.2794" in text for text in waiting)


def test_every_decision_and_the_draft_say_they_are_the_examples(built):
    _, task, _ = built
    manager = FinanceStore(task, actor="manager")
    decided = [(row.get("issue") or {}).get("disposition") for row in manager.finance_controls_list({})["controls"]]
    decided = [disposition for disposition in decided if disposition]
    assert len(decided) == 4 and all(disposition["decided_by_name"] == DECIDER for disposition in decided)
    draft = AnalysisStore(task).state()["drafts"][-1]
    dimensions = draft["explanation_check"]["status_dimensions"]
    assert {key: dimensions[key]["status"] for key in ("execution", "numeric_citation", "source_validation")} == {
        "execution": "pass", "numeric_citation": "pass", "source_validation": "pass"}
    assert "91.14%" in draft["body"] and "-3.22 个百分点" in draft["body"]


def test_the_reference_is_reused_rebuilt_on_request_and_never_prefills_the_practice_task(built):
    var, task, made = built
    assert create_reference_task(var) == {"id": made["id"], "created": False}

    practice = TaskStore(var).get(create_sample_task(var)["id"])
    dataset = next(row for row in AnalysisStore(practice).state()["datasets"] if row["name"] == AUGUST)
    proposal = FinanceStore(practice).structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]
    assert not proposal.get("template_matches")
    assert {row["kind"] for row in sample_status(var)["tasks"]} == {"reference", "practice"}

    rebuilt = create_reference_task(var, rebuild=True)
    assert rebuilt["created"] is True and rebuilt["id"] != made["id"]
    assert task.lifecycle_status() == "trashed"


def test_a_second_request_waits_for_the_reference_being_built(tmp_path, monkeypatch):
    import threading
    import time

    import foundry.sample_reference as reference

    started, var = threading.Event(), tmp_path / "var"

    def slow(task):
        started.set()
        time.sleep(12)  # longer than the ordinary 10-second lock wait
        return {}

    monkeypatch.setattr(reference, "build_reference", slow)
    first: dict = {}
    builder = threading.Thread(target=lambda: first.update(create_reference_task(var)))
    builder.start()
    started.wait(30)
    second = create_reference_task(var)
    builder.join()
    assert second == {"id": first["id"], "created": False}
