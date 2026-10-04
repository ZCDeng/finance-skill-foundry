# Finance Skill Foundry

面向财务经理的分析工作台。从问题与资料开始，检查计算、调整假设、修改文稿，再把有用的分析保存为可复用方法。建账和银行资金操作保留独立扩展边界。

[代码审查](docs/reviews/2026-09-05-codex-review.md) · [产品与架构方案](docs/plans/2026-09-05-finance-analysis-workbench-plan.md) · [验收设计](docs/plans/2026-09-05-finance-analysis-workbench-test-spec.md) · [实施与验证记录](docs/plans/2026-09-05-execution-log.md)

## 使用流程

1. 输入“华东利润为什么低于预算”等问题，或直接添加资料。首次使用无需先写 skill、配置科目表或锁定期间。
2. 添加 CSV、JSON、XLSX 表格，或 Markdown、TXT 背景资料。原文件复制为带哈希的资料快照；补资料增加快照，不覆盖旧数据。
3. 与助手研究问题。可以检索、检查资料、执行 SQL、运行隔离的 Python/Bash 脚本，也可以委派有明确范围的子任务。
4. 在“分析结果”检查来源、计算与执行状态，修改参数和假设后保存新版并重跑。高级 SQL 默认折叠。
5. 在“文稿”查看事实引用和质量提示，编辑后重检当前正文；有提示仍可保存草稿。确认专业判断后归档，导出 Markdown 或 XLSX。经理判断可按账套、组织和有效期保存，回到助手继续分析；旧稿和旧计算保留。
6. 有复用价值时再“保存方法”。下个任务提供新的资料绑定和参数后运行，不继承原任务的数据与结论。

财务经理决定口径、假设及文稿是否采用。系统分别记录执行、可复现性、用户判断和发布状态，不把程序运行成功当作业务结论正确。首次执行不会自动显示“可复现”；相同定义和输入的实际重跑一致后，才标记 SQL 结果可复现。

## 当前能力与边界

| 能力 | 当前行为 |
|---|---|
| 解释质量 | 事实占位符自动绑定精确引用；数字、单位、方向及当前稿引用检查；背景按当前任务授权与期间复用。检查未发现问题不等于经理认可或业务原因已证实 |
| 财务分析 | 真实条件筛选、分组、预算差异、账龄与现金情景计算；示例验收使用合成资料 |
| 关联计算 | 声明快照、关联键和基数，检查重复计数；派生 CTE 的 JOIN 需先物化成快照 |
| 金额 | 导入和常规运算保留 Decimal；DuckDB 除法产生的浮点结果明确提示；XLSX 无法精确保留的长数以文本输出 |
| 脚本 | macOS 系统隔离、冻结输入、独立工作目录、资源上限、代码/环境/产物哈希；归档输出可打开 |
| 后台任务 | 查看、取消、重试；重试创建新记录并沿用原输入；取消回收脚本进程 |
| 子任务 | 真实 spawn/fork，冻结父任务上下文，有深度与工具范围限制；记录结束状态 |
| Office | 隔离 Python/openpyxl 生成或修改工作簿成果，原始快照保持不变；可导出、打开后重新导入 |
| 方法 | SQL 方法显式保存，移除注释与具体字面值，跨任务重新绑定；脚本暂不保存为方法 |
| 财务方法技能 | 随包提供 financial-statements、variance-analysis、reconciliation、journal-entry 四项方法，以及 setup、close、bva、cash 四个路由包；分析会话可发现并加载正文与配套说明。连接器占位不代表已连接 ERP，分录技能用于草拟。随包技能的措辞由契约测试把关：不声称已接通 ERP、能过账或付款，斜杠命令和正文里反引号标出的工具名必须真实存在；这只检查文字，助手的回答仍需经理核对 |
| 后续领域 | 总账、凭证过账、银行支付尚未实现；现金预测属于分析，不执行资金划拨 |

脚本隔离目前只支持 macOS；其它系统拒绝执行，没有静默降级。Bash 支持受限命令，不提供任意子进程或网络。工作簿生成不包含 Excel 公式重算引擎；带公式但缺少缓存值的输入会明确报错。日常回归使用确定性适配器；真实模型验收另用显式 `--live` 入口，在临时配置中使用已有 provider 和合成资料。每次实测分别记录模型、技能来源、计算和草稿。新版解释质量的功能验收、首轮模型成绩和边界见 [解释质量交付记录](docs/finance/explanation-quality-delivery.md)；历史基线见 [r2 实施记录](docs/plans/2026-09-06-finance-r2-execution-log.md)。

## 数据与调用边界

```text
var/tasks/<task_id>/
  task.json, windows.jsonl, sessions.jsonl, deliverables.jsonl
  analysis/
    datasets/           # 原始资料与元信息、哈希
    revisions/          # 不可变计算定义与版本
    runs/               # 实际输入、执行结果与状态
    drafts/             # 文稿版本、来源与用户判断
    methods/            # 显式保存的复用方法
    jobs/               # 后台/子任务运行记录
```

`foundry/` 统一负责数据读写；Electron 与插件调用 CLI，不另建数据库入口。每次助手调用以服务端登记的 session 解析 task、workspace 与资料范围；未知 session 拒绝执行。A→B→A 切换不会让 A 的会话落到全局 current 指向的 B。父任务补资料后可以显式刷新上下文，已派出的子任务保持原资料范围。

新任务默认使用 `analysis` preset，工具通过相同的数据与执行边界开放。旧 `period` / `f3` 和技能创作保留在“旧版期间流程”中，便于处理已有窗口。旧命令详见[期间流程参考](docs/legacy-period-workflow.md)。`mark-done` 的合同校验、引擎样例通过与方法实际执行分别报告，不能互相替代。

## CLI 示例

```bash
foundry --var VAR task-new --title "华东利润与预算分析"
foundry --var VAR --task TASK dataset-add --path actual.csv --name "本月实际"
foundry --var VAR --task TASK analysis-state
foundry --var VAR --task TASK analysis-save --spec '{"question":"经营利润","bindings":{"actual":"SNAPSHOT_ID"},"sql":"SELECT revenue-cost-expense AS profit FROM actual"}'
foundry --var VAR --task TASK analysis-run --analysis ANALYSIS_ID
foundry --var VAR --task TASK analysis-draft --spec '{"title":"经营简报","body":"可编辑的管理层判断","run_ids":["RUN_ID"]}'
foundry --var VAR --task TASK analysis-export --draft DRAFT_ID --format xlsx
```

`--var`、`--task`、`--session` 是全局参数，放在子命令前。应用原生选文件是受信任的用户操作；助手只能导入已登记工作目录内的资料。

## 开发与打包

依赖以 `pyproject.toml`、`uv.lock`、`app/package-lock.json` 为准。当前固定 harness 为 `@deepseek-ai/dsh@0.1.1-rc.2`。没有为本轮新增第三方依赖。

```bash
uv sync --extra dev
cd app
npm ci
npm run harness
npm run foundry
npm run formulator
npm run package
```

`npm run package` 检查 runtime/冻包版本，实际启动冻结的 Data Formulator 校验 connector，再构建 macOS 应用。`npm run foundry` 使用 PyInstaller one-dir，校验冻结引擎及真实脚本隔离。产物在 `app/release/`，构建脚本不会安装或覆盖 `/Applications`。

开发时 `FOUNDRY_BIN` 可以指向本仓库虚拟环境的 `foundry`，`FOUNDRY_VAR` 指向独立测试目录；`npm run dev --prefix app` 启动桌面窗口。不要让测试使用真实财务资料或用户已有任务目录。

## 验证

```bash
.venv/bin/python -m pytest -q
npm test --prefix app
npm run build --prefix app
FOUNDRY_DSH_BIN="$PWD/app/extra/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js" .venv/bin/python -m pytest -q tests/test_real_load.py tests/test_analysis_runtime.py
.venv/bin/python tools/verify_analysis_workbench.py --foundry .venv/bin/foundry
.venv/bin/python tools/verify_analysis_workbench.py --foundry app/extra/foundry/foundry
```

桌面真实交互脚本为 `tools/verify_desktop_workbench.cjs` 和 `tools/verify_desktop_sessions.cjs`，使用已有 Playwright（`PLAYWRIGHT_MODULE` 指定其模块路径），无需添加项目依赖。会话脚本测试打包应用时另设 `QA_APP` 为应用可执行路径，`QA_FOUNDRY` 为包内 CLI；默认使用开发应用，此时先在 `app/` 下 `npm run build`，再运行 `npx vite --port 5273 --strictPort`。

最后一条请使用实际冻包中的可执行路径。详细结果、桌面交互证据及尚未验证的边界见[实施记录](docs/plans/2026-09-05-execution-log.md)。
