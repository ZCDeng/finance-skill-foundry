import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createCompletionRuntime } from "./completion-runtime.js";

function user(seq, id, text = "分析应收") {
  return {
    type: "user/message",
    seq,
    time: Date.now(),
    data: { id, source: { kind: "user" }, content: [{ type: "text", text }] },
  };
}

function runtimeEvent(seq) {
  return { type: "user/message", seq, time: Date.now(), data: { source: { kind: "goal" }, content: [{ type: "text", text: "background" }] } };
}

function assistant(seq) {
  return { type: "assistant/message", seq, time: Date.now(), data: { turn: 1, step: 1, message: { role: "assistant", content: [] } } };
}

function execFor(events, overrides = {}) {
  const { agent: agentOverrides, ...rest } = overrides;
  return {
    name: "save_explanation_draft",
    callId: "call-1",
    agent: {
      id: "session-a",
      session: { events },
      ...agentOverrides,
    },
    ...rest,
  };
}

function makeCtx() {
  const handlers = [];
  return {
    handlers,
    warnings: [],
    logger: { warn(message) { this.warnings?.push?.(message); } },
    on(event, handler) {
      assert.equal(event, "tools/result");
      handlers.push(handler);
      return () => {
        const index = handlers.indexOf(handler);
        if (index >= 0) handlers.splice(index, 1);
      };
    },
    emitToolResult(exec, result = { isError: false }) {
      for (const handler of [...handlers]) handler(exec, result);
    },
  };
}

async function flushMicrotasks() {
  await new Promise((resolve) => setImmediate(resolve));
}

function makeInvoke({ begin = {}, status = {}, log = [] } = {}) {
  return async (args, exec) => {
    log.push({ args, exec });
    if (args[0] === "finance-completion-begin") {
      return JSON.stringify({ id: "op-1", deadline_at: new Date(Date.now() + 60_000).toISOString(), status: "running", ...begin });
    }
    if (args[0] === "finance-completion-status") return JSON.stringify({ id: "op-1", status: "complete", ...status });
    if (args[0] === "finance-completion-stop") return JSON.stringify({ stopped: true });
    throw new Error(`unexpected command ${args[0]}`);
  };
}

function spec(title = "ok") {
  return { spec: { title, body: "说明", claims: [] } };
}

function repoRootUrl() {
  let current = new URL(".", import.meta.url);
  for (let depth = 0; depth < 8; depth += 1) {
    if (existsSync(new URL("foundry/cli.py", current))) return current;
    current = new URL("../", current);
  }
  throw new Error("unable to locate finance-skill-foundry repository root");
}

async function testNonSavePassThrough() {
  const log = [];
  const runtime = createCompletionRuntime({}, makeInvoke({ log }));
  const output = await runtime("analysis-run", { spec: { a: 1 } }, execFor([user(1, "u1")]), async (input) => JSON.stringify(input));
  assert.equal(output, JSON.stringify({ spec: { a: 1 } }));
  assert.equal(log.length, 0);
}

async function testRejectsAuthorityFromTopAndSpec() {
  const runtime = createCompletionRuntime({}, makeInvoke());
  await assert.rejects(() => runtime("save_explanation_draft", { spec: {}, _completion_operation: "evil" }, execFor([user(1, "u1")]), async () => "{}"), /authority field/);
  await assert.rejects(() => runtime("save_explanation_draft", { spec: { completion_operation_id: "evil" } }, execFor([user(1, "u1")]), async () => "{}"), /spec authority field/);
  await assert.rejects(() => runtime("save_explanation_draft", { spec: { _private: true } }, execFor([user(1, "u1")]), async () => "{}"), /spec authority field/);
}

async function testRequestKeyUsesRealDshUserMessageShape() {
  const log = [];
  const runtime = createCompletionRuntime({}, makeInvoke({ log }));
  const exec = execFor([user(1, "old"), assistant(2), user(3, "new"), runtimeEvent(4)]);
  await runtime("save_explanation_draft", spec(), exec, async (input) => {
    assert.equal(input._completion_operation, "op-1");
    assert.equal(input._completion_call_id, "call-1");
    return JSON.stringify({ saved: true });
  });
  const beginSpec = JSON.parse(log.find((item) => item.args[0] === "finance-completion-begin").args[2]);
  assert.equal(beginSpec.request_key, "session-a:message:new:seq:3");
  assert.deepEqual(beginSpec.policy, {});
}

async function testPolicyComesOnlyFromThirdArgAndTrustedEnv() {
  const previousMax = process.env.FOUNDRY_COMPLETION_MAX_REPAIRS;
  const previousTimeout = process.env.FOUNDRY_COMPLETION_TIMEOUT_SECONDS;
  process.env.FOUNDRY_COMPLETION_MAX_REPAIRS = "1";
  process.env.FOUNDRY_COMPLETION_TIMEOUT_SECONDS = "abc";
  try {
    const log = [];
    const runtime = createCompletionRuntime({}, makeInvoke({ log }), { max_repairs: 0, timeout_seconds: 300, ignored: true });
    await runtime("save_explanation_draft", spec(), execFor([user(1, "u1")]), async () => "{}");
    const beginSpec = JSON.parse(log.find((item) => item.args[0] === "finance-completion-begin").args[2]);
    assert.deepEqual(beginSpec.policy, { max_repairs: 1, timeout_seconds: "abc" });
  } finally {
    if (previousMax === undefined) delete process.env.FOUNDRY_COMPLETION_MAX_REPAIRS;
    else process.env.FOUNDRY_COMPLETION_MAX_REPAIRS = previousMax;
    if (previousTimeout === undefined) delete process.env.FOUNDRY_COMPLETION_TIMEOUT_SECONDS;
    else process.env.FOUNDRY_COMPLETION_TIMEOUT_SECONDS = previousTimeout;
  }
}

async function testRequiresTrustedCallIdAndDeadline() {
  const runtime = createCompletionRuntime({}, makeInvoke());
  const exec = execFor([user(1, "u1")]);
  delete exec.callId;
  await assert.rejects(() => runtime("save_explanation_draft", spec(), exec, async () => "{}"), /trusted exec.callId/);
  const runtime2 = createCompletionRuntime({}, makeInvoke({ begin: { deadline_at: null } }));
  await assert.rejects(() => runtime2("save_explanation_draft", spec(), execFor([user(1, "u1")]), async () => "{}"), /deadline_at/);
  const execWithFallbackOnly = execFor([user(1, "u1")]);
  delete execWithFallbackOnly.callId;
  execWithFallbackOnly.call = { id: "not-trusted" };
  execWithFallbackOnly.toolCall = { id: "not-trusted-either" };
  await assert.rejects(() => runtime("save_explanation_draft", spec(), execWithFallbackOnly, async () => "{}"), /trusted exec.callId/);
}

async function testResultObserverUsesRealSignatureAndExactExecIdentity() {
  const cancelLog = [];
  const ctx = makeCtx();
  const runtime = createCompletionRuntime(ctx, makeInvoke({ begin: { id: "op-needs" }, status: { status: "needs_review" } }));
  const exec = execFor([user(1, "u1")], { callId: "call-needs", agent: { cancel: (cause, options) => cancelLog.push({ cause, options }) } });
  const raw = await runtime("save_explanation_draft", spec(), exec, async () => JSON.stringify({ saved: true }));
  assert.equal(raw, JSON.stringify({ saved: true }));
  assert.equal(cancelLog.length, 0);
  ctx.emitToolResult({ ...exec, callId: "other" });
  await flushMicrotasks();
  assert.equal(cancelLog.length, 0);
  ctx.emitToolResult(exec);
  await flushMicrotasks();
  assert.equal(cancelLog.length, 1);
  assert.deepEqual(cancelLog[0].cause, { kind: "hook", reason: "finance completion needs_review" });
  assert.deepEqual(cancelLog[0].options, { keepInbox: true });
}

async function testCompleteAndRepairAvailableDoNotCancelAfterResult() {
  for (const state of ["complete", "repair_available"]) {
    const cancelLog = [];
    const ctx = makeCtx();
    const runtime = createCompletionRuntime(ctx, makeInvoke({ status: { status: state } }));
    const exec = execFor([user(1, state)], { agent: { cancel: (cause, options) => cancelLog.push({ cause, options }) } });
    await runtime("save_explanation_draft", spec(state), exec, async () => "{}");
    ctx.emitToolResult(exec);
    await flushMicrotasks();
    assert.equal(cancelLog.length, 0, state);
  }
}

async function testNewUserOnNonSaveStopsSupersededOldOperation() {
  const log = [];
  const runtime = createCompletionRuntime({}, makeInvoke({ begin: { id: "op-active" }, status: { status: "repair_available" }, log }));
  const exec = execFor([user(1, "u1")], { callId: "call-active" });
  await runtime("save_explanation_draft", spec("active"), exec, async () => "{}");
  exec.agent.session.events.push(user(2, "u2"));
  const output = await runtime("analysis-run", { spec: { ok: true } }, { ...exec, name: "analysis-run", callId: "non-save" }, async (input) => JSON.stringify(input));
  assert.equal(output, JSON.stringify({ spec: { ok: true } }));
  const stops = log.filter((item) => item.args[0] === "finance-completion-stop").map((item) => JSON.parse(item.args[2]).reason);
  assert.deepEqual(stops, ["superseded"]);
}

async function testBeginTerminalCompleteDoesNotArmTimerOrCancel() {
  const cancelLog = [];
  const log = [];
  const ctx = makeCtx();
  const runtime = createCompletionRuntime(ctx, makeInvoke({ begin: { id: "op-complete", status: "complete", deadline_at: null }, status: { status: "complete" }, log }));
  const exec = execFor([user(1, "u1")], { agent: { cancel: (cause, options) => cancelLog.push({ cause, options }) } });
  await runtime("save_explanation_draft", spec("replay"), exec, async () => "{}");
  ctx.emitToolResult(exec);
  await flushMicrotasks();
  assert.equal(cancelLog.length, 0);
  assert.equal(log.some((item) => item.args[0] === "finance-completion-stop"), false);
}

async function testExternalSignalListenerIsRemoved() {
  const controller = new AbortController();
  let adds = 0;
  let removes = 0;
  const originalAdd = controller.signal.addEventListener.bind(controller.signal);
  const originalRemove = controller.signal.removeEventListener.bind(controller.signal);
  controller.signal.addEventListener = (...args) => { adds += 1; return originalAdd(...args); };
  controller.signal.removeEventListener = (...args) => { removes += 1; return originalRemove(...args); };
  const runtime = createCompletionRuntime({}, makeInvoke());
  await runtime("save_explanation_draft", spec("listener"), execFor([user(1, "u1")], { signal: controller.signal }), async () => "{}");
  assert.equal(adds, 1);
  assert.equal(removes, 1);
}

async function testNewUserBeforeResultPreventsCancelAndSupersedesOldOperation() {
  const cancelLog = [];
  const log = [];
  const ctx = makeCtx();
  const events = [user(1, "u1")];
  const exec = execFor(events, { agent: { cancel: (cause, options) => cancelLog.push({ cause, options }) } });

  const terminalRuntime = createCompletionRuntime(ctx, makeInvoke({ status: { status: "awaiting_input" }, log }));
  await terminalRuntime("save_explanation_draft", spec("old"), exec, async () => "{}");
  events.push(user(2, "u2"));
  ctx.emitToolResult(exec);
  await flushMicrotasks();
  assert.equal(cancelLog.length, 0);

  const activeRuntime = createCompletionRuntime(ctx, makeInvoke({ begin: { id: "op-active" }, status: { status: "repair_available" }, log }));
  const activeExec = execFor([user(1, "a1")], { callId: "call-active" });
  await activeRuntime("save_explanation_draft", spec("active"), activeExec, async () => "{}");
  activeExec.agent.session.events.push(user(2, "a2"));
  await activeRuntime("save_explanation_draft", spec("new"), { ...activeExec, callId: "call-new" }, async () => "{}");
  const stops = log.filter((item) => item.args[0] === "finance-completion-stop").map((item) => JSON.parse(item.args[2]).reason);
  assert.deepEqual(stops, ["superseded"]);
}

async function testDeadlineTimerStopsWithTimeoutAndCancelsSameUser() {
  const cancelLog = [];
  const log = [];
  const runtime = createCompletionRuntime({}, makeInvoke({ begin: { id: "op-time", deadline_at: new Date(Date.now() + 20).toISOString() }, status: { status: "running" }, log }));
  const exec = execFor([user(1, "u1")], { agent: { cancel: (cause, options) => cancelLog.push({ cause, options }) } });
  const keepAlive = setInterval(() => {}, 1000);
  try {
    await assert.rejects(() => runtime("save_explanation_draft", spec("slow"), exec, async (_input, runExec) => new Promise((_resolve, reject) => {
      runExec.signal.addEventListener("abort", () => reject(runExec.signal.reason), { once: true });
    })), /timed out|Timeout/);
  } finally {
    clearInterval(keepAlive);
  }
  await flushMicrotasks();
  const stop = log.find((item) => item.args[0] === "finance-completion-stop");
  assert.equal(JSON.parse(stop.args[2]).reason, "timeout");
  assert.equal(stop.exec.signal, undefined);
  assert.equal(cancelLog.length, 1);
  assert.deepEqual(cancelLog[0].cause, { kind: "hook", reason: "finance completion timeout" });
  assert.deepEqual(cancelLog[0].options, { keepInbox: true });
}

async function testExternalCancelStopsCancelled() {
  const controller = new AbortController();
  const log = [];
  const runtime = createCompletionRuntime({}, makeInvoke({ begin: { id: "op-cancel" }, log }));
  controller.abort(new Error("user stopped"));
  await assert.rejects(() => runtime("save_explanation_draft", spec("cancel"), execFor([user(1, "u1")], { signal: controller.signal }), async (_input, runExec) => {
    throw runExec.signal.reason;
  }), /user stopped/);
  const stop = log.find((item) => item.args[0] === "finance-completion-stop");
  assert.equal(JSON.parse(stop.args[2]).reason, "cancelled");
  assert.equal(stop.exec.signal, undefined);
}

function testBackendCliSmoke() {
  const root = mkdtempSync(join(tmpdir(), "foundry-completion-runtime-"));
  try {
    // Use a real process so stdout/capsys tricks cannot fake the CLI contract.
    const py = String.raw`
import io, json, sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from foundry.cli import main
from foundry.task import TaskStore
root = Path(${JSON.stringify(root)})
task = TaskStore(root).create(title="runtime smoke")
task.record_session("runtime-one", role="analysis")
args = ["--var", str(root), "--session", "runtime-one"]
def call(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(argv)
    if code != 0:
        raise SystemExit(f"command failed {code}: {argv}")
    return json.loads(out.getvalue())
operation = call([*args, "finance-completion-begin", "--spec", json.dumps({"request_key":"session-a:message:u1:seq:1", "policy":{"max_repairs":0, "timeout_seconds":300}})])
assert operation["policy"]["max_repairs"] == 0
assert operation["policy"]["timeout_seconds"] == 300
draft = call([*args, "save-explanation-draft", "--completion-operation", operation["id"], "--completion-call-id", "actual-runtime-call", "--spec", json.dumps({"title":"待核对", "body":"本次判断仍需资料支持。"})])
assert draft["completion_operation"]["revisions"][0]["call_id"] == "actual-runtime-call"
status = call([*args, "finance-completion-status", "--spec", json.dumps({"operation_id": operation["id"]})])
assert status["session_id"] == "runtime-one"
print(json.dumps({"operation": operation["id"], "status": status["status"], "draft": draft["id"]}, ensure_ascii=False))
`;
    const repoRoot = repoRootUrl();
    const python = existsSync(new URL(".venv/bin/python", repoRoot)) ? new URL(".venv/bin/python", repoRoot).pathname : "python3";
    const output = execFileSync(python, ["-c", py], { cwd: repoRoot, encoding: "utf8", env: { ...process.env, PYTHONPATH: repoRoot.pathname } });
    const receipt = JSON.parse(output.trim().split("\n").at(-1));
    assert.match(receipt.operation, /^[0-9a-f]+$/);
    assert.ok(["needs_review", "awaiting_input", "complete", "repair_available"].includes(receipt.status));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

await testNonSavePassThrough();
await testRejectsAuthorityFromTopAndSpec();
await testRequestKeyUsesRealDshUserMessageShape();
await testPolicyComesOnlyFromThirdArgAndTrustedEnv();
await testRequiresTrustedCallIdAndDeadline();
await testResultObserverUsesRealSignatureAndExactExecIdentity();
await testCompleteAndRepairAvailableDoNotCancelAfterResult();
await testNewUserOnNonSaveStopsSupersededOldOperation();
await testBeginTerminalCompleteDoesNotArmTimerOrCancel();
await testExternalSignalListenerIsRemoved();
await testNewUserBeforeResultPreventsCancelAndSupersedesOldOperation();
await testDeadlineTimerStopsWithTimeoutAndCancelsSameUser();
await testExternalCancelStopsCancelled();
testBackendCliSmoke();
console.log("completion-runtime tests passed");
