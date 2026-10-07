---
name: FA Foundry
description: 以任务、持续对话与真实成果组织的财务经理工作台。
colors: {fnd-bg: '#ffffff', fnd-surface: '#ffffff', fnd-surface-strong: '#f7f7f7', fnd-ink: '#000000e0', fnd-muted: '#00000099', fnd-line: '#1f1f1f24', fnd-accent: '#1f1f1f', fnd-on-accent: '#f9fafb', fnd-selection-surface: '#efefed', fnd-line-hover: '#1f1f1f66', fnd-focus: '#8a6729', fnd-selected: '#8a6729', fnd-on-selected: '#f9fafb', fnd-warning: '#a3372b', fnd-warning-line: '#c96a5c', fnd-warning-fill: '#c96a5c1f', fnd-negative: '#94463d', fnd-bg-dark: '#111111', fnd-surface-dark: '#1f1f1f', fnd-surface-strong-dark: '#161616', fnd-ink-dark: '#f9fafb', fnd-muted-dark: '#a6a6a6', fnd-line-dark: '#ffffff24', fnd-accent-dark: '#f9fafb', fnd-on-accent-dark: '#1f1f1f', fnd-selection-surface-dark: '#292929', fnd-line-hover-dark: '#ffffff59', fnd-focus-dark: '#bfa36c', fnd-selected-dark: '#e2c180', fnd-on-selected-dark: '#1f1f1f', fnd-warning-dark: '#eb9a8c', fnd-warning-line-dark: '#eb9a8c', fnd-warning-fill-dark: '#eb9a8c1f', fnd-negative-dark: '#d9a097'}
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
  figure: {fontFamily: '''IBM Plex Mono'', ''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 14px, fontWeight: 400, lineHeight: 22px}
rounded: {control: 8px, container: 12px, chip: 30px, mark: 6px, menu: 10px}
spacing: {control-gap: 8px, compact: 8px, small: 12px, grid-gap: 20px, workspace-gap: 20px, gutter: 24px, section-gap: 32px}
components:
  button-primary: {backgroundColor: '{colors.fnd-accent}', textColor: '{colors.fnd-on-accent}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 14px, height: 36px}
  button-secondary: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 14px, height: 36px}
  input: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 12px, height: 36px}
  nav-current: {backgroundColor: '{colors.fnd-selection-surface}', textColor: '{colors.fnd-selected}', typography: '{typography.body}', rounded: '{rounded.control}', padding: 0 16px, height: 36px}
  chip: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.label}', rounded: '{rounded.chip}', padding: 4px 10px}
  card: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', rounded: '{rounded.container}', padding: 18px 20px}
  card-compact: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', rounded: '{rounded.container}', padding: 16px}
  workspace-tab: {backgroundColor: transparent, textColor: '{colors.fnd-muted}', typography: '{typography.small}', padding: 12px 0}
  disclosure: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.body}', rounded: '{rounded.mark}', padding: 5px 8px 5px 32px}
---

# Design System: FA Foundry

## Overview

**Creative North Star: "财务经理的任务工作台"**

沿用 FA 标识、中性色与金色定位。业务问题、计算值与文稿承担主要层级；财务经理可以持续讨论并查看成果，专业判断和方法复用保留为用户可控动作。此名称概括已有产品定位，未新增品牌概念、comp 承诺或长期工作流偏好。

本记录合并既有设计约定，描述 2026-09-08 的实际界面。样式来源为 [tokens](app/src/styles/tokens.css)、[base](app/src/styles/base.css)、[公共控件](app/src/components/components.css)、[工作区](app/src/components/Workspace.tsx)和[成果样式](app/src/views/analysis.css)；产品事实见 [PRODUCT.md](PRODUCT.md)。

**Key Characteristics:**

- FA 图形与 Asap Sharp 品牌字；离线 Noto Sans SC 中文工作界面；离线 IBM Plex Mono 财务数字。
- 中性平面、细分隔线、有限容器与金色交互定位。
- 持续对话与成果并排，空间不足时使用同任务专注视图。
- 按真实参数、来源、版本和状态呈现结果与文稿。

## Colors

主操作使用 `fnd-accent/on-accent` 的中性反差。标题栏品牌字「FA Foundry」用 `fnd-selected` 金色。标题栏按钮平时用次要文字色、透明底，悬停时文字变金；当前页签用金色文字、选择底色，标签下方加一条 1px 金色下划线，当前位置因此不只靠颜色区分；键盘聚焦保留所在状态，另加 1px `fnd-focus` 焦点框，不改文字颜色。这几条只写在 `.fnd-head` 里，其他页面复用 `.fnd-head__tab` 的返回按钮和 Formulator 按钮保持中性。`fnd-selected` 作文字时，浅色在标题栏白底上 5.18:1、在选择底色 #efefed 上 4.50:1，正好压在下限，改这两个 token 前先跑 tokens.test.ts；深色分别为 9.55:1 和 8.43:1。品牌字和页签都保持静态，2026-09-27 试做的两个动效按门槛撤回。metal-fx 的 MetalText 材质固定为 chromatic，浅色下品牌字读成灰色，对比度最低 4.33:1；liquid-gooey 的滑动指示器每次切换后约 40 秒持续重绘，空闲时渲染进程和 GPU 占用都上升。成果页签同样用 1px 金色下划线。`fnd-line-hover` 用于中性悬停边界，`fnd-focus` 仅用于焦点框，`fnd-selection-surface` 用于任务及布局选择底色，也是折叠摘要等文字行的中性悬停底。界面控件和折叠摘要只用中性色、金色（位置、选择、焦点）和砖红（警示）；蓝色只留给 external 历史标记，图表系列色另行规定。背景、容器、次要层、正文、次要文字和分隔线分别对应 `bg/surface/surface-strong/ink/muted/line`。

警告、错误、不可逆删除和输入错误使用砖红警示色 `fnd-warning`，文字用主色，边用 `fnd-warning-line`，浅底用 `fnd-warning-fill`。浅色主色 #a3372b 在白底上 6.69:1，深色主色 #eb9a8c 在 #1f1f1f 上 7.48:1。三件一起换，警示文字旁边不留金色边或金色浅底。

前置 YAML 的 `-dark` 项是同名 CSS token 的深色覆盖值。壳跟随系统主题；原生对话在自身主题完成解析后，通过 DSW 语义别名映射同一套底色、文字、边界、金色强调色和警示色；原生的错误色和危险悬停底映射到 `fnd-warning` 与 `fnd-warning-fill`。原生 composer 默认中性边界，悬停保持中性色，仅在聚焦时使用 1px 金色边界。历史标记保留原有金色、灰色、蓝色语义，FA 图形保持自身颜色。

**The Location Rule.** 金色只服务于品牌、当前位置、选择、焦点和原有的历史标记（稿外追问 chip）；警告、错误、不可逆删除和输入错误一律用警示色，不用金色。标题栏按钮平时保持中性，只在当前页签、悬停和聚焦时出现金色。主操作使用既有中性反差，数值与业务状态保留文字。

## Typography

Noto Sans SC 用于中文正文、标题、输入和控件，完整 WOFF2 随壳和原生客户端离线打包，真实变量字重 100–900，关闭合成字重；不依赖 localhost 或远程字体。Asap Sharp 仅用于品牌字。见[字体来源与许可](app/src/assets/fonts/noto-sans-sc/README.md)。

财务数字用 IBM Plex Mono（IBM 官方 npm 包 @ibm/plex-mono 2.5.0 的 WOFF2 原文件，OFL，不转换、不裁字、不改名），只打包 Regular、SemiBold、Bold 三个字重，随包离线，不在线加载。等宽字体里数字、千分位逗号、小数点、负号、括号、百分号和空格同宽，数字列在末位对齐。`--fnd-font-figure` 用于整格数字：表格数字格（`.analysis-number`、`.fnd-num`、`.fnd-figure`）、KPI 数值与明细、报告复核的数字、金额输入；万元、个百分点这类中文单位回落到 Noto Sans SC。`--fnd-font-prose` 用于结果区句子：结论、KPI 卡的说明行、勾稽结果、报告复核说明和计算历史。它只让 0–9 和 % 走 Plex Mono，文字、逗号、小数点仍用 Noto，不拆文本。标题栏、按钮、菜单、表单标签不换。负数色 `fnd-negative` 是柔和暗红（浅色 #94463d，白底 6.56:1；深色 #d9a097，#1f1f1f 上 7.40:1），饱和度低于警示砖红，只给负数，和警告、错误分开；负号或括号始终保留，颜色不单独表意。见[数字字体来源与许可](app/src/assets/fonts/ibm-plex-mono/README.md)。

任务标题 20px，窄窗为 18px；结果页结论优先，首句脚本结论 22px/32px、其余 18px/28px，结果区不画可见标题：顶栏已完整显示任务名，结果的 h3 用任务名（为空时用版本问题）并只留给读屏。有脚本结论时 22px 结论直接领起，没有时日期和四项状态领起。分析版本的问题是助手写的版本说明，放在「技术信息」的「版本问题」一行，版本选择器、比较下拉和计算历史里仍用它区分版本。文稿标题 28px/40px（字重 750）、章 22px/32px（720）、节 18px/28px、小节 16px/26px（700），编辑器、阅读视图与导出 HTML 共用 `--fnd-doc-*` token（h4 至 h6 同用小节字号），由 `document-headings.test.ts` 保持一致。壳与原生对话共用 14px/22px 控件字号，标签 13px、元信息 12px；文稿正文、原生消息和输入共用 16px/28px。应用内阅读与编辑共用一列居中、最大 56rem（896px）的正文；目录由文稿工具栏的「目录」打开，居中的正文列左侧留得下 200px 目录列和 32px 间距时放在正文列外侧，否则以浮层抽屉打开；开合时工具栏和正文都不移动，抽屉在焦点移出、点外面或按 Escape 时关闭，焦点回到「目录」；导出 HTML 正文最大 42em。段后 18px、章前 32px；Markdown 的最浅标题深度映射到正文一级章节，保留相对层级。代码使用 `ui-monospace`。全局启用 `tabular-nums`，结果数值列按真实列类型右对齐；文稿表格按单元格内容判断，数字格（含带单位的数）右对齐且不换行，文字格左对齐，以数字为主的列表头和列里的「—」「不适用」等说明格随列右对齐，文字格和数字列表头至少 4em、首列不在字间断开，首列和不带单位的年份不按数字排，放不下时表格横向滚动，阅读视图与导出 HTML 共用同一份 num/text 标记。

**The Real Weight Rule.** 中文强调使用已打包的真实字重；数据保留原有精度、零和缺值，不借排版制造业务含义。负数在结果表和 KPI 卡上写成会计括号，只改写法、不改数值，保存、导出、文稿和交给助手的文字仍用负号。

## Layout

工作区铺满窗口，不受普通页面 1200px 上限约束；应用顶栏 56px，任务栏最小 64px。当前桌面最小窗口宽度为 1080px。初次挂载在 ≥1360px 默认显示 256px 任务栏；1101–1359px 默认收起，打开时为 288px 模态抽屉；≤1100px 将默认并排状态显示为成果专注，并保留对话/成果切换。

进入窄布局收起任务栏，放大后保留收起状态，不承诺 1440px 自动展开。专注选择按任务保留。对话默认 420px，可调 400–640px；7px 分隔条支持拖动、左右键每次 20px、Home/End 到边界，双击恢复默认值。

对话与成果独立滚动，成果区 scrollTop 按任务保留；资料、结果、文稿复用该成果滚动容器，不承诺按三个页签分别恢复滚动。成果留白为顶部 24px、左右 24px、底部 32px，窄窗左右保留 20px；原生对话采用相同字号与边缘留白。侧栏以标题、状态分段、搜索、两行任务项和固定底部入口组织，任务名称 14px、期间 12px；「进行中 / 已归档 / 回收站」分段按常规控件做，36px 高、14px 字。依据抽屉最大 340px，结果容器 ≤620px 时局部覆盖；比较为两列，≤680px 逻辑视口回退单列。这些 CSS 回退不构成移动端交付承诺。

## Elevation & Depth

工作区使用底色、细边框和留白；结果、计算定义以平面行与下边线分隔。现有帮助面板保留柔和阴影与径向底色，不推广到数据卡片。任务抽屉、壳弹层、成果专注、新任务及分隔条拖动期间实际隐藏原生层；结束后恢复会话，零尺寸不能替代可见性控制。原生工具详情在对话内占满整栏。

通用壳控件过渡为 `180ms ease`，时长与缓动独立为 `fnd-duration/easing`，`prefers-reduced-motion` 将时长归零；不据此承诺第三方原生客户端全部动画均已覆盖。sidecar 色阶为面板插值预览，非产品 token；组件片段仅展示现有外观与 CSS 状态。

## Shapes

控件和任务行使用 `control` 圆角，文稿输入与依据使用 `container`，小图标操作和折叠摘要使用 `mark`，工具菜单使用 `menu`，历史 chip 保留原形，可点 chip 的规格见按钮与字段。资料页不再有文件卡。内容以细分隔线组织，避免把每个标题和操作组包成卡片。KPI 卡、月结步骤卡这类并排汇总卡用 `card-compact`。沿用线性 SVG 控件，装饰图标不进入无障碍名称。

## Components

**按钮与字段。** 主操作实心，次操作细描边；常规按钮、输入和选择框高 36px（紧凑图标动作 32px），长示例允许换行增高。一个表单或一排操作只有一个主操作，放在右下，宽度跟文字走，不做通栏。次操作/输入悬停为中性边界，主按钮没有额外悬停变色，按下时略降透明度或使用选择底色。字段组合为标签、控件、帮助或错误；`aria-invalid` 与警告边使用 `fnd-warning-line`，错误文字使用 `fnd-warning`。通用焦点外框 1px、偏移 -1px，与原边界重叠成单一指示；聚焦、错误或禁用的字段不叠加普通悬停边色。原生选择框与财务输入沿用同一字段状态。主按钮文字使用 `on-accent`，暗色下不得继承 ink。禁用使用真实 disabled 与既有透明度。会一直挡住操作的原因在按钮下方用一行 13px muted 文字写明，并用 aria-describedby 关联，几个按钮原因相同时合成一行；读取或保存中这类短暂禁用不写原因。例外是以损益表为主的任务里只缺预算资料时，「计算预算差异」的原因只给读屏（sr-only），不在主操作下常挂一行。工具菜单、选择弹出层和导出菜单共用 `fnd-shadow-menu`；工具菜单每一项左侧都有 15px 线性图标，文字左缘对齐；抽屉遮罩使用 `fnd-overlay`。成果页签为下划线式 tab，未选中悬停变为正文色。参数显示真实业务名称、类型、单位和约束，未标注语义的旧参数按原名留在高级区。不可逆删除使用次操作的 destructive 变体（`fnd-warning` 砖红文字与 `fnd-warning-line` 边，悬停为 `fnd-warning-fill`），菜单项用同名变体。能恢复的移除，例如移入回收站和删除分析要求，按普通次操作或普通菜单项处理，不用砖红。错误提示旁的修复动作沿用警示色。薄控件（按钮、简单输入、成果页签、菜单）来自 shadcn 原语，视觉仍只读 `--fnd-*` token。可点 chip 只有一种，即描边按钮的 chip 尺寸，28px 高、12px 字、chip 圆角、细描边；按下或选中时用选择底色加 `fnd-ink` 边，悬停时保持不变，不用主色实心，也不用金色；焦点框离边 1px，选中的 ink 边仍看得见。期间快捷项、资料里读到的候选值、结果页期间页签和成果库的导出格式按钮都用它。28px 是 chip 的单独规格，不按常规控件 36px 判违规。列表行的详情（资料页每份文件的表结构、公式体检、内容预览）用带 aria-expanded 与 aria-controls 的按钮在该行下方原位展开，不用 details；按钮用常规 36px 尺寸，可见文字以动词开头，可访问名称以可见文字开头并带对象名，按钮右侧 14px 向下 chevron 展开时转 180°。收起只是隐藏，明细留在页面里，没提交的改动不丢；在明细里按 Escape 收起并把焦点还给按钮；确认或追认之后焦点回到该行文件名。行内表结构卡的文件名标题只给读屏。原本可见的信息不挪进 title；需要补充说明时保持可见，或同时提供 sr-only 文字。

**折叠段落。** `app/src` 的 React 视图里原位展开的折叠段落都是原生 `details`，摘要统一用 `DisclosureSummary`（[组件](app/src/components/Disclosure.tsx)）。摘要为正文色 14px/22px 常规字重，左侧 16px Lucide `ChevronRight`，描边 1.5，随文字色，不进入无障碍名称，展开时旋转 90°，过渡用 `fnd-duration/easing`。悬停为 `fnd-selection-surface` 中性底，键盘焦点沿用 base 的 1px `fnd-focus` 框。摘要整行向左让出 8px，chevron 的图标盒左缘与展开内容的左缘对齐，摘要文字从内容左缘起 24px 处开始，悬停底伸进左侧 8px 留白。技术信息、诊断、脚本输出、中间步骤和图表原始数据这类辅助折叠用 `tone="quiet"`，12px/18px、`fnd-muted`，图标 14px。标签文字直接作为 `summary` 的文本；需要标题层级或说明行时可以放块级标题或说明 span。警告这类语义图标可以和 chevron 并存，装饰图标不放。页面样式只给折叠调间距，不改摘要的颜色、字号、字重、标记和焦点，也不用文字三角、原生三角或右侧 chevron。行内展开（按钮带 `aria-expanded` 在行下展开）、Popover 和「设置与高级」的原位面板各按自己的规则，不在此列。原生对话标题区的「对话工具」打开浮层，保留向下 chevron，用正文色和原生中性悬停底。另有三处摘要不经过这个组件：导出 HTML 里图表的「查看图表数据与说明」（`app/electron/reports/format.ts` 生成，应用内阅读视图由 report.css 的一条限定规则画成同样的 quiet 行）、原生对话里的工具调用折叠（`foundry/resources/dsh-plugin/client.js`）和 Excel 加载项 taskpane。

**成果库。** 页首是 20px 标题「成果库」和按任务名搜索。表格按任务分组，组标题行与结果表的分组标题同一规则，写任务名，有期间时用中文期间跟在后面，两者都只出现一次。组内每个文稿修订一行，列为来源文稿、状态、导出件、最近更新。导出件按管理版、审计版分排，每种格式一个 chip，点开交给默认程序；导出文件带复核标记时在格内可见地写出来。状态只写一次。旧流程版本各占一行，成因写在版本名后面。

**使用指南。** 指南在对话栏里单栏显示。目录是顶部按章节分组的原生下拉，搜索命中列在正文上方。正文占满栏宽，整栏只有正文一个滚动区。

**导航与焦点。** 顶层为工作区/成果库，方法库、数据台、历史任务从次级入口可达。资料/结果/文稿用带计数的 tablist，支持左右键、Home/End 与 roving tabindex。任务抽屉聚焦搜索、限制 Tab、使主工作区 inert；Escape 关闭并返回开关。图标动作有名称和状态，分隔条提供方向与数值。

**持续对话。** 任务切换和隐藏/显示保留会话与未发送草稿；完整问题按准确任务转交，实际接收成功才确认提交，受阻时保留问题并允许重试，同一动作不重复发送。400/460px 设置与工具详情已有验收；这不等于未来客户端版本无需适配。

**结果与依据。** 分析版本选择器在结果最上方，比较版本在它右侧并在下方展开；结果正是最新文稿引用的那次计算时，下方用一行 12px 辅助文字说明，不加边框。随后是日期和四项独立状态，状态在任何宽度下都在日期下方，再以 22px 脚本结论领起结果；结果标题只给读屏，不重复顶栏的任务名。KPI 卡预算、差异、达成率各占一行，标签在左、等宽数字在右；期间、单位、依据与「推断」等标记合成一行元信息，每段不拆开，只在「 · 」处换行；结果区不超过 900px 时两列。达成率字段是差异率时标签写差异率，缺值照常写“—”。业务结果的「整理成文稿」是主按钮，和「查看本次计算依据」紧跟 KPI 卡，没有 KPI 卡时跟在结果表之后；版本问题、原始字段和诊断放进同一个「技术信息」折叠，一个结果只有一个。结果页上的会计期间经 formatPeriod 写成「2026 年 1–8 月」，技术信息里的原始表和版本比较的对照表保留原值；两个期间写成文字后相同时（如 2026-08 与 2026-08:2026-08）也用原值区分。保存、导出、筛选和交给助手的文字用原值。结果页以外也一样：任务栏、任务列表与详情、资料页的范围与就绪表、表结构建议、工作簿浏览、财务背景、成果库和月结范围上的会计期间一律经 formatPeriod 显示，跨年写全，并排列出的几个期间写成文字后相同时同样退回原值；月结范围由服务端按键给出各项原值，界面只改写期间。写成文字的期间不在中间断行（.fnd-period），所在的一行只在「 · 」等分隔处换行。输入框、已选期间按钮、资料候选按钮、存储、导出、读屏名称和服务端写给助手的文字保留 2026-01:2026-08 原值；任务搜索和可搜索下拉两种写法都能找到，比较前去掉空格、把「–」当作「-」，所以「2026年8月」「1-8月」也能搜到。定义、历史及方法保存按需展开。失败明确说明当前保留的是历史成功结果。依据按本次运行绑定定位确切快照；非模态 dialog 打开聚焦关闭按钮，Escape 返回触发按钮。参数/假设优先用保存版本的元数据；比较并列保存运行及原行序，不推断主键或差额。

**结果表格。** 表格使用中性横线与 10px 以上单元格内边距。Python/shell 结果包含明确的 label/value/unit 字段，且其余列仅为 metric、wb、sheet、cell、note、check 等已知依据字段时，先显示项目、数值、单位，完整原始列通过“完整明细”展开；额外数值列或未知字段继续默认显示全表。不改变行序、缺值或财务专用展示；唯一例外是「其他结果」按组织分组，组按首次出现排序，组内保持原行序。表格具备与表格左缘对齐的 caption、列标题、可聚焦横向滚动区，放不下时在表下写「右侧还有列，可横向滚动查看」；每页最多 100 行，截断明确提示，缺值显示“—”。脚本长表每行都有 metric_label 时不显示指标键列，悬停指标名显示指标键；metric 与 metric_key 等键列取值不一致时键列照常显示；全表只有人民币时不显示币种列；两者都留在技术信息的原始表里。重名按字段判断，和后端 label_ambiguous 同一口径，共用样例在 app/tests/fixtures/label-collisions.json：范围是没有进入配对的长表行（能配对时是「其他结果」，不能配对时是主表全部行）；组织取 organization、region、区域 中第一个非 null 的值；期间取原始 period，没有时取「期间」，不格式化；标签取 trim 后的 metric_label 按表格显示的文本（估算行未自述估算时带「（估算）」，等于指标代码的换成中文名），再 trim 比较；指标键取 metric、metric_key、business_key、result_key、item、name、指标 中第一个非 null 的原值，不换成配对用的基础指标。同组织、同期间、同显示标签下指标键有两个以上就算重名。不显示键列时名字后补中文名或指标键；开发环境不论是否补键都在控制台报警，指标名写清对象仍由脚本负责。「其他结果」每个组织一个 tbody，组标题是 14px 正文色的 rowgroup 表头，规则只在 components.css 定义一次，翻页延续的组注「（续）」。单位列在单位种类为比率或百分数且有值时写「%」，数值文本不变。两个比率之差的行单位写「百分点」，结果区和文稿附表都显示「3.30 个百分点」，单位列写「个百分点」，不显示成百分数，也不参与实际与预算配对。同一组织、同一期间有两行共用一个指标名而指标键不同时，运行记录给出 label_ambiguous 提示，结果区照上面的规则补键。后端提示按运行固定的需求版本和行自身信号判断估算；读取时从任务最新需求版本合入的估算会让结果区给标签补「（估算）」，但不重算 label_ambiguous，这种情况下两边可能差一组。「其他结果」的 source 或「来源」列超过 24 个字时显示第一条和条数，点开列出全部引用；source_note、「口径与来源」是说明，照旧全文显示，业务结果主表的来源也照旧全文显示。分组用行里原样的组织值，只有 null 和空串算未声明组织。滚动提示在滚到最右端后隐藏。改版时原来可见的信息继续可见，或同时给 sr-only 文字。

**财务数字。** 结果表和 KPI 卡的数字都经 `app/src/lib/figures.ts` 和 `Figure` 组件（[组件](app/src/components/Figure.tsx)）显示：金额两位小数、千分位，比率两位小数加 %，比率之差写「个百分点」。不带单位字的负数写成会计括号 `(18,843.06)`、`(3.30%)`；带单位字的（`-0.65 个百分点`、`-1,234.00 万元`）保留负号，以免括号读成注释。所有负数用 `fnd-negative` 柔和暗红。同一列里有括号负数时，正数右侧让出一个数字宽（1ch），个位与括号内的个位对齐。数字列按内容判断：引擎列类型是数字，或这一列显示的每个值都是数字（差异率、脚本的「数值」），表头和数字格都右对齐，文字格左对齐。首格以「合计」「总计」开头的行 700 字重，上方一条 `fnd-line-hover` 细线；以「小计」开头的行 600；明细 400；表头 600。全表只有这三档。技术信息的原始表和其他原样表（决定 6B）里，按列名是金额或比率的值照业务表格式化；其余数字只加千分位，不舍掉小数位，并按本列最多的小数位补零对齐，最多补到 4 位；期间、编码、行号、单元格、版本和精确值列照原样显示。改过写法的格悬停显示原值。勾稽和控制的合计、差额只加千分位，保留全部小数位，避免 0.0004 的差额显示成 0.00；差异结论兜底句同样只加千分位。滚动预览的原值和新值、Excel 协作的绑定区域读取结果和写回预览（`Table exact`），是单元格里或要写进单元格的内容：用数字字体右对齐、负数着色，但不加千分位、不补零、不改括号。

**文稿与方法。** 文稿支持 Markdown 阅读和独立编辑，借鉴 Kami 的行长、章节留白与轻表格规范。仅当已保存的计算依据与正文末尾完全匹配时，阅读区将该附录折叠，编辑和导出仍保留完整正文；旧版和不匹配内容直接呈现。工作副本按任务/版本使用会话级存储恢复，正式保存生成新版本；交给助手或导出前先保存改动。改正文不替换已引用的历史运行，导出、归档与经理认可分别操作，「归档此版」和导出并列在文稿工具栏。发布前检查里相同的阅读建议合并成一条，逐段写出章节、段序和段首文字，点「定位」切到阅读视图并滚到该段；分析要求的缺口按原因合并，要求和组织列在原因下面，完整说明留在「原始问题」里。方法保存是折叠的可选动作，复用重新选择资料与参数；未来领域入口随实际能力出现。

**验证边界。** 已核对最终整窗图与[流程](build/ui-workspace-review/final/verification.json)、[比较补拍](build/ui-workspace-review/final/comparison-recapture.json)、[原生检查](build/verification/native-workspace-final.json)、[产物记录](build/verification/ui-final-artifacts.json)：26 项原生检查和 6 项界面流程通过，资料为合成 fixture，真实 provider 调用为 0。真实模型接收/流式响应、物理 macOS 中文候选窗、完整屏幕阅读器流程未验收。[最终 ship](docs/reviews/2026-09-06-ui-finish-review.md)仅覆盖 F1–F4 修复评分；详细实现与限制见 [UI 实施记录](docs/plans/2026-09-06-ui-execution-log.md)。

### shadcn 原语（2026-10-04）

底座保持 Radix（`radix-ui` 统一包），不迁到 Base UI；组件从 shadcn 结构出发，视觉只读 `--fnd-*` token，不跑 `shadcn apply` 覆盖。

- **字段结构。** `FieldShell` 使用 Field 结构（`field`、`field-label`、`field-description`、`field-error` 四个 data-slot），错误时字段带 `data-invalid`、控件带 `aria-invalid`，类名仍为 `fnd-control*`。
- **选择框。** 一律用 NativeSelect：仍是原生 `select`，菜单由系统绘制，能盖在原生视图之上；外层只加 16px 下拉箭头，字段状态与输入框相同（高 36px、`fnd-field`）。任务栏的选择框沿用 `fnd-picker` 尺寸。页面样式不再单独给 `select` 写边框和内边距。
- **勾选与开关。** 多选和逐项纳入用 Checkbox（16px，选中为主色底）；保存即生效的设置用 Switch（如「接受差异后需要第二人复核」）。两者均为 `role="checkbox"`/`role="switch"` 按钮，标签包住控件即可点击文字切换。
- **空状态。** 整屏或整块的空状态用 Empty（`empty`、`empty-header`、`empty-title`、`empty-description`、`empty-content`）：左对齐、弱色说明、不加卡片和插图；标题用 `asChild` 保留所在页面的标题层级，操作按钮放在 `empty-content`。面板里一句话的「还没有……」仍用普通说明文字。不引入 Toast（内联提示更符合结论优先）、`cn` 独立包和 Rhea 紧凑风格（与 36px 控件高度冲突）。
- **日期与搜索选择。** 浮层统一用 Popover（Radix 定位，贴边自动翻转，挂到 body，宽度跟随触发控件）。来源引用弹层例外，宽度不跟随触发控件，上限 32em。日期选择用 Calendar（react-day-picker）：周一开头、标题「2026 年 8 月」、星期单字，打开后焦点落在已选日（没有则今天），方向键、PageUp/PageDown、Enter 由日历处理。会计期间仍为 YYYY-MM 月份网格（shadcn 没有月份视图），放在同一种 Popover 里。搜索选择与多选用 Combobox（Popover + Command）：筛选和排序仍按名称、编码、说明的顺序且最多显示 80 项，Command 只负责高亮项、方向键与 Enter；输入法组字时 Enter 不选中。选中或 Escape 后焦点回到触发控件，点外面关闭时焦点留在点击处。
- **设置与高级。** 分析页和财务工作台共用一个 `SettingsPanel`（shadcn Collapsible）：在页面内原位展开、打开时替换入口，不做浮层，因为面板里有自带弹出层的搜索选择，计算结果也要留在下方可读。用户打开时焦点进入面板；之后无论 Escape、「关闭」还是计算成功自动收起，焦点都回到打开前的位置（已不在页面时回到入口），不会落到页面顶端。首次进入时默认展开的面板不抢焦点。面板随页面滚动，不设内部滚动区，标题行吸顶。主计算按钮由当前分析决定，比较预算（差异运算或绑定 budget 资料）时「计算预算差异」为主，否则「计算损益表」为主；表单里的选择不改变主次和位置。「保存范围」在这里是次操作。面板不重复结果页的问题标题，假设只在本版本还没有成功运行时显示。

## Do's and Don'ts

- **Do** 沿用现有 FA 标识、离线字体、系统主题、真实任务归属与可见焦点。
- **Do** 用保存的名称、单位、参数、来源与版本支持财务经理自主判断。
- **Don't** 合并执行/复算/阅核/发布状态，猜测旧参数语义或添加不可用业务入口。
- **Don't** 把工作副本恢复写成跨重启正式自动保存，或把窄窗回退写成移动端承诺。
- **Don't** 将分区标题做成大写 tracking 的 kicker；章节用标题元素承担层级。未定义的选择色 fallback 或原生控件局部色差也不推广为全局规则。

## 样式级联与来源披露（2026-09-08）

宿主按 `theme → base → components → layout → utilities` 排序：token 提供颜色，base 提供继承和可访问焦点，组件持有控件状态，页面持有排版，显式 utilities 用于局部组件变体。禁止在层外增加控件颜色/字体/焦点补丁。Input、Textarea 与财务字段共用 `fnd-field`；复合年月、日期和金额仅增加自己的布局及业务行为。年月内嵌图标为 26×26px，垂直居中于 36px 输入内部。

资料页自上而下是「这批资料能算什么」、资料列表、分析范围和工作簿工具。「这批资料能算什么」不加卡片，下边一条细线收住。资料列表每份文件一行，文件名下一行 12px 元信息写类型、大小、派生表的来源、导入时间和资料声明的期间单位币种；右侧依次是表结构、公式体检和「查看内容」。表结构和公式体检的状态词用中性色，只有「其中 N 类需留意」用砖红。月结待处理卡是关卡汇总，用砖红；资料页是逐文件状态，用中性色。「任务资料」标题旁带指南「?」。空资料页优先展示添加资料与讨论入口。“更新 ERP 来源”默认折叠，展开后显示原有刷新表单，保留填写内容及新旧快照语义。

## 经营分析文稿（2026-09-08）

文稿入口整合版本、导入、阅读、编辑、打印预览与五格式导出。Tiptap 开源编辑器支持段落层级、列表、链接、本地图片、表格合并拆分、章节末编号附注和分页；Markdown 保留源码入口，转换前展示结构降级。目录默认收起，由文稿工具栏的「目录」开关打开，宽时放在正文列外侧、窄时作浮层抽屉，正文不移动；证据与校验结果独立于连续正文。

模板借鉴保利物业、海信家电和 Berkshire 年报的章节、比较表、单位和附注组织，结合 Kami 的阅读节奏。阅读正文沿用主题及离线 Noto Sans SC，16px/28px，应用内正文列最大 56rem、导出 HTML 约 42em，至少 24px 内边距及 32px 章节间距。正式预览与 PDF 使用白底 A4、20mm 页边距、11pt 正文、至少 9pt 表格及附注；页眉页码统一。表格以细横线、重复表头及项目列组织长表和宽表，数字保持原始文本、精度与负号，放不下时由表格自身横向滚动，确实溢出的表格在应用内阅读视图里成为可用键盘聚焦、以表题命名的滚动区，导出 HTML 不加。界面和导出不改写数字文本，写法由写稿规则约定。章节只呈现已有内容，不自动补写管理结论。

[五格式实现与验收契约](docs/plans/2026-09-08-financial-documents-plan.md)记录结构模型、离线转换与安全边界。Excel 工作表/区域保留来源定位；PDF 原页与草稿对照，OCR 不可用时保留已提取内容并支持重试。导入文件不执行脚本，也不自动请求外部图片或链接。

## 工作簿公式体检（2026-10-04）

公式体检是资料页上的提示，不是关卡：它是资料列表每一行的一项状态，写「未做」「N 类提示」「无提示」或「未能完成（不影响使用）」；有提示时点「查看」在该行下方展开，现查后自动展开。展开后逐类给出中文说明、处数和至多 5 个样例单元格，样例用链接式「查看」在原表只读预览中定位。需留意的提示用砖红 `fnd-warning` 系列配「需留意」字样和警示图标，一般提示用 muted 配「提示」字样和信息图标，颜色从不单独表意，也不使用金色。提示不禁用任何按钮、不改变任何状态；结尾一句「这些是提示，不影响导入和计算；是否需要修改由你判断。」说明由谁决定。

## 差异问题类型与套表可用结论（2026-10-04）

月结页另起一块「套表可用结论」，放在步骤卡和「已就绪」「尚未开始」两行之后、勾稽控制之前，不替代顶部状态，不加边框和底色。级别用图标加文字表达，不可用的图标和级别字用 `fnd-warning`，无法判断用 `fnd-muted` 并配虚线圆 `CircleDashed`（不用像帮助的问号），「套表可用结论：」标签和工作簿名保持正文色，可用与带保留可用保持正文色；金色只留给位置、选择和焦点。结论行只放级别图标，指南「?」只放在顶部状态旁。原因不超过五条时全部列出，超过五条先列三条、其余折叠；「按工作簿看」始终折叠。确认的控制一条都没有时不显示「依据」。差异行头用描边 Badge 显示经理定下的问题类型；助手建议只写成「助手建议：…」文字，不用 Badge。

## 月结页顶部与步骤卡（2026-10-07）

顶部状态不加外框和单侧色条。尚未准备和需要复核在标题前放 20px 砖红 `CircleAlert`，标题文字用正文色；可计算时的副句照旧用砖红文字加图标。标题里的数字由服务端从六块里挡住月结的条目数出，等于待处理卡列表里的行数，「下一步」取同一份列表的第一条。版面自上而下是标题、「下一步」、待处理卡、「已就绪」「尚未开始」两行、套表可用结论、勾稽控制；结论的原因另算，不进标题，也不紧贴标题。

步骤卡只展开待处理和请留意的卡，卡号沿用 1 到 6，内边距和圆角用 `card-compact` token。已就绪的块合成一行「已就绪：…」，尚未开始的合成一行「尚未开始：…」。范围的确认值、复核的「经理尚未复核（提交后由经理完成）」和「另有 N 份旧版本已被更新的资料取代」跟在块名后用 `fnd-muted` 小字直接显示，免得「已就绪」被读成经理已签；来源文件名和其余块的一句话明细放在块名的提示里，并同时写进读屏文字。待处理卡的列表只放挡住月结的条目，用正文色；其余说明在列表下另起段落用 `fnd-muted`，请留意的说明以「请留意：」开头。请留意卡照原样列出全部条目。砖红只给卡头的状态词和图标。每张待处理卡底部一个 36px 描边「去处理」；控制和异常卡的按钮留在本页，滚到勾稽控制并聚焦它的标题。月结页的待处理状态词用砖红，因为它是关卡汇总；资料页逐文件的「表结构 待确认」用中性色，因为它是单个文件的进度。来源文件的摘要哈希只在提示里，读屏只读文件名。

## 证据标签与证据等级（2026-10-04）

文稿质量检查在核对状态下方单列「证据等级」块：一行「证据等级：{可决策/研究级/初步/假设主导/无法支持}」配图标和指南「?」，下一行固定写「这是对引用依据的分类，不代表经理认可。」，再列出决定等级的几条依据和各标签计数。它不进入待处理核对行、四项独立状态或月结顶栏。每张事实卡和每条引用带一个小标签（Badge）：矛盾来源、缺必需来源、过期来源用警示色、三角图标并直接写出原因，其余用中性描边、原因放在提示和读屏文字里；被覆盖的原依据写在标签内（「过期来源（原为标准化数据）」）。依据分类列表里每项写成「引用 1 · 计算 · 结果第 1 行 · actual」。资料页就绪表增加「截至日 / 期间」「时效」两列，时效用文字加图标并带原因（当前 / 资料过期（原因） / 期间不符（原因） / 未声明（原因）；分析期间还没确认时写「无法判断（原因）」，不说成资料没声明），警示色只给资料过期和期间不符。这些位置都不使用金色。

## 外部报告数字复核（2026-10-04）

复核结果先用一句话说有几个数字需要核对，再列出「不一致 / 疑似单位换算 / 需人工核对 / 一致」四个计数，每个计数都有图标和文字；需要核对的计数用砖红 `--fnd-warning*`，一致不着色。下方用同名页签逐项列出：文稿里写的数字、位置（第几页、表几第几行第几列或哪一节）、原文片段和最接近的来源（「套表 sheet!B12 = 1,234.56 万元」），不一致时另起一行写折算后的来源数值和差额。查看源区域沿用工作簿浏览，PDF 打开对应原页。结尾固定说明复核只比对数字，不代表报告可以对外发送；界面不出现“通过”。
