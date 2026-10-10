import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REFUSED, apply, definitions, f3Denied, inject, invokeFoundry, readPresented, readReceipt, registerTools, toolDefinition } from "./index.js";

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

// -- cards under the answer -----------------------------------------------
//
// `answer_cards` prints its cards beside one line per card; the model reads
// the line and the row draws the cards. `dashboard_propose` keeps printing the
// board for the model, and the card it proposed is drawn for the conversation.
{
  const drawn = { task_id: "t1", cards: [{ kind: "figure", title: "当期收缴率" }], follow_ups: ["按城市公司拆开"] };
  assert.deepEqual(readPresented("answer_cards", JSON.stringify({ ...drawn, text: "回答下方已画出 1 张卡" })),
    { stdout: "回答下方已画出 1 张卡", presented: drawn });
  const board = { id: "b1", cards: [] };
  assert.deepEqual(readPresented("dashboard_propose", JSON.stringify({ ...board, presented: { task_id: "t1", proposed: null } })),
    { stdout: JSON.stringify(board), presented: { task_id: "t1", proposed: null } });
  // An older `foundry`, or any shape that is not this one, passes through as it came, with nothing to draw.
  for (const raw of ["not json", "[]", "null", JSON.stringify({ text: 1, cards: [] }), JSON.stringify({ text: "x" })]) {
    assert.deepEqual(readPresented("answer_cards", raw), { stdout: raw });
  }
  assert.deepEqual(readPresented("dashboard_propose", JSON.stringify(board)), { stdout: JSON.stringify(board) });
  assert.deepEqual(readPresented("dashboard_propose", JSON.stringify({ ...board, presented: [] })),
    { stdout: JSON.stringify({ ...board, presented: [] }) });
  const other = JSON.stringify({ text: "x", cards: [] });
  assert.deepEqual(readPresented("run_metric", other), { stdout: other }, "only the drawing verbs are reshaped");

  const tool = toolDefinition("answer_cards", {
    description: "x", parameters: { type: "object", required: [], properties: {} },
    execute: async () => JSON.stringify({ ...drawn, text: "一行" }),
  });
  const value = await tool.execute({}, {});
  assert.deepEqual(value, { tool: "answer_cards", stdout: "一行", filed: [], presented: drawn });
  assert.deepEqual(tool.output.render({}, value), [{ type: "text", text: "一行" }], "the model reads the line, not the cards");
  assert.deepEqual(tool.output.presentationMeta({}, value), { filed: [], presented: drawn });
  for (const presented of [null, [], "x", 3]) {
    assert.deepEqual(tool.output.presentationMeta({}, { ...value, presented }), { filed: [] });
  }
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
  const inputSources = [];
  const jsxRuntime = {
    jsx: (type, props, key) => ({ type, props, key }),
    jsxs: (type, props, key) => ({ type, props, key }),
    Fragment: Symbol.for("Fragment"),
  };
  let clientExports = null;
  const loader = {
    load: (bundle) => {
      const factory = bundle.factory((id) => {
        if (id === "react/jsx-runtime") return jsxRuntime;
        throw new Error(`unexpected require(${id})`);
      });
      clientExports = factory;
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
        inputTriggers: { registerSource: (source) => { inputSources.push(source); return source; } },
        get: (name) => {
          if (name === "inputTriggers") return { registerSource: (source) => { inputSources.push(source); return source; } };
          throw new Error(`unexpected ctx.get(${name})`);
        },
        effect: (run) => run(),
        layout: { toggleSidebar: () => {} },
      });
    },
  };

  const priorWindow = globalThis.window;
  const priorDocument = globalThis.document;
  const page = { __ModuleLoader__: loader };
  globalThis.window = page;
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
  assert.ok(inputSources.some((source) => source.name === "foundry-draft"),
    "the draft reference input source was never registered");

  // The 「/」 menu's finance shortcuts: above upstream's skill list, in the
  // manager's words, each one a question for a real bundled skill.
  const shortcuts = inputSources.find((source) => source.name === "foundry-finance");
  assert.ok(shortcuts, "the finance shortcut source was never registered");
  assert.equal(shortcuts.trigger, "/");
  assert.ok(shortcuts.order < 2, "finance shortcuts must list above upstream's skill source (order 2)");
  const SKILL_IDS = new Set(readdirSync(new URL("../method/", import.meta.url), { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(new URL(`../method/${entry.name}/SKILL.md`, import.meta.url)))
    .map((entry) => entry.name));
  const rows = clientExports.FINANCE_SHORTCUTS;
  assert.deepEqual([...new Set(rows.map((row) => row.section))],
    ["开始与资料体检", "月结与管理报表", "预算与差异分析", "对账", "凭证草稿", "回款与现金", "看板"]);
  assert.equal(new Set(rows.map((row) => row.id)).size, rows.length, "shortcut ids must be unique");
  for (const row of rows) {
    assert.ok(SKILL_IDS.has(row.skill), `${row.id} names ${row.skill}, which is not a bundled skill`);
    for (const text of [row.label, row.prompt, ...row.keywords]) {
      assert.ok(!/[A-Za-z]{3,}/.test(text), `${row.id} shows an English word to the manager: ${text}`);
    }
  }
  for (const skill of SKILL_IDS) {
    assert.ok(rows.some((row) => row.skill === skill), `no shortcut reaches the bundled ${skill} skill`);
  }
  const signal = new AbortController().signal;
  const all = await shortcuts.candidates({ sessionId: "s" }, { query: "", position: "leading", signal });
  assert.equal(all.length, rows.length);
  assert.ok(all.every((candidate) => candidate.section && candidate.value && candidate.description));
  const collection = await shortcuts.candidates({ sessionId: "s" }, { query: "收缴率", position: "leading", signal });
  assert.deepEqual(collection.map((candidate) => candidate.value), ["collection-health"]);
  const closing = await shortcuts.candidates({ sessionId: "s" }, { query: "关账", position: "leading", signal });
  assert.deepEqual(closing.map((candidate) => candidate.value), ["close-walk"]);
  assert.deepEqual(await shortcuts.candidates({ sessionId: "s" }, { query: "不存在", position: "leading", signal }), []);
  // A pick only writes the question into the composer; it never claims or sends.
  const picked = shortcuts.onPick({ candidate: collection[0], session: { sessionId: "s" }, position: "leading", via: "menu", span: { start: 0, end: 4, draftRev: 1 } });
  assert.deepEqual(picked, { text: rows.find((row) => row.id === "collection-health").prompt });
  assert.equal(shortcuts.onPick({ candidate: { name: "x", value: "missing" } }), undefined);
  const registeredKeys = new Set(registered.keys());
  for (const key of ["emit-brief", "query-locked", "record-reference"]) {
    assert.ok(registeredKeys.has(key), `${key} receipt row was not registered`);
  }
  for (const key of ["workbook-range-preview", "run-metric", "validate-explanation", "save-explanation-draft"]) {
    assert.ok(registeredKeys.has(key), `${key} finance stage row was not registered`);
  }
  for (const key of ["analysis-script", "save_explanation_draft", "run_metric", "workbook_read", "validate_explanation"]) {
    assert.ok(registeredKeys.has(key), `${key} runtime finance stage row was not registered`);
  }
  assert.ok(!registeredKeys.has("unknown_finance_like_tool"), "unknown tools must not be claimed as finance stages");

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

  const StageRow = registered.get("save_explanation_draft");
  const stageTree = StageRow({
    callId: "save-1",
    toolName: "save_explanation_draft",
    block: {
      kind: "tool-result",
      isError: false,
      argsRaw: JSON.stringify({ spec: { body: "很长".repeat(1000) } }),
      content: [{ type: "text", text: JSON.stringify({ saved: true, draft_id: "draft-1", body: "结果".repeat(1000) }) }],
    },
  });
  assert.match(flatten(stageTree.props.children[0]), /保存结果 · 已完成/);
  assert.ok(flatten(stageTree.props.children[0]).length < 80, "stage summary must stay bounded");
  assert.ok(flatten(stageTree).includes('"body"'), "raw input/output remains available in details");

  const scriptTree = registered.get("analysis-script")({
    callId: "script-1",
    toolName: "analysis-script",
    block: { kind: "tool-result", isError: false, content: [{ type: "text", text: "ok" }] },
  });
  assert.match(flatten(scriptTree.props.children[0]), /计算指标 · 已完成/);

  // -- cards under the answer ---------------------------------------------
  //
  // The figures arrive written; the row lays them out, never re-reads or
  // re-formats them, and every shape short of a drawing falls back to the
  // stage row rather than throwing.
  const find = (node, test, found = []) => {
    if (node === null || node === undefined || node === false || typeof node !== "object") return found;
    if (Array.isArray(node)) { for (const child of node) find(child, test, found); return found; }
    if (typeof node.type === "function") return find(node.type(node.props ?? {}), test, found);
    if (test(node)) found.push(node);
    return find(node.props?.children, test, found);
  };
  const CardsRow = registered.get("answer_cards");
  assert.ok(CardsRow && registered.get("answer-cards") === CardsRow, "the answer card row was not registered");
  const ProposedRow = registered.get("dashboard_propose");
  assert.ok(ProposedRow && ProposedRow !== StageRow, "a proposed card is drawn, not listed as a stage");
  const runId = "r".repeat(32);
  const source = { kind: "analysis", run_id: runId, analysis_id: "a1", at: "2026-10-10T05:33:00+00:00", computed: "计算成功 · 财务引擎",
    lines: [["公式", "1 − 毛利率 + 期间费用率"]], files: [{ name: "kpi", digest: "abcdef123456" }] };
  const pinned = { kind: "figure", title: "集团距生死线", run_id: runId, select: { match: { entity: "集团" }, column: "value" } };
  const presented = {
    task_id: "task-1",
    cards: [
      { kind: "figure", title: "集团距生死线", subject: "集团", part: "本期", value: { text: "(3.10) 个百分点", negative: true },
        beside: [["上年同期", "1.20 个百分点"]], level: "red", level_label: "低于生死线", source, pin: pinned },
      { kind: "rank", title: "各城市距生死线", items: [{ label: "三亚", value: -3.1, text: "-3.10", note: null }, { label: "海口", value: 2, text: "2.00", note: "高于生死线" }],
        unit: "个百分点", reference: { value: 0, label: "生死线" }, source, pin: null },
      { kind: "bridge", title: "利润桥", steps: [{ label: "预算利润", kind: "total", value: 25, text: "25" }, { label: "收入", kind: "delta", value: 20, text: "20" },
        { label: "成本", kind: "delta", value: -15, text: "-15" }, { label: "实际利润", kind: "total", value: 30, text: "30" }], unit: "万元", source, pin: null },
    ],
    follow_ups: ["按城市公司拆开"],
  };
  const settledCards = (meta, extra = {}) => ({ callId: "cards-1", toolName: "answer_cards",
    block: { kind: "tool-result", isError: false, content: [{ type: "text", text: "回答下方已画出 3 张卡" }], ...(meta === undefined ? {} : { meta }), ...extra } });
  const drawnCards = flatten(CardsRow(settledCards({ filed: [], presented })));
  for (const text of ["集团距生死线", "(3.10) 个百分点", "低于生死线", "上年同期", "1.20 个百分点", "三亚", "虚线：生死线", "预算利润", "实际利润",
    "单位：万元", "看来源", "1 − 毛利率 + 期间费用率", "摘要 abcdef123456", "计算编号 " + runId, "钉到看板", "打开结果", "接着问", "按城市公司拆开"]) {
    assert.ok(drawnCards.includes(text), `the cards do not show ${text}`);
  }
  assert.ok(!drawnCards.includes("回答下方已画出"), "the line the model reads is not drawn on the cards");
  assert.equal(find(CardsRow(settledCards({ filed: [], presented })), (node) => node.type === "button" && flatten(node.props.children) === "钉到看板").length, 1,
    "only a card that names what it would pin offers 钉到看板");

  const more = { task_id: "task-1", cards: [
    { kind: "compare", title: "海口和三亚", items: [
      { subject: "海口", part: "本期", value: { text: "2.00 个百分点", negative: false }, beside: [], source },
      { subject: "三亚", part: "本期", value: { text: "(3.10) 个百分点", negative: true }, beside: [], source: { ...source, kind: "collection", trial: true } }], pin: null },
    { kind: "trend", title: "收入走势", subject: "revenue", part: "实际", unit: "万元", points: [
      { label: "2026 年 1 月", value: 100, text: "100.00" }, { label: "2026 年 2 月", value: -20.125, text: "-20.13" }, { label: "2026 年 3 月", value: 310.5, text: "310.50" }], source, pin: null },
  ] };
  const drawnMore = flatten(CardsRow(settledCards({ filed: [], presented: more })));
  for (const text of ["海口", "三亚", "(3.10) 个百分点", "2026 年 1 月", "100.00", "2026 年 3 月", "310.50", "逐期 3 个数", "-20.13"]) {
    assert.ok(drawnMore.includes(text), `the compare and trend cards do not show ${text}`);
  }
  assert.ok(!flatten(CardsRow(settledCards({ filed: [], presented: { task_id: "task-1", cards: [more.cards[0]] } }))).includes("打开结果"),
    "a compare card shows each figure's source, and opens no one result");
  assert.match(flatten(CardsRow(settledCards({ filed: [], presented: { task_id: "task-1", cards: [{ ...presented.cards[0], source: { ...source, kind: "collection", trial: true } }] } }))),
    /试算.*打开收缴率结果/, "a trial collection figure says so");

  // While the assistant is still writing the call: the titles it has written so far, and nothing else.
  assert.match(flatten(CardsRow({ callId: "c", toolName: "answer_cards", block: { argsRaw: '{"spec":{"cards":[{"kind":"figure","title":"当期收' } })), /正在从计算结果取数/);
  const streaming = flatten(CardsRow({ callId: "c", toolName: "answer_cards", block: { argsRaw: '{"spec":{"cards":[{"kind":"figure","title":"当期收缴率"},{"title":"清' } }));
  assert.match(streaming, /当期收缴率/);
  assert.ok(!streaming.includes("清"), "a title cut mid-way waits for the rest");

  for (const props of [{}, { block: null }, settledCards(undefined), settledCards({ presented: null }), settledCards({ presented: [] }),
    settledCards({ presented: { cards: "x" } }),
    settledCards({ presented: { task_id: "t", cards: [null, 3, { kind: "chart" }, { kind: "rank", items: "no" }, { kind: "rank", items: [{ value: "x" }] },
      { kind: "trend", points: [{ value: 1 }] }, { kind: "bridge", steps: [{}] }, { kind: "compare", items: [null] }, { kind: "figure", value: null, beside: [[1]] }] } }),
    settledCards({ filed: [], presented }, { isError: true, error: { code: "refused" } })]) {
    assert.equal(typeof flatten(CardsRow(props)), "string");
  }
  assert.match(flatten(CardsRow(settledCards({ filed: [], presented }, { isError: true, error: { code: "refused", message: "card 1: exactly one row" } }))),
    /画卡片 · 需要处理/, "a refused call reads as one, not as cards");
  assert.match(flatten(CardsRow(settledCards({ filed: [] }))), /画卡片 · 已完成/, "an older foundry with no drawing shows its text");

  // The two clicks that leave the page go to the window only with its nonce; 接着问 only fills the composer.
  {
    const lines = [];
    const info = console.info;
    console.info = (line) => lines.push(line);
    try {
      const tree = CardsRow(settledCards({ filed: [], presented }));
      const button = (label) => find(tree, (node) => node.type === "button" && flatten(node.props.children) === label)[0];
      button("钉到看板").props.onClick();
      assert.equal(lines.length, 0, "without the window's nonce a click goes nowhere");
      page.__foundryCardNonce = "n".repeat(32);
      button("钉到看板").props.onClick();
      button("打开结果").props.onClick();
      const asked = [];
      page.__foundryEmbedded = { appendDraft: (text) => { asked.push(text); } };
      button("按城市公司拆开").props.onClick();
      await new Promise((resolve) => setTimeout(resolve, 0));
      assert.deepEqual(asked, ["按城市公司拆开"]);
    } finally {
      console.info = info;
      delete page.__foundryCardNonce;
      delete page.__foundryEmbedded;
    }
    const marker = "__foundry_card_action__";
    assert.ok(lines.every((line) => line.startsWith(marker)));
    const [pin, open] = lines.map((line) => JSON.parse(line.slice(marker.length)));
    assert.deepEqual(pin, { nonce: "n".repeat(32), action: "pin", task_id: "task-1", card: pinned });
    assert.deepEqual(open, { nonce: "n".repeat(32), action: "open", task_id: "task-1", kind: "analysis", run_id: runId, analysis_id: "a1" });
  }

  // A proposal is drawn as the card it would be, and says where it went; it offers no pin of its own.
  const proposal = (meta) => ({ callId: "p", toolName: "dashboard_propose",
    block: { kind: "tool-result", isError: false, content: [{ type: "text", text: "{}" }], ...(meta ? { meta } : {}) } });
  const drawnProposal = flatten(ProposedRow(proposal({ filed: [], presented: { task_id: "task-1", proposed: { ...presented.cards[0], pin: null } } })));
  assert.match(drawnProposal, /助手提议/);
  assert.match(drawnProposal, /点「钉住」才算/);
  assert.ok(!drawnProposal.includes("钉到看板"));
  assert.match(flatten(ProposedRow(proposal({ filed: [], presented: { task_id: "task-1", proposed: null } })).props.children[0]), /保存结果 · 已完成/);
  assert.match(flatten(ProposedRow(proposal()).props.children[0]), /保存结果 · 已完成/);
}
