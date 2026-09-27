"""Durable task jobs provisioned by a trusted runtime broker.

Child agent IDs originate here, before the harness starts them. Script workers
run a saved request and context, not whichever task a UI later selects. Model
surfaces expose start/read/cancel/retry; started/settle are runtime-only hooks.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import uuid

from foundry.context import CallContext, resolve_context
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.task import TASK_ID_RE, Task, TaskStore, now_iso

TERMINAL = {"completed", "failed", "cancelled"}
COMMANDS = {
    "analysis-child-start", "analysis-script-start", "analysis-job-list",
    "analysis-job-show", "analysis-job-started", "analysis-job-settle",
    "analysis-job-cancel", "analysis-job-retry",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _object(value: str) -> dict[str, Any]:
    from decimal import Decimal
    from foundry.analysis_data import json_value, load_json

    raw = load_json(value)
    result = json_value(raw)
    # This is a resource duration, not a financial amount. Preserve Decimal
    # data elsewhere while handing the runner an ordinary seconds value.
    if isinstance(raw, dict) and isinstance(raw.get("timeout_seconds"), Decimal):
        result["timeout_seconds"] = float(raw["timeout_seconds"])
    if not isinstance(result, dict):
        raise FoundryError("job argument must be a JSON object")
    return result



def _elapsed(start: str, end: str) -> float:
    """Seconds between two of this module's stamps; they have seconds resolution, so this does too."""
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _process_identity(pid: int) -> dict[str, Any] | None:
    """Observe one process instance without signalling or stopping it.

    The birth stamp distinguishes a reused PID. An unreadable stamp is unknown,
    not evidence of termination; a zombie has already stopped executing.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return {"pid": pid, "birth": None}
    try:
        inspected = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "stat="],
            capture_output=True, text=True, timeout=2,
            env={"PATH": os.defpath, "LC_ALL": "C", "TZ": "UTC"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"pid": pid, "birth": None}
    fields = inspected.stdout.split()
    if inspected.returncode == 0 and len(fields) >= 6:
        if fields[-1].startswith("Z"):
            return None
        return {"pid": pid, "birth": " ".join(fields[:-1])}
    # The process can end between signal-zero and ps. Check that race without
    # treating an unavailable ps implementation as proof of an exited runtime.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    return {"pid": pid, "birth": None}


def _runtime_identity(pid: int | None) -> dict[str, Any] | None:
    if pid is None:
        return None
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise FoundryError("runtime pid must be a positive integer")
    identity = _process_identity(pid)
    if identity is None or not identity["birth"]:
        raise FoundryError("cannot verify the live runtime process identity")
    return identity

def _frozen(context: CallContext) -> dict[str, Any]:
    return {
        "task_id": context.task_id, "session_id": context.session_id,
        "context_revision": context.context_revision, "window_id": context.window_id,
        "snapshot_ids": list(context.snapshot_ids), "workspace_id": context.workspace_id,
        "workspace_path": str(context.workspace_path) if context.workspace_path else None,
    }


class JobStore:
    def __init__(self, task: Task):
        self.task = task
        self.root = task.root / "analysis" / "jobs"
        self.lock_path = task.root / ".jobs.lock"
        self._safe(self.root)

    def _safe(self, path: Path) -> Path:
        if not path.resolve().is_relative_to(self.task.root.resolve()):
            raise FoundryError("job path escapes its task")
        current = path
        while current != self.task.store.tasks_dir:
            if current.is_symlink():
                raise FoundryError("job paths cannot contain symbolic links")
            current = current.parent
        return path

    def _path(self, job_id: str) -> Path:
        if not TASK_ID_RE.fullmatch(str(job_id)):
            raise FoundryError("invalid job id")
        return self._safe(self.root / (job_id + ".json"))

    def _read(self, job_id: str) -> dict[str, Any]:
        try:
            record = json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FoundryError(f"job is unavailable: {job_id}") from exc
        if record.get("task_id") != self.task.id or record.get("id") != job_id:
            raise FoundryError("job belongs to another task")
        if record.get("spec_hash") != _digest(record["spec"]) or record.get("context_hash") != _digest(record["context"]):
            raise FoundryError("job request or context integrity check failed")
        return record

    def _write(self, record: dict[str, Any]) -> None:
        write_json_atomic(self._path(record["id"]), record)

    @staticmethod
    def _authorize(record: dict[str, Any], session_id: str | None) -> None:
        if session_id and record["session_id"] != session_id:
            raise FoundryError("job belongs to another session")

    def get(self, job_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        record = self._read(job_id)
        self._authorize(record, session_id)
        return record

    def refresh(self, job_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        record = self.get(job_id, session_id=session_id)
        if record["status"] in TERMINAL:
            return record
        identity = record.get("runtime_identity") if record["kind"] == "child" else (
            record.get("worker_identity") or ({"pid": record["worker_pid"], "birth": None} if record.get("worker_pid") else None)
        )
        if identity:
            observed = _process_identity(identity["pid"])
            exited = observed is None or (identity["birth"] and observed["birth"] and observed["birth"] != identity["birth"])
            if exited:
                label = "harness runtime" if record["kind"] == "child" else "script worker"
                return self.settle(job_id, "failed", {"error": f"{label} stopped before recording completion", "recovery": "process_instance_ended"},
                                   session_id=record["session_id"], child_session_id=record["child_session_id"])
        return record

    def list(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        records = [self.refresh(path.stem) for path in self.root.glob("*.json") if TASK_ID_RE.fullmatch(path.stem)]
        return sorted((row for row in records if not session_id or row["session_id"] == session_id), key=lambda row: (row["created_at"], row["id"]))

    def create(self, context: CallContext, kind: str, spec: dict[str, Any], *, retry_of: str | None = None,
               frozen_context: dict[str, Any] | None = None,
               runtime_pid: int | None = None) -> dict[str, Any]:
        if context.task_id != self.task.id or not context.session_id:
            raise FoundryError("jobs require a registered parent session")
        if kind not in {"child", "script"} or not isinstance(spec, dict):
            raise FoundryError("unknown job kind or invalid spec")
        # Read the registration, never a caller-supplied parent/child id.
        registered = next(row for row in self.task.sessions() if row["session_id"] == context.session_id)
        if kind == "child" and registered.get("parent_session_id"):
            raise FoundryError("child delegation depth is limited to one")
        frozen = frozen_context or _frozen(context)
        if frozen["task_id"] != self.task.id or frozen["session_id"] != context.session_id:
            raise FoundryError("job cannot change its original context owner")
        if kind == "child":
            if not isinstance(spec.get("prompt"), str) or not spec["prompt"].strip() or len(spec["prompt"]) > 32000:
                raise FoundryError("child prompt must contain 1 to 32000 characters")
            if spec.get("mode", "spawn") not in {"spawn", "fork"}:
                raise FoundryError("child mode must be spawn or fork")
            if not isinstance(spec.get("label", ""), str) or len(spec.get("label", "")) > 200:
                raise FoundryError("child label must be at most 200 characters")
            spec = {"prompt": spec["prompt"], "label": spec.get("label", "子任务"), "mode": spec.get("mode", "spawn")}
        else:
            bindings = spec.get("bindings", {})
            if not isinstance(bindings, dict) or any(not isinstance(value, str) for value in bindings.values()):
                raise FoundryError("script bindings must be a map of snapshot ids")
            if not set(bindings.values()).issubset(set(frozen["snapshot_ids"])):
                raise FoundryError("script snapshots are outside the frozen session context")
            requirements_id = spec.get("requirements_id")
            if requirements_id:
                from foundry.analysis import AnalysisStore

                requirements = AnalysisStore(self.task)._get("requirements", requirements_id)
                requirement_bindings = requirements.get("bindings", {})
                if (
                    not isinstance(requirement_bindings, dict)
                    or any(not isinstance(value, str) for value in requirement_bindings.values())
                    or not set(requirement_bindings.values()).issubset(set(frozen["snapshot_ids"]))
                ):
                    raise FoundryError("script requirements are outside the frozen session context")
            if not isinstance(spec.get("code"), str) or not spec["code"].strip() or len(spec["code"].encode()) > 256 * 1024:
                raise FoundryError("script code must contain 1 to 256 KiB of text")
        runtime_identity = _runtime_identity(runtime_pid) if kind == "child" else None
        record = {
            "id": uuid.uuid4().hex, "kind": kind, "task_id": self.task.id,
            "session_id": context.session_id, "child_session_id": uuid.uuid4().hex,
            "context_revision": frozen["context_revision"], "snapshot_ids": frozen["snapshot_ids"],
            "context": frozen, "context_hash": _digest(frozen), "spec": spec, "spec_hash": _digest(spec),
            "status": "queued", "created_at": now_iso(), "cancel_requested": False,
            "retry_of": retry_of, "result": None, "events": [],
            "runtime_identity": runtime_identity,
        }
        # Historical registration is required for retries and closes the race
        # between resolving a parent and that parent refreshing its snapshots.
        self.task.record_session(
            record["child_session_id"], role="analysis", parent_session_id=context.session_id,
            parent_context_revision=frozen["context_revision"],
        )
        with exclusive(self.lock_path, timeout=10):
            self._write(record)
        if kind == "script":
            self._launch(record)
            return self.get(record["id"], session_id=context.session_id)
        return record

    def _launch(self, record: dict[str, Any]) -> None:
        prefix = [sys.executable, "--_foundry-job-worker"] if getattr(sys, "frozen", False) else [sys.executable, "-E", "-m", "foundry.analysis_jobs"]
        try:
            process = subprocess.Popen(
                [*prefix, "--worker", record["id"],
                 "--var", str(self.task.store.var_root.resolve()), "--task", self.task.id],
                cwd=str(Path(__file__).resolve().parent.parent),
                env={"PATH": os.defpath, "LANG": "en_US.UTF-8"},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True,
            )
            with exclusive(self.lock_path, timeout=10):
                current = self.get(record["id"])
                current["worker_pid"] = process.pid
                current["worker_identity"] = _process_identity(process.pid)
                self._write(current)
        except OSError as exc:
            self.settle(record["id"], "failed", {"error": f"worker launch failed: {exc.strerror}"},
                        session_id=record["session_id"], child_session_id=record["child_session_id"])

    def started(self, job_id: str, *, session_id: str, child_session_id: str,
                runtime_pid: int | None = None) -> dict[str, Any]:
        identity = _runtime_identity(runtime_pid)
        with exclusive(self.lock_path, timeout=10):
            record = self.get(job_id, session_id=session_id)
            self._child(record, child_session_id)
            if identity and record.get("runtime_identity") not in (None, identity):
                raise FoundryError("job belongs to a different runtime process instance")
            if record["status"] != "queued":
                return record
            if identity:
                record["runtime_identity"] = identity
            record.update(status="running", started_at=now_iso())
            record["events"].append({"status": "running", "at": record["started_at"]})
            self._write(record)
            return record

    @staticmethod
    def _child(record: dict[str, Any], child_session_id: str) -> None:
        if record["child_session_id"] != child_session_id:
            raise FoundryError("runtime child id does not match the provisioned job")

    def settle(self, job_id: str, status: str, result: dict[str, Any], *, session_id: str,
               child_session_id: str) -> dict[str, Any]:
        if status not in TERMINAL or not isinstance(result, dict):
            raise FoundryError("job completion requires a terminal status and JSON result")
        if len(json.dumps(result).encode()) > 4 * 1024 * 1024:
            raise FoundryError("job result exceeds 4 MiB; store artifacts and return their ids")
        with exclusive(self.lock_path, timeout=10):
            record = self.get(job_id, session_id=session_id)
            self._child(record, child_session_id)
            if record["status"] in TERMINAL:
                return record
            record.update(status=status, result=result, finished_at=now_iso())
            # Kept on the job beside its result, so a cancelled, failed or timed-out job has a time even
            # when no run record was written; one that never started counts from when it was queued.
            record["duration_seconds"] = _elapsed(record.get("started_at") or record["created_at"], record["finished_at"])
            record["events"].append({"status": status, "at": record["finished_at"]})
            self._write(record)
            return record

    def cancel(self, job_id: str, *, session_id: str) -> dict[str, Any]:
        with exclusive(self.lock_path, timeout=10):
            record = self.get(job_id, session_id=session_id)
            if record["status"] in TERMINAL or record["cancel_requested"]:
                return record
            record.update(cancel_requested=True, cancel_requested_at=now_iso())
            self._write(record)
            return record

    def retry(self, job_id: str, context: CallContext, *, runtime_pid: int | None = None) -> dict[str, Any]:
        old = self.get(job_id, session_id=context.session_id)
        if old["status"] not in TERMINAL:
            raise FoundryError("wait for the existing job to finish or cancel before retrying")
        return self.create(context, old["kind"], old["spec"], retry_of=old["id"], frozen_context=old["context"], runtime_pid=runtime_pid)


def _worker(var_root: Path, task_id: str, job_id: str) -> None:
    from foundry.analysis import AnalysisStore

    jobs = JobStore(TaskStore(var_root).get(task_id))
    record = jobs.get(job_id)
    if record["kind"] != "script":
        raise FoundryError("the local worker only executes scripts")
    parent, child = record["session_id"], record["child_session_id"]
    # A live worker lock prevents a repeated dispatch from running a job twice.
    with exclusive(jobs.root / (job_id + ".worker.lock"), timeout=1):
        record = jobs.get(job_id)
        if record["status"] in TERMINAL:
            return
        if record["status"] == "running":
            jobs.settle(job_id, "failed", {"error": "previous worker was interrupted; retry creates a new job"},
                        session_id=parent, child_session_id=child)
            return
        jobs.started(job_id, session_id=parent, child_session_id=child)
        try:
            if jobs.get(job_id)["cancel_requested"]:
                jobs.settle(job_id, "cancelled", {}, session_id=parent, child_session_id=child)
                return
            run = AnalysisStore(jobs.task).run_script(
                record["spec"], session_id=child, context_revision=1,
                cancel_check=lambda: jobs.get(job_id)["cancel_requested"],
            )
            status = "completed" if run["execution_status"] == "succeeded" else ("cancelled" if run.get("runner_status") == "cancelled" else "failed")
            # Result rows that break the contract: the run still completed, and the assistant reads what to fix here.
            warnings = (run.get("row_declarations") or {}).get("warnings", [])
            jobs.settle(job_id, status, {"run_id": run["id"], "runner_status": run.get("runner_status"),
                                      "stdout": run.get("stdout", ""), "stderr": run.get("stderr", ""), "outputs": run.get("outputs", []),
                                      "warnings": warnings},
                        session_id=parent, child_session_id=child)
        except Exception as exc:
            jobs.settle(job_id, "failed", {"error": str(exc)}, session_id=parent, child_session_id=child)


def add_parsers(sub) -> None:
    for name in ("analysis-child-start", "analysis-script-start"):
        parser = sub.add_parser(name)
        parser.add_argument("--spec", required=True)
        if name == "analysis-child-start":
            parser.add_argument("--runtime-pid", type=int)
    sub.add_parser("analysis-job-list")
    for name in ("analysis-job-show", "analysis-job-cancel", "analysis-job-retry", "analysis-job-started", "analysis-job-settle"):
        parser = sub.add_parser(name)
        parser.add_argument("--job", required=True)
        if name in {"analysis-job-started", "analysis-job-retry"}:
            parser.add_argument("--runtime-pid", type=int)
        if name in {"analysis-job-started", "analysis-job-settle"}:
            parser.add_argument("--child-session", required=True)
        if name == "analysis-job-settle":
            parser.add_argument("--status", required=True, choices=sorted(TERMINAL))
            parser.add_argument("--result", default="{}")


def dispatch(args) -> bool:
    if args.cmd not in COMMANDS:
        return False
    context = resolve_context(Path(args.var), session_id=args.session or None, task_id=args.task or None)
    if context.task is None:
        raise FoundryError("jobs require a task")
    jobs = JobStore(context.task)
    if args.cmd in {"analysis-child-start", "analysis-script-start"}:
        result = jobs.create(context, "child" if args.cmd == "analysis-child-start" else "script", _object(args.spec), runtime_pid=getattr(args, "runtime_pid", None))
    elif args.cmd == "analysis-job-list":
        result = jobs.list(session_id=context.session_id)
    elif args.cmd == "analysis-job-show":
        result = jobs.refresh(args.job, session_id=context.session_id)
    else:
        if not context.session_id:
            raise FoundryError("changing a job requires its registered parent session")
        if args.cmd == "analysis-job-started":
            result = jobs.started(args.job, session_id=context.session_id, child_session_id=args.child_session, runtime_pid=args.runtime_pid)
        elif args.cmd == "analysis-job-settle":
            result = jobs.settle(args.job, args.status, _object(args.result), session_id=context.session_id, child_session_id=args.child_session)
        elif args.cmd == "analysis-job-cancel":
            result = jobs.cancel(args.job, session_id=context.session_id)
        else:
            result = jobs.retry(args.job, context, runtime_pid=args.runtime_pid)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return True


def worker_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--var", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    _worker(Path(args.var), args.task, args.worker)
    return 0


if __name__ == "__main__":
    sys.exit(worker_main())
