import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REFUSED, apply, definitions, f3Denied, inject, registerTools } from "./index.js";

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
]);
assert.deepEqual(calls[6], ["--var", process.env.FOUNDRY_VAR, "stop-formulator"]);
assert.deepEqual(calls[7], ["--var", process.env.FOUNDRY_VAR, "re-import", "--named", "named.json"]);
assert.equal(calls.length, 8);

// `execute` resolves the canonical value the output schema declares. It is no
// longer a JSON string: the registry validates the value and `output.render`
// turns it into the model-facing block.
assert.deepEqual(await call("lock"), { tool: "lock", stdout: "ok stdout" });
assert.deepEqual(await call("emit-brief"), { tool: "emit-brief", stdout: "ok stdout" });

// -- binding --------------------------------------------------------------
//
// The task rides the environment the host set when it opened the session. The
// session cannot: one dsh process hosts many conversations, so it is read per
// call off the agent the loop attached to this execution. Both are top-level
// flags and must land in front of the subcommand, or argparse rejects them.
{
  const mark = readFileSync(log, "utf8").trim().split("\n").length;
  process.env.FOUNDRY_TASK = "task-abc";
  await call("emit-brief", {}, { agent: { id: "sess-42" } });
  const line = JSON.parse(readFileSync(log, "utf8").trim().split("\n")[mark]);
  assert.deepEqual(line, [
    "--var",
    process.env.FOUNDRY_VAR,
    "--task",
    "task-abc",
    "--session",
    "sess-42",
    "emit-brief",
  ]);
}

{
  // No agent behind the call: no session recorded, and the call still runs.
  const mark = readFileSync(log, "utf8").trim().split("\n").length;
  await call("emit-brief", {}, {});
  const line = JSON.parse(readFileSync(log, "utf8").trim().split("\n")[mark]);
  assert.deepEqual(line, ["--var", process.env.FOUNDRY_VAR, "--task", "task-abc", "emit-brief"]);
}

{
  // No task in the environment either: the CLI falls through to the addressed
  // window's own back-pointer, so the bundle passes neither flag.
  const mark = readFileSync(log, "utf8").trim().split("\n").length;
  delete process.env.FOUNDRY_TASK;
  await call("emit-brief", {}, { agent: { id: "sess-9" } });
  const line = JSON.parse(readFileSync(log, "utf8").trim().split("\n")[mark]);
  assert.deepEqual(line, ["--var", process.env.FOUNDRY_VAR, "--session", "sess-9", "emit-brief"]);
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
