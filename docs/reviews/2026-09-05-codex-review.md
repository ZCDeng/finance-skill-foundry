---
title: Finance Skill Foundry 全面审查
reviewer: codex
review_date: 2026-09-05
baseline_commit: efbbc1b
repository: /Users/zcdeng/projects/finance-skill-foundry
code_verdict: REQUEST CHANGES
existing_architecture_for_new_goal: BLOCK
revised_plan_verdict: CLEAR
scope: 代码与方案审查；新版产品架构和验收设计；未修改运行代码
---

# Finance Skill Foundry 全面审查

## 结论

现有系统具备值得保留的工程底座：原始输入归档、DuckDB 只读快照、Decimal 金额、任务/交付版本、历史追问和 companion 生命周期管理。但它的实际计算能力与“财务经理的分析工作台”不匹配：问题只是计算结果的标题，核心仍是单表求和与分组，缺少过滤、比较、联查与假设计算。

不能用来源标签证明“算的是用户的问题”，也不能用全套测试通过证明完整业务已实现。代码审查为 **REQUEST CHANGES**；旧方案面对本次新目标的架构结论为 **BLOCK**。新版方案已完成独立复审，结论为 **CLEAR（方案层）**；不意味着新功能或运行缺陷已经修复。

本轮完成文档修订，不改运行代码，不提交或推送。问题依优先级进入新版方案的 P0/P1。

## 审查依据与覆盖

基线：2026-09-05 本地 HEAD `efbbc1b`，开始时工作区干净。任务环境仍指向旧目录 `/Users/zcdeng/projects/mySkills/finance-skill-foundry`，实际仓库已迁至本文元数据所列路径，远端为 `ZCDeng/finance-skill-foundry`。

先读取 8/25 原始计划、8/30 task-chain、9/1 fence-scope，以及 README、CONCEPTS、method/FOUNDRY，再按实现审查。历史记录仅用于找到原约束；结论依据当前代码和本轮复现。

- 独立代码 lane：catalog/window/task、brief/query/questions、references/workpaper/sheet、probe/CLI、插件调用与注册、Electron 会话与 IPC、主要工作台入口和相关测试。
- 独立架构 lane：产品契约、流程、数据与分析生命周期、preset/fence、harness 开放及未来领域边界。
- 主线：审查整合、测试/构建、真实 harness 检查、新版方案与验收文件；新版方案交由架构 lane 再次复审。
- Formulator 生命周期、打包和样式主要做接口与测试覆盖检查；未逐行审计第三方依赖，也未进行完整安装后 GUI 验收或客户真实数据验证。

## P1-01 问题文本没有进入计算，整表汇总却被归档为问题答案

**位置：** `foundry/brief.py:42`、`:209`；`foundry/query.py:232`、`:275`。

`_aggregate` 有 amount 就求和，否则计数；query 增加单个 split_by 或 map-cut。问题 text 用于输出与匹配，不会产生地区筛选、比例、期间比较或指标公式。

**独立代码 lane 实测：** 同一科目 North=70、South=30。问“North 收入是多少？”，brief 输出“锁库汇总 100。我重算 100”；问“North 收入占比是多少？”，query 输出 100，仍带重算标签。实际答案应分别为 70 与 70%。

**影响：** 字节来源可追踪，但数值没有回答问题。财务经理的判断力需要实际计算表达与明细支撑，不能补足一个未执行的过滤条件。

**建议：** P0 明确旧工具仅提供汇总，避免其工具描述承诺任意问答；P1 引入显式 AnalysisRevision 和 Run，包含过滤、指标、比较、关系、假设。不要添加关键词猜测来替代分析表达式。验收 A07/B01/B02。

## P1-02 多任务会话使用全局 current，恢复先前任务无法继续

**位置：** `foundry/cli.py:503`；`dsh-plugin/index.js:55`；`app/electron/ipc/register.ts:216`。

App 已登记 session 属于哪个 task，插件调用只传 session（task 仍可能来自进程环境）；CLI 先取 global current，再检查归属。

**独立代码 lane 实测：** 建 A/windowA/session-A，再建 B/windowB/session-B，返回 A 调 import：exit 3，session-A 已属于 A，不能登记到 B。即使增加 `--task A`，也因 current=windowB 返回“window belongs to B, not A”。

**影响：** 现有 guard 阻止错写，是正确保护；缺少正确路由导致正常使用失败。简单删除 guard 会把可见拒绝变成跨任务写入，不能采用。

**建议：** 持久 session→task/context/snapshot 绑定，每次工具调用从可信注册记录解析。current 仅留给无上下文 CLI。覆盖 A→B→A、并发、重导后旧会话、fork/child 继承。验收 A01/A02。

## P1-03 XLSX 输出的精度判断不符合实际序列化

**位置：** `foundry/sheet.py:79`、`:97`。

当前 `Decimal(repr(float(value))) == value` 只检查 Python float 的表示，不检查 openpyxl 实际写出的单元格。

**独立代码 lane 经 put_number→save→load 实测：**

| 原 Decimal | 重新读取 XLSX |
| --- | --- |
| 123456789012345.67 | 123456789012345.7 |
| 1234567890.1234567 | 1234567890.123457 |

**影响：** 已归档 Excel 与准确的原金额不同，和当前产品“不能精确保留就存文本”的合同冲突。

**建议：** 按实际序列化精度判断；不能精确往返的值存原值文本。测试必须保存并重读真实 XLSX，不只检查内存 Cell 或 float round trip。验收 A04。

## P1-04 JSON 金额在进入 Decimal 前已失真

**位置：** `foundry/catalog.py:195`。

`json.loads` 默认将小数解析成 float；后续 Decimal 无法恢复原 token。

**独立代码 lane 实测：** 原始 JSON `{"account_code":"1001","amount":900719925474099.99}` 经 load_tabular 变为 `900719925474100.0`。

**建议：** JSON parse_float 使用 Decimal，保留非有限值及范围检查；对 JSON 路径后的类型推断和序列化一起做兼容验证。用文本字面量构造测试，避免在测试生成阶段先损失精度。验收 A03。

## P2-01 并发追加引用可丢记录，与底稿分裂

**位置：** `foundry/references.py:68`、`:105`、`:118`。

读取、去重、合并发生在窗口锁外；Locked 分支写入也未被同一事务覆盖。

**独立代码 lane 受控交错复现：** Barrier 让两个线程都先读取空引用集，随后分别追加 id=1、id=2。两调用成功，最终 references.json 仅 `['1']`，schedules.json 却为 `['q1','2','1']`。

**建议：** 状态检查、读取、去重、合并、写入与对应底稿更新放在同一窗口锁范围；同时测试引用与出稿并发，避免新的死锁与记录脱节。验收 A05/A06。

## P2-02 方法 done-gate 的证据不足以证明方法可执行

**位置：** `foundry/probe.py:226`。

validate_authored_skill 检查非空说明与契约，run_probe 跑固定引擎 fixture，并不接收或执行 authored instructions。

**影响：** 可证明“契约有效、引擎通过自检”，不能证明“这个用户的方法能完成分析”。此项为代码路径证据，未执行模型方法实跑。

**建议：** 拆分契约校验、引擎自检、方法样例执行。新方法以自身输入、计算定义和期望输出验收；无需让用户在首次使用前先创建方法。验收 A08/B08。

## 产品与架构限制

| 现状与证据 | 对使用的影响 | 新版处理 |
| --- | --- | --- |
| questions.py:11，一次登记；brief.py:114，一窗一稿 | 用户改问题/判断也被数据锁限制 | 快照不变，分析与文稿可多版本 |
| caliber.py:394，一次仅一张 named fact table | 预算、同比、应收核对无法完整表达 | 多快照/多表绑定，检查粒度与关系 |
| f3-scope.js:24、index.js:452，仅 query-locked | 领导追问时不能外部研究或登记引用 | 追问延续分析能力，绑定其报告版本 |
| Workbench.tsx:29，写方法/开始本期/追问及 preset 名 | 用户需理解内部座位和流程 | 从问题与资料开始；方法事后沉淀 |
| 9/1 KTD11，永久禁 shell/fs/delegation | 限制资料、清洗、专题与并行研究 | 明确修订旧政策，开放任务内执行 |
| window.py:685/743，仅 read_only 连接 | 不能直接暴露任意 SQL 并宣称隔离 | 独立 runner 与数据 broker，记录实际执行 |
| 当前 lock/external 依据分类 | 财务经理自己的预测假设无合适表达 | 来源/计算/外部/假设/判断，与验证状态分开 |

边界应保护历史记录、准确金额、调用归属与计算证据。用户可以修改假设、调整口径、接受局限；不是每个分析动作都需要批准。未来正式过账/付款走领域服务与具体命令，分析结论的认可不等于交易授权。

## 本轮验证证据

| 验证 | 结果 | 范围与限制 |
| --- | --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 381 passed, 10 skipped，46.43s | 初始默认套件 |
| `npm test -- --reporter=dot`（app） | 15 files、236 tests passed | 包含 mock/渲染及配置测试；不等于完整 GUI 实跑 |
| `npm run build`（app） | 通过 | TypeScript 两配置检查与 Vite 构建 |
| 设置 staged `FOUNDRY_DSH_BIN` 后单跑 `tests/test_real_load.py` | 8 passed，23.90s | 补齐默认跳过的真实 runtime 加载/权限检查；不是付费模型任务实跑 |

剩余两个默认跳过项涉及可选 pyarrow/data_formulator Python 依赖；本轮未安装依赖补跑。默认测试与补跑不能简单相加称“全部无跳过”。本轮未执行冻结 Formulator gate、安装应用验证、生产数据验证或依赖漏洞扫描。项目未配置独立 lint 脚本；未将类型检查冒称为 lint。

桌面测试另输出一次重复 React key `3` 警告，位于工作簿预览相关测试。未单独证明为生产缺陷，保留为低优先验证项，不与上面的已复现数据问题混列。

## 交付与下一步

- `../plans/2026-09-05-finance-analysis-workbench-plan.md`：新产品逻辑、旧决策替换、能力矩阵、执行与证据结构、领域扩展、兼容与阶段计划。
- `../plans/2026-09-05-finance-analysis-workbench-test-spec.md`：缺陷复现、财务纵向场景、开放能力、迁移和发布验收。
- README 增加上述入口，保留现有实现说明，明确新能力未实现。

新版方案独立复审 CLEAR；复审提出的“验证状态正交”与“首批资料格式明确”两项建议已纳入。下一实施优先级：精度/并发/路由缺陷 → 真实计算与分析版本闭环 → 隔离执行和完整 harness → 方法复用 → 新领域。不得仅将 period 替换成 standard 来完成本次方向调整。
