from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import pytest

from foundry.errors import FoundryError
from foundry.analysis import AnalysisStore, _hash, _new
from foundry.finance_completion_operations import CompletionOperationStore, list_completion_recoveries
from foundry.finance_service import FinanceStore
from foundry.fsutil import write_json_atomic
from foundry.task import TaskStore


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def task(tmp_path):
    return TaskStore(tmp_path / "var").create(title="completion ops")


def store(task, *, session="session-a", snapshots=None, clock=None):
    return CompletionOperationStore(task, session, snapshot_ids=snapshots, clock=clock)


def draft(suffix="1"):
    return {"id": suffix * 32, "content_hash": "hash-" + suffix, "claims": []}


def completion(suffix="1", **updates):
    row = {
        "id": suffix * 32,
        "draft_id": suffix * 32,
        "draft_content_hash": "hash-" + suffix,
        "status": "needs_attention",
        "repair_allowed": True,
        "stop_reason": None,
    }
    row.update(updates)
    return row



def test_recoveries_list_terminal_unsettled_payload_without_runtime_authority(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], payload={
        "title": "利润说明",
        "body": "待恢复正文",
        "limitations": ["来源暂不可用"],
        "run_ids": ["run-1"],
        "fact_ids": ["fact-1"],
        "claims": [{"basis": "professional_judgment", "reason": "经理判断"}],
        "evidence_recipes": [{"dataset_id": "dataset-1", "columns": ["amount"]}],
        "consistency_rules": [{"id": "rule-1", "kind": "tie_out"}],
        "consistency_sources": [{"run_id": "run-1", "column": "profit"}],
        "materiality": {"absolute": "10"},
        "requirements_id": "req-1",
        "parent_id": "parent-1",
        "bindings": {"actual": "secret-snapshot"},
    }, call_id="call-secret")
    ops.stop(op["id"], "timeout")

    recovery = list_completion_recoveries(task)["recoveries"]

    assert recovery == [{
        "operation_id": op["id"],
        "status": "timed_out",
        "revision": 1,
        "title": "利润说明",
        "body": "待恢复正文",
        "limitations": ["来源暂不可用"],
        "run_ids": ["run-1"],
        "fact_ids": ["fact-1"],
        "claims": [{"basis": "professional_judgment", "reason": "经理判断"}],
        "evidence_recipes": [{"dataset_id": "dataset-1", "columns": ["amount"]}],
        "consistency_rules": [{"id": "rule-1", "kind": "tie_out"}],
        "consistency_sources": [{"run_id": "run-1", "column": "profit"}],
        "materiality": {"absolute": "10"},
        "requirements_id": "req-1",
        "parent_id": "parent-1",
        "updated_at": recovery[0]["updated_at"],
    }]
    assert "session_id" not in recovery[0]
    assert "request_key" not in recovery[0]
    assert recovery[0]["claims"] == [{"basis": "professional_judgment", "reason": "经理判断"}]
    assert recovery[0]["materiality"] == {"absolute": "10"}
    assert "session_id" not in recovery[0]
    assert "request_key" not in recovery[0]
    assert "snapshot_ids" not in recovery[0]
    assert "call_id" not in recovery[0]
    assert "bindings" not in recovery[0]


def test_recoveries_preserve_consistency_source_mapping_and_default_wrong_types(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], payload={
        "body": "待恢复正文",
        "evidence_recipes": {"dataset_id": "dataset-1"},
        "consistency_rules": "rule-1",
        "consistency_sources": {"source-1": {"kind": "number", "dataset_id": "dataset-1"}},
    }, call_id="call-bad-metadata")
    ops.stop(op["id"], "timeout")

    recovery = list_completion_recoveries(task)["recoveries"][0]

    assert recovery["evidence_recipes"] == []
    assert recovery["consistency_rules"] == []
    assert recovery["consistency_sources"] == {"source-1": {"kind": "number", "dataset_id": "dataset-1"}}


def test_recoveries_expire_running_operations_before_listing(task):
    clock = Clock()
    ops = store(task, clock=clock)
    op = ops.begin("runtime-request-1", policy={"timeout_seconds": 1})
    ops.reserve(op["id"], payload={"body": "超时前正文"}, call_id="call-1")
    clock.advance(2)

    listed = list_completion_recoveries(task, clock=clock)["recoveries"]

    assert listed[0]["operation_id"] == op["id"]
    assert listed[0]["status"] == "timed_out"
    assert store(task, clock=clock).get(op["id"])["status"] == "timed_out"


def test_recoveries_do_not_resurface_rejected_payload_after_later_saved_revision(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], payload={"body": "错误正文"}, call_id="bad-call")
    ops.reject_attempt(op["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
    ops.reserve(op["id"], payload={"body": "已保存正文"}, call_id="good-call")
    ops.settle(op["id"], 2, draft("2"), completion("2", repair_allowed=True))

    assert list_completion_recoveries(task) == {"recoveries": []}


def test_recover_completion_draft_refuses_older_revision_after_later_runtime_save(task):
    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 2})
    ops.reserve(op["id"], payload={"body": "错误正文"}, call_id="bad-call")
    ops.reject_attempt(op["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
    runtime = FinanceStore(task)
    runtime.session_id = "session-a"
    saved = runtime.save_completion_draft(op["id"], "corrected-call", {"body": "已修正正文"})

    with pytest.raises(FoundryError, match="newer completion revision"):
        FinanceStore(task).recover_completion_draft({
            "operation_id": op["id"],
            "revision": 1,
            "draft": {"body": "旧恢复正文"},
        })

    drafts = AnalysisStore(task)._list("drafts")
    completions = AnalysisStore(task)._list("completions")
    current = store(task).get(op["id"])

    assert [row["id"] for row in drafts] == [saved["id"]]
    assert len(completions) == 1
    assert current["revisions"][0]["status"] == "rejected_validation"
    assert "draft_id" not in current["revisions"][0]
    assert current["revisions"][1]["draft_id"] == saved["id"]


def test_recover_completion_draft_rereads_operation_under_lock_before_saving(task, monkeypatch):
    from foundry import finance_completion_operations as completion_operations

    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 2})
    ops.reserve(op["id"], payload={"body": "错误正文"}, call_id="bad-call")
    ops.reject_attempt(op["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
    original = completion_operations.get_completion_operation_for_recovery
    interleaved = False

    def stale_read_then_runtime_save(task_arg, operation_id, clock=None):
        nonlocal interleaved
        stale = original(task_arg, operation_id, clock)
        if not interleaved:
            interleaved = True
            runtime = FinanceStore(task_arg)
            runtime.session_id = "session-a"
            runtime.save_completion_draft(operation_id, "corrected-call", {"body": "已修正正文"})
        return stale

    monkeypatch.setattr(
        completion_operations,
        "get_completion_operation_for_recovery",
        stale_read_then_runtime_save,
    )

    with pytest.raises(FoundryError, match="newer completion revision"):
        FinanceStore(task).recover_completion_draft({
            "operation_id": op["id"],
            "revision": 1,
            "draft": {"body": "旧恢复正文"},
        })

    drafts = AnalysisStore(task)._list("drafts")
    completions = AnalysisStore(task)._list("completions")
    current = store(task).get(op["id"])

    assert len(drafts) == 1
    assert len(completions) == 1
    assert drafts[0]["completion_operation_revision"] == 2
    assert current["revisions"][0]["status"] == "rejected_validation"
    assert "draft_id" not in current["revisions"][0]
    assert current["revisions"][1]["draft_id"] == drafts[0]["id"]


def test_recoveries_exclude_settled_and_real_service_saved_before_settle(task):
    ops = store(task)
    settled = ops.begin("settled-request")
    ops.reserve(settled["id"], payload={"body": "已结算正文"}, call_id="settled-call")
    ops.settle(settled["id"], 1, draft("1"), completion("1"))

    service = FinanceStore(task)
    service.session_id = "session-a"
    saved = ops.begin("saved-request", policy={"max_repairs": 1})
    result = service.save_completion_draft(saved["id"], "saved-call", {"body": "已保存但未结算正文"})
    saved_record = ops.get(saved["id"])
    path = task.root / "analysis" / "completion_operations" / f"{saved['id']}.json"
    raw = __import__("json").loads(path.read_text())
    raw.pop("_integrity_hash")
    raw["status"] = "timed_out"
    raw["stop_reason"] = "timeout"
    raw["finished_at"] = raw["updated_at"]
    for attempt in raw["revisions"]:
        attempt.pop("draft_id", None)
        attempt.pop("completion_id", None)
    raw["_integrity_hash"] = _hash(raw)
    write_json_atomic(path, raw)

    assert result["completion_operation"]["id"] == saved_record["id"]
    assert result["completion_operation"]["revisions"][0]["call_id"] == "saved-call"
    assert result["completion_operation"]["revisions"][0]["draft_id"] == result["id"]

    pending = ops.begin("pending-request")
    ops.reserve(pending["id"], payload={"body": "可恢复正文"}, call_id="pending-call")
    ops.stop(pending["id"], "timeout")

    recoveries = list_completion_recoveries(task)["recoveries"]

    assert [row["operation_id"] for row in recoveries] == [pending["id"]]
    assert recoveries[0]["body"] == "可恢复正文"


def test_recoveries_exclude_saved_draft_bound_by_operation_revision_even_without_call_id(task):
    ops = store(task)
    op = ops.begin("runtime-request")
    ops.reserve(op["id"], 1, {"body": "已保存正文"})
    ops.stop(op["id"], "timeout")
    analysis = AnalysisStore(task)
    record = _new(
        task,
        title="saved",
        body="saved body",
        content_hash="saved-hash",
        completion_operation_id=op["id"],
        completion_operation_revision=1,
    )
    analysis._write(analysis._object_path("drafts", record["id"]), record)

    assert list_completion_recoveries(task) == {"recoveries": []}


def test_recoveries_exclude_complete_operations_even_if_unsettled(task):
    ops = store(task)
    op = ops.begin("runtime-request")
    ops.reserve(op["id"], payload={"body": "完整但未结算"}, call_id="call-1")
    path = task.root / "analysis" / "completion_operations" / f"{op['id']}.json"
    raw = __import__("json").loads(path.read_text())
    raw.pop("_integrity_hash")
    raw["status"] = "complete"
    raw["stop_reason"] = "complete"
    raw["finished_at"] = raw["updated_at"]
    raw["_integrity_hash"] = _hash(raw)
    write_json_atomic(path, raw)

    assert list_completion_recoveries(task) == {"recoveries": []}


def test_recoveries_are_task_local(task):
    other = TaskStore(task.store.var_root).create(title="other", make_current=False)
    op = store(task).begin("runtime-request-1")
    store(task).reserve(op["id"], payload={"body": "task one"}, call_id="call-1")
    store(task).stop(op["id"], "timeout")

    assert list_completion_recoveries(other) == {"recoveries": []}


def test_recoveries_fail_closed_on_corrupt_operation(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    path = task.root / "analysis" / "completion_operations" / f"{op['id']}.json"
    raw = __import__("json").loads(path.read_text())
    raw["status"] = "timed_out"
    write_json_atomic(path, raw)

    with pytest.raises(FoundryError, match="integrity"):
        list_completion_recoveries(task)


def test_recoveries_reject_symbolic_linked_operation_path(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    path = task.root / "analysis" / "completion_operations" / f"{op['id']}.json"
    path.unlink()
    path.symlink_to(path.with_name("missing.json"))

    with pytest.raises(FoundryError, match="symbolic links"):
        list_completion_recoveries(task)

def test_begin_is_server_generated_and_replays_by_runtime_request_key(task):
    clock = Clock()
    first = store(task, clock=clock).begin("runtime-request-1")
    reopened = store(task, clock=clock).begin("runtime-request-1")

    assert first["id"] == reopened["id"]
    assert reopened["replayed"] is True
    assert first["session_id"] == "session-a"
    assert first["policy"]["max_repairs"] == 2
    assert first["policy"]["timeout_seconds"] == 420
    assert first["deadline_at"] == "2026-09-07T01:07:00Z"
    assert first["current_revision"] == 0


def test_same_runtime_request_key_rejects_different_session(task):
    store(task, session="session-a").begin("runtime-request-1")

    with pytest.raises(FoundryError, match="another session"):
        store(task, session="session-b").begin("runtime-request-1")


def test_rejects_invalid_inputs_and_policy_values(task):
    ops = store(task)
    for request_key in ["", "bad\0key"]:
        with pytest.raises(FoundryError):
            ops.begin(request_key)
    for policy in [
        {"max_repairs": True},
        {"max_repairs": 3},
        {"max_repairs": -1},
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 1.5},
        {"timeout_seconds": 0},
        {"timeout_seconds": 3601},
        {"unknown": 1},
        [],
    ]:
        with pytest.raises(FoundryError):
            ops.begin("request-" + repr(policy), policy=policy)


def test_same_revision_same_payload_replays_but_different_payload_conflicts(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    reserved = ops.reserve(op["id"], 1, {"body": "draft", "bindings": {"actual": "snap-a"}})
    replayed = ops.reserve(op["id"], 1, {"bindings": {"actual": "snap-a"}, "body": "draft"})

    assert reserved["current_revision"] == 1
    assert reserved["attempt"]["payload"] == {"body": "draft", "bindings": {"actual": "snap-a"}}
    assert replayed["reservation_replayed"] is True
    assert len(replayed["revisions"]) == 1
    with pytest.raises(FoundryError, match="payload conflict"):
        ops.reserve(op["id"], 1, {"body": "changed"})



def test_call_id_retry_reuses_server_assigned_revision_without_counting_budget(task):
    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 2})
    first = ops.reserve(op["id"], payload={"body": "first"}, call_id="tool-call-1")
    retry = ops.reserve(op["id"], payload={"body": "first"}, call_id="tool-call-1")

    assert first["attempt"]["revision"] == 1
    assert retry["attempt"]["revision"] == 1
    assert retry["attempt"]["replayed"] is True
    assert retry["repair_attempts_reserved"] == 0
    assert len(retry["revisions"]) == 1


def test_different_call_id_cannot_start_new_revision_while_first_is_inflight(task):
    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 2})
    ops.reserve(op["id"], payload={"body": "first"}, call_id="tool-call-1")

    with pytest.raises(FoundryError, match="has not settled"):
        ops.reserve(op["id"], payload={"body": "second"}, call_id="tool-call-2")

    current = ops.get(op["id"])
    assert current["current_revision"] == 1
    assert [row["call_id"] for row in current["revisions"]] == ["tool-call-1"]
    assert [event["type"] for event in current["events"]].count("revision_reserved") == 1


def test_call_id_rejects_changed_payload_or_wrong_explicit_revision(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], payload={"body": "first"}, call_id="tool-call-1")

    with pytest.raises(FoundryError, match="payload conflict"):
        ops.reserve(op["id"], payload={"body": "changed"}, call_id="tool-call-1")
    with pytest.raises(FoundryError, match="revision conflict"):
        ops.reserve(op["id"], revision=2, payload={"body": "first"}, call_id="tool-call-1")


def test_next_revision_is_explicit_and_does_not_reset_deadline_or_budget(task):
    clock = Clock()
    ops = store(task, clock=clock)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 2, "timeout_seconds": 300})
    first_deadline = op["deadline_at"]
    ops.reserve(op["id"], 1, {"body": "first"})
    ops.settle(op["id"], 1, draft("1"), completion("1"))
    clock.advance(60)
    second = ops.reserve(op["id"], 2, {"body": "second", "requirements_id": "changed"})

    assert second["deadline_at"] == first_deadline
    assert second["repair_attempts_reserved"] == 1
    with pytest.raises(FoundryError, match="revision conflict"):
        ops.reserve(op["id"], 4, {"body": "skip"})


def test_previous_revision_must_settle_before_next_revision(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], 1, {"body": "first"})

    with pytest.raises(FoundryError, match="has not settled"):
        ops.reserve(op["id"], 2, {"body": "second"})


def test_repair_budget_allows_initial_plus_two_repairs_and_then_stops(task):
    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 2})
    for revision in [1, 2, 3]:
        ops.reserve(op["id"], revision, {"body": f"rev-{revision}"})
        ops.settle(op["id"], revision, draft(str(revision)), completion(str(revision)))

    stopped = ops.get(op["id"])
    assert stopped["status"] == "needs_review"
    assert stopped["stop_reason"] == "repair_budget_exhausted"
    assert stopped["repair_attempts_reserved"] == 2
    with pytest.raises(FoundryError, match="terminal"):
        ops.reserve(op["id"], 4, {"body": "rev-4"})


def test_zero_repairs_allows_initial_attempt_only(task):
    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 0})
    ops.reserve(op["id"], 1, {"body": "initial"})
    ops.settle(op["id"], 1, draft("1"), completion("1"))

    stopped = ops.get(op["id"])
    assert stopped["status"] == "needs_review"
    assert stopped["stop_reason"] == "repair_budget_exhausted"
    with pytest.raises(FoundryError, match="terminal"):
        ops.reserve(op["id"], 2, {"body": "repair"})


def test_rejected_attempt_with_zero_repair_budget_goes_to_review(task):
    ops = store(task)
    op = ops.begin("runtime-request-1", policy={"max_repairs": 0})
    ops.reserve(op["id"], 1, {"body": "bad"}, call_id="tool-call-1")

    rejected = ops.reject_attempt(op["id"], 1, {"code": "claim_value_mismatch", "message": "bad claim"})

    assert rejected["status"] == "needs_review"
    assert rejected["stop_reason"] == "repair_budget_exhausted"
    assert rejected["revisions"][0]["status"] == "rejected_validation"
    with pytest.raises(FoundryError, match="terminal"):
        ops.reserve(op["id"], payload={"body": "fixed"}, call_id="tool-call-2")


def test_deadline_persists_across_restarted_store_and_blocks_new_reserve(task):
    clock = Clock()
    op = store(task, clock=clock).begin("runtime-request-1", policy={"timeout_seconds": 30})
    store(task, clock=clock).reserve(op["id"], 1, {"body": "first"})
    clock.advance(31)
    reopened = store(task, clock=clock)
    expired = reopened.get(op["id"])

    assert expired["status"] == "timed_out"
    assert expired["stop_reason"] == "timeout"
    with pytest.raises(FoundryError, match="terminal"):
        reopened.reserve(op["id"], 1, {"body": "first"})


def test_subsecond_clock_does_not_round_deadline(task):
    clock = Clock()
    clock.value = datetime(2026, 9, 7, 1, 0, 0, 500000, tzinfo=timezone.utc)
    op = store(task, clock=clock).begin("runtime-request-1", policy={"timeout_seconds": 1})

    assert op["started_at"] == "2026-09-07T01:00:00.500000Z"
    assert op["deadline_at"] == "2026-09-07T01:00:01.500000Z"
    clock.value = datetime(2026, 9, 7, 1, 0, 1, 499999, tzinfo=timezone.utc)
    assert store(task, clock=clock).get(op["id"])["status"] == "running"
    clock.value = datetime(2026, 9, 7, 1, 0, 1, 500000, tzinfo=timezone.utc)
    assert store(task, clock=clock).get(op["id"])["status"] == "timed_out"


def test_cancelled_status_is_distinct_from_automatic_timeout(task):
    clock = Clock()
    ops = store(task, clock=clock)
    cancelled = ops.begin("cancelled-request", policy={"timeout_seconds": 1})
    ops.reserve(cancelled["id"], payload={"body": "cancel"}, call_id="cancel-call")
    stopped = ops.stop(cancelled["id"], "user_cancelled")
    clock.advance(2)

    assert store(task, clock=clock).get(cancelled["id"])["status"] == "cancelled"
    assert stopped["stop_reason"] == "user_cancelled"

    timed = store(task, clock=clock).begin("timeout-request", policy={"timeout_seconds": 1})
    store(task, clock=clock).reserve(timed["id"], payload={"body": "timeout"}, call_id="timeout-call")
    clock.advance(2)
    expired = store(task, clock=clock).get(timed["id"])

    assert expired["status"] == "timed_out"
    assert expired["stop_reason"] == "timeout"


def test_settle_after_deadline_keeps_draft_reference_but_times_out(task):
    clock = Clock()
    ops = store(task, clock=clock)
    op = ops.begin("runtime-request-1", policy={"timeout_seconds": 30})
    ops.reserve(op["id"], 1, {"body": "first"})
    clock.advance(31)
    settled = ops.settle(op["id"], 1, draft("1"), completion("1", status="complete", repair_allowed=False))

    assert settled["status"] == "timed_out"
    assert settled["revisions"][0]["draft_id"] == "1" * 32
    assert settled["revisions"][0]["completion_id"] == "1" * 32


def test_settled_exact_call_id_replays_after_complete_terminal(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], payload={"body": "done"}, call_id="tool-call-1")
    ops.settle(op["id"], 1, draft("1"), completion("1", status="complete", repair_allowed=False))

    replay = ops.reserve(op["id"], payload={"body": "done"}, call_id="tool-call-1")

    assert replay["status"] == "complete"
    assert replay["attempt"]["revision"] == 1
    assert replay["attempt"]["draft_id"] == "1" * 32
    assert replay["attempt"]["completion_id"] == "1" * 32



def test_settled_call_id_replay_after_deadline_returns_receipt_but_status_timed_out(task):
    clock = Clock()
    ops = store(task, clock=clock)
    op = ops.begin("runtime-request-1", policy={"timeout_seconds": 1})
    ops.reserve(op["id"], payload={"body": "done"}, call_id="tool-call-1")
    ops.settle(op["id"], 1, draft("1"), completion("1"))
    clock.advance(2)

    replay = ops.reserve(op["id"], payload={"body": "done"}, call_id="tool-call-1")

    assert replay["status"] == "timed_out"
    assert replay["stop_reason"] == "timeout"
    assert replay["attempt"]["replayed"] is True
    assert replay["attempt"]["draft_id"] == "1" * 32
    assert replay["attempt"]["completion_id"] == "1" * 32

def test_expired_unsettled_call_id_cannot_restart_work(task):
    clock = Clock()
    ops = store(task, clock=clock)
    op = ops.begin("runtime-request-1", policy={"timeout_seconds": 1})
    ops.reserve(op["id"], payload={"body": "work"}, call_id="tool-call-1")
    clock.advance(2)

    with pytest.raises(FoundryError, match="terminal"):
        ops.reserve(op["id"], payload={"body": "work"}, call_id="tool-call-1")


def test_settle_statuses_follow_completion_receipt(task):
    ops = store(task)
    complete = ops.begin("complete")
    ops.reserve(complete["id"], 1, {"body": "done"})
    assert ops.settle(complete["id"], 1, draft("1"), completion("1", status="complete", repair_allowed=False))["status"] == "complete"

    gap = ops.begin("gap")
    ops.reserve(gap["id"], 1, {"body": "gap"})
    assert ops.settle(gap["id"], 1, draft("2"), completion("2", status="awaiting_input", repair_allowed=False))["status"] == "awaiting_input"

    review = ops.begin("review")
    ops.reserve(review["id"], 1, {"body": "review"})
    result = ops.settle(review["id"], 1, draft("3"), completion("3", repair_allowed=False, stop_reason="no_progress"))
    assert result["status"] == "needs_review"
    assert result["stop_reason"] == "no_progress"


def test_settle_replays_same_draft_and_rejects_different_receipt(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], 1, {"body": "first"})
    first = ops.settle(op["id"], 1, draft("1"), completion("1"))
    replayed = ops.settle(op["id"], 1, draft("1"), completion("1"))

    assert replayed["replayed"] is True
    assert replayed["id"] == first["id"]
    with pytest.raises(FoundryError, match="settlement conflict"):
        ops.settle(op["id"], 1, draft("1"), {**completion("1"), "id": "2" * 32})


def test_stop_is_terminal_and_does_not_remove_settled_drafts(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], 1, {"body": "first"})
    ops.settle(op["id"], 1, draft("1"), completion("1"))
    stopped = ops.stop(op["id"], "user_cancelled")

    assert stopped["status"] == "cancelled"
    assert stopped["revisions"][0]["draft_id"] == "1" * 32
    with pytest.raises(FoundryError, match="terminal"):
        ops.reserve(op["id"], 2, {"body": "second"})


def test_stop_timeout_records_timed_out(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")

    assert ops.stop(op["id"], "timeout")["status"] == "timed_out"


def test_late_settle_after_cancelled_or_failed_preserves_terminal_status(task):
    ops = store(task)
    cancelled = ops.begin("cancelled")
    ops.reserve(cancelled["id"], 1, {"body": "first"})
    ops.stop(cancelled["id"], "user_cancelled")
    late = ops.settle(cancelled["id"], 1, draft("1"), completion("1", status="complete", repair_allowed=False))
    assert late["status"] == "cancelled"
    assert late["revisions"][0]["draft_id"] == "1" * 32

    failed = ops.begin("failed")
    ops.reserve(failed["id"], 1, {"body": "first"})
    failed_path = task.root / "analysis" / "completion_operations" / f"{failed['id']}.json"
    raw = __import__("json").loads(failed_path.read_text())
    raw.pop("_integrity_hash")
    raw["status"] = "failed"
    raw["stop_reason"] = "runtime_failed"
    raw["finished_at"] = raw["updated_at"]
    raw["_integrity_hash"] = _hash(raw)
    write_json_atomic(failed_path, raw)
    late_failed = ops.settle(failed["id"], 1, draft("2"), completion("2", status="complete", repair_allowed=False))
    assert late_failed["status"] == "failed"
    assert late_failed["stop_reason"] == "runtime_failed"


def test_snapshot_authority_is_checked_for_payload_draft_completion_and_stored_record(task):
    ops = store(task, snapshots={"snap-a"})
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], 1, {"bindings": {"actual": "snap-a"}, "claims": [{"dataset_id": "snap-a"}]})
    ops.settle(op["id"], 1, {**draft("1"), "claims": [{"dataset_id": "snap-a"}]}, {**completion("1"), "sources": [{"dataset_id": "snap-a"}]})

    with pytest.raises(FoundryError, match="outside this session"):
        ops.reserve(op["id"], 2, {"bindings": {"actual": "snap-b"}})
    with pytest.raises(FoundryError, match="outside this session"):
        store(task, snapshots={"snap-b"}).get(op["id"])


def test_concurrent_begin_and_same_reserve_are_idempotent(task):
    def begin(_):
        return store(task).begin("runtime-request-1")["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(begin, range(8)))
    assert len(set(ids)) == 1

    op_id = ids[0]
    def reserve(_):
        return store(task).reserve(op_id, 1, {"body": "same"})

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(reserve, range(8)))
    assert {len(record["revisions"]) for record in records} == {1}
    assert store(task).get(op_id)["current_revision"] == 1


def test_completion_must_match_draft_identity_and_content_hash(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    ops.reserve(op["id"], 1, {"body": "first"})

    with pytest.raises(FoundryError, match="draft_id"):
        ops.settle(op["id"], 1, draft("1"), {**completion("1"), "draft_id": "2" * 32})
    with pytest.raises(FoundryError, match="content hash"):
        ops.settle(op["id"], 1, draft("1"), {**completion("1"), "draft_content_hash": "changed"})


def test_dangling_symlink_in_operation_path_is_rejected(task):
    ops = store(task)
    op = ops.begin("runtime-request-1")
    path = task.root / "analysis" / "completion_operations" / f"{op['id']}.json"
    path.unlink()
    path.symlink_to(path.with_name("missing.json"))

    with pytest.raises(FoundryError, match="symbolic links"):
        ops.get(op["id"])
