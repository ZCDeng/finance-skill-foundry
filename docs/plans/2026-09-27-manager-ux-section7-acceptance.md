# 财务经理交互收敛：第 7 节验收

完成日期：2026-09-28。

依据：[设计交接第 7 节](2026-09-27-manager-ux-design-handoff.md#7-未纳入与后续建议)、[实施计划](2026-09-27-manager-ux-acceptance-plan.md)。本次继续完成六项后续建议，覆盖此前第 1–6 节实现，完成验收后提交并推送。

## 交付与简化

| 项目 | 实现 | 验证 |
| --- | --- | --- |
| 范围与情景用词 | 结构确认、就绪面板、工作簿浏览与写回统一为范围或情景；已知情景用 `scenarioLabel`；保留“开票口径”原业务含义 | section7-scope-copy、readiness、report-editor 等组件测试 |
| 成果库、任务详情、预览编号 | 业务页面以版本顺序、标题和时间区分内容，完整编号与摘要由 `TechnicalInfo` 保留 | 专项组件与真实桌面检查 |
| 指标与区块标签 | 必答要求使用名称和序号；区块使用区域序号、单元格范围及表头行；提交仍用原编号 | section7-scope-copy：显示及真实提交参数断言 |
| 原始结果与诊断 | 结构化汇总和预算差异共用一个 `RawResultDetails`，统一放在技术信息内 | run-panel 精确 Decimal 字符串回归；桌面展开检查 |
| 设置与高级 | 财务设置与计算定义统一到一个入口；调整范围对应选定结果；保留工作副本与保存错误 | 组件生命周期测试及打包应用检查 |
| 文稿与方法库 | 引用计算使用顺序标签，原始引用可展开核对；方法业务参数与高级定义分层 | section7-draft、analysis、方法库桌面检查 |

审查发现并修复恢复稿载入后仍显示旧稿引用的问题；引用区和保存使用同一组 `effectiveRunIds` / `effectiveClaims`。无名称资料改用“资料 N”，真实编号仍保留在技术信息中。计算接口返回成功但计算记录失败时，设置抽屉保留错误与编辑内容；保存或重算真正成功后才关闭。

预览增加当前任务与版本归属校验，并将打开、关闭操作串行处理：导航后延迟返回的旧预览不会显示，IPC 异常后可以重试。技术信息展开时暂时隐藏原生工作簿视图，收起后恢复原边界，避免原生视图遮住可复制的编号。

真实桌面复核补修了 SQL 参数在关闭设置后丢失的问题，以及预览栏被纵向压缩、露出下层页面的问题；最终验收要求重新打开后保留编辑，并严格匹配 44px 预览栏与原生视图边界。展开设置后只显示一个标题，更多范围的情景摘要使用中文词表。

核心改动位于 `app/src/views/Analysis.tsx`、`Deliverables.tsx`、`TaskDetail.tsx`、`Preview.tsx`、`analysis.css`，以及 `app/src/views/analysis/` 下的 `FinanceWorkbench.tsx`、`AnalysisEditor.tsx`、`TechnicalInfo.tsx`、`RunPanel.tsx`、`DraftEditor.tsx`、`Methods.tsx`、`ReadinessPanel.tsx`、`RequirementsPanel.tsx`、结构确认和工作簿组件。验收脚本为 `tools/verify_ui_workspace.cjs` 与 `tools/verify_ui_section7_pages.cjs`。

## 验收结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| Python（不重复运行应用门禁） | 2118 通过，15 跳过 | [backend.log](../../build/manager-ux-section7-acceptance/logs/backend.log) |
| 应用门禁 | 4 通过，包含前端测试、类型与静态边界检查 | [app.log](../../build/manager-ux-section7-acceptance/logs/app.log) |
| Vitest | 53 文件、837 测试通过 | [vitest-run.log](../../build/manager-ux-section7-acceptance/logs/vitest-run.log) |
| TypeScript 与 Vite 构建 | 通过 | [build.log](../../build/manager-ux-section7-acceptance/logs/build.log) |
| harness / foundry / formulator 资源检查及 Formulator 门禁 | 均通过 | [门禁日志](../../build/manager-ux-section7-acceptance/logs/formulator-gate.log) |
| 候选包与构建一致性 | 42 文件逐字节一致；按配置排除 32 个 source map | [package-verification.json](../../build/manager-ux-section7-acceptance/package-verification.json) |
| 工作区真实桌面 | 17 组检查通过，两个阶段均执行，无跳过项 | [verification.json](../../build/manager-ux-section7-acceptance/verification.json) |
| 成果库、任务详情、原生预览 | 34 项检查通过；两条入口、浅深色与 1280/1080 窗口均通过 | [pages/verification.json](../../build/manager-ux-section7-pages/verification.json) |
| 视觉复核 | 95/100，通过阈值 90；人工截图判断 | [visual-verdict.json](../../build/manager-ux-section7-acceptance/visual-verdict.json) |

应用门禁中的前端测试不与 Vitest 重复计数。仓库无独立 lint 脚本，使用现有类型检查、静态边界检查和 `git diff --check`。

最终候选包的 `app.asar` SHA-256：

```text
f0c0d00d2408c484b012b163cf75b19e09f50d8097176065eaf621142e6a9dbc
```

两组桌面证据记录相同的候选包摘要。工作区检查包含真实参数修改与重算（利润 250 → 240）、关闭后保留编辑、成功后关闭抽屉、范围保存与重载、原始 Decimal 值、文稿引用、方法复用参数留空，以及保存新稿并导出有效 XLSX。预览检查确认技术信息展开时原生视图隐藏、收起后恢复原边界，预览栏恒为 44px，原生视图起点与栏底对齐。

共保存 113 张 PNG（工作区 85、页面专项 28），包括 renderer、原生视图和完整窗口。关键截图：[设置抽屉](../../build/manager-ux-section7-acceptance/calculation-settings-1280-window.png)、[深色财务范围](../../build/manager-ux-section7-acceptance/finance-settings-dark-1080-window.png)、[方法库](../../build/manager-ux-section7-acceptance/method-library-advanced-dark-1080-window.png)、[文稿引用](../../build/manager-ux-section7-acceptance/draft-references-1280-window.png)、[任务详情预览](../../build/manager-ux-section7-pages/task-detail-preview-light-1280-window.png)、[窄窗口深色预览](../../build/manager-ux-section7-pages/task-detail-preview-dark-1080-window.png)。

完整变更文件、删除项及摘要见 [source-manifest.json](../../build/manager-ux-section7-acceptance/source-manifest.json)。验收日志、截图和未签名候选包保留在本机 `build/` 下；可复跑脚本与本报告随源码提交。

## 验收边界

使用隔离目录与合成资料，不写入用户工作数据。桌面验收不调用模型，仅证明界面、真实本地计算、保存与导出流程；不代表模型效果评测。候选包用于本地验收，不包含签名、公证、替换安装版本或发布操作。

金额继续保持 Decimal 字符串，计算、复现、审阅与发布状态独立；引擎原始 Refusal 保留。没有新增依赖。

保留既有非失败提示：jsdom canvas / localstorage、Vite 大分块、打包默认图标。原工作簿内容原样预览，本次只收敛应用界面的编号展示。没有剩余已知验收阻塞。
