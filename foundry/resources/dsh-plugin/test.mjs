import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REFUSED, apply, f3Denied, registerTools } from "./index.js";

const ROSTER = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).dsh.foundry.tools;

assert.deepEqual(
  apply({ profile: "f3" }).map((tool) => tool.name),
  ["query-locked"],
);
assert.equal(f3Denied("re-import"), true);
assert.equal(f3Denied("query-locked"), false);
assert.deepEqual(registerTools().map((tool) => tool.name), ROSTER);
assert.deepEqual(apply({}).map((tool) => tool.name), ROSTER);
assert.equal(apply({ phase: "f3" }).length, 1);

for (const tool of registerTools()) {
  assert.equal(typeof tool.description, "string", `${tool.name} needs a description`);
  assert.ok(tool.description.length > 0, `${tool.name} description is empty`);
  assert.equal(tool.parameters.type, "object", `${tool.name} needs an object schema`);
  assert.equal(typeof tool.parameters.properties, "object", `${tool.name} needs declared properties`);
  assert.ok(Array.isArray(tool.parameters.required), `${tool.name} needs a required list`);
  for (const key of tool.parameters.required) {
    assert.ok(key in tool.parameters.properties, `${tool.name} requires undeclared ${key}`);
  }
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
const named = '[{"id":"gl","path":"gl.xlsx"}]';
tools.create.run({});
tools.import.run({ dropDir: "drop", coa: "coa.xlsx", named, units: "units.xlsx", aux: "aux.xlsx", map: "map.xlsx" });
tools["record-questions"].run({ questions: "questions.json" });
tools.workpaper.run({});
tools.workpaper.run({ window: "abc123" });
tools["query-locked"].run({ text: "GL", tables: "gl", splitBy: "unit_id", briefWindow: "abc", questionId: "q1" });
tools["stop-formulator"].run({});
tools["re-import"].run({ named: "named.json" });

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
]);
assert.deepEqual(calls[6], ["--var", process.env.FOUNDRY_VAR, "stop-formulator"]);
assert.deepEqual(calls[7], ["--var", process.env.FOUNDRY_VAR, "re-import", "--named", "named.json"]);
assert.equal(calls.length, 8);

assert.deepEqual(JSON.parse(tools.lock.run({})), { ok: true, tool: "lock", stdout: "ok stdout" });
assert.deepEqual(JSON.parse(tools["emit-brief"].run({})), { ok: true, tool: "emit-brief", stdout: "ok stdout" });

// Host metadata rides under a reserved prefix: the arg check ignores those
// keys and the call still reaches the CLI instead of failing every tool call.
const beforeMeta = readFileSync(log, "utf8").trim().split("\n").length;
assert.doesNotThrow(() => tools.workpaper.run({ _callId: "abc", $trace: "x" }));
assert.equal(readFileSync(log, "utf8").trim().split("\n").length, beforeMeta + 1);

const before = readFileSync(log, "utf8").trim().split("\n").length;
assert.throws(() => tools["query-locked"].run({ tables: "gl" }), /缺少必填参数 text/);
assert.throws(() => tools["query-locked"].run({ text: "GL" }), /缺少必填参数 tables/);
assert.throws(() => tools["query-locked"].run({}), /缺少必填参数 text,tables/);
assert.throws(() => tools["record-questions"].run({}), /缺少必填参数 questions/);
assert.throws(() => tools["record-questions"].run(), /缺少必填参数 questions/);
assert.throws(() => tools["query-locked"].run({ text: "GL", tables: "gl", table: "gl" }), /未声明参数 table/);
assert.throws(() => tools.import.run({ drop_dir: "drop" }), /未声明参数 drop_dir/);
assert.equal(readFileSync(log, "utf8").trim().split("\n").length, before, "bad arguments must not reach the CLI");

// A non-refusal failure and a domain refusal must be separable by code, not
// by string-matching stderr: exit 9 is an error, exit 3 is 稿外/state refusal.
process.env.FOUNDRY_FAIL_COMMAND = "lock";
assert.throws(() => tools.lock.run({}), (error) => {
  assert.match(error.message, /boom stderr/);
  assert.equal(error.name, "FoundryError");
  assert.equal(error.refused, false);
  assert.equal(error.status, 9);
  return true;
});
delete process.env.FOUNDRY_FAIL_COMMAND;

process.env.FOUNDRY_FAIL_COMMAND = "emit-brief";
process.env.FOUNDRY_FAIL_STATUS = String(REFUSED);
assert.throws(() => tools["emit-brief"].run({}), (error) => {
  assert.equal(error.name, "FoundryRefusal");
  assert.equal(error.refused, true);
  assert.equal(error.status, REFUSED);
  return true;
});
delete process.env.FOUNDRY_FAIL_COMMAND;
delete process.env.FOUNDRY_FAIL_STATUS;

process.env.FOUNDRY_HANG_COMMAND = "emit-brief";
process.env.FOUNDRY_TIMEOUT_MS = "400";
assert.throws(() => tools["emit-brief"].run({}), /ETIMEDOUT/);
delete process.env.FOUNDRY_HANG_COMMAND;
delete process.env.FOUNDRY_TIMEOUT_MS;

process.env.FOUNDRY_BIN = join(tmp, "no-such-foundry");
assert.throws(() => tools.lock.run({}), /ENOENT/);
process.env.FOUNDRY_BIN = bin;

delete process.env.FOUNDRY_VAR;
assert.throws(() => tools.lock.run({}), /FOUNDRY_VAR is required/);
process.env.FOUNDRY_VAR = join(tmp, "var");

for (const [key, value] of Object.entries(oldEnv)) {
  if (value === undefined) delete process.env[key];
  else process.env[key] = value;
}
