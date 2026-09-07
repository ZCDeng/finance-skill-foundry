# FA Foundry 前端优化复核 · 2026-09-08

结论：**REQUEST CHANGES**。shadcn 原语已接入部分界面，但重复边框仍可在安装版复现，财务字段仍使用旧控件，原生 harness 的紧凑布局和主题适配也没有达到统一工作区的视觉要求。

独立复核：代码审查为 REQUEST CHANGES，架构审查为 WATCH。主线结合当前代码和安装版证据，将以下视觉/集成问题统一评为 P2；没有确认到关键工具不可达或需要重写原生运行机制的架构阻断。

本次按“审核”执行：读取原始设计与验收要求、审查提交、检查实际安装版、运行前端回归；未修改产品实现、安装包或用户业务数据。

**范围与版本**

- 实际仓库：`/Users/zcdeng/projects/finance-skill-foundry`。任务原 cwd `/Users/zcdeng/projects/mySkills/finance-skill-foundry` 已不包含当前前端源码。
- 审查差异：`dd2d6e8..89062b6`，共 41 个文件，其中 40 个位于 app。相关提交在本地时区为 2026-09-07 19:43、20:58、23:34：`983e0e9`、`813d29e`、`89062b6`。
- 对照：`DESIGN.md`；`docs/plans/2026-09-06-ui-interaction-design-proposal.md`；`docs/plans/2026-09-06-ui-execution-log.md`；`docs/reviews/2026-09-06-ui-finish-review.md`；`app/harness-client/README.md`。
- 当前运行程序：`/Applications/FA Foundry.app`，版本 0.1.5。通过 CUA 读取实际窗口与原生会话，复现资料页账簿字段聚焦，检查 400px、460px 对话栏。
- 安装包中的 `dist-vite/assets/index-DUhYGW3N.css` 与本地同名 dist 文件字节一致，SHA-256 为 `e45066089a0db460306ea63199261793683231d1e90ee77b21679079edd5941f`；`dist-electron/harness/skin.js`、`pane.js` 也分别一致。没有证据支持把截图问题归因于未安装新 CSS。

**1. [P2] Hover 与 focus-visible 同时把字段画成金色，双边框修复没有覆盖实际触发状态。**

证据：`app/src/components/FinancialControls.tsx:47`；`app/src/components/components.css:384`、`:403`；`app/src/views/analysis.css:78`；`app/src/components/ui/input.tsx:15`；`app/src/styles/base.css:83`。

截图中的账簿来自 `SourceRefreshPanel` 的 `TextField`，最终是 `<input className="fnd-field">`，没有使用新增的 shadcn `Input`。悬停把原有 1px 边框染成金色；获得焦点又绘制 2px 同色 outline，并留出 1px 间距。鼠标点击字段后两种状态同时成立，因而出现截图中的内外两道金边。安装版现场点击同一字段可以复现。

即使把 TextField 机械替换为 Input，也不能单独解决问题：新 Input 仍有金色 hover border，宿主仍会添加全局/分析区 focus outline。必须先统一状态规则，再让所有字段复用它。

建议：普通输入的默认、悬停、聚焦、错误、禁用状态由同一处定义。可保留可访问的 focus outline，但在 focus-visible 时让普通 hover border 恢复中性色；或选择一个替代边框的单一聚焦指示。不要全局删掉键盘焦点。错误状态和复合日期/金额字段应分别规定优先级，避免内外两个元素同时绘制焦点。

归属：旧 TextField 路径的遗留问题，本轮以“避免双金边”为目的的修复遗漏；新 Input 也保留同类组合风险。

**2. [P2] 年月选择按钮被通用类覆盖，超出输入框。**

证据：`app/src/components/financial-controls.css:80`、`:93`；`app/src/components/FinancialControls.tsx:190`。

日历按钮同时具有 `.fnd-control-icon` 和 `.fnd-control-icon--calendar`。前面的 modifier 指定 26×26px，后面的通用类以相同选择器权重覆盖为 `height: 32px`、`min-width: 42px`。结合 `top: 3px`，它会伸出 32px 输入框下沿。尺寸结论来自 CSS 级联推导，用户截图和安装版可视外观与之相符。

建议：通用类在前、modifier 在后，或用明确的组合选择器限定内嵌图标按钮；统一设置 width/min-width/height，并保证图标按钮边界包含于输入框。复核月份、日期、金额等复合控件，不能仅检查文本字段。

归属：现存组件缺陷，本轮共享控件优化未修复。

**3. [P2] 新增的未分层覆盖继续压过 Tailwind 状态规则。**

证据：`app/src/styles/base.css:2`、`:83`、`:88`、`:96`；`app/src/components/components.css:38`、`:48`、`:56`；`app/src/components/ui/button.tsx:32`；`app/src/components/ui/tabs.tsx:59`。

Tailwind utilities 位于 layer，公共 CSS、页面 CSS 和新增的 data-slot 修补规则仍未分层。普通声明的级联中，未分层规则优先于这些 utilities。这不仅影响 outline：例如 components.css 固定 ghost/link 按钮和未选中 tabs 的文字颜色，会压过组件文件中定义的 `hover:text-foreground`。全局 `font: inherit` 也会接管原语中声明的字号、行高等属性。

这意味着 JSX 中出现 hover/focus/字号类名，并不代表这些视觉行为最终生效。最后一次修复主按钮文字对比度的方向合理，但继续添加同类外层覆盖会使各状态分散在更多文件中。

建议：明确 tokens、基础样式、组件、页面布局、utilities 的级联顺序。组件负责控件状态，页面负责空间布局；财务 TextField 复用公共输入基础样式，业务校验与期间/Decimal 行为仍留在财务层。无需为了统一视觉重写已经可用的业务控件。

归属：shadcn 迁移后的集成问题，最新修补继续扩大了未分层覆盖。

**4. [P2] Harness 顶部存在重复的空间预留，业务内容位置被无效层级挤压。**

证据：`app/src/components/Workspace.tsx:180`；`app/src/components/workspace.css:30`；`app/harness-client/compact.css:3`、`:5`、`:9`、`:11`。

宿主先为“分析助手”保留 40px 标题行，原生适配又为右上设置按钮保留 34px 顶部空间；下面仍有原生会话标识/Session log 行与对话/轨迹页签。也就是说，在原生会话头部之前已经额外占用了 74px。截图及 400/460px 安装版检查均保留这些层次，原始会话 hash 占据显著位置，左右面板的首行内容也难以对齐。

这里已有真实的紧凑客户端适配、持久会话和原生矩形契约，不能说完全没有适配。问题是适配偏重运行与可达性，没有完成信息层级重排。本次没有观察到 400/460px 下模型菜单、访问模式等关键控件完全消失，不把空间粗糙夸大成工具不可达。

建议：在现有原生适配里合并会话顶栏，把对话/轨迹、设置、会话详情入口组织在一个紧凑区域；会话 hash 和 Session log 放在可达的详情/更多入口。宿主已有任务名称，减少重复标识。权限模式保留真实、明确的可访问入口，原始 permission 日志可在轨迹中查看。维持 session、draft、admission、队列、工具审批与 ask_user 的现有运行机制。

归属：既有视觉债务，此次 shadcn 迁移范围没有触及。

**5. [P2] Harness 使用独立主题，壳内的 shadcn token 桥接无法统一原生视图。**

证据：`app/electron/harness/skin.ts:31`、`:60`、`:68`、`:76`；`app/harness-client/compact.css:16`；`app/src/styles/shadcn-bridge.css:9`。

原生会话位于单独的 WebContentsView，宿主的 CSS 变量不会自动跨文档继承。目前 skin 固定使用深色金值，并通过 `[class*="_card"]` 和 `!important` 常驻覆盖边框；没有建立与宿主默认/悬停/焦点/禁用相同的语义状态。安装版中输入器未聚焦时仍是金色边框，原生页签和发送按钮仍使用蓝色，与右侧宿主控件呈现两套交互色彩。

建议：在固定版本的原生适配层映射 DSH 的语义颜色、密度和圆角；规则限定到已检查的容器或 `data-composer-card`。默认使用中性边界，聚焦再强调。保留版本 pin、适配摘要与升级检测，逐步替换宽泛 class substring + 常驻 !important 的边框覆盖。

归属：旧 skin 的边界问题，shadcn token 桥接仅覆盖宿主，未覆盖原生文档。

**验证为何放过了这些问题**

`app/tests/views.test.tsx:865` 仅抽取 `.fnd-field:focus-visible` 这一段 CSS，断言其中没有 `border-color`。它没有把 hover 规则一起计算，因此双金边存在时仍能通过。`views.test.tsx:844`、`:874` 同样偏向检查类名/源码字符串，不能证明最终对比度或 hover 状态。原生几何和会话回归有价值，但不能替代对标题密度、控件边界和主题状态的视觉验收。

本轮实际运行：`npm test -- --reporter=dot`，30 个测试文件、420 项全部通过；`tsc -p tsconfig.json --noEmit` 与 `tsc -p tsconfig.electron.json --noEmit` 均通过；`git diff --check` 通过。`node scripts/fetch-harness.mjs --check` 也通过，当前固定 runtime 为 `@deepseek-ai/dsh@0.1.1-rc.2`。测试输出有既有 workbook fixture 的重复 React key `3` 提示。

安装版 Console 还观察到一条 inline style 被 CSP `style-src 'self'` 阻止的消息。本次未确认对应功能后果，不将其作为已证实的 UI 缺陷或新增阻断项。

**建议的修复顺序与完成条件**

1. 先修公共控件状态与日历 modifier 顺序，再收敛未分层覆盖。以真实 Chromium/Electron 渲染验证默认、hover、键盘 focus、鼠标 focus、hover+focus、invalid、disabled；同时包含普通字段、shadcn 字段、日期/金额复合字段和按钮。
2. 重排现有 harness 适配的顶部层级，再补齐独立文档的主题映射。合并重复行、降低原始会话元数据的默认权重，保留关键权限、模型、附件、停止与工具入口。
3. 整理空任务资料页：主要动作集中于添加资料/提问，ERP 刷新表单按需展开。当前无条件渲染完整来源表单属于可优化的信息层级，不单独认定为功能错误。
4. 新包验收同时采集宿主与 WebContentsView 的整窗画面。覆盖 1280×800、400/460px 对话栏、专注模式、深浅主题；检查每个交互状态，而不只补拍静态空态。新增布局调整后重跑原生可见性、任务切换、草稿、审批、工具详情与焦点回归。

修复完成前，不宜将当前状态标为“边框修复完成”或“统一视觉验收通过”。本轮产物是这份审查记录；没有提交或推送改动。
