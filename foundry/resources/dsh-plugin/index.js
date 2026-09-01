import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const PACKAGE_URL = new URL("./package.json", import.meta.url);
const DEFAULT_TIMEOUT_MS = 120000;
const MAX_BUFFER = 32 * 1024 * 1024;
// foundry exits 3 for a domain refusal ("the window is not locked") and leaves 2
// to argparse for a usage error ("no such flag"). The first is a state the model
// reacts to by advancing the period loop; the second is a caller bug. Branch on
// the code so they are separable without string-matching stderr.
export const REFUSED = 3;

function readRoster() {
  const pkg = JSON.parse(readFileSync(PACKAGE_URL, "utf8"));
  const tools = pkg?.dsh?.foundry?.tools;
  if (!Array.isArray(tools) || tools.length === 0) {
    throw new Error("dsh.foundry.tools is missing from package.json");
  }
  return tools;
}

const REQUIRED = readRoster();

export const HOST_WRITERS = ["bash", "dsh-tool-fs", "str-replace-editor"];
export const LINE_LEAKS = ["read_document"];

/**
 * The conversation this call happened in.
 *
 * `exec.agent` is set by the agent loop and `exec.agent.id` is that agent's
 * session. It has to be read here, per call, and cannot come from the process
 * environment the way `FOUNDRY_VAR` does: one dsh process hosts many
 * conversations at once, so an ambient value would collapse every follow-up a
 * leader ever asked into a single id.
 *
 * A call with no agent behind it -- a direct registry dispatch, a probe -- is
 * not refused. It records no session, which is the truth about it.
 */
function sessionOf(exec) {
  const id = exec?.agent?.id;
  return id ? String(id) : null;
}

/**
 * Which task and which conversation this call writes to.
 *
 * Both are decided here rather than asked of the model. The task comes from the
 * environment the host set when it opened the session; the CLI falls through to
 * the addressed window's own back-pointer when it is absent, so an operator who
 * never set one still gets their window adopted.
 *
 * These are top-level flags, so they go in front of the subcommand: argparse
 * stops accepting parser-level optionals once a subparser has been chosen.
 */
function bindingArgs(exec) {
  const out = [];
  const task = String(process.env.FOUNDRY_TASK ?? "").trim();
  if (task) out.push("--task", task);
  const session = sessionOf(exec);
  if (session) out.push("--session", session);
  return out;
}

function foundry(args, exec) {
  const bin = process.env.FOUNDRY_BIN ?? "foundry";
  const varRoot = process.env.FOUNDRY_VAR;
  if (!varRoot) {
    throw new Error("FOUNDRY_VAR is required");
  }
  const result = spawnSync(bin, ["--var", varRoot, ...bindingArgs(exec), ...args], {
    encoding: "utf8",
    timeout: Number(process.env.FOUNDRY_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS),
    killSignal: "SIGKILL",
    maxBuffer: MAX_BUFFER,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const error = new Error(result.stderr || result.stdout || `foundry ${args[0]} failed`);
    error.name = result.status === REFUSED ? "FoundryRefusal" : "FoundryError";
    error.status = result.status;
    error.refused = result.status === REFUSED;
    throw error;
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

const IMPORT_PARAMETERS = {
  type: "object",
  properties: {
    dropDir: { type: "string", description: "落盘目录; foundry 按文件名 stem 认表, coa/aux/map/units 是保留名" },
    coa: { type: "string", description: "科目表路径 (xlsx/csv/json)" },
    named: {
      type: "string",
      description: "命名表描述: [{id,path}] 的 JSON, {id: path} 映射, 带 tables 键的信封, 或指向该 JSON 的文件路径; 省略则按 dropDir 的文件名认表",
    },
    units: { type: "string", description: "核算单元维表路径; aux 的快捷写法" },
    aux: { type: "string", description: "辅助核算维表路径" },
    map: { type: "string", description: "分析节点映射表路径" },
  },
  required: [],
};

const TOOL_SPECS = {
  create: {
    description: "新建期间窗口并置为 current。期间循环的第一步; 没有窗口时其余工具全部拒绝。已出稿的窗口不会被删, 但 current 会指向新窗口, 之后要读旧稿得用 query-locked 的 briefWindow 或 workpaper 的 window。stdout 是新窗口 id。",
    parameters: { type: "object", properties: {}, required: [] },
    argv: () => ["create"],
  },
  import: {
    description: "把本期账表导入当前窗口 (Open/Imported 可用)。给 dropDir 让 foundry 按文件名认表, 或用 named 逐张点名。",
    parameters: IMPORT_PARAMETERS,
    argv: (input) => importArgs("import", input),
  },
  lock: {
    description: "锁口径: 冻结已导入的表与哈希, 之后只读。锁后才能记录追问、出稿和重算。",
    parameters: { type: "object", properties: {}, required: [] },
    argv: () => ["lock"],
  },
  "record-questions": {
    description: "登记本期追问清单 (Locked 状态, 只能记一次)。每条要有 id / text / required_table_ids。",
    parameters: {
      type: "object",
      properties: {
        questions: {
          type: "string",
          description: "追问数组的 JSON [{id,text,required_table_ids}], 或指向该 JSON 的文件路径",
        },
      },
      required: ["questions"],
    },
    argv: (input) => ["record-questions", "--questions", input.questions],
  },
  "record-reference": {
    description:
      "登记一条外部引用 (锁后到追问期间都可以, 可多次追加)。用于行业基准、政策口径这类查到的材料: 它们能进稿帮读者判断, 但不出自本窗口的锁库。每条要有 id / text / source / at, 缺 source 或 at 会被拒。text 里不能出现 报表声称 / 我重算 / 两者一致 / 稿外追问 / not-in-this-window —— 那几个词是稿子自己的标记。出稿前登记的进结论稿的「外部引用」一节; 出稿后登记的落到底稿, 并记一版交付物。",
    parameters: {
      type: "object",
      properties: {
        references: {
          type: "string",
          description:
            "引用数组的 JSON [{id,text,source,at,note?}] (单条对象也可), 或指向该 JSON 的文件路径。at 是查到的日期。",
        },
      },
      required: ["references"],
    },
    argv: (input) => ["record-reference", "--references", input.references],
  },
  "emit-brief": {
    description: "出本期结论稿: 窗内问题给结论, 窗外问题标 稿外追问 并落到底稿排期。同时写出可勾选底稿。stdout 是稿件 markdown。",
    parameters: { type: "object", properties: {}, required: [] },
    argv: () => ["emit-brief"],
  },
  workpaper: {
    description: "读回底稿 (emit-brief / query-locked 写出)。省略 window 读当前窗口; 追问挂回旧窗口时给 window 读那一份。还没写出时拒绝并说明 workpaper not written。stdout 是底稿 markdown。",
    parameters: {
      type: "object",
      properties: {
        window: { type: "string", description: "窗口 id; 省略则读 current。补数据后旧稿的底稿要用它读" },
      },
      required: [],
    },
    argv: (input) => (input.window ? ["workpaper", "--window", input.window] : ["workpaper"]),
  },
  "launch-formulator": {
    description: "在本窗口起 Data Formulator, 只挂锁后的只读 catalog。stdout 是 JSON {argv, env, home, url}。",
    parameters: { type: "object", properties: {}, required: [] },
    argv: () => ["launch-formulator"],
  },
  "stop-formulator": {
    description: "停掉本窗口的 Data Formulator 并释放租约。stdout 是 JSON {stopped, window_id}。",
    parameters: { type: "object", properties: {}, required: [] },
    argv: () => ["stop-formulator"],
  },
  "query-locked": {
    description: "对锁后的表重算一问。窗外或未点名的表一律拒绝; 结果带 稿外追问 标记。stdout 是重算结论文本。",
    parameters: {
      type: "object",
      properties: {
        text: { type: "string", description: "要重算的问题原话" },
        tables: { type: "string", description: "本问依赖的表 id, 逗号分隔, 例如 gl,map; 必须是已点名的锁后表" },
        splitBy: { type: "string", description: "拆分维度: unit_id 或 analysis_node; 省略则不拆" },
        briefWindow: { type: "string", description: "结论稿窗口 id; 把重算挂回那一稿" },
        questionId: { type: "string", description: "追问清单里的 question id; 把重算挂回那一条" },
        briefSha: { type: "string", description: "领导手上那一版结论稿的 sha256; 把重算锚到他读的那一份" },
      },
      required: ["text", "tables"],
    },
    argv: (input) => [
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
      "--brief-sha",
      input.briefSha ?? "",
    ],
  },
  "re-import": {
    description: "补数据: 开一个继承本期口径的后继窗口并重导。stdout 是后继窗口 id。",
    parameters: IMPORT_PARAMETERS,
    argv: (input) => importArgs("re-import", input),
  },
};

export const name = "finance-skill-foundry";
export const inject = ["tools"];

function specFor(toolName) {
  const spec = TOOL_SPECS[toolName];
  if (!spec) {
    throw new Error(`unknown tool ${toolName}`);
  }
  return spec;
}

// Host metadata travels under a reserved prefix; a model's own arguments never
// do. Ignoring those keys keeps the typo guard (tables vs table) without a host
// that annotates a call breaking every foundry tool.
const METADATA_PREFIX = /^[_$]/;

function checkArgs(toolName, spec, input) {
  const declared = spec.parameters.properties;
  const missing = spec.parameters.required.filter((key) => String(input[key] ?? "").trim() === "");
  const undeclared = Object.keys(input).filter(
    (key) => !Object.hasOwn(declared, key) && !METADATA_PREFIX.test(key),
  );
  const problems = [];
  if (missing.length) problems.push(`缺少必填参数 ${missing.join(",")}`);
  if (undeclared.length) problems.push(`未声明参数 ${undeclared.join(",")}`);
  if (problems.length) {
    throw new Error(`foundry ${toolName} 参数错误: ${problems.join("; ")}; 可用参数 ${Object.keys(declared).join(",") || "(无)"}`);
  }
}

/**
 * What every foundry tool returns to the model.
 *
 * `output.schema` is mandatory on a `ToolDefinition` and the registry enforces
 * it against the value `execute` resolves, so the shape is declared once here
 * rather than restated per tool.
 */
const OUTPUT_SCHEMA = {
  type: "object",
  properties: {
    tool: { type: "string" },
    stdout: { type: "string" },
  },
  required: ["tool", "stdout"],
  additionalProperties: false,
};

/**
 * How a pending call is drawn before it runs.
 *
 * Deliberately without `locations`. The runtime's produced-files row reads
 * `locations` off this view, and it would be the natural place to make a brief
 * clickable in the chat -- but a presenter is required to be pure and replayable
 * from `args` alone, and no foundry tool's arguments name a file. The path is
 * `<FOUNDRY_VAR>/windows/<id>/brief.md`, and neither half is in `args`: the var
 * root is ambient, and the window is `var/current`, which moves on every
 * re-import. Reading either here would draw a card that resolves to a different
 * file every time an old session is replayed.
 *
 * So the card says what the call does and stops there. Which documents a period
 * produced, and in what order, is a question the task store answers durably --
 * `foundry --task T deliverables` -- rather than one this row guesses at.
 */
function presentCall(toolName, kind) {
  return () => ({ card: "generic", kind, title: `foundry ${toolName}` });
}

const CALL_KINDS = {
  create: "edit",
  import: "edit",
  lock: "edit",
  "record-questions": "edit",
  "record-reference": "edit",
  "emit-brief": "edit",
  workpaper: "read",
  "launch-formulator": "execute",
  "stop-formulator": "execute",
  "query-locked": "edit",
  "re-import": "edit",
};

export function toolDefinition(toolName) {
  const spec = specFor(toolName);
  return {
    name: toolName,
    description: spec.description,
    parameters: spec.parameters,
    output: {
      schema: OUTPUT_SCHEMA,
      render: (_args, value) => [
        { type: "text", text: value?.stdout || `${value?.tool ?? toolName} 完成` },
      ],
    },
    presentCall: presentCall(toolName, CALL_KINDS[toolName] ?? "other"),
    execute: async (args, exec) => {
      const input = args ?? {};
      checkArgs(toolName, spec, input);
      return { tool: toolName, stdout: foundry(spec.argv(input), exec) };
    },
  };
}

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
  const undocumented = REQUIRED.filter((toolName) => !Object.hasOwn(TOOL_SPECS, toolName));
  const orphaned = Object.keys(TOOL_SPECS).filter((toolName) => !REQUIRED.includes(toolName));
  if (undocumented.length || orphaned.length) {
    throw new Error(
      `foundry plugin startup failed; tool metadata drifted from package.json: missing ${undocumented.join(",") || "(none)"}, extra ${orphaned.join(",") || "(none)"}`,
    );
  }
  const leaks = available.filter((toolName) => periodDenied(toolName));
  if (leaks.length) {
    throw new Error(`period profile must omit ${leaks.join(",")}`);
  }
  const enabled = toolsForProfile(options.profile ?? options.phase);
  return enabled.map((toolName) => toolDefinition(toolName));
}

/**
 * The tools this profile would register, without a runtime to register them on.
 *
 * `apply` cannot answer this any more: the Cordis contract is that it registers
 * on the context it is handed and returns nothing, and a caller that read its
 * return value was reading a value the runtime itself discards. The headless
 * smoke and the bundle test enumerate through here instead.
 */
export function definitions(profile) {
  return registerTools(REQUIRED, { profile });
}

/**
 * The companion tools the close seat must not see.
 *
 * Read from the manifest rather than restated, so the roster that scopes the
 * preset and the roster that documents the companion are one list. An empty
 * list would be a scope that quietly allows everything, so it refuses.
 */
export function officeDenied() {
  const pkg = JSON.parse(readFileSync(PACKAGE_URL, "utf8"));
  const denied = pkg?.dsh?.foundry?.companions?.office?.omitTools ?? [];
  if (!denied.length) {
    throw new Error("office companion declares no omitTools; the period scope would allow all of them");
  }
  return denied;
}

export function f3Allowlist() {
  return ["query-locked"];
}

export function f3Denied(toolName) {
  return toolName !== "query-locked";
}

/**
 * Register this bundle's tools on a live runtime.
 *
 * The shape is the runtime's own, and it is not what this file used to do. The
 * previous `apply` built the tool list and *returned* it; Cordis discards a
 * plugin's return value, so under a real `dsh` boot nothing was ever registered
 * and nothing said so. `inject` names the service this needs before it runs, and
 * `ctx.tools.register` is the only thing that puts a tool in front of a model.
 *
 * The profile arrives as the patch row's own `config`, so which roster a
 * composition gets is a deployment decision in the patch file rather than
 * something a caller passes at runtime.
 */
export function apply(ctx, config = {}) {
  const profile = config.profile ?? process.env.FOUNDRY_PROFILE ?? undefined;
  for (const definition of definitions(profile)) {
    ctx.tools.register(definition);
  }
}
