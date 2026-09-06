import { readFileSync } from "node:fs";
import { invokeFoundry, toolDefinition } from "./index.js";
import { createAnalysisRuntime } from "./analysis-runtime.js";
import { FINANCE_TOOLS } from "./finance-tools.js";

const PROFILE = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"))
  .dsh.foundry.profiles.analysis;
const string = (description) => ({ type: "string", description });
const object = (properties, required = Object.keys(properties)) => ({
  type: "object", properties, required, additionalProperties: false,
});
const json = (value) => JSON.stringify(value);
const relationship = {
  type: "object",
  required: ["left", "right", "left_keys", "right_keys", "cardinality"],
  additionalProperties: false,
  properties: {
    left: string("左侧 SQL 表别名，必须是 bindings 中的别名，例如 actual"),
    right: string("右侧 SQL 表别名，必须是 bindings 中的别名，例如 budget"),
    left_keys: { type: "array", minItems: 1, items: { type: "string" }, description: "左侧表参与 JOIN 的字段名数组，顺序对应 right_keys" },
    right_keys: { type: "array", minItems: 1, items: { type: "string" }, description: "右侧表参与 JOIN 的字段名数组，顺序对应 left_keys" },
    cardinality: { type: "string", enum: ["one-to-one", "one-to-many", "many-to-one", "many-to-many"], description: "按 left -> right 方向声明基数；预算/映射表常见为 many-to-one" },
    allow_many_to_many: { type: "boolean", description: "仅当确需多对多并已说明分摊/去重口径时为 true" },
    rationale: { type: "string", description: "many-to-many 必填；说明分摊、去重或重复行处理口径" },
  },
};
const claim = {
  type: "object",
  required: ["basis"],
  additionalProperties: true,
  properties: {
    basis: {
      type: "string",
      enum: ["source_fact", "calculation", "external_reference", "user_assumption", "professional_judgment"],
      description: "证据类型；计算结果用 calculation，经理调整/假设用 user_assumption，专业判断用 professional_judgment",
    },
    run_id: string("basis=calculation 时必填，引用 analysis-run 返回的成功运行 id"),
    row: { type: "integer", minimum: 0, description: "basis=calculation 时必填；result.rows 的下标，从 0 开始" },
    column: string("basis=calculation 时必填，引用 result.rows[row] 中的列名"),
    value: string("basis=calculation 时必填，必须等于该 run 对应单元格；经理调整另写 user_assumption claim"),
    dataset_id: string("source_fact 可选，引用资料快照 id"),
    paragraph: { type: "integer", minimum: 0, description: "背景资料段落号，按 dataset-read 返回值填写" },
    reason: string("用户假设、专业判断或调整说明"),
  },
};

// These commands share the legacy tool result envelope, but no Window state or
// current pointer. Every call is resolved by the service from exec.agent.id.
const SPECS = {
  ...FINANCE_TOOLS,
  "method-resource": {
    description: "读取已随包技能明确引用的配套说明。skill 工具加载正文后，用此入口读取 FOUNDRY.md 的运行模式规则或 CONNECTORS.md 的连接类别说明，也可核对 NOTICE/LICENSE。只能读取四项随包技能的这些资源，不能传本机路径；不读取用户同名技能或账套资料。返回来源路径、内容哈希与全文。",
    parameters: object({
      skill: { type: "string", enum: ["financial-statements", "variance-analysis", "reconciliation", "journal-entry"] },
      resource: { type: "string", enum: ["FOUNDRY.md", "CONNECTORS.md", "NOTICE", "LICENSE"] },
    }),
    kind: "read", argv: (input) => ["method-resource", "--skill", input.skill, "--resource", input.resource],
  },
  "analysis-state": {
    description: "读取当前分析任务的资料快照、分析版本、运行记录、文稿和可复用方法。先查看已有资料与字段，再明确计算表达式；无需建科目表或锁期间窗口。stdout 为 JSON。",
    parameters: object({}), kind: "read", argv: () => ["analysis-state"],
  },
  "analysis-refresh": {
    description: "将当前任务中新加入的资料明确加入本会话的后续分析范围，生成新的上下文版本；已经启动的计算保留原快照。仅刷新本任务资料，不读取其他任务。",
    parameters: object({}), kind: "edit", argv: () => ["analysis-refresh"],
  },
  "dataset-add": {
    description: "将当前任务工作区中的已授权表格资料登记为不可变数据快照，保存来源和字段。无需科目表。运行会话仅可读取服务登记的任务工作区，不能用任意本机路径；资料缺失时让用户加入资料。stdout 为快照 JSON。",
    parameters: object({
      path: string("已加入当前任务工作区的 csv/xlsx/json 表格或 md/txt 背景资料路径"),
      name: string("数据集名称，例如 实际收入、预算、应收明细"),
      meta: { type: "object", description: "资料元数据：期间、币种、金额单位、粒度等；按源资料填写，不猜测缺失值" },
    }, ["path", "name"]),
    kind: "edit", argv: (input) => ["dataset-add", "--path", input.path, "--name", input.name, "--meta", json(input.meta ?? {})],
  },
  "dataset-read": {
    description: "读取当前任务已绑定快照的字段、类型和明细，或背景资料的原文与段落来源，用于检查资料与设计联查。正式计算用 analysis-save + analysis-run 固化表达式和结果。stdout 为 JSON。",
    parameters: object({ dataset: string("analysis-state 或 dataset-add 返回的快照 id") }),
    kind: "read", argv: (input) => ["dataset-read", "--dataset", input.dataset],
  },
  "analysis-save": {
    description: "保存可修改的分析定义，不执行计算。spec 必须包含 question、显式只读 SQL、bindings（SQL表别名到快照id）。question 仅说明业务目的，不会自动变成公式。可用 parameters 参数化查询；parameter_metadata 可为实际 SQL 参数绑定业务名称、类型、单位和约束，不能猜测没有绑定的字段。assumptions 只记录说明，修改说明不会改变公式；grain、relationships、metrics 记录粒度/关系/指标，parent_id 生成后续版本。跨表 JOIN 必须声明 relationships，格式为 {left,right,left_keys,right_keys,cardinality}，例如 actual JOIN budget USING(period,region) 对应 left='actual', right='budget', left_keys=['period','region'], right_keys=['period','region'], cardinality='one-to-one'；不要传字符串、source/target/on 或 1:1。金额口径、比较期间、币种和分摊规则须明确，跨表先检查重复键和匹配情况。",
    parameters: object({ spec: {
      type: "object", required: ["question", "sql", "bindings"],
      properties: {
        question: string("本次分析的业务问题"), sql: string("对绑定表别名执行的显式只读 SQL；不允许外部文件读取、多条语句或任意连接"),
        bindings: { type: "object", additionalProperties: { type: "string" }, description: "SQL表别名到已登记快照id，例如 {actual: dataset_id}" },
        parameters: { oneOf: [{ type: "array", items: {} }, { type: "object", additionalProperties: {} }], description: "对应 SQL 占位符的数组或命名键对象；金额用字符串保留精度" },
        parameter_metadata: { type: "array", description: "可选业务参数描述；key必须对应实际SQL参数，position从1开始；默认不猜业务语义", items: {
          type: "object", required: ["label", "type"], properties: {
            key: { type: "string" }, position: { type: "integer", minimum: 1 }, label: { type: "string" },
            type: { type: "string", enum: ["string", "decimal", "integer", "boolean", "date"] },
            unit: { type: "string" }, description: { type: "string" },
            role: { type: "string", enum: ["business", "formula_constant"] },
            constraints: { type: "object", properties: { min: {}, max: {}, choices: { type: "array", items: {} }, nullable: { type: "boolean" } } },
            default: { description: "共享方法仅保留明确声明的数值/布尔公式常数默认；业务值需在新任务提供" },
          },
        } },
        assumptions: { type: "array", items: {}, description: "用户假设及其依据" },
        grain: { type: "array", items: {}, description: "参与计算的数据粒度" },
        relationships: { type: "array", items: relationship, description: "表间关联键和基数约束；JOIN 时必填 left/right/left_keys/right_keys/cardinality" },
        metrics: { type: "array", items: {}, description: "指标定义、币种、单位与舍入规则" },
        parent_id: string("修改既有定义时填写父分析id"),
      },
    } }),
    kind: "edit", argv: (input) => ["analysis-save", "--spec", json(input.spec)],
  },
  "analysis-run": {
    description: "执行已保存的显式 SQL 分析，固化输入快照、计算表达式、参数、执行状态和输出。只能访问本次绑定的数据。金额按 JSON 字符串返回；检查状态与局限后再引用结果，不把运行成功等同于经理认可。stdout 为运行 JSON，result 包含 columns、rows、row_count、truncated。",
    parameters: object({ analysis: string("analysis-save 返回的分析版本id") }),
    kind: "execute", argv: (input) => ["analysis-run", "--analysis", input.analysis],
  },
  "analysis-script": {
    description: "在已验证的隔离运行环境中执行 Python 或受限 shell 清洗、计算或生成图表。绑定快照由服务复制至只读目录（环境变量 FOUNDRY_INPUTS）：每个别名有 .json 标准化数据及原件。当前工作目录即本次输出目录（FOUNDRY_OUTPUTS），只能向此处写文件。无网络、无宿主密钥、不能读其他任务或历史记录。spec 明确 code、bindings，可附 question、language、assumptions、timeout_seconds。保存真实代码、环境、输入输出哈希与执行状态；不可用或失败时照实报告。脚本输出尚不自动成为可引用的SQL行列数字，引用前检查实际输出与假设。",
    parameters: object({ spec: {
      type: "object", required: ["code", "bindings"],
      properties: {
        code: string("完整代码；用 os.environ['FOUNDRY_INPUTS'] 读取绑定快照，在当前目录写结果；shell使用对应环境变量。不得猜测宿主目录"),
        language: { type: "string", enum: ["python", "shell"] },
        bindings: { type: "object", additionalProperties: { type: "string" }, description: "本次允许读取的别名到快照id映射" },
        question: string("本次脚本要回答的问题"),
        assumptions: { type: "array", items: {} },
        timeout_seconds: { type: "integer", minimum: 1, maximum: 120 },
      },
    } }),
    kind: "execute", argv: (input) => ["analysis-script", "--spec", json(input.spec)],
  },
  "analysis-script-start": {
    description: "在后台执行隔离 Python/受限 shell 分析，立即返回持久 job id。spec 与 analysis-script 一致，输入快照和上下文在启动时固定。用 analysis-jobs / analysis-job-output 查看，analysis-job-cancel 取消，失败后 analysis-job-retry 创建可追溯的新尝试。后台记录不等于执行成功。",
    parameters: object({ spec: { type: "object", required: ["code", "bindings"], properties: {
      code: string("完整代码；通过环境变量 FOUNDRY_INPUTS 读输入，在当前工作目录写输出"), language: { type: "string", enum: ["python", "shell"] },
      bindings: { type: "object", additionalProperties: { type: "string" } }, question: string("业务问题"),
      assumptions: { type: "array", items: {} }, timeout_seconds: { type: "integer", minimum: 1, maximum: 120 },
    } } }),
    kind: "execute", argv: (input) => ["analysis-script-start", "--spec", json(input.spec)],
  },
  "analysis-delegate": {
    description: "将独立分析或研究交给同一任务下的子助手并在后台继续。先保存子任务与冻结的上下文，再创建真实harness子会话。spawn 从完整独立指令开始，fork 继承已结束的对话轮次；当前轮要点仍需写入prompt。子助手仅可研究、读取已绑定快照和执行分析，不能添加资料、修改主文稿或继续委派。返回job id，用 analysis-job-output 读取实际状态和结果。",
    parameters: object({ prompt: string("范围清晰的独立子任务，注明资料别名、问题、口径和所需结果"), label: string("简短任务名"), mode: { type: "string", enum: ["spawn", "fork"] } }, ["prompt", "label"]),
    kind: "execute", runtime: true,
  },
  "analysis-jobs": {
    description: "列出当前会话拥有的持久后台计算和子任务，查看真实状态；不要重复启动仍在运行的任务。",
    parameters: object({}), kind: "read", argv: () => ["analysis-job-list"],
  },
  "analysis-job-output": {
    description: "读取指定后台任务的状态、执行结果和局限。任务仍在运行时继续独立工作；queued/running 不表示完成。",
    parameters: object({ job: string("当前会话的后台任务id") }), kind: "read", argv: (input) => ["analysis-job-show", "--job", input.job],
  },
  "analysis-job-cancel": {
    description: "请求取消当前会话拥有的后台计算或子助手。子助手会在运行时停止后登记结果；脚本由服务工作进程处理取消，若仍在运行可用 analysis-job-output 查看最终状态。已经结束的任务保持原状态。",
    parameters: object({ job: string("要取消的后台任务id") }), kind: "execute", runtime: true,
  },
  "analysis-job-retry": {
    description: "为失败或取消的任务创建新的尝试，沿用原先冻结的资料与指令并记录 retry_of；不会改写旧任务结果。要改变口径或资料则新建分析。",
    parameters: object({ job: string("需要重试的后台任务id") }), kind: "execute", runtime: true,
  },
  "analysis-draft": {
    description: "从分析结果与专业判断保存一版可编辑文稿，允许先导出草稿。spec 包含 title、body、run_ids、claims、limitations，可用 parent_id 延续上一版。claims 的 basis 必须是 source_fact、calculation、external_reference、user_assumption 或 professional_judgment。计算数字用 basis=calculation、run_id、row、column、value 引用真实输出；row 是 result.rows 的 0-based 下标，第一行写 0，不要写自然语言行号；假设和判断分别标明，不伪造计算依据。review_status 与 publication_status 独立，只有用户明确选定归档时设置 archived，已归档内容不会原地修改。",
    parameters: object({ spec: {
      type: "object", required: ["title", "body"],
      properties: {
        title: string("文稿标题"), body: string("可编辑 Markdown 正文，包含结论、依据和局限"),
        run_ids: { type: "array", items: { type: "string" } },
        claims: { type: "array", items: claim, description: "数字定位与来源、用户假设、专业判断；计算引用包含 basis,run_id,row,column,value；row 使用 result.rows 的 0-based 下标" },
        limitations: { type: "array", items: { type: "string" } },
        parent_id: string("上一文稿版本id"),
        publication_status: { type: "string", enum: ["draft", "archived"] },
        review_status: { type: "string", enum: ["unreviewed", "reviewed", "accepted"] },
      },
    } }),
    kind: "edit", argv: (input) => ["analysis-draft", "--spec", json(input.spec)],
  },
  "analysis-export": {
    description: "导出指定文稿版本为 Markdown 或 Excel 工作簿，包含其结果和依据。草稿可直接导出；导出不自动标记为经理认可或正式归档。stdout 为导出记录 JSON。",
    parameters: object({ draft: string("analysis-draft 返回的文稿版本id"), format: { type: "string", enum: ["md", "xlsx"] } }),
    kind: "edit", argv: (input) => ["analysis-export", "--draft", input.draft, "--format", input.format],
  },
  "analysis-method-save": {
    description: "将选定分析定义保存为可复用方法，保留表达式与数据契约；任务敏感数据和临时问题不默认带入。方法沉淀是成功分析后的可选动作，不阻止当前分析。",
    parameters: object({ analysis: string("分析版本id"), name: string("方法名称") }),
    kind: "edit", argv: (input) => ["analysis-method-save", "--analysis", input.analysis, "--name", input.name],
  },
  "analysis-method-apply": {
    description: "将方法绑定到当前任务的新快照，生成分析版本后再用 analysis-run 执行。必须重新明确各表绑定；按方法契约的canonical参数key提供当前业务值；参数对象可以省略契约明确标出的公式常数默认。业务默认值与choices不会从上个任务继承。先检查真实参数名称、单位及新绑定，生成后再运行。",
    parameters: object({
      method: string("方法id"), bindings: { type: "object", additionalProperties: { type: "string" } },
      parameters: { oneOf: [{ type: "array", items: {} }, { type: "object", additionalProperties: {} }] }, question: string("当前任务的问题"),
    }, ["method", "bindings"]),
    kind: "edit", argv: (input) => [
      "analysis-method-apply", "--method", input.method, "--bindings", json(input.bindings),
      ...(input.parameters === undefined ? [] : ["--parameters", json(input.parameters)]),
      ...(input.question === undefined ? [] : ["--question", input.question]),
    ],
  },
};

export const name = "finance-skill-foundry-analysis";
export const inject = ["tools", "subagents"];

export function definitions(runtime) {
  const declared = PROFILE.tools;
  if (!Array.isArray(declared) || !declared.length || declared.length !== Object.keys(SPECS).length
      || declared.some((tool) => !Object.hasOwn(SPECS, tool))) {
    throw new Error("analysis tool metadata drifted from package.json");
  }
  return declared.map((tool) => toolDefinition(tool, {
    ...SPECS[tool], requireSession: true,
    execute: (input, exec) => SPECS[tool].runtime
      ? (runtime ? runtime(tool, input, exec) : Promise.reject(new Error("analysis runtime is unavailable")))
      : invokeFoundry(SPECS[tool].argv(input), exec),
  }));
}

export function allowlist() {
  return [...PROFILE.tools, ...PROFILE.harnessTools];
}

export function apply(ctx) {
  const runtime = createAnalysisRuntime(ctx, PROFILE.childTools);
  for (const definition of definitions(runtime)) ctx.tools.register(definition);
  // Restrictions filter inherited tools for actual sessions as well as the
  // standing preset. An empty allowlist would hide this preset's own tools
  // after an agent joins it, so deny the current GLOBAL layer explicitly.
  const denied = ctx.tools.schemas().map((tool) => tool.name).filter((tool) => tool !== "run_code");
  if (denied.length) ctx.tools.restrict({ deny: denied });
  const allowed = new Set([...allowlist(), "report"]);
  // Keep late registrations from acquiring execution authority in a live task.
  ctx.tools.guard((exec) => allowed.has(exec.name) ? undefined : `analysis cannot execute ${exec.name}`);
}
