# FA Foundry 0.1.9 UI 阅读与布局修复验收

本轮覆盖组件拥挤、金边过重、结果和文稿阅读层级、原生 harness 字号、任务侧栏五项反馈。参考 Kami 的留白、行宽、章节与表格规则，继续使用应用自带字体和明暗主题；未引入依赖。

## 改动与简化

| 范围 | 最终行为 | 主要文件 |
| --- | --- | --- |
| 间距与控件 | 标签间距 8px、动作间距 12px、表单行距 20px、阅读章节间距 32px；主要内容边距 24px，窄栏至少 20px。修复 details 内部仅写 gap 却未产生间距的问题。 | `app/src/styles/tokens.css`、`components/components.css`、`components/financial-controls.css`、`views/analysis.css` |
| 焦点与选中 | 常态和悬停使用中性边线；焦点只有 1px 细线，移除叠加的 ring、outline、border 效果；选中底色改为中性。 | `styles/base.css`、`styles/shadcn-bridge.css`、`components/ui/button.tsx`、`components/ui/tabs.tsx` |
| 原生对话 | 与右侧共用 Noto 字体、14px/22px 控件、16px/28px 正文；调整页签、设置入口、滚动区、输入区的上下和侧边留白。 | `app/electron/harness/skin.ts`、`app/harness-client/compact.css` |
| 分析结果 | 有明确字段且附加列仅为已知依据字段的 Python/shell 结果先展示项目、数值、单位；原始列仍可展开。多值及未知字段默认显示全表。去除表头填色，保持横向滚动局限在表格内。 | `views/analysis/RunPanel.tsx`、`views/analysis.css` |
| 文稿阅读 | 正文 16px/28px，最大行宽 42em；标题 24px，主章节 20px。按文稿实际 Markdown 层级确定标题，忽略代码围栏内的标题符号。仅折叠与正文末尾精确匹配的系统依据附录；编辑与导出保留完整正文。 | `views/Analysis.tsx`、`views/analysis/DraftBody.tsx`、`bridge.ts` |
| 侧栏 | 256px 常驻栏、288px 抽屉；增加任务标题、整合搜索、两行任务名称、期间信息和独立底部方法库入口，保留原有焦点与键盘行为。 | `components/Workspace.tsx`、`components/workspace.css` |

未写 `app/` 前缀的样式和组件路径以 `app/src/` 为基准。同步更新 `DESIGN.md`、验收计划、版本号与既有控件检查工具。删除冲突或冗余样式，复用已有 Table、Button 和阅读组件；未增加展示框架或数据转换层。

## 验证证据

- 前端全套：30 个测试文件、446 项测试通过。覆盖焦点对比度、原生皮肤、侧栏行为、标题层级、附录精确匹配及编辑保留、简表精度和完整列回退。
- 独立只读复核未发现阻塞问题；另跑相关 4 个文件、128 项测试通过，renderer 与 Electron 两套 TypeScript 检查通过。MCP LSP 通道不可用，使用实际 TypeScript 编译检查替代。
- `npm run package` 通过 harness、foundry、formulator 检查和 gate，以及 renderer/Electron 编译、Vite 构建、macOS arm64 打包。`git diff --check` 通过。项目未配置独立 lint 命令。
- 使用 CUA 检查明暗主题、1144/1440 等宽度下的阅读和侧栏，并在 `/Applications/FA Foundry.app` 检查原生对话、表单焦点、设置、真实结果和成稿。控件实测 14px、36px 高、1px 焦点线。完整明细的 `check` 列曾逐字换行导致表头高 130.5px，修复后为 42.5px；完整列仍可横向查看。
- 已安装并启动 0.1.9；构建包与安装包的 21,499 个文件及符号链接逐项比对一致。安装清单 SHA-256：`a0a5364c2c425aa8eceb410b9244fd9301a6d655bef60126c41e1f0b973dd445`。
- 原有月结验收任务恢复成功：2 份资料、29 次运行、6 份文稿。154 份分析 JSON 与修复前哈希一致；两份工作簿与原始导入清单一致。没有新发起模型分析，也没有改写源表。
- 安装版确认后，删除 `/Applications` 下本轮保留的 0.1.8 旧包和两个 0.1.9 中间候选包；保留当前应用和全部用户数据。最终视觉复核 93/100，达到 90 分门槛。

本机证据位于 `build/ui-reading-polish-20260908/`：`frontend-test.log`、`package.log`、`content-integrity.json`、`release-delivery.json`、`final-table-metrics.json`、`visual-verdict-final.json`。最终原生截图为 `final-full-table-native.png`、`final-draft-native.png`，侧栏和设置截图为 `installed-sidebar.png`、`installed-native-settings.png`。这些本机验收材料不包含在源代码提交中。

## 保留的边界

- 宽原始财务表仍需要横向滚动，避免隐藏多值列或强行压缩金额；简表不会重算、四舍五入或推断单位。
- 现有财务质量提示仍保留；本轮 UI 验收不代表源表差异已确认或文稿已获得财务审批。
- 原生客户端以后升级时，仍需复核皮肤适配。本轮验证的是当前打包的客户端。
- 当前为本机使用的未签名构建；既有构建提示包括缺少作者字段和较大的前端 chunk，未作为本轮 UI 工作扩展处理。未进行公证或公共分发验收。
