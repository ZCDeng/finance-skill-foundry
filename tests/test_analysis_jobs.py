from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.analysis_jobs import JobStore, TERMINAL
from foundry.context import resolve_context
from foundry.errors import FoundryError
from foundry.runner import runner_capabilities
from foundry.task import TaskStore


def _context(tmp_path: Path):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="分析")
    task.record_session("parent", role="analysis")
    return task, resolve_context(var, session_id="parent")


def _wait(jobs, record):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = jobs.get(record["id"])
        if result["status"] in TERMINAL:
            return result
        time.sleep(0.05)
    pytest.fail(f"job did not finish: {jobs.get(record['id'])}")


def test_child_is_registered_before_start_and_terminal_events_are_idempotent(tmp_path: Path):
    task, context = _context(tmp_path)
    jobs = JobStore(task)
    record = jobs.create(context, "child", {"prompt": "检查预算差异", "mode": "fork"})
    child = resolve_context(task.store.var_root, session_id=record["child_session_id"])
    assert child.task_id == task.id
    assert record["status"] == "queued"
    assert record["context"]["session_id"] == "parent"
    with pytest.raises(FoundryError, match="runtime child id"):
        jobs.started(record["id"], session_id="parent", child_session_id="invented")
    args = {"session_id": "parent", "child_session_id": record["child_session_id"]}
    assert jobs.started(record["id"], **args)["status"] == "running"
    jobs.settle(record["id"], "completed", {"text": "已核对"}, **args)
    assert jobs.settle(record["id"], "cancelled", {}, **args)["status"] == "completed"
    assert len(jobs.get(record["id"])["events"]) == 2
    with pytest.raises(FoundryError, match="depth"):
        jobs.create(child, "child", {"prompt": "再委派"})


def test_jobs_cannot_be_read_or_changed_by_another_session(tmp_path: Path):
    task, context = _context(tmp_path)
    jobs = JobStore(task)
    record = jobs.create(context, "child", {"prompt": "核对"})
    task.record_session("other", role="analysis")
    with pytest.raises(FoundryError, match="another session"):
        jobs.get(record["id"], session_id="other")
    with pytest.raises(FoundryError, match="another session"):
        jobs.cancel(record["id"], session_id="other")
    assert jobs.list(session_id="other") == []


def test_retry_freezes_original_context_after_parent_refresh(tmp_path: Path):
    task, context = _context(tmp_path)
    jobs = JobStore(task)
    record = jobs.create(context, "child", {"prompt": "核对"})
    source = tmp_path / "new.csv"
    source.write_text("amount\n10\n")
    dataset = AnalysisStore(task).add_dataset(source, name="new")
    task.update_session_context("parent", snapshot_ids=[dataset["id"]])
    jobs.settle(record["id"], "failed", {"error": "interrupted"}, session_id="parent", child_session_id=record["child_session_id"])
    retry = jobs.retry(record["id"], resolve_context(task.store.var_root, session_id="parent"))
    assert retry["id"] != record["id"]
    assert retry["retry_of"] == record["id"]
    assert retry["context"] == record["context"]
    assert retry["spec"] == record["spec"]
    assert resolve_context(task.store.var_root, session_id=retry["child_session_id"]).snapshot_ids == ()


def test_script_rejects_unbound_snapshot_before_creating_job(tmp_path: Path):
    task, context = _context(tmp_path)
    with pytest.raises(FoundryError, match="outside"):
        JobStore(task).create(context, "script", {"code": "print(1)", "bindings": {"foreign": "a" * 32}})
    assert len(task.sessions()) == 1
    assert not (task.root / "analysis" / "jobs").exists()


def test_script_rejects_requirements_outside_frozen_context(tmp_path: Path):
    from foundry.finance_requirements import save_requirements

    task, _ = _context(tmp_path)
    analysis = AnalysisStore(task)
    allowed_path = tmp_path / "allowed.csv"
    allowed_path.write_text("amount\n1\n", encoding="utf-8")
    outside_path = tmp_path / "outside.csv"
    outside_path.write_text("amount\n2\n", encoding="utf-8")
    allowed = analysis.add_dataset(allowed_path, name="allowed")
    outside = analysis.add_dataset(outside_path, name="outside")
    task.update_session_context("parent", snapshot_ids=[allowed["id"]])
    context = resolve_context(task.store.var_root, session_id="parent")
    requirement = save_requirements(analysis, {
        "question": "解释利润",
        "bindings": {"actual": outside["id"]},
        "items": [{"id": "profit", "metric": "profit"}],
    })

    with pytest.raises(FoundryError, match="requirements are outside"):
        JobStore(task).create(context, "script", {
            "code": "print(1)",
            "bindings": {"actual": allowed["id"]},
            "requirements_id": requirement["id"],
        })


@pytest.mark.skipif(not runner_capabilities()["available"], reason="requires macOS isolated runner")
def test_real_background_script_completion_failure_and_retry(tmp_path: Path):
    task, context = _context(tmp_path)
    jobs = JobStore(task)
    record = jobs.create(context, "script", {"code": "print('budget result: 42')", "bindings": {}})
    result = _wait(jobs, record)
    assert result["status"] == "completed", result
    assert result["result"]["stdout"].strip() == "budget result: 42"
    run = AnalysisStore(task).get_run(result["result"]["run_id"])
    assert run["session_id"] == record["child_session_id"]
    failed = _wait(jobs, jobs.create(context, "script", {"code": "raise ValueError('bad assumption')", "bindings": {}}))
    assert failed["status"] == "failed"
    retry = jobs.retry(result["id"], context)
    assert retry["retry_of"] == result["id"]
    assert _wait(jobs, retry)["status"] == "completed"


@pytest.mark.skipif(not runner_capabilities()["available"], reason="requires macOS isolated runner")
def test_real_background_script_cancel_stops_execution(tmp_path: Path):
    task, context = _context(tmp_path)
    jobs = JobStore(task)
    record = jobs.create(context, "script", {"code": "import os, pathlib, time\npathlib.Path('started').write_text(str(os.getpid()))\ntime.sleep(20)\nprint('must not finish')", "bindings": {}, "timeout_seconds": 30})
    deadline = time.monotonic() + 10
    markers = []
    while time.monotonic() < deadline:
        markers = list((task.root / "analysis" / "run_workspaces").glob("*/scratch/*/output/started"))
        if markers:
            break
        time.sleep(0.05)
    assert markers, "the sandbox must actually enter user code before cancellation"
    sandbox_pid = int(markers[0].read_text())
    jobs.cancel(record["id"], session_id="parent")
    result = _wait(jobs, record)
    assert result["status"] == "cancelled", result
    assert "must not finish" not in result.get("result", {}).get("stdout", "")
    assert result["result"]["run_id"]
    import os
    with pytest.raises(ProcessLookupError):
        os.kill(sandbox_pid, 0)


def test_job_cli_routes_registered_parent_and_hides_runtime_hooks_from_other_sessions(tmp_path: Path, capsys):
    from foundry.cli import main

    task, context = _context(tmp_path)
    base = ["--var", str(task.store.var_root), "--session", "parent"]
    assert main([*base, "analysis-child-start", "--spec", json.dumps({"prompt": "查预算", "mode": "spawn"})]) == 0
    row = json.loads(capsys.readouterr().out)
    assert main([*base, "analysis-job-started", "--job", row["id"], "--child-session", row["child_session_id"]]) == 0
    capsys.readouterr()
    assert main([*base, "analysis-job-settle", "--job", row["id"], "--child-session", row["child_session_id"], "--status", "completed", "--result", '{"text":"完成"}']) == 0
    capsys.readouterr()
    assert main([*base, "analysis-job-show", "--job", row["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["text"] == "完成"
    task.record_session("other", role="analysis")
    assert main(["--var", str(task.store.var_root), "--session", "other", "analysis-job-show", "--job", row["id"]]) == 3


@pytest.mark.skipif(not runner_capabilities()["available"], reason="requires macOS isolated runner")
def test_job_cli_fractional_timeout_remains_a_resource_number(tmp_path: Path, capsys):
    from foundry.cli import main

    task, _ = _context(tmp_path)
    assert main(["--var", str(task.store.var_root), "--session", "parent", "analysis-script-start", "--spec", '{"code":"import time; time.sleep(5)","bindings":{},"timeout_seconds":0.1}']) == 0
    row = json.loads(capsys.readouterr().out)
    result = _wait(JobStore(task), row)
    assert result["status"] == "failed"
    assert result["result"]["runner_status"] == "timeout"


def test_restarting_an_interrupted_worker_requires_an_explicit_retry(tmp_path: Path, monkeypatch):
    from foundry.analysis_jobs import _worker

    task, context = _context(tmp_path)
    jobs = JobStore(task)
    monkeypatch.setattr(jobs, "_launch", lambda record: None)
    row = jobs.create(context, "script", {"code": "print('must not rerun')", "bindings": {}})
    jobs.started(row["id"], session_id="parent", child_session_id=row["child_session_id"])
    _worker(task.store.var_root, task.id, row["id"])
    result = jobs.get(row["id"])
    assert result["status"] == "failed"
    assert "retry creates a new job" in result["result"]["error"]
    assert not (task.root / "analysis" / "runs").exists()


def test_child_runtime_exit_is_reconciled_without_touching_a_live_runtime(tmp_path: Path):
    import subprocess
    import sys

    task, context = _context(tmp_path)
    jobs = JobStore(task)
    dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        old = jobs.create(context, "child", {"prompt": "old runtime"}, runtime_pid=dead.pid)
        current = jobs.create(context, "child", {"prompt": "live runtime"}, runtime_pid=live.pid)
        jobs.started(old["id"], session_id="parent", child_session_id=old["child_session_id"], runtime_pid=dead.pid)
        jobs.started(current["id"], session_id="parent", child_session_id=current["child_session_id"], runtime_pid=live.pid)
        dead.terminate()
        dead.wait(timeout=5)
        assert jobs.refresh(old["id"])["status"] == "failed"
        assert jobs.refresh(current["id"])["status"] == "running"
        assert live.poll() is None
    finally:
        for process in (dead, live):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


def test_runtime_pid_reuse_does_not_attach_an_old_job_to_the_new_process(tmp_path: Path, monkeypatch):
    import os
    import foundry.analysis_jobs as module

    task, context = _context(tmp_path)
    jobs = JobStore(task)
    old = jobs.create(context, "child", {"prompt": "old instance"}, runtime_pid=os.getpid())
    original = module._process_identity
    actual = original(os.getpid())
    # Simulate a replacement process at the same PID: the observed birth stamp
    # changes. No cancellation signal is sent to that replacement process.
    monkeypatch.setattr(module, "_process_identity", lambda pid: {"pid": pid, "birth": actual["birth"] + " replacement"})
    replacement = jobs.create(context, "child", {"prompt": "replacement instance"}, runtime_pid=os.getpid())
    assert jobs.refresh(old["id"])["status"] == "failed"
    assert jobs.refresh(replacement["id"])["status"] == "queued"
    assert jobs.get(old["id"])["result"]["recovery"] == "process_instance_ended"


def test_unreadable_runtime_birth_is_not_treated_as_proof_of_death(tmp_path: Path, monkeypatch):
    import os
    import foundry.analysis_jobs as module

    task, context = _context(tmp_path)
    jobs = JobStore(task)
    row = jobs.create(context, "child", {"prompt": "still running"}, runtime_pid=os.getpid())
    monkeypatch.setattr(module, "_process_identity", lambda pid: {"pid": pid, "birth": None})
    assert jobs.refresh(row["id"])["status"] == "queued"


@pytest.mark.skipif(not runner_capabilities()["available"], reason="requires macOS isolated runner")
def test_background_script_completion_report_carries_result_contract_warnings(tmp_path: Path, monkeypatch):
    """A result row that breaks the contract still completes; the report says what to fix, in Chinese."""
    from foundry.analysis_jobs import _worker

    task, context = _context(tmp_path)
    jobs = JobStore(task)
    monkeypatch.setattr(jobs, "_launch", lambda record: None)
    rows = [{"metric_key": "revenue_achievement_ratio", "organization": "集团合并", "period": "2026-01:2026-08",
             "scenario": "budget_1_8", "value": "0.945301", "unit": "-", "metric_label": "营业收入达成率"}]
    code = f"from pathlib import Path\nPath('result.json').write_text({json.dumps(rows, ensure_ascii=False)!r}, encoding='utf-8')\n"
    row = jobs.create(context, "script", {"code": code, "bindings": {}, "result_file": "result.json"})
    _worker(task.store.var_root, task.id, row["id"])

    result = jobs.get(row["id"])
    assert result["status"] == "completed", result
    warnings = result["result"]["warnings"]
    assert [(warning["severity"], warning["code"]) for warning in warnings] == [("warning", "unit_unmarked")]
    assert "未标单位" in warnings[0]["message"]
    run = AnalysisStore(task).get_run(result["result"]["run_id"])
    assert run["execution_status"] == "succeeded"
    assert warnings == run["row_declarations"]["warnings"]
