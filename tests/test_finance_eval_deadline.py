"""An OS process supervisor enforces the case budget even when Node cannot run timers."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deadline_verifier", ROOT / "tools/verify_finance_evals.py")
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def persist_evidence(name, value):
    if destination := os.environ.get("FOUNDRY_DEADLINE_EVIDENCE_DIR"):
        output = Path(destination)
        output.mkdir(parents=True, exist_ok=True)
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def test_supervisor_stops_blocked_node_and_retains_unstarted_slot_identities(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    path = tmp_path / "session.json"
    script = tmp_path / "blocked.cjs"
    script.write_text("""
const {writeFileSync}=require('node:fs');
writeFileSync(process.argv[2], JSON.stringify({status:'running',deadline_policy:'absolute-case-v1',
 model:{provider:'fake',model:'fake'},cases:[{id:'first',completed:false,calls:[],
 deadline:{schema_version:1,limit_ms:150,started_monotonic_ns:process.hrtime.bigint().toString(),
 expires_at_epoch_ms:Date.now()+150,exceeded:false}}]}));
Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,10000);
""")
    cases = [{"id": name, "slot": {"repeat": repeat}, "taskId": f"task-{name}",
              "sessionId": f"session-{name}", "inputSha256": f"hash-{name}"}
             for repeat, name in enumerate(("first", "second"), 1)]
    child = subprocess.Popen([node, str(script), str(path)], start_new_session=True)
    started = time.monotonic()
    try:
        report = V._wait_report(child, path, 5, cases=cases)
        assert time.monotonic() - started < 2
        assert child.poll() is not None
    finally:
        V._stop(child)
    first, second = report["cases"]
    assert first["completed"] is False
    assert first["deadline"]["exceeded"] is True
    assert first["deadline"]["phase"] == "independent_supervisor"
    assert first["duration_ms"] >= 150
    assert first["deadline"]["supervisor_termination"]["returncode"] is not None
    assert second["execution_status"] == "not_started"
    assert second["slot"] == {"repeat": 2}
    assert second["error"] == "not_started_due_to_supervisor_stop"
    assert "started_at" not in second
    assert json.loads(path.read_text()) == report
    assert path.with_name(path.name + ".supervisor.jsonl").exists()
    persist_evidence("blocked-event-loop.json", report)


def test_unconfirmed_termination_is_a_failed_auditable_observation(monkeypatch, tmp_path):
    from types import SimpleNamespace

    def denied(*args, **kwargs):
        raise PermissionError("synthetic termination refusal")

    monkeypatch.setattr(V, "_stop", denied)
    child = SimpleNamespace(pid=123, returncode=None, poll=lambda: None)
    row = {"id": "refused", "completed": True, "deadline": {"schema_version": 1, "limit_ms": 150}}
    path = tmp_path / "report.json"
    report = V._supervisor_timeout(child, path, {"cases": [row]}, row, [], time.monotonic())
    assert report["supervisor"]["status"] == "termination_unconfirmed"
    assert row["deadline"]["runtime_terminated"] is False
    assert row["deadline"]["supervisor_termination"]["confirmed"] is False
    assert "PermissionError" in row["deadline"]["supervisor_termination"]["error"]
    assert not V._case_completed(row)
    assert json.loads(path.read_text()) == report


def test_hard_stop_kills_same_group_descendant_that_ignores_sigterm(tmp_path):
    pidfile = tmp_path / "descendant.pid"
    child_code = "import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path(__import__('sys').argv[1]).write_text(str(os.getpid()));time.sleep(100)"
    parent_code = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);time.sleep(100)"
    child = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-c", parent_code, child_code, str(pidfile)], start_new_session=True)
    descendant = None
    try:
        until = time.monotonic() + 3
        while not pidfile.exists() and time.monotonic() < until:
            time.sleep(0.02)
        descendant = int(pidfile.read_text())
        V._stop(child, grace_seconds=0)
        assert child.returncode == -signal.SIGKILL
        # A zombie is already stopped; its init-owned reap can lag group death.
        until = time.monotonic() + 2
        state = ""
        while time.monotonic() < until:
            state = subprocess.run(["ps", "-p", str(descendant), "-o", "stat="], text=True, capture_output=True).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.02)
        assert not state or state.startswith("Z"), state
        persist_evidence("same-group-descendant.json", {"parent_returncode": child.returncode,
            "strategy": "SIGKILL_process_group", "descendant_state": state, "stopped": True})
    finally:
        if child.poll() is None:
            V._stop(child, grace_seconds=0)
        if descendant:
            try:
                os.kill(descendant, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_new_deadline_receipt_prevents_late_completion_credit_without_reinterpreting_history():
    historical = {"completed": True, "duration_ms": 424251,
                  "events": [{"type": "turn/end", "data": {"reason": {"kind": "completed"}}}]}
    assert V._case_completed(historical)
    current = {**historical, "deadline": {"schema_version": 1, "limit_ms": 420000, "exceeded": False}}
    assert not V._case_completed(current)
    current["duration_ms"] = 419999
    assert V._case_completed(current)
    current["deadline"]["exceeded"] = True
    assert not V._case_completed(current)


def test_supervisor_does_not_spend_execution_budget_on_state_capture(tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"status": "completed", "deadline_policy": "absolute-case-v1", "cases": [
        {"id": "done", "completed": True, "duration_ms": 80, "evidence_collection_ms": 500,
         "deadline": {"schema_version": 1, "limit_ms": 100, "expires_at_epoch_ms": 0,
                      "execution_ended": True, "exceeded": False}}]}))
    # A completed report is enough; no process or timer is allowed to rewrite it.
    report = V._wait_report(None, path, 1)
    assert V._case_completed(report["cases"][0])


@pytest.mark.parametrize("seam", ["tool", "model"])
def test_supervisor_keeps_ownership_until_ignored_abort_and_dispose_are_terminated(tmp_path, seam):
    from test_verify_finance_evals_observer import run_observer

    run_observer(tmp_path)  # Reuse the existing fake Foundry/package fixture.
    path = tmp_path / "report.json"
    path.unlink()
    config_path = tmp_path / "probe/config.json"
    config = json.loads(config_path.read_text())
    config["timeoutSeconds"] = 0.5
    config_path.write_text(json.dumps(config))
    if seam == "tool":
        wait = """await listeners['tools/execute']({callId:'ignored',name:'ignored',arguments:{},agent},
          async () => {await new Promise(() => {});});"""
    else:
        wait = """for await (const chunk of listeners['llm/stream']({sessionId:agent.id},
          async function*() {await new Promise(() => {});})) {}"""
    driver = tmp_path / "driver.mjs"
    text = driver.read_text().replace("whenIdle: async () => {", "whenIdle: async () => {" + wait)
    text = text.replace("dispose: async () => {", "dispose: async () => {if(options.sessionId==='session-f01') await new Promise(() => {});")
    driver.write_text(text)
    env = {**os.environ, "FOUNDRY_BIN": str(tmp_path / "foundry.mjs"), "FOUNDRY_VAR": str(tmp_path / "var")}
    log = tmp_path / "ignored-abort.log"
    with log.open("wb") as sink:
        child = subprocess.Popen([shutil.which("node"), str(driver)], stdout=sink, stderr=subprocess.STDOUT,
                                 env=env, start_new_session=True)
        try:
            until = time.monotonic() + 3
            pending = None
            while time.monotonic() < until:
                if path.exists():
                    pending = json.loads(path.read_text())
                    if pending["cases"] and pending["cases"][0]["deadline"].get("budget_closed"):
                        break
                time.sleep(0.02)
            receipt = pending["cases"][0]["deadline"]
            assert receipt["budget_closed"] is True
            assert receipt["execution_ended"] is False
            assert not receipt.get("runtime_terminated")
            assert any(event["phase"] == f"{seam}_start" for event in receipt["events"])
            report = V._wait_report(child, path, 2, cases=config["cases"])
            assert report["supervisor"]["status"] == "terminated_after_case_deadline"
            assert report["cases"][0]["deadline"]["runtime_terminated"] is True
            assert child.poll() is not None
            persist_evidence(f"ignored-abort-{seam}.json", {"seam": seam, "before": receipt,
                "after": report["cases"][0]["deadline"], "supervisor": report["supervisor"], "completed": False})
        finally:
            if child.poll() is None:
                V._stop(child, grace_seconds=0)


def test_observer_cancels_an_inflight_model_in_installed_dsh(tmp_path):
    """Use the real hook waterfall and agent loop with a local waiting adapter."""
    from foundry.harness import install_presets
    from foundry.task import TaskStore
    from test_real_load import DSH_BIN, _dsh_args, _prepare, _probe_package

    if not DSH_BIN or not Path(DSH_BIN).is_file():
        pytest.skip("set FOUNDRY_DSH_BIN to the installed runtime")
    adapter_events = tmp_path / "adapter-events.jsonl"
    body = r"""
import {apply as observe} from './observer.mjs';
import {appendFileSync} from 'node:fs';
export const name = 'foundry-deadline-real-probe';
export const inject = ['tools', 'agentPresets', 'llm', 'agents', 'agentDefaultModel', 'skills'];
export function apply(ctx) {
  (async () => {
    const {LlmAdapter} = await import(process.env.FOUNDRY_LLM_MODULE);
    ctx.llm.registerAdapter(['finance-deadline-fixture'], new class extends LlmAdapter {
      requestedTool = false;
      async *stream(options) {
        const record = event => appendFileSync(process.env.FOUNDRY_DEADLINE_EVENTS, JSON.stringify({event,session:options.sessionId})+'\n');
        if (!options.purpose && !this.requestedTool) {
          this.requestedTool = true;
          record('tool_requested');
          const block = {type:'tool-call',id:'deadline-state',name:'analysis-state',arguments:'{}'};
          yield {type:'block-start',index:0,blockType:block.type};
          yield {type:'block-end',index:0,block};
          yield {type:'finish',reason:{kind:'tool-calls'}};
          return;
        }
        record('waiting');
        await new Promise(resolve => {
          const aborted = () => {record('aborted'); resolve();};
          if (options.signal.aborted) aborted();
          else options.signal.addEventListener('abort', aborted, {once:true});
        });
        options.signal.throwIfAborted();
        yield {type:'finish',reason:{kind:'stop'}};
      }
    }());
    ctx.agentDefaultModel.currentSelection = () => ({provider:'finance-deadline-fixture',model:'deterministic'});
    observe(ctx);
  })().catch(error => console.error('DEADLINE_REAL_ERROR', error));
}
"""
    probe = _probe_package(tmp_path / "probe", body)
    shutil.copyfile(ROOT / "tools/verify_finance_evals.mjs", probe / "observer.mjs")
    home = tmp_path / "dsh-home"
    _prepare(home, probe, "web")
    install_presets(home)
    var = tmp_path / "var"
    task = TaskStore(var).create(title="deadline runtime fixture")
    (task.root / "analysis").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "session.json"
    (probe / "config.json").write_text(json.dumps({"report": str(path), "dshRoot": str(Path(DSH_BIN).resolve().parents[4]),
        "ids": [], "timeoutSeconds": 6, "cases": [{"id": "deadline-real", "sessionId": "deadline-real",
        "taskId": task.id, "workspace": str(task.root / "analysis"), "inputSha256": "fixture", "question": "等待取消"}]}))
    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env.update({"FOUNDRY_VAR": str(var), "FOUNDRY_BIN": str(ROOT / ".venv/bin/foundry"),
        "FOUNDRY_LLM_MODULE": (Path(DSH_BIN).resolve().parents[2] / "dsh-llm/lib/index.js").as_uri(),
        "FOUNDRY_DEADLINE_EVENTS": str(adapter_events)})
    report = None
    log = tmp_path / "runtime.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd, start_new_session=True)
        try:
            expires = time.monotonic() + 30
            while time.monotonic() < expires:
                if path.exists():
                    report = json.loads(path.read_text())
                    if report.get("status") != "running":
                        break
                time.sleep(0.05)
        finally:
            V._stop(child, grace_seconds=1)
    assert report and report["status"] == "completed", log.read_text(errors="replace")[-8000:]
    row = report["cases"][0]
    assert row["completed"] is False
    assert row["deadline"]["exceeded"] is True
    assert row["deadline"]["phase"] == "timer"
    phases = [event["phase"] for event in row["deadline"]["events"]]
    assert "model_start" in phases and "cancel_requested" in phases
    assert "tool_start" in phases and "tool_end" in phases
    assert any(call["call_id"] == "deadline-state" and not call["isError"] for call in row["calls"])
    starts = [event for event in row["deadline"]["events"] if event["phase"] in {"model_start", "tool_start"}]
    assert all(event["elapsed_ms"] < 6000 and event["call_id"] for event in starts)
    for kind in ("tool", "model"):
        started = {event["call_id"] for event in row["deadline"]["events"] if event["phase"] == f"{kind}_start"}
        ended = {event["call_id"] for event in row["deadline"]["events"] if event["phase"] == f"{kind}_end"}
        assert started and started == ended
    events = [json.loads(line)["event"] for line in adapter_events.read_text().splitlines()]
    # DSH may also start its session-title model call under this session.
    assert events.count("waiting") >= 1
    assert events.count("waiting") == events.count("aborted")
    assert events[-1] == "aborted"
    persist_evidence("installed-dsh-model-and-tool-hooks.json", {"runtime": report["runtime"],
        "provider_kind": "local_deterministic_adapter_no_financial_provider_credit", "deadline": row["deadline"],
        "duration_ms": row["duration_ms"], "completed": row["completed"], "error": row["error"],
        "calls": [{key: call.get(key) for key in ("call_id", "name", "isError")} for call in row["calls"]],
        "adapter_events": [json.loads(line) for line in adapter_events.read_text().splitlines()]})
