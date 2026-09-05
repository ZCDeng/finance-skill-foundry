# UI 与交互优化实施记录

用户已批准按设计提案的落地顺序实施，并允许操作界面改用 HarmonyOS 或 Noto 中文字体。沿用本地既有改动，不提交、不新增软件依赖。

## 改动前的清理与验证计划

1. 先增加回归保护：完整问题和附件路径、未保存修改交给助手、导出精确新版本、任务切换隔离。修复后再改变布局。
2. 原生嵌入作为独立前置：可重放的紧凑客户端适配、受约束的矩形、持久在线输入与窄栏工具详情。不重写 runtime。
3. 合并重复的分析/对话入口；保留资料、历史交付与旧流程可达。任务内成果优先，删除重复输入和无业务用途的嵌套容器。
4. 业务参数元数据向后兼容；先有真实字段与绑定，再展示业务编辑控件。工作副本与不可变正式记录分离。
5. 统一字体、密度、颜色和控件。沿用现有组件和依赖；本地打包字体，不依赖机器字体或 localhost 字体服务。
6. 运行针对性回归、完整桌面与后端测试、类型/静态检查及打包验证。视觉采用一次批量检查、一次修复后确认；功能失败继续定位修复。

## 文件责任

- 主线：App、Shell、工作区容器、公共样式、字体资源及测试、设计文档、集成验证与打包。
- Analysis 界面：Analysis 与其拆分组件、analysis.css、分析界面测试；先连续操作修复，再结果/文稿/方法交互。
- Harness：electron/harness、相关 IPC/桥接、客户端适配与打包脚本、对应测试。
- 分析合同：foundry 分析/CLI、方法参数元数据与对应测试。

## 进度与证据

按 A → B → C → D 顺序完成实现，最终打包与功能验证通过。独立审查发现的 F1–F4 四项问题均评为 resolved，最终 disposition 为 ship；该结论覆盖这四项修复评分，不扩展为对所有未知状态的全面保证。

| 阶段 | 已实现行为 | 主要文件 |
| --- | --- | --- |
| A：连续操作与原生嵌入 | 完整问题/附件草稿；准确任务绑定；原生成功接收后才确认发送；阻断可重试且同一动作去重；持久会话、紧凑设置/工具详情；隐藏与显示不重载 | `App.tsx`、`electron/harness/`、`harness-client/`、`adapt-harness-client.mjs` |
| B：统一工作区 | 任务列表、持续对话、资料/结果/文稿共处；调整栏宽；窄窗专注切换；任务改名；方法库为次级入口；任务间草稿、版本、滚动隔离 | `Workspace.tsx`、`workspace.css`、`Shell.tsx`、`App.tsx` |
| C：财务分析交互 | 真实类型/单位/约束的业务参数；保存新口径并重跑；运行比较；来源抽屉；文稿阅读/编辑；交给助手或导出前保存确切版本；方法不携带原任务业务默认值 | `views/Analysis.tsx`、`views/analysis/`、`analysis.css`、`foundry/analysis_parameters.py`、分析/CLI 合同 |
| D：字体、视觉与验证 | 离线 Noto Sans SC；金额右对齐；稳定字号与间距；系统主题；键盘焦点、中文组合输入、缩放及真实窗口检查 | `styles/`、`assets/fonts/`、`electron/main.ts`、字体构建/打包检查与验证脚本 |

### 本轮已运行的验证

- 完整桌面测试：342 passed / 27 files，另通过两个 TypeScript 配置；这是最终产品源码对应的结果。
- 完整后端测试：570 passed、12 skipped；随后配置本地 DSH 路径补跑 `tests/test_real_load.py`，10 passed。余下 2 项依赖项目环境没有的 pyarrow/data_formulator；冻结的 Formulator gate 单独通过。
- Python Ruff、Node 语法、插件资源镜像及 `git diff --check` 通过。
- 冻结 foundry 的无模型 fixture、自检、harness pin/适配检查、Formulator 打包门禁均通过。
- 最终包原生交互 26/26 通过：400/460px 设置与工具详情、Escape 返回焦点、任务 A/B/A 草稿与 document 不变、125% 缩放、非法/过期/越界矩形、同一动作重试去重、Chromium 中文组合输入、真实 visibility 与系统深浅主题。初版报告只检查零尺寸，随后整窗截图发现残留 native layer；修复采用 `setVisible(false)`，最终报告与截图共同确认隐藏，未沿用初版的不足结论。
- 首轮视觉检查修复文稿 Markdown 阅读排版、依据抽屉的位置/焦点与工作区未铺满窗口；独立审查 F1–F4 后修复 native 隐藏、来源别名解析、运行版本的参数名称/单位/假设展示。Playwright 曾为原生页面强制浅色；清除每个 page 的媒体模拟后，系统主题在壳和原生区均通过实测。
- 打包后验收确认 1280×800 下结果表起点为 y=333.09；修改费用分摊 20 → 30 后利润 250 → 240；比较运行、来源别名打开原始快照、文稿保存后导出、任务改名持久化通过。最终窗口覆盖 1440×900、1280×800、1080×760。合成 fixture 仅用于验证，不进入用户资料。
- 真实导出的 XLSX 经 openpyxl 检查：文稿标题、正文、版本号，所有结果单元格及 Evidence 运行 ID 均与保存记录一致。手工编辑文稿不会悄悄切换其已引用的历史运行；验收专门保留并检查这一关系。
- 最终 `app.asar` SHA-256：`13619ac6c9e7f452fc5165964ea79c980ce1c7cf554d0653c85d274dfbb8d2c5`，UI 完整流程及原生 26 项检查记录一致。

### 字体来源与交付

采用 Google Fonts 官方 Noto Sans SC，固定提交 `5e35378e6bda803962ee6fd257e444a7d459660d`，保留 OFL 与重建说明。变量字重 100–900；WOFF2 8,490,924 bytes，SHA-256 `97a715fad95d3cacf4838b1ffedb123d2f1bf0f6bbd726c73e147dcaf317869f`。应用壳和原生客户端均随包包含字体。发现并修复原生字体仅进入 staging、未进入 App Resources 的遗漏，新增 afterPack 存在性/哈希门禁。删除原来的 231 个 LXGW 资源，保留三片 Asap 品牌字体。

### 证据入口

- `build/verification/vitest-ui-final.txt`、`pytest-ui-final.txt`、`real-load-ui-final.txt`
- `build/verification/package-ui-final.txt`、`native-workspace-final.json`
- `build/verification/workbook-ui-final.json`：真实工作簿内部核对
- `build/verification/ui-final-artifacts.json`：最终包哈希与各项验收对应关系
- `build/ui-workspace-review/final/verification.json` 与同目录 OS 整窗截图（`*-window.png`）
- `tools/verify_ui_workspace.cjs`、`tools/verify_native_workspace.cjs`：可重复的隔离验收脚本
- `tools/verify_ui_workbook.py`：导出结果逐单元格核对
- `docs/reviews/2026-09-06-ui-finish-review.md`：独立初审与修复评分；初审截图保留在 `build/ui-workspace-review/pre-finish-fixes/`。

本地产物：`app/release/mac-arm64/FA Foundry.app`。字体 afterPack 校验通过；打包未新增项目软件依赖。

### 验证边界

未调用真实模型验证 admission/流式响应；原生提交成功分支使用明确标注的 synthetic sink，真实模型请求数为 0。中文输入覆盖 Chromium composition，未覆盖物理 macOS 候选窗。没有把本地未签名目录包称为正式公开发行，也没有安装/覆盖用户 `/Applications` 中的应用。

Impeccable 检测器仅运行一次，结果 `[]`。完成复核使用无历史上下文的原生子代理；当前工具未注册技能专用角色名，因此显式提供技能的 finish-reviewer 工作规范作为替代，最终按复核实际结论记录。

最终设计约定记录于 `DESIGN.md` 和 `.impeccable/design.json`，由另一独立子代理依 documenter 规范从实际代码整理。保留 Noto/品牌体系和可复用控件，并明确：成果滚动按任务恢复，资料/结果/文稿复用成果容器；sessionStorage 工作副本不等同于跨重启的正式自动保存。

最后一次比较图补拍仅关闭了依据抽屉，未修改产品代码。`comparison-recapture.json` 确认真实保存的 30/20 万元与 240/250 利润并列；截图使用同一任务后续已保存的新名称。其余终版截图与主流程记录保持对应。
