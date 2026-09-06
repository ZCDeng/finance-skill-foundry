"""Real DSH completion-runtime integration without a paid provider or live port.

This test boots an installed DSH web profile with a local deterministic LLM
adapter. It verifies the real analysis preset mounts `save_explanation_draft`
through `createCompletionRuntime`, that DSH publishes true `user/message` events,
and that the post-`tools/result` cancellation preserves the saved tool result
while allowing a later user message to continue.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from foundry.harness import install_presets
from foundry.task import TaskStore
from test_real_load import (  # reuse the real harness installer; do not fork it here
    DSH_BIN,
    ROOT,
    WEB_SETTLE_SECONDS,
    _dsh_args,
    _prepare,
    _probe_package,
    needs_dsh,
)


COMPLETION_RUNTIME_PROBE = r"""
export const name = 'foundry-completion-runtime-probe';
export const inject = ['tools', 'agentPresets', 'llm', 'agents'];
export function apply(ctx) {
  (async () => {
    const { LlmAdapter, createUserMessage } = await import(process.env.FOUNDRY_LLM_MODULE);
    const report = {eventsAfterFirst: [], eventsAfterSecond: [], calls: [], toolResults: [], streams: [], cancels: []};
    let streams = 0;
    ctx.llm.registerAdapter(['foundry-completion-fixture'], new class extends LlmAdapter {
      async *stream(options) {
        options.signal?.throwIfAborted();
        const messages = options.messages.map(message => ({role: message.role, source: message.source, content: message.content}));
        report.streams.push({index: streams, tools: options.tools.map(tool => tool.name), messages});
        let block;
        if (streams === 0) {
          block = {
            type: 'tool-call',
            id: 'save-call-needs-review',
            name: 'save_explanation_draft',
            arguments: JSON.stringify({spec: {title: '待核对', body: '本次判断仍需资料支持。'}}),
          };
        } else {
          block = {type: 'text', text: 'SECOND_USER_CAN_CONTINUE_DONE'};
        }
        streams += 1;
        yield {type: 'block-start', index: 0, blockType: block.type};
        yield {type: 'block-end', index: 0, block};
        yield {type: 'finish', reason: {kind: block.type === 'tool-call' ? 'tool-calls' : 'stop'}};
      }
    }());
    await ctx.agentPresets.standingKeyFor('analysis');
    const handle = await ctx.agents.create({
      sessionId: 'completion-runtime-real',
      meta: {cwd: process.env.FOUNDRY_TEST_WORKSPACE, agentPreset: 'analysis'},
      agentOptions: {provider: 'foundry-completion-fixture', model: 'deterministic'},
      setup: async (agentCtx) => {
        await ctx.agentPresets.mount(agentCtx, 'analysis');
        const originalCancel = agentCtx.agent.cancel.bind(agentCtx.agent);
        agentCtx.agent.cancel = (cause, options) => {
          report.cancels.push({cause, options});
          return originalCancel(cause, options);
        };
        agentCtx.on('tools/result', (exec, result) => {
          if (exec.agent.id !== 'completion-runtime-real') return;
          report.toolResults.push({name: exec.name, callId: exec.callId, isError: result.isError === true, value: result.value, error: result.error});
        });
      },
    });
    try {
      handle.agent.followup(createUserMessage({content: [{type: 'text', text: 'FIRST_USER_SAVE_NEEDS_REVIEW'}], source: {kind: 'user'}}));
      await handle.agent.whenIdle();
      report.eventsAfterFirst = handle.agent.session.events;
      handle.agent.followup(createUserMessage({content: [{type: 'text', text: 'SECOND_USER_CAN_CONTINUE'}], source: {kind: 'user'}}));
      await handle.agent.whenIdle();
      report.eventsAfterSecond = handle.agent.session.events;
      report.messages = handle.agent.session.deriveMessages();
      process.stdout.write('FOUNDRY_COMPLETION_RUNTIME ' + JSON.stringify(report) + '\n');
    } finally {
      await handle.dispose();
    }
  })().catch(error => process.stdout.write('FOUNDRY_COMPLETION_RUNTIME_ERROR ' + (error.stack ?? error.message) + '\n'));
}
"""

PREFLIGHT_RESOURCE_PROBE = r"""
export const name = 'foundry-completion-preflight-probe';
export const inject = ['tools', 'agentPresets', 'agents'];
export function apply(ctx) {
  (async () => {
    const report = {resource: null, save: null, toolResults: []};
    await ctx.agentPresets.standingKeyFor('analysis');
    const handle = await ctx.agents.create({
      sessionId: 'completion-preflight-real',
      meta: {cwd: process.env.FOUNDRY_TEST_WORKSPACE, agentPreset: 'analysis'},
      agentOptions: {provider: 'foundry-preflight-unused', model: 'deterministic'},
      setup: async (agentCtx) => {
        await ctx.agentPresets.mount(agentCtx, 'analysis');
        agentCtx.on('tools/result', (exec, result) => {
          if (exec.agent.id !== 'completion-preflight-real') return;
          report.toolResults.push({name: exec.name, callId: exec.callId, isError: result.isError === true});
        });
      },
    });
    const agent = handle.agent;
    try {
      const dispatch = async (name, args, callId) => {
        const result = await ctx.tools.execute({
          callId,
          name,
          arguments: args,
          agent,
          signal: new AbortController().signal,
        });
        if (result.isError) return {isError: true, error: result.error};
        return {isError: false, value: JSON.parse(result.value.stdout)};
      };
      report.resource = await dispatch('method-resource', {skill: 'financial-statements', resource: 'FOUNDRY.md'}, 'preflight-resource');
      report.save = await dispatch('save_explanation_draft', {spec: {title: '无人类事件', body: '不应保存'}}, 'preflight-save');
      process.stdout.write('FOUNDRY_PREFLIGHT_RESOURCE ' + JSON.stringify(report) + '\n');
    } finally {
      await handle.dispose();
    }
  })().catch(error => process.stdout.write('FOUNDRY_PREFLIGHT_RESOURCE_ERROR ' + (error.stack ?? error.message) + '\n'));
}
"""


@needs_dsh
def test_completion_runtime_uses_real_dsh_events_and_keeps_inbox(tmp_path: Path) -> None:
    home = tmp_path / "dsh-home"
    _prepare(home, _probe_package(tmp_path / "probe", COMPLETION_RUNTIME_PROBE), "web")
    install_presets(home)

    var = tmp_path / "var"
    task = TaskStore(var).create(title="真实 completion runtime")
    task.record_session("completion-runtime-real", role="analysis")
    workspace = task.root / "analysis"

    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env.update(
        {
            "FOUNDRY_VAR": str(var),
            "FOUNDRY_BIN": str(ROOT / ".venv" / "bin" / "foundry"),
            "FOUNDRY_LLM_MODULE": (Path(DSH_BIN).resolve().parents[2] / "dsh-llm" / "lib" / "index.js").as_uri(),
            "FOUNDRY_TEST_WORKSPACE": str(workspace),
            "FOUNDRY_COMPLETION_MAX_REPAIRS": "0",
        }
    )
    log = tmp_path / "completion-runtime-real.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + WEB_SETTLE_SECONDS
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace")
                if "FOUNDRY_COMPLETION_RUNTIME " in output or "FOUNDRY_COMPLETION_RUNTIME_ERROR " in output:
                    break
                time.sleep(0.2)
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)

    output = log.read_text(encoding="utf-8", errors="replace")
    assert "FOUNDRY_COMPLETION_RUNTIME_ERROR " not in output, output[-12000:]
    lines = [line for line in output.splitlines() if line.startswith("FOUNDRY_COMPLETION_RUNTIME ")]
    assert lines, output[-12000:]
    report = json.loads(lines[-1].split(" ", 1)[1])

    first_user_events = [
        event for event in report["eventsAfterFirst"]
        if event.get("type") == "user/message" and event.get("data", {}).get("source", {}).get("kind") == "user"
    ]
    assert first_user_events, report["eventsAfterFirst"]
    assert all("seq" in event and "data" in event for event in first_user_events)
    assert first_user_events[-1]["data"]["content"][0]["text"] == "FIRST_USER_SAVE_NEEDS_REVIEW"

    save_results = [row for row in report["toolResults"] if row["name"] == "save_explanation_draft"]
    assert save_results, report
    assert save_results[0]["callId"] == "save-call-needs-review"
    assert save_results[0]["isError"] is False, save_results[0]
    saved_stdout = json.loads(save_results[0]["value"]["stdout"])
    assert saved_stdout["completion_operation"]["status"] == "needs_review"
    assert saved_stdout["completion_operation"]["revisions"][0]["call_id"] == "save-call-needs-review"

    assert report["cancels"], report
    assert report["cancels"][0] == {
        "cause": {"kind": "hook", "reason": "finance completion needs_review"},
        "options": {"keepInbox": True},
    }
    assert any(
        stream["index"] > 0 and "SECOND_USER_CAN_CONTINUE" in json.dumps(stream["messages"], ensure_ascii=False)
        for stream in report["streams"]
    ), report["streams"]
    assert "SECOND_USER_CAN_CONTINUE_DONE" in json.dumps(report["messages"], ensure_ascii=False)

    operations = list((task.root / "analysis" / "completion_operations").glob("*.json"))
    assert operations
    operation = json.loads(operations[0].read_text(encoding="utf-8"))
    assert operation["request_key"].startswith("completion-runtime-real:")
    assert operation["status"] == "needs_review"


@needs_dsh
def test_preflight_method_resource_without_human_event_and_save_guard(tmp_path: Path) -> None:
    home = tmp_path / "dsh-home"
    _prepare(home, _probe_package(tmp_path / "probe", PREFLIGHT_RESOURCE_PROBE), "web")
    install_presets(home)

    var = tmp_path / "var"
    task = TaskStore(var).create(title="真实 preflight resource")
    task.record_session("completion-preflight-real", role="analysis")
    workspace = task.root / "analysis"

    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env.update(
        {
            "FOUNDRY_VAR": str(var),
            "FOUNDRY_BIN": str(ROOT / ".venv" / "bin" / "foundry"),
            "FOUNDRY_TEST_WORKSPACE": str(workspace),
        }
    )
    log = tmp_path / "preflight-resource-real.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + WEB_SETTLE_SECONDS
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace")
                if "FOUNDRY_PREFLIGHT_RESOURCE " in output or "FOUNDRY_PREFLIGHT_RESOURCE_ERROR " in output:
                    break
                time.sleep(0.2)
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)

    output = log.read_text(encoding="utf-8", errors="replace")
    assert "FOUNDRY_PREFLIGHT_RESOURCE_ERROR " not in output, output[-12000:]
    lines = [line for line in output.splitlines() if line.startswith("FOUNDRY_PREFLIGHT_RESOURCE ")]
    assert lines, output[-12000:]
    report = json.loads(lines[-1].split(" ", 1)[1])

    assert report["resource"]["isError"] is False, report
    resource = report["resource"]["value"]
    assert resource["resource"] == "FOUNDRY.md"
    assert resource["skill"] == "financial-statements"
    assert "save_explanation_draft" in resource["content"]

    assert report["save"]["isError"] is True, report
    assert "requires a human user/message event" in json.dumps(report["save"]["error"])
    assert report["toolResults"] == [
        {"name": "method-resource", "callId": "preflight-resource", "isError": False},
        {"name": "save_explanation_draft", "callId": "preflight-save", "isError": True},
    ]
    assert not (task.root / "analysis" / "completion_operations").exists()
