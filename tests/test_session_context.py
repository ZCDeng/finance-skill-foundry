from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.cli import main
from foundry.resources import fixture_root
from foundry.task import TaskStore
from foundry.window import WindowStore


def _setup(var: Path, title: str, session: str):
    task = TaskStore(var).create(title=title)
    window = WindowStore(var).create()
    window.bind_task(task.id)
    task.bind_window(window.id)
    task.record_session(session, role="period", window_id=window.id)
    return task, window


def _bytes(var: Path):
    return {str(path.relative_to(var)): path.read_bytes() for path in var.rglob("*") if path.is_file()}


def test_session_import_uses_its_window_after_another_task_becomes_current(tmp_path: Path, capsys):
    var = tmp_path / "var"
    task_a, window_a = _setup(var, "A", "session-A")
    _, window_b = _setup(var, "B", "session-B")
    before = _bytes(window_b.root)
    fixtures = fixture_root(None)
    assert main(["--var", str(var), "--session", "session-A", "import", "--coa", str(fixtures / "coa.xlsx"), "--named", str(fixtures / "named.json")]) == 0
    assert window_a.state == "Imported"
    assert window_b.state == "Open"
    assert _bytes(window_b.root) == before
    assert task_a.sessions()[0]["window_id"] == window_a.id


def test_explicit_task_uses_its_latest_window(tmp_path: Path):
    var = tmp_path / "var"
    task_a, window_a = _setup(var, "A", "session-A")
    _, window_b = _setup(var, "B", "session-B")
    fixtures = fixture_root(None)
    assert main(["--var", str(var), "--task", task_a.id, "import", "--coa", str(fixtures / "coa.xlsx"), "--named", str(fixtures / "named.json")]) == 0
    assert window_a.state == "Imported"
    assert window_b.state == "Open"


@pytest.mark.parametrize("command", [["create"], ["task-show"], ["task-new", "--title", "no"], ["import"]])
def test_unknown_session_is_refused_without_writes(tmp_path: Path, command):
    var = tmp_path / "var"
    _setup(var, "A", "session-A")
    before = _bytes(var)
    assert main(["--var", str(var), "--session", "unknown", *command]) == 3
    assert _bytes(var) == before


def test_unknown_session_does_not_initialize_an_empty_store(tmp_path: Path):
    var = tmp_path / "absent"
    assert main(["--var", str(var), "--session", "unknown", "create"]) == 3
    assert not var.exists()


def test_child_inherits_parent_window_without_global_current(tmp_path: Path, capsys):
    var = tmp_path / "var"
    task_a, window_a = _setup(var, "A", "session-A")
    _setup(var, "B", "session-B")
    assert main(["--var", str(var), "--session", "child", "record-session", "--role", "analysis", "--parent-session", "session-A"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["task_id"] == task_a.id
    assert row["window_id"] == window_a.id
    assert row["parent_session_id"] == "session-A"
    assert row["context_revision"] == 1


def test_create_advances_only_the_calling_session(tmp_path: Path, capsys):
    var = tmp_path / "var"
    task, window = _setup(var, "A", "old")
    task.record_session("active", role="analysis", parent_session_id="old")
    assert main(["--var", str(var), "--session", "active", "create"]) == 0
    new_id = capsys.readouterr().out.strip()
    by_id = {row["session_id"]: row for row in task.sessions()}
    assert by_id["old"]["window_id"] == window.id
    assert by_id["active"]["window_id"] == new_id
    assert by_id["active"]["context_revision"] == 2
    assert by_id["active"]["context_history"][0]["window_id"] == window.id


def test_registration_refuses_foreign_parent_and_window_without_mutation(tmp_path: Path):
    var = tmp_path / "var"
    task_a, _ = _setup(var, "A", "session-A")
    _, window_b = _setup(var, "B", "session-B")
    before = _bytes(var)
    for extra in (["--window", window_b.id], ["--parent-session", "session-B"]):
        assert main(["--var", str(var), "--task", task_a.id, "--session", "child", "record-session", "--role", "analysis", *extra]) == 3
    assert _bytes(var) == before


def test_reimport_advances_only_active_session_and_preserves_older_snapshot(tmp_path: Path, capsys):
    from foundry.context import resolve_context

    var = tmp_path / "var"
    task, old = _setup(var, "A", "history")
    task.record_session("active", role="period", parent_session_id="history")
    _setup(var, "B", "other-task")
    fixtures = fixture_root(None)
    assert main(["--var", str(var), "--session", "active", "re-import", "--coa", str(fixtures / "coa.xlsx"), "--named", str(fixtures / "named.json")]) == 0
    successor = capsys.readouterr().out.strip()
    assert resolve_context(var, session_id="active", require_window=True).window_id == successor
    assert resolve_context(var, session_id="history", require_window=True).window_id == old.id
    assert old.task_id == task.id
    assert task.sessions()[0]["context_revision"] == 1
    assert resolve_context(var, session_id="active").context_revision == 2


def test_session_ignores_process_task_and_refuses_foreign_explicit_task(tmp_path: Path, monkeypatch):
    from foundry.context import resolve_context

    var = tmp_path / "var"
    task_a, window_a = _setup(var, "A", "session-A")
    task_b, _ = _setup(var, "B", "session-B")
    monkeypatch.setenv("FOUNDRY_TASK", task_b.id)
    context = resolve_context(var, session_id="session-A", require_window=True)
    assert (context.task_id, context.window_id) == (task_a.id, window_a.id)
    before = _bytes(var)
    assert main(["--var", str(var), "--session", "session-A", "--task", task_b.id, "create"]) == 3
    assert _bytes(var) == before


def test_session_without_window_does_not_borrow_current(tmp_path: Path):
    from foundry.context import resolve_context
    from foundry.errors import FoundryError

    var = tmp_path / "var"
    task = TaskStore(var).create(title="new analysis")
    task.record_session("empty", role="analysis")
    _setup(var, "B", "session-B")
    assert resolve_context(var, session_id="empty").window is None
    before = _bytes(var)
    with pytest.raises(FoundryError, match="no bound window"):
        resolve_context(var, session_id="empty", require_window=True)
    assert _bytes(var) == before


def test_workspace_and_revision_inherit_and_invalid_workspace_is_refused(tmp_path: Path, capsys):
    from foundry.context import resolve_context

    var = tmp_path / "var"
    task, window = _setup(var, "A", "parent")
    workspace = tmp_path / "task workspace"
    workspace.mkdir()
    assert main(["--var", str(var), "--task", task.id, "--session", "parent", "record-session", "--role", "analysis", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    task.record_session("child", role="analysis", parent_session_id="parent")
    child = resolve_context(var, session_id="child")
    assert child.workspace_path == workspace.resolve()
    assert child.workspace_id == task.id
    assert child.window_id == window.id
    assert task.sessions()[1]["parent_context_revision"] == 2
    before = _bytes(var)
    assert main(["--var", str(var), "--task", task.id, "--session", "bad", "record-session", "--workspace", str(tmp_path / "missing")]) == 3
    assert _bytes(var) == before


def _snapshot(task, snapshot_id: str):
    folder = task.root / "analysis" / "datasets" / snapshot_id
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"id": snapshot_id}))


def test_new_session_sees_existing_data_while_child_and_existing_sessions_stay_pinned(tmp_path: Path):
    from foundry.context import resolve_context

    var = tmp_path / "var"
    task = TaskStore(var).create(title="analysis")
    task.record_session("before-import", role="analysis")
    first, second = "a" * 32, "b" * 32
    _snapshot(task, first)
    task.record_session("after-import", role="analysis")
    _snapshot(task, second)
    task.record_session("child", role="analysis", parent_session_id="after-import")
    assert resolve_context(var, session_id="before-import").snapshot_ids == ()
    assert resolve_context(var, session_id="after-import").snapshot_ids == (first,)
    assert resolve_context(var, session_id="child").snapshot_ids == (first,)
    task.update_session_context("after-import", snapshot_ids=[second])
    after = resolve_context(var, session_id="after-import")
    assert after.snapshot_ids == (first, second)
    assert after.context_revision == 2
    assert resolve_context(var, session_id="child").snapshot_ids == (first,)


def test_snapshot_context_cannot_adopt_another_tasks_data(tmp_path: Path):
    from foundry.errors import FoundryError

    var = tmp_path / "var"
    a, _ = _setup(var, "A", "session-A")
    b, _ = _setup(var, "B", "session-B")
    foreign = "b" * 32
    _snapshot(b, foreign)
    before = _bytes(var)
    with pytest.raises(FoundryError, match="not registered on task"):
        a.update_session_context("session-A", snapshot_ids=[foreign])
    assert _bytes(var) == before


def test_two_processes_cannot_register_one_session_on_different_tasks(tmp_path: Path):
    import subprocess
    import sys
    import time

    var = tmp_path / "var"
    tasks = TaskStore(var)
    a, b = tasks.create(title="A"), tasks.create(title="B")
    script = """
import sys, time
from pathlib import Path
from foundry.task import TaskStore
from foundry.errors import FoundryError
while time.time() < float(sys.argv[3]):
    time.sleep(0.005)
try:
    TaskStore(Path(sys.argv[1])).get(sys.argv[2]).record_session('shared', role='analysis')
except FoundryError:
    sys.exit(3)
"""
    start = str(time.time() + 0.5)
    children = [subprocess.Popen([sys.executable, "-c", script, str(var), task.id, start]) for task in (a, b)]
    assert sorted(child.wait(timeout=15) for child in children) == [0, 3]
    assert sum(len(task.sessions()) for task in (a, b)) == 1


def test_two_processes_append_snapshot_context_without_lost_ids(tmp_path: Path):
    import subprocess
    import sys
    import time

    var = tmp_path / "var"
    task = TaskStore(var).create(title="A")
    task.record_session("shared", role="analysis")
    snapshots = ["a" * 32, "b" * 32]
    for snapshot in snapshots:
        _snapshot(task, snapshot)
    script = """
import sys, time
from pathlib import Path
from foundry.task import TaskStore
while time.time() < float(sys.argv[4]):
    time.sleep(0.005)
TaskStore(Path(sys.argv[1])).get(sys.argv[2]).update_session_context('shared', snapshot_ids=[sys.argv[3]])
"""
    start = str(time.time() + 0.5)
    children = [subprocess.Popen([sys.executable, "-c", script, str(var), task.id, snapshot, start]) for snapshot in snapshots]
    assert [child.wait(timeout=15) for child in children] == [0, 0]
    row = task.sessions()[0]
    assert set(row["snapshot_ids"]) == set(snapshots)
    assert row["context_revision"] == 3
    assert len(row["context_history"]) == 2


def test_child_cannot_adopt_new_parent_snapshots_after_creation(tmp_path: Path):
    from foundry.errors import FoundryError

    var = tmp_path / "var"
    task = TaskStore(var).create(title="analysis")
    first, second = "a" * 32, "b" * 32
    _snapshot(task, first)
    task.record_session("parent", role="analysis")
    task.record_session("child", role="analysis", parent_session_id="parent")
    _snapshot(task, second)
    task.update_session_context("parent", snapshot_ids=[second])
    before = _bytes(var)
    with pytest.raises(FoundryError, match="cannot expand"):
        task.update_session_context("child", snapshot_ids=[first, second])
    assert _bytes(var) == before
