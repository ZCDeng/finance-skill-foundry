from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.cli import main
from foundry.errors import FoundryError, WindowBusy
from foundry.locking import exclusive
from foundry.task import TaskStore


def test_rename_preserves_metadata_directory_and_history(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "var")
    task = store.create(title="原任务", period="2026-08", skill_id="monthly")
    task.record_session("session-one", role="analysis")
    task.bind_window("window-one")
    task.register_deliverable(window_id="window-one", kind="brief", text="原稿", cause="test")
    original = {**task.meta(), "future_extension": {"ledger": True}}
    task.meta_path.write_text(json.dumps(original), encoding="utf-8")
    history = {
        path.relative_to(task.root): path.read_bytes()
        for path in task.root.rglob("*")
        if path.is_file() and path != task.meta_path
    }
    task_root = task.root

    result = task.rename("  华北经营分析  ")

    assert result == {**original, "title": "华北经营分析"}
    assert task.meta() == result
    assert task.root == task_root
    assert store.current().id == task.id
    assert {path: (task.root / path).read_bytes() for path in history} == history


@pytest.mark.parametrize("title", ["", " \t\n", None, 123])
def test_invalid_rename_has_no_effect(tmp_path: Path, title: object) -> None:
    task = TaskStore(tmp_path / "var").create(title="原任务")
    before = task.meta_path.read_bytes()
    with pytest.raises(FoundryError, match="title"):
        task.rename(title)
    assert task.meta_path.read_bytes() == before
    assert not task.lock_path.exists()


def test_rename_obeys_existing_task_lock(tmp_path: Path) -> None:
    task = TaskStore(tmp_path / "var").create(title="原任务")
    with exclusive(task.lock_path):
        with pytest.raises(WindowBusy):
            task.rename("新标题")
    assert task.meta()["title"] == "原任务"


@pytest.mark.parametrize("task_before_command", [False, True])
def test_cli_rename_returns_json_and_updates_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], task_before_command: bool
) -> None:
    var = tmp_path / "var"
    task = TaskStore(var).create(title="原任务")
    target = ["--task", task.id]
    command = [*target, "task-rename"] if task_before_command else ["task-rename", *target]
    assert main(["--var", str(var), *command, "--title", "新标题"]) == 0
    assert json.loads(capsys.readouterr().out) == {"task_id": task.id, "title": "新标题"}
    assert main(["--var", str(var), "task-list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["title"] == "新标题"


def test_cli_rename_requires_explicit_task_and_respects_session_binding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    store = TaskStore(var)
    first = store.create(title="A")
    second = store.create(title="B")
    first.record_session("session-A", role="analysis")
    assert main(["--var", str(var), "task-rename", "--title", "no"]) == 3
    capsys.readouterr()
    assert main([
        "--var", str(var), "--session", "session-A", "task-rename",
        "--task", second.id, "--title", "no",
    ]) == 3
    capsys.readouterr()
    assert first.meta()["title"] == "A"
    assert second.meta()["title"] == "B"
