# 财务解释质量实施与清理计划

日期：2026-09-06。用户已批准执行上一轮六项建议。基线提交 e5ba923；不新增依赖，不改用户当前模型配置，不放宽 SQL/Python 或现有任务授权。真实 ERP 仍待账套。本计划直接进入实施，无再次批准步骤。

## 交付目标

解释采用确定性财务事实、可定位业务依据和经理判断；生成文稿自动绑定引用。正文修改重新检查但可保存；检查结果不等于经理认可。评测面向本轮最终成果，保留首轮和每次独立尝试，不用历史草稿联合覆盖或补造零值通过。

## 清理与回归顺序

1. 在改动前增加失败测试：跨草稿联合覆盖、正文改错仍留旧引用、未产生的零值、比例显示与精确值、成本变化与利润影响、期间比较、跨范围背景泄漏。
2. 一次只修一个边界：评分与结果定位；计算语义和 schema；事实引用和文稿检查；业务背景版本与适用性；UI 和生产 harness 指引。
3. 重用 AnalysisStore、FinanceService、既有 financeCall、不可变版本和方法资源镜像；不另建 agent 平台，不添加重复同名方法。
4. 先定向测试，再 Python/App 全量、静态检查、真实配置模型评测、安装版可见流程；最后唯一文件名打包、安装、清旧包、提交推送并核验远端。

## 共享接口（实施时保持兼容）

- `prepare_explanation` / CLI `prepare-explanation`：`{run_ids:[id], materiality?:{absolute}}`。返回 `{facts:[{id,run_id,row,column,value,display_value,label,unit,scope,semantics}], required_fact_ids, diagnostics, business_contexts}`。只用当前任务授权的成功 run；fact id 稳定绑定输出哈希与行列，SQL run 同样可用。
- `save_explanation_draft` 继续接受原 `body/run_ids/claims/parent_id`，新增 `fact_ids`；正文可用 `{{fact:FACT_ID}}`，由服务渲染展示值并自动补齐精确 claims。保留原文模板和引用关联；自由文字仍能保存。
- `validate_explanation` / CLI `validate-explanation`：`{draft_id}` 或未保存 `{body,run_ids,fact_ids,claims}`；返回 `{status,issues:[{code,message,severity,...}],coverage,...}`。检查当前文稿引用、数字/单位/方向、完整性；不自动赋予 review_status，也不阻止普通草稿。
- `finance_background_save` / CLI `finance-background-save`：`{text,basis,scope:{ledger,organization,currency?,unit?},effective_from,effective_to?,dataset_id?,paragraph?,parent_id?,label?}`；basis 复用 source_fact/external_reference/user_assumption/professional_judgment。版本化保存；来源必须授权，经理输入明确标记。
- `finance_background_list` / CLI `finance-background-list`：`{context_id?,scope?,as_of?}`；只返回当前授权与适用期间背景，过期/不同账套不默认注入。
- 计算返回在现有字段之外加语义信息：成本/费用 amount_change 与 profit_impact 分离；比例精确分子分母与展示值分离；比较两侧显式期间和情景，不猜缺失输入。
- 本轮新增字段与原始记录兼容；普通 analysis-draft/UI 改稿也必须重新产生检查结果，不能携带失效的旧核验结论。

## 验收 Q01–Q12

- Q01：单份最终草稿/回答评分，旧草稿不能补齐；缺失零值不由评分器伪造。
- Q02：正文数字、引用值、单位、利润影响同义表达一致；显示舍入和计算精度分别验证；日期/编号不当财务数值。
- Q03：DSH 与外部 MCP 明确 ratio 分子/分母、比较过滤、事实引用合同；测试覆盖真实 loader。
- Q04：事实 id 不可跨 run/任务重用；引用自动生成，可按结果来源下钻；未授权数据拒绝。
- Q05：经理改错数字仍可保存，检查提示失配；源事实与经理假设分开；不新增逐步审批。
- Q06：背景按范围、有效期、版本复用；跨账套、过期和撤销授权不注入。
- Q07：保存背景并运行解释、查看依据、改稿、重检构成实际桌面流程，Noto/双栏/首屏结果保持。
- Q08：生产指引支持检查及最多两轮针对性修复；保留成功步骤和失败记录，缺数据不无限重试。
- Q09：30题旧集与新增留出题独立运行，主评测没有专用加分提示；记录每题首次结果、耗时、工具错误、最终文稿及来源。
- Q10：数值引用要求100%，跨账套/无依据确定性原因0；完整数据流程至少90%。未达如实保留失败，不改阈值。
- Q11：洞察评分区分重要性、驱动/原因、行动建议和不确定性；模型评审需以财务经理样例校准，未取得校准不得冒充专家通过。
- Q12：新安装包使用自身资源完成真实技能/解释会话与可见UI验证；包/安装/源码资源哈希一致，推送远端哈希一致。

## 分工与证据

评分器 lane 独占 tools/verify_finance_evals.*、tests/test_finance_evals.py、tests/fixtures/finance_evals；领域 lane 独占 finance_metrics/variance、finance_cli/mcp、dsh-plugin/finance-tools 及对应镜像/测试；解释 lane 独占 finance_service/analysis、新 explanation/background 模块及对应测试。主代理负责集成、生产方法指引、UI、实际评测与交付。各 lane 不覆盖其他修改，先写测试，报告接口变化。

模型比较以用户选择为准，默认保持 deepseek-official/deepseek-v4-flash/max；实现可复用对比入口，不把未做的跨模型测试计为完成。

实施收敛：本轮提供绝对金额重要性阈值；相对重要性参数明确返回不支持，避免没有比较基准的隐式阈值。业务背景在当前任务授权和期间内复用，未扩展为跨任务全局记忆。


## 本轮落地状态

工程实现及确定性验证已完成，详见 `docs/finance/explanation-quality-delivery.md` 与对应 JSON 证据。Q10 的 90% 完整流程目标尚未达成：首轮 17/30、留出 5/8，最终安装版定向 3/5；不把功能交付标成模型质量全面验收。Q11 已提供逐维量表和合成例，财务经理校准仍待真实标注。

后续优先级：
1. 补齐解释最后一稿的关键零值引用，覆盖持平利润与费用无变化场景；维持两轮修复上限和经理自由保存。
2. 为账龄状态筛选提供可定位币种、分桶和源行的确定性路径，减少临时 SQL 丢失来源映射。
3. 完整重跑原集与独立留出集，保留首轮记录，验证是否达到 Q10 后再提高质量声明。
4. 收集财务经理逐维标注，校准洞察评审；真实 ERP 联调继续等待账套。
