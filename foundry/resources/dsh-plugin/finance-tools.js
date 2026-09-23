const text = (description) => ({ type: "string", description });
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
  kind: ["drilldown-fact", "open-source-locator", "workbook-inspect", "workbook-read", "prepare-explanation", "validate-explanation", "finance-background-list", "analysis-requirements-list", "finance-adjustment-list", "report-template-list", "structure-proposal-list", "structure-template-list"].includes(command) ? "read" : ["run-metric", "explain-variance", "finance-scenario-run"].includes(command) ? "execute" : "edit",
  argv: ({ spec }) => [command, "--spec", JSON.stringify(spec)],
});
const contextId = text("list_finance_context 或 finance_context_save 返回的当前任务口径版本 id");
const runId = text("run_metric、explain_variance 或 finance_scenario_run 返回的真实运行 id");
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
  required: ["kind", "claim"],
  additionalProperties: false,
  oneOf: [
    { required: ["kind", "claim", "dataset_id", "source_hash", "sheet", "range"], properties: { kind: { enum: ["direct", "sum"] } }, not: { anyOf: [{ required: ["left"] }, { required: ["right"] }] } },
    { required: ["kind", "claim", "left", "right"], properties: { kind: { enum: ["diff", "ratio"] } }, not: { anyOf: [{ required: ["dataset_id"] }, { required: ["source_hash"] }, { required: ["sheet"] }, { required: ["range"] }] } },
  ],
  properties: {
    id: text("稳定 recipe id，同一文稿内唯一；省略时服务按顺序生成 recipe-N"),
    label: text("给财务经理看的检查名称；省略时使用 id"),
    kind: { type: "string", enum: ["direct", "sum", "diff", "ratio"] },
    ...evidenceSource.properties,
    left: evidenceSource,
    right: evidenceSource,
    scale: text("可选 Decimal 缩放，默认 1"),
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
  analysis_requirements_save: specTool("analysis-requirements-save", "计算前登记用户要求：问题、范围、必答指标、逐一覆盖的结果情景和指定下钻对象。更新必须带当前parent_id，移除项必须说明change_reason，不代表原问题已经完成。返回support由绑定快照核验；requires_input应补资料或字段映射，不能补零。", {
    question: text("用户要回答的管理问题"), context_id: contextId, scope: financeScope,
    bindings: {type:"object", additionalProperties:{type:"string"}}, parent_id: text("当前要求版本id"), change_reason: text("范围或要求调整原因"),
    items: {type:"array", items:{type:"object", required:["id","metric"], properties:{id:text("稳定要求标识"),metric:text("规范语义键，如profit/revenue/cost/expense/ratio/control_totals/price_quantity、单一科目代码或实际结果列名；不要把公式放入metric，公式放label，分解方法放dimensions.method，精确运行行指标键放dimensions.metric_key"),label:text("用户可读的要求"),dimensions:{type:"object"},periods:{type:"array",items:text("要求完整覆盖的期间，例如2026-01:2026-08或2026-08"),description:"每个期间都须有结果；多期间时清空scope.period；dimensions.period仅接受单个期间"},organizations:{type:"array",items:text("须逐一覆盖的组织，例如集团合并或华东"),description:"每个组织与每个期间都须有结果；多组织时清空scope.organization"},scenarios:{type:"array",items:text("须逐一覆盖的结果情景键，例如actual_ytd、budget_ytd、achievement_ratio"),description:"每个组织、期间与情景都须有对应结果；按运行结果的scenario原值填写，不从显示名称猜测"},requires_drilldown:{type:"boolean"}}}},
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
  finance_scenario_save: specTool("finance-scenario-save", "保存账龄、13周现金或驱动情景。kind=receivables_aging 的 inputs 含 invoices_alias、activity_alias、as_of、scope；账龄支持 inputs.status_filter={field,include,exclude,mapping}，按来源或经理声明映射状态；筛选保留 rows/detail_rows/excluded_detail_rows 的稳定键、as_of、纳入/剔除余额与来源，不能把当前状态声称为截止日历史状态；kind=cash_13_weeks 含 opening_cash、start_date、actual_cutoff、scope 和可选 receipts_alias/payments_alias/scenario.delay_receipts_days。scope明确单一ledger/organization/currency/unit。驱动模型 kind=driver_model，inputs.drivers 声明公式和depends_on、values或manager_assumptions。创建子情景只用parent_id、changes和label，保留父输入。没有支付或过账能力。", {
    context_id: contextId, kind: { type: "string", enum: ["receivables_aging", "cash_13_weeks", "driver_model"] }, inputs: scenarioInputs, label: text("经理可辨认的情景名称"), parent_id: text("父情景id"), changes: { type: "object", description: "替换指定输入键；如 {scenario:{delay_receipts_days:14}}" },
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
  chart_deliverable_save: specTool("chart-deliverable-save", "把当前任务已授权 run 的结果系列归档为图表成果。写入 FinanceStore charts 与 analysis/charts，绑定 run_id 与 snapshot hash。不得传入路径、预览句柄或 dataset_id。打开归档图复现原值，不重跑。改假设走子情景后再归档新版本。", {
    run_id: runId,
    parent_id: text("可选父图表版本"),
    label: text("图表名称"),
  }, ["run_id"]),
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
  explain_variance: specTool("explain-variance", "生成有来源的利润桥或量价拆分 run。利润桥明确实际/基准scenario和实际/基准filters；比较同一actual的当前/历史期间时分别填 actual_filters.period 与 baseline_filters.period。返回 amount_change 与 profit_impact，contribution 保留为 profit_impact 兼容字段；成本/费用增加为利润负影响。负预算的分母政策可选，零预算无比例。量价 kind=price_quantity 必须有数量价格，method=quantity_then_price 或 base_weights_with_interaction；只有金额不能推测量价。贡献是算术，业务原因另记经理判断。", {
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
  validate_explanation: specTool("validate-explanation", "检查当前说明正文与事实引用、已登记分析要求、来源追溯、独立 evidence_recipes 和自动附表是否一致：数字、方向、单位、舍入展示和缺失引用。可传 draft_id，或传未保存的 body/run_ids/fact_ids/claims/evidence_recipes/consistency_sources/consistency_rules。检查不代表经理认可，也不阻止保存普通草稿；区域均值、行业估计等只能作为 user_assumption/external_reference 单独列示，不可混成直接来源事实。", {
    require_all_material_facts: { type: "boolean", description: "检查全部重要行是否引用；正文通常只需当前问题相关事实" }, draft_id: text("可选已保存文稿 id"), body: text("未保存正文"), run_ids: { type: "array", items: runId }, fact_ids: { type: "array", items: { type: "string" } }, claims: { type: "array", items: { type: "object" } }, evidence_recipes: { type: "array", items: evidenceRecipe },
    consistency_sources: { type: "array", items: consistencySource }, consistency_rules: { type: "array", items: consistencyRule },
  }),
  save_explanation_draft: specTool("save-explanation-draft", "保存可由经理自由编辑的说明。优先使用 prepare_explanation 返回的 fact_ids 或 {{fact:FACT_ID}}；服务会补齐精确 claims 并返回 quality 与 completion。内部草稿引用协议仅用于原生输入：[[FA_FOUNDRY_DRAFT_REF:{\"draftId\":\"...\",\"revision\":N}]]；正文中不得展示 raw draftId，应显示“基于修订 N”。completion 中 repair_allowed、stop_reason=no_progress 和最多两轮修复预算用于继续或停止自动收尾。awaiting_input和verified_input_gap表示绑定快照已核验资料缺口，本轮答复可结束但原分析要求仍未完成；不要重复运行同一缺资料计算。每个计算数字 claim 引用 run_id、row、column、value，value必须匹配真实单元格；服务保留口径/映射版本。关键数字可附 evidence_recipes，用归档工作簿单元格/范围独立核验指定 run 单元格；recipe 的 expected 不能自填，必须由 claim.run_id/row/column 指向真实运行结果。业务原因若来自经理，basis=professional_judgment；直接假设为user_assumption。缺少原因证据可以保存草稿，不能写成确定因果。修改可用parent_id，新版本不覆盖历史。", {
    title: text("说明标题"), body: text("可编辑的Markdown正文"), run_ids: { type: "array", items: { type: "string" } }, fact_ids: { type: "array", items: { type: "string" } }, claims: { type: "array", items: { type: "object", additionalProperties: false, properties: { basis: { type: "string", enum: ["calculation", "source_fact", "external_reference", "user_assumption", "professional_judgment"] }, run_id: text("运行id"), row: { type: "integer", minimum: 0 }, column: text("结果列名"), value: text("精确结果值"), fact_id: text("prepare_explanation 返回的真实事实 id；使用 presentation 时必填"), presentation: NUMERIC_PRESENTATION, reason: text("判断或假设依据"), dataset_id: text("source_fact 的资料快照id"), paragraph: { type: "integer", minimum: 0 } }, required: ["basis"] } }, evidence_recipes: { type: "array", items: evidenceRecipe }, consistency_sources: { type: "array", items: consistencySource }, consistency_rules: { type: "array", items: consistencyRule }, parent_id: text("被修改的文稿 id"),
  }, ["body"]),
  finance_background_save: specTool("finance-background-save", "保存一条版本化业务背景，只在当前授权财务范围和有效期内供解释使用。basis 区分 source_fact/external_reference/user_assumption/professional_judgment；经理输入不要伪装为系统事实。可用 dataset_id/paragraph 绑定授权资料段落。", {
    external_reference: { type: "object", properties: { title: text("外部来源名称"), url: text("外部来源URL"), source_date: text("来源日期YYYY-MM-DD"), retrieved_at: text("查询日期YYYY-MM-DD") } }, context_id: contextId, text: text("背景内容"), basis: financeBasis, scope: financeScope, effective_from: text("生效起始日期或期间"), effective_to: text("可选失效日期或期间"), dataset_id: text("可选授权资料快照id"), paragraph: { type: "integer", minimum: 1 }, parent_id: text("可选父背景id"), label: text("背景标签"),
  }, ["text", "basis"]),
  finance_background_list: specTool("finance-background-list", "列出当前授权且适用于 as_of/财务范围的业务背景。不会默认注入其他账套、过期背景或撤销授权后的资料。", {
    context_id: contextId, scope: financeScope, as_of: text("解释所处日期或期间"),
  }),
  finance_adjustment_list: specTool("finance-adjustment-list", "列出当前口径下的考核调整项：待确认与已确认纳入。只读。窄会话不得列出其他会话的调整。确认纳入仍由经理在界面完成。", {
    context_id: contextId,
  }, ["context_id"]),
  structure_proposal_list: specTool("structure-proposal-list", "读取已加载工作簿的表结构提议：每张表判为可作数据表或排除、表头行、列角色、借贷列配对与方向、要排除的分节小计行、需向下填充的列、标题里读到的期间单位币种。blocked_reason 非空的表不能确认，unreadable_columns 表示它确实是张表但一列都没识别出来——复述给经理，不要放进确认清单。只读。不传 dataset_id 时列出本任务所有待确认文件。", {
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
