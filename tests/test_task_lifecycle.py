from __future__ import annotations

import json
from pathlib import Path

from foundry.cli import main
from foundry.task import TaskStore, session_owner


def test_task_lifecycle_hides_without_deleting_and_restores(tmp_path: Path, capsys) -> None:
    var = tmp_path / "var"
    store = TaskStore(var)
    first = store.create(title="活跃")
    archived = store.create(title="归档")
    trashed = store.create(title="删除")
    (archived.root / "analysis" / "uploads").mkdir(parents=True)
    kept = archived.root / "analysis" / "uploads" / "source.csv"
    kept.write_text("amount\n1\n", encoding="utf-8")

    assert main(["--var", str(var), "--task", archived.id, "task-archive"]) == 0
    assert main(["--var", str(var), "--task", trashed.id, "task-trash"]) == 0
    capsys.readouterr()

    assert [task.id for task in store.list()] == [first.id]
    assert [task.id for task in store.list("archived")] == [archived.id]
    assert [task.id for task in store.list("trashed")] == [trashed.id]
    assert kept.read_text(encoding="utf-8") == "amount\n1\n"
    assert store.get(archived.id).meta()["lifecycle_status"] == "archived"

    assert main(["--var", str(var), "--task", archived.id, "task-restore"]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored == {"task_id": archived.id, "lifecycle_status": "active"}
    assert {task.id for task in store.list()} == {first.id, archived.id}


def test_lifecycle_moves_current_to_next_active_task(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "var")
    first = store.create(title="A")
    second = store.create(title="B")
    assert store.current().id == second.id

    second.set_lifecycle_status("archived")
    assert store.current().id == first.id

    first.set_lifecycle_status("trashed")
    assert store.current() is None

    second.set_lifecycle_status("active")
    assert store.current().id == second.id


def test_session_owner_scans_archived_tasks(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "var")
    task = store.create(title="已归档")
    task.record_session("session-a", role="analysis")
    task.set_lifecycle_status("archived")

    assert session_owner(store, "session-a").id == task.id


def test_task_list_lifecycle_filters(tmp_path: Path, capsys) -> None:
    var = tmp_path / "var"
    store = TaskStore(var)
    active = store.create(title="活跃")
    archived = store.create(title="归档")
    trashed = store.create(title="删除")
    archived.set_lifecycle_status("archived")
    trashed.set_lifecycle_status("trashed")

    assert main(["--var", str(var), "task-list"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == [active.id]

    assert main(["--var", str(var), "task-list", "--lifecycle", "archived"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == [archived.id]

    assert main(["--var", str(var), "task-list", "--lifecycle", "all"]) == 0
    assert {row["id"] for row in json.loads(capsys.readouterr().out)} == {active.id, archived.id, trashed.id}
