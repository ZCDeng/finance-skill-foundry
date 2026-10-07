# 首屏检查（R12）

财务经理在 1280×800 的窗口里打开一个有结果的任务，分析结果页不用滚动就要看到结论条或关键数卡片，默认视图里也不能出现 12 位编号、actual_1_8 这类英文情景码和 value、metric_key 这类英文列名。这项检查在打包应用上自动核对这几条，写在 `tools/verify_ui_workspace.cjs` 的 first-screen 阶段，种子数据由 `tools/fixtures/seed_first_screen_runs.py` 生成。同一个脚本的 workspace 阶段跑完整的工作区流程，9 月 27 日已按现在的界面改好。两个阶段一起跑通才算过门，门禁用的是不带 `UI_CHECKS` 的完整命令。

## 运行

先打一个未签名的候选包，放到 `app/release` 以外的目录，签名包保持不动。

```sh
cd app
npm run foundry          # foundry:check 报冻结 CLI 过期时才需要
npm run clean:electron && npm run build
npx electron-builder --mac --dir -c.directories.output=<候选目录> -c.mac.identity=null
cd ..
PLAYWRIGHT_MODULE=<装有 playwright 的 node_modules>/playwright \
UI_APP_BUNDLE="<候选目录>/mac-arm64/FA Foundry.app" \
node tools/verify_ui_workspace.cjs
```

- `UI_CHECKS` 选要跑的阶段，逗号分隔，可选 `first-screen` 和 `workspace`，默认两个都跑。写错阶段名，脚本在启动应用前就报错退出。只在排查时单跑一个阶段，这样的结果不能当门禁。
- `verification.json` 的 `status` 只在两个阶段都跑且都通过时写 `passed`。少跑一个阶段写 `partial`，`skippedPhases` 列出没跑的阶段，`notRun` 写明原因。断言失败写 `failed`，`error` 里是失败信息。每次运行都会重写这个文件，上一次的 `passed` 不会留下来。
- `UI_APP_BUNDLE` 指定被测的 .app，默认 `app/release/mac-arm64/FA Foundry.app`。
- `UI_EVIDENCE_DIR` 指定截图和 `verification.json` 的目录，默认 `build/ui-workspace-review`。
- 种子脚本用仓库的 `.venv/bin/python` 运行，需要能导入 `foundry`。

脚本在 `/tmp/finance-ui-workspace-*` 建一套隔离的 var 和 Electron profile，全部数据是合成的，不发模型请求。

## 种子数据

三个任务都经打包应用自带的 foundry CLI 写入，在检查开头、其他任务之前建好。

| 任务 | 运行 | 做法 |
| --- | --- | --- |
| 首屏检查 · 财务差异 | 财务引擎预算差异运行 | 实际和预算两份合成台账，`finance-context-save` 后 `explain-variance` |
| 首屏检查 · 声明长表 | 带 `row_declarations` 的脚本长表运行 | `analysis-script` 写出 13 行长表，含 actual_1_8、budget_1_8、revenue_variance、单位为比率的 revenue_achievement_ratio，东部和西部区域的预算 basis 为 estimate |
| 首屏检查 · 旧格式长表 | 无声明的旧格式运行 | 同一脚本同样保存后，删掉运行记录里的 `row_declarations` |

CLI 保存新脚本运行时总会写声明，所以旧格式运行要事后改记录。种子脚本删掉该字段，去掉旧的 `_integrity_hash`，用 `foundry.analysis._hash` 按存储自己的方式对其余字段重新算哈希，写回原路径，`seq` 和其他字段一个不改。随后用仓库里的 `AnalysisStore.get_run` 和打包 CLI 的 `analysis-state` 各读一遍，两处都校验哈希，读回的记录都没有声明且 `seq` 不变。

## 断言

每个任务在 1280×800 下从任务列表打开，停在分析结果页，浅色和深色各截一张图，每张图都重新测一遍。

- 视口是 1280×800，结果区和页面的滚动位置都是 0。
- 财务任务的结论条、声明任务的第一句结论和第一张卡片、旧格式任务的第一张卡片，上边缘都落在结果区可见范围内（120 到 800 像素）。
- 页面上有财务分析设置时，上面这些元素的上边缘都要在设置之上。
- 分析结果页上看得见的文字不含 12 位以上十六进制串和 snake_case 代码，也不含这次运行自带的原始列名、行字段名和英文取值（例如 value、metric_key、scenario、revenue、unfavorable）。折叠着的 `<details>` 只算摘要行；下拉框只算当前选中的那一项。
- 旧格式任务的每张卡片都标「推断」，声明任务没有一张卡片出现「推断」。

截图命名为 `first-screen-<finance|declared|legacy>-<light|dark>-1280.png`，同名的 `-native.png` 和 `-window.png` 是原生层和整窗截图。测量值写进 `verification.json` 的 `firstScreen`。

## workspace 阶段

first-screen 跑完后，脚本回到「华东八月经营分析」这个 SQL 任务，按财务经理的顺序走一遍结果、资料、依据、比较、文稿、窄窗、任务抽屉、改名和新建任务。9 月 27 日对照 DESIGN.md 和现在的组件改了下面几步，旧断言针对的界面已经不在了。

| 步骤 | 旧断言 | 现在的断言 | 依据 |
| --- | --- | --- | --- |
| 结果首屏 | 第一个 `.analysis-table` 上边缘小于 450 像素 | 名为「业务结果」的整张表落在结果区首屏可见范围内，结果区没有滚动 | 表名 9 月 23 日改为「业务结果」（a1d7d0d），检查本来要的就是首屏包含结果表 |
| 账簿字段悬停加聚焦 | 只在深色量一次，要 2px 焦点框、金色 #e2c180 | 浅色和深色各量一次，都要命中 `:focus-visible`，1px 实线，偏移 -1px；边框保持 `fnd-line`（浅色 rgba(31, 31, 31, 0.14)，深色 rgba(255, 255, 255, 0.14)），焦点框用 `fnd-focus`（浅色 #8a6729，深色 #bfa36c） | DESIGN.md「按钮与字段」和前置 token，`components.css` 的 `.fnd-field:focus-visible` |
| 调参重跑 | 页面任意一格出现 240.00 | 「业务结果」表里出现 240.00 | 表名依据同第一行 |
| 查看资料快照 | 页面任意一个「八月经营数据」标题 | 「依据资料预览」区里的标题，资料标识写着运行绑定的资料版本 | `Analysis.tsx` 在结果页打开依据资料预览，`DatasetPreview` 写出资料版本 |
| 文稿阅读 | 找 `.analysis-draft-reading` 截图（该类已于 2026-10 移除，阅读视图现为 `.report-reading`） | 已保存的文稿停在「阅读」，工具栏写「文稿」和「草稿 · 未阅 · 检查」；阅读区渲染出标题、两个章节、加粗的 250 万元和两条列表，不留 `**`；正文 Noto Sans SC、16px/28px、段后 18px | DESIGN.md「文稿与方法」和 Typography，`ReportEditor.tsx` 的阅读模式，`report.css` |
| 文稿编辑与导出 | 点「编辑文稿」，往 `.analysis-draft-fields` 第一个 textarea 填正文，拦 `shell.openPath` | 切到「编辑」，标题框和 Markdown 源码框带出已保存内容；改源码后可视化编辑器跟着变，状态变成「改稿后未重检」，出现「保存文稿新版」和先保存再导出的提示；从「导出」菜单选「导出工作簿」，拦下 `dialog.showSaveDialog` 并给 QA 目录里的路径，等到「已导出工作簿」加这条路径 | 导出现在先弹保存框（`electron/reports/host.ts`），不再调 `shell.openPath` |
| 导出后的记录 | 最新文稿正文是新正文，分析 2 版，运行 2 次 | 另要求文稿共 2 版，新版的上一版是原稿，引用的运行仍是 250 那次 | DESIGN.md「改正文不替换已引用的历史运行」 |

依据面板按 Escape 关闭后焦点回到按钮，版本比较出现对照表，窄窗成果专注、任务抽屉和新建任务时隐藏原生层，改名后任务编号不变，这几步和现在的界面一致，没有改。截图有 `results-1440`、`results-1280`、`materials-collapsed-1280`、`materials-focus-<light|dark>-1280`、`evidence-1280`、`comparison-1440`、`draft-1440`、`draft-dark-1280`、`draft-edit-1280`、`results-narrow-1080`、`tasks-overlay-1080` 和 `new-task-1280`，测量值写进 `verification.json` 的 `measures`。

## 已验证

2026-09-27，基于 1cc4fad 的工作树。

| 包 | 结果 |
| --- | --- |
| 当前代码 | 通过，6 张截图，结论条和第一句结论在 380 像素，声明任务第一张卡片在 665 像素，旧格式任务卡片在 380 像素，可见文字命中 0 处 |
| 临时把财务设置挪回结果上方 | 失败于 `first-screen-finance-light-1280 conclusion top 671.765625 stands above the finance settings at 212` |
| 撤回改动后重新打包 | 通过，结果同第一行 |

挪回之后结论条落在 672 像素，仍在 800 像素以内。收起状态的财务设置一共只有约 290 像素高，单看视口挡不住这次回退，所以加了「结论在设置之上」这一条。

2026-09-27，基于 d5a1836 的工作树，两个阶段一起跑。

| 包 | 结果 |
| --- | --- |
| 当前代码 | 通过，`status` 为 `passed`，11 条检查，首屏数值同上表 |
| 临时把 `.fnd-field` 焦点框改成 2px | 失败于 `light ledger hover + focus`，实测 outline 2px |
| 撤回后临时把 `.report-reading` 行高改成 22px | 失败于 `reading typography per DESIGN.md`，实测行高 22px |
| 撤回改动后重新打包 | 通过，结果同第一行 |

同一个包单跑 `UI_CHECKS=first-screen` 和单跑 `UI_CHECKS=workspace`，`status` 都是 `partial`，`skippedPhases` 分别是 `workspace` 和 `first-screen`。

## 已知限制

- 文稿阅读区的行长不做断言。DESIGN.md 写约 42em，`report.css` 从 9 月 9 日（7b8f55a）起把阅读列放宽到 56rem，1440 窗口下实测 733 像素，约 46em。两边哪个作准要先定下来。
- 版本比较只确认对照表出现，不核对「修订差异」那句话。这个 SQL 任务的行没有 metric_key 这类业务身份，一行都没参与比较，界面照样写「可比较指标没有发现数值变化」，下面两张对照表的经营利润却差了 10 万元。这是产品文案的问题，见 `comparison-1440.png`，已另行报告，检查没有为它改。
- 文字扫描只看默认可见的内容。财务运行「来源列（可选）」下拉框展开后列出 ledger、amount_change 这类原始列名，不在扫描范围内。
