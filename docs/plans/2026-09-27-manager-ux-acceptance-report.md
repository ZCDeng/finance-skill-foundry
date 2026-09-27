# 财务经理交互收敛：开发与验收报告

日期：2026-09-27。本报告记录第一轮验收：**交接文档第 1–6 节范围内的开发与验收通过**。用户随后要求继续完成第 7 节，其实现与最终验收记录见[第 7 节验收报告](2026-09-27-manager-ux-section7-acceptance.md)。

依据：[设计交接](2026-09-27-manager-ux-design-handoff.md)、[实施与验收计划](2026-09-27-manager-ux-acceptance-plan.md)。集成来源为 PR #47 的 `cursor/manager-ux-scope-results-64cd`，取得的提交为 `e580c9e7448a393fe3fa9da0d97e6eadceef34d1`；本地基线为 `ef4474f9b5d413494251915933b3148e83fc700b`。第一轮验收时未提交；后续交付包含第 7 节。

## 交付结果

| 要求 | 完成行为 | 验收依据 |
| --- | --- | --- |
| 统一业务用词与错误提示 | 分析页采用中文词表；错误提示统一处理，包含已翻译提示和插值字段的编号脱敏；持久化失败记录也经过同一处理 | glossary、run-panel 等组件测试；六个浅色/深色首屏样例技术词命中均为 0 |
| 一个任务共享一份分析范围 | 资料、结果设置与分析要求共享当前 requirements；采用服务端返回记录，保留问题、指标项、绑定、context_id 与扩展字段 | CAS、跨面板同步、刷新、保存与切换任务回归测试 |
| 资料候选可采用 | 期间、组织、单位、币种、情景均可一键采用；账簿和粒度在更多范围中；固定枚举采用下拉，兼容已有未知值 | 真实桌面逐项采用、保存后 CLI 读取、结果页同步、重载持久化检查 |
| 计算使用已确认范围 | 先保存 requirements，再保存计算上下文和计算；默认值仅补足计算上下文，不冒充经理确认的范围 | FinanceWorkbench 组件测试；完整桌面计算与结果检查 |
| 结论、依据和过程分层 | 技术信息默认折叠，展开可核对完整编号和摘要；计算历史区分结果、未完成计算及中间步骤；版本使用业务序号和时间 | 默认隐藏/展开精确值断言；依据预览、历史与版本对照桌面验收 |
| 保持财务与引擎约定 | 金额保持 Decimal 字符串；四类状态维持独立；Refusal 原句保留 | 后端全量测试、前端测试与静态边界检查；引擎、bridge、App.tsx 无本次差异 |

财务背景的历史适用范围仍属于其引用记录，未用当前任务范围覆盖历史事实；其单位和币种复用统一选项，并保留未知枚举值。

## 集成后的补齐与简化

- 删除重复的 `AnalysisScopeCard.tsx`，复用 `ScopePanel`、`ScopeFields` 和 `useAnalysisScope`。
- 用 `glossary.ts` 和 `TechnicalInfo.tsx` 集中业务词表、错误处理及技术信息展示，减少分散实现。
- 修复刷新覆盖未保存范围、旧请求覆盖新记录、旧任务保存回调写入新任务、卸载后读取回调等竞态；用五项专门的异步回归测试锁定行为。
- 补齐所有主范围字段的候选采用入口、保存防重入和冲突保护，以及同一时间戳计算记录的唯一序号。
- 保留进入本任务前已有的结果比较改进：无法建立可比关系时明确提示，不把空差异误报为“没有变化”。

没有新增依赖。完整路径、删除项和文件摘要见 [source-manifest.json](../../build/manager-ux-acceptance/source-manifest.json)。主要变更文件如下。

| 文件组 | 路径 |
| --- | --- |
| 共享范围与页面状态 | `app/src/views/Analysis.tsx`、`app/src/views/analysis/scope.ts`、`ScopePanel.tsx`、`FinanceWorkbench.tsx`、`RequirementsPanel.tsx`、`FinanceBackgroundPanel.tsx` |
| 词表、技术信息与展示 | `app/src/views/analysis/glossary.ts`、`TechnicalInfo.tsx`、`shared.ts`、`RunPanel.tsx`、`DatasetPreview.tsx`、`DraftEditor.tsx`、`presentation.tsx`、`app/src/views/analysis.css` |
| 其他分析组件用词 | `AccountMapEditor.tsx`、`AnalysisEditor.tsx`、`ClaimBindingRepair.tsx`、`EvidenceQuality.tsx`、`ExplanationQualityPanel.tsx`、`FinanceAdjustmentPanel.tsx`、`FinanceChartPanel.tsx`、`ReadinessPanel.tsx`、`ReportEditor.tsx`、`SourceRefreshPanel.tsx`、`StructurePanel.tsx`、`StructureProposalCard.tsx`、`WorkbookBrowser.tsx`、`WorkbookPanel.tsx`，均位于 `app/src/views/analysis/` |
| 结果比较 | `app/src/views/analysis/RevisionDiff.tsx`、`businessResults.ts`、`businessResults.test.ts` |
| 测试与桌面验收 | `app/tests/glossary.test.ts`、`scope-sync.test.tsx`、`analysis.test.tsx`、`business-result-components.test.tsx`、`evidence-quality.test.tsx`、`requirements-panel.test.tsx`、`run-panel.test.tsx`；`tools/verify_ui_workspace.cjs` |
| 删除重复组件 | `app/src/views/analysis/AnalysisScopeCard.tsx` |
| 文档 | 本报告、设计交接及实施与验收计划 |

## 验证结果

以下结果均来自最终源码版本。前端测试由 Python 门禁调用，表内的 4 项门禁包括前端测试和类型检查，不与 821 项重复累加。

| 验证 | 结果 | 日志 |
| --- | --- | --- |
| Python：`pytest -q --ignore=tests/test_app.py` | **2118 通过，15 跳过** | [backend.log](../../build/manager-ux-acceptance/logs/backend.log) |
| 应用门禁：`pytest -q tests/test_app.py` | **4 通过**，包含静态边界检查 | [app-gate.log](../../build/manager-ux-acceptance/logs/app-gate.log) |
| Vitest：`vitest run` | **51 文件，821 测试通过** | [vitest.log](../../build/manager-ux-acceptance/logs/vitest.log) |
| TypeScript：renderer / Electron | **均通过** | [renderer](../../build/manager-ux-acceptance/logs/typecheck-renderer.log)、[Electron](../../build/manager-ux-acceptance/logs/typecheck-electron.log) |
| 构建：`npm --prefix app run build` | **通过** | [build.log](../../build/manager-ux-acceptance/logs/build.log) |
| harness / foundry / formulator 检查 | **通过** | 既有包资源检查命令均退出 0 |
| Formulator 集成门禁 | **通过**，冻结实例提供本项目 locked catalog | [formulator-gate.log](../../build/manager-ux-acceptance/logs/formulator-gate.log) |
| Electron 桌面验收 | **通过**，first-screen / workspace 两阶段，无跳过阶段、无未执行项 | [verification.json](../../build/manager-ux-acceptance/verification.json)、[desktop.log](../../build/manager-ux-acceptance/logs/desktop.log) |
| 本地候选包与构建一致性 | **42 文件逐字节一致**；按配置排除 32 个 source map | [package-verification.json](../../build/manager-ux-acceptance/package-verification.json) |
| 视觉复核 | **通过，96/100**，阈值 90；人工视觉判断 | [visual-verdict.json](../../build/manager-ux-acceptance/visual-verdict.json) |

另已通过 `git diff --check` 与 `node --check tools/verify_ui_workspace.cjs`。项目没有独立 lint 脚本；本次使用现有 TypeScript、静态边界门禁与差异检查。

桌面验收启动的是打包后的 Electron 应用，使用合成资料和真实本地引擎完成 13 组检查：范围采用与持久化、首屏、浅深色焦点边框、参数从 20 改为 30 后利润由 250 变为 240、历史与技术信息、精确来源快照、版本对照、Escape 焦点归还、文稿阅读与编辑、保存新版本并导出有效 XLSX，以及任务重命名保持身份。文稿引用原计算，后续参数调整不会偷偷改变其引用。

## 候选应用与截图

应用：[FA Foundry.app](<../../build/manager-ux-candidate/mac-arm64/FA Foundry.app>)。打包日志：[package.log](../../build/manager-ux-acceptance/logs/package.log)。应用内中文字体资源校验通过。

本次运行及校验对应的 `app.asar` SHA-256：

```text
8db114b105b31b202f9bdd041644dcb8c1cafc7e8d864e7f66de78943d579838
```

55 张截图保存在 `build/manager-ux-acceptance/`，关键复核画面：

- [实际桌面首屏（浅色）](../../build/manager-ux-acceptance/first-screen-finance-light-1280-window.png)
- [声明长表首屏（深色）](../../build/manager-ux-acceptance/first-screen-declared-dark-1280.png)
- [保存后的完整分析范围](../../build/manager-ux-acceptance/scope-confirmed-1280.png)
- [依据与折叠技术信息](../../build/manager-ux-acceptance/evidence-1280.png)、[展开后的精确编号](../../build/manager-ux-acceptance/technical-expanded-1280.png)
- [版本对照](../../build/manager-ux-acceptance/comparison-1440.png)、[深色文稿](../../build/manager-ux-acceptance/draft-dark-1280.png)、[1080 窄窗口](../../build/manager-ux-acceptance/results-narrow-1080.png)

## 验收边界与剩余事项

- 本次桌面验证 `synthetic=true`、`providerCalls=0`，证明本地交互、保存、计算和导出流程；不构成真实模型效果或生产资料质量评测。
- 第一轮未包含第 7 节；其后续执行情况见[第 7 节验收报告](2026-09-27-manager-ux-section7-acceptance.md)。
- 候选应用用于本地验收，未签名、公证或替换 `/Applications` 中的安装版本；未执行发布。
- 保留现有非失败告警：jsdom canvas / localstorage 提示、Vite 大于 500 kB 的分块提示、打包默认图标提示。没有为消除这些提示引入依赖或扩大本次范围。
- 用户原有根目录依赖文件及未提交结果比较变更得到保留；集成前备份位于 `/tmp/manager-ux-integration-5hgvvqu7`。
