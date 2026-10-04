---
name: FA Foundry
description: 以任务、持续对话与真实成果组织的财务经理工作台。
colors: {fnd-bg: '#ffffff', fnd-surface: '#ffffff', fnd-surface-strong: '#f7f7f7', fnd-ink: '#000000e0', fnd-muted: '#00000099', fnd-line: '#1f1f1f24', fnd-accent: '#1f1f1f', fnd-on-accent: '#f9fafb', fnd-selection-surface: '#efefed', fnd-line-hover: '#1f1f1f66', fnd-focus: '#8a6729', fnd-selected: '#8a6729', fnd-on-selected: '#f9fafb', fnd-warning: '#a3372b', fnd-warning-line: '#c96a5c', fnd-warning-fill: '#c96a5c1f', fnd-bg-dark: '#111111', fnd-surface-dark: '#1f1f1f', fnd-surface-strong-dark: '#161616', fnd-ink-dark: '#f9fafb', fnd-muted-dark: '#a6a6a6', fnd-line-dark: '#ffffff24', fnd-accent-dark: '#f9fafb', fnd-on-accent-dark: '#1f1f1f', fnd-selection-surface-dark: '#292929', fnd-line-hover-dark: '#ffffff59', fnd-focus-dark: '#bfa36c', fnd-selected-dark: '#e2c180', fnd-on-selected-dark: '#1f1f1f', fnd-warning-dark: '#eb9a8c', fnd-warning-line-dark: '#eb9a8c', fnd-warning-fill-dark: '#eb9a8c1f'}
typography:
  headline: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 24px, fontWeight: 600, lineHeight: 32px}
  task-title: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 20px, fontWeight: 600, lineHeight: 28px}
  title: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 16px, fontWeight: 600, lineHeight: 20px}
  body: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 14px, lineHeight: 22px, letterSpacing: '0'}
  small: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 13px}
  label: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 12px}
  document: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 16px, lineHeight: 28px}
  document-title: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 28px, fontWeight: 750, lineHeight: 40px}
  document-chapter: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 22px, fontWeight: 720, lineHeight: 32px}
  document-section: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 18px, fontWeight: 700, lineHeight: 28px}
  composer: {fontFamily: '''Noto Sans SC'', sans-serif', fontSize: 16px, lineHeight: 28px}
  brand: {fontFamily: '''Asap Sharp'', ''Noto Sans SC'', sans-serif', fontSize: 22px, fontWeight: 700, lineHeight: 1}
rounded: {control: 8px, container: 12px, chip: 30px, mark: 6px, menu: 10px}
spacing: {control-gap: 8px, compact: 8px, small: 12px, grid-gap: 20px, workspace-gap: 20px, gutter: 24px, section-gap: 32px}
components:
  button-primary: {backgroundColor: '{colors.fnd-accent}', textColor: '{colors.fnd-on-accent}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 14px, height: 36px}
  button-secondary: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 14px, height: 36px}
  input: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 12px, height: 36px}
  nav-current: {backgroundColor: '{colors.fnd-selection-surface}', textColor: '{colors.fnd-selected}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 16px, height: 36px}
  chip: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.label}', rounded: '{rounded.chip}', padding: 4px 10px}
  card: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', rounded: '{rounded.container}', padding: 18px 20px}
  workspace-tab: {backgroundColor: transparent, textColor: '{colors.fnd-muted}', typography: '{typography.small}', padding: 12px 0}
---

# Design System: FA Foundry

## Overview

**Creative North Star: "财务经理的任务工作台"**

沿用 FA 标识、中性色与金色定位。业务问题、计算值与文稿承担主要层级；财务经理可以持续讨论并查看成果，专业判断和方法复用保留为用户可控动作。此名称概括已有产品定位，未新增品牌概念、comp 承诺或长期工作流偏好。

本记录合并既有设计约定，描述 2026-09-08 的实际界面。样式来源为 [tokens](app/src/styles/tokens.css)、[base](app/src/styles/base.css)、[公共控件](app/src/components/components.css)、[工作区](app/src/components/Workspace.tsx)和[成果样式](app/src/views/analysis.css)；产品事实见 [PRODUCT.md](PRODUCT.md)。

**Key Characteristics:**

- FA 图形与 Asap Sharp 品牌字；离线 Noto Sans SC 中文工作界面。
- 中性平面、细分隔线、有限容器与金色交互定位。
- 持续对话与成果并排，空间不足时使用同任务专注视图。
- 按真实参数、来源、版本和状态呈现结果与文稿。

## Colors

主操作使用 `fnd-accent/on-accent` 的中性反差。标题栏品牌字「FA Foundry」用 `fnd-selected` 金色。标题栏按钮平时用次要文字色、透明底，悬停时文字变金；当前页签用金色文字、选择底色，标签下方加一条 1px 金色下划线，当前位置因此不只靠颜色区分；键盘聚焦保留所在状态，另加 1px `fnd-focus` 焦点框，不改文字颜色。这几条只写在 `.fnd-head` 里，其他页面复用 `.fnd-head__tab` 的返回按钮和 Formulator 按钮保持中性。`fnd-selected` 作文字时，浅色在标题栏白底上 5.18:1、在选择底色 #efefed 上 4.50:1，正好压在下限，改这两个 token 前先跑 tokens.test.ts；深色分别为 9.55:1 和 8.43:1。品牌字和页签都保持静态，2026-09-27 试做的两个动效按门槛撤回。metal-fx 的 MetalText 材质固定为 chromatic，浅色下品牌字读成灰色，对比度最低 4.33:1；liquid-gooey 的滑动指示器每次切换后约 40 秒持续重绘，空闲时渲染进程和 GPU 占用都上升。成果页签同样用 1px 金色下划线。`fnd-line-hover` 用于中性悬停边界，`fnd-focus` 仅用于焦点框，`fnd-selection-surface` 用于任务及布局选择底色。背景、容器、次要层、正文、次要文字和分隔线分别对应 `bg/surface/surface-strong/ink/muted/line`。

警告、错误、不可逆删除和输入错误使用砖红警示色 `fnd-warning`，文字用主色，边用 `fnd-warning-line`，浅底用 `fnd-warning-fill`。浅色主色 #a3372b 在白底上 6.69:1，深色主色 #eb9a8c 在 #1f1f1f 上 7.48:1。三件一起换，警示文字旁边不留金色边或金色浅底。

前置 YAML 的 `-dark` 项是同名 CSS token 的深色覆盖值。壳跟随系统主题；原生对话在自身主题完成解析后，通过 DSW 语义别名映射同一套底色、文字、边界、金色强调色和警示色；原生的错误色和危险悬停底映射到 `fnd-warning` 与 `fnd-warning-fill`。原生 composer 默认中性边界，悬停保持中性色，仅在聚焦时使用 1px 金色边界。历史标记保留原有金色、灰色、蓝色语义，FA 图形保持自身颜色。

**The Location Rule.** 金色只服务于品牌、当前位置、选择、焦点和原有的历史标记（稿外追问 chip）；警告、错误、删除和输入错误一律用警示色，不用金色。标题栏按钮平时保持中性，只在当前页签、悬停和聚焦时出现金色。主操作使用既有中性反差，数值与业务状态保留文字。

## Typography

Noto Sans SC 用于中文正文、标题、输入和控件，完整 WOFF2 随壳和原生客户端离线打包，真实变量字重 100–900，关闭合成字重；不依赖 localhost 或远程字体。Asap Sharp 仅用于品牌字。见[字体来源与许可](app/src/assets/fonts/noto-sans-sc/README.md)。

任务标题 20px，窄窗为 18px；结果页结论优先，首句脚本结论 22px/32px、其余 18px/28px，所问问题作为结果标签 16px（没有脚本结论时仍为 20px 标题）。文稿标题 28px/40px（字重 750）、章 22px/32px（720）、节 18px/28px、小节 16px/26px（700），编辑器、阅读视图与导出 HTML 共用 `--fnd-doc-*` token（h4 至 h6 同用小节字号；旧草稿阅读样式一并对齐），由 `document-headings.test.ts` 保持一致。壳与原生对话共用 14px/22px 控件字号，标签 13px、元信息 12px；文稿正文、原生消息和输入共用 16px/28px。文稿最大宽度 42em，段后 18px、章前 32px；Markdown 的最浅标题深度映射到正文一级章节，保留相对层级。代码使用 `ui-monospace`。全局启用 `tabular-nums`，结果数值列按真实列类型右对齐。

**The Real Weight Rule.** 中文强调使用已打包的真实字重；数据保留原有精度、负号、零和缺值，不借排版制造业务含义。

## Layout

工作区铺满窗口，不受普通页面 1200px 上限约束；应用顶栏 56px，任务栏最小 64px。当前桌面最小窗口宽度为 1080px。初次挂载在 ≥1360px 默认显示 256px 任务栏；1101–1359px 默认收起，打开时为 288px 模态抽屉；≤1100px 将默认并排状态显示为成果专注，并保留对话/成果切换。

进入窄布局收起任务栏，放大后保留收起状态，不承诺 1440px 自动展开。专注选择按任务保留。对话默认 420px，可调 400–640px；7px 分隔条支持拖动、左右键每次 20px、Home/End 到边界，双击恢复默认值。

对话与成果独立滚动，成果区 scrollTop 按任务保留；资料、结果、文稿复用该成果滚动容器，不承诺按三个页签分别恢复滚动。成果留白为顶部 24px、左右 24px、底部 32px，窄窗左右保留 20px；原生对话采用相同字号与边缘留白。侧栏以标题、搜索、两行任务项和固定底部入口组织，任务名称 14px、期间 12px。依据抽屉最大 340px，结果容器 ≤620px 时局部覆盖；比较为两列，≤680px 逻辑视口回退单列。这些 CSS 回退不构成移动端交付承诺。

## Elevation & Depth

工作区使用底色、细边框和留白；结果、计算定义以平面行与下边线分隔。现有帮助面板保留柔和阴影与径向底色，不推广到数据卡片。任务抽屉、壳弹层、成果专注、新任务及分隔条拖动期间实际隐藏原生层；结束后恢复会话，零尺寸不能替代可见性控制。原生工具详情在对话内占满整栏。

通用壳控件过渡为 `180ms ease`，时长与缓动独立为 `fnd-duration/easing`，`prefers-reduced-motion` 将时长归零；不据此承诺第三方原生客户端全部动画均已覆盖。sidecar 色阶为面板插值预览，非产品 token；组件片段仅展示现有外观与 CSS 状态。

## Shapes

控件和任务行使用 `control` 圆角，独立资料卡、文稿输入与依据使用 `container`，小图标操作使用 `mark`，工具菜单使用 `menu`，历史 chip 保留原形。内容以细分隔线组织，避免把每个标题和操作组包成卡片。沿用线性 SVG 控件，装饰图标不进入无障碍名称。

## Components

**按钮与字段。** 主操作实心，次操作细描边；常规按钮、输入和选择框高 36px（紧凑图标动作 32px），长示例允许换行增高。次操作/输入悬停为中性边界，主按钮没有额外悬停变色，按下时略降透明度或使用选择底色。字段组合为标签、控件、帮助或错误；`aria-invalid` 与警告边使用 `fnd-warning-line`，错误文字使用 `fnd-warning`。通用焦点外框 1px、偏移 -1px，与原边界重叠成单一指示；聚焦、错误或禁用的字段不叠加普通悬停边色。原生选择框与财务输入沿用同一字段状态。主按钮文字使用 `on-accent`，暗色下不得继承 ink。禁用使用真实 disabled 与既有透明度。工具菜单、选择弹出层和导出菜单共用 `fnd-shadow-menu`；抽屉遮罩使用 `fnd-overlay`。成果页签为下划线式 tab，未选中悬停变为正文色。参数显示真实业务名称、类型、单位和约束，未标注语义的旧参数按原名留在高级区。不可逆删除使用次操作的 destructive 变体（`fnd-warning` 砖红文字与 `fnd-warning-line` 边，悬停为 `fnd-warning-fill`）。薄控件（按钮、简单输入、成果页签、菜单）来自 shadcn 原语，视觉仍只读 `--fnd-*` token。

**导航与焦点。** 顶层为工作区/成果库，方法库、数据台、历史任务从次级入口可达。资料/结果/文稿用带计数的 tablist，支持左右键、Home/End 与 roving tabindex。任务抽屉聚焦搜索、限制 Tab、使主工作区 inert；Escape 关闭并返回开关。图标动作有名称和状态，分隔条提供方向与数值。

**持续对话。** 任务切换和隐藏/显示保留会话与未发送草稿；完整问题按准确任务转交，实际接收成功才确认提交，受阻时保留问题并允许重试，同一动作不重复发送。400/460px 设置与工具详情已有验收；这不等于未来客户端版本无需适配。

**结果与依据。** 先展示运行问题（16px 标签）、日期、四项独立状态，随后以 22px 脚本结论领起真实结果；定义、历史及方法保存按需展开。失败明确说明当前保留的是历史成功结果。表格使用中性横线与 10px 以上单元格内边距。Python/shell 结果包含明确的 label/value/unit 字段，且其余列仅为 metric、wb、sheet、cell、note、check 等已知依据字段时，先显示项目、数值、单位，完整原始列通过“完整明细”展开；额外数值列或未知字段继续默认显示全表。不改变精度、行序、缺值或财务专用展示。表格具备 caption、列标题、可聚焦横向滚动区，每页最多 100 行，截断明确提示，缺值显示“—”。依据按本次运行绑定定位确切快照；非模态 dialog 打开聚焦关闭按钮，Escape 返回触发按钮。参数/假设优先用保存版本的元数据；比较并列保存运行及原行序，不推断主键或差额。

**文稿与方法。** 文稿支持 Markdown 阅读和独立编辑，借鉴 Kami 的行长、章节留白与轻表格规范。仅当已保存的计算依据与正文末尾完全匹配时，阅读区将该附录折叠，编辑和导出仍保留完整正文；旧版和不匹配内容直接呈现。工作副本按任务/版本使用会话级存储恢复，正式保存生成新版本；交给助手或导出前先保存改动。改正文不替换已引用的历史运行，导出、归档与经理认可分别操作。方法保存是折叠的可选动作，复用重新选择资料与参数；未来领域入口随实际能力出现。

**验证边界。** 已核对最终整窗图与[流程](build/ui-workspace-review/final/verification.json)、[比较补拍](build/ui-workspace-review/final/comparison-recapture.json)、[原生检查](build/verification/native-workspace-final.json)、[产物记录](build/verification/ui-final-artifacts.json)：26 项原生检查和 6 项界面流程通过，资料为合成 fixture，真实 provider 调用为 0。真实模型接收/流式响应、物理 macOS 中文候选窗、完整屏幕阅读器流程未验收。[最终 ship](docs/reviews/2026-09-06-ui-finish-review.md)仅覆盖 F1–F4 修复评分；详细实现与限制见 [UI 实施记录](docs/plans/2026-09-06-ui-execution-log.md)。

### shadcn 原语（2026-10-04）

底座保持 Radix（`radix-ui` 统一包），不迁到 Base UI；组件从 shadcn 结构出发，视觉只读 `--fnd-*` token，不跑 `shadcn apply` 覆盖。

- **字段结构。** `FieldShell` 使用 Field 结构（`field`、`field-label`、`field-description`、`field-error` 四个 data-slot），错误时字段带 `data-invalid`、控件带 `aria-invalid`，类名仍为 `fnd-control*`。
- **选择框。** 一律用 NativeSelect：仍是原生 `select`，菜单由系统绘制，能盖在原生视图之上；外层只加 16px 下拉箭头，字段状态与输入框相同（高 36px、`fnd-field`）。任务栏的选择框沿用 `fnd-picker` 尺寸。页面样式不再单独给 `select` 写边框和内边距。
- **勾选与开关。** 多选和逐项纳入用 Checkbox（16px，选中为主色底）；保存即生效的设置用 Switch（如「接受差异后需要第二人复核」）。两者均为 `role="checkbox"`/`role="switch"` 按钮，标签包住控件即可点击文字切换。
- **空状态。** 整屏或整块的空状态用 Empty（`empty`、`empty-header`、`empty-title`、`empty-description`、`empty-content`）：左对齐、弱色说明、不加卡片和插图；标题用 `asChild` 保留所在页面的标题层级，操作按钮放在 `empty-content`。面板里一句话的「还没有……」仍用普通说明文字。不引入 Toast（内联提示更符合结论优先）、`cn` 独立包和 Rhea 紧凑风格（与 36px 控件高度冲突）。
- **设置与高级。** 分析页和财务工作台共用一个 `SettingsPanel`（shadcn Collapsible）：在页面内原位展开、打开时替换入口，不做浮层，因为面板里有自带弹出层的搜索选择，计算结果也要留在下方可读。用户打开时焦点进入面板；之后无论 Escape、「关闭」还是计算成功自动收起，焦点都回到打开前的位置（已不在页面时回到入口），不会落到页面顶端。首次进入时默认展开的面板不抢焦点。

## Do's and Don'ts

- **Do** 沿用现有 FA 标识、离线字体、系统主题、真实任务归属与可见焦点。
- **Do** 用保存的名称、单位、参数、来源与版本支持财务经理自主判断。
- **Don't** 合并执行/复算/阅核/发布状态，猜测旧参数语义或添加不可用业务入口。
- **Don't** 把工作副本恢复写成跨重启正式自动保存，或把窄窗回退写成移动端承诺。
- **Don't** 将分区标题做成大写 tracking 的 kicker；章节用标题元素承担层级。未定义的选择色 fallback 或原生控件局部色差也不推广为全局规则。

## 样式级联与来源披露（2026-09-08）

宿主按 `theme → base → components → layout → utilities` 排序：token 提供颜色，base 提供继承和可访问焦点，组件持有控件状态，页面持有排版，显式 utilities 用于局部组件变体。禁止在层外增加控件颜色/字体/焦点补丁。Input、Textarea 与财务字段共用 `fnd-field`；复合年月、日期和金额仅增加自己的布局及业务行为。年月内嵌图标为 26×26px，垂直居中于 36px 输入内部。

空资料页优先展示添加资料与讨论入口。“更新 ERP 来源”默认折叠，展开后显示原有刷新表单，保留填写内容及新旧快照语义。

## 经营分析文稿（2026-09-08）

文稿入口整合版本、导入、阅读、编辑、打印预览与五格式导出。Tiptap 开源编辑器支持段落层级、列表、链接、本地图片、表格合并拆分、章节末编号附注和分页；Markdown 保留源码入口，转换前展示结构降级。目录独立可折叠，证据与校验结果独立于连续正文。

模板借鉴保利物业、海信家电和 Berkshire 年报的章节、比较表、单位和附注组织，结合 Kami 的阅读节奏。阅读正文沿用主题及离线 Noto Sans SC，16px/28px、约 42em 行长、至少 24px 内边距及 32px 章节间距。正式预览与 PDF 使用白底 A4、20mm 页边距、11pt 正文、至少 9pt 表格及附注；页眉页码统一。表格以细横线、重复表头及项目列组织长表和宽表，数字保持原始文本、精度与负号。章节只呈现已有内容，不自动补写管理结论。

[五格式实现与验收契约](docs/plans/2026-09-08-financial-documents-plan.md)记录结构模型、离线转换与安全边界。Excel 工作表/区域保留来源定位；PDF 原页与草稿对照，OCR 不可用时保留已提取内容并支持重试。导入文件不执行脚本，也不自动请求外部图片或链接。
