const text = (description) => ({ type: "string", description });
const specTool = (command, description, properties, required = []) => ({
  description,
  parameters: { type: "object", required: ["spec"], additionalProperties: false,
    properties: { spec: { type: "object", required, properties, additionalProperties: true } } },
  kind: ["drilldown-fact", "workbook-inspect", "workbook-read", "prepare-explanation", "validate-explanation", "finance-background-list"].includes(command) ? "read" : ["run-metric", "explain-variance", "finance-scenario-run"].includes(command) ? "execute" : "edit",
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
export const FINANCE_TOOLS = {
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
  workbook_preview: specTool("workbook-preview", "预览限定区域的Excel结果写入。writes每项包含field、value以及cell或从1开始的row；引用计算结果时附run_id及result_row/result_column。显示经理修改冲突与数值精度策略，保存patch_id后再应用。", {
    binding_id: text("结果绑定id"), dataset_id: text("可选更新后的XLSX快照"), run_id: text("可选真实运行id"),
    writes: { type: "array", items: { type: "object", properties: { cell: text("目标单元格地址"), field: text("绑定字段名"), row: {type:"integer", minimum:1}, value: {}, result_row: { type: "integer", minimum: 0 }, result_column: text("真实结果列名") }, required: ["field", "value"] } },
  }, ["binding_id", "writes"]),
  workbook_apply: specTool("workbook-apply", "应用已保存且未失效的Excel预览，生成新工作簿并返回路径/哈希。resolutions按冲突单元格声明经理选择keep或apply。原快照不覆盖；不要擅自代替经理决定冲突。", {
    patch_id: text("workbook_preview返回的patch_id"), resolutions: { type: "object", additionalProperties: { type: "string", enum: ["keep", "apply"] } },
  }, ["patch_id"]),
  finance_scenario_save: specTool("finance-scenario-save", "保存账龄、13周现金或驱动情景。kind=receivables_aging 的 inputs 含 invoices_alias、activity_alias、as_of、scope；账龄引擎不支持 status/exclude_statuses 等状态过滤，需剔除争议发票时直接用显式 SQL 筛选并计算，不能反复猜参数；kind=cash_13_weeks 含 opening_cash、start_date、actual_cutoff、scope 和可选 receipts_alias/payments_alias/scenario.delay_receipts_days。scope明确单一ledger/organization/currency/unit。驱动模型 kind=driver_model，inputs.drivers 声明公式和depends_on、values或manager_assumptions。创建子情景只用parent_id、changes和label，保留父输入。没有支付或过账能力。", {
    context_id: contextId, kind: { type: "string", enum: ["receivables_aging", "cash_13_weeks", "driver_model"] }, inputs: { type: "object" }, label: text("经理可辨认的情景名称"), parent_id: text("父情景id"), changes: { type: "object", description: "替换指定输入键；如 {scenario:{delay_receipts_days:14}}" },
  }, ["label"]),
  finance_scenario_run: specTool("finance-scenario-run", "计算已保存财务情景并生成同源运行与来源依据。账龄以实际截止日核算，不引入未来收款；现金每周连续，延迟收款保留未来计划。输出可下钻并整理为经理可编辑草稿。", { scenario_id: text("finance_scenario_save 返回的id"), question: text("业务问题") }, ["scenario_id"]),
  list_finance_context: {
    description: "查看本任务已授权资料、财务口径、科目映射和指标定义。先检查现有可复用方法与已加载财务技能；没有专用口径可建立，或继续 SQL/Python。无需审批。",
    parameters: { type: "object", required: [], properties: {}, additionalProperties: false }, kind: "read", argv: () => ["list-finance-context"],
  },
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
  drilldown_fact: specTool("drilldown-fact", "从当前任务真实 run 的结果行/列下钻到原始快照行。row 是 result.rows 下标（从0开始）；返回精确 source_hash 和原始数据，不搜索其他账套或最新快照。余额资料无凭证链接；分页最多1000行。", {
    run_id: runId, row: { type: "integer", minimum: 0 }, column: text("可选结果列"), offset: { type: "integer", minimum: 0 }, limit: { type: "integer", minimum: 1, maximum: 1000 },
  }, ["run_id", "row"]),
  prepare_explanation: specTool("prepare-explanation", "为财务解释准备稳定 fact id、精确值、展示值、scope、semantics、必引事实和适用业务背景。只读取当前授权的成功 run；用于让模型选择事实而不是手写 run/row/column。示例：{run_ids:[run.id], materiality:{absolute:'10'}}。", {
    run_ids: { type: "array", minItems: 1, items: runId }, materiality: { type: "object", properties: { absolute: text("绝对重要性阈值") }, additionalProperties: true },
  }, ["run_ids"]),
  validate_explanation: specTool("validate-explanation", "检查当前说明正文与事实引用是否一致：数字、方向、单位、舍入展示和缺失引用。可传 draft_id，或传未保存的 body/run_ids/fact_ids/claims。检查不代表经理认可，也不阻止保存普通草稿。", {
    require_all_material_facts: { type: "boolean", description: "检查全部重要行是否引用；正文通常只需当前问题相关事实" }, draft_id: text("可选已保存文稿 id"), body: text("未保存正文"), run_ids: { type: "array", items: runId }, fact_ids: { type: "array", items: { type: "string" } }, claims: { type: "array", items: { type: "object" } },
  }),
  save_explanation_draft: specTool("save-explanation-draft", "保存可由经理自由编辑的说明。优先使用 prepare_explanation 返回的 fact_ids 或 {{fact:FACT_ID}}；服务会补齐精确 claims。每个计算数字 claim 引用 run_id、row、column、value，value必须匹配真实单元格；服务保留口径/映射版本。业务原因若来自经理，basis=professional_judgment；直接假设为user_assumption。缺少原因证据可以保存草稿，不能写成确定因果。修改可用parent_id，新版本不覆盖历史。", {
    title: text("说明标题"), body: text("可编辑的Markdown正文"), run_ids: { type: "array", items: { type: "string" } }, fact_ids: { type: "array", items: { type: "string" } }, claims: { type: "array", items: { type: "object", properties: { basis: { type: "string", enum: ["calculation", "source_fact", "external_reference", "user_assumption", "professional_judgment"] }, run_id: text("运行id"), row: { type: "integer", minimum: 0 }, column: text("结果列名"), value: text("精确结果值"), reason: text("判断或假设依据") }, required: ["basis"] } }, parent_id: text("被修改的文稿 id"),
  }, ["body"]),
  finance_background_save: specTool("finance-background-save", "保存一条版本化业务背景，只在当前授权财务范围和有效期内供解释使用。basis 区分 source_fact/external_reference/user_assumption/professional_judgment；经理输入不要伪装为系统事实。可用 dataset_id/paragraph 绑定授权资料段落。", {
    external_reference: { type: "object", properties: { title: text("外部来源名称"), url: text("外部来源URL"), source_date: text("来源日期YYYY-MM-DD"), retrieved_at: text("查询日期YYYY-MM-DD") } }, context_id: contextId, text: text("背景内容"), basis: financeBasis, scope: financeScope, effective_from: text("生效起始日期或期间"), effective_to: text("可选失效日期或期间"), dataset_id: text("可选授权资料快照id"), paragraph: { type: "integer", minimum: 1 }, parent_id: text("可选父背景id"), label: text("背景标签"),
  }, ["text", "basis"]),
  finance_background_list: specTool("finance-background-list", "列出当前授权且适用于 as_of/财务范围的业务背景。不会默认注入其他账套、过期背景或撤销授权后的资料。", {
    context_id: contextId, scope: financeScope, as_of: text("解释所处日期或期间"),
  }),
};
