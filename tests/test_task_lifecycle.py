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


def test_purge_deletes_only_trashed_tasks_and_their_windows(tmp_path: Path, capsys) -> None:
    import pytest

    from foundry.errors import FoundryError
    from foundry.window import WindowStore

    var = tmp_path / "var"
    store = TaskStore(var)
    kept = store.create(title="保留")
    gone = store.create(title="删除")
    windows = WindowStore(var)
    owned = windows.create()
    owned.bind_task(gone.id)
    gone.bind_window(owned.id)
    other = windows.create(make_current=False)
    other.bind_task(kept.id)
    gone.bind_window(other.id)  # a chain row alone is not ownership

    with pytest.raises(FoundryError):
        store.purge(gone.id)
    assert main(["--var", str(var), "--task", gone.id, "task-purge"]) != 0
    assert gone.meta_path.exists()

    gone.set_lifecycle_status("trashed")
    owned.formulator_pid_path.parent.mkdir(parents=True, exist_ok=True)
    owned.formulator_pid_path.write_text("1\n", encoding="utf-8")
    assert main(["--var", str(var), "task-empty", "--lifecycle", "trashed"]) != 0
    assert gone.meta_path.exists() and owned.root.exists()
    owned.formulator_pid_path.unlink()
    capsys.readouterr()
    assert main(["--var", str(var), "--task", gone.id, "task-purge"]) == 0
    assert json.loads(capsys.readouterr().out) == {"task_ids": [gone.id], "lifecycle_status": "purged"}
    assert not gone.root.exists()
    assert not owned.root.exists()
    assert other.root.exists()
    assert not windows.current_path.exists()
    assert [task.id for task in store.list("all")] == [kept.id]
    assert [path.name for path in store.tasks_dir.iterdir() if path.name.startswith(".purging")] == []


def test_empty_archived_moves_to_trash_and_empty_trash_deletes(tmp_path: Path, capsys) -> None:
    var = tmp_path / "var"
    store = TaskStore(var)
    active = store.create(title="活跃")
    archived = [store.create(title=f"归档{index}") for index in range(2)]
    trashed = store.create(title="回收")
    for task in archived:
        task.set_lifecycle_status("archived")
    trashed.set_lifecycle_status("trashed")
    capsys.readouterr()

    assert main(["--var", str(var), "task-empty", "--lifecycle", "archived"]) == 0
    moved = json.loads(capsys.readouterr().out)
    assert moved["lifecycle_status"] == "trashed"
    assert sorted(moved["task_ids"]) == sorted(task.id for task in archived)
    assert store.list("archived") == []
    assert {task.id for task in store.list("trashed")} == {trashed.id, *(task.id for task in archived)}

    assert main(["--var", str(var), "task-empty", "--lifecycle", "trashed"]) == 0
    assert len(json.loads(capsys.readouterr().out)["task_ids"]) == 3
    assert [task.id for task in store.list("all")] == [active.id]

    assert main(["--var", str(var), "task-empty", "--lifecycle", "trashed"]) == 0
    assert json.loads(capsys.readouterr().out) == {"task_ids": [], "lifecycle_status": "purged"}
