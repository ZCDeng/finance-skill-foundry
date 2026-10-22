const text = (description) => ({ type: "string", description });
const boundedText = (maximum, description, minimum = 0) => ({ type: "string", minLength: minimum, maxLength: maximum, description });
const closedObject = (properties, required = []) => ({ type: "object", properties, required, additionalProperties: false });
export const PERIOD_BINDING = closedObject({
  mode: { type: "string", enum: ["current"] },
  parameters: { type: "array", minItems: 1, uniqueItems: true, items: { oneOf: [
    { type: "string", minLength: 1 }, { type: "integer", minimum: 1 },
  ] }, description: "SQL 中明确跟随本期的参数键，或从1开始的位置；比较期参数不要列入" },
  filter_fields: { type: "array", minItems: 1, uniqueItems: true, items: { type: "string", minLength: 1 }, description: "结构化聚合中现有 eq 期间筛选字段" },
}, ["mode"]);
PERIOD_BINDING.description = "显式声明本期随已确认任务/资料期间解析。SQL用parameters，聚合用filter_fields；脚本仅写mode=current，通过FOUNDRY_CONTEXT指向的只读JSON读取period。未知或冲突期间拒绝执行，不用今天日期猜测。";
// Text limits are per field; the service also checks the combined layout density.
const visualCommon = {
  version: { type: "integer", enum: [1] },
  title: boundedText(160, "图题；写清比较对象和期间，不填事实模板占位符", 1),
  takeaway: boundedText(300, "图后的一句有依据的结论；不把相关性写成因果，不填事实模板占位符"),
};
const reportVisual = { oneOf: [
  closedObject({
    ...visualCommon,
    kind: { type: "string", enum: ["bar", "line"] },
    chart_id: { type: "string", pattern: "^[0-9a-f]{32}$", description: "chart_deliverable_save 返回的当前任务归档图 id；只用成功运行" },
    category: boundedText(200, "归档系列中非空且唯一的类别列；line 须由运行按时间顺序排列", 1),
    value_columns: { type: "array", minItems: 1, maxItems: 3, uniqueItems: true, items: { type: "string", minLength: 1, maxLength: 200 }, description: "原运行的 1–3 个可比较数值列，不传手填数值；bar 行数×系列数（含缺失位置）最多 12、line 最多 24 行，不静默截断" },
    unit: boundedText(40, "共同展示单位，如万元；仅声明，不换算数据，不混用金额和比率", 1),
  }, ["version", "kind", "title", "chart_id", "category", "value_columns", "unit"]),
  closedObject({
    ...visualCommon,
    kind: { type: "string", enum: ["flow"] },
    source_label: boundedText(200, "解释来源，默认作者分析；不能伪装为计算证据"),
    steps: { type: "array", minItems: 2, maxItems: 6, items: closedObject({
      label: boundedText(60, "步骤名称", 1),
      detail: boundedText(140, "步骤说明；假设或判断明确标识"),
      connector: boundedText(40, "与下一步的关系；最后一步必须为空"),
    }, ["label"]) },
  }, ["version", "kind", "title", "steps"]),
] };
const reportSourceAttrs = {
  source_id: { type: "string", pattern: "^[0-9a-f]{32}$", description: "已在 sources 声明的当前任务文档来源 id" },
  ...Object.fromEntries(["page", "sheet", "range"].map(key => [key, boundedText(120, "原资料定位")])),
};
const reportMark = { oneOf: [
  closedObject({ type: { type: "string", enum: ["bold", "italic", "strike", "code", "underline"] } }, ["type"]),
  closedObject({ type: { type: "string", enum: ["link"] }, attrs: closedObject({
    href: { type: "string", maxLength: 1000, pattern: "^(?:(?:https?|mailto):[^\\s]+|#[A-Za-z0-9_.:-]+)$" },
  }, ["href"]) }, ["type", "attrs"]),
] };
const reportImage = closedObject({
  type: { type: "string", enum: ["image"] },
  attrs: closedObject({ ...reportSourceAttrs,
    src: { type: "string", maxLength: 2097152, pattern: "^data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\\r\\n]+$", description: "已有受控 PNG/JPEG；不传文件路径、外部图片或 SVG" },
    alt: boundedText(300, "图片替代文字"), title: boundedText(300, "图片标题"),
  }, ["src"]),
}, ["type", "attrs"]);
const reportRef = (name) => ({ $ref: `#/properties/spec/properties/document/$defs/${name}` });
const reportInline = { oneOf: [
  closedObject({ type: { type: "string", enum: ["text"] }, text: boundedText(1000000, "正文文字；可用 {{fact:FACT_ID}}"), marks: { type: "array", items: reportMark } }, ["type", "text"]),
  closedObject({ type: { type: "string", enum: ["hardBreak"] } }, ["type"]),
  reportRef("image"),
] };
const reportParagraph = closedObject({
  type: { type: "string", enum: ["paragraph"] }, attrs: closedObject(reportSourceAttrs),
  content: { type: "array", items: reportRef("inline") },
}, ["type"]);
const reportList = closedObject({
  type: { type: "string", enum: ["bulletList", "orderedList"] },
  content: { type: "array", items: closedObject({
    type: { type: "string", enum: ["listItem"] },
    content: { type: "array", items: { oneOf: [reportRef("paragraph"), reportRef("list")] } },
  }, ["type", "content"]) },
}, ["type", "content"]);
const reportCell = closedObject({
  type: { type: "string", enum: ["tableCell", "tableHeader"] },
  attrs: closedObject({ ...reportSourceAttrs,
    colspan: { type: "integer", minimum: 1, maximum: 100 }, rowspan: { type: "integer", minimum: 1, maximum: 100 },
    colwidth: { type: "array", items: { type: "integer", minimum: 1, maximum: 2000 } },
    textAlign: { type: "string", enum: ["left", "center", "right", "justify"] },
  }), content: { type: "array", items: { oneOf: [reportRef("paragraph"), reportRef("inline")] } },
}, ["type"]);
// Model-authored reports use the existing document AST. Visual evidence fields
// (series, run_id, snapshot_hash, source_label) are resolved by the service.
export const REPORT_DOCUMENT = closedObject({
  schema_version: { type: "integer", enum: [1] },
  template_version: { type: "string", enum: ["annual-v1"] },
  template_id: text("可选已有文稿模板 id"),
  metadata: closedObject(Object.fromEntries(["ledger", "organization", "company", "period", "currency", "unit"].map(key => [key, boundedText(300, "文稿声明口径")])), []),
  sources: { type: "array", items: closedObject({
    id: { type: "string", pattern: "^[0-9a-f]{32}$" }, name: boundedText(300, "当前任务已登记文档名", 1),
    sha256: { type: "string", pattern: "^[0-9a-f]{64}$" },
    format: { type: "string", enum: ["docx", "pdf", "html", "md", "xlsx"] },
  }, ["id", "name", "sha256", "format"]) },
  content: { type: "array", maxItems: 20000, items: { oneOf: [
    reportRef("paragraph"),
    closedObject({ type: { type: "string", enum: ["heading"] }, attrs: closedObject({ ...reportSourceAttrs, level: { type: "integer", minimum: 1, maximum: 6 } }), content: { type: "array", items: reportRef("inline") } }, ["type"]),
    reportRef("list"),
    closedObject({ type: { type: "string", enum: ["blockquote", "codeBlock"] }, content: { type: "array", items: { oneOf: [reportRef("paragraph"), reportRef("inline")] } } }, ["type", "content"]),
    closedObject({ type: { type: "string", enum: ["table"] }, attrs: closedObject({ ...reportSourceAttrs, ...Object.fromEntries(["caption", "period", "currency", "unit"].map(key => [key, boundedText(300, "表格声明口径")])) }), content: { type: "array", items: closedObject({ type: { type: "string", enum: ["tableRow"] }, content: { type: "array", items: reportRef("cell") } }, ["type", "content"]) } }, ["type", "content"]),
    reportRef("image"),
    closedObject({ type: { type: "string", enum: ["reportNote"] }, attrs: closedObject({ ...reportSourceAttrs, id: boundedText(80, "附注编号", 1) }), content: { type: "array", items: { oneOf: [reportRef("paragraph"), reportRef("inline")] } } }, ["type", "content"]),
    closedObject({ type: { type: "string", enum: ["horizontalRule", "reportPageBreak"] } }, ["type"]),
    closedObject({ type: { type: "string", enum: ["reportVisual"] }, attrs: closedObject({ visual: reportVisual }, ["visual"]) }, ["type", "attrs"]),
  ] } },
}, ["schema_version", "template_version", "content"]);
REPORT_DOCUMENT.$defs = { inline: reportInline, paragraph: reportParagraph, list: reportList, cell: reportCell, image: reportImage };
REPORT_DOCUMENT.description = "可选结构文稿，服务据此生成正文；每稿最多 20 个 reportVisual，图内文字过密需缩短或拆图；数量图只引用 chart_id 和列名，禁止手填 series/rows、SVG、HTML 或任意路径。图题/结论用已核验的文字；正文 text 节点可用事实占位符。";
export const NUMERIC_PRESENTATION = {
  type: "object",
  additionalProperties: false,
  required: ["decimal_places", "scale", "rounding"],
  description: "可选数字展示规则；须绑定真实 fact_id 并保留精确 value。服务据事实计算展示值，不接受自由填写展示数字或改变单位、符号。",
  properties: {
    decimal_places: { type: "integer", minimum: 0, maximum: 6 },
    scale: { type: "string", enum: ["identity", "percent"], description: "identity 保留原单位；percent 仅适用于事实明确为比率的值" },
    rounding: { type: "string", enum: ["half_up"] },
  },
};
const specTool = (command, description, properties, required = []) => ({
  description,
  parameters: { type: "object", required: ["spec"], additionalProperties: false,
    properties: { spec: { type: "object", required, properties, additionalProperties: true } } },
  kind: ["drilldown-fact", "open-source-locator", "finance-controls-propose", "finance-controls-list", "workbook-inspect", "workbook-read", "prepare-explanation", "validate-explanation", "finance-background-list", "analysis-requirements-list", "finance-adjustment-list", "report-template-list", "structure-proposal-list", "structure-template-list", "answer-cards"].includes(command) ? "read" : ["run-metric", "explain-variance", "finance-scenario-run", "finance-controls-run", "collection-run"].includes(command) ? "execute" : "edit",
  argv: ({ spec }) => [command, "--spec", JSON.stringify(spec)],
});
const contextId = text("list_finance_context 或 finance_context_save 返回的当前任务口径版本 id");
const runId = text("analysis-run、analysis-script、run_metric、explain_variance 或 finance_scenario_run 返回的真实成功运行 id");
const financeScope = {
  type: "object",
  properties: Object.fromEntries(["ledger", "organization", "period", "currency", "unit"].map(key => [key, text("当前授权财务范围的" + key)])),
  additionalProperties: true,
};
const financeBasis = { type: "string", enum: ["source_fact", "external_reference", "user_assumption", "professional_judgment"] };
const statusFilter = {
  type: "object",
  description: "账龄状态筛选，由来源适配或经理口径声明；工具不写死企业状态含义。",
  properties: {
    field: text("状态字段名，如 invoice_status"),
    include: { type: "array", items: { type: "string" }, description: "只纳入这些规范状态" },
    exclude: { type: "array", items: { type: "string" }, description: "剔除这些规范状态" },
    mapping: { type: "object", additionalProperties: { type: "array", items: { type: "string" } }, description: "规范状态到来源值的映射；未命中会标记 unknown" },
  },
  additionalProperties: true,
};
const scenarioInputs = {
  type: "object",
  properties: {
    invoices_alias: text("应收发票资料别名"),
    activity_alias: text("核销/收款/减项活动资料别名"),
    as_of: text("账龄截止日 YYYY-MM-DD"),
    scope: financeScope,
    buckets: { type: "array", items: { type: "object" } },
    status_filter: statusFilter,
    opening_cash: text("13周现金期初余额"),
    start_date: text("13周现金起始日期"),
    actual_cutoff: text("实际收付截止日"),
    receipts_alias: text("收款资料别名"),
    payments_alias: text("付款资料别名"),
    scenario: { type: "object" },
    drivers: { type: "array", items: { type: "object" } },
    entities: { type: "array", items: { type: "object" }, description: "仅 collection_health：[{name, values:{输入名:{alias, match:{列名:文本} 或 source_row, column, scale?:percent|fraction, unit?}}, sensitivity?}]。输入名：revenue、cost 或 gross_profit、period_expense、gross_margin/expense_ratio（套表直接报比率时）、collection_rate_current（本年账单收缴率）、collection_rate_total（综合收缴率）、revenue_py（上年同期累计）、revenue_py_full（上年全年）、revenue_ttm、ar_end、ar_begin、contract_assets_end、contract_assets_begin、impairment、cash_from_sales、ar_gross、provision、ar_over_1y、related_ar、related_provision、ar_collected、ar_gross_begin、ar_new；全年按去年节奏估计用 net_profit、net_profit_py、net_profit_py_full、net_profit_le、revenue_le、impairment_py_full，months_elapsed（1–12）给线性外推对照；有 revenue_budget_full（全年收入预算，套表没有就请经理给数，按手填数注明）时算全年收入预算还差，再有 months_elapsed 时算剩余月份每月需完成收入；规模续约人效用 area_begin、area_end、area_exit、area_nonrenewal、contract_revenue、revenue_at_risk、billed_exiting、collected_exiting、billed_staying、collected_staying、headcount；风险雷达另读 operating_profit、revenue_budget_full、collection_rate_current_py；加 _py 后缀为上年同期。取数也可写 {alias, column, sum_where:{列名:文本或[文本]}, require_columns?:[列名]}，按条件对台账某列求和（只限金额和人数）；收缴率的分子分母给同样的 require_columns，保证读同一批行。风险雷达是筛查分，不计入月结。主体写 sensitivity: true 时为它算敏感性表（毛利率 × 收缴率 → 距生死线），看板和对话里的敏感性表读它。裸数字按手填数处理并在结果中注明。" },
    entity_tables: { type: "array", items: { type: "object" }, description: "仅 collection_health：明细表每行一个主体，[{alias, name_column, columns:{输入名: 列名 或 {column, scale}}, exclude?:[\"合计\"], name_prefix?}]；名称为空的行视为分组标题跳过。" },
    params: { type: "object", description: "仅 collection_health：vat_factor（默认 1.06）与筛查阈值。" },
    values: { type: "object" },
    manager_assumptions: { type: "object" },
  },
  additionalProperties: true,
};
const evidenceSource = {
  type: "object",
  required: ["dataset_id", "source_hash", "sheet", "range"],
  additionalProperties: false,
  properties: {
    dataset_id: text("授权资料快照 id；必须属于当前任务/会话"),
    source_hash: text("资料原始文件 SHA-256；必须匹配归档快照"),
    sheet: text("工作表名"),
    range: text("有界 A1 矩形，例如 B36:I39；后端不接受整列/整行，最大200行、40列、8000格"),
  },
};
const evidenceClaim = {
  type: "object",
  required: ["run_id", "row", "column"],
  additionalProperties: false,
  properties: { run_id: runId, row: { type: "integer", minimum: 0 }, column: text("被核验的结果列名；expected 由该运行单元格读取，不由模型填写") },
};
const evidenceRecipe = {
  type: "object",
  description: "服务端按归档工作簿重新复算，结果只由服务端认定，调用方的 evidence_report 不被采信。金额类要求（比率、只要比率情景的项、数量、人数、面积等以外的一切指标，认不出的名称也算金额）：脚本或 SQL 结果须有通过的 direct（来源原值）或 sum/diff（来源计算）且 scale 为 1 或千/万/百万/亿单位换算、来源在要求绑定快照内、claim 指向本稿已引用的单元格，才计为已回答；ratio 规则永远不能证明金额；带 factor_recipe_id 只计为估算；其他 scale 只证明乘法，不计入。精确比对不放宽：运行结果须保存完整精度，被舍入的值会失败并带 precision_hint；除不尽的比值和估算至少保留 28 位有效数字，按精确有理数比对。",
  required: ["kind", "claim"],
  additionalProperties: false,
  oneOf: [
    { required: ["kind", "claim", "dataset_id", "source_hash", "sheet", "range"], properties: { kind: { enum: ["direct", "sum"] } }, not: { anyOf: [{ required: ["left"] }, { required: ["right"] }] } },
    { required: ["kind", "claim", "left", "right"], properties: { kind: { enum: ["diff", "ratio"] } }, not: { anyOf: [{ required: ["dataset_id"] }, { required: ["source_hash"] }, { required: ["sheet"] }, { required: ["range"] }, { required: ["factor_recipe_id"] }] } },
  ],
  properties: {
    id: text("稳定 recipe id，同一文稿内唯一；省略时服务按顺序生成 recipe-N"),
    label: text("给财务经理看的检查名称；省略时使用 id"),
    kind: { type: "string", enum: ["direct", "sum", "diff", "ratio"] },
    ...evidenceSource.properties,
    left: evidenceSource,
    right: evidenceSource,
    scale: text("可选 Decimal 缩放，默认 1；只有 1 或千/万/百万/亿的单位换算（如元→万元 0.0001）能让金额计为来源证据，其他系数只证明乘法、不计入要求覆盖"),
    factor_recipe_id: text("仅 direct/sum 估算可选：引用本批次已由归档数值范围独立复算通过的 ratio recipe；需同一 business_key.metric_key 与 period；同时写 scale 时只能是 1 或千/万/百万/亿单位换算（来源以元计、结果以万元计时写 0.0001），系数只写在被引用的 ratio 规则里。结果只计为估算，且只对要求 grain_basis 声明为 estimate 的组合有效，永不计为已回答"),
    anchors: { type: "object", maxProperties: 4, additionalProperties: text("同一工作表的单个 A1 单元格"), description: "可选：来源区域旁的行标签、列表头单元格，如 {row_label:\"A12\", column_header:\"I3\"}；只供经理复核展示，不影响复算结果" },
    unit: text("展示单位"),
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
    id: text("稳定 source id，供 consistency_rules 引用"),
    label: text("展示标签"),
    kind: { type: "string", enum: ["number", "text"] },
    dataset_id: text("授权归档资料快照 id"),
    source_hash: text("资料原始文件 SHA-256；必须匹配归档快照"),
    sheet: text("归档工作簿 sheet；number source 必填，text source 可用单格 sheet/range 代替 paragraph"),
    range: text("归档工作簿有界范围；number source 可为单格或区域，text source 只能是单格；模型不能填写 value/original_text"),
    paragraph: { type: "integer", minimum: 1, description: "text source 的归档段落号；与 sheet/range 二选一" },
    scale: text("number source 可选 Decimal 缩放，默认 1"),
  },
};
const consistencyRule = {
  type: "object",
  required: ["id", "kind", "threshold", "asserted_result", "assertion_source_id", "values"],
  additionalProperties: false,
  properties: {
    id: text("稳定规则 id"),
    label: text("展示标签"),
    kind: { type: "string", enum: ["all_absolute_exceed"] },
    threshold: text("Decimal 阈值；按绝对值比较"),
    asserted_result: { type: "boolean", description: "正文声明的判断结果" },
    assertion_source_id: text("声明文本所在的 consistency source id；必须是归档 text source"),
    values: { type: "array", minItems: 1, items: { type: "object", additionalProperties: false, required: ["id"], oneOf: [{ required: ["source_id"] }, { required: ["recipe_result_id"] }], properties: { id: text("值 id"), label: text("展示标签"), source_id: text("归档 number source id；服务读取真实数值"), recipe_result_id: text("也可引用 evidence_recipes 的 recipe_id/result_id") } } },
  },
};

export const FINANCE_TOOLS = {
  analysis_requirements_list: specTool("analysis-requirements-list", "读取当前任务已登记的分析要求及版本；先于选择文稿引用确认哪些问题必须回答。", {}),
  analysis_requirements_save: specTool("analysis-requirements-save", "计算前登记用户要求：问题、范围、必答指标、逐一覆盖的结果情景和指定下钻对象。更新必须带当前parent_id，移除项必须说明change_reason，不代表原问题已经完成。返回support由绑定快照核验；requires_input应补资料或字段映射，不能补零；support.items 的 accepted_evidence/blocked_evidence 说明哪些依据现在能回答、哪些被什么阻塞。scope.unit 与 currency 只约束金额类要求，ratio 项不套用；scope.ledger 由绑定快照哈希证明，不要求抄到结果行。因维度被拒收时，错误信息里的 suggested_items 可原样重新提交；上一版已有、原样沿用的下钻层级（逐个键比较）会在新版中去掉，并记在 authoring_warnings；去掉下钻层级和删除要求项一样，原始要求记为未完成，completion 以 hierarchy_dimension_dropped 写明。scope 里的 drilldown（或 drill_down）下钻层级同样拒收（错误里的 suggested_scope 可原样重提）；scope.granularity（粒度）只作口径说明，不约束结果行。", {
    question: text("用户要回答的管理问题"), context_id: contextId, scope: financeScope,
    bindings: {type:"object", additionalProperties:{type:"string"}}, parent_id: text("当前要求版本id"), change_reason: text("范围或要求调整原因"),
    items: {type:"array", items:{type:"object", required:["id","metric"], properties:{id:text("稳定要求标识"),metric:text("规范语义键，如profit/revenue/cost/expense/ratio/control_totals/price_quantity、单一科目代码或实际结果列名；不要把公式放入metric，公式放label，分解方法放dimensions.method，精确运行行指标键放dimensions.metric_key"),label:text("用户可读的要求"),dimensions:{type:"object",description:"结果行必须逐字带着的过滤字段，如 metric_key、management_account、product，以及 method/dimension/scenario_compare 意图；drilldown（或 drill_down）是下钻层级、不是维度，保存会被拒收（名为 level、group_by 等的键仍按结果行字段过滤）：把下钻对象逐一列入 organizations 或另立要求项，逐格来源核查用 requires_drilldown"},periods:{type:"array",items:text("要求完整覆盖的期间，例如2026-01:2026-08或2026-08"),description:"每个期间都须有结果；多期间时清空scope.period；dimensions.period仅接受单个期间"},organizations:{type:"array",items:text("须逐一覆盖的组织，例如集团合并或华东"),description:"每个组织与每个期间都须有结果；多组织时清空scope.organization"},scenarios:{type:"array",items:text("须逐一覆盖的结果情景键，例如actual_ytd、budget_ytd、achievement_ratio"),description:"每个组织、期间与情景都须有对应结果；按运行结果的scenario原值填写，不从显示名称猜测"},requires_drilldown:{type:"boolean"},grain_basis:{type:"array",description:"可选：声明源表没有直接数的组合。basis=estimate 须写 method，只有这些组合接受带 factor_recipe_id 的估算，并且只计为估算；系数无法用现有规则复算时写 factor_reproducible:false 与 reason，组合停在待定并交经理，不得换用其他系数凑数。basis=unavailable 须写 reason，经理确认前不算缺数。organizations/periods/scenarios 为本项列表的子集，省略表示全部",items:{type:"object",required:["basis"],properties:{basis:{type:"string",enum:["estimate","unavailable"]},organizations:{type:"array",items:{type:"string"}},periods:{type:"array",items:{type:"string"}},scenarios:{type:"array",items:{type:"string"}},method:text("估算方法，如 区域全年预算 × 集团1-8月预算进度"),factor_reproducible:{type:"boolean"},reason:text("原因")}}}}}},
  }, ["question","items"]),
  finance_source_list: {
    description: "列出当前会话已授权的文件刷新批次、变化摘要与快照。重复批次不会产生重复数据。旧运行固定原快照；需要更新分析时显式保存新口径。没有真实 ERP 授权时只说明文件或适配合同能力。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["finance-source-list"],
  },
  finance_source_refresh: specTool("finance-source-refresh", "把已上传的新文件按明确来源范围刷新为不可变快照。path仅限当前任务工作区。普通余额/预算导出使用snapshot_only，只报告整表变化；有真实单据/行ID时可用business_key。不重绑旧结果、不猜删除记录，也不向ERP写入。", {
    path: text("当前任务中已授权的上传文件"), name: text("资料名称"), product: text("实际来源产品名称，未知时file"), version: text("实际产品版本，文件可填export"),
    scope: { type: "object", properties: Object.fromEntries(["source_id", "tenant_id", "ledger_id", "organization_id", "period", "currency", "cutoff_at", "calendar"].map(key => [key, text("经理或来源资料声明的" + key)])), required: ["source_id", "tenant_id", "ledger_id", "organization_id", "period", "currency", "cutoff_at"] },
    metadata: { type: "object" }, file_identity_policy: { type: "string", enum: ["snapshot_only", "business_key"] },
  }, ["path", "scope"]),
  workbook_inspect: specTool("workbook-inspect", "检查已授权XLSX快照的工作表、命名区域、表与复杂特性；选择稳定绑定范围前先检查。不能读取任意本机文件。", { dataset_id: text("已登记XLSX快照id") }, ["dataset_id"]),
  workbook_bind: specTool("workbook-bind", "保存Excel命名表/区域的输入或结果绑定版本。source按workbook_inspect返回的定位；fields声明列名、类型、单位。结果区仅在经理明确授权时writable=true。复杂原件生成独立结果工作簿。", {
    dataset_id: text("已登记XLSX快照id"), source: { type: "object", properties: { kind: { type: "string", enum: ["table", "named_range", "range"] }, name: text("命名表/区域名称"), sheet: text("工作表名"), range: text("矩形范围，例如A1:C10") } },
    fields: { type: "array", items: { type: "object", properties: {name: text("列名"), policy: {type:"string", enum:["text","identifier","amount","decimal"]}, unit: text("金额单位")}, required:["name"] } }, role: { type: "string", enum: ["input", "output"] }, writable: { type: "boolean" }, header: { type: "boolean" }, parent_id: text("可选父绑定版本id"),
  }, ["dataset_id", "source", "fields"]),
  workbook_read: specTool("workbook-read", "读取已保存绑定的输入；可传更新后的XLSX快照，保持旧绑定与旧成果。", { binding_id: text("绑定版本id"), dataset_id: text("可选新XLSX快照id") }, ["binding_id"]),
  workbook_range_preview: specTool("workbook-range-preview", "只读预览已授权XLSX快照的工作表范围，用于确定表头、总计行、证据recipe范围或绑定区域。必须传 dataset_id 和 sheet；range 可选但必须是有界A1范围；不读取任意本机文件，不写入工作簿。", {
    dataset_id: text("已登记XLSX快照id"), sheet: text("工作表名"), range: text("可选有界A1矩形，例如 B36:I39；省略时由后端返回安全预览窗口"),
  }, ["dataset_id", "sheet"]),
  workbook_preview: specTool("workbook-preview", "预览限定区域的Excel结果写入。writes每项包含field、value以及cell或从1开始的row；引用计算结果时附run_id及result_row/result_column。显示经理修改冲突与数值精度策略，保存patch_id后再应用。", {
    binding_id: text("结果绑定id"), dataset_id: text("可选更新后的XLSX快照"), run_id: text("可选真实运行id"),
    writes: { type: "array", items: { type: "object", properties: { cell: text("目标单元格地址"), field: text("绑定字段名"), row: {type:"integer", minimum:1}, value: {}, result_row: { type: "integer", minimum: 0 }, result_column: text("真实结果列名") }, required: ["field", "value"] } },
  }, ["binding_id", "writes"]),
  workbook_apply: specTool("workbook-apply", "应用已保存且未失效的Excel预览，生成新工作簿并返回路径/哈希。resolutions按冲突单元格声明经理选择keep或apply。原快照不覆盖；不要擅自代替经理决定冲突。", {
    patch_id: text("workbook_preview返回的patch_id"), resolutions: { type: "object", additionalProperties: { type: "string", enum: ["keep", "apply"] } },
  }, ["patch_id"]),
  finance_scenario_save: specTool("finance-scenario-save", "保存账龄、13周现金、驱动或回款健康情景。kind=receivables_aging 的 inputs 含 invoices_alias、activity_alias、as_of、scope；账龄支持 inputs.status_filter={field,include,exclude,mapping}，按来源或经理声明映射状态；筛选保留 rows/detail_rows/excluded_detail_rows 的稳定键、as_of、纳入/剔除余额与来源，不能把当前状态声称为截止日历史状态；kind=cash_13_weeks 含 opening_cash、start_date、actual_cutoff、scope 和可选 receipts_alias/payments_alias/scenario.delay_receipts_days。scope明确单一ledger/organization/currency/unit。驱动模型 kind=driver_model，inputs.drivers 声明公式和depends_on、values或manager_assumptions。回款健康 kind=collection_health，inputs.entities 或 inputs.entity_tables 按单元格取数，算毛利率、期间费用率、生死线收缴率（1−毛利率+期间费用率）及距生死线、近12个月收入、应收天数、应收蓄水率、反推回款率、现金回收比、减值占毛利和拨备结构，以及按去年节奏的全年收入和净利润、LE 偏离和去年减值进度（线性外推只作对照，不进结论）；每行带公式、红黄绿筛查、估算标记和来源单元格，缺输入的指标跳过并列出，不猜。创建子情景只用parent_id、changes和label，保留父输入。没有支付或过账能力。", {
    context_id: contextId, kind: { type: "string", enum: ["receivables_aging", "cash_13_weeks", "driver_model", "collection_health"] }, inputs: scenarioInputs, label: text("经理可辨认的情景名称"), parent_id: text("父情景id"), changes: { type: "object", description: "替换指定输入键；如 {scenario:{delay_receipts_days:14}}" },
  }, ["label"]),
  finance_scenario_run: specTool("finance-scenario-run", "计算已保存财务情景并生成同源运行与来源依据。账龄以实际截止日核算，不引入未来收款；现金每周连续，延迟收款保留未来计划。账龄输出包含 rows、detail_rows 和 excluded_detail_rows，可用 drilldown_fact 的 section 参数下钻。输出可整理为经理可编辑草稿。", { scenario_id: text("finance_scenario_save 返回的id"), question: text("业务问题") }, ["scenario_id"]),
  list_finance_context: {
    description: "查看本任务已授权资料、财务口径、科目映射、指标定义及requirement_metric_catalog规范能力名。先检查现有可复用方法与已加载财务技能；没有专用口径可建立，或继续 SQL/Python。无需审批。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["list-finance-context"],
  },
  finance_readiness: {
    description: "只读检查当前任务已授权资料能否计算管理损益等能力：返回 proposed_scope、datasets、can_run、blocked、file_identity_policy。不写快照、不写口径。缺期间/币种或科目映射时列入 blocked，不填本月或币种。proposed_scope 只给所有文件一致的值，不一致就留空；每份文件各自的口径、缺什么、能算什么在 datasets 里，blocked 项带 dataset_id，要告诉经理是哪份文件缺什么，不要笼统说任务缺。未具名授权适配器时 erp_connected 为 false。不必先加载 setup；未加载 setup 不得拒绝 run_metric。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["finance-readiness"],
  },
  chart_deliverable_save: specTool("chart-deliverable-save", "把当前任务已授权 run 的结果系列归档为图表成果。需在文稿展示时，用返回 id 构造 document 的 reportVisual 节点（bar/line），视觉规格保存在文稿版本内。写入 FinanceStore charts 与 analysis/charts，绑定 run_id 与 snapshot hash。不得传入路径、预览句柄或 dataset_id。打开归档图复现原值，不重跑。改假设走子情景后再归档新版本。", {
    run_id: runId,
    parent_id: text("可选父图表版本"),
    label: text("图表名称"),
  }, ["run_id"]),
  dashboard_read: {
    description: "读本任务看板上的卡（只含本会话能读的运行）。卡不存数字，只记 run_id 和 select：读那次成功运行里 select.match 指的哪几行。state：explore 是助手提议、经理还没钉住；pinned 已在看板上、等经理认可；accepted 经理已认可。kind=scenario 的回款情景卡永远不认可。提议新卡前先读，看板上已有的同样的卡不要再提。只读。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["dashboard-read", "--spec", "{}"],
  },
  dashboard_repair_read: specTool("dashboard-repair-read", "读取经理已发起的跨月带入失败计算。只开放该次失败记录里的原算法与目标文件绑定，不返回原任务明细。按run_id合并9张卡的修复，保留原卡与原运行；还没发起带入时不能读取。", {
    run_id: runId,
  }),
  dashboard_repair_propose: specTool("dashboard-repair-propose", "提议修复已授权的跨月失败算法：只把写死本期改为period_binding，不能改指标口径或公式。服务先在隔离副本用原月快照验证列和结果逐行完全等价，再用目标月新资料运行；不一致拒绝。原任务和历史不变，结果仍需经理点「继续带入剩余卡」并重新认可；助手不能替经理认可。", {
    run_id: runId,
    spec: { type: "object", properties: {
      sql: text("使用期间参数的原公式SQL"), parameters: { oneOf: [{type: "object"}, {type: "array"}] },
      parameter_metadata: { type: "array", items: {type: "object"} }, aggregate_plan: { type: "object" },
      code: text("通过FOUNDRY_CONTEXT读取期间的原脚本"), period_binding: PERIOD_BINDING,
    }, required: ["period_binding"], additionalProperties: false },
  }, ["run_id", "spec"]),
  dashboard_propose: specTool("dashboard-propose", "在看板上提议一张卡，放进看板页「助手提议」，经理点「钉住」才上看板；认可只能经理在界面做。不要说卡已经上了看板或已认可。卡不存数字：读 run_id 那次成功运行里 select.match（列名 → 该列的文字）选中的行，数字和来源都来自那次运行。kind=figure 一个数：match 恰好选中一行，column 是数所在的列（回款健康运行用 value）。kind=rank 排名条：match 选出要排的行，column 是数值列，label 是每条的名字列（回款健康运行用 entity），order 为 asc 或 desc，limit 1–50，可选 reference {value,label} 画参考线（距生死线用 {value:'0',label:'生死线'}）。kind=bridge 利润桥：读 explain_variance 的预算或上期利润桥运行，match 选出含 profit 行的那一组。kind=scenario 回款情景卡：读回款健康运行（finance_scenario_run kind=collection_health），match 写 {entity: 主体名, scenario: '本期'}，经理在卡上拖收缴率看距生死线、现金经营利润和一年回款怎么变；卡上永远标「情景，不是实际数」，不能认可、不进月结和文稿。kind=goal 倒推卡和 kind=sensitivity 敏感性表同样读回款健康运行的一个主体，match 写 {entity: 主体名, scenario: '本期'}，同样标情景、不能认可：goal 加 goal=collection 看收缴率到目标一年要多收多少（可选 target，带 % 的文字如 '92%'，不写就是回到生死线），goal=budget 看全年收入预算还差多少、剩余月份每月要做到多少（运行里要有全年收入预算还差那两行）；sensitivity 读运行里该主体的敏感性表（算回款健康时给该主体写 sensitivity: true）。回款健康运行的行按 entity、metric_key、scenario（本期/上年同期/变动）区分，城市公司明细表的行带 entity_origin=table。「只看海口」「按城市公司拆开」这类说法只改 match 选哪些行，不改口径；要换口径、期间或资料，先按原流程算出新的运行（口径改动仍由经理确认），再用新的 run_id 提议。同一运行、同一种卡、同样的行，看板上已有时会被拒。", {
    card: { type: "object", required: ["kind", "title", "run_id", "select"], additionalProperties: false, properties: {
      kind: { type: "string", enum: ["figure", "rank", "bridge", "scenario", "goal", "sensitivity"] },
      title: boundedText(60, "卡片标题，经理看得懂的中文，写清看什么", 1),
      run_id: runId,
      select: { type: "object", description: "match（列名 → 文字，最多 8 列）；figure 加 column；rank 加 column、label、order、limit、可选 reference；goal 加 goal（collection 或 budget），collection 可选 target（如 '92%'）" },
      note: boundedText(200, "一句为什么值得看，可选"),
    } },
  }, ["card"]),
  answer_cards: specTool("answer-cards", "在回答下方画卡，经理一眼看到数、看来源、点「接着问」。回答的文字写完后最后调用一次，调用之后不再写字。最多 3 张卡、3 个接着问；一句话能答清的问题不画卡。卡上的数由服务从已经算好的成功运行里取出，按看板的写法显示，并带公式、资料和计算时间：你不写数字，也不在文字里重复卡上的数。kind=figure 一个数：run_id + select（写法同 dashboard_propose 的 figure：match 恰好选中一行，column 是数所在的列，回款健康运行用 value）；或收缴率运行 collection_run_id + figure（collection_rate_current 当期收缴率、arrears_recovery_rate 清欠率、collection_rate_total 综合收缴率、collection_rate_month 本月收缴率、waiver_rate 减免率、household_rate 交清的户占比，或金额 receivable、collected、month_receivable、month_collected、arrears_opening、arrears_collected、outstanding、advance_balance、waiver）+ 可选 group（分组运行里的一组，{列: 值}，如 {type: '洋房'}）；整体收缴率卡会带上套表报数和相差多少个百分点。kind=compare 2–4 个数并排：items 每项写法同 figure，不计算它们之间的差。kind=rank 排名条：run_id + select（写法同 dashboard_propose 的 rank），或分组的收缴率运行 collection_run_id + figure + order（asc/desc）+ 可选 limit、reference。kind=bridge 利润桥：explain_variance 的利润桥运行，select.match 选出含 profit 行的那一组。kind=trend 一条线随期间变化：run_id + select {match 选出同一条线各期的行, column 数所在的列, period 期间列名（默认 period）}，3–24 期。kind=goal 倒推卡：回款健康运行 run_id + select（写法同 dashboard_propose 的 goal），答「收缴率到 X% 一年要多收多少」「全年预算还差多少、每月要做到多少」；或收缴率运行 collection_run_id + target（带 % 的文字，如 '92%'）+ 可选 figure（collection_rate_current 默认、collection_rate_month、arrears_recovery_rate）、group，按账单算还要收多少，未分组时列出还要收得最多的几组。kind=sensitivity 敏感性表：回款健康运行 run_id + select {match: {entity, scenario: '本期'}}，毛利率和收缴率一起变时距生死线怎么变。倒推卡和敏感性表都标「情景，不是实际数」。follow_ups 写经理接下来最可能问的问题，每个 40 字以内，经理点了只填进对话框、由他改了再发。有一张卡画不出（行选错、运行没成功、分组不存在）整次被拒并说明原因，照原因改了再调。经理可以在卡上看来源、打开结果；读分析运行的数字卡、排名卡、利润桥、倒推卡和敏感性表可以由经理自己钉到看板：不要说卡已经钉上看板或已认可。只读，不改任何东西。", {
    cards: { type: "array", maxItems: 3, items: { type: "object", required: ["kind", "title"], properties: {
      kind: { type: "string", enum: ["figure", "compare", "rank", "bridge", "trend", "goal", "sensitivity"] },
      title: boundedText(60, "卡片标题，经理看得懂的中文，写清看什么", 1),
      run_id: runId,
      collection_run_id: text("collection_run 返回的收缴率运行 id"),
      select: { type: "object", description: "figure：match + column；rank：match + column + label + order + limit + 可选 reference；bridge：match；trend：match + column + 可选 period；goal：match + goal（collection 或 budget）+ 可选 target；sensitivity：match" },
      figure: text("收缴率运行的哪个数，如 collection_rate_current"),
      group: { type: "object", additionalProperties: { type: "string" }, description: "分组收缴率运行里的一组，{列: 值}" },
      items: { type: "array", minItems: 2, maxItems: 4, items: { type: "object" }, description: "compare：每项写法同 figure（run_id + select，或 collection_run_id + figure + 可选 group）" },
      order: { type: "string", enum: ["asc", "desc"] },
      limit: { type: "integer", minimum: 1, maximum: 50 },
      reference: { type: "object", description: "排名条的参考线 {value, label}；收缴率排名的 value 和运行里的率一样写小数（80% 写 0.8）" },
      target: text("收缴率运行倒推卡的目标收缴率，带 % 的文字，如 '92%'"),
    } } },
    follow_ups: { type: "array", maxItems: 3, items: boundedText(40, "经理接下来可能问的一个问题", 1) },
  }),
  month_brief: {
    description: "读任务页顶部的「本月三句话」：变化、风险、等你拍板各一句。规则从看板按新资料重算的卡、最近一次回款健康的风险雷达和月结待办里挑数，parts 里带 ref 的是数或能点开的字，经理在任务页上点开能看来源；worded 是改过的措辞，数没变时才有。经理问「这个月怎么样」「给我三句话」「本月要点」时先读它，回答以这三句的数为准，不另挑数、不另算。只读。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["month-brief"],
  },
  month_brief_word: specTool("month-brief-word", "改写「本月三句话」的措辞，经理在任务页顶部看到，原句随时能切回去看。先用 month_brief 读原句和 signature，lines 只写要改的几句（change、risk、waiting），没写的几句保留之前改过的措辞；每句一行、120 字以内。只改措辞：原句里带 ref 的部分（数、能点开的字）一字不改地保留，不加原句里没有的数字，不加原句没有的判断或建议。数一变，改写自动作废，要重新读再改；被拒时照原因改了再调。", {
    signature: text("month_brief 返回的 signature"),
    lines: { type: "object", additionalProperties: false, properties: {
      change: boundedText(120, "「变化」这一句的新措辞", 1),
      risk: boundedText(120, "「风险」这一句的新措辞", 1),
      waiting: boundedText(120, "「等你拍板」这一句的新措辞", 1),
    } },
  }, ["signature", "lines"]),
  finance_context_save: specTool("finance-context-save", "建立不可变财务口径：bindings 为别名到现有快照 ID；scopes 按别名声明 ledger/organization/period/currency/unit/scenario，值来自资料或经理明确口径，不能猜测。policy.field_map 可映射中文列名。管理科目用 revenue/cost/expense；余额也可分析，缺少凭证时不虚构分录链接。修改科目映射或口径生成新版本。", {
    name: text("财务口径名称"), bindings: { type: "object", additionalProperties: { type: "string" } },
    scopes: { type: "object", additionalProperties: { type: "object" } }, policies: { type: "object", additionalProperties: { type: "object" } },
    account_map_id: text("可选科目映射版本"), parent_id: text("可选父口径版本"),
  }, ["bindings", "scopes"]),
  finance_map_save: specTool("finance-map-save", "保存经理选定的管理科目映射版本。rows 每项为 account_code 和 management_account；支持 revenue/cost/expense。未映射与重叠项显示诊断；经理修订生成新版本，历史报告保留旧映射。", {
    name: text("映射名称"), rows: { type: "array", items: { type: "object", properties: { account_code: text("保留前导零"), management_account: text("管理科目") }, required: ["account_code", "management_account"] } }, parent_id: text("可选父映射"),
  }, ["rows"]),
  run_metric: specTool("run-metric", "在已保存财务口径上计算指标并保存真实 analysis run。metric.kind 可为 management_pnl、ratio、account_total、control_totals。ratio 必须声明 numerator_accounts 与 denominator_accounts，可用 account_signs 明确符号；返回精确值、display_value 与 semantics。金额以精确字符串返回；结果来源行可 drilldown_fact。默认账套/组织/期间/币种/单位/情景分开，经理明确允许才 aggregate_dimensions。检查 diagnostics，运行成功不代表账套完整或已核对。", {
    context_id: contextId, question: text("业务问题"), metric: { type: "object", properties: {
      kind: { type: "string", enum: ["management_pnl", "ratio", "account_total", "control_totals"] },
      dimensions: { type: "array", items: { type: "string" } }, scenario_bindings: { type: "object" }, filters: { type: "object" },
      numerator_accounts: { type: "array", items: { type: "string" }, description: "ratio 分子管理科目，如 cost" },
      denominator_accounts: { type: "array", items: { type: "string" }, description: "ratio 分母管理科目，如 revenue" },
      accounts: { type: "array", items: { type: "string" } },
      account_signs: { type: "object", additionalProperties: { type: "string" }, description: "按管理科目声明符号倍率，如 {cost:'1', revenue:'1'}" },
      aggregate_dimensions: { type: "boolean" },
    }, additionalProperties: true },
  }, ["context_id"]),
  explain_variance: specTool("explain-variance", "生成有来源的利润桥或量价拆分 run。利润桥明确实际/基准scenario和实际/基准filters；比较同一actual的当前/历史期间时分别填 actual_filters.period 与 baseline_filters.period。filters 不能按来源行、凭证或分录（source_row、doc_id、line_id）挑出一部分行，也不能与要求本身的组织、期间、情景或维度矛盾，否则这座桥不计为要求的依据；account_signs 只写 1 或 -1 说明科目符号，其他倍数会缩放整条科目，这样的桥不计入；实际与基准为同一情景、同一 filters 的桥也不计入。返回 amount_change 与 profit_impact，contribution 保留为 profit_impact 兼容字段；成本/费用增加为利润负影响。负预算的分母政策可选，零预算无比例。量价 kind=price_quantity 必须有数量价格，method=quantity_then_price 或 base_weights_with_interaction；只有金额不能推测量价。贡献是算术，业务原因另记经理判断。", {
    context_id: contextId, question: text("差异问题"), kind: { type: "string", enum: ["profit_bridge", "price_quantity"] }, actual_scenario: text("实际版本值"), baseline_scenario: text("基准版本值"), dimensions: { type: "array", items: { type: "string" } },
    method: { type: "string", enum: ["quantity_then_price", "base_weights_with_interaction"] }, field_map: { type: "object" }, actual_filters: { type: "object" }, baseline_filters: { type: "object" },
    negative_budget_policy: { type: "string", enum: ["absolute_baseline", "signed_baseline"] }, missing_groups_as_zero: { type: "boolean", description: "仅经理明确将缺失组按零处理时使用，资料缺失不能自行启用" },
  }, ["context_id"]),

  open_source_locator: specTool("open-source-locator", "按 fact_id 或 run_id/row/column 打开已授权原文定位与预览句柄。只读；不得传入 dataset_id、本机路径或 URL。无定位返回 locator_unavailable，越权返回 locator_forbidden。返回不含路径。", {
    fact_id: text("prepare_explanation 返回的事实 id"),
    run_id: runId,
    row: {type:"integer", minimum:0, description:"结果行下标，从0开始"},
    column: text("结果列名，如 expense"),
  }),
  drilldown_fact: specTool("drilldown-fact", "从当前任务真实 run 的结果行/列下钻到原始快照行。row 是所选 section 的下标（从0开始），section 可为 rows、detail_rows 或 excluded_detail_rows；返回精确 source_hash 和原始数据，不搜索其他账套或最新快照。余额资料无凭证链接；分页最多1000行。", {
    run_id: runId, section: { type: "string", enum: ["rows", "detail_rows", "excluded_detail_rows"] }, row: { type: "integer", minimum: 0 }, column: text("可选结果列"), offset: { type: "integer", minimum: 0 }, limit: { type: "integer", minimum: 1, maximum: 1000 },
  }, ["run_id", "row"]),
  prepare_explanation: specTool("prepare-explanation", "为财务解释准备稳定 fact id、精确值、展示值、scope、semantics、evidence_groups、自动附表和适用业务背景。先登记分析要求，再只读取能回答要求的当前授权成功 run；用于让模型选择事实而不是手写 run/row/column。新问题或新资料必须使用新 run_ids，不要用旧 claim 掩盖新的运行变化。示例：{run_ids:[run.id], materiality:{absolute:'10'}}。", {
    run_ids: { type: "array", minItems: 1, items: runId }, materiality: { type: "object", properties: { absolute: text("绝对重要性阈值") }, additionalProperties: true },
  }, ["run_ids"]),
  validate_explanation: specTool("validate-explanation", "检查当前说明正文与事实引用、已登记分析要求、来源追溯、独立 evidence_recipes 和自动附表是否一致：数字、方向、单位、舍入展示和缺失引用。可传 draft_id，或传未保存的 body/run_ids/fact_ids/claims/evidence_recipes/consistency_sources/consistency_rules。evidence_recipes 由服务端重新复算，传入的 evidence_report 不被采信。检查不代表经理认可，也不阻止保存普通草稿；区域均值、行业估计等只能作为 user_assumption/external_reference 单独列示，不可混成直接来源事实。", {
    require_all_material_facts: { type: "boolean", description: "检查全部重要行是否引用；正文通常只需当前问题相关事实" }, draft_id: text("可选已保存文稿 id"), body: text("未保存正文"), run_ids: { type: "array", items: runId }, fact_ids: { type: "array", items: { type: "string" } }, claims: { type: "array", items: { type: "object" } }, evidence_recipes: { type: "array", items: evidenceRecipe },
    consistency_sources: { type: "array", items: consistencySource }, consistency_rules: { type: "array", items: consistencyRule },
  }),
  save_explanation_draft: specTool("save-explanation-draft", "保存可由经理自由编辑的说明。优先使用 prepare_explanation 返回的 fact_ids 或 {{fact:FACT_ID}}；金额行的 {{fact:FACT_ID}} 原样保留；比率行和 %、pct、百分比行不用占位符，手写百分数，claim 写全 basis=calculation、run_id、row、column、value、fact_id 和 presentation（比率行 scale=percent，%、pct、百分比行 scale=identity）；手写数字用千分位；服务会补齐精确 claims 并返回 quality 与 completion。内部草稿引用协议仅用于原生输入：[[FA_FOUNDRY_DRAFT_REF:{\"draftId\":\"...\",\"revision\":N}]]；正文中不得展示 raw draftId，应显示“基于修订 N”。completion 中 repair_allowed、stop_reason=no_progress 和最多两轮修复预算用于继续或停止自动收尾。awaiting_input和verified_input_gap表示绑定快照已核验资料缺口，本轮答复可结束但原分析要求仍未完成；不要重复运行同一缺资料计算。每个计算数字 claim 引用 run_id、row、column、value，value必须匹配真实单元格；服务保留口径/映射版本。关键数字可附 evidence_recipes，用归档工作簿单元格/范围独立核验指定 run 单元格；recipe 的 expected 不能自填，必须由 claim.run_id/row/column 指向真实运行结果。金额类要求（比率、只要比率情景的项、数量、人数、面积等以外的一切指标，认不出的名称也算金额；名称里同时写了价格或收入、利润等金额的数量和面积，如 price_volume、revenue_by_area，也是金额）按以下依据计为已回答：①本稿引用的结果单元格附一条通过的 direct/sum/diff recipe；②finance 引擎 explain_variance 闭合通过的结果，只适用于 metric 为 revenue/cost/expense/profit 且不带 scenarios 的项（filters 不能按来源行、凭证或分录挑行，也不能与要求本身的组织、期间、情景或维度矛盾；account_signs 只能是 1 或 -1；实际与基准不能是同一情景同一 filters）；③metric 是账套科目名（不是 revenue、cost、expense、profit 这类规范指标名或其别名，如营业收入、净利润、营业成本、期间费用，大小写不论；这些只按①②作答）时，finance 引擎 run_metric account_total（accounts 只列该科目，filters 只能写要求本身的组织、期间、情景或维度；按凭证、产品或来源行筛选出的合计不计入）那一行的 amount；④列了 periods/organizations 的科目项和 control_totals：run_metric 结果集，引用范围内全部行的 amount 并逐行用 drilldown_fact 核查来源；⑤收入、成本、费用、利润和量价拆分（price_quantity、price_volume 等同时写了价格和数量的名称）以外的金额，也可引用 finance 引擎自己输出的该指标（如 finance_scenario_run 的 open_amount、closing_cash），或服务端 structured_aggregate 汇总计划（analysis-save，只绑定要求的那一份快照）输出的该指标列（金额用 sum 度量；count、count_distinct、min、max 只回答问笔数或单笔最大/最小值的项）；⑥metric 为 price_quantity 的项：finance 引擎 explain_variance 量价桥同一行的 total_variance、quantity_contribution、price_contribution、interaction，或按①附 recipe。文稿为同一个要求组合引用的每个数都要按上述依据计入：已计入的引用不能替另一个数作证，多出的数要补依据或从正文和 claims 中删去；估算与另一个已计入的数并列时，该组合仍按估算计，经理确认前不算已回答。脚本输出、脚本自行算出的闭合对任何金额都不计入，run_metric management_pnl 行本身也不计入收入、成本、费用、利润。运行须按要求的绑定运行（别名和快照都一致；要求只有一个绑定时别名不限），否则结果不计入，见 rebind_run。finance 引擎运行的 finance_scope 里每个绑定别名的口径都须与要求范围一致（如 cash_13_weeks 同时绑定 receipts 和 payments 时两个都要一致），否则结果不计入，见 rescope_run。②至⑥的 finance 引擎依据要求绑定的快照里至少有一份能让引擎读出数据行（有列名为 amount、金额、发生额或本期金额的金额列，或列名恰为 revenue、cost、expense 的列，或财务口径把某列映射为金额；营业收入、营业成本、期间费用这类中文列名引擎读不到）：一份都没有时（工作簿文件、空表、列名都不是上述名称的表，如区域预算分解表、城市公司明细表），这些路径在 blocked_evidence 里标 bindings_without_engine_rows 并交经理；在其他快照上保存财务口径或运行都不计入（绑定不同），不要为此 finance_context_save 或重复运行。带科目列的明细表只是金额所在列的列名不是默认列名（如 本期发生额、本月数）时，这些路径标 amount_column_unmapped 并在 amount_columns 列出候选列，由助手打开：用 finance_context_save 为同一组绑定保存财务口径，在该绑定的 policies.field_map 写 {\"amount\": \"列名\"}，再按路径计算。明细表旁另绑一份供复算的工作簿不阻塞引擎路径。run_metric 结果集在本要求的绑定上运行后仍不计入时，engine_run_does_not_cover_requirement 会写明是哪次运行、行上（及财务口径 scopes 里）哪些字段为空或与要求范围不一致（含账套、币种、单位，required_scope 给出要求的值）、多少科目未映射、哪些组合没有结果行或结果行不在要求范围内，原样重跑不会改变结果；整张表同属一个值时在该绑定的 scopes 里写明后重跑；单位不同时 scopes 的 unit 只写表本身的单位，在该绑定的 policies.<别名>.target_unit 写要求的单位，由引擎换算金额（结果里的 target_unit 指明），只改 unit 标签不会换算。结果行的 metric_key 写要求的 metric；currency、unit 写在每一条结果行上（只有 finance 引擎运行的 finance_scope 能代替行上字段，脚本和 SQL 运行的 scope 不参与要求核对），不要把账套全文抄到行上；运行结果用精确小数计算（不要用二进制浮点数）并保存完整精度，展示时再舍入：能除尽的值须与复算值完全相等，除不尽的比值及由它算出的估算至少保留 28 位有效数字（Python Decimal 默认精度，运算顺序不限）；运行结果的数值列按 DECIMAL(38) 保存，同一列最长的整数位数加最长的小数位数超过 38 位时运行会失败，所以精度不要超过需要（如与 6 位整数的万元金额同列时，系数最多保留 32 位小数）。按 quality 里 requirement_unanswered 的 fixups 逐项补：row_keys、scope_fields、evidence_recipe_cells、rebind_run、rescope_run、blocked_evidence；脚本单元格的来源核查用 add_source_recipe 指名的 recipe，drilldown_fact 只核查 finance 引擎和 structured_aggregate 的行。completion.status=awaiting_manager 表示只剩估算待经理确认、声明的缺数、工作簿结构待确认或要求绑定的资料引擎读不到行，停止修补并如实说明。业务原因若来自经理，basis=professional_judgment；直接假设为user_assumption。缺少原因证据可以保存草稿，不能写成确定因果。修改可用parent_id，新版本不覆盖历史；只传 parent_id 的修订沿用原文稿的要求版本，要求改版后（repin_requirements、revise_requirement_dimension）修订时同时传 requirements_id 为当前版本 id。", {
    title: text("说明标题"), body: text("可编辑的Markdown正文；传 document 时由结构文稿生成正文"), document: REPORT_DOCUMENT, run_ids: { type: "array", items: { type: "string" } }, fact_ids: { type: "array", items: { type: "string" } }, claims: { type: "array", items: { type: "object", additionalProperties: false, properties: { basis: { type: "string", enum: ["calculation", "source_fact", "external_reference", "user_assumption", "professional_judgment"] }, run_id: text("运行id"), row: { type: "integer", minimum: 0 }, column: text("结果列名"), value: text("精确结果值"), fact_id: text("prepare_explanation 返回的真实事实 id；使用 presentation 时必填"), presentation: NUMERIC_PRESENTATION, reason: text("判断或假设依据"), dataset_id: text("source_fact 的资料快照id"), paragraph: { type: "integer", minimum: 0 } }, required: ["basis"] } }, evidence_recipes: { type: "array", items: evidenceRecipe }, consistency_sources: { type: "array", items: consistencySource }, consistency_rules: { type: "array", items: consistencyRule }, parent_id: text("被修改的文稿 id"), requirements_id: text("本稿答复的要求版本 id；只传 parent_id 时沿用原文稿的版本，要求改版后传 repin_requirements 给出的当前版本 id"),
  }, ["body"]),
  finance_background_save: specTool("finance-background-save", "保存一条版本化业务背景，只在当前授权财务范围和有效期内供解释使用。basis 区分 source_fact/external_reference/user_assumption/professional_judgment；经理输入不要伪装为系统事实。可用 dataset_id/paragraph 绑定授权资料段落。", {
    external_reference: { type: "object", properties: { title: text("外部来源名称"), url: text("外部来源URL"), source_date: text("来源日期YYYY-MM-DD"), retrieved_at: text("查询日期YYYY-MM-DD") } }, context_id: contextId, text: text("背景内容"), basis: financeBasis, scope: financeScope, effective_from: text("生效起始日期或期间"), effective_to: text("可选失效日期或期间"), dataset_id: text("可选授权资料快照id"), paragraph: { type: "integer", minimum: 1 }, parent_id: text("可选父背景id"), label: text("背景标签"),
  }, ["text", "basis"]),
  finance_background_list: specTool("finance-background-list", "列出当前授权且适用于 as_of/财务范围的业务背景。不会默认注入其他账套、过期背景或撤销授权后的资料。必须给出 as_of 或 scope.period；两者都没有时返回空列表并标 missing: [\"as_of\"]，不会按当前日期猜期间。", {
    context_id: contextId, scope: financeScope, as_of: text("解释所处日期或期间"),
  }),
  finance_adjustment_list: specTool("finance-adjustment-list", "列出当前口径下的考核调整项：待确认与已确认纳入。只读。窄会话不得列出其他会话的调整。确认纳入仍由经理在界面完成。", {
    context_id: contextId,
  }, ["context_id"]),
  finance_controls_propose: specTool("finance-controls-propose", "按工作簿自己的合计行建议勾稽控制（分项加总 = 合计），每条附预览结果。只读，不保存；比率、占比、天数类列不建议。", {
    dataset_ids: { type: "array", items: { type: "string" }, description: "只看这些工作簿资料；省略则看全部" },
  }),
  finance_controls_save: specTool("finance-controls-save", "保存勾稽控制为待确认（proposed）：subtotal 比较同一张表的分项与合计，tie_out 比较两处取数（可跨表、跨工作簿），formula 按单元格重算一个数再对套表报数：formula=signed_sum 用 inputs 各取数乘 sign（1 或 -1）相加，适合应收滚动「年初+新增−收回−核销=期末」；formula=dso 用 ar_end、可选 contract_assets_end，以及 revenue_ttm 或 revenue_py_full+revenue_py+revenue 重算应收天数，对套表报的周转天数，tolerance 按天；formula=implied_collection 用 ar_end、ar_begin、impairment（负数按损失计）、revenue 和可选合同资产反推回款率，对综合收缴率（小数，百分数用 scale 0.01），tolerance 用小数如 0.03。只能保存，确认、停用由经理在界面完成；同一检查重复保存返回已有记录。差异由系统发现，不由你择一。", {
    controls: { type: "array", items: { type: "object", required: ["label", "right"], properties: { kind: { type: "string", enum: ["subtotal", "tie_out", "formula"] }, label: text("控制名称"), formula: { type: "string", enum: ["signed_sum", "dso", "implied_collection"] }, inputs: { type: "object", additionalProperties: { type: "object", required: ["dataset_id", "source_hash", "sheet", "range"], properties: { dataset_id: text("analysis-state 里的资料 id"), source_hash: text("该资料的 source_hash"), sheet: text("工作表名"), range: text("A1 单元格或区域"), scale: text("单位换算，只能是 10 的整数次幂"), sign: { type: "integer", enum: [1, -1] } } }, description: "仅 formula：命名取数" }, params: { type: "object", description: "仅 formula：dso 可设 days_per_year，implied_collection 可设 vat_factor" }, left: { type: "object", required: ["dataset_id", "source_hash", "sheet", "range"], properties: { dataset_id: text("analysis-state 里的资料 id"), source_hash: text("该资料的 source_hash"), sheet: text("工作表名"), range: text("A1 区域，如 T5:T604 或 C11"), scale: text("单位换算，只能是 10 的整数次幂，如 0.0001 表示元→万元") } }, right: { type: "object", required: ["dataset_id", "source_hash", "sheet", "range"], properties: { dataset_id: text("analysis-state 里的资料 id"), source_hash: text("该资料的 source_hash"), sheet: text("工作表名"), range: text("A1 区域，如 T5:T604 或 C11"), scale: text("单位换算，只能是 10 的整数次幂，如 0.0001 表示元→万元") } }, tolerance: text("允许差额，默认 0"), unit: text("单位标签"), note: text("说明") } } },
    origin: { type: "string", enum: ["suggested", "declared"] },
  }, ["controls"]),
  finance_controls_run: specTool("finance-controls-run", "运行当前有效的勾稽控制并留存记录：每条给出两侧取数、差额、是否只是显示舍入；资料快照变化后为 stale。只有经理确认过的控制计入月结。", {
    ids: { type: "array", items: { type: "string" }, description: "只运行这些控制；省略则全部" },
  }),
  finance_controls_list: specTool("finance-controls-list", "列出勾稽控制（含待确认与已确认）及各自最近一次结果。只读。", {
    include_retired: { type: "boolean" },
  }),
  finance_control_finding_save: specTool("finance-control-finding-save", "给一项差异（运行后结果为不相符或读不出的勾稽控制）记一个问题类型建议，附一句理由。只记录建议：问题类型由经理在界面确认或改选，你的建议不改变差异状态、处置或套表可用结论，不要说类型已定。五类：formula_control 公式或控制缺陷（公式、取数范围或控制本身错了）；source_conflict 来源矛盾（两份来源对不上，又没有说得通的解释）；unsupported_assumption 无依据假设（数字靠估计或倒挤，没有依据）；not_updated 未更新（一边还没更新到本期或最新版本）；basis_difference 口径不同（两边量的不是同一件事，例如含税与不含税、期间或范围不同，需要列调节而不是改数）。", {
    control_id: text("finance_controls_list 返回的控制 id"),
    finding_type: { type: "string", enum: ["formula_control", "source_conflict", "unsupported_assumption", "not_updated", "basis_difference"] },
    note: text("一句理由，最多 500 字"),
  }, ["control_id", "finding_type"]),
  detail_list: {
    description: "列出本任务已导入的收费明细表（应收明细、实收明细、房产主数据）：行数、来源文件、各列名、系统按列名提的映射、经理确认的映射和还缺哪几列。收费明细在界面「资料」里由经理导入，助手不导入文件。只读。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["detail-list"],
  },
  detail_propose: {
    description: "为一张收费明细表提议每个标准字段对应哪一列（mapping：标准字段 → 原列名），供经理确认。应收明细字段 bill_id、property_id、fee_item、period、amount_gross、waiver、amount_net、due_date、status、project、customer_type；实收明细 receipt_id、date、bill_id、amount、property_id、method、nature；房产主数据 property_id、project、city、nature、type、owner、area、state。只是提议：经理在界面确认之前，这张表不能算收缴率。",
    parameters: { type: "object", required: ["detail_id", "mapping"], additionalProperties: false, properties: {
      detail_id: text("detail_list 返回的明细表 id"),
      mapping: { type: "object", additionalProperties: { type: "string" }, description: "标准字段 → 明细表里的原列名" },
    } },
    kind: "edit", argv: (input) => ["detail-propose", "--detail", input.detail_id, "--mapping", JSON.stringify(input.mapping)],
  },
  collection_caliber: {
    description: "读取本任务的收缴率口径：行业通行默认值（defaults）、经理确认的口径（confirmed）、等经理确认的提议（proposed）和计算实际采用的口径（effective）。只读。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["collection-caliber"],
  },
  collection_caliber_propose: specTool("collection-caliber-propose", "按客户说法提议收缴率口径，经理在界面确认后才生效；没写的键沿用当前口径。params 可含：total_method（bounded 默认：(当期已收+本年清欠)÷(本年应收+年初往年欠费)，不超过 100%；all_receipts：本年全部实收÷本年应收，含清欠和预收，可能超过 100%）、year_start_month（年度起始月份，物业服务年度 7 月起填 7）、related_owners（算关联方的产权归属，默认 [\"地产\"]）、exclude_related（主口径是否剔除关联方）、excluded_fee_items（不算物业费、不进收缴率的收费项目，如 [\"商业租金代收\"]）。note 写一句客户原话或理由。不要自己确认，也不要说口径已生效。", {
    params: { type: "object", description: "要改的口径键" },
    note: boundedText(500, "客户原话或提议理由"),
  }, ["params"]),
  collection_run: specTool("collection-run", "用经理确认过列的收费明细计算收缴率：当期收缴率、当月收缴率、清欠率、综合收缴率、预收余额、减免率、户数收缴率，按账期归属而不是按收款日期。receivable、receipt 必填明细表 id，property 可选（按业态、产权分组和关联方需要它）。as_of 统计日 YYYY-MM-DD。默认用经理确认的口径；spec 里另写口径键就是试算，结果 caliber.status 为 trial，向经理说明是试算、不是确认口径。group_by 最多两项：fee_item、project、customer_type、city、nature、type、owner。reported 填套表报数（小数）可算相差多少个百分点。结果的 quality 和 labels 列出作废单、冲红行、找不到应收单的收款、找不到房产的应收、重复房产编号、款项性质和账期对不上的收款，每条带文件和行号。", {
    receivable: text("应收明细表 id"), receipt: text("实收明细表 id"), property: text("房产主数据表 id，可选"),
    as_of: text("统计日 YYYY-MM-DD"),
    group_by: { type: "array", items: { type: "string", enum: ["fee_item", "project", "customer_type", "city", "nature", "type", "owner"] }, maxItems: 2 },
    reported: { type: "object", properties: { collection_rate_current: text("套表报的本年收缴率，小数"), collection_rate_total: text("套表报的综合收缴率，小数") }, additionalProperties: false },
  }, ["receivable", "receipt", "as_of"]),
  collection_run_read: {
    description: "按 id 重新读出一次收缴率计算的完整记录：参数、口径状态、输入明细的哈希和映射、结果。只读。",
    parameters: { type: "object", required: ["run_id"], additionalProperties: false, properties: { run_id: text("collection_run 返回的 id") } },
    kind: "read", argv: (input) => ["collection-run-read", "--run", input.run_id],
  },
  structure_proposal_list: specTool("structure-proposal-list", "读取已加载工作簿的表结构提议：每张表判为可作数据表或排除、表头行、列角色、借贷列配对与方向、要排除的分节小计行、需向下填充的列、标题里读到的期间单位币种。blocked_reason 非空的表不能确认，unreadable_columns 表示它确实是张表但一列都没识别出来——复述给经理，不要放进确认清单。看板之类的展示页默认排除（presentation_sheet）；带 adoptable=true 的说明上面读到了表，经理同意采用时把它的 decision 改为 table 再提交。只读。不传 dataset_id 时列出本任务所有待确认文件。", {
    dataset_id: text("analysis-state 里的工作簿资料 id"),
  }),
  structure_proposal_confirm: specTool("structure-proposal-confirm", "代经理提交表结构确认，生成可算的表。只接受资料 id 与提议项，不接受路径、URL 或工作簿字节；来源由调用入口判定，spec 里自报的 source 一律丢弃。助手提交的确认记为待经理追认，经理在界面追认或拒绝。借贷方向未定时拒绝确认——先请经理说明哪一侧是金额。清单里带 blocked_reason 的表会被整单拒绝并报出表名，别原样把提议全量传回来。", {
    dataset_id: text("要确认的工作簿资料 id"),
    revision: {type:"integer", minimum:1, description:"structure_proposal_list 返回的提议版本号"},
    sheets: {type:"array", items:{type:"object"}, description:"确认后的逐表结构声明，省略则按提议原样确认全部可作数据表的表"},
  }, ["dataset_id"]),
  structure_template_list: specTool("structure-template-list", "列出这套账记住的表结构模板：签名、表名模式、权重、是否停用。模板按工作区记，不按任务记，所以上个月确认的形状这个月照样命中。只读，不含路径或字节。命中模板的文件会自动套用并标为待经理追认。", {}),
  report_template_list: specTool("report-template-list", "列出当前任务可用的公司 Word/Excel 模板（内置与已发布）。只返回 template_id、label、kind，不含路径或字节。", {}),
  report_template_apply: specTool("report-template-apply", "按 template_id 套用公司模板，在当前任务写一份新草稿。可传 context_id 填页眉口径。Excel 模板的命名区数值只能来自 run_id 指向的已授权 run（命名区名匹配结果列或 metric 名），不接受调用方直接给数字；没有 run_id 就只套皮不写数。不覆盖旧稿。发布模板仍由经理点选。", {
    template_id: text("report_template_list 返回的 template_id"),
    context_id: contextId,
    run_id: text("可选：为 Excel 命名区取数的已授权 run"),
    scope: financeScope,
  }, ["template_id"]),
};
