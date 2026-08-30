import { spawnSync } from "node:child_process";

type ToolName =
  | "import"
  | "lock"
  | "record-questions"
  | "emit-brief"
  | "launch-formulator"
  | "stop-formulator"
  | "query-locked"
  | "re-import";

const REQUIRED: ToolName[] = [
  "import",
  "lock",
  "record-questions",
  "emit-brief",
  "launch-formulator",
  "stop-formulator",
  "query-locked",
  "re-import",
];

export const HOST_WRITERS = ["bash", "dsh-tool-fs", "str-replace-editor"] as const;
export const LINE_LEAKS = ["read_document"] as const;

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

function importArgs(cmd: "import" | "re-import", input: Record<string, string>): string[] {
  const args = [cmd];
  if (input.dropDir) args.push("--drop-dir", input.dropDir);
  if (input.coa) args.push("--coa", input.coa);
  if (input.named) args.push("--named", input.named);
  if (input.units) args.push("--units", input.units);
  if (input.aux) args.push("--aux", input.aux);
  if (input.map) args.push("--map", input.map);
  return args;
}

export function defineTool(name: ToolName, run: (input: Record<string, string>) => string) {
  return { name, run };
}

export function periodDenied(name: string): boolean {
  return (HOST_WRITERS as readonly string[]).includes(name) || (LINE_LEAKS as readonly string[]).includes(name);
}

export function toolsForProfile(profile?: string): ToolName[] {
  if (profile === "f3") return f3Allowlist();
  return REQUIRED;
}

export function registerTools(available: ToolName[] = REQUIRED, options: { profile?: string; phase?: string } = {}) {
  const missing = REQUIRED.filter((name) => !available.includes(name));
  if (missing.length) {
    throw new Error(`foundry plugin startup failed; missing tools: ${missing.join(",")}`);
  }
  const leaks = available.filter((name) => periodDenied(name));
  if (leaks.length) {
    throw new Error(`period profile must omit ${leaks.join(",")}`);
  }
  const enabled = toolsForProfile(options.profile ?? options.phase);
  return enabled.map((name) =>
    defineTool(name, (input) => {
      if (name === "import") return foundry(importArgs("import", input));
      if (name === "lock") return foundry(["lock"]);
      if (name === "record-questions") return foundry(["record-questions", "--questions", input.questions]);
      if (name === "emit-brief") return foundry(["emit-brief"]);
      if (name === "launch-formulator") return foundry(["launch-formulator"]);
      if (name === "stop-formulator") return foundry(["stop-formulator"]);
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
          "--question-id",
          input.questionId ?? "",
        ]);
      }
      if (name === "re-import") return foundry(importArgs("re-import", input));
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

export function apply(context: { profile?: string; phase?: string } = {}) {
  return registerTools(REQUIRED, { profile: context.profile ?? context.phase });
}
