import { spawnSync } from "node:child_process";

type ToolName =
  | "import"
  | "lock"
  | "record-questions"
  | "emit-brief"
  | "launch-formulator"
  | "query-locked"
  | "re-import";

const REQUIRED: ToolName[] = [
  "import",
  "lock",
  "record-questions",
  "emit-brief",
  "launch-formulator",
  "query-locked",
  "re-import",
];

function foundry(args: string[]): string {
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

export function defineTool(name: ToolName, run: (input: Record<string, string>) => string) {
  return { name, run };
}

export function registerTools(available: ToolName[] = REQUIRED) {
  const missing = REQUIRED.filter((name) => !available.includes(name));
  if (missing.length) {
    throw new Error(`foundry plugin startup failed; missing tools: ${missing.join(",")}`);
  }
  return REQUIRED.map((name) =>
    defineTool(name, (input) => {
      if (name === "import") {
        const args = ["import", "--coa", input.coa, "--named", input.named, "--drop-dir", input.dropDir ?? ""];
        if (input.units) args.push("--units", input.units);
        if (input.aux) args.push("--aux", input.aux);
        if (input.map) args.push("--map", input.map);
        return foundry(args);
      }
      if (name === "lock") return foundry(["lock"]);
      if (name === "record-questions") return foundry(["record-questions", "--questions", input.questions]);
      if (name === "emit-brief") return foundry(["emit-brief"]);
      if (name === "launch-formulator") return foundry(["launch-formulator"]);
      if (name === "query-locked") {
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
      if (name === "re-import") {
        const args = ["re-import", "--coa", input.coa, "--named", input.named, "--drop-dir", input.dropDir ?? ""];
        if (input.units) args.push("--units", input.units);
        if (input.aux) args.push("--aux", input.aux);
        if (input.map) args.push("--map", input.map);
        return foundry(args);
      }
      throw new Error(`unknown tool ${name}`);
    }),
  );
}

export function f3Allowlist(): ToolName[] {
  return ["query-locked"];
}

export function f3Denied(name: string): boolean {
  return name !== "query-locked";
}

export function apply() {
  return registerTools();
}
