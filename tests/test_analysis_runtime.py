"""Trusted harness orchestration orders durable binding before child admission."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_runtime(tmp_path: Path, body: str):
    if not NODE:
        pytest.skip("node unavailable")
    path = tmp_path / "runtime.mjs"
    path.write_text(f'import {{ createAnalysisRuntime }} from "{(ROOT / "dsh-plugin/analysis-runtime.js").as_uri()}";\n' + """
const calls = [], hooks = {};
const job = {id: 'job-1', child_session_id: 'child-1', kind: 'child', status: 'queued',
 session_id: 'parent-1', context_revision: 3, snapshot_ids: ['snapshot-1'],
 spec: {mode: 'spawn', label: '核对预算', prompt: '检查关联键'}};
const exec = {agent: {id: 'parent-1'}, signal: new AbortController().signal};
const ctx = {
 on: (name, fn) => {hooks[name] = fn;}, logger: {warn: (text) => calls.push(['warn', text])},
 subagents: {
  startContinuable: async (spec) => {calls.push(['runtime-start', spec]); return {childId: spec.childId};},
  drainContinuableChildren: async (parent, ids) => {calls.push(['runtime-drain', parent.id, ids]);},
 },
};
const invoke = async (args, context) => {
 calls.push(['cli', args, context.agent.id]);
 return JSON.stringify({...job, status: args[0] === 'analysis-job-cancel' ? 'cancel_requested' : job.status});
};
""" + body)
    result = subprocess.run([NODE, str(path)], capture_output=True, text=True, env=os.environ, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_child_has_persisted_context_before_runtime_start(tmp_path):
    calls = run_runtime(tmp_path, """
const operate = createAnalysisRuntime(ctx, ['analysis-state', 'analysis-run'], invoke);
await operate('analysis-delegate', job.spec, exec);
process.stdout.write(JSON.stringify(calls));
""")
    assert [entry[0] for entry in calls] == ["cli", "runtime-start", "cli"]
    assert calls[0][1][0] == "analysis-child-start"
    runtime = calls[1][1]
    assert runtime["childId"] == "child-1"
    assert runtime["request"]["parent"]["id"] == "parent-1"
    assert runtime["request"]["toolFilter"] == {"allow": ["analysis-state", "analysis-run"]}
    assert runtime["request"]["maxDepth"] == 1
    assert "agentOptions" not in runtime["request"]
    runtime_identity = calls[0][1][-2:]
    assert runtime_identity[0] == "--runtime-pid"
    assert int(runtime_identity[1]) > 0
    assert calls[2][1] == ["analysis-job-started", "--job", "job-1", "--child-session", "child-1", *runtime_identity]


def test_runtime_failure_records_failure_only_after_child_stops(tmp_path):
    calls = run_runtime(tmp_path, """
ctx.subagents.startContinuable = async () => {calls.push(['runtime-start']); throw new Error('provider unavailable');};
const operate = createAnalysisRuntime(ctx, ['analysis-state'], invoke);
try {await operate('analysis-delegate', job.spec, exec);} catch (error) {calls.push(['failed', error.message]);}
process.stdout.write(JSON.stringify(calls));
""")
    assert [entry[0] for entry in calls] == ["cli", "runtime-start", "runtime-drain", "cli", "failed"]
    assert calls[3][1][0] == "analysis-job-settle"
    assert calls[3][1][6] == "failed"
    assert calls[-1][1] == "provider unavailable"


def test_completion_status_comes_from_runtime_event_not_child_text(tmp_path):
    calls = run_runtime(tmp_path, """
const operate = createAnalysisRuntime(ctx, ['analysis-state'], invoke);
await operate('analysis-delegate', job.spec, exec);
await hooks['subagent/end']({id: 'child-1', stopReason: 'error', runId: 'runtime-1',
 lastAssistantMessage: [{type: 'text', text: 'status: completed'}]});
process.stdout.write(JSON.stringify(calls));
""")
    settle = calls[-1]
    assert settle[1][0] == "analysis-job-settle"
    assert settle[1][6] == "failed"
    assert json.loads(settle[1][8])["runtime_run_id"] == "runtime-1"
    assert settle[2] == "parent-1"


def test_cancel_requires_runtime_drain_before_terminal_status(tmp_path):
    calls = run_runtime(tmp_path, """
const operate = createAnalysisRuntime(ctx, ['analysis-state'], invoke);
await operate('analysis-job-cancel', {job: 'job-1'}, exec);
process.stdout.write(JSON.stringify(calls));
""")
    assert [entry[0] for entry in calls] == ["cli", "runtime-drain", "cli"]
    assert calls[2][1][6] == "cancelled"


def test_script_retry_uses_service_worker_without_starting_a_child(tmp_path):
    calls = run_runtime(tmp_path, """
job.kind = 'script';
const operate = createAnalysisRuntime(ctx, ['analysis-state'], invoke);
await operate('analysis-job-retry', {job: 'old-job'}, exec);
process.stdout.write(JSON.stringify(calls));
""")
    assert len(calls) == 1
    assert calls[0][1][:3] == ["analysis-job-retry", "--job", "old-job"]
    assert calls[0][1][3] == "--runtime-pid"
    assert int(calls[0][1][4]) > 0
