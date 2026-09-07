---
name: FA Foundry
description: 以任务、持续对话与真实成果组织的财务经理工作台。
colors: {fnd-bg: '#ffffff', fnd-surface: '#ffffff', fnd-surface-strong: '#f7f7f7', fnd-ink: '#000000e0', fnd-muted: '#00000099', fnd-line: '#1f1f1f24', fnd-accent: '#1f1f1f', fnd-on-accent: '#f9fafb', fnd-selection-surface: '#f5efe3', fnd-line-hover: '#a67e3c', fnd-selected: '#8a6729', fnd-on-selected: '#f9fafb', fnd-bg-dark: '#111111', fnd-surface-dark: '#1f1f1f', fnd-surface-strong-dark: '#161616', fnd-ink-dark: '#f9fafb', fnd-muted-dark: '#a6a6a6', fnd-line-dark: '#ffffff24', fnd-accent-dark: '#f9fafb', fnd-on-accent-dark: '#1f1f1f', fnd-selection-surface-dark: '#302b21', fnd-line-hover-dark: '#e2c180', fnd-selected-dark: '#e2c180', fnd-on-selected-dark: '#1f1f1f'}
typography:
  headline: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 24px, fontWeight: 600, lineHeight: 32px}
  task-title: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 20px, fontWeight: 600, lineHeight: 28px}
  title: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 16px, fontWeight: 600, lineHeight: 20px}
  body: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 14px, lineHeight: 22px, letterSpacing: '0'}
  small: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 13px}
  label: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 12px}
  document: {fontFamily: '''Noto Sans SC'', ''PingFang SC'', system-ui, sans-serif', fontSize: 16px, lineHeight: 1.85}
  composer: {fontFamily: '''Noto Sans SC'', sans-serif', fontSize: 15px, lineHeight: 1.6}
  brand: {fontFamily: '''Asap Sharp'', ''Noto Sans SC'', sans-serif', fontSize: 22px, fontWeight: 700, lineHeight: 1}
rounded: {control: 8px, container: 12px, chip: 30px, mark: 6px, menu: 10px}
spacing: {control-gap: 6px, compact: 8px, small: 12px, grid-gap: 16px, workspace-gap: 20px, gutter: 24px, section-gap: 32px}
components:
  button-primary: {backgroundColor: '{colors.fnd-accent}', textColor: '{colors.fnd-on-accent}', typography: '{typography.small}', rounded: '{rounded.control}', padding: 0 14px, height: 32px}
  button-secondary: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.small}', rounded: '{rounded.control}', padding: 0 14px, height: 32px}
  input: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', typography: '{typography.small}', rounded: '{rounded.control}', padding: 0 12px, height: 32px}
  nav-current: {backgroundColor: '{colors.fnd-selected}', textColor: '{colors.fnd-on-selected}', typography: '{typography.small}', rounded: '{rounded.control}', padding: 0 16px, height: 32px}
  chip: {backgroundColor: transparent, textColor: '{colors.fnd-ink}', typography: '{typography.label}', rounded: '{rounded.chip}', padding: 4px 10px}
  card: {backgroundColor: '{colors.fnd-surface}', textColor: '{colors.fnd-ink}', rounded: '{rounded.container}', padding: 18px 20px}
  workspace-tab: {backgroundColor: transparent, textColor: '{colors.fnd-muted}', typography: '{typography.small}', padding: 12px 0}
---

# Design System: FA Foundry

## Overview

**Creative North Star: "财务经理的任务工作台"**

沿用 FA 标识、中性色与金色定位。业务问题、计算值与文稿承担主要层级；财务经理可以持续讨论并查看成果，专业判断和方法复用保留为用户可控动作。此名称概括已有产品定位，未新增品牌概念、comp 承诺或长期工作流偏好。

本记录合并既有设计约定，描述 2026-09-06 的实际界面。样式来源为 [tokens](app/src/styles/tokens.css)、[base](app/src/styles/base.css)、[公共控件](app/src/components/components.css)、[工作区](app/src/components/Workspace.tsx)和[成果样式](app/src/views/analysis.css)；产品事实见 [PRODUCT.md](PRODUCT.md)。

**Key Characteristics:**

- FA 图形与 Asap Sharp 品牌字；离线 Noto Sans SC 中文工作界面。
- 中性平面、细分隔线、有限容器与金色交互定位。
- 持续对话与成果并排，空间不足时使用同任务专注视图。
- 按真实参数、来源、版本和状态呈现结果与文稿。

## Colors

主操作使用 `fnd-accent/on-accent` 的中性反差；当前导航使用 `fnd-selected/on-selected`，成果页签用金色下划线。`fnd-line-hover` 用于悬停边界与通用焦点，`fnd-selection-surface` 用于任务及布局选择底色。背景、容器、次要层、正文、次要文字和分隔线分别对应 `bg/surface/surface-strong/ink/muted/line`。

前置 YAML 的 `-dark` 项是同名 CSS token 的深色覆盖值。壳与原生对话跟随同一系统主题；原生仍使用自己的局部别名，底色与发送按钮并非逐 token 相同。历史标记保留原有金色、灰色、蓝色语义，FA 图形保持自身颜色。

**The Location Rule.** 金色服务于当前位置、选择和焦点；主操作使用既有中性反差，数值与业务状态保留文字。

## Typography

Noto Sans SC 用于中文正文、标题、输入和控件，完整 WOFF2 随壳和原生客户端离线打包，真实变量字重 100–900，关闭合成字重；不依赖 localhost 或远程字体。Asap Sharp 仅用于品牌字。见[字体来源与许可](app/src/assets/fonts/noto-sans-sc/README.md)。

任务标题 20px，窄窗为 18px；结果标题 20px，文稿标题 24px。操作/数据使用 `small`，普通正文使用 `body`，标签使用 `label`；文稿阅读为 `document`（最大 72ch），原生输入为 `composer`。代码使用 `ui-monospace`。全局启用 `tabular-nums`，结果数值列按真实列类型右对齐。

**The Real Weight Rule.** 中文强调使用已打包的真实字重；数据保留原有精度、负号、零和缺值，不借排版制造业务含义。

## Layout

工作区铺满窗口，不受普通页面 1200px 上限约束；应用顶栏 56px，任务栏最小 60px。当前桌面最小窗口宽度为 1080px。初次挂载在 ≥1360px 默认显示 192px 任务栏；1101–1359px 默认收起，打开时为 240px 模态抽屉；≤1100px 将默认并排状态显示为成果专注，并保留对话/成果切换。

进入窄布局收起任务栏，放大后保留收起状态，不承诺 1440px 自动展开。专注选择按任务保留。对话默认 420px，可调 400–640px；7px 分隔条支持拖动、左右键每次 20px、Home/End 到边界，双击恢复默认值。

对话与成果独立滚动，成果区 scrollTop 按任务保留；资料、结果、文稿复用该成果滚动容器，不承诺按三个页签分别恢复滚动。成果左右留白通常 24px，窄窗 16px。依据抽屉最大 340px，结果容器 ≤620px 时局部覆盖；比较为两列，≤680px 逻辑视口回退单列。这些 CSS 回退不构成移动端交付承诺。

## Elevation & Depth

工作区使用底色、细边框和留白；结果、计算定义以平面行与下边线分隔。现有帮助面板保留柔和阴影与径向底色，不推广到数据卡片。任务抽屉、壳弹层、成果专注、新任务及分隔条拖动期间实际隐藏原生层；结束后恢复会话，零尺寸不能替代可见性控制。原生工具详情在对话内占满整栏。

通用壳控件过渡为 `180ms ease`，`prefers-reduced-motion` 将该 token 归零；不据此承诺第三方原生客户端全部动画均已覆盖。sidecar 色阶为面板插值预览，非产品 token；组件片段仅展示现有外观与 CSS 状态。

## Shapes

控件和任务行使用 `control` 圆角，独立资料卡、文稿输入与依据使用 `container`，小图标操作使用 `mark`，工具菜单使用 `menu`，历史 chip 保留原形。内容以细分隔线组织，避免把每个标题和操作组包成卡片。沿用线性 SVG 控件，装饰图标不进入无障碍名称。

## Components

**按钮与字段。** 主操作实心，次操作细描边；常规按钮、输入和选择框高 32px，长示例允许换行增高。次操作/输入悬停为金色边界，主按钮没有额外悬停变色，按下时略降透明度或使用选择底色。字段组合为标签、控件、帮助或错误；`aria-invalid` 与警告边使用 `fnd-mark-outside`。通用焦点外框 2px，偏移 2px；公共按钮与字段偏移 1px，分析区局部偏移 3px。禁用使用真实 disabled 与既有透明度。工具菜单、选择弹出层和导出菜单共用 `fnd-shadow-menu`；抽屉遮罩使用 `fnd-overlay`。成果页签为下划线式 tab，未选中悬停变为正文色。参数显示真实业务名称、类型、单位和约束，未标注语义的旧参数按原名留在高级区。不可逆删除使用次操作的 `data-tone="danger"`，不另开一套颜色。

**导航与焦点。** 顶层为工作区/成果库，方法库、数据台、历史任务从次级入口可达。资料/结果/文稿用带计数的 tablist，支持左右键、Home/End 与 roving tabindex。任务抽屉聚焦搜索、限制 Tab、使主工作区 inert；Escape 关闭并返回开关。图标动作有名称和状态，分隔条提供方向与数值。

**持续对话。** 任务切换和隐藏/显示保留会话与未发送草稿；完整问题按准确任务转交，实际接收成功才确认提交，受阻时保留问题并允许重试，同一动作不重复发送。400/460px 设置与工具详情已有验收；这不等于未来客户端版本无需适配。

**结果与依据。** 先展示运行问题、日期、四项独立状态和真实结果；定义、历史及方法保存按需展开。失败明确说明当前保留的是历史成功结果。表格具备 caption、列标题、可聚焦横向滚动区，每页最多 100 行，截断明确提示，缺值显示“—”。依据按本次运行绑定定位确切快照；非模态 dialog 打开聚焦关闭按钮，Escape 返回触发按钮。参数/假设优先用保存版本的元数据；比较并列保存运行及原行序，不推断主键或差额。

**文稿与方法。** 文稿支持 Markdown 阅读和独立编辑。工作副本按任务/版本使用会话级存储恢复，正式保存生成新版本；交给助手或导出前先保存改动。改正文不替换已引用的历史运行，导出、归档与经理认可分别操作。方法保存是折叠的可选动作，复用重新选择资料与参数；未来领域入口随实际能力出现。

**验证边界。** 已核对最终整窗图与[流程](build/ui-workspace-review/final/verification.json)、[比较补拍](build/ui-workspace-review/final/comparison-recapture.json)、[原生检查](build/verification/native-workspace-final.json)、[产物记录](build/verification/ui-final-artifacts.json)：26 项原生检查和 6 项界面流程通过，资料为合成 fixture，真实 provider 调用为 0。真实模型接收/流式响应、物理 macOS 中文候选窗、完整屏幕阅读器流程未验收。[最终 ship](docs/reviews/2026-09-06-ui-finish-review.md)仅覆盖 F1–F4 修复评分；详细实现与限制见 [UI 实施记录](docs/plans/2026-09-06-ui-execution-log.md)。

## Do's and Don'ts

- **Do** 沿用现有 FA 标识、离线字体、系统主题、真实任务归属与可见焦点。
- **Do** 用保存的名称、单位、参数、来源与版本支持财务经理自主判断。
- **Don't** 合并执行/复算/阅核/发布状态，猜测旧参数语义或添加不可用业务入口。
- **Don't** 把工作副本恢复写成跨重启正式自动保存，或把窄窗回退写成移动端承诺。
- **Don't** 将分区标题做成大写 tracking 的 kicker；章节用标题元素承担层级。未定义的选择色 fallback 或原生控件局部色差也不推广为全局规则。
