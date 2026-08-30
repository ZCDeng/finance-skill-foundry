from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic as _write_json
from foundry.locking import exclusive

TASK_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SESSION_ROLES = ("author", "period", "followup")
DELIVERABLE_KINDS = ("brief", "workpaper", "export")
WINDOW_REASONS = ("initial", "reimport")
TASK_LOCK_TIMEOUT = 10.0


def now_iso() -> str:
    """One spelling of "when" for everything this module appends.

    The window store records no times at all, so there is no house convention
    to follow; this establishes one. Seconds resolution in UTC with a ``Z``
    suffix sorts lexicographically, which is the only thing the timeline views
    ask of it.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


class TaskStore:
    """The task root, one level above windows.

    A window is a caliber lock and a re-import opens a successor, so one
    closing period is already several windows and the old brief's follow-ups
    stay on the old one. The task is what makes those one thing. It owns no
    catalog and holds no numbers -- it holds ids, and the bytes of what was
    handed out.
    """

    def __init__(self, var_root: Path) -> None:
        self.var_root = Path(var_root)
        self.tasks_dir = self.var_root / "tasks"
        self.current_path = self.var_root / "current-task"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        title: str,
        period: str | None = None,
        skill_id: str | None = None,
        make_current: bool = True,
    ) -> Task:
        cleaned = str(title).strip()
        if not cleaned:
            raise FoundryError("task title is required")
        task_id = uuid.uuid4().hex
        task = Task(self, task_id)
        task.root.mkdir(parents=True, exist_ok=True)
        _write_json(
            task.meta_path,
            {
                "id": task_id,
                "title": cleaned,
                "period": period,
                "skill_id": skill_id,
                "created_at": now_iso(),
            },
        )
        if make_current:
            self.set_current(task_id)
        return task

    def get(self, task_id: str) -> Task:
        if not TASK_ID_RE.match(str(task_id)):
            raise FoundryError(f"not a task id: {task_id}")
        task = Task(self, str(task_id))
        if not task.meta_path.exists():
            raise FoundryError(f"no such task: {task_id}")
        return task

    def list(self) -> list[Task]:
        ids = sorted(
            path.name
            for path in self.tasks_dir.iterdir()
            if path.is_dir() and TASK_ID_RE.match(path.name) and (path / "task.json").exists()
        )
        tasks = [Task(self, task_id) for task_id in ids]
        return sorted(tasks, key=lambda task: str(task.meta().get("created_at") or ""))

    def current(self) -> Task | None:
        if not self.current_path.exists():
            return None
        task_id = self.current_path.read_text(encoding="utf-8").strip()
        if not TASK_ID_RE.match(task_id):
            return None
        task = Task(self, task_id)
        return task if task.meta_path.exists() else None

    def set_current(self, task_id: str) -> None:
        if not TASK_ID_RE.match(str(task_id)):
            raise FoundryError(f"not a task id: {task_id}")
        self.current_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.current_path.with_name(f".current-task.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(f"{task_id}\n", encoding="utf-8")
            tmp.replace(self.current_path)
        finally:
            tmp.unlink(missing_ok=True)


@dataclass
class Task:
    store: TaskStore
    id: str

    @property
    def root(self) -> Path:
        return self.store.tasks_dir / self.id

    @property
    def meta_path(self) -> Path:
        return self.root / "task.json"

    @property
    def windows_path(self) -> Path:
        return self.root / "windows.jsonl"

    @property
    def sessions_path(self) -> Path:
        return self.root / "sessions.jsonl"

    @property
    def deliverables_path(self) -> Path:
        return self.root / "deliverables.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def lock_path(self) -> Path:
        return self.root / ".lock"

    def meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            raise FoundryError(f"no such task: {self.id}")
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    # -- windows ---------------------------------------------------------

    def windows(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.windows_path)

    def bind_window(self, window_id: str, *, reason: str = "initial") -> dict[str, Any]:
        """Append a window to this task's chain, once.

        Idempotent on the window id, because adoption-on-touch means every
        later operation on an already-bound window calls this again. The first
        binding's reason is the one that stands: a window that entered as the
        initial import does not become a re-import because something touched it
        afterwards.
        """
        if reason not in WINDOW_REASONS:
            raise FoundryError(f"window reason must be one of {WINDOW_REASONS}: {reason}")
        with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
            for row in _read_jsonl(self.windows_path):
                if row.get("window_id") == window_id:
                    return row
            row = {"window_id": window_id, "reason": reason, "at": now_iso()}
            _append_jsonl(self.windows_path, row)
            return row

    # -- sessions --------------------------------------------------------

    def sessions(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.sessions_path)

    def record_session(
        self,
        session_id: str,
        *,
        role: str,
        leader_verbatim: str | None = None,
    ) -> dict[str, Any]:
        """Register a conversation against this task.

        ``leader_verbatim`` is what the leader actually asked, in their own
        words, and it is deliberately not the ``text`` a model later passes to
        ``query-locked``. A model may paraphrase, narrow, or split one question
        into two; what was asked and what was computed are two columns that have
        to be readable side by side. It is written by the operator, once, when
        the follow-up conversation opens -- never inferred from a tool argument.
        """
        if role not in SESSION_ROLES:
            raise FoundryError(f"session role must be one of {SESSION_ROLES}: {role}")
        cleaned = str(session_id).strip()
        if not cleaned:
            raise FoundryError("session id is required")
        with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
            existing = _read_jsonl(self.sessions_path)
            for row in existing:
                if row.get("session_id") == cleaned:
                    if leader_verbatim is None or row.get("leader_verbatim"):
                        return row
                    # The session was first seen through a tool call, which
                    # carries no verbatim. Filling it in later is the operator
                    # supplying what was missing, not overwriting an answer.
                    updated = {**row, "leader_verbatim": leader_verbatim}
                    rows = [updated if item is row else item for item in existing]
                    text = "".join(
                        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows
                    )
                    self.sessions_path.write_text(text, encoding="utf-8")
                    return updated
            row = {
                "session_id": cleaned,
                "role": role,
                "opened_at": now_iso(),
                **({} if leader_verbatim is None else {"leader_verbatim": leader_verbatim}),
            }
            _append_jsonl(self.sessions_path, row)
            return row

    # -- deliverables ----------------------------------------------------

    def deliverables(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.deliverables_path)

    def register_deliverable(
        self,
        *,
        window_id: str,
        kind: str,
        text: str,
        cause: str,
        session_id: str | None = None,
        ext: str = ".md",
    ) -> dict[str, Any]:
        """Record one version of a produced document, by its bytes.

        The live file stays in the window directory for a human to open. This
        copy is the immutable history: a follow-up rewrites ``workpaper.md`` in
        place, so without a version per write the audit trail holds a filename
        and no way to say which answer came from which shape of it.

        A re-render that produced identical bytes appends nothing. That is not
        a new version, and a timeline showing it as one would be lying about
        what changed.
        """
        if kind not in DELIVERABLE_KINDS:
            raise FoundryError(f"deliverable kind must be one of {DELIVERABLE_KINDS}: {kind}")
        digest = sha256_text(text)
        with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
            rows = _read_jsonl(self.deliverables_path)
            prior = [
                row for row in rows if row.get("kind") == kind and row.get("window_id") == window_id
            ]
            if prior and prior[-1].get("sha256") == digest:
                return prior[-1]
            artifact = self.artifacts_dir / f"{digest}{ext}"
            if not artifact.exists():
                artifact.parent.mkdir(parents=True, exist_ok=True)
                tmp = artifact.with_name(f".{artifact.name}.{uuid.uuid4().hex}.tmp")
                try:
                    tmp.write_text(text, encoding="utf-8")
                    tmp.replace(artifact)
                finally:
                    tmp.unlink(missing_ok=True)
            row = {
                "seq": len(rows) + 1,
                "kind": kind,
                "window_id": window_id,
                "sha256": digest,
                "bytes": len(text.encode("utf-8")),
                "cause": cause,
                "session_id": session_id,
                "at": now_iso(),
            }
            _append_jsonl(self.deliverables_path, row)
            return row

    def artifact_text(self, sha256: str, *, ext: str = ".md") -> str:
        path = self.artifacts_dir / f"{sha256}{ext}"
        if not path.is_file():
            raise FoundryError(f"no archived deliverable {sha256} on task {self.id}")
        return path.read_text(encoding="utf-8")


def register_window_deliverable(
    task: Task | None,
    *,
    window_id: str,
    kind: str,
    text: str,
    cause: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Register when the window has a task, do nothing when it does not.

    Every write site calls this rather than branching on its own. A window
    imported before this store existed, or one an operator drove straight
    through the CLI, still produces its documents -- it just has no timeline to
    hang them on until something adopts it.
    """
    if task is None:
        return None
    return task.register_deliverable(
        window_id=window_id,
        kind=kind,
        text=text,
        cause=cause,
        session_id=session_id,
    )


def task_for(var_root: Path, task_id: str | None) -> Task | None:
    """The task a window's back-pointer names, or nothing.

    Takes the id rather than the window so this module never imports the window
    store: a task holds ids and bytes, and knowing how a window is laid out is
    not its business.
    """
    if not task_id:
        return None
    return TaskStore(Path(var_root)).get(task_id)


def resolve_task(
    store: TaskStore,
    *,
    explicit: str | None = None,
    window_task_ids: tuple[str | None, ...] = (),
    env: dict[str, str] | None = None,
) -> Task | None:
    """Decide which task a call belongs to. Code decides; no model is asked.

    First hit wins:

    1. an explicit ``--task``
    2. ``FOUNDRY_TASK`` in the environment, which the app sets when it opens a
       session
    3. the back-pointer of a window the caller already named -- the brief's
       window for a follow-up, the current window for a period step
    4. nothing, and the call is recorded unassigned

    The session id is deliberately absent from this chain. One dsh process
    hosts many conversations, so a session cannot come from the environment;
    it arrives per call from the runtime and is passed through separately.
    """
    environ = os.environ if env is None else env
    if explicit:
        return store.get(explicit)
    from_env = str(environ.get("FOUNDRY_TASK") or "").strip()
    if from_env:
        return store.get(from_env)
    for task_id in window_task_ids:
        if task_id:
            return store.get(task_id)
    return None
