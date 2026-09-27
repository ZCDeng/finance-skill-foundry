# 首屏检查（R12）

财务经理在 1280×800 的窗口里打开一个有结果的任务，分析结果页不用滚动就要看到结论条或关键数卡片，默认视图里也不能出现 12 位编号、actual_1_8 这类英文情景码和 value、metric_key 这类英文列名。这项检查在打包应用上自动核对这几条，写在 `tools/verify_ui_workspace.cjs` 的 first-screen 阶段，种子数据由 `tools/fixtures/seed_first_screen_runs.py` 生成。

## 运行

先打一个未签名的候选包，放到 `app/release` 以外的目录，签名包保持不动。

```sh
cd app
npm run foundry          # foundry:check 报冻结 CLI 过期时才需要
npm run clean:electron && npm run build
npx electron-builder --mac --dir -c.directories.output=<候选目录> -c.mac.identity=null
cd ..
UI_CHECKS=first-screen \
PLAYWRIGHT_MODULE=<装有 playwright 的 node_modules>/playwright \
UI_APP_BUNDLE="<候选目录>/mac-arm64/FA Foundry.app" \
node tools/verify_ui_workspace.cjs
```

- `UI_CHECKS` 选要跑的阶段，逗号分隔，可选 `first-screen` 和 `workspace`，默认两个都跑。
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

## 已验证

2026-09-27，基于 1cc4fad 的工作树。

| 包 | 结果 |
| --- | --- |
| 当前代码 | 通过，6 张截图，结论条和第一句结论在 380 像素，声明任务第一张卡片在 665 像素，旧格式任务卡片在 380 像素，可见文字命中 0 处 |
| 临时把财务设置挪回结果上方 | 失败于 `first-screen-finance-light-1280 conclusion top 671.765625 stands above the finance settings at 212` |
| 撤回改动后重新打包 | 通过，结果同第一行 |

挪回之后结论条落在 672 像素，仍在 800 像素以内。收起状态的财务设置一共只有约 290 像素高，单看视口挡不住这次回退，所以加了「结论在设置之上」这一条。

## 已知限制

- workspace 阶段是 9 月 8 日写的旧流程，已经跟不上现在的界面。它先在焦点框断言上失败，旧断言要 2px，DESIGN.md 现在规定焦点框 1px、颜色用 `fnd-focus`。后面文稿步骤要找 `.analysis-draft-reading`，新报告编辑器已经不渲染这个元素。修好之前，首屏检查用 `UI_CHECKS=first-screen` 单独跑。这次只把它开头等待的表格名从「计算结果」改成「业务结果」，这个名字 9 月 23 日（a1d7d0d）就改了。
- 文字扫描只看默认可见的内容。财务运行「来源列（可选）」下拉框展开后列出 ledger、amount_change 这类原始列名，不在扫描范围内。
