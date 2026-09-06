import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REFUSED, apply, definitions, f3Denied, inject, invokeFoundry, readReceipt, registerTools } from "./index.js";

const ROSTER = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).dsh.foundry.tools;

// The runtime's own registration contract. `inject` names the service the
// bundle needs mounted before `apply` runs, and `apply` registers on the context
// it is handed rather than returning a list -- Cordis discards a plugin's return
// value, so the previous shape put nothing in front of a model and said nothing.
assert.deepEqual(inject, ["tools"]);

function fakeCtx() {
  const registered = [];
  return { registered, tools: { register: (definition) => registered.push(definition) } };
}

const period = fakeCtx();
apply(period, {});
assert.deepEqual(period.registered.map((tool) => tool.name), ROSTER);

const f3 = fakeCtx();
apply(f3, { profile: "f3" });
assert.deepEqual(f3.registered.map((tool) => tool.name), ["query-locked"]);

assert.deepEqual(definitions("f3").map((tool) => tool.name), ["query-locked"]);
assert.equal(f3Denied("re-import"), true);
assert.equal(f3Denied("query-locked"), false);
assert.deepEqual(registerTools().map((tool) => tool.name), ROSTER);

for (const tool of registerTools()) {
  assert.equal(typeof tool.description, "string", `${tool.name} needs a description`);
  assert.ok(tool.description.length > 0, `${tool.name} description is empty`);
  assert.equal(tool.parameters.type, "object", `${tool.name} needs an object schema`);
  assert.equal(typeof tool.parameters.properties, "object", `${tool.name} needs declared properties`);
  assert.ok(Array.isArray(tool.parameters.required), `${tool.name} needs a required list`);
  for (const key of tool.parameters.required) {
    assert.ok(key in tool.parameters.properties, `${tool.name} requires undeclared ${key}`);
  }
  // `output` is mandatory on a ToolDefinition and the registry validates the
  // value `execute` resolves against it, so a tool without one registers and
  // then fails on its first call.
  assert.equal(typeof tool.output, "object", `${tool.name} needs an output declaration`);
  assert.equal(tool.output.schema.type, "object", `${tool.name} needs an output schema`);
  assert.deepEqual(
    tool.output.render({}, { tool: tool.name, stdout: "ok" }),
    [{ type: "text", text: "ok" }],
    `${tool.name} must render its stdout as one text block`,
  );
  assert.equal(typeof tool.execute, "function", `${tool.name} needs an execute`);
  const view = tool.presentCall({});
  assert.equal(view.card, "generic", `${tool.name} needs a generic call card`);
  // No `locations`: a presenter must be pure and replayable from args alone, and
  // no foundry tool's arguments name a file. See the note in index.js.
  assert.equal(view.locations, undefined, `${tool.name} must not guess a file path`);
}

const tmp = mkdtempSync(join(tmpdir(), "foundry-dsh-"));
const bin = join(tmp, "foundry-bin.mjs");
const log = join(tmp, "argv.log");
writeFileSync(
  bin,
  [
    "#!/usr/bin/env node",
    'import { appendFileSync } from "node:fs";',
    "const args = process.argv.slice(2);",
    "if (process.env.FOUNDRY_PID_LOG) appendFileSync(process.env.FOUNDRY_PID_LOG, String(process.pid) + '\\n');",
    "appendFileSync(process.env.FOUNDRY_LOG, JSON.stringify(args) + '\\n');",
    "if (process.env.FOUNDRY_FAIL_COMMAND && args.includes(process.env.FOUNDRY_FAIL_COMMAND)) {",
    "  console.error('boom stderr');",
    "  process.exit(Number(process.env.FOUNDRY_FAIL_STATUS ?? 9));",
    "}",
    "if (process.env.FOUNDRY_HANG_COMMAND && args.includes(process.env.FOUNDRY_HANG_COMMAND)) {",
    "  setTimeout(() => {}, 60000);",
    "} else {",
    "  process.stdout.write('ok stdout');",
    "}",
    "",
  ].join("\n"),
);
chmodSync(bin, 0o755);

const oldEnv = {
  FOUNDRY_BIN: process.env.FOUNDRY_BIN,
  FOUNDRY_VAR: process.env.FOUNDRY_VAR,
  FOUNDRY_LOG: process.env.FOUNDRY_LOG,
  FOUNDRY_PID_LOG: process.env.FOUNDRY_PID_LOG,
  FOUNDRY_FAIL_COMMAND: process.env.FOUNDRY_FAIL_COMMAND,
  FOUNDRY_FAIL_STATUS: process.env.FOUNDRY_FAIL_STATUS,
  FOUNDRY_HANG_COMMAND: process.env.FOUNDRY_HANG_COMMAND,
  FOUNDRY_TIMEOUT_MS: process.env.FOUNDRY_TIMEOUT_MS,
};
process.env.FOUNDRY_BIN = bin;
process.env.FOUNDRY_VAR = join(tmp, "var");
process.env.FOUNDRY_LOG = log;
delete process.env.FOUNDRY_FAIL_COMMAND;
delete process.env.FOUNDRY_FAIL_STATUS;
delete process.env.FOUNDRY_HANG_COMMAND;
delete process.env.FOUNDRY_TIMEOUT_MS;

const tools = Object.fromEntries(registerTools().map((tool) => [tool.name, tool]));

/** One call, with no agent behind it. The registry hands `execute` two arguments. */
const call = (toolName, input = {}, exec = {}) => tools[toolName].execute(input, exec);
const asyncCall = (args, exec = { agent: { id: "sess-direct" } }) => invokeFoundry(args, exec);
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(read, message, timeoutMs = 3000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const value = read();
    if (value) return value;
    await delay(25);
  }
  throw new Error(message);
}
function logLines(path) {
  try { return readFileSync(path, "utf8").trim().split("\n").filter(Boolean); }
  catch { return []; }
}
function processAlive(pid) {
  try { process.kill(pid, 0); return true; }
  catch { return false; }
}

const named = '[{"id":"gl","path":"gl.xlsx"}]';
await call("create");
await call("import", { dropDir: "drop", coa: "coa.xlsx", named, units: "units.xlsx", aux: "aux.xlsx", map: "map.xlsx" });
await call("record-questions", { questions: "questions.json" });
await call("workpaper");
await call("workpaper", { window: "abc123" });
await call("query-locked", { text: "GL", tables: "gl", splitBy: "unit_id", briefWindow: "abc", questionId: "q1" });
await call("stop-formulator");
await call("re-import", { named: "named.json" });

const calls = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line));
assert.deepEqual(calls[0], ["--var", process.env.FOUNDRY_VAR, "create"]);
assert.deepEqual(calls[1], [
  "--var",
  process.env.FOUNDRY_VAR,
  "import",
  "--drop-dir",
  "drop",
  "--coa",
  "coa.xlsx",
  "--named",
  named,
  "--units",
  "units.xlsx",
  "--aux",
  "aux.xlsx",
  "--map",
  "map.xlsx",
]);
assert.deepEqual(calls[2], ["--var", process.env.FOUNDRY_VAR, "record-questions", "--questions", "questions.json"]);
assert.deepEqual(calls[3], ["--var", process.env.FOUNDRY_VAR, "workpaper"]);
assert.deepEqual(calls[4], ["--var", process.env.FOUNDRY_VAR, "workpaper", "--window", "abc123"]);
assert.deepEqual(calls[5], [
  "--var",
  process.env.FOUNDRY_VAR,
  "query-locked",
  "--text",
  "GL",
  "--tables",
  "gl",
  "--split-by",
  "unit_id",
  "--brief-window",
  "abc",
  "--question-id",
  "q1",
  "--brief-sha",
  "",
  "--receipt",
]);
assert.deepEqual(calls[6], ["--var", process.env.FOUNDRY_VAR, "stop-formulator"]);
assert.deepEqual(calls[7], ["--var", process.env.FOUNDRY_VAR, "re-import", "--named", "named.json"]);
assert.equal(calls.length, 8);

// `execute` resolves the canonical value the output schema declares. It is no
// longer a JSON string: the registry validates the value and `output.render`
// turns it into the model-facing block.
assert.deepEqual(await call("lock"), { tool: "lock", stdout: "ok stdout", filed: [] });

// -- the receipt ----------------------------------------------------------
//
// The three verbs that file deliverable versions ask for `--receipt`, and the
// stub prints `ok stdout`, which is not an envelope. That is the degrade path
// and it is the one that matters most: by the time this runs the brief is
// written, the workpaper is rendered and the versions are filed, so a parse
// error must not turn a completed close into a failed tool call. An older
// `foundry` on the PATH is a far likelier cause than a broken document.
assert.deepEqual(await call("emit-brief"), { tool: "emit-brief", stdout: "ok stdout", filed: [] });
assert.deepEqual(
  readReceipt("emit-brief", "ok stdout"),
  { stdout: "ok stdout", filed: [] },
  "unparsable stdout keeps the text and drops the receipt",
);
assert.deepEqual(
  readReceipt("emit-brief", JSON.stringify({ text: "# 本期结论稿\n", filed: [{ seq: 1, appended: true }] })),
  { stdout: "# 本期结论稿\n", filed: [{ seq: 1, appended: true }] },
  "an envelope splits into what the model reads and what the card draws",
);
assert.deepEqual(
  readReceipt("emit-brief", JSON.stringify({ text: "x" })),
  { stdout: "x", filed: [] },
  "an envelope with no filed list is a receipt with nothing in it",
);
assert.deepEqual(
  readReceipt("emit-brief", JSON.stringify({ filed: [] })),
  { stdout: JSON.stringify({ filed: [] }), filed: [] },
  "an envelope with no text is not an envelope",
);
assert.deepEqual(
  readReceipt("lock", JSON.stringify({ text: "x", filed: [{ seq: 1 }] })),
  { stdout: JSON.stringify({ text: "x", filed: [{ seq: 1 }] }), filed: [] },
  "a verb that files nothing is never parsed, so its stdout is never reshaped",
);

// What the model reads is unchanged by any of this: `render` emits `stdout`
// and never `filed`.
for (const toolName of ["emit-brief", "query-locked", "record-reference"]) {
  const tool = tools[toolName];
  const blocks = tool.output.render({}, { tool: toolName, stdout: "文字", filed: [{ seq: 9 }] });
  assert.deepEqual(blocks, [{ type: "text", text: "文字" }], `${toolName} leaked its receipt to the model`);
}

// -- binding --------------------------------------------------------------
//
// Runtime calls resolve their task from a durable session. A process-wide
// FOUNDRY_TASK belongs only to direct operator calls and must not cross sessions.
{
  const mark = readFileSync(log, "utf8").trim().split("\n").length;
  process.env.FOUNDRY_TASK = "task-abc";
  await call("emit-brief", {}, { agent: { id: "sess-42" } });
  const line = JSON.parse(readFileSync(log, "utf8").trim().split("\n")[mark]);
  assert.deepEqual(line, [
    "--var",
    process.env.FOUNDRY_VAR,
    "--session",
    "sess-42",
    "emit-brief",
    "--receipt",
  ]);
}

{
  // No agent behind the call: no session recorded, and the call still runs.
  const mark = readFileSync(log, "utf8").trim().split("\n").length;
  await call("emit-brief", {}, {});
  const line = JSON.parse(readFileSync(log, "utf8").trim().split("\n")[mark]);
  assert.deepEqual(line, ["--var", process.env.FOUNDRY_VAR, "--task", "task-abc", "emit-brief", "--receipt"]);
}

{
  // No task in the environment either: the CLI falls through to the addressed
  // window's own back-pointer, so the bundle passes neither flag.
  const mark = readFileSync(log, "utf8").trim().split("\n").length;
  delete process.env.FOUNDRY_TASK;
  await call("emit-brief", {}, { agent: { id: "sess-9" } });
  const line = JSON.parse(readFileSync(log, "utf8").trim().split("\n")[mark]);
  assert.deepEqual(line, ["--var", process.env.FOUNDRY_VAR, "--session", "sess-9", "emit-brief", "--receipt"]);
}

// Host metadata rides under a reserved prefix: the arg check ignores those
// keys and the call still reaches the CLI instead of failing every tool call.
const beforeMeta = readFileSync(log, "utf8").trim().split("\n").length;
await assert.doesNotReject(() => call("workpaper", { _callId: "abc", $trace: "x" }));
assert.equal(readFileSync(log, "utf8").trim().split("\n").length, beforeMeta + 1);

const before = readFileSync(log, "utf8").trim().split("\n").length;
await assert.rejects(() => call("query-locked", { tables: "gl" }), /缺少必填参数 text/);
await assert.rejects(() => call("query-locked", { text: "GL" }), /缺少必填参数 tables/);
await assert.rejects(() => call("query-locked", {}), /缺少必填参数 text,tables/);
await assert.rejects(() => call("record-questions", {}), /缺少必填参数 questions/);
await assert.rejects(() => tools["record-questions"].execute(undefined, {}), /缺少必填参数 questions/);
await assert.rejects(() => call("query-locked", { text: "GL", tables: "gl", table: "gl" }), /未声明参数 table/);
await assert.rejects(() => call("import", { drop_dir: "drop" }), /未声明参数 drop_dir/);
assert.equal(readFileSync(log, "utf8").trim().split("\n").length, before, "bad arguments must not reach the CLI");

// A non-refusal failure and a domain refusal must be separable by code, not
// by string-matching stderr: exit 9 is an error, exit 3 is 稿外/state refusal.
process.env.FOUNDRY_FAIL_COMMAND = "lock";
await assert.rejects(() => call("lock"), (error) => {
  assert.match(error.message, /boom stderr/);
  assert.equal(error.name, "FoundryError");
  assert.equal(error.refused, false);
  assert.equal(error.status, 9);
  return true;
});
delete process.env.FOUNDRY_FAIL_COMMAND;

process.env.FOUNDRY_FAIL_COMMAND = "emit-brief";
process.env.FOUNDRY_FAIL_STATUS = String(REFUSED);
await assert.rejects(() => call("emit-brief"), (error) => {
  assert.equal(error.name, "FoundryRefusal");
  assert.equal(error.refused, true);
  assert.equal(error.status, REFUSED);
  return true;
});
delete process.env.FOUNDRY_FAIL_COMMAND;
delete process.env.FOUNDRY_FAIL_STATUS;

process.env.FOUNDRY_HANG_COMMAND = "emit-brief";
process.env.FOUNDRY_TIMEOUT_MS = "400";
await assert.rejects(() => call("emit-brief"), /ETIMEDOUT/);
delete process.env.FOUNDRY_HANG_COMMAND;
delete process.env.FOUNDRY_TIMEOUT_MS;

{
  const mark = logLines(log).length;
  assert.equal(await asyncCall(["emit-brief"]), "ok stdout");
  const line = JSON.parse(logLines(log).at(-1));
  assert.deepEqual(line, ["--var", process.env.FOUNDRY_VAR, "--session", "sess-direct", "emit-brief"]);
  assert.equal(logLines(log).length, mark + 1, "normal async calls still reach foundry once");
}

{
  const controller = new AbortController();
  controller.abort(new Error("already cancelled"));
  const mark = logLines(log).length;
  await assert.rejects(
    () => asyncCall(["emit-brief"], { agent: { id: "sess-preabort" }, signal: controller.signal }),
    (error) => {
      assert.equal(error.name, "FoundryCancelled");
      assert.equal(error.cancelled, true);
      assert.match(error.message, /already cancelled/);
      return true;
    },
  );
  assert.equal(logLines(log).length, mark, "pre-aborted async calls must not start foundry");
}

{
  const pidLog = join(tmp, "pid.log");
  process.env.FOUNDRY_PID_LOG = pidLog;
  process.env.FOUNDRY_HANG_COMMAND = "emit-brief";
  process.env.FOUNDRY_TIMEOUT_MS = "60000";
  const controller = new AbortController();
  const promise = asyncCall(["emit-brief"], { agent: { id: "sess-abort" }, signal: controller.signal });
  const pid = Number(await waitFor(() => {
    const value = Number(logLines(pidLog).at(-1));
    return value && processAlive(value) ? value : null;
  }, "hanging foundry process did not start and stay alive"));
  controller.abort(new Error("completion deadline exceeded"));
  await assert.rejects(
    () => promise,
    (error) => {
      assert.equal(error.name, "FoundryCancelled");
      assert.equal(error.cancelled, true);
      assert.equal(error.refused, false);
      assert.match(error.message, /completion deadline exceeded/);
      return true;
    },
  );
  await waitFor(() => !processAlive(pid), "aborted foundry process was not terminated");
  delete process.env.FOUNDRY_PID_LOG;
  delete process.env.FOUNDRY_HANG_COMMAND;
  delete process.env.FOUNDRY_TIMEOUT_MS;
}

process.env.FOUNDRY_BIN = join(tmp, "no-such-foundry");
await assert.rejects(() => call("lock"), /ENOENT/);
process.env.FOUNDRY_BIN = bin;

delete process.env.FOUNDRY_VAR;
await assert.rejects(() => call("lock"), /FOUNDRY_VAR is required/);
process.env.FOUNDRY_VAR = join(tmp, "var");

for (const [key, value] of Object.entries(oldEnv)) {
  if (value === undefined) delete process.env[key];
  else process.env[key] = value;
}

// -- the presentation projection ------------------------------------------
//
// The runtime calls this after `execute` resolved and turns a throw into
// `projectionError`, which fails the whole call. By then the documents are
// written and the versions are filed, so every shape a value could arrive in
// has to come back as a list rather than as an exception.
for (const toolName of ROSTER) {
  const project = tools[toolName].output.presentationMeta;
  assert.equal(typeof project, "function", `${toolName} needs a presentation projection`);
  assert.deepEqual(project({}, { tool: toolName, stdout: "x", filed: [{ seq: 1 }] }), {
    filed: [{ seq: 1 }],
  });
  for (const value of [undefined, null, {}, { filed: null }, { filed: "no" }, { filed: 7 }, "text", 0]) {
    assert.deepEqual(
      project({}, value),
      { filed: [] },
      `${toolName} projection threw or leaked on ${JSON.stringify(value) ?? "undefined"}`,
    );
  }
}

// The projection is the only path the receipt takes to the browser, and it
// carries nothing the model did not already have -- it is a view of the value
// `execute` returned, not a second read of the store.
{
  const value = { tool: "emit-brief", stdout: "# 本期结论稿\n", filed: [{ seq: 1, kind: "brief" }] };
  const meta = tools["emit-brief"].output.presentationMeta({}, value);
  assert.deepEqual(meta.filed, value.filed);
  assert.equal(Object.keys(meta).length, 1, "the projection carries only the receipt");
}

// -- the row itself, actually rendered ------------------------------------
//
// Everything above checks that the receipt reaches the browser. This checks
// what the browser does with it. `client.js` is a module-loader envelope that
// only runs inside the page, so it is executed here against stand-ins: a fake
// jsx runtime that returns plain objects, and a slot registry that captures
// what was registered instead of mounting it.
//
// The failure this exists for is a row that throws while drawing. Upstream
// catches nothing on our behalf, and a turn that renders an exception is worse
// than one with no strip at all.
{
  const clientSource = readFileSync(new URL("./client.js", import.meta.url), "utf8");
  const registered = new Map();
  const injected = [];
  const jsxRuntime = {
    jsx: (type, props, key) => ({ type, props, key }),
    jsxs: (type, props, key) => ({ type, props, key }),
    Fragment: Symbol.for("Fragment"),
  };
  const loader = {
    load: (bundle) => {
      const factory = bundle.factory((id) => {
        if (id === "react/jsx-runtime") return jsxRuntime;
        throw new Error(`unexpected require(${id})`);
      });
      factory.apply({
        slots: {
          inject: (name, run) => {
            injected.push(name);
            const produced = run();
            // A generator yields its registrations; a plain thunk returns.
            if (produced && typeof produced[Symbol.iterator] === "function") {
              for (const _ of produced) { /* drain */ }
            }
          },
          register: (descriptor, component) => {
            if (descriptor.key) registered.set(descriptor.key, component);
            return descriptor;
          },
        },
        layout: { toggleSidebar: () => {} },
      });
    },
  };

  const priorWindow = globalThis.window;
  const priorDocument = globalThis.document;
  globalThis.window = { __ModuleLoader__: loader };
  globalThis.document = { querySelector: () => null };
  try {
    new Function("window", "document", "globalThis", clientSource)(
      globalThis.window,
      globalThis.document,
      globalThis,
    );
  } finally {
    if (priorWindow === undefined) delete globalThis.window;
    else globalThis.window = priorWindow;
    if (priorDocument === undefined) delete globalThis.document;
    else globalThis.document = priorDocument;
  }

  assert.ok(injected.includes("tool.call.toolview"), "the tool view slot was never injected");
  assert.deepEqual(
    [...registered.keys()].sort(),
    ["emit-brief", "query-locked", "record-reference"],
    "the row is registered for exactly the verbs that file versions",
  );

  const Row = registered.get("emit-brief");
  const flatten = (node) => {
    if (node === null || node === undefined || node === false) return "";
    if (typeof node === "string" || typeof node === "number") return String(node);
    if (Array.isArray(node)) return node.map(flatten).join("");
    if (typeof node.type === "function") return flatten(node.type(node.props ?? {}));
    return flatten(node.props?.children);
  };

  const settled = (meta, extra = {}) => ({
    callId: "call-1",
    toolName: "emit-brief",
    block: {
      kind: "tool-result",
      isError: false,
      content: [{ type: "text", text: "# 本期结论稿" }],
      ...(meta === undefined ? {} : { meta }),
      ...extra,
    },
  });

  // The whole point: two archived versions, named where the call is.
  const withReceipt = flatten(
    Row(
      settled({
        filed: [
          { kind: "brief", appended: true, sha256: "c".repeat(64) },
          { kind: "workpaper", appended: false, sha256: "d".repeat(64) },
        ],
      }),
    ),
  );
  assert.match(withReceipt, /本期结论稿/);
  assert.match(withReceipt, /归档/);
  assert.match(withReceipt, /结论稿/);
  assert.match(withReceipt, /底稿 · 已在册/, "a version that was already on file must say so");
  assert.match(withReceipt, /cccccccccccc…/);

  // No task behind the window: say so rather than drawing nothing.
  assert.match(flatten(Row(settled({ filed: [] }))), /未登记/);

  // Every shape that is not a receipt draws the text and no strip, and none of
  // them may throw: a running call, a nested call the runtime never projected,
  // an older `foundry` whose stdout was not an envelope, a refusal.
  for (const props of [
    { callId: "c", toolName: "emit-brief", block: { argsRaw: "{}" } },
    settled(undefined),
    settled(null),
    settled({}),
    settled({ filed: "no" }),
    settled({ filed: null }),
    settled({ filed: [] }, { isError: true, error: { name: "FoundryRefusal", code: "refused" } }),
    { callId: "c", toolName: "emit-brief" },
    {},
  ]) {
    const drawn = flatten(Row(props));
    assert.equal(typeof drawn, "string");
    assert.ok(!drawn.includes("归档"), "a call with no receipt must not claim one");
  }

  // Taking the key takes the whole row, refusals included. A refusal is the
  // fence working, and it must not read as an answer just because this bundle
  // owns the row now.
  {
    const refused = flatten(
      Row(
        settled(undefined, {
          isError: true,
          error: { name: "FoundryRefusal", code: "refused" },
          content: [{ type: "text", text: "table not in this window: ['cash_flow']" }],
        }),
      ),
    );
    assert.match(refused, /拒绝/);
    assert.match(refused, /cash_flow/, "the refusal's own message has to survive");
    assert.ok(!refused.includes("归档"));
  }

  // A running call says it is working rather than showing an empty strip.
  assert.match(
    flatten(Row({ callId: "c", toolName: "emit-brief", block: { argsRaw: "{}" } })),
    /正在从锁库算/,
  );
}
