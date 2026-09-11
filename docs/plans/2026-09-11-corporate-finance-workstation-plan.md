---
title: 公司财务工作台补强：就绪诊断、原文定位、角色包与公司模板
status: proposed-awaiting-execution
reviewer: pending
review_date: 2026-09-11
baseline: r2 A01–A34 已通过；解释质量 90% 门槛未达，本计划不以其为出口
product_authority: 财务经理主导判断；不转向投行/股权研究终端
related:
  - docs/plans/2026-09-05-finance-analysis-workbench-plan.md
  - .omx/plans/2026-09-06-finance-capability-plan.md
  - docs/plans/2026-09-06-explanation-quality-plan.md
  - docs/plans/2026-09-08-financial-documents-plan.md
acceptance: docs/plans/2026-09-11-corporate-finance-workstation-test-spec.md
---

# 公司财务工作台补强方案

对照 Codex / ChatGPT for Financial Services（2026-09-10）之后的增量实施计划。不重做 r2 的账套语义、差异桥、情景、Excel 绑定与 MCP。目标是补上对方真正拉开体验的三件事：**资料能不能算、数字能不能点回原文、成果像不像本公司文件**。

本文件是待执行方案。未获用户确认前不改产品代码、不打包、不改 `PRODUCT.md` 事实页。

## 1. 决策

| 决策 | 内容 |
|---|---|
| 岗位 | 继续服务财务经理的关账、预算差异、账龄与现金。不引入 tearsheet、DCF、comps、ib-deck、pitchbook。 |
| 抄机制不抄名单 | 内建数据就绪、原文高亮、模板即资产、角色技能包。不接 Daloopa / PitchBook / FactSet。金蝶/用友仍按租户另验。 |
| 增量 | 复用 `FinanceStore`、`source_refresh`、`prepare_explanation`、`ReportDocument`、`workbook_bindings`、随包四项方法。不另建 agent 平台或 EPM。 |
| 四态不变 | 执行成功、可复算、经理认可、归档继续正交。有引用 ≠ 经营原因已证实。 |
| 依赖 | 不新增第三方依赖。PPTX、云转换、捆绑 OCR、通用 MCP 市场不做。 |
| 解释质量 | 既有 30 题 90% 门槛仍按 `docs/plans/2026-09-06-explanation-quality-plan.md` 平行推进，不阻塞本计划 CF-1/CF-2 出口。CF-3 只新增表+附注题，不宣称整体达标。 |
| 方法仍可选 | 角色包与 `setup` 是路由与建议，不是技能门。未加载包时，四项原技能与 `run_metric` 仍可用。persona 不得因未跑 setup 而拒绝计算。 |
| 文稿合同 | 文稿 `template_version` 仍为 `annual-v1`。公司模板用 `template_id`（及已发布快照）区分经营简报/差异说明，不另开一套文稿 schema 版本号。 |

## 2. 用户路径（完成后应如此）

1. 经理丢入金蝶/用友/Excel 导出，问「这批资料能不能出管理损益」。助手**可以**加载 `setup` 并调用 `finance_readiness`，给出账套/期间/币种、能算什么、缺什么，不猜 ERP 已连接。经理直接要数字时，仍可走已有映射与 `run_metric`。
2. 就绪因 `mapping_incomplete` 挡住时，先走关账包做映射（`finance_map_save`），**不**要求 `can_run` 已含 `management_pnl`。能算则走关账包：管理损益、对账或分录草稿。点文稿里的「费用 −5」打开**授权预览副本**对应区域并高亮，而不是只看到 run 的行列号，也不得把账套原件路径交给模型。
3. 经理说「总部费用 5 不进考核利润」。保存调整项（附注、有效期）；默认 `include_in_management_pnl=false`。经理在结果区确认纳入后，新 run 利润 35，旧 run 仍为 30。总部费用调整与 G1 费用贡献 −5 不是同一条样本。
4. 出经营简报时套**已发布**的本公司 Word/Excel 模板（随包简报只是夹具），页眉带账套、组织、期间、单位。
5. 需要看桥或现金时，用差异包/现金包；拨假设生成子情景。圈选报告表或绑定区域「改成开票口径」生成新 revision，而不是另开一轮无记录的聊天。

## 3. 与现状的差距（只列本轮要补的）

| 能力 | 已经有 | 本轮补什么 |
|---|---|---|
| 取数 | 文件快照、`finance_source_refresh`、可注入 transport；CONNECTORS 仍是占位 | 导出文件识别与就绪诊断，先于 `finance_context_save`；多表工作簿按表试解析，不把空 `rows` 当成可算 |
| 引用 | `fact_id`、run 行列、`drilldown_fact` 回快照行 | 快照行上的表/单元格/页定位；UI 用 digest 句柄打开预览副本并高亮 |
| 方法 | 四项关账 SKILL 可发现、可加载 | 角色包（关账/差异/现金）+ `setup`；不复制四项正文；包必须是捆绑技能根下的一级目录 |
| 口径 | 科目映射、管理损益、情景 | 调整项一等对象，进入考核利润的显式开关与确认 |
| 成果 | `annual-v1` 文稿、五格式导出、Excel 绑定 | 管理员/经理可发布的公司模板；页眉写入口径；随包皮肤 ≠ 本公司文件 |
| 交互图 | Data Formulator 可启动，不是归档成果 | 绑定 `run_id` 的可归档图表版本 |
| 改口径 | 对话里改 filters / 新 context | 圈选表或绑定区 → 有记录的 revision |

## 4. 对象与工具合同

沿用现有集合。本轮新增合同清点：3 个领域对象（`SourceLocator`、`ReadinessReport`、`ManagementAdjustment`）、角色包路由（`setup`/`close`/`bva`/`cash`）、公司模板快照、图表成果，以及 §4.6 的 7 个工具。不要各建服务。

### 4.1 SourceLocator

挂在规范化事实和 `prepare_explanation` 的 `source_trace` 上。

```text
dataset_id, source_hash, kind: xlsx|csv|json|md|pdf|txt
sheet?, excel_range?, source_row, page?, passage?
preview_available: bool
```

规则：

- XLSX：`sheet` + `excel_range`（优先单元格，如 `费用!D18`）。`excel_range` 必须来自规范化时记下的表名+列（或已有工作簿绑定），**不能**只凭 `source_row_numbers` 拼出列字母。缺列时只给 sheet+行，不得伪造 `D18`。
- CSV/JSON：行号；无表名时 `sheet` 为空。
- PDF：仅当该页已作为任务 `ReportSource` 快照存在；否则 `preview_available: false`，不得伪造页码。
- 旧 run 没有定位时返回明确 `locator_unavailable`。
- `fact_id` / `run_id` 不属于当前任务或授权快照时返回 `locator_forbidden`，不得打开、不得静默落到别的任务文件。
- 点击响应：`locator_unavailable` → 只展示快照行、不高亮；`locator_forbidden` → 行内「无权打开」、不导航、不回退成无定位预览；`preview_available=false` → 行内「该页未归档」+ 快照行、不高亮页。
- `drilldown_fact` 继续返回快照行。新增只读 `open_source_locator`，参数**仅** `{fact_id}` 或 `{run_id,row,column}`，禁止 `dataset_id` / 本机路径 / URL 入参。
- 返回给模型与渲染器的定位不得含本机路径、`file://` 或 Univer/PDF 网关 URL。定位专用 IPC 的**成功回包**（不只 locator 对象）同样路径无关：在交给渲染器之前剥掉 `origin`、`file`、`allowedRoot`、`file://` 以及 Univer/PDF 网关 URL。主进程可在进程内保留 origin，仅用于放置 WebContentsView。
- 预览副本是 ephemeral scratch（与现有 `artifacts/preview/` 同寿命），**不得** `register_bytes` 进成果目录，不得出现在成果列表。主进程用定位专用 IPC 打开，**不得**走现有成果 `preview:open` / `deliverable-path`。XLSX：把授权 dataset 的归档字节拷到以 `source_hash` 命名的 scratch 目录，`allowedRoot` 仅该目录，再调用 Univer 预览宿主对副本做导入。PDF 且 `preview_available=true` 时复用现有 pdfjs ReportSource 预览，不走 Univer。禁止把 `analysis/` 整树当作预览根。`passage` 有上限。

### 4.2 ReadinessReport

`finance_readiness` 只读，不写快照、不写口径。

```text
proposed_scope: {ledger, organization, period, currency, unit}
can_run: [management_pnl | control_totals | reconciliation | receivables_aging | cash_13_weeks | ...]
blocked: [{capability, missing_fields[], reason}]
file_identity_policy: snapshot_only | business_key
diagnostics: 与 finance_model 同源（仅稳定代码与文案）
erp_connected: false   # 除非会话具名且已授权的适配器
```

- `diagnostics` 与 `blocked.reason` 只用稳定的 finance_model 代码和文案。不得含异常原文、文件系统路径、网关 URL、主机名、租户连接细节或 transport 载荷。内部 `finance_readiness` 工具结果同样剥离，不只 MCP 错误通道。
- 无授权 dataset：`can_run: []`，`blocked` 含一条 `{capability: management_pnl, missing_fields: ["dataset"], reason: no_dataset}`（其余能力同样不得列入 `can_run`），`erp_connected: false`。
- 缺期间或币种列入 `blocked`，不得静默填「本月」或 CNY。标题或表头出现「人民币」视为已声明币种（`proposed_scope.currency=人民币`），不得改写成 CNY；「不得静默填 CNY」只适用于没有任何币种标记的资料。
- 多工作表只提议，不自动合并。`kind=workbook` 不得只走「默认空 rows」的规范化；必须按表检查（现有工作簿检查或逐表试解析）。只有空壳工作簿时不得把 `management_pnl` 列入 `can_run`。`management_pnl` 列入 `can_run` 仅当至少一张 `sheet_candidate`（或 `kind=table`）自身同时具备期间、币种与映射覆盖；收入/成本与费用分在不同表、单表无法闭合损益的，只报告候选表，不得跨表并账户来宣称能算。
- `can_run` 含 `management_pnl` 的前提是：期间/币种可声明，**且**科目映射已覆盖该能力所需账户。半映射或未映射 → 该能力进 `blocked`（`reason=mapping_incomplete`），禁止「字段在就能算」。
- 若对金蝶/用友风格表头做了身份识别且失败：即使映射覆盖账户，`management_pnl` 仍进 `blocked`（`reason=identity_failed`）。G1 等不宣称 ERP 身份的通用文件仍按期间/币种+映射决定 `can_run`（CF01）。
- 表头/标题身份：至少一份金蝶或用友风格表头夹具（身份在标题或表头，不在英文字段名）。G1 合成样只证明合同，不得单独当作 ERP 导出已识别的出口证据。

### 4.3 ManagementAdjustment

独立于科目映射。映射回答「这行是费用」；调整项回答「这 5 万本月不进考核利润」。

```text
id, context_id, label, amount, profit_impact
accounts[], effective_period, include_in_management_pnl
basis: user_assumption | professional_judgment | source_fact
note, locator?, parent_id
bindings   # 所属 context/run 的 snapshot 顶格，必填
```

合同：

- `amount` 是调整幅度（正数表示剔除或加入的规模）；`profit_impact` 是对管理利润的有符号影响。B04：账面 `source_total=30`，剔除总部费用后 `profit_impact=+5`，`adjusted_total=35`。结果里既有 `source_total` 也有 `adjusted_total`；禁止只留一个含义不明的 `profit`。
- `run_metric(kind=management_pnl)` 只应用调用方**点名**的 adjustment ids，且这些项 `include_in_management_pnl=true`，且 `effective_period` 与本次 run 的期间键匹配。YTD/多月 run 只把各月调整应用到对应月份。禁止隐式「当前口径全部启用」。点名了不存在的 id 直接报错；点名但未确认、已被后续 revision 替代、或 `effective_period` 不在本次 run 期间集合内的 id，记入结果 `ignored_adjustments`（带 reason）并出 warning 诊断，不静默丢弃。`finance_adjustment_list` 给已被替代的行（pending 或已确认）打 `superseded_by`，UI 两个列表都不显示这些行。`adjustment_ids` 只接受 `run_metric(kind=management_pnl)`，其它指标带此参数直接拒绝。祖先判断沿 `parent_id` 链传递，不只看直接子项。
- `finance_adjustment_save` 默认不暴露给模型；若内部可写，保存后仅记录且 `include_in_management_pnl=false`。须经理在 UI 确认 `include` 才进入后续 `run_metric`。确认是把 include 置 true 的唯一动作。
- `parent_id` 表示对重叠调整的**替代**：账户重叠仅当 `parent_id` 指向那条被替代行才允许保存；`parent_id` 不指向重叠账户则拒绝。`run_metric` 只应用被点名的叶子，忽略已点名的祖先，避免双计。
- 多笔不重叠的调整按保存顺序应用。同一账户且 `effective_period` 重叠、又无合法 `parent_id` 时拒绝保存。不同月份同一账户可以并存，无需 `parent_id`。
- 新调整只生成新 revision/run。`basis=source_fact` 必须带授权定位；否则拒绝升格。调整不是凭证，不调用过账。
- B04 总部费用调整用独立科目/标签（如「总部费用调整」），不得占用 G1 费用贡献 −5 的同一行身份。
- `adjustments` 必须持久化所属 context/run 的 `bindings`。list/save/open 先授权该 context 或 run；空 bindings 对会话不可见。`locator.dataset_id` 必须落在该记录 bindings 内。

### 4.4 角色包

不是新的运行时，是随包目录与发现合同。捆绑技能提供方只扫描 `DSH_BUNDLED_SKILL_DIR` 下的**一级** `skill_id/SKILL.md`。因此包入口必须是一级目录，禁止 `method/packs/<id>/SKILL.md` 作为可发现路径。

```text
method/
  setup/SKILL.md
  close/SKILL.md
  bva/SKILL.md
  cash/SKILL.md
  financial-statements/   # 已有，不复制
  variance-analysis/
  reconciliation/
  journal-entry/
  packs.json              # 声明哪些 id 是路由包
```

`foundry/method_skills.py` 增加 `BUNDLED_PACKS = ("setup", "close", "bva", "cash")`。`BUNDLED_IDS` 仅含四项方法技能 id（与 `bundled_skill_manifest()["ids"]` 一致），不得并入包 id。`bundled_skill_dirs()` / `bundled_skill_files()` / `bundled_skill_manifest()["ids"]` 以及 dsh-plugin `methodSkills.ids` **仍只**覆盖四项方法技能，不得并进包 id（包 SKILL 没有 FOUNDRY.md 运行时备注，并进去会打实现有测试）。另增 `bundled_pack_dirs()` / `bundled_pack_manifest()` 扫描一级包目录。`packs.json` 与 `BUNDLED_PACKS` 是角色包注册表；`setup` 固定登记在 `BUNDLED_PACKS`，不另开第三套注册表。捆绑技能提供方对包目录的发现走包清单（或与方法根并列的一级 `SKILL.md`），不是改 `bundled_skill_dirs()` 的返回值。包 SKILL 只写：何时用、建议先调 `finance_readiness`、再 load 哪些已有技能、标准产出。canonical、`foundry/resources/method/`、安装包三处同步。不写入 `var/skills/`。

| 包 | 入口技能 | 组合已有能力 | 标准产出 |
|---|---|---|---|
| `setup` | `setup` | `finance_readiness` | 就绪报告 |
| `close` | `close` | 映射（`finance_map_save`）、报表、对账、分录草稿、可选差异 | 管理损益、勾稽、分录草稿 |
| `bva` | `bva` | `variance-analysis`、`explain_variance` | 闭合利润桥或量价桥 |
| `cash` | `cash` | `finance_scenario_save/run`（账龄、13 周现金） | 账龄表或 13 周现金 |

自然语言「关账」「预算差异」「现金会不会断」应能发现对应包；未装包时四项原技能仍可用。包不得成为 `run_metric` 的前置条件。

### 4.5 公司模板

扩展 `ReportDocument` 的 **template_id / 已发布快照**，不取消、不改写 `template_version=annual-v1`。校验继续拒绝未知文稿 schema 版本。`validate_report_document` 必须把顶层 `template_id` 与 `template_version` 一并保留进返回文档（`template_id` 不是 metadata 字段），以便 `save_draft` 哈希包含它。

- `template_id`：内置夹具 `management-brief-v1`（经营简报）与 `variance-note-v1`（差异说明），用于测试。CF-2「像本公司文件」的出口还要求任务或应用资源里至少一份**经理经原生文件选择器发布**的 Word 或 Excel 快照；随包皮肤不得单独关闭该出口。
- 页眉/封面字段来自当前 finance scope：账套、组织、期间、币种、单位。扩展 metadata 白名单为 `ledger`（账套）、`organization`（组织），并改 Python 与 Electron 页眉标签表（`DOCUMENT_METADATA_LABELS` / `EMPTY_METADATA` / `ReportDocument.metadata`）。旧稿 `company` 仍可读；缺项显示「未声明」，不编造。`template_id` 不当页眉字段。
- Excel 套用针对已发布模板快照字节写命名区（现有 openpyxl），普通金额可 SUM。不得把模板 `dataset-add` 进分析资料，也不得把模板快照当成 dataset 去做 `workbook_bindings`。命名区数值只来自 `run_id` 指向的已授权 run（命名区名匹配结果列或 metric 名，忽略大小写），调用方直接传 `values` 一律拒绝；没有 `run_id` 只套皮不写数，随包 Excel 夹具同样不写任何常量。返回 `filled_named_ranges` / `unfilled_named_ranges`。发布快照单文件上限 25 MiB。
- 模板是任务或应用资源中的不可变快照。助手不能用任意路径覆盖。发布必须走与「添加分析文件」相同的原生选择器，但**不得**调用分析资料的 `dataset-add`。主进程另开模板发布 IPC（与 `analysisAddFiles` 并列），不接收渲染器路径；写入当前任务的不可变模板快照。
- `report_template_list` / `report_template_apply` 先授权当前任务/会话。list 只返回 `template_id`、label、kind，不得含路径、快照字节或 URL。任务内已发布快照对其它任务不可见；apply 只在当前任务写新草稿。
- UI：文稿「套用公司模板」打开已发布模板列表（含空态「暂无已发布模板」）。现有「插入经营分析模板」降为本地草稿脚手架或移除，不得与已发布模板并列成两套入口。套用生成新草稿，不改旧稿字节。
- PPTX 仍排除。

### 4.6 新增工具（内部 harness）

| 工具 | 读写 | 作用 |
|---|---|---|
| `finance_readiness` | 读 | 对当前任务已授权资料出就绪报告 |
| `open_source_locator` | 读 | 按 fact/run 单元格返回定位与不透明预览句柄 |
| `finance_adjustment_save` | 写 | 保存调整项版本（默认不对模型暴露） |
| `finance_adjustment_list` | 读 | 当前口径下的调整项 |
| `report_template_list` / `report_template_apply` | 读 / 写草稿 | 列出并套用已发布模板 |
| `chart_deliverable_save` | 写 | 归档绑定 run 的图表 |

MCP：默认**不**把本表任何新工具（含只读 locator/list/template/chart）加入对外方法，直到为每个参数写完 grant：fact → `run.finance_context_id` 与 snapshot 顶格；adjustment/chart/template 同理。`prepare_explanation` 的 `source_trace` 不得含路径或网关 URL。撤销 grant 后拒绝。CF-1/CF-2 出口不依赖 MCP。

`charts` 是 FinanceStore 集合（与 `adjustments` 一样持久化 `bindings`）。save/open/list 都先授权该 run 的 context；空 bindings 对会话不可见；`run_id` 与 snapshot hash 必须落在该记录 bindings 内。磁盘表示写在 `analysis/charts/`，不另建第二套权威存储。归档图**不是**文稿成果；不得把预览 scratch 登记进图表集合。

## 5. 实施顺序

按 1→2→3。阶段内可以并行，但出口测试按阶段冻结。日期为自 2026-09-11 起的工作日历目标，不是对外承诺。

```text
CF-1 就绪 + 原文 + 关账包
  ├─ 1a finance_readiness + setup 技能
  ├─ 1b SourceLocator 贯通 model → fact → UI
  └─ 1c close 包发现与加载（依赖 1a）
CF-2 模板 + 调整项 + 差异/现金包
  ├─ 2a ManagementAdjustment + management_pnl
  ├─ 2b Word/Excel 公司模板
  └─ 2c bva / cash 包
CF-3 交互图归档 + 圈选改口径 + 表附注评测
```

### CF-1（约 30 天）

**1a 就绪诊断**

- 新增 `foundry/finance_readiness.py`：对已授权 dataset 做就绪汇总。工作簿必须按表检查，不得只调用一次默认空表的 `normalize_finance_dataset`。输出 `proposed_scope` / `can_run` / `blocked`，遵守 §4.2（空资料、映射不全、表头身份夹具）。
- `FinanceStore.finance_readiness`；CLI `finance-readiness`。
- `dsh-plugin/finance-tools.js` 与 `foundry/resources/dsh-plugin/finance-tools.js` 同步只读工具。
- `method/setup/SKILL.md`：建议先 readiness；若 `blocked.reason=mapping_incomplete` 再 `finance_map_save`，然后决定是否 `finance_source_refresh` / `finance_context_save`。禁止把占位 `~~erp` 说成已连接。
- 分析 preset 的 persona：资料未绑定口径时**建议** setup / readiness；**禁止**把未跑 setup 写成硬错误或拒绝 `run_metric`。

**1b 原文定位**

- `foundry/analysis_data.py` 的 xlsx 解析必须持久化表头单元格 → Excel 列字母映射（用单元格坐标，不用表头序号；使用区域不从 A 列起时序号会错）。`finance_model.py` 把 `dataset_id`、`sheet`、`source_row` 与该映射写入 `source_locator.excel_range`。不得把现有 sheet/`source_row_numbers` 当成已有列信息。G1 XLSX 夹具必须让记下的区域与高亮单元格一致；多表工作簿须先选定可映射表（或 `kind=table`），空 `rows` 的 workbook 快照不能作为 CF06 费用定位来源。
- `foundry/finance_explanations.py` 把 locator 纳入 `source_trace`；`prepare_explanation` 对可定位事实设 `preview_available`，且 locator 无路径。
- `FinanceStore.open_source_locator`：校验授权后返回定位与不透明句柄（无路径）。Electron 走 §4.1 的定位专用 IPC + ephemeral scratch，高亮 `excel_range` 或页。文稿点击只传 fact/run 单元格，由主进程解析。定位预览在**分析屏**打开现有工作区预览窗格（可盖住原生聊天，但不离开草稿/结果页）；关闭预览恢复原分析布局。
- 主入口：渲染后的文稿正文里绑定 `fact_id` 的数字（表格单元格与行内值）可点，调用 `open_source_locator`。引用事实面板是同一事实的次入口。run 表下钻仍只走结果路径。两种入口都不得打开任务外文件。

**1c 关账包**

- `method/packs.json`、`method/close/SKILL.md`（一级目录）。`close` SKILL 写明：`mapping_incomplete` 时先 `finance_map_save`，再管理损益。
- `method_skills.bundled_pack_manifest()` / `bundled_pack_dirs()` 覆盖包 id；`bundled_skill_dirs()` 仍只含四项方法。干净 DSH 目录可发现 `setup` 与 `close`。
- 安装版复验：新会话问「这批资料能不能出管理损益」，**可以**加载 setup 或 close，再计算 G1；未走包时四项技能仍能算出 G1。

出口：验收 CF01–CF15。开发态通过后打包，安装版复验发现/加载/G1，不把仓库存在当成通过。

### CF-2（约 60 天）

**2a 调整项**

- 新增 `foundry/finance_adjustments.py`；`FinanceStore` 集合 `adjustments`（含 bindings）。
- `finance_adjustment_list` 只读：按当前口径列出调整项；`FinanceStore`、CLI 与 DSH 同步，覆盖 `tests/test_finance_adjustments.py`。窄会话不得列出宽会话的调整项。
- `evaluate_metric` / `run_metric` 只应用点名且已确认 include、且期间匹配的调整；结果行区分 `source_total` 与 `adjusted_total`。
- 固定样本对齐工作台 B04：账面利润 30，剔除总部费用 5 后管理利润 35。总部费用调整与 G1 费用 −5 分夹具。
- 文稿必须同时能引用调整前与调整后；调整原因默认 `professional_judgment` 或 `user_assumption`。
- UI：已保存未确认的调整出现在结果侧栏，pending 标记；「确认纳入」是把 `include_in_management_pnl` 置 true 的唯一控件。每条 pending 行：确认按钮在 save/include IPC 进行中禁用；失败行内报错且 `include` 仍为 false；成功去掉 pending 标记、移入已确认列表，**不**自动重跑。同一侧栏下方「重算」块列出已确认调整的勾选（默认全选），只把勾选的 id 传给 `run_metric`；全不选则无调整重跑。未确认 id 不得进入重算。
- 结果区成对展示账面与考核。文稿引用选择器按「账面 / 考核」分组；有调整时默认筛选考核，可显式切到账面引用调整前数字。

**2b 公司模板**

- 内置两份夹具进 `foundry/resources/templates/`（`template_id`，文稿仍 `annual-v1`）。
- `report_documents.validate_report_document` 保留顶层 `template_id`；页眉字段来自 scope（`ledger`/`organization` 进白名单与标签表）。
- Excel：`tests/fixtures/` 放一份命名区模板，对已发布快照字节写入 G1 后 SUM 一致（不是把模板当 dataset 绑定）。
- UI：见 §4.5；套用已发布模板生成新草稿。出口另需一份经理经模板发布 IPC（非分析资料添加）发布的本公司文件快照。

**2c 差异包与现金包**

- `method/bva/SKILL.md`、`method/cash/SKILL.md` 只做路由。现金包写明用 `receivables_aging` / `cash_13_weeks`，禁止发明支付工具。
- `BUNDLED_IDS` 与 `BUNDLED_PACKS` / `packs.json` 均不含任何卖方研究技能名。

出口：CF16–CF26。回归 CF-1。

### CF-3（约 90 天）

**3a 可归档交互图**

- `chart_deliverable_save` 写入 FinanceStore `charts` 集合；磁盘文件在 `analysis/charts/`。记录系列、筛选、`run_id`、snapshot hash、假设、`bindings`。save/open/list 先授权该 run 的 context；空 bindings 不可见；`run_id` 与 snapshot hash 必须落在 bindings 内。窄会话或外任务不得 list/open/save 该图。不得把 locator scratch 登记为图表或文稿成果。
- 打开图表必须复现原 run；改假设走子情景 + 新图表版本。CF28 用现有 G3 现金延迟样本（回款晚 14 天），不另造假设夹具。
- Data Formulator 仍可当探索器；本阶段出口是 Foundry 归档，不把 Formulator 进程当作成果。
- 不做 Codex Sites 式托管 URL。

**3b 圈选改口径**

- 文稿表或 Excel 绑定区：选中单元格/列，发出「改成开票口径」等指令。
- 圈选 IPC 只接受当前任务内的选择句柄（文稿块 id + 单元格/列范围，或已有 workbook binding 的 range），不得传入路径、`dataset_id` 或外任务 `parent_id`。新 finance context 必须复制父 context 的 `bindings`，不得抬高 snapshot 顶格。未授权选择直接拒绝，不保存。`instruction` 必填，服务端不默认「改成开票口径」。圈选的选区（`kind`、`draft_id` 或 `binding_id`、`block_id`、`range`）写入新 requirements 记录的 `selection` 字段，revision 能回答「改的是哪张表哪一列」。
- 服务生成 `analysis_requirements_save`（`parent_id` + `change_reason`）和新 finance context/filters，不静默改旧 run。
- 无定位的纯聊天改口径保持原路径。

**3c 表+附注评测**

- 在 `tests/fixtures/finance_evals/` 增加独立小题集：脚注改变数字含义、调节表必须闭合、费用持平零值必须引用。
- 沿用 `r3-final-draft-text-bound-v3`。本集通过不代替原 30 题 90% 门槛。

出口：CF27–CF36。ERP 租户联调仍不在出口内。

## 6. 修改落点

| 区域 | 主要文件 |
|---|---|
| 就绪 | `foundry/finance_readiness.py`（新）、`foundry/finance_service.py`、`foundry/finance_cli.py` |
| 定位 | `foundry/finance_model.py`、`foundry/finance_explanations.py`、`foundry/analysis_data.py`（xlsx 表头→列字母映射）、定位专用 IPC、文稿阅读视图 |
| 调整项 | `foundry/finance_adjustments.py`（新）、`foundry/finance_metrics.py`、`foundry/finance_service.py` |
| 模板 | `foundry/report_documents.py`（扩展 template_id 与 metadata，不改 annual-v1）、`foundry/resources/templates/`（新）、`foundry/finance_files.py` |
| 包 | `foundry/method_skills.py`、`method/setup/`、`method/close/`、`method/bva/`、`method/cash/`、`method/packs.json`、资源镜像、`dsh-plugin/presets/analysis/agent.cordis.yml` |
| 工具 | `dsh-plugin/finance-tools.js` 与 `foundry/resources/dsh-plugin/finance-tools.js` |
| 图表 | `foundry/chart_deliverables.py`（新）、分析成果列表 |
| 圈选 | 文稿编辑器选择 → IPC → `analysis_requirements_save`；Excel 绑定已有 range |
| 测试 | `tests/test_finance_readiness.py`、`tests/test_finance_locators.py`、`tests/test_finance_adjustments.py`、`tests/test_method_packs.py`、`tests/test_report_templates.py`、`tests/test_workbook_bindings.py`（CF17）、`tests/test_report_documents.py`（CF34 回归）、`tests/test_chart_deliverables.py`、评测 fixture |
| 验收器 | CLI/G1 就绪仍走 `tools/verify_analysis_workbench.py`。CF12/CF13/CF13b 的 loader 与模型会话证明走 `tools/verify_method_skill_session.py`（扩展 `EXPECTED_CELLS` / `verify_loaded_resources`，核对工具记录含 `finance_readiness` 与 `can_run`/`blocked`）。CF07 走现有 Electron source-locator 测试 + r2 同款安装版收据；不新增 Playwright 入口 |

镜像规则与 r2 相同：改 plugin/method/工具合同必须同步 `foundry/resources/`。

## 7. 明确不做

- 卖方研究技能包、PPT 路演、effort 档位、托管内部网站。
- 把 `~~erp` 写成已接通；把「适配器能跑注入 transport」写成金蝶/用友可用。
- 通用 MCP 目录扩张。新写能力先内部工具，再按 grant 外露。
- 用引用成功代替四态，或把调整项写成已过账凭证。
- 为高亮引入云文档转换或新表格引擎。Univer/PDF 快照不够时标明 `preview_available: false`。
- 用本计划出口宣称解释质量 90% 已达到。

## 8. 风险与假设

显性假设：财务经理的第一分钟痛点是「这文件能不能算」，不是「有没有 comps」；公司模板先做 Word/Excel 就够用；圈选改口径比再做一个聊天入口更贴近改表习惯。

隐性假设：导出文件能稳定抽出账套/期间/币种（要用 G1、表头身份夹具、以及至少一种故意缺字段的负向样本打掉）；Univer 能高亮矩形区域（若不能，CF-1 改为「打开表并选中行」，不得宣称单元格高亮）；角色包会被模型先加载（必须用真实会话证明，不能只测文件存在）。

最危险的假设：把「有 setup 技能」或「字段能抽出来」当成「经理不再卡在映射」。若 readiness 不能把映射不全写成 `blocked`，关账包会在半映射资料上继续猜。CF01–CF04 必须在写 UI 之前先红。

## 9. 完成定义

- **CF-1 完成**：安装版中，经理上传 G1 合成资料并问能否出管理损益，得到结构化就绪报告（含 can_run/blocked）；映射不全或 ERP 表头身份失败时不得宣称能出管理损益；随后**可以**经关账包或四项原技能跑出 +5 桥；点击费用贡献打开预览副本对应区域。表头身份夹具不得仅因英文字段名而 can_run。旧四项技能仍可单独加载。
- **CF-2 完成**：同一任务套已发布经营简报模板导出 Word/Excel（文稿仍为 annual-v1）；经理确认「总部费用不进考核」后新利润 35、旧稿仍 30；差异包与现金包可发现且不注册卖方技能。随包夹具不得单独充当「本公司文件」。
- **CF-3 完成**：一张绑定原 run 的归档图作为成果打开仍复现原值；用 G3 现金延迟样本改假设后父图 hash 不变、子情景出新版本；圈选一列改口径产生新 requirements 版本；表+附注小题集按该集门槛报告，不覆盖原 30 题声明。

每阶段先新增合同测试，再 Python / App / 静态检查，最后安装包哈希与隔离配置复验。真实企业样本与 ERP 租户分别取证，不互相替代。

## 10. 调研依据

- OpenAI，[Introducing ChatGPT for Financial Services](https://openai.com/index/introducing-chatgpt-financial-services/)，2026-09-10。
- Codex 角色插件与 Corporate Finance 路线图，2026-06-02。
- 对照画布：`canvases/codex-finance-services-vs-foundry.canvas.tsx`。
- 本仓库已交付基线：`docs/plans/2026-09-06-finance-r2-completion-audit.md`。

## Deferred / Open Questions

### From 2026-09-11 review

- **Competitor three-gap premise replaces the confirmed analysis job** — 开篇目标 (P0, product-lens, confidence 75)

  实施者会按「资料能不能算、数字能不能点回原文、成果像不像本公司文件」排期，而已确认的工作台岗位是问题→原因→行动。竞品三件事可能把解释质量闸门和改口径挤到后面。是否改开篇目标，仍待产品拍板。

- **User path recasts the analysis workbench as a close workstation** — 用户路径 (P1, product-lens, confidence 75)

  路径把第一分钟写成关账包就绪，可能把工作台从「带着问题与文件进来」收成关账工作站。是否接受这一岗位收窄，未决。

- **CF-3 phase adds work outside the three headline goals** — 实施顺序 / 完成定义 (P1, scope-guardian, confidence 100)

  图归档与圈选改口径不在开篇三件事里，却占第三阶段出口。是拆成后续计划，还是把开篇目标改写成包含它们。

- **Accepted 改口径 loop and explanation gate sit behind competitor chrome** — 决策 / 解释质量 (P1, product-lens, confidence 100)

  已接受的改口径回路与 90% 解释门槛被标成平行、不阻塞 CF-1/CF-2。先交货竞品体验，可能让经理带着仍不及格的稿去开会。是否把闸门或改口径提前，未决。

- **Headline goal #3 (company templates) is subordinate to a longer non-headline phase** — 实施顺序 (P1, scope-guardian, confidence 75)

  「像本公司文件」是开篇第三件事，完整模板却在更长的 CF-2，且 CF-3 仍占日历。是否把页眉级最小模板片提前到 CF-1，未决。

- **Template “三处同步” claim lacks the third mirror path** — 公司模板实施 (P2, coherence, confidence 75)

  方法技能写 canonical / 资源镜像 / 安装包三处，模板目前只点名资源目录。两处还是三处，正文仍需选定。

- **Phase durations (30 / 60 / 90 days) are ambiguous** — 实施顺序 (P3, coherence, confidence 75)

  30/60/90 是自 2026-09-11 起的累计里程碑，还是每阶段各自时长，未写明。

- **Circle-select vs chat as the recorded 改口径 exit** — 圈选改口径 (P2, feasibility, adversarial, design-lens, confidence 75)

  可行性要求补选区合同；对抗审阅认为把圈选当出口会让聊天改口径继续无记录。以谁为有记录出口，两条建议相反。

- **ReadinessReport likely duplicates existing normalize diagnostics** — 就绪诊断 (P2, scope-guardian, confidence 75)

  就绪报告可能只是规范化诊断的投影。是否坚持独立模块，还是先做纯函数投影，未决（与「必须按表检查工作簿」不冲突）。

- **File and abstraction surface exceeds complexity smell threshold** — 修改落点 (P2, scope-guardian, confidence 75)

  文件与抽象面大于开篇三件事所需。是否再列一张 CF-1 最小文件集、把包/模板/图标成 stretch，未决。

- **ReadinessReport has no UI placement or interaction state machine** — 用户路径 / 就绪 (P1, design-lens, confidence 100)

  就绪报告放在资料页哪一块、加载/空/部分能算/失败各长什么样，计划未写。交互位置待设计。

- **Chart deliverable has no information-architecture home** — 交互图 (P2, design-lens, confidence 75)

  归档图在成果列表的入口未定，且取决于 CF-3 是否仍留在本计划。

- **Method packs lack Methods-tab grouping and missing-pack affordance** — 角色包 (P2, design-lens, confidence 75)

  方法页是否把角色包与单项技能分组、缺包时如何提示，属信息架构，未决。

- **B04 HQ exclusion needs UI confirm, not speech** — 用户路径 / 调整项 (P1, product-lens, feasibility, confidence 75)

  工作台 B04 是经理说「总部费用不进考核」后利润变为 35，但本计划把 include 唯一动作写成结果区「确认纳入」，且保存不对模型暴露。按第二轮已写入的确认控件做，口述不再单独过关；是否改回「口述即确认」，仍待产品拍板。

- **Confirm does not apply unnamed run_metric** — 调整项 / run_metric (P1, adversarial, confidence 75)

  经理确认 include 后，聊天或 CLI 未点名调整 id 的 `run_metric` 仍可能得到账面 30。UI 默认全选会盖住这条。省略 id 视为全部已确认项，还是继续「禁止隐式全部启用」，未决。

- **CF-3 chart store and viewer unspecified** — 可归档交互图 (P1, feasibility, confidence 75)

  图表既写进财务存储集合、又落在 `analysis/charts/`，应用里没有图表库且禁止新依赖。磁盘路径、用哪套列表打开、无新依赖时如何复现系列，未决。

- **ReadinessReport can_run exceeds phased exits** — 就绪报告 (P1, scope-guardian, confidence 75)

  就绪枚举含对账/账龄/13 周现金，但 CF-1 出口只验收管理损益与勾稽。是把未测能力从 CF-1 合同里拿掉，还是 CF-2 补验收行，未决。

- **CF24 tests bridge math not routing** — CF-2 验收 (P2, scope-guardian, confidence 75)

  差异包合同是路由包装，验收却要求 G1 桥仍闭合 +5。失败会被当成包缺陷。是否改成只测发现与路由引用，未决。

- **Scratch copies lack close-time deletion** — 原文定位预览 (P1, security-lens, confidence 75)

  定位预览把账套副本拷到 `artifacts/preview/`，关闭时是否立即删掉 digest 目录并关掉表格网关，还是与现有预览目录同寿命、等任务清理，未决。
