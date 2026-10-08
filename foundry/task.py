from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic as _write_json, write_text_atomic
from foundry.locking import exclusive

TASK_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SESSION_ROLES = ("author", "period", "followup", "analysis")
DELIVERABLE_KINDS = ("brief", "workpaper", "export")
WINDOW_REASONS = ("initial", "reimport")
TASK_LIFECYCLE_STATUSES = ("active", "archived", "trashed")
TASK_LOCK_TIMEOUT = 10.0


class Filed(NamedTuple):
    """One archived version, and whether this call is what archived it.

    ``register_bytes`` returns the prior row when the bytes are identical, so
    the row alone cannot say which of two things happened: a document was just
    written, or a re-render produced what was already on file. Both are normal
    -- `_register_period_outputs` runs on every `emit-brief` -- and a receipt
    that reported the second as the first would tell an operator a version
    exists that they have already seen, every time.
    """

    row: dict[str, Any]
    appended: bool

    def as_receipt(self) -> dict[str, Any]:
        return {**self.row, "appended": self.appended}


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
                "lifecycle_status": "active",
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

    def list(self, lifecycle: str = "active") -> list[Task]:
        if lifecycle not in (*TASK_LIFECYCLE_STATUSES, "all"):
            raise FoundryError(f"task lifecycle must be one of active, archived, trashed, all: {lifecycle}")
        ids = sorted(
            path.name
            for path in self.tasks_dir.iterdir()
            if path.is_dir() and TASK_ID_RE.match(path.name) and (path / "task.json").exists()
        )
        tasks = []
        for task_id in ids:
            task = Task(self, task_id)
            if lifecycle == "all" or task.lifecycle_status() == lifecycle:
                tasks.append(task)
        return sorted(tasks, key=lambda task: str(task.meta().get("created_at") or ""))

    def purge(self, task_id: str) -> list[str]:
        """Delete a task in the trash for good, and name the windows it held.

        Only a trashed task can go: archive and active are one step further
        from a deliberate "throw this away", and the caller asked for the
        trash. The directory is renamed out of the id namespace first, so a
        concurrent list never sees a half-deleted task, then removed. Window
        directories are not this store's to lay out; their ids are handed back
        for the caller to remove.
        """
        task = self.get(task_id)
        self.sweep_purged()
        with exclusive(task.lock_path, timeout=TASK_LOCK_TIMEOUT):
            if task.lifecycle_status() != "trashed":
                raise FoundryError(f"only a task in the trash can be deleted for good: {task.id}")
            windows = [str(row.get("window_id") or "") for row in task.windows()]
            tombstone = self.tasks_dir / f".purging-{task.id}-{uuid.uuid4().hex}"
            task.root.replace(tombstone)
        try:
            shutil.rmtree(tombstone)
        except OSError as exc:
            raise FoundryError("任务已经移出列表，但有文件没删掉；再清空一次回收站会接着删。") from exc
        current = self.current_path.read_text(encoding="utf-8").strip() if self.current_path.exists() else ""
        if current == task.id:
            self.clear_current()
        return [window for window in windows if window]

    def sweep_purged(self) -> None:
        """Finish deletions an earlier purge renamed out of the list but could not remove."""
        for path in self.tasks_dir.iterdir():
            if path.name.startswith(".purging-"):
                shutil.rmtree(path, ignore_errors=True)

    def current(self) -> Task | None:
        if not self.current_path.exists():
            return None
        task_id = self.current_path.read_text(encoding="utf-8").strip()
        if not TASK_ID_RE.match(task_id):
            return None
        task = Task(self, task_id)
        return task if task.meta_path.exists() and task.lifecycle_status() == "active" else None

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

    def clear_current(self) -> None:
        self.current_path.unlink(missing_ok=True)


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

    def lifecycle_status(self) -> str:
        status = str(self.meta().get("lifecycle_status") or "active")
        return status if status in TASK_LIFECYCLE_STATUSES else "active"

    def rename(self, title: str) -> dict[str, Any]:
        """Change the display title without moving the task or rewriting history."""
        if not isinstance(title, str) or not title.strip():
            raise FoundryError("task title is required")
        with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
            metadata = self.meta()
            metadata["title"] = title.strip()
            _write_json(self.meta_path, metadata)
            return metadata

    def set_lifecycle_status(self, status: str) -> dict[str, Any]:
        """Hide, recover or keep a task without moving or deleting its files."""
        if status not in TASK_LIFECYCLE_STATUSES:
            raise FoundryError(f"task lifecycle must be one of {TASK_LIFECYCLE_STATUSES}: {status}")
        with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
            metadata = self.meta()
            previous = str(metadata.get("lifecycle_status") or "active")
            if previous == status:
                return metadata
            metadata["lifecycle_status"] = status
            field = {
                "active": "restored_at",
                "archived": "archived_at",
                "trashed": "trashed_at",
            }[status]
            metadata[field] = now_iso()
            _write_json(self.meta_path, metadata)
        current = self.store.current_path.read_text(encoding="utf-8").strip() if self.store.current_path.exists() else ""
        if status != "active" and current == self.id:
            fallback = self.store.list("active")
            if fallback:
                self.store.set_current(fallback[-1].id)
            else:
                self.store.clear_current()
        elif status == "active" and current == "":
            self.store.set_current(self.id)
        return metadata

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
        window_id: str | None = None,
        parent_session_id: str | None = None,
        parent_context_revision: int | None = None,
        workspace_path: Path | None = None,
    ) -> dict[str, Any]:
        """Register a trusted session once, with a durable task/window context.

        Re-registering a session preserves its context. Explicit window/workspace
        changes create a revision; opening another task never changes this row.
        A registry-wide lock protects ownership across different task locks.
        """
        if role not in SESSION_ROLES:
            raise FoundryError(f"session role must be one of {SESSION_ROLES}: {role}")
        cleaned = str(session_id).strip()
        if not cleaned:
            raise FoundryError("session id is required")
        with exclusive(self.store.var_root / ".sessions.lock", timeout=TASK_LOCK_TIMEOUT):
            owner = session_owner(self.store, cleaned)
            if owner is not None and owner.id != self.id:
                raise FoundryError(
                    f"session {cleaned} already belongs to task {owner.id}; "
                    f"it cannot also be recorded on {self.id}"
                )
            parent = None
            if parent_session_id:
                if parent_session_id == cleaned:
                    raise FoundryError("a session cannot be its own parent")
                parent_owner = session_owner(self.store, parent_session_id)
                if parent_owner is None:
                    raise FoundryError(f"unknown parent session {parent_session_id}; register it first")
                if parent_owner.id != self.id:
                    raise FoundryError(f"parent session {parent_session_id} belongs to task {parent_owner.id}")
                parent = next(row for row in parent_owner.sessions() if row["session_id"] == parent_session_id)
                if parent_context_revision is not None and parent.get("context_revision", 1) != parent_context_revision:
                    historical = next((item for item in parent.get("context_history", []) if item.get("context_revision") == parent_context_revision), None)
                    if historical is None:
                        raise FoundryError("parent context revision is unavailable")
                    parent = {**parent, **historical}
            with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
                rows = self.sessions()
                existing = next((row for row in rows if row.get("session_id") == cleaned), None)
                if existing is not None and parent_session_id and existing.get("parent_session_id") != parent_session_id:
                    raise FoundryError("an existing session cannot change its parent")
                source = existing if existing is not None else parent
                target_window = window_id if window_id is not None else (source or {}).get("window_id")
                if source is None and target_window is None:
                    windows = self.windows()
                    target_window = windows[-1]["window_id"] if windows else None
                if source and (parent is not None or source.get("parent_session_id")):
                    if window_id is not None and window_id != source.get("window_id"):
                        raise FoundryError("a child session cannot widen its inherited window context")
                if target_window:
                    self._validate_session_window(target_window)
                workspace = str((source or {}).get("workspace_path") or (self.root / "analysis").resolve())
                if workspace_path is not None:
                    try:
                        resolved = Path(workspace_path).resolve(strict=True)
                    except OSError as exc:
                        raise FoundryError("session workspace must be an existing directory") from exc
                    if not resolved.is_dir():
                        raise FoundryError("session workspace must be a directory")
                    if source and (parent is not None or source.get("parent_session_id")) and str(resolved) != workspace:
                        raise FoundryError("a child session cannot change its inherited workspace")
                    workspace = str(resolved)
                if existing is None:
                    row = {
                        "session_id": cleaned, "task_id": self.id, "role": role,
                        "opened_at": now_iso(), "window_id": target_window,
                        "context_revision": 1, "workspace_id": self.id,
                        "workspace_path": workspace,
                        "snapshot_ids": list(parent.get("snapshot_ids") or []) if parent is not None else sorted(
                            path.parent.name for path in (self.root / "analysis" / "datasets").glob("*/meta.json")
                            if TASK_ID_RE.fullmatch(path.parent.name)
                        ),
                        "context_history": [],
                        **({} if parent is None else {
                            "parent_session_id": parent_session_id,
                            "parent_context_revision": parent.get("context_revision", 1),
                            "snapshot_ceiling": list(parent.get("snapshot_ids") or []),
                        }),
                        **({} if leader_verbatim is None else {"leader_verbatim": leader_verbatim}),
                    }
                    rows.append(row)
                else:
                    row = dict(existing)
                    # Older rows require explicit registration to acquire a
                    # window, rather than following whichever window is current.
                    row.setdefault("task_id", self.id)
                    row.setdefault("workspace_id", self.id)
                    row.setdefault("context_revision", 1)
                    row.setdefault("snapshot_ids", [])
                    row.setdefault("context_history", [])
                    if row.get("window_id") != target_window or row.get("workspace_path", workspace) != workspace:
                        row = self._revised_context(row, window_id=target_window, workspace_path=workspace)
                    row.setdefault("window_id", target_window)
                    row.setdefault("workspace_path", workspace)
                    if leader_verbatim is not None and not row.get("leader_verbatim"):
                        row["leader_verbatim"] = leader_verbatim
                    rows[rows.index(existing)] = row
                self._write_sessions(rows)
                return row

    def _validate_session_window(self, window_id: str) -> None:
        from foundry.window import WindowStore

        window = WindowStore(self.store.var_root).get(window_id)
        if window.task_id != self.id or window_id not in {row["window_id"] for row in self.windows()}:
            raise FoundryError(f"window {window_id} belongs to task {window.task_id}, not {self.id}")

    def _write_sessions(self, rows: list[dict[str, Any]]) -> None:
        write_text_atomic(self.sessions_path, "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ))

    @staticmethod
    def _revised_context(row: dict[str, Any], **changes: Any) -> dict[str, Any]:
        previous = {key: row.get(key) for key in (
            "context_revision", "window_id", "workspace_id", "workspace_path", "snapshot_ids"
        )}
        return {
            **row, **changes,
            "context_revision": int(row.get("context_revision", 1)) + 1,
            "context_history": [*row.get("context_history", []), previous],
            "context_updated_at": now_iso(),
        }

    def update_session_context(
        self, session_id: str, *, window_id: str | None = None,
        snapshot_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Advance only this registered session, retaining earlier revisions.

        Snapshot ids are immutable analysis dataset ids; legacy windows have a
        separate window_id field and never masquerade as analysis datasets.
        """
        cleaned = str(session_id).strip()
        with exclusive(self.store.var_root / ".sessions.lock", timeout=TASK_LOCK_TIMEOUT):
            owner = session_owner(self.store, cleaned)
            if owner is None or owner.id != self.id:
                raise FoundryError(f"session {cleaned} is not registered on task {self.id}")
            registered = next(row for row in self.sessions() if row["session_id"] == cleaned)
            if window_id is not None:
                self._validate_session_window(window_id)
            if snapshot_ids is not None:
                if registered.get("parent_session_id"):
                    ceiling = set(registered.get("snapshot_ceiling", registered.get("snapshot_ids", [])))
                    if not set(snapshot_ids).issubset(ceiling):
                        raise FoundryError("a child session cannot expand its inherited snapshot context")
                for snapshot_id in snapshot_ids:
                    if not TASK_ID_RE.fullmatch(str(snapshot_id)):
                        raise FoundryError(f"not a snapshot id: {snapshot_id}")
                    if not (self.root / "analysis" / "datasets" / snapshot_id / "meta.json").is_file():
                        raise FoundryError(f"snapshot {snapshot_id} is not registered on task {self.id}")
            with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
                rows = self.sessions()
                row = next(row for row in rows if row["session_id"] == cleaned)
                changes: dict[str, Any] = {}
                if window_id is not None and row.get("window_id") != window_id:
                    changes["window_id"] = window_id
                if snapshot_ids is not None:
                    # Concurrent imports append their immutable snapshots rather
                    # than dropping a snapshot added since the caller resolved.
                    merged = list(dict.fromkeys([*row.get("snapshot_ids", []), *snapshot_ids]))
                    if row.get("snapshot_ids", []) != merged:
                        changes["snapshot_ids"] = merged
                if not changes:
                    return row
                updated = self._revised_context(row, **changes)
                rows[rows.index(row)] = updated
                self._write_sessions(rows)
                return updated

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
        return self.register_bytes(
            window_id=window_id,
            kind=kind,
            data=text.encode("utf-8"),
            cause=cause,
            session_id=session_id,
            ext=ext,
        ).row

    def register_bytes(
        self,
        *,
        window_id: str,
        kind: str,
        data: bytes,
        cause: str,
        session_id: str | None = None,
        ext: str = ".md",
    ) -> Filed:
        """The same version row, for a document that is not text.

        A workbook is bytes and a brief is characters, and only one of those
        two facts should reach the versioning rules. Everything above this line
        -- the digest, the dedupe, the append under the task lock -- was already
        about bytes; it was just spelled in `str` because until now every
        deliverable was markdown.

        The row records `ext`. A reader has to know whether it may decode the
        artifact before it opens it, and a row that did not say would make the
        deliverables screen guess. Rows written before this field default to
        `.md`, which is what they are.
        """
        if kind not in DELIVERABLE_KINDS:
            raise FoundryError(f"deliverable kind must be one of {DELIVERABLE_KINDS}: {kind}")
        digest = sha256_bytes(data)
        with exclusive(self.lock_path, timeout=TASK_LOCK_TIMEOUT):
            rows = _read_jsonl(self.deliverables_path)
            prior = [
                row
                for row in rows
                if row.get("kind") == kind
                and row.get("window_id") == window_id
                and row.get("ext", ".md") == ext
            ]
            if prior and prior[-1].get("sha256") == digest:
                return Filed(prior[-1], appended=False)
            artifact = self.artifacts_dir / f"{digest}{ext}"
            if not artifact.exists():
                artifact.parent.mkdir(parents=True, exist_ok=True)
                tmp = artifact.with_name(f".{artifact.name}.{uuid.uuid4().hex}.tmp")
                try:
                    tmp.write_bytes(data)
                    tmp.replace(artifact)
                finally:
                    tmp.unlink(missing_ok=True)
            row = {
                "seq": len(rows) + 1,
                "kind": kind,
                "window_id": window_id,
                "sha256": digest,
                "bytes": len(data),
                "ext": ext,
                "cause": cause,
                "session_id": session_id,
                "at": now_iso(),
            }
            _append_jsonl(self.deliverables_path, row)
            return Filed(row, appended=True)

    def artifact_path(self, sha256: str, *, ext: str = ".md") -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", str(sha256)):
            raise FoundryError(f"not a sha256: {sha256}")
        path = self.artifacts_dir / f"{sha256}{ext}"
        if not path.is_file():
            raise FoundryError(f"no archived deliverable {sha256} on task {self.id}")
        return path

    def artifact_text(self, sha256: str, *, ext: str = ".md") -> str:
        """One archived version, decoded.

        Text only. A workbook is bytes and asking for it here would either
        raise deep in a decoder or hand back mojibake, so the caller is told to
        ask for the path instead -- which is what the app does with it anyway,
        since a spreadsheet opens in the operator's own spreadsheet software.
        """
        path = self.artifact_path(sha256, ext=ext)
        if ext != ".md":
            raise FoundryError(f"deliverable {sha256}{ext} is not text; ask for its path")
        return path.read_text(encoding="utf-8")


def register_window_deliverable(
    task: Task | None,
    *,
    window_id: str,
    kind: str,
    text: str,
    cause: str,
    session_id: str | None = None,
) -> Filed | None:
    """Register when the window has a task, do nothing when it does not.

    Every write site calls this rather than branching on its own. A window
    imported before this store existed, or one an operator drove straight
    through the CLI, still produces its documents -- it just has no timeline to
    hang them on until something adopts it.
    """
    if task is None:
        return None
    return task.register_bytes(
        window_id=window_id,
        kind=kind,
        data=text.encode("utf-8"),
        cause=cause,
        session_id=session_id,
    )


def session_owner(store: TaskStore, session_id: str) -> Task | None:
    """The task that already holds this conversation, if one does.

    A scan rather than an index, and that is a size judgement rather than a
    principle: a store holds one task per closing period, so this reads a few
    dozen small files on the calls that carry a session, and an index would be
    a second thing to keep true for no measured gain.
    """
    cleaned = str(session_id).strip()
    if not cleaned:
        return None
    for task in store.list("all"):
        for row in task.sessions():
            if row.get("session_id") == cleaned:
                return task
    return None


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
    session_id: str | None = None,
    env: dict[str, str] | None = None,
) -> Task | None:
    """Resolve registered sessions first, without ambient fallback.

    Sessionless operator calls retain explicit task, environment, and window
    back-pointer precedence. The CLI resolves the addressed task's window
    separately, so another task becoming current cannot redirect a session.
    """
    if session_id:
        task = session_owner(store, session_id)
        if task is None:
            raise FoundryError(f"unknown session {session_id}; run record-session before calling tools")
        if explicit and explicit != task.id:
            raise FoundryError(f"session {session_id} already belongs to task {task.id}, not {explicit}")
        for owner_id in window_task_ids:
            if owner_id and owner_id != task.id:
                raise FoundryError(f"session {session_id} already belongs to task {task.id}, not {owner_id}")
        return task
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
