import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { apply, f3Denied, registerTools } from "./index.js";

assert.deepEqual(
  apply({ profile: "f3" }).map((tool) => tool.name),
  ["query-locked"],
);
assert.equal(f3Denied("re-import"), true);
assert.equal(f3Denied("query-locked"), false);
assert.equal(registerTools().length, 8);
assert.equal(apply({ phase: "f3" }).length, 1);

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
    "  process.exit(9);",
    "}",
    "process.stdout.write('ok stdout');",
    "",
  ].join("\n"),
);
chmodSync(bin, 0o755);

const oldEnv = {
  FOUNDRY_BIN: process.env.FOUNDRY_BIN,
  FOUNDRY_VAR: process.env.FOUNDRY_VAR,
  FOUNDRY_LOG: process.env.FOUNDRY_LOG,
  FOUNDRY_FAIL_COMMAND: process.env.FOUNDRY_FAIL_COMMAND,
};
process.env.FOUNDRY_BIN = bin;
process.env.FOUNDRY_VAR = join(tmp, "var");
process.env.FOUNDRY_LOG = log;
delete process.env.FOUNDRY_FAIL_COMMAND;

const tools = Object.fromEntries(registerTools().map((tool) => [tool.name, tool]));
tools.import.run({ dropDir: "drop", coa: "coa.xlsx", named: "[{}]", units: "units.xlsx", aux: "aux.xlsx", map: "map.xlsx" });
tools["record-questions"].run({ questions: "questions.json" });
tools["query-locked"].run({ text: "GL", tables: "gl", splitBy: "unit_id", briefWindow: "abc", questionId: "q1" });
tools["stop-formulator"].run({});
tools["re-import"].run({ named: "named.json" });

const calls = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line));
assert.deepEqual(calls[0], [
  "--var",
  process.env.FOUNDRY_VAR,
  "import",
  "--drop-dir",
  "drop",
  "--coa",
  "coa.xlsx",
  "--named",
  "[{}]",
  "--units",
  "units.xlsx",
  "--aux",
  "aux.xlsx",
  "--map",
  "map.xlsx",
]);
assert.deepEqual(calls[1], ["--var", process.env.FOUNDRY_VAR, "record-questions", "--questions", "questions.json"]);
assert.deepEqual(calls[2], [
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
assert.deepEqual(calls[3], ["--var", process.env.FOUNDRY_VAR, "stop-formulator"]);
assert.deepEqual(calls[4], ["--var", process.env.FOUNDRY_VAR, "re-import", "--named", "named.json"]);

process.env.FOUNDRY_FAIL_COMMAND = "lock";
assert.throws(() => tools.lock.run({}), /boom stderr/);

const js = readFileSync(new URL("./index.js", import.meta.url), "utf8");
const ts = readFileSync(new URL("./src/index.ts", import.meta.url), "utf8");
for (const needle of ["stop-formulator", "--question-id", 'if (profile === "f3") return f3Allowlist()']) {
  assert.equal(js.includes(needle), true);
  assert.equal(ts.includes(needle), true);
}

for (const [key, value] of Object.entries(oldEnv)) {
  if (value === undefined) delete process.env[key];
  else process.env[key] = value;
}
