import { spawnSync } from "node:child_process";

const REQUIRED = [
  "import",
  "lock",
  "record-questions",
  "emit-brief",
  "launch-formulator",
  "query-locked",
  "re-import",
];

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

export const name = "finance-skill-foundry";

export function registerTools(available = REQUIRED) {
  const missing = REQUIRED.filter((toolName) => !available.includes(toolName));
  if (missing.length) {
    throw new Error(`foundry plugin startup failed; missing tools: ${missing.join(",")}`);
  }
  return REQUIRED.map((toolName) => ({
    name: toolName,
    run: (input) => {
      if (toolName === "import") {
        return foundry([
          "import",
          "--coa",
          input.coa,
          "--units",
          input.units,
          "--named",
          input.named,
          "--drop-dir",
          input.dropDir ?? "",
        ]);
      }
      if (toolName === "lock") return foundry(["lock"]);
      if (toolName === "record-questions") return foundry(["record-questions", "--questions", input.questions]);
      if (toolName === "emit-brief") return foundry(["emit-brief"]);
      if (toolName === "launch-formulator") return foundry(["launch-formulator"]);
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
        ]);
      }
      if (toolName === "re-import") {
        return foundry([
          "re-import",
          "--coa",
          input.coa,
          "--units",
          input.units,
          "--named",
          input.named,
          "--drop-dir",
          input.dropDir ?? "",
        ]);
      }
      throw new Error(`unknown tool ${toolName}`);
    },
  }));
}

export function f3Allowlist() {
  return ["query-locked"];
}

export function f3Denied(name) {
  return name !== "query-locked";
}

export function apply() {
  return registerTools();
}
