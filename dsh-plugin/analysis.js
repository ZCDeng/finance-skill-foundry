import { readFileSync } from "node:fs";
import { invokeFoundry, toolDefinition } from "./index.js";
import { createAnalysisRuntime } from "./analysis-runtime.js";
import { createCompletionRuntime } from "./completion-runtime.js";
import { FINANCE_TOOLS, NUMERIC_PRESENTATION } from "./finance-tools.js";

const PROFILE = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"))
  .dsh.foundry.profiles.analysis;
const string = (description) => ({ type: "string", description });
const object = (properties, required = Object.keys(properties)) => ({
  type: "object", properties, required, additionalProperties: false,
});
const json = (value) => JSON.stringify(value);
const resultRole = {
  type: "string",
  enum: ["business", "activity", "probe", "preanalysis", "calculation", "draft_support", "audit_check"],
  description: "本次运行结果在业务流程中的角色；后端校验并持久化到 analysis/run 记录。默认 SQL 有 result_file 时 business，否则 activity；脚本默认 business。",
};
const runScope = {
  type: "object",
  additionalProperties: true,
  description: "本次运行结果适用的账套、组织、期间、币种、单位等业务范围元数据；后端按对象持久化，不替代 filters/exclusions。",
};
const requirementsId = string("analysis_requirements_save 返回的要求版本 id；用于把运行与当前问题/范围绑定");
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

const filterCondition = {
  type: "object",
  required: ["field", "op"],
  additionalProperties: false,
  properties: {
    field: string("数据集字段名；必须来自 dataset-read/schema，不猜不存在的列"),
    op: { type: "string", enum: ["eq", "ne", "in", "not_in", "between", "gt", "gte", "lt", "lte", "is_null", "not_null"], description: "筛选操作；in/not_in/between 使用 values，其余比较使用 value；空值判断不传 value" },
    value: { description: "单值筛选/比较值；金额保持字符串以保留精度" },
    values: { type: "array", items: {}, description: "多值筛选或 between 两端；金额保持字符串以保留精度" },
    reason: string("该筛选或剔除条件的业务原因，例如 剔除作废行、仅看本期收入"),
  },
};
const aggregateMeasure = {
  type: "object",
  required: ["name", "aggregation"],
  additionalProperties: false,
  properties: {
    name: string("结果列名，例如 revenue、customer_count"),
    field: string("参与聚合的来源字段；count 可省略，sum/min/max/count_distinct 必须指向真实字段"),
    aggregation: { type: "string", enum: ["sum", "count", "count_distinct", "min", "max"], description: "当前结构化聚合支持的确定性聚合函数" },
  },
};
const aggregatePlan = {
  type: "object",
  required: ["dataset_alias", "measures", "dedupe"],
  additionalProperties: false,
  properties: {
    dataset_alias: string("唯一输入快照别名；必须是 bindings 中唯一的键，例如 actual"),
    filters: { type: "array", items: filterCondition, description: "纳入条件；所有条件都按 AND 应用，并保留可下钻来源行" },
    exclusions: { type: "array", items: filterCondition, description: "剔除条件；被剔除行会进入可下钻的剔除明细，reason 应说明业务口径" },
    group_by: { type: "array", items: { type: "string" }, description: "分组字段；跨币种/单位合计时必须把 currency/unit 纳入分组或先用 scope/filter 限定" },
    measures: { type: "array", minItems: 1, items: aggregateMeasure, description: "输出指标；加总类指标可追溯纳入/剔除，min/max/count_distinct 不声称加总勾稽" },
    dedupe: { type: "object", required: ["policy"], additionalProperties: false, properties: {
      policy: { type: "string", enum: ["none", "error_on_duplicate", "keep_first_identical_else_error"], description: "重复业务键处理；不能静默选择冲突行" },
      keys: { type: "array", items: { type: "string" }, description: "判定重复的业务键字段，例如 doc_id,line_id" },
    } },
    result_key_columns: { type: "array", items: { type: "string" }, description: "可选稳定结果键字段；通常与 group_by 一致，用于后续 claim/drilldown 定位" },
    scope: { type: "object", additionalProperties: {}, description: "可选账套/组织/期间/币种等业务范围说明；只作为计划元数据，真实筛选仍写 filters/exclusions" },
  },
};
const analysisSpec = {
  type: "object",
  required: ["question", "bindings"],
  additionalProperties: false,
  oneOf: [
    { required: ["question", "sql", "bindings"], properties: { engine: { enum: ["sql"] } }, not: { required: ["aggregate_plan"] }, description: "自由 SQL 分支：必须提供显式只读 SQL；可做临时测算，但不会因为金额相同就获得完整 verified 来源行追溯。" },
    { required: ["question", "engine", "bindings", "aggregate_plan"], properties: { engine: { enum: ["structured_aggregate"] }, bindings: { type: "object", minProperties: 1, maxProperties: 1 } }, not: { anyOf: [{ required: ["sql"] }, { required: ["parameters"] }, { required: ["parameter_metadata"] }, { required: ["relationships"] }] }, description: "结构化聚合分支：只接受一个绑定快照和 aggregate_plan；不接 SQL、parameters 或 relationships。" },
  ],
  properties: {
    question: string("本次分析的业务问题"),
    engine: { type: "string", enum: ["sql", "structured_aggregate"], description: "省略时为 sql；structured_aggregate 用声明式聚合计划生成可下钻来源行" },
    sql: string("SQL 分支使用：对绑定表别名执行的显式只读 SQL；不允许外部文件读取、多条语句或任意连接；自由 SQL 可用但来源行不会自动升级为完整 verified"),
    bindings: { type: "object", minProperties: 1, maxProperties: 32, additionalProperties: { type: "string" }, description: "表别名到已登记快照id，例如 {actual: dataset_id}；structured_aggregate 只允许一个别名" },
    aggregate_plan: aggregatePlan,
    parameters: { oneOf: [{ type: "array", items: {} }, { type: "object", additionalProperties: {} }], description: "SQL 分支使用：对应 SQL 占位符的数组或命名键对象；金额用字符串保留精度" },
    parameter_metadata: { type: "array", description: "SQL 分支使用：可选业务参数描述；key必须对应实际SQL参数，position从1开始；默认不猜业务语义", items: {
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
    relationships: { type: "array", items: relationship, description: "SQL JOIN 分支使用：表间关联键和基数约束；structured_aggregate 不使用 relationships" },
    metrics: { type: "array", items: {}, description: "指标定义、币种、单位与舍入规则" },
    missing_inputs: { type: "array", items: {}, description: "保存时已知缺失资料或口径，不把缺失推断为0" },
    conversion_rules: { type: "array", items: {}, description: "明确的币种、单位或口径转换规则；未声明则不得改标签合并" },
    requirements_id: requirementsId,
    result_role: resultRole,
    scope: runScope,
    timeout_seconds: { type: "number", minimum: 0.01, maximum: 60 },
    max_rows: { type: "integer", minimum: 1, maximum: 10000 },
    method_id: string("由方法应用生成时的来源方法 id"),
    parent_id: string("修改既有定义时填写父分析id"),
  },
};


const evidenceSource = {
  type: "object",
  required: ["dataset_id", "source_hash", "sheet", "range"],
  additionalProperties: false,
  properties: {
    dataset_id: string("授权资料快照 id；必须属于当前任务/会话"),
    source_hash: string("资料原始文件 SHA-256；必须匹配归档快照"),
    sheet: string("工作表名"),
    range: string("有界 A1 矩形，例如 B36:I39；不接受整列/整行"),
  },
};
const evidenceClaim = {
  type: "object",
  required: ["run_id", "row", "column"],
  additionalProperties: false,
  properties: {
    run_id: string("被核验的运行 id"),
    row: { type: "integer", minimum: 0, description: "result.rows 的 0-based 行下标" },
    column: string("被核验的结果列名；expected 由该运行单元格读取，不由模型填写"),
  },
};
const evidenceRecipe = {
  type: "object",
  required: ["kind", "claim"],
  additionalProperties: false,
  oneOf: [
    { required: ["kind", "claim", "dataset_id", "source_hash", "sheet", "range"], properties: { kind: { enum: ["direct", "sum"] } }, not: { anyOf: [{ required: ["left"] }, { required: ["right"] }] } },
    { required: ["kind", "claim", "left", "right"], properties: { kind: { enum: ["diff", "ratio"] } }, not: { anyOf: [{ required: ["dataset_id"] }, { required: ["source_hash"] }, { required: ["sheet"] }, { required: ["range"] }, { required: ["factor_recipe_id"] }] } },
  ],
  properties: {
    id: string("稳定 recipe id，同一文稿内唯一；省略时服务按顺序生成 recipe-N"),
    label: string("给财务经理看的检查名称；省略时使用 id"),
    kind: { type: "string", enum: ["direct", "sum", "diff", "ratio"] },
    ...evidenceSource.properties,
    left: evidenceSource,
    right: evidenceSource,
    scale: string("可选自填 Decimal 缩放，默认 1；只核验乘法，不能证明系数来源"),
    factor_recipe_id: string("仅 direct/sum 估算可选：引用本批次已由归档数值范围独立复算通过的 ratio recipe；需同一 business_key.metric_key 与 period；同时写 scale 时只能是 1 或千/万/百万/亿单位换算，系数只写在被引用的 ratio 规则里"),
    unit: string("展示单位"),
    claim: evidenceClaim,
    business_key: { type: "object", additionalProperties: true },
  },
};


const consistencySource = {
  type: "object",
  required: ["id", "kind", "dataset_id", "source_hash"],
  additionalProperties: false,
  oneOf: [
    { required: ["id", "kind", "dataset_id", "source_hash", "sheet", "range"], properties: { kind: { enum: ["number"] } }, not: { required: ["paragraph"] } },
    { required: ["id", "kind", "dataset_id", "source_hash", "paragraph"], properties: { kind: { enum: ["text"] } }, not: { anyOf: [{ required: ["sheet"] }, { required: ["range"] }, { required: ["scale"] }] } },
    { required: ["id", "kind", "dataset_id", "source_hash", "sheet", "range"], properties: { kind: { enum: ["text"] } }, not: { anyOf: [{ required: ["paragraph"] }, { required: ["scale"] }] } },
  ],
  properties: {
    id: string("稳定 source id，供 consistency_rules 引用"),
    label: string("展示标签"),
    kind: { type: "string", enum: ["number", "text"] },
    dataset_id: string("授权归档资料快照 id"),
    source_hash: string("资料原始文件 SHA-256；必须匹配归档快照"),
    sheet: string("归档工作簿 sheet；number source 必填，text source 可用单格 sheet/range 代替 paragraph"),
    range: string("归档工作簿有界范围；number source 可为单格或区域，text source 只能是单格；模型不能填写 value/original_text"),
    paragraph: { type: "integer", minimum: 1, description: "text source 的归档段落号；与 sheet/range 二选一" },
    scale: string("number source 可选 Decimal 缩放，默认 1"),
  },
};
const consistencyRule = {
  type: "object",
  required: ["id", "kind", "threshold", "asserted_result", "assertion_source_id", "values"],
  additionalProperties: false,
  properties: {
    id: string("稳定规则 id"),
    label: string("展示标签"),
    kind: { type: "string", enum: ["all_absolute_exceed"] },
    threshold: string("Decimal 阈值；按绝对值比较"),
    asserted_result: { type: "boolean", description: "正文声明的判断结果" },
    assertion_source_id: string("声明文本所在的 consistency source id；必须是归档 text source"),
    values: { type: "array", minItems: 1, items: { type: "object", additionalProperties: false, required: ["id"], oneOf: [{ required: ["source_id"] }, { required: ["recipe_result_id"] }], properties: { id: string("值 id"), label: string("展示标签"), source_id: string("归档 number source id；服务读取真实数值"), recipe_result_id: string("也可引用 evidence_recipes 的 recipe_id/result_id") } } },
  },
};

const claim = {
  type: "object",
  required: ["basis"],
  additionalProperties: false,
  properties: {
    basis: {
      type: "string",
      enum: ["source_fact", "calculation", "external_reference", "user_assumption", "professional_judgment"],
      description: "证据类型；计算结果用 calculation，经理调整/假设用 user_assumption，专业判断用 professional_judgment",
    },
    run_id: string("basis=calculation 时必填，引用 analysis-run 返回的成功运行 id"),
    row: { type: "integer", minimum: 0, description: "basis=calculation 时必填；result.rows 的下标，从 0 开始" },
    column: string("basis=calculation 时必填，引用 result.rows[row] 中的列名"),
    value: string("basis=calculation 时必填，必须等于该 run 对应单元格；不匹配时更正 row/column/value。独立业务假设另写 user_assumption claim，不能覆盖计算值。"),
    fact_id: string("prepare_explanation 返回的真实事实 id；使用 presentation 时必填"),
    presentation: NUMERIC_PRESENTATION,
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
      meta: { type: "object", description: "资料元数据：期间、币种、金额单位、粒度等；按源资料填写。XLSX默认多表保留完整工作簿，明确单表可传sheet，或mode=table；mode=workbook强制保留原件目录，不猜表头" },
    }, ["path", "name"]),
    kind: "edit", argv: (input) => ["dataset-add", "--path", input.path, "--name", input.name, "--meta", json(input.meta ?? {})],
  },
  "dataset-read": {
    description: "读取当前任务已绑定快照的字段、类型和明细，或背景资料的原文与段落来源；kind=workbook 返回完整工作簿的工作表目录，不是零行数据表。工作簿需先确定工作表及范围，再用 workbook_inspect/workbook_read 或 analysis-script 读取原始快照。普通表格计算用 analysis-save + analysis-run 固化表达式和结果。stdout 为 JSON。",
    parameters: object({ dataset: string("analysis-state 或 dataset-add 返回的快照 id") }),
    kind: "read", argv: (input) => ["dataset-read", "--dataset", input.dataset],
  },
  "analysis-save": {
    description: "保存可修改的分析定义，不执行计算。默认 SQL 分支必须包含 question、显式只读 SQL、bindings（SQL表别名到快照id）；自由 SQL 可用于临时测算，但不会因为金额相同就获得完整 verified 来源行追溯。结构化聚合分支设置 engine='structured_aggregate'，只接一个 binding 和 aggregate_plan，不接 SQL/parameters/relationships；它会用声明式 filters/exclusions/group_by/measures/dedupe 生成可下钻来源行。question 仅说明业务目的，不会自动变成公式。金额口径、比较期间、币种和分摊规则须明确，跨表 SQL JOIN 仍必须声明 relationships，包含 left/right/left_keys/right_keys/cardinality。",
    parameters: object({ spec: analysisSpec }),
    kind: "edit", argv: (input) => ["analysis-save", "--spec", json(input.spec)],
  },
  "analysis-run": {
    description: "执行已保存的显式 SQL 分析，固化输入快照、计算表达式、参数、执行状态和输出。只能访问本次绑定的数据。金额按 JSON 字符串返回；检查状态与局限后再引用结果，不把运行成功等同于经理认可。stdout 为运行 JSON，result 包含 columns、rows、row_count、truncated。",
    parameters: object({ analysis: string("analysis-save 返回的分析版本id") }),
    kind: "execute", argv: (input) => ["analysis-run", "--analysis", input.analysis],
  },
  "analysis-script": {
    description: "在已验证的隔离运行环境中执行 Python 或受限 shell 清洗、计算或生成图表。绑定快照由服务复制至只读目录（环境变量 FOUNDRY_INPUTS）：每个别名有 .json 标准化数据及原件。当前工作目录即本次输出目录（FOUNDRY_OUTPUTS），只能向此处写文件。无网络、无宿主密钥、不能读其他任务或历史记录。spec 明确 code、bindings，可附 question、language、assumptions、timeout_seconds。保存真实代码、环境、输入输出哈希与执行状态；不可用或失败时照实报告。需要在结果区和文稿中引用数值时，指定 result_file 为脚本写出的 CSV 或 JSON 表格文件；服务校验其清单和摘要后填充 result.rows。金额以精确数字字符串写入；同一数值列只放数字或 null，单位放 unit，解释和小计说明放 note，不把“26 个项目”等文本混入数值列。附来源工作表、单元格、单位；此结果仍为脚本计算，复现与原始行取证不会自动变成已验证。",
    parameters: object({ spec: {
      type: "object", required: ["code", "bindings"],
      properties: {
        code: string("完整代码；用 os.environ['FOUNDRY_INPUTS'] 读取绑定快照，在当前目录写结果；shell使用对应环境变量。不得猜测宿主目录"),
        language: { type: "string", enum: ["python", "shell"] },
        bindings: { type: "object", additionalProperties: { type: "string" }, description: "本次允许读取的别名到快照id映射" },
        question: string("本次脚本要回答的问题"),
        result_file: string("可选：当前输出目录中已生成的 CSV/JSON 表格相对路径，例如 result.json；JSON为对象行数组，列名非空唯一，金额使用字符串"),
        requirements_id: requirementsId,
        result_role: resultRole,
        scope: runScope,
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
      result_file: string("可选：本次输出的 CSV/JSON 表格相对路径，用于可引用结果行；金额用字符串"),
      requirements_id: requirementsId, result_role: resultRole, scope: runScope,
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
    description: "从分析结果与专业判断保存一版可编辑文稿，允许先导出草稿。spec 包含 title、body、run_ids、claims、limitations，可用 parent_id 延续上一版。claims 的 basis 必须是 source_fact、calculation、external_reference、user_assumption 或 professional_judgment。计算数字用 basis=calculation、run_id、row、column、value 引用真实输出；row 是 result.rows 的 0-based 下标，第一行写 0，不要写自然语言行号；假设和判断分别标明，不伪造计算依据。关键数字可附 evidence_recipes，用归档工作簿单元格/范围独立核验指定 run 单元格；recipe 的 expected 不能自填，必须由 claim.run_id/row/column 指向真实运行结果。review_status 与 publication_status 独立，只有用户明确选定归档时设置 archived，已归档内容不会原地修改。",
    parameters: object({ spec: {
      type: "object", required: ["title", "body"],
      properties: {
        title: string("文稿标题"), body: string("可编辑 Markdown 正文，包含结论、依据和局限"),
        run_ids: { type: "array", items: { type: "string" } },
        claims: { type: "array", items: claim, description: "数字定位与来源、用户假设、专业判断；计算引用包含 basis,run_id,row,column,value；row 使用 result.rows 的 0-based 下标" },
        limitations: { type: "array", items: { type: "string" } },
        evidence_recipes: { type: "array", items: evidenceRecipe, description: "独立来源核验 recipe；用于检查运行结果是否等于归档工作簿中的单元格、范围和差额/比例" },
        consistency_sources: { type: "array", items: consistencySource, description: "一致性规则使用的归档 text/number source；number 的值由服务读取，不由模型填写" },
        consistency_rules: { type: "array", items: consistencyRule, description: "声明与来源数值之间的一致性规则；当前支持 all_absolute_exceed" },
        parent_id: string("上一文稿版本id"),
        publication_status: { type: "string", enum: ["draft", "archived"] },
        review_status: { type: "string", enum: ["unreviewed"], description: "模型只能保存未复核草稿；reviewed/accepted 由经理界面或受控后端权限设置" },
      },
    } }),
    kind: "edit", argv: (input) => ["analysis-draft", "--spec", json(input.spec)],
  },
  "analysis-export": {
    description: "导出指定文稿版本为 Markdown 或 Excel 工作簿，包含其结果和依据。mode=management 为管理阅读版；mode=audit 附加审计质量与证据记录。草稿可直接导出；导出不自动标记为经理认可或正式归档。stdout 为导出记录 JSON。",
    parameters: object({ draft: string("analysis-draft 返回的文稿版本id"), format: { type: "string", enum: ["md", "xlsx"] }, mode: { type: "string", enum: ["management", "audit"], description: "可选导出模式；默认 management" } }, ["draft", "format"]),
    kind: "edit", argv: (input) => ["analysis-export", "--draft", input.draft, "--format", input.format, ...(input.mode === undefined ? [] : ["--mode", input.mode])],
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

function runtimeParts(runtime) {
  return typeof runtime === "function" ? { analysis: runtime } : (runtime ?? {});
}

function foundryArgs(tool, input) {
  const args = SPECS[tool].argv(input);
  if (tool !== "save_explanation_draft" || !input?._completion_operation) return args;
  if (!input?._completion_call_id) throw new Error("save_explanation_draft completion call id is required");
  const [command, ...rest] = args;
  return [
    command,
    "--completion-operation", String(input._completion_operation),
    "--completion-call-id", String(input._completion_call_id),
    ...rest,
  ];
}

export function definitions(runtime, invoke = invokeFoundry) {
  const declared = PROFILE.tools;
  if (!Array.isArray(declared) || !declared.length || declared.length !== Object.keys(SPECS).length
      || declared.some((tool) => !Object.hasOwn(SPECS, tool))) {
    throw new Error("analysis tool metadata drifted from package.json");
  }
  const parts = runtimeParts(runtime);
  return declared.map((tool) => {
    const run = (input, exec) => SPECS[tool].runtime
      ? (parts.analysis ? parts.analysis(tool, input, exec) : Promise.reject(new Error("analysis runtime is unavailable")))
      : invoke(foundryArgs(tool, input), exec);
    return toolDefinition(tool, {
      ...SPECS[tool], requireSession: true,
      execute: (input, exec) => parts.completion
        ? parts.completion(tool, input, exec, run)
        : run(input, exec),
    });
  });
}

export function allowlist() {
  return [...PROFILE.tools, ...PROFILE.harnessTools];
}

export function apply(ctx) {
  const runtime = {
    analysis: createAnalysisRuntime(ctx, PROFILE.childTools),
    completion: createCompletionRuntime(ctx),
  };
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
