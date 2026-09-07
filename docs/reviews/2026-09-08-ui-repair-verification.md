# FA Foundry 前端完整修复验收 · 2026-09-08

结论：**PASS，已安装并启动 0.1.6**。本次按用户“按照你的顺序全量修复”的授权，完成前次审查的五项问题、资料页信息层级整理及安装版验证。代码与架构独立复核均为 **APPROVE**，未发现剩余阻断项。

前置记录：[原始审查](/Users/zcdeng/projects/finance-skill-foundry/docs/reviews/2026-09-08-frontend-shadcn-harness-review.md)、[修复计划](/Users/zcdeng/projects/finance-skill-foundry/docs/plans/2026-09-08-ui-repair-plan.md)。原始审查保留修复前的结论和证据。

## 修复结果

| 原问题 | 最终行为与改动 |
| --- | --- |
| 字段 hover 与 focus 叠出双金边 | Input、Textarea、财务字段复用同一状态定义；聚焦 outline 为 2px、offset 为 -1px，普通 hover 不覆盖聚焦、错误和禁用状态。账簿鼠标点击与键盘焦点均已真实渲染复核。 |
| 日历按钮超出输入框 | 通用规则先定义、calendar modifier 后定义；26×26px 图标按钮完整包含于 32px 输入框内。 |
| 外层 CSS 压过 shadcn utilities | 明确 theme → base → components → layout → utilities；删除重复 data-slot 状态补丁和字体覆盖，字号、hover、focus 由控件定义，页面保留布局。 |
| Harness 顶栏多层重复 | 删除宿主“分析助手”行和原生多余顶部留白；对话/轨迹、会话信息和设置整合在 44px 顶栏。原始 lineage、任务标识与 Session log 放入可展开详情，Escape 关闭并恢复焦点。 |
| Harness 与宿主主题分离 | 根据原生 resolved theme 映射深浅语义色；输入器默认中性边界，交互时强调；页签、发送和设置关闭按钮焦点统一。用精确 composer/按钮选择器替代宽泛 card/primary 匹配。 |
| 空资料页被 ERP 表单占据 | 添加资料、讨论成为主要动作；“更新 ERP 来源”默认收起，展开后原表单、校验与刷新路径保留。 |
| SQL 结果被业务设置挤出首屏 | 完整窗口验收中发现并补修：任何已有成功运行都默认收起业务设置；显式展开仍可用。1280×800 下计算结果表顶部由约 829px 回到 418px。 |

未新增依赖，未改变财务计算、权限、会话 admission 或用户数据。仅应用版本从 0.1.5 更新为 0.1.6。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 前端全量 Vitest | **30 个文件、429 项通过**。 |
| TypeScript | 宿主与 Electron 两套配置通过；使用 app 本地 TypeScript 5.9.3。 |
| Chromium 控件状态 | **72/72 通过，两轮一致**；深浅主题各 36 项，包括鼠标/键盘/hover+focus、invalid、disabled、日期/金额几何和按钮字体/前景色。 |
| 修复前对照 | 同一真实组件 fixture 和完整 CSS，干净旧快照两轮均有 **28/72 项失败**，证明新增检查能发现原缺陷。 |
| 原生工作区 | 最终包 **42/42 通过**：400/460px 几何、主题、设置、会话详情、Escape 焦点、A→B→A 草稿与文档驻留、隐藏/显示、缩放、无效/过期布局、输入合成与合成 admission 去重。 |
| 完整业务流程 | **7 项通过、13 个场景无横向溢出**；覆盖 1440/1280/1080 宽度、资料与结果、两次真实 SQL 计算、参数改版、原资料快照、版本比较、证据抽屉、文稿、工作簿导出和重命名持久化。 |
| Excel 复核 | 文稿标题/正文/版本、全部结果单元格及引用运行 ID 与保存记录一致；DECIMAL 列按数值比较，并保持文本与数值单元格边界。另验证修改一个财务单元格会被校验器拒绝。 |
| 打包与静态检查 | `npm run package` 通过 harness、Foundry、Formulator 摘要与运行门禁、两套类型检查、Vite 和 Electron 打包；三个 QA 脚本语法检查与 `git diff --check` 通过。仓库未配置独立 lint 命令。 |
| 独立审查 | 代码审查与原生架构审查均 APPROVE；最后增量复核另运行了 107 项针对测试。 |
| 视觉验收 | 已人工查看包含宿主及 WebContentsView 的整窗图、原生 400/460px 图和控件深浅主题图；最终视觉评分 **94/100，PASS**，仅表示本次修复范围。 |

业务验证使用隔离 QA 资料目录与真实打包 CLI。模型 admission 和工具历史使用明确的合成夹具，真实模型请求计数为零；未将这些检查表述为真实供应商运行成功。

证据目录：[build/ui-repair-20260908](/Users/zcdeng/projects/finance-skill-foundry/build/ui-repair-20260908)。包含单测及打包日志、两轮旧快照控件报告、当前控件报告、原生报告、业务报告、Excel 校验、安装摘要、视觉 verdict 和截图。此目录为本机生成的忽略产物。

- [账簿焦点与日历整窗图](/Users/zcdeng/projects/finance-skill-foundry/build/ui-repair-20260908/materials-focus-dark-1280-window.png)
- [ERP 收起后的资料页](/Users/zcdeng/projects/finance-skill-foundry/build/ui-repair-20260908/materials-collapsed-1280-window.png)
- [1280×800 结果首屏](/Users/zcdeng/projects/finance-skill-foundry/build/ui-repair-20260908/results-1280-window.png)
- [原生 400px 设置页](/Users/zcdeng/projects/finance-skill-foundry/build/ui-repair-20260908/native-settings-400.png)
- [原生会话详情](/Users/zcdeng/projects/finance-skill-foundry/build/ui-repair-20260908/native-session-metadata-400.png)

## 安装版核对

- 安装位置：`/Applications/FA Foundry.app`；Info.plist 版本 **0.1.6**。
- 已退出旧程序后替换应用，并通过 CUA 从 `/Applications` 重新启动和读取完整窗口。
- `app.asar` 加全部 33 个原生客户端 bundle，共 **34 个文件**，安装版与最终测试包 SHA-256 全部一致。
- `app.asar` SHA-256：`446ba096d364bbb91c8ba797d08b08b44ef5ac5f48f5b27e10c39206ef2df3ba`。
- CUA 现场验证：原任务 `newtask` 和原会话身份保留，DeepSeek-V4-Flash / Max、Full access 保留；紧凑顶栏、会话日志入口、Escape 焦点恢复、420px 原生设置页、ERP 默认收起、账簿单边聚焦及日历包含关系均已检查。
- 0.1.5 可恢复备份：`/Users/zcdeng/Downloads/FA-Foundry-backup-20260908/FA Foundry.app`。未移动或清理用户业务资料与配置。
- 继续使用现有本地打包/签名配置；这次交付不等同于公证或公开发布。

## 改动文件与简化

| 文件组 | 责任与简化 |
| --- | --- |
| `app/src/styles/base.css`、`tokens.css`；`app/src/components/components.css`、`financial-controls.css` | 建立级联顺序、统一字段状态、修正日历包含关系，删除重复覆盖。 |
| `app/src/components/ui/{input,textarea,button,tabs,badge,dropdown-menu}.tsx`；`FinancialControls.tsx` | 共享输入基础样式；去除吞掉字号的字体简写，恢复真实 variant/utility 行为；财务行为保留。 |
| `app/src/components/Workspace.tsx`、`workspace.css` | 删除重复标题行，搜索/重命名复用输入原语。 |
| `app/src/views/Analysis.tsx`、`analysis.css`、`analysis/RequirementsPanel.tsx` | ERP 按需披露、资料主要动作、Textarea 复用、成功结果优先。 |
| `app/scripts/adapt-harness-client.mjs`、`app/harness-client/compact.css`、`README.md`；`app/electron/harness/skin.ts` | 固定版本适配、44px 顶栏、保留原始槽位、精确主题映射与焦点规则。 |
| `app/tests/{analysis,client-adapter,skin,views}.test.*`、`app/tests/fixtures/control-states.{tsx,html}` | 增加行为与适配回归，用浏览器检查替换无法证明最终视觉效果的 CSS 字符串测试。 |
| `tools/verify_control_states.cjs`、`verify_native_workspace.cjs`、`verify_ui_workspace.cjs`、`verify_ui_workbook.py` | 渲染状态、原生交互、整窗业务及 Excel 内容验证。修正 QA 对导出菜单角色及数值单元格的过时假设。 |
| `DESIGN.md`、`app/package.json`、`app/package-lock.json`、本次计划/审查记录 | 同步设计约定、0.1.6 版本与交付证据。 |

剩余验证边界：未覆盖物理 macOS 中文输入法候选窗及真实模型供应商流式执行；原生适配依赖 pinned bundle SHA 和 DOM，升级 DSH 时必须重跑适配检查与原生回归。

本次未提交或推送。工作区原有无关的根目录 `node_modules/`、`package.json`、`package-lock.json`、`uv.lock` 保留。
