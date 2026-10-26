from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_observer(tmp_path: Path, *, fail_state: bool = False, max_buffer_bytes: str | None = None, trace: bool = False,
                 deadline_mode: str = "", tool_attempts: int = 0, tool_limit: int | None = None) -> dict:
    if NODE is None:
        pytest.skip("node is unavailable")
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "index.mjs").write_text((ROOT / "tools" / "verify_finance_evals.mjs").read_text(encoding="utf-8"), encoding="utf-8")
    report = tmp_path / "report.json"
    dsh_root = tmp_path / "dsh-root"
    llm = dsh_root / "node_modules" / "@deepseek-ai" / "dsh-llm" / "lib"
    llm.mkdir(parents=True)
    (llm / "index.js").write_text("export const createUserMessage = (message) => message;\n", encoding="utf-8")
    config = {
        "report": str(report),
        "dshRoot": str(dsh_root),
        "ids": [],
        "timeoutSeconds": 3 if tool_attempts else 0.5 if deadline_mode else 1,
        "cases": [{
            "id": "F01",
            "sessionId": "session-f01",
            "taskId": "task-f01",
            "workspace": str(tmp_path),
            "inputSha256": "abc",
            "question": "解释利润",
        }],
    }
    if tool_limit is not None:
        config['maxToolTurns'] = tool_limit
    (probe / "config.json").write_text(json.dumps(config), encoding="utf-8")
    foundry = tmp_path / "foundry.mjs"
    foundry.write_text(
        """
#!/usr/bin/env node
const args = process.argv.slice(2);
const hasCommand = (name) => args.includes(name);
if (hasCommand('record-session')) {
  if (process.env.DEADLINE_MODE === 'sync_record' && args.includes('session-f01')) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,1000);
  }
  process.stdout.write(JSON.stringify({recorded: true}));
} else if (hasCommand('analysis-state')) {
  if (process.env.DEADLINE_MODE === 'evidence') Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,750);
  if (process.env.FAIL_STATE === '1') {
    console.error('analysis-state failed marker');
    process.exit(7);
  }
  const body = 'x'.repeat(1_250_000);
  process.stdout.write(JSON.stringify({drafts: [{id: 'draft-large', body}], runs: [{id: 'run-1'}, {id: 'run-2'}]}));
} else {
  console.error(`unexpected foundry args: ${JSON.stringify(args)}`);
  process.exit(2);
}
""".strip(),
        encoding="utf-8",
    )
    foundry.chmod(0o755)
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f"""
import {{ apply }} from {json.dumps((probe / 'index.mjs').as_uri())};
const events = [];
const listeners = {{}};
const mode = {json.dumps(deadline_mode)};
const block = () => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,750);
const modelAbort = new AbortController();
let followed = false;
const agent = {{
  id: 'session-f01',
  session: {{ events, deriveMessages: () => [] }},
  followup: () => {{ followed = true; events.push({{type:'test/followup'}}); }},
  cancel: () => {{ events.push({{type:'test/cancel'}}); modelAbort.abort(new Error('agent cancelled')); }},
  whenIdle: async () => {{
    if ({tool_attempts}) {{
      for (let index = 0; index < {tool_attempts}; index++) {{
        const exec = {{callId:`budget-${{index}}`,name:'analysis-state',arguments:{{}},agent}};
        const result = await listeners['tools/execute'](exec, async () => {{
          events.push({{type:'test/budget_tool_entered', index}});
          return {{isError:false,value:{{index}}}};
        }});
        listeners['tools/result'](exec, result);
      }}
      return;
    }}
    if (mode === 'late') {{ block(); return; }}
    if (mode === 'tool_admission' || mode === 'model_admission') block();
    if (mode === 'tool_admission' || mode === 'tool_abort') {{
      const exec = {{callId:'deadline-tool',name:'analysis-state',arguments:{{}},agent}};
      await listeners['tools/execute'](exec, async () => {{
        events.push({{type:'test/tool_entered'}});
        await new Promise(resolve => exec.signal.addEventListener('abort', () => {{
          events.push({{type:'test/tool_aborted'}}); resolve();
        }}, {{once:true}}));
      }});
      return;
    }}
    if (mode === 'model_admission' || mode === 'model_abort') {{
      const options = Object.freeze({{sessionId:agent.id,signal:modelAbort.signal}});
      for await (const chunk of listeners['llm/stream'](options, async function*() {{
        events.push({{type:'test/model_entered'}});
        if (mode === 'model_abort') await new Promise(resolve => options.signal.addEventListener('abort', () => {{
          events.push({{type:'test/model_aborted'}}); resolve();
        }}, {{once:true}}));
        yield {{type:'finish',reason:{{kind:'stop'}}}};
      }})) {{}}
      return;
    }}
    if (!{json.dumps(trace)}) return;
    for (const [id, name, args, value] of [
      ['resource-1', 'method-resource', {{skill:'variance-analysis',resource:'FOUNDRY.md'}}, {{stdout:JSON.stringify({{sha256:'resource-hash',content:'rules'}})}}],
      ['calc-1', 'explain_variance', {{context:'context-1'}}, {{stdout:'{{}}'}}],
    ]) {{
      const exec = {{callId:id,name,arguments:args,agent}};
      await listeners['tools/execute'](exec, async () => ({{isError:false,value}}));
      listeners['tools/result'](exec, {{isError:false,value}});
    }}
  }},
}};
const ctx = {{
  on: (name, handler) => {{listeners[name] = handler;}},
  agentPresets: {{ standingKeyFor: async () => 'analysis', mount: async () => {{}} }},
  agentDefaultModel: {{ currentSelection: () => ({{ provider: 'fake', model: 'fake-model' }}) }},
  agents: {{ create: async (options) => {{
    await options.setup({{on: (name, handler) => {{listeners[name] = handler;}}}});
    if (mode === 'create' && options.sessionId === 'session-f01') block();
    if (mode === 'create_async' && options.sessionId === 'session-f01') await new Promise(resolve => setTimeout(resolve, 750));
    return {{ agent, dispose: async () => {{
      events.push({{type:'test/dispose',session:options.sessionId}});
      if (options.sessionId !== 'session-f01') return;
      try {{
        if (mode === 'closed_model_admission') {{
          for await (const chunk of listeners['llm/stream'](Object.freeze({{sessionId:agent.id,signal:modelAbort.signal}}), async function*() {{
            events.push({{type:'test/closed_model_entered'}}); yield {{type:'finish',reason:{{kind:'stop'}}}};
          }})) {{}}
        }}
        if (mode === 'closed_tool_admission') {{
          await listeners['tools/execute']({{callId:'closed-tool',name:'analysis-state',arguments:{{}},agent}}, async () => {{
            events.push({{type:'test/closed_tool_entered'}}); return {{isError:false,value:{{}}}};
          }});
        }}
      }} catch (error) {{events.push({{type:'test/closed_admission_rejected',name:error.name}});}}
    }} }};
  }} }},
  tools: {{ execute: async () => ({{ isError: false, value: {{ provider: 'fake', resourceBase: 'fake', content: '' }} }}) }},
  skills: {{ snapshot: async () => ({{ skills: [], complete: true }}) }},
}};
apply(ctx);
for (let i = 0; i < 100; i += 1) {{
  await new Promise((resolve) => setTimeout(resolve, 20));
  try {{
    const report = JSON.parse(await import('node:fs/promises').then(fs => fs.readFile({json.dumps(str(report))}, 'utf8')));
    if (report.status !== 'running') {{
      if (mode === 'create_async') {{
        await new Promise(resolve => setTimeout(resolve, 750));
        await import('node:fs/promises').then(fs => fs.writeFile({json.dumps(str(tmp_path / 'late-create-events.json'))}, JSON.stringify(events)));
      }}
      console.log(JSON.stringify(report));
      process.exit(0);
    }}
  }} catch {{}}
}}
console.error('observer did not finish');
process.exit(1);
""",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "FOUNDRY_BIN": str(foundry),
        "FOUNDRY_VAR": str(tmp_path / "var"),
        "DEADLINE_MODE": deadline_mode,
        **({"FAIL_STATE": "1"} if fail_state else {}),
    }
    if max_buffer_bytes is not None:
        env["FOUNDRY_OBSERVER_MAX_BUFFER_BYTES"] = max_buffer_bytes
    result = subprocess.run(
        [NODE, str(driver)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-1000:]
    return json.loads(report.read_text(encoding="utf-8"))


def test_finance_eval_observer_reads_large_analysis_state_without_enobufs(tmp_path: Path) -> None:
    report = run_observer(tmp_path)
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert "state_error" not in case
    assert case["final_draft"]["id"] == "draft-large"
    assert len(case["final_draft"]["body"]) == 1_250_000
    assert case["runs_seen"] == 2
    snapshot = tmp_path / case["state_snapshot"]["path"]
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == case["state_snapshot"]["sha256"]
    assert json.loads(snapshot.read_text())["drafts"][0] == case["final_draft"]


def test_finance_eval_observer_records_analysis_state_failure_on_case(tmp_path: Path) -> None:
    report = run_observer(tmp_path, fail_state=True)
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert case["completed"] is True
    assert "analysis-state failed marker" in case["state_error"]
    assert case.get("final_draft") is None


def test_finance_eval_observer_rejects_invalid_buffer_override(tmp_path: Path) -> None:
    report = run_observer(tmp_path, max_buffer_bytes="Infinity")
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert case["completed"] is True
    assert "state_error" not in case
    assert case["final_draft"]["id"] == "draft-large"


def test_finance_eval_observer_keeps_case_completed_when_analysis_state_exceeds_buffer(tmp_path: Path) -> None:
    report = run_observer(tmp_path, max_buffer_bytes="1024")
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert case["completed"] is True
    assert "ENOBUFS" in case["state_error"]
    assert case.get("final_draft") is None


def test_observer_records_resource_end_before_calc_start_with_call_identity(tmp_path: Path) -> None:
    case = run_observer(tmp_path, trace=True)["cases"][0]
    events = case["tool_events"]
    assert [e["phase"] for e in events] == ["start", "end", "start", "end"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert events[0]["call_id"] == events[1]["call_id"] == "resource-1"
    assert events[1]["content_sha256"] == "resource-hash"
    assert int(events[1]["monotonic_ns"]) < int(events[2]["monotonic_ns"])
    assert all(e["session_id"] == "session-f01" for e in events)
    assert events[0]["arguments_sha256"] == events[1]["arguments_sha256"]
    assert case["calls"][0]["call_id"] == "resource-1"
    assert case["usage"]["input_tokens"] is None


@pytest.mark.parametrize("mode", ["create", "late", "tool_admission", "model_admission", "tool_abort", "model_abort", "sync_record"])
def test_absolute_deadline_covers_creation_late_completion_and_admission(tmp_path: Path, mode: str) -> None:
    case = run_observer(tmp_path, deadline_mode=mode)["cases"][0]
    assert case["completed"] is False
    assert "exceeded 0.5s" in case["error"]
    assert case["deadline"]["schema_version"] == 1
    assert case["deadline"]["exceeded"] is True
    assert case["deadline"]["execution_ended"] is True
    phases = [event["phase"] for event in case["deadline"]["events"]]
    assert phases[0] == "deadline_armed"
    assert "deadline_fired" in phases
    events = [event["type"] for event in case["events"]]
    assert "test/cancel" in events
    if mode in {"create", "sync_record"}:
        assert "test/followup" not in events
    if mode == "tool_admission":
        assert "test/tool_entered" not in events
    if mode == "model_admission":
        assert "test/model_entered" not in events
    if mode == "tool_abort":
        assert "test/tool_entered" in events
        assert "test/tool_aborted" in events
    if mode == "model_abort":
        assert "test/model_entered" in events
        assert "test/model_aborted" in events


def test_creation_resolving_after_deadline_is_cancelled_and_disposed_without_followup(tmp_path: Path) -> None:
    case = run_observer(tmp_path, deadline_mode="create_async")["cases"][0]
    assert case["completed"] is False
    assert case["deadline"]["exceeded"] is True
    events = json.loads((tmp_path / "late-create-events.json").read_text())
    assert any(event["type"] == "test/cancel" for event in events)
    assert any(event == {"type": "test/dispose", "session": "session-f01"} for event in events)
    assert not any(event["type"] == "test/followup" for event in events)


def test_evidence_collection_has_separate_timing_after_execution_ends(tmp_path: Path) -> None:
    case = run_observer(tmp_path, deadline_mode="evidence")["cases"][0]
    assert case["completed"] is True
    assert case["duration_ms"] <= 500
    assert case["deadline"]["exceeded"] is False
    assert case["evidence_collection_ms"] >= 750


@pytest.mark.parametrize("kind", ["model", "tool"])
def test_budget_closed_rejects_deferred_background_admission_during_disposal(tmp_path: Path, kind: str) -> None:
    case = run_observer(tmp_path, deadline_mode=f"closed_{kind}_admission")["cases"][0]
    assert case["completed"] is True
    assert case["deadline"]["exceeded"] is False
    assert case["deadline"]["runtime_terminated"] is True
    events = [event["type"] for event in case["events"]]
    assert "test/closed_admission_rejected" in events
    assert f"test/closed_{kind}_entered" not in events
    receipt = case["deadline"]["events"]
    rejected = [event for event in receipt if event["phase"] == "admission_rejected"]
    assert rejected and rejected[0]["requested_phase"] == f"{kind}_admission"
    assert rejected[0]["reason"] == "budget_closed"
    closed = next(event["elapsed_ms"] for event in receipt if event["phase"] == "budget_closed")
    assert all(event["elapsed_ms"] < closed for event in receipt if event["phase"] in {"model_start", "tool_start"})
