"""Resolve durable call context before opening a mutable operation.

Session calls never use process environment or the global current selection.
The remaining fallback exists only for direct, sessionless operator CLI use.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from foundry.errors import FoundryError
from foundry.task import Task, TaskStore, resolve_task
from foundry.window import Window, WindowStore


@dataclass(frozen=True)
class CallContext:
    task: Task | None
    window: Window | None
    session_id: str | None = None
    context_revision: int | None = None
    snapshot_ids: tuple[str, ...] = ()
    workspace_id: str | None = None
    workspace_path: Path | None = None

    @property
    def task_id(self) -> str | None:
        return self.task.id if self.task else None

    @property
    def window_id(self) -> str | None:
        return self.window.id if self.window else None


def resolve_context(
    var_root: Path, *, session_id: str | None = None,
    task_id: str | None = None, window_id: str | None = None,
    require_window: bool = False,
) -> CallContext:
    root = Path(var_root)
    session_id = str(session_id or "").strip() or None
    if session_id and not (root / "tasks").is_dir():
        raise FoundryError(f"unknown session {session_id}; run record-session before calling tools")
    tasks = TaskStore(root)
    task = resolve_task(tasks, explicit=task_id, session_id=session_id)
    row = None
    if session_id:
        assert task is not None
        row = next(item for item in task.sessions() if item["session_id"] == session_id)
        window_id = window_id or row.get("window_id")
    store = WindowStore(root)
    window = store.get(window_id) if window_id else None
    if row is None:
        if window is None and task is not None:
            windows = task.windows()
            if windows:
                window = store.get(windows[-1]["window_id"])
        if window is None and require_window:
            candidate = store.current()
            # Preserve adoption of old unowned CLI windows without allowing an
            # explicit task to accidentally borrow another task's current one.
            if task is None or candidate.task_id in (None, task.id):
                window = candidate
        if task is None and window is not None and window.task_id:
            task = tasks.get(window.task_id)
        if task is None:
            task = tasks.current()
    if window is not None and task is not None and window.task_id not in (None, task.id):
        if session_id:
            raise FoundryError(f"session {session_id} already belongs to task {task.id}; window {window.id} belongs to task {window.task_id}")
        raise FoundryError(f"window {window.id} belongs to task {window.task_id}, not {task.id}")
    if session_id and window is not None and window.task_id != task.id:
        raise FoundryError(f"session {session_id} cannot access unregistered window {window.id}")
    if require_window and window is None:
        raise FoundryError("session has no bound window; create one or record-session --window" if session_id else "task has no window; run create")
    return CallContext(
        task=task, window=window, session_id=session_id,
        context_revision=int(row.get("context_revision", 1)) if row else None,
        snapshot_ids=tuple((row or {}).get("snapshot_ids", [])),
        workspace_id=(row or {}).get("workspace_id") or (task.id if task else None),
        workspace_path=Path(row["workspace_path"]) if row and row.get("workspace_path") else ((task.root / "analysis").resolve() if task else None),
    )
