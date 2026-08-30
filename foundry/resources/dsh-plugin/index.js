import { spawnSync } from "node:child_process";

const REQUIRED = [
  "import",
  "lock",
  "record-questions",
  "emit-brief",
  "launch-formulator",
  "stop-formulator",
  "query-locked",
  "re-import",
];

export const HOST_WRITERS = ["bash", "dsh-tool-fs", "str-replace-editor"];
export const LINE_LEAKS = ["read_document"];

function foundry(args) {
  const bin = process.env.FOUNDRY_BIN ?? "foundry";
  const varRoot = process.env.FOUNDRY_VAR;
  if (!varRoot) {
    throw new Error("FOUNDRY_VAR is required");
  }
  const result = spawnSync(bin, ["--var", varRoot, ...args], { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `foundry ${args[0]} failed`);
  }
  return result.stdout;
}

function importArgs(cmd, input) {
  const args = [cmd];
  if (input.dropDir) args.push("--drop-dir", input.dropDir);
  if (input.coa) args.push("--coa", input.coa);
  if (input.named) args.push("--named", input.named);
  if (input.units) args.push("--units", input.units);
  if (input.aux) args.push("--aux", input.aux);
  if (input.map) args.push("--map", input.map);
  return args;
}

export const name = "finance-skill-foundry";

export function periodDenied(toolName) {
  return HOST_WRITERS.includes(toolName) || LINE_LEAKS.includes(toolName);
}

export function toolsForProfile(profile) {
  if (profile === "f3") return f3Allowlist();
  return REQUIRED;
}

export function registerTools(available = REQUIRED, options = {}) {
  const missing = REQUIRED.filter((toolName) => !available.includes(toolName));
  if (missing.length) {
    throw new Error(`foundry plugin startup failed; missing tools: ${missing.join(",")}`);
  }
  const leaks = available.filter((toolName) => periodDenied(toolName));
  if (leaks.length) {
    throw new Error(`period profile must omit ${leaks.join(",")}`);
  }
  const enabled = toolsForProfile(options.profile ?? options.phase);
  return enabled.map((toolName) => ({
    name: toolName,
    run: (input) => {
      if (toolName === "import") return foundry(importArgs("import", input));
      if (toolName === "lock") return foundry(["lock"]);
      if (toolName === "record-questions") return foundry(["record-questions", "--questions", input.questions]);
      if (toolName === "emit-brief") return foundry(["emit-brief"]);
      if (toolName === "launch-formulator") return foundry(["launch-formulator"]);
      if (toolName === "stop-formulator") return foundry(["stop-formulator"]);
      if (toolName === "query-locked") {
        return foundry([
          "query-locked",
          "--text",
          input.text,
          "--tables",
          input.tables,
          "--split-by",
          input.splitBy ?? "",
          "--brief-window",
          input.briefWindow ?? "",
          "--question-id",
          input.questionId ?? "",
        ]);
      }
      if (toolName === "re-import") return foundry(importArgs("re-import", input));
      throw new Error(`unknown tool ${toolName}`);
    },
  }));
}

export function f3Allowlist() {
  return ["query-locked"];
}

export function f3Denied(toolName) {
  return toolName !== "query-locked";
}

export function apply(context = {}) {
  return registerTools(REQUIRED, { profile: context.profile ?? context.phase });
}
