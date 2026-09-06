# Finance r2 最终验收审计

日期：2026-09-06。范围：核对 r2 A01–A34 当前工作树、测试和真实运行证据。本文汇总交付范围、实现、验证和保留限制。证据摘要见 [`docs/finance/r2-final-evidence-summary.json`](../finance/r2-final-evidence-summary.json)。

## 总体结论

r2 的后台财务模型、来源刷新、文件协作、情景计算、MCP 外部助手接入、性能优化、DSH 真实加载、Python 全量测试、App 测试、Excel 宿主和最终安装版 A34 技能会话均有可核证通过证据。阶段 4 按用户要求缩为“适配 + 文件刷新”；当前没有真实 ERP 测试账套，所以不把 ERP 租户联调作为本轮阻塞项。30 题真实模型评测已完成本轮覆盖，但解释质量门槛未达：30/30 有尝试、29/30 完成、22/30 题含重跑至少一次严格通过（已完成的 29 题中为 22 题），首轮修正批次为 16/27 题通过、26/27 题完成，不能写成全部通过或达到 90%。旧版 `native-workspace-final` 只作为基线证据，不写成 0.1.3 原生 UI 验收。

## 最终证据索引

| 证据 | 结果 | 说明 |
| --- | --- | --- |
| `build/verification/r2-final-pytest.log` | `758 passed, 2 skipped in 73.66s` | 两项跳过为可选依赖：`pyarrow`、`data_formulator` 未安装。 |
| `build/verification/r2-final-app-tests.log` | `361 passed` | App/Vitest 最终测试。 |
| `build/verification/r2-real-load.log` | `10 passed in 18.69s` | 真实 DSH runtime/load 验证全过；这 10 项已包含在 758 项总数内。 |
| `docs/finance/r2-native-ui-final-evidence.json` | `passed` | 最终 0.1.3 安装版 CUA 复验：预算桥首屏四行 +20/−10/−5/+5，设置自动收起，利润下钻 6 行。 |
| `docs/finance/r2-package-final-evidence.json` | `passed` | 最终归档 CRC、包内/安装版主程序与 canonical 方法/Excel 资源一致。 |
| `build/finance-mcp-client-verification-codex-app.json` | `passed` | ChatGPT.app 内置 `codex-cli 0.153.4`、当前 `gpt-6-astra`，真实 MCP list/run/drilldown 等价，撤销后捕获 `-32001 access denied`。 |
| `docs/finance/r2-excel-host-evidence.json` | `passed` | Excel Mac 16.111.802.3 真实 Office.js 宿主：导入、指标运行、预览、应用、重算、保存、冲突保留均有事件证据；临时 manifest/token/key/证书已清。 |
| `docs/finance/r2-performance-optimized-evidence.json` | A25 通过 | 10 万行、5 次：导入中位数 2.824s，冷查询 1.269s，热查询 1.130s，取消路径 0.413s 内返回 timeout。 |
| `build/verification/financial-acceptance.json` | `passed` | 预算差异、利润桥、历史期、缺预算、跨任务方法、重复哈希、后台文档、假设修订等核心流通过。 |
| `build/verification/workbook-ui-final.json` | `passed` | UI 工作簿导出保存标题/正文/版本、结果单元格和 run evidence ID。 |
| `build/verification/native-workspace-final.json` | `passed` | 旧版基线：打包主进程/CLI/native service、任务切换、A→B→A 草稿保持等通过；不作为 0.1.3 原生 UI 验收。 |
| `/Applications/FA Foundry.app/Contents/Resources/app.asar` | final installed hash | 最终 UI 修复后安装版 app.asar SHA256 `cfd4bed70437c0c387c252515cd91da20ff71f65eb9afaa10f0d386d02de0052`，大小 9,032,204 字节；最终归档 `app/release/FA-Foundry-0.1.3-macOS-arm64-r2-20260906-0853.zip`，SHA256 `7aa0a4fa34c151ad3bd78335e360ac916f834bba0ea9f2db21fe7364890b6131`，497,870,440 字节；CRC、安装版主程序和方法/Excel 资源一致性均通过。 |
| `docs/finance/r2-skill-session-installed-013-evidence.json` | `passed` | 最终 UI 修复后 0.1.3 安装版真实 App + 当前 deepseek 配置，G1/G2 技能会话和重启复核通过；raw final path 为 `build/verification/r2-skill-session-installed-013-final`；旧 `installed-013-retry1` 为中间 renderer 包证据。 |
| `docs/finance/r2-finance-evals-report.md` / `docs/finance/r2-finance-evals-evidence.json` | gate not met | 30/30 尝试、29/30 完成、22/30 题含重跑至少一次严格通过（已完成的 29 题中为 22 题）；首轮修正批次为 16/27 题通过、26/27 题完成；解释质量门槛未达，只能作为可编辑草稿与失败证据。 |

## 阶段状态

| 阶段 | 范围 | 状态 | 证据结论 |
| --- | --- | --- | --- |
| 1 | 财务口径、科目映射、指标、来源行 | 通过 | A01–A05、A08–A09 有模型/指标/服务测试覆盖，Python 全量通过。 |
| 2 | 利润桥、量价拆分、说明修改、下钻 | 后台通过；解释质量门槛未达 | A06–A12 后台与验收器通过；30 题真实模型评测 30/30 尝试、29/30 完成、22/30 题含重跑至少一次严格通过，未达 90%。 |
| 3 | 工作簿绑定、文件往返、冲突选择 | 通过 | A19–A20、A22 文件层和真实 Excel `.xlsx` roundtrip 通过。 |
| 4 | 来源适配与文件刷新 | 范围内通过；真实 ERP 待账套 | A16–A18 以本地文件、注入 transport、分页/重试/删除策略/凭据隔离验证；无 ERP 测试账套，不阻塞当前缩范围。 |
| 5 | 应收账龄、13 周现金、驱动模型、子情景 | 通过 | A13–A15、A26 有纯函数、服务持久化、MCP scenario 工具和无支付/过账 API 证据。 |
| 6 | macOS Excel / Office.js 宿主交互 | 通过 | `docs/finance/r2-excel-host-evidence.json` 记录真实 Excel Mac Office.js 宿主导入、指标、预览、应用、重算、保存和冲突保留。 |
| 7 | 外部助手 MCP 接入 | 通过 | A23 及外部 MCP list/run/drilldown/revoke gate 通过；系统 CLI/Claude 的失败历史保留为环境 blocker 证据。 |
| 性能 | 大样本装载、查询、取消 | 通过 | A25 10 万行 5 次中位数和取消路径达到目标。 |
| 随包技能 | A27–A34 | 通过 | 阶段 0 技能接入、真实 DSH、最终 UI 修复后安装版 A34 技能会话通过；最终归档 CRC 与源文件/包内/安装版资源哈希一致。 |

## A01–A34 映射

| 项 | 状态 | 实现/测试映射 |
| --- | --- | --- |
| A01 | 通过 | `tests/test_finance_model.py::test_normalizes_service_ledger_with_scope_control_totals_and_trace`；控制总额按组织、期间、币种、单位、管理科目拆分。 |
| A02 | 通过 | `tests/test_finance_model.py::test_balance_level_rows_are_usable_without_fabricated_drilldown`；余额级资料可分析，不伪造凭证明细。 |
| A03 | 通过 | `tests/test_finance_model.py::test_mapping_diagnostics_manager_resolution_and_leading_zero_codes`；重复映射、父子重叠、经理口径诊断。 |
| A04 | 通过 | `tests/test_finance_model.py`、`tests/test_workbook_bindings.py`、`tests/test_finance_excel_export.py` 与 Excel roundtrip；Decimal、前导零、长精度文本策略验证。 |
| A05 | 通过 | `tests/test_finance_model.py::test_g5_movement_checks_preserve_signed_credit_balances_and_special_policies`；借贷方向、红字、结转、调整期、未过账处理。 |
| A06 | 通过 | `tests/test_finance_variance.py::test_profit_bridge_closes_and_links_sources`、`financial-acceptance.json`；G1 利润桥闭合。 |
| A07 | 通过 | `tests/test_finance_variance.py::test_price_quantity_closure`、`tests/test_finance_metrics.py`；G2 量价拆分闭合，不用汇总替代占比/贡献。 |
| A08 | 通过 | `tests/test_analysis_staging.py::test_snapshot_staging_keeps_relationship_and_sql_boundaries`、多组织 finance model/metrics tests；关系边界和 join fanout 有测试。 |
| A09 | 通过 | `tests/test_finance_metrics.py` 与 fixture metadata；actual/budget/forecast、期间、单位、stock/flow 语义保留。 |
| A10 | 通过 | `tests/test_finance_service.py::test_shared_run_draft_drilldown_and_immutable_mapping`；run、draft、drilldown 和映射版本绑定。 |
| A11 | 通过 | `tests/test_finance_service.py::test_changed_calculated_value_cannot_keep_verification`、`test_finance_rerun_output_mismatch_is_non_reproducible`；修改后不可保留旧 verified/reproducible 结论。 |
| A12 | 通过 | `app/tests/analysis.test.tsx` 覆盖经理编辑、删除或替换说明并保存；普通分析/草稿不增加逐工具审批，个人判断可保存。30 题模型解释质量门槛另行记录。 |
| A13 | 通过 | `tests/test_finance_scenarios.py`、`tests/test_finance_scenario_service.py`；G3 cash delay、G4 aging、13 周现金连续性、effective date。 |
| A14 | 通过 | `tests/test_finance_scenarios.py::test_child_scenario_serializes_diff_and_keeps_parent_inputs_unchanged`；子情景保留父输入/哈希。 |
| A15 | 通过 | `tests/test_finance_scenarios.py::test_driver_model_refuses_cycles_and_unsafe_formulas`、`test_driver_run_preserves_manager_assumptions_and_formula_provenance`；循环拒绝、经理假设留痕。 |
| A16 | 范围内通过 | `tests/test_source_refresh.py::test_a16_same_file_duplicate_points_to_prior_snapshot_and_changed_file_is_new_snapshot`；同源去重、变更生成新 snapshot。 |
| A17 | 范围内通过 | `tests/test_source_refresh.py::test_a17_transport_pagination_retries_dedupe_replay_and_failed_attempts_do_not_publish`；分页、重试、重放、失败不发布。 |
| A18 | 范围内通过 | `tests/test_source_refresh.py::test_a18_updates_voids_deletes_and_unsupported_incremental_deletion_policy`；更新/作废/删除策略；真实 ERP 待账套。 |
| A19 | 通过 | `tests/test_workbook_bindings.py`、`tests/test_finance_files.py`；绑定、baseline hash、冲突选择、越界拒绝。 |
| A20 | 通过 | `tests/test_finance_excel_export.py` 与 `file-roundtrip-evidence.json`；真实 Excel 保存重读后金额可求和，超精度按文本保留。 |
| A21 | 通过 | `docs/finance/r2-excel-host-evidence.json`：Excel Mac 16.111.802.3 真实宿主中完成导入、指标、预览、应用、重算、保存，冲突保留已观察。 |
| A22 | 通过 | `tests/test_excel_bridge.py`、`tests/test_finance_cli.py::test_workbook_cli_writes_numeric_new_artifact_with_real_run`、`workbook-ui-final.json`；桥接授权、预览、应用、run cell evidence。 |
| A23 | 通过 | `tests/test_finance_mcp.py`、`build/finance-mcp-client-verification-codex-app.json`；真实外部 Codex App MCP list/run/drilldown 等价，撤销拒绝。 |
| A24 | 通过 | 内部同源计算/草稿、既有任务授权与 SQL/Python 保留；外部 MCP 复用合同，连接凭据隔离、撤销拒绝、业务错误 `isError` 均有测试和真实客户端证据。模型解释质量另行记录。 |
| A25 | 通过 | `docs/finance/r2-performance-optimized-evidence.json`；10 万行 5 次中位数和取消路径达标。 |
| A26 | 通过 | `tests/test_finance_scenarios.py::test_domain_boundary_has_no_payment_submission_or_journal_posting_api`；无付款提交/凭证过账公共 API。 |
| A27 | 通过 | `docs/finance/r2-stage0-evidence.json`、`r2-package-audit.json`；canonical、资源镜像、安装包方法文件一致。 |
| A28 | 通过 | `docs/finance/r2-stage0-evidence.json`、真实 DSH 10 项加载；隔离目录发现/加载 bundled 技能，个人同名技能优先不破坏。 |
| A29 | 通过 | 阶段 0 结构化证据与真实 DSH；四个正文和 FOUNDRY/CONNECTORS 引用由会话加载，哈希匹配。 |
| A30 | 通过 | 阶段 0 G1/G2 会话证据、session 权限回归；无 Window analysis 任务可组合资料。 |
| A31 | 通过 | 实际配置模型 G1/G2 在新会话先加载方法后计算并保存真实 run 引用；最终安装版 A34 再次通过。30 题扩展质量门槛未达，不以两题替代总体可靠性。 |
| A32 | 通过 | 缺失/损坏技能根诊断、引用校验、通用分析连续执行；ERP 标记仍是占位。 |
| A33 | 通过 | 四个方法 ID、Apache-2.0/NOTICE、经理判断边界、save/apply method 复用回归。 |
| A34 | 通过 | `docs/finance/r2-skill-session-installed-013-evidence.json`：最终 UI 修复后 0.1.3 安装版真实 App、app.asar SHA256 `cfd4bed70437c0c387c252515cd91da20ff71f65eb9afaa10f0d386d02de0052`、当前 `deepseek-official/deepseek-v4-flash/max`，G1/G2 技能会话、方法资源加载和重启复核通过；旧 `installed-013-retry1` 是中间 renderer 包证据。 |

## 交付改动与简化

- 财务领域：`foundry/finance_model.py`、`finance_metrics.py`、`finance_variance.py`、`finance_service.py` 与情景服务统一口径、Decimal 运算、版本、来源和草稿合同；保留未来建账/资金管理边界。
- 文件和工具：`foundry/source_refresh.py`、`finance_files.py`、`workbook_bindings.py`、`excel_bridge.py`、`finance_mcp.py`、`excel-addin/` 完成适配/刷新、工作簿冲突选择、真实 Office.js 写入确认和外部助手调用。
- 交互：`app/src/views/Analysis.tsx` 与 `analysis/RunPanel.tsx` 统一持续讨论、财务口径、结果和来源；合并预算桥入口，运行后收起设置，保留维度和原始字段，减少首屏操作负担。
- 性能与复用：`foundry/analysis_sql.py` 批量装载受控快照；沿用已有 harness/权限/方法加载及资源镜像，没有新增项目依赖。新增合同、固定真值和真实宿主验证脚本保存验证路径。

## 保留限制

1. 独立的 30 题解释质量门槛未达：30/30 有尝试、29/30 完成、22/30 含重跑至少一次严格通过；首轮修正批次为 16/27 题通过，不能当作 22/30 的首次通过率。数值引用要求仍为 100%，完整数据问题的“计算→说明→下钻”要求仍为至少 90%，阈值未降低。交付为可编辑草稿，失败证据保留。
2. 阶段 4 未做真实 ERP 租户联调：用户暂无测试账套，本轮交付通用 adapter/transport 合同和文件刷新，不宣称金蝶、用友等产品 API 已连接。
3. 最终原生 UI 使用 `docs/finance/r2-native-ui-final-evidence.json`：安装版预算桥首屏四行、利润差异 +5、来源下钻 6 行，视觉复验 93 分；旧 `native-workspace-final` 仅是历史基线。
4. 两项 Python 可选依赖测试跳过，未宣称这些测试已运行。冻结包的 Formulator 独立 gate 通过；34 个变更 Python 文件 Ruff 通过，仓库已有未改静态诊断不在本轮清理范围。
5. 当前为本机未签名构建，未进行签名/公证发布。Excel 验证用 manifest/token/key/证书已清理。

## 证据处理

提交的证据摘要只含相对证据路径、状态、版本、计数和必要哈希；原始会话保留在忽略的本机 build 目录，凭据不进入 Git。
