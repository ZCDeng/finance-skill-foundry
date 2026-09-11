---
title: 公司财务工作台补强：验收合同
status: proposed-awaiting-execution
plan: 2026-09-11-corporate-finance-workstation-plan.md
review_date: 2026-09-11
---

# 公司财务工作台补强：验收合同

本文是 [实施计划](2026-09-11-corporate-finance-workstation-plan.md) 的验收设计，不是通过报告。编号 CF01–CF36 与 r2 的 A01–A34、解释质量 Q01–Q12 并列，互不替代。

固定样本沿用 G1（利润桥 +5）及工作台 B04（剔除总部费用 5 后管理利润 35）。金额用 Decimal 字面量构造。禁止用实现输出反推期望，禁止真实客户资料。

## 证据分层

| 层 | 可证明 | 不可冒充 |
|---|---|---|
| 文件存在 | 技能/模板已打包 | 模型已加载或经理已用过 |
| 合同测试 | 工具返回结构化字段 | 桌面高亮或安装版路径 |
| 桌面/安装版 | 点击、套模板、隔离配置 | ERP 已连接 |
| 真实模型会话 | 自然语言走了 setup/包 | 解释质量 90% |

`erp_connected` 在本套合同中必须为 false，除非另有具名租户证据（本计划不要求）。

## CF-1 就绪、原文、关账包

| ID | 条件及通过标准 | 验证位置 |
|---|---|---|
| CF01 | 仅加入 G1 实际/预算文件且科目映射已覆盖所需账户后调用 `finance_readiness`：`can_run` 含 `management_pnl` 与 `control_totals`；`proposed_scope` 含期间与币种；不写口径、不新建 snapshot | 新增 `tests/test_finance_readiness.py` |
| CF01e | 当前任务无授权 dataset：`can_run` 为空，`blocked` 含 `{capability: management_pnl, missing_fields: ["dataset"], reason: no_dataset}`，`erp_connected=false` | 同上 |
| CF02 | 去掉期间或币种列：对应能力进入 `blocked`，`missing_fields` 点名；不得填「本月」或 CNY | 同上 |
| CF02m | 期间/币种在但科目映射未覆盖管理损益账户：`management_pnl` 进 `blocked`（`reason=mapping_incomplete`），不得列入 `can_run` | 同上 |
| CF03 | 多工作表 workbook（默认规范化会得到空 `rows`）：按表检查或逐表试解析；只有一张能映射时报告候选表，不静默 UNION，也不把空壳工作簿标成可算。收入/成本与费用分两表、单表无法闭合损益：不得把 `management_pnl` 列入 `can_run`，只报告候选表 | 同上 |
| CF03h | 金蝶或用友风格表头夹具（身份在标题/表头，不在英文字段名）：不得仅因字段名把 `management_pnl` 列入 `can_run`。身份识别失败时即使映射覆盖账户，仍 `blocked`（`reason=identity_failed`）。G1 合成本身不代替本条 | 同上 |
| CF03c | 金蝶/用友风格标题含期间与「人民币」、且映射已覆盖管理损益账户：`proposed_scope.currency` 为人民币（不得改写成 CNY），`can_run` 含 `management_pnl` | 同上 |
| CF04 | `product=file` 或未具名适配器：`erp_connected=false`；文案不得出现已连接金蝶/用友 | 合同测试 + setup 技能正文抽查 |
| CF05 | 无单据/行 ID 的余额表建议 `snapshot_only`；带 `document_id`+`line_id` 才建议 `business_key` | 同上 |
| CF06 | G1 XLSX 经规范化后，费用行 `source_locator` 含 `dataset_id`、`sheet`、以及由列信息构成的 `excel_range`（不得只凭行号拼列字母）；`source_hash` 与快照一致 | 新增 `tests/test_finance_locators.py` |
| CF07 | 安装版：文稿中费用贡献数字可点开，预览打开 artifacts digest 副本并选中对应行/区域；句柄无本机路径；不打开任务外路径，也不把 `analysis/` 整树当预览根 | 现有 Electron source-locator 测试 + r2 同款安装版收据 |
| CF08 | CSV 只有行号定位，`sheet` 为空，`preview_available` 可为 true（文本高亮行） | `tests/test_finance_locators.py` |
| CF09 | 未登记为 `ReportSource` 的 PDF 不得编造 `page`；`preview_available=false` | 同上 |
| CF10 | 故意去掉 locator 的旧 run：`open_source_locator` 返回 `locator_unavailable`；UI 仍可 `drilldown_fact` 看快照行 | 同上 + UI 测试 |
| CF10f | 另一任务或未授权 snapshot 的 `fact_id`/`run_id`：返回 `locator_forbidden`，不得打开 | 同上 |
| CF11 | 干净 DSH 目录经真实提供方可发现一级目录 `setup` 与 `close`（不是 `packs/close`）；`financial-statements` 等四项仍可单独 load | `tests/test_method_packs.py` |
| CF12 | 真实 loader 加载 `setup` 正文后，工具记录含 `finance_readiness`；不得只列出技能名 | `tools/verify_method_skill_session.py` + 会话证据 |
| CF13 | 新会话自然语言「这批资料能不能出管理损益」必须返回带 `can_run`/`blocked` 的就绪报告（`finance_readiness` 可不加载 setup 包）。单独证明 G1 +5 且从未出报告不算通过 | `tools/verify_method_skill_session.py` 扩展 + 模型会话 |
| CF13b | 未加载 setup/close 包时，四项原技能与 `run_metric` 仍可得 G1 +5，不得当成错误 | `tools/verify_method_skill_session.py` + `tools/verify_analysis_workbench.py`（CLI G1） |
| CF14 | 删除 `close`（或 packs.json 中的包 id）的负向配置：四项原技能与 SQL/Python 仍可用；诊断指向包缺失，不宣称已加载 close | `tests/test_method_packs.py` |
| CF15 | canonical `method/`、`foundry/resources/method/`、新安装包的 setup/packs 哈希一致；不写入 `var/skills/` | 打包检查 + A27 回归 |

CF-1 出口：CF01–CF15（含 CF01e / CF02m / CF03h / CF03c / CF10f / CF13b）。CF07/CF13 无安装版/模型会话时该项保持未验证，不得用合同测试冒充。

## CF-2 模板、调整项、差异/现金包

| ID | 条件及通过标准 | 验证位置 |
|---|---|---|
| CF16 | 套用 `template_id=management-brief-v1` 的草稿：文稿 `template_version` 仍为 `annual-v1`；页眉含账套、组织、期间、单位；缺项为「未声明」；`template_id` 进入草稿哈希 | 新增 `tests/test_report_templates.py` |
| CF17 | 经营简报 Excel 模板命名区写入 G1 利润 30 与桥 +20/−10/−5；普通金额为可 SUM 数值单元格 | `tests/test_workbook_bindings.py` 扩展或模板夹具 |
| CF18 | 套用已发布模板生成新草稿，旧 `annual-v1` 稿字节不变；未发布模板 id 被拒绝。随包夹具可测套用；「本公司文件」出口另需经理经原生选择器发布的一份 Word 或 Excel 快照 | `tests/test_report_templates.py` |
| CF18f | 外任务或未授权会话：`report_template_list` / `report_template_apply` 不得列出或套用他任务已发布快照；list 不含路径/字节/URL | 同上 |
| CF19 | `finance_adjustment_save` 持久化金额、利润影响、有效期、`include_in_management_pnl`、basis；非法 `source_fact`（无定位）拒绝 | 新增 `tests/test_finance_adjustments.py` |
| CF20 | B04：账面利润 30，调整「总部费用 5 不进考核」（独立标签/科目，不得占用 G1 费用贡献 −5）且经理确认 include 后，新 `run_metric` 只应用点名的调整 id，管理利润 35；结果区分 `source_total`/`adjusted_total` | 同上 + G1 夹具 |
| CF21 | 应用调整后旧 run 仍为 30，旧草稿引用不改；新 revision 才是 35 | 同上 |
| CF22 | 调整项 `note` 可保存；若带 locator，必须指向当前授权快照 | 同上 |
| CF23 | 无来源的剔除项 `basis` 只能是 `user_assumption` 或 `professional_judgment`；文稿不得把调整写成账面事实 | 合同 + `validate_explanation` 样本 |
| CF24 | 干净目录可发现 `bva`；加载后指引 `explain_variance`；G1 桥仍闭合为 +5 | `tests/test_method_packs.py` + 会话可选 |
| CF25 | `cash` 包只路由到 `receivables_aging` / `cash_13_weeks`；工具列表无支付/过账 | 包正文抽查 + A26 回归 |
| CF26 | `BUNDLED_IDS` / packs.json 不含 tearsheet、dcf、comps、ib-deck、initiate、research-note | `tests/test_method_packs.py` |

CF-2 出口：CF16–CF26（含 CF18f），并回归 CF01–CF15。

## CF-3 图表归档、圈选、表+附注评测

| ID | 条件及通过标准 | 验证位置 |
|---|---|---|
| CF27 | `chart_deliverable_save` 记录 `run_id`、snapshot hash、系列定义；再次打开不重跑也能展示原值 | 新增 `tests/test_chart_deliverables.py` |
| CF27f | 外任务或窄会话不得 list/open/save 该图；空 bindings 不可见 | 同上 |
| CF28 | 改假设（如回款晚 14 天）产生子情景与新图表版本；父图表 hash 不变 | 同上 + G3 |
| CF29 | 删除或刷新源文件后，旧图表仍绑定原 snapshot；打不开原件时明确失败，不改用最新快照顶上 | 同上 |
| CF30 | 文稿表选中费用列并提交「改成开票口径」：新 `analysis_requirements` 带 `parent_id` 与 `change_reason`；旧 run 不变 | 后端合同 + 编辑器测试 |
| CF30f | 圈选 IPC 传入路径、外任务 `parent_id` 或未授权选区：拒绝且不保存；新 context 的 `bindings` 不得高于父 context | 同上 |
| CF31 | 已绑定 Excel 结果区圈选同等指令：同一 requirements 合同，不写原快照 | 绑定合同扩展 |
| CF32 | 新评测题：表内利润 30，脚注写「含一次性补贴 8」；稿必须把 8 标为附注/调整，不得把 30 写成经常性利润 | `tests/fixtures/finance_evals/` 新集 |
| CF33 | 费用持平（贡献 0）必须在最终稿引用真实零值单元格，评分器不补造 | 新集 + 既有评分合同 |
| CF34 | 导出格式枚举仍无 pptx；模板发布拒绝 pptx 字节 | 回归 `test_report_documents` |
| CF35 | 默认不向 MCP 暴露本计划新工具（含只读 locator/list/template/chart）。若暴露，grant 须映射 fact/adjustment/chart/template；grant 外调用与本机调整后利润、单位、无路径 locator 一致，撤销后拒绝 | 仅当选择外露时跑 `test_finance_mcp.py` 扩展 |
| CF36 | 新安装包在隔离配置下复验 CF01、CF07、CF13、CF16、CF20；包/安装/源码模板与 packs 哈希一致 | 安装版收据 |

CF-3 出口：CF27–CF36（含 CF27f / CF30f）。CF32/CF33 只报告该小题集，不得更新原 30 题「已达 90%」声明。

## 回归与顺序

1. 每阶段先红合同测试，再改实现。
2. 阶段结束跑现有 Python 全量、App 测试、method/A27–A34 抽样、解释质量既有夹具不回退。
3. 打包后用干净 `DSH_HOME` 复验包级项。
4. 金蝶/用友租户、相对 90% 解释门槛、PPT、卖方数据均列为范围外。

## 失败如何记录

按层分开写：未实现、合同失败、桌面未验证、模型未走包、安装哈希不一致。不允许用「技能文件已加入」关闭 CF13，也不允许用「有 fact_id」关闭 CF07。
