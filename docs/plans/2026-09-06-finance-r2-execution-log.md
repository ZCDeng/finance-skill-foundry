# 财务能力 r2 实施记录

最新阶段 1–7 交付状态及性能结果见 [最终验收审计](2026-09-06-finance-r2-completion-audit.md)。下文阶段 0 的版本/数量/待办是当时历史记录，已由文末最终交付记录补充。

本轮用户要求先提交推送当前成果，再执行 r2。执行依据为 `.omx/plans/2026-09-06-finance-capability-plan.md` 和配套 34 条验收合同。

## 执行前基线

- 已提交并推送 `4116de1256d0e8ac633ed463290d93224472cecb` 至 `origin/main`，使用 `git ls-remote` 验证远端哈希相同。
- 基线包括统一财务分析工作区、UI/Noto 字体、测试、研究与 r2 计划；本机 `.omx/state/` 和构建/资料目录排除。
- 本次基线复验：Python 570 passed、12 skipped；其中 10 项真实 harness 测试随后显式指定本地运行时补跑通过，另 2 项可选依赖测试仍跳过。桌面 342 passed，两个 TypeScript 项目检查、插件 smoke、JS 语法及 staged diff 检查通过。
- 全目录 Ruff 检查有 22 条既有诊断，包括冻结脚本的显式模块打包导入及验证脚本格式；未在基线提交中伪报全量静态检查通过。

## 阶段 0 的改动

1. 先增加资源接线、运行模式和真实提供方/loader 的回归保护。用现有方法资源定位和运行时 bundled 根解决发现问题，保留用户技能与 SQL/Python。
2. 适配 canonical 方法及配套指引，同步打包镜像；analysis 与旧 period/f3 分别使用可信运行模式，解除旧单表/锁定窗口对普通分析的干扰。
3. 以合成企业资料和实际配置模型验证 G1/G2：技能加载、计算、run、草稿与来源证据均需保留，固定查询或模拟模型不能替代此项。
4. 开发态通过后重建应用，在隔离测试配置与安装位置复验发现、引用加载、真实分析和重启；不依赖个人技能或开发仓库。
5. 阶段 0 完成后再推进阶段 1–3 的财务口径、差异工具与 Excel 文件协作；ERP、Excel 原生插件及外部 MCP 分别遵守计划中的真实联调出口。

## 技能接入验收结果

A27–A34 已通过。实现和验证都沿用真实 harness，未新增技能加载器或项目依赖。详细的来源哈希、会话 ID、run ID、草稿 ID、单元格与调用顺序见 [结构化证据](../finance/r2-stage0-evidence.json)，复现命令见 [运行验收说明](../finance/skill-runtime-verification.md)。

| 合同 | 证据与实际结果 |
|---|---|
| A27 | canonical、Python 资源镜像、构建包及 `/Applications/FA Foundry.app` 的 9 个方法文件逐字节一致，包含四个正文、共享说明及 NOTICE/LICENSE；归档包内容也已核对 |
| A28 | 真实 `skill-filesystem` 在隔离目录发现并加载四个 bundled 技能；同名个人技能测试验证 `user-agents` 优先且文件哈希不变；安装版运行时模块另补跑 3 项通过 |
| A29 | 开发态及安装版 analysis 会话用真实 `skill` 工具逐项加载四个正文，`method-resource` 读取 FOUNDRY/CONNECTORS，正文和引用的来源及内容哈希匹配 |
| A30 | G1 在无 Window 的 analysis 任务组合实际与预算两份资料；既有 period/f3 与可信 session 权限合同全量回归通过 |
| A31 | 原配置 `deepseek-official / deepseek-v4-flash / max` 的完整回合：G1 利润差异 +5、分量 +20/−10/−5；G2 收入差异 +32、先数量后价格分量 +20/+12；相关技能先于计算加载，同一草稿逐项引用全部成功 run 单元格并闭合 |
| A32 | 缺失根不崩溃；损坏 frontmatter 的真实提供方日志包含文件路径和原因；引用路径/技能 ID 校验有回归保护。通用分析保持可用，ERP 标记仍为占位，未引入普通分析审批 |
| A33 | 四个 ID、Apache-2.0/NOTICE 和经理决定口径的原则保留；未写入全局技能或 var/skills；现有 save_method/apply_method 重绑复用及个人判断草稿回归通过 |
| A34 | 实际启动 `/Applications/FA Foundry.app` 0.1.2，由其自身资源生成 harness；验证真实父子进程、技能来源与 G1/G2。退出再启动后四个正文/引用哈希一致，原 run 和草稿仍在 |

开发态证据保留在 `build/verification/r2-skill-session-dev-07/`，其完整原始回合又用最终严格检查器复验，结论为 `verification-strict.json`；安装版最终证据为 `build/verification/r2-skill-session-installed-04/verification.json`。原始会话、合成输入及结果保留在忽略的本机构建目录；仓库中提交不含凭据的证据摘要。

## 本轮修复与验证中的边界

- 真实模型暴露了 `analysis-save.relationships` 的弱 schema：现在明确左右绑定、键和 cardinality，后端在保存前校验结构，保留已有 `keys` 合同以及重复键/多对多约束。
- `analysis-draft.claims` 现在明确 basis、run、行、列、值。非对象工具参数返回简洁错误，便于模型恢复。
- 初始验收器曾过早结束模型回合、将费用差异符号视为错误，及与桌面恢复会话竞争；这些均在最终验收前修正。最终检查排除同值比例/原始指标，要求草稿引用完整差异桥，10 项检查器回归通过。
- 模型不是每次调用都成功。最终开发态有 4 次工具参数错误、1 个失败 run；安装版有 1 次工具参数错误、1 个失败 run。模型均自行修正后完成。失败 run 来自派生表 JOIN 缺少独立粒度合同，现有数据约束未放宽；后续专用财务工具应减少这类可恢复错误。
- 这次仅运行阶段 0 的两道模型题，不代表后续至少 30 题解释质量评测通过，也不代表企业 ERP 或 Excel 原生刷新已联调。

## 回归与交付

- Python：`FOUNDRY_DSH_BIN=.../app/extra/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js .venv/bin/python -m pytest -q` → **611 passed、2 skipped**。两项跳过为可选 pyarrow / data_formulator 环境；真实 harness 测试已实际运行。
- 桌面：27 个测试文件，**344 passed**；两个 TypeScript 项目与 Vite/Electron 打包检查通过。
- 冻结 Foundry 自检、来源指纹、Formulator 检查/隔离 gate、插件 JS 语法通过。新增及修改的核心 Python/验收器定向 Ruff 通过；全目录仍有基线已有的 **22 条 Ruff 诊断**，未宣称仓库静态检查全绿。
- 独立代码复核通过；验收器复核指出的贡献语义及完整草稿引用问题修复后再次通过。
- 交付版本：桌面 **0.1.2**。已安装到 `/Applications/FA Foundry.app`，运行时原生复验完成。包为本机使用的未签名构建，未进行公证发布。
- 新包：`app/release/FA-Foundry-0.1.2-macOS-arm64-r2-stage0.zip`，497,538,934 字节；SHA-256：`1fa07bb073934ec02ef21b73df36d499a9a1a0dc2f4788a98baff29b3f83ef65`。已经核对 ZIP 中版本和方法内容，旧 0.1.1 归档、旧 release 子目录及替换时保留的备份已清理。

## 后续执行位置

阶段 0 的技能接入及样本/基线准备已完成。下一阶段按 r2 进入企业账套与可执行指标：先修复下述 snapshot 装载热点，再做 LedgerScope/SourceBatch、AccountMap、余额/预算和管理损益指标，使用本轮静态企业样本建立 A01–A05、A08–A09 的合同。阶段 1–7 尚未完成，不以阶段 0 通用 SQL 的通过代替财务领域对象、专用工具、Excel 文件绑定或 ERP 能力。

## 企业样本与性能基线

服务、商品销售和多组织三类合成企业样本及独立真值已保存；新增同一科目借贷变动、贷方有符号余额、红字、结转、调整、未过账，以及同凭证多行/跨账套同号样本。G1/G2 分解闭合、G5 的 110 和 −220 余额、CSV 结构均已独立核对。准备样本不等于完成 A01–A09 的领域实现；G4 的期后回款/部分核销等保留给阶段 5。详见 [样本说明](../finance/finance_baseline_fixtures.md)。

100,000 行 CSV 的 5 次实测，机器为 macOS arm64、10 核、24 GiB，Python 3.14.4；每轮利润均为独立真值 250110。原始数据见 [基准 JSON](../finance/r2-stage0-benchmark.json)。

| 指标 | 实测中位数及口径 |
|---|---|
| 导入 | 1.5749 秒，低于 30 秒初始目标 |
| 首次查询 | 117.1204 秒，每轮新 snapshot 的第一次执行 |
| 进程 RSS 高水位 | 查询后 439,730,176 字节，约 419 MiB；为同一进程的累积高水位，不是各轮独立峰值 |
| 热查询 / 取消 | 本轮未测，不标记 A25 全项达标 |

一次独立 5,000 行 cProfile 验证得到导入 0.0928 秒、首次查询 7.824 秒；`_duckdb.executemany` 累计 7.781 秒，占该次剖析总时间约 97.9%。热点位于 `foundry/analysis_sql.py` 的 snapshot staging：每次查询创建内存表并经 Python 参数绑定逐行插入，内部伴随大量 importlib 查询。下一步优先评估受控快照的原生批量装载，保留显式 DECIMAL schema、来源哈希、精度/粒度合同和用户 SQL 的外部访问限制，不通过开放任意文件读取换取速度。

当前源上限仍为 32 MiB、100,000 行、256 列；SQL 返回行数默认 1,000、最大 10,000。扩容前先完成装载优化和冷热查询/取消测量，不增加新的运行时依赖。

## 提交记录

- `4116de1256d0e8ac633ed463290d93224472cecb`：执行前产品/研究/r2 基线，先行推送并核对远端。
- `a48f91b24711a2c779387516fa505aff40f1a326`：执行基线记录。
- `3e23cee55282fbc39686c8887032f476c9d8b0aa`：阶段 0 技能接线、方法适配、工具合同、真实会话及安装版验收，已推送。
- 本记录及企业样本、性能测量以随后的独立提交保存，避免把样本准备误计为新增财务领域能力。

## 阶段 1–7 最终交付（2026-09-06）

实现与本轮验收闭环完成，阶段 4 按用户答复交付通用适配与文件刷新，真实 ERP 租户联调待测试账套。最终 Python 为 758 passed、2 skipped，App 为 361 passed，变更 Python Ruff、TypeScript 与构建检查通过；真实 Excel、外部 MCP、最终安装版技能调用/重启和预算桥 UI 均通过。10 万行冷查询中位数降至 1.269 秒，热查询 1.130 秒。

30 题模型评测完成尝试覆盖，29 题完成，22 题含重跑至少一次严格通过，解释质量门槛尚未满足；按既定计划保留为可编辑草稿和失败证据，不降低数值/来源标准。

最终交付 0.1.3：`app/release/FA-Foundry-0.1.3-macOS-arm64-r2-20260906-0853.zip`，SHA256 `7aa0a4fa34c151ad3bd78335e360ac916f834bba0ea9f2db21fe7364890b6131`；已安装到 `/Applications/FA Foundry.app`，归档与安装版哈希一致。旧阶段 0 归档和中间 renderer 归档均已清理。
