"""Persistent operation state for bounded finance explanation completion.

This module owns only the durable bookkeeping for a runtime-driven finish
operation. It does not submit model turns, decide requirement quality, or expose
schema to the model.
"""

from __future__ import annotations

import json
import math
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from foundry.analysis import AnalysisStore, _hash, _new
from foundry.analysis_data import json_value
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.task import Task

DEFAULT_TIMEOUT_SECONDS = 420
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_REPAIRS = 2
MAX_REPAIRS_CAP = 2
POLICY_KEYS = {"max_repairs", "timeout_seconds"}
TERMINAL = {"complete", "awaiting_input", "needs_review", "timed_out", "cancelled", "failed"}
ATTEMPT_TERMINAL = {"settled", "rejected_validation", "failed_execution"}

Clock = Callable[[], datetime | int | float]


def _utc_now(clock: Clock | None) -> datetime:
    value = clock() if clock else datetime.now(timezone.utc)
    if isinstance(value, bool):
        raise FoundryError("clock returned an invalid time")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise FoundryError("clock returned an invalid time")
        return datetime.fromtimestamp(float(value), timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raise FoundryError("clock returned an invalid time")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise FoundryError(f"completion operation {label} is invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise FoundryError(f"completion operation {label} is invalid") from exc


def _safe_text(value: Any, label: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value or len(value) > maximum:
        raise FoundryError(f"{label} must be nonempty text at most {maximum} characters")
    return value


def _operation_id(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 32:
        raise FoundryError("invalid completion operation id")
    try:
        int(value, 16)
    except ValueError as exc:
        raise FoundryError("invalid completion operation id") from exc
    return value


def _revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FoundryError("operation revision must be a positive integer")
    return value


def _json(value: Any, label: str) -> Any:
    try:
        return json_value(value)
    except (TypeError, ValueError) as exc:
        raise FoundryError(f"completion operation {label} must be finite JSON") from exc


def _canonical_hash(value: Any) -> str:
    return _hash(_json(value, "payload"))


def _policy(spec: dict[str, Any] | None) -> dict[str, Any]:
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise FoundryError("completion policy must be an object")
    unknown = set(spec) - POLICY_KEYS
    if unknown:
        raise FoundryError("completion policy contains unknown keys")
    max_repairs = spec.get("max_repairs", DEFAULT_MAX_REPAIRS)
    if isinstance(max_repairs, bool) or not isinstance(max_repairs, int) or not 0 <= max_repairs <= MAX_REPAIRS_CAP:
        raise FoundryError("completion max_repairs must be an integer from 0 to 2")
    timeout = spec.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise FoundryError("completion timeout_seconds must be an integer from 1 to 3600")
    return {"version": 1, "max_repairs": max_repairs, "timeout_seconds": timeout}


def _extract_snapshots(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "dataset_id" and isinstance(item, str):
                found.add(item)
            elif key == "snapshot_ids" and isinstance(item, list):
                found.update(child for child in item if isinstance(child, str))
            elif key == "bindings" and isinstance(item, dict):
                found.update(child for child in item.values() if isinstance(child, str))
            found.update(_extract_snapshots(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_extract_snapshots(item))
    return found


def _public(record: dict[str, Any], *, replayed: bool = False, reservation_replayed: bool = False) -> dict[str, Any]:
    result = deepcopy(record)
    result.pop("_integrity_hash", None)
    if replayed:
        result["replayed"] = True
    if reservation_replayed:
        result["reservation_replayed"] = True
    return result




def _task_inside(task: Task, path: Path) -> Path:
    task_root = task.root.resolve()
    if not path.resolve().is_relative_to(task_root):
        raise FoundryError("completion operation path escapes this task")
    current = path
    while True:
        if current.is_symlink():
            raise FoundryError("completion operation paths cannot use symbolic links")
        if current.resolve() == task_root:
            break
        if current == current.parent:
            raise FoundryError("completion operation path has no task ancestor")
        current = current.parent
    return path


def _operation_root(task: Task) -> Path:
    return _task_inside(task, task.root / "analysis" / "completion_operations")


def _operation_path(task: Task, operation_id: str) -> Path:
    return _task_inside(task, _operation_root(task) / f"{_operation_id(operation_id)}.json")


def _read_operation_path(task: Task, path: Path) -> dict[str, Any]:
    path = _task_inside(task, path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FoundryError("completion operation is unavailable") from exc
    check = dict(record)
    digest = check.pop("_integrity_hash", None)
    if not digest or digest != _hash(check) or record.get("task_id") != task.id or record.get("id") != path.stem:
        raise FoundryError("completion operation integrity check failed")
    return record


def _write_operation(task: Task, record: dict[str, Any]) -> None:
    record = json_value(record)
    record.pop("_integrity_hash", None)
    record["_integrity_hash"] = _hash(record)
    write_json_atomic(_operation_path(task, record["id"]), record)


def _expire_record_locked(task: Task, record: dict[str, Any], clock: Clock | None) -> dict[str, Any]:
    if record["status"] in TERMINAL:
        return record
    if _utc_now(clock) < _parse_iso(record.get("deadline_at"), "deadline"):
        return record
    now = _iso(_utc_now(clock))
    record["status"] = "timed_out"
    record["stop_reason"] = "timeout"
    record["updated_at"] = now
    record["finished_at"] = now
    record["events"].append({"type": "operation_status", "status": "timed_out", "reason": "timeout", "at": now})
    _write_operation(task, record)
    return record


def _saved_completion_request_keys(task: Task) -> set[str]:
    return {
        draft["completion_request_key"]
        for draft in AnalysisStore(task)._list("drafts")
        if isinstance(draft.get("completion_request_key"), str)
    }


def _saved_operation_revisions(task: Task) -> set[tuple[str, int]]:
    pairs: set[tuple[str, int]] = set()
    for draft in AnalysisStore(task)._list("drafts"):
        operation_id = draft.get("completion_operation_id")
        revision = draft.get("completion_operation_revision")
        if isinstance(operation_id, str) and isinstance(revision, int) and not isinstance(revision, bool):
            pairs.add((operation_id, revision))
    return pairs


def _attempt_saved_by_draft(
    record: dict[str, Any],
    attempt: dict[str, Any],
    *,
    saved_request_keys: set[str],
    saved_operation_revisions: set[tuple[str, int]],
) -> bool:
    call_id = attempt.get("call_id")
    if isinstance(call_id, str) and _hash({"operation_id": record["id"], "call_id": call_id}) in saved_request_keys:
        return True
    return (record["id"], attempt.get("revision")) in saved_operation_revisions


def _latest_unsettled_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    for attempt in sorted(record.get("revisions", []), key=lambda row: row.get("revision", 0), reverse=True):
        if attempt.get("draft_id") or attempt.get("completion_id"):
            return None
        payload = attempt.get("payload")
        if isinstance(payload, dict):
            return attempt
    return None


def _recovery_projection(record: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any] | None:
    payload = attempt.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("body"), str):
        return None
    result = {
        "operation_id": record["id"],
        "status": record["status"],
        "revision": attempt["revision"],
        "title": payload.get("title") if isinstance(payload.get("title"), str) else None,
        "body": payload["body"],
        "limitations": payload.get("limitations") if isinstance(payload.get("limitations"), list) else [],
        "run_ids": payload.get("run_ids") if isinstance(payload.get("run_ids"), list) else [],
        "fact_ids": payload.get("fact_ids") if isinstance(payload.get("fact_ids"), list) else [],
        "claims": payload.get("claims") if isinstance(payload.get("claims"), list) else [],
        "evidence_recipes": payload.get("evidence_recipes") if isinstance(payload.get("evidence_recipes"), list) else [],
        "consistency_rules": payload.get("consistency_rules") if isinstance(payload.get("consistency_rules"), list) else [],
        "consistency_sources": payload.get("consistency_sources") if isinstance(payload.get("consistency_sources"), (dict, list)) else [],
        "materiality": payload.get("materiality") if isinstance(payload.get("materiality"), dict) else {},
        "requirements_id": payload.get("requirements_id") if isinstance(payload.get("requirements_id"), str) else None,
        "parent_id": payload.get("parent_id") if isinstance(payload.get("parent_id"), str) else None,
        "updated_at": record.get("updated_at"),
    }
    if attempt.get("status") == "rejected_validation":
        result["attempt_status"] = "rejected_validation"
    if isinstance(attempt.get("error"), dict):
        result["validation_error"] = attempt["error"]
    return result




def get_completion_operation_for_recovery(task: Task, operation_id: str, clock: Clock | None = None) -> dict[str, Any]:
    """Read an operation for manager recovery without runtime session authority.

    Recovery still happens by explicit operation id and revision; this helper does
    not expose call ids or permit reserving new runtime work.
    """
    operation_id = _operation_id(operation_id)
    with exclusive(task.lock_path, timeout=10):
        record = _expire_record_locked(task, _read_operation_path(task, _operation_path(task, operation_id)), clock)
        return _public(record)


def list_completion_recoveries(task: Task, clock: Clock | None = None) -> dict[str, Any]:
    """List task-level draft bodies recoverable after an interrupted completion operation.

    This is a manager/CLI recovery surface. It intentionally has no session-id
    parameter and returns no runtime request key, session id, snapshot ceiling,
    call id, or raw authority material.
    """
    root = _operation_root(task)
    with exclusive(task.lock_path, timeout=10):
        saved_request_keys = _saved_completion_request_keys(task)
        saved_operation_revisions = _saved_operation_revisions(task)
        recoveries: list[dict[str, Any]] = []
        if not root.exists():
            return {"recoveries": recoveries}
        for path in root.glob("*.json"):
            record = _expire_record_locked(task, _read_operation_path(task, path), clock)
            if record.get("status") not in {*TERMINAL, "repair_available"} or record.get("status") == "complete":
                continue
            attempt = _latest_unsettled_payload(record)
            if not attempt:
                continue
            if _attempt_saved_by_draft(
                record,
                attempt,
                saved_request_keys=saved_request_keys,
                saved_operation_revisions=saved_operation_revisions,
            ):
                continue
            recovery = _recovery_projection(record, attempt)
            if recovery is not None:
                recoveries.append(recovery)
        recoveries.sort(key=lambda row: (str(row.get("updated_at") or ""), row["operation_id"], row["revision"]))
        return {"recoveries": recoveries}


class CompletionOperationStore:
    def __init__(
        self,
        task: Task,
        session_id: str,
        snapshot_ids: list[str] | set[str] | None = None,
        clock: Clock | None = None,
    ):
        self.task = task
        self.session_id = _safe_text(session_id, "session_id")
        self.snapshot_ids = None if snapshot_ids is None else set(snapshot_ids)
        self.clock = clock
        self.root = self._inside(task.root / "analysis" / "completion_operations")

    def begin(self, request_key: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        request_key = _safe_text(request_key, "request_key")
        effective_policy = _policy(policy)
        with exclusive(self.task.lock_path, timeout=10):
            for record in self._list_locked():
                if record.get("request_key") != request_key:
                    continue
                self._authorize(record)
                if policy is not None and record.get("policy") != effective_policy:
                    raise FoundryError("completion operation policy conflict")
                record = self._expire_locked(record)
                return _public(record, replayed=True)
            now = _utc_now(self.clock)
            operation_id = uuid.uuid4().hex
            record = _new(
                self.task,
                id=operation_id,
                domain="foundry.finance.completion_operation.v1",
                request_key=request_key,
                session_id=self.session_id,
                snapshot_ids=sorted(self.snapshot_ids) if self.snapshot_ids is not None else None,
                status="running",
                mode="finish_explanation",
                started_at=_iso(now),
                deadline_at=_iso(now + timedelta(seconds=effective_policy["timeout_seconds"])),
                updated_at=_iso(now),
                finished_at=None,
                policy=effective_policy,
                current_revision=0,
                revisions=[],
                repair_attempts_reserved=0,
                repair_attempts_settled=0,
                stop_reason=None,
                events=[{"type": "operation_started", "at": _iso(now)}],
            )
            record["seq"] = AnalysisStore(self.task)._next_seq()
            self._write_locked(record)
            return _public(record)

    def get(self, operation_id: str) -> dict[str, Any]:
        with exclusive(self.task.lock_path, timeout=10):
            record = self._read_locked(_operation_id(operation_id))
            self._authorize(record)
            record = self._expire_locked(record)
            return _public(record)

    def reserve(
        self,
        operation_id: str,
        revision: int | None = None,
        payload: Any = None,
        *,
        call_id: str | None = None,
    ) -> dict[str, Any]:
        operation_id = _operation_id(operation_id)
        if revision is not None:
            revision = _revision(revision)
        if call_id is not None:
            call_id = _safe_text(call_id, "call_id")
        clean_payload = _json({} if payload is None else payload, "payload")
        payload_hash = _hash(clean_payload)
        self._authorize_snapshots(clean_payload)
        with exclusive(self.task.lock_path, timeout=10):
            record = self._read_locked(operation_id)
            self._authorize(record)
            record = self._expire_locked(record)
            existing = self._call_record(record, call_id) if call_id else None
            if existing:
                if revision is not None and existing.get("revision") != revision:
                    raise FoundryError("operation call id revision conflict")
                if existing.get("payload_hash") != payload_hash:
                    raise FoundryError("operation payload conflict")
                if self._attempt_finished(existing):
                    return self._public_with_attempt(record, existing, reservation_replayed=True)
            existing_by_revision = self._revision_record(record, revision) if revision is not None else None
            if existing_by_revision:
                if existing_by_revision.get("payload_hash") != payload_hash:
                    raise FoundryError("operation payload conflict")
                if call_id and existing_by_revision.get("call_id") not in (None, call_id):
                    raise FoundryError("operation call id conflict")
                if self._attempt_finished(existing_by_revision):
                    return self._public_with_attempt(record, existing_by_revision, reservation_replayed=True)
            if record["status"] in TERMINAL:
                raise FoundryError("completion operation is terminal")
            if existing:
                return self._public_with_attempt(record, existing, reservation_replayed=True)
            if existing_by_revision:
                if call_id and existing_by_revision.get("call_id") is None:
                    existing_by_revision["call_id"] = call_id
                    self._write_locked(record)
                return self._public_with_attempt(record, existing_by_revision, reservation_replayed=True)
            if revision is None:
                revision = int(record.get("current_revision", 0)) + 1
            expected = int(record.get("current_revision", 0)) + 1
            if revision != expected:
                raise FoundryError("operation revision conflict")
            if revision > 1:
                previous = self._revision_record(record, revision - 1)
                if not previous or not self._attempt_finished(previous):
                    raise FoundryError("previous operation revision has not settled")
            max_repairs = int(record["policy"]["max_repairs"])
            if max(0, revision - 1) > max_repairs:
                self._mark_locked(record, "needs_review", "repair_budget_exhausted")
                self._write_locked(record)
                raise FoundryError("completion repair budget exhausted")
            now = _iso(_utc_now(self.clock))
            attempt = {
                "revision": revision,
                "payload": clean_payload,
                "payload_hash": payload_hash,
                "reserved_at": now,
                "status": "reserved",
            }
            if call_id:
                attempt["call_id"] = call_id
            record["current_revision"] = revision
            record["repair_attempts_reserved"] = max(0, revision - 1)
            record["status"] = "running"
            record["stop_reason"] = None
            record["updated_at"] = now
            record["revisions"].append(attempt)
            event = {"type": "revision_reserved", "revision": revision, "at": now}
            if call_id:
                event["call_id"] = call_id
            record["events"].append(event)
            self._write_locked(record)
            return self._public_with_attempt(record, attempt)

    def reject_attempt(self, operation_id: str, revision: int, error: dict[str, Any]) -> dict[str, Any]:
        operation_id = _operation_id(operation_id)
        revision = _revision(revision)
        clean_error = _json(error, "attempt error")
        with exclusive(self.task.lock_path, timeout=10):
            record = self._read_locked(operation_id)
            self._authorize(record)
            target = self._revision_record(record, revision)
            if not target:
                raise FoundryError("operation revision has not been reserved")
            if target.get("draft_id") or target.get("completion_id"):
                raise FoundryError("operation revision already saved")
            if target.get("status") in ATTEMPT_TERMINAL:
                return _public(record, replayed=True)
            now = _iso(_utc_now(self.clock))
            target.update({
                "status": "rejected_validation",
                "error": clean_error,
                "rejected_at": now,
            })
            record["repair_attempts_settled"] = max(record.get("repair_attempts_settled", 0), max(0, revision - 1))
            record["updated_at"] = now
            record["events"].append({
                "type": "revision_rejected",
                "revision": revision,
                "code": clean_error.get("code"),
                "at": now,
            })
            next_revision = int(record.get("current_revision", 0)) + 1
            if max(0, next_revision - 1) > int(record["policy"]["max_repairs"]):
                self._mark_locked(record, "needs_review", "repair_budget_exhausted")
            elif record["status"] not in TERMINAL:
                record["status"] = "repair_available"
                record["stop_reason"] = None
                record["finished_at"] = None
                record["events"].append({"type": "operation_status", "status": "repair_available", "at": now})
            self._write_locked(record)
            return _public(record)

    def settle(self, operation_id: str, revision: int, draft: dict[str, Any], completion: dict[str, Any]) -> dict[str, Any]:
        operation_id = _operation_id(operation_id)
        revision = _revision(revision)
        if not isinstance(draft, dict) or not isinstance(completion, dict):
            raise FoundryError("draft and completion must be objects")
        clean_draft = _json(draft, "draft")
        clean_completion = _json(completion, "completion")
        self._validate_settlement_pair(clean_draft, clean_completion)
        self._authorize_snapshots({"draft": clean_draft, "completion": clean_completion})
        with exclusive(self.task.lock_path, timeout=10):
            record = self._read_locked(operation_id)
            self._authorize(record)
            target = self._revision_record(record, revision)
            if not target:
                raise FoundryError("operation revision has not been reserved")
            draft_id = _safe_text(clean_draft.get("id"), "draft id")
            completion_id = _safe_text(clean_completion.get("id"), "completion id")
            prior = (target.get("draft_id"), target.get("completion_id"))
            if prior != (None, None):
                if prior != (draft_id, completion_id):
                    raise FoundryError("operation settlement conflict")
                return _public(record, replayed=True)
            prior_terminal = record["status"] in TERMINAL
            prior_status = record["status"]
            prior_reason = record.get("stop_reason")
            prior_finished_at = record.get("finished_at")
            now = _iso(_utc_now(self.clock))
            target.update({
                "status": "settled",
                "draft_id": draft_id,
                "draft_content_hash": clean_draft.get("content_hash"),
                "completion_id": completion_id,
                "completion_status": clean_completion.get("status"),
                "completion_stop_reason": clean_completion.get("stop_reason"),
                "repair_allowed": bool(clean_completion.get("repair_allowed")),
                "settled_at": now,
            })
            record["repair_attempts_settled"] = max(record.get("repair_attempts_settled", 0), max(0, revision - 1))
            record["updated_at"] = now
            record["events"].append({
                "type": "revision_settled",
                "revision": revision,
                "draft_id": draft_id,
                "completion_id": completion_id,
                "late_terminal": prior_terminal,
                "at": now,
            })
            if prior_terminal:
                record["status"] = prior_status
                record["stop_reason"] = prior_reason
                record["finished_at"] = prior_finished_at
            else:
                self._apply_completion_locked(record, clean_completion)
            self._write_locked(record)
            return _public(record)

    def stop(self, operation_id: str, reason: str) -> dict[str, Any]:
        reason = _safe_text(reason, "stop reason", maximum=500)
        with exclusive(self.task.lock_path, timeout=10):
            record = self._read_locked(_operation_id(operation_id))
            self._authorize(record)
            if record["status"] not in TERMINAL:
                status = "timed_out" if reason == "timeout" else "cancelled"
                self._mark_locked(record, status, reason)
                self._write_locked(record)
            return _public(record)

    def _inside(self, path: Path) -> Path:
        return _task_inside(self.task, path)

    def _path(self, operation_id: str) -> Path:
        return self._inside(self.root / f"{_operation_id(operation_id)}.json")

    def _list_locked(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        records = [self._read_path_locked(path) for path in self.root.glob("*.json")]
        return sorted(records, key=lambda row: (row.get("seq", 0), row.get("created_at", ""), row["id"]))

    def _read_locked(self, operation_id: str) -> dict[str, Any]:
        return self._read_path_locked(self._path(operation_id))

    def _read_path_locked(self, path: Path) -> dict[str, Any]:
        path = self._inside(path)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FoundryError("completion operation is unavailable") from exc
        check = dict(record)
        digest = check.pop("_integrity_hash", None)
        if not digest or digest != _hash(check) or record.get("task_id") != self.task.id or record.get("id") != path.stem:
            raise FoundryError("completion operation integrity check failed")
        return record

    def _write_locked(self, record: dict[str, Any]) -> None:
        _write_operation(self.task, record)

    def _authorize(self, record: dict[str, Any]) -> None:
        if record.get("session_id") != self.session_id:
            raise FoundryError("completion operation belongs to another session")
        self._authorize_snapshots(record)

    def _authorize_snapshots(self, value: Any) -> None:
        if self.snapshot_ids is None:
            return
        snapshots = _extract_snapshots(value)
        if not snapshots <= self.snapshot_ids:
            raise FoundryError("completion operation snapshots are outside this session context")

    @staticmethod
    def _revision_record(record: dict[str, Any], revision: int | None) -> dict[str, Any] | None:
        if revision is None:
            return None
        return next((row for row in record.get("revisions", []) if row.get("revision") == revision), None)

    @staticmethod
    def _call_record(record: dict[str, Any], call_id: str | None) -> dict[str, Any] | None:
        if not call_id:
            return None
        return next((row for row in record.get("revisions", []) if row.get("call_id") == call_id), None)

    @staticmethod
    def _attempt_settled(attempt: dict[str, Any]) -> bool:
        return bool(attempt.get("draft_id") and attempt.get("completion_id"))

    @classmethod
    def _attempt_finished(cls, attempt: dict[str, Any]) -> bool:
        return cls._attempt_settled(attempt) or attempt.get("status") in ATTEMPT_TERMINAL

    def _public_with_attempt(
        self,
        record: dict[str, Any],
        attempt: dict[str, Any],
        *,
        reservation_replayed: bool = False,
    ) -> dict[str, Any]:
        result = _public(record, reservation_replayed=reservation_replayed)
        result["attempt"] = deepcopy(attempt)
        result["attempt"]["replayed"] = reservation_replayed
        return result

    def _expired(self, record: dict[str, Any]) -> bool:
        return _utc_now(self.clock) >= _parse_iso(record.get("deadline_at"), "deadline")

    def _expire_locked(self, record: dict[str, Any]) -> dict[str, Any]:
        if record["status"] not in TERMINAL and self._expired(record):
            self._mark_locked(record, "timed_out", "timeout")
            self._write_locked(record)
        return record

    def _mark_locked(self, record: dict[str, Any], status: str, reason: str | None) -> None:
        now = _iso(_utc_now(self.clock))
        record["status"] = status
        record["stop_reason"] = reason
        record["updated_at"] = now
        if status in TERMINAL:
            record["finished_at"] = now
        record["events"].append({"type": "operation_status", "status": status, "reason": reason, "at": now})

    def _apply_completion_locked(self, record: dict[str, Any], completion: dict[str, Any]) -> None:
        if self._expired(record):
            self._mark_locked(record, "timed_out", "timeout")
            return
        status = completion.get("status")
        stop_reason = completion.get("stop_reason")
        if status == "complete":
            self._mark_locked(record, "complete", "complete")
        elif status == "awaiting_input" or stop_reason == "verified_input_gap":
            self._mark_locked(record, "awaiting_input", "verified_input_gap")
        elif bool(completion.get("repair_allowed")):
            next_revision = int(record.get("current_revision", 0)) + 1
            if max(0, next_revision - 1) > int(record["policy"]["max_repairs"]):
                self._mark_locked(record, "needs_review", "repair_budget_exhausted")
            else:
                now = _iso(_utc_now(self.clock))
                record["status"] = "repair_available"
                record["stop_reason"] = None
                record["updated_at"] = now
                record["finished_at"] = None
                record["events"].append({"type": "operation_status", "status": "repair_available", "at": now})
        else:
            self._mark_locked(record, "needs_review", stop_reason or "needs_review")

    @staticmethod
    def _validate_settlement_pair(draft: dict[str, Any], completion: dict[str, Any]) -> None:
        draft_id = _safe_text(draft.get("id"), "draft id")
        content_hash = _safe_text(draft.get("content_hash"), "draft content_hash", maximum=500)
        if completion.get("draft_id") != draft_id:
            raise FoundryError("completion draft_id does not match draft")
        if completion.get("draft_content_hash") != content_hash:
            raise FoundryError("completion draft content hash does not match draft")
