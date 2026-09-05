# 新版方案实施与验证记录

2026-09-06。用户已授权执行；代码基线 `efbbc1b`。本轮完成财务分析主线、任务内 harness 能力及方法复用，保留旧期间流程。未提交、推送或覆盖已安装应用。

## 修改前的执行计划

1. 先以回归测试锁定 JSON/XLSX 精度、引用并发、任务路由问题，再做局部修复。
2. 新增任务级分析服务：资料快照、分析定义/版本、执行记录、文稿与方法；复用 Decimal、DuckDB、openpyxl、现有 CLI/IPC。
3. 新分析入口与 legacy 入口共存；所有 session 先登记再显示，不将 global current 用作会话地址。
4. 给 harness 增加任务内分析工具和专用 preset，开放研究与可检查计算；脚本隔离通过真实测试后才开放。
5. 做预算/环比/假设/补资料/改稿/复用验收，再跑完整回归、构建与独立复审。

没有新增第三方依赖、空总账或银行写入模块；历史数据不批量重写。旧行为改变的测试依据新版合同调整，未通过删去失败断言规避问题。

## 已交付的用户流程

打开应用即可输入问题或添加资料，首次不需要写 skill、配置 CoA 或锁定期间。一个任务可加入多份表格及背景资料，继续提问、检查真实计算、调整假设、保存新版本，再编辑和归档文稿。用户自己决定是否认可结论。方法可在分析完成后显式保存，在其它任务重新绑定资料和参数。

工作台包含资料、分析结果、文稿、方法四个页签。原生助手工作区使用业务任务标题，保留用户自行改名；稳定任务目录不随显示名变化。SQL 收在高级选项；指标优先用业务名称与表达式显示。返回工作台自动读取助手新增内容，当前编辑版本和未保存文字保留。任务切换不会显示上个任务的助手；冷启动、同任务续聊和助手换端口重启均验证过会话及问题草稿恢复；验收直接读取原生窗口的可编辑输入框并截图，不仅检查持久化状态。

## 实施范围与主要文件

| 范围 | 改动与简化 | 文件 |
| --- | --- | --- |
| 正确性 P0 | Decimal 原始 token、XLSX 精确导出；引用追加完整事务锁；合同/引擎/方法执行证据分开 | `foundry/catalog.py`、`sheet.py`、`references.py`、`brief.py`、`probe.py`、`authoring/SKILL.md` |
| 上下文 P0/P2 | session 服务端绑定任务、工作区和快照；不再以全局 current 为会话后备地址 | `foundry/task.py`、`context.py`、`cli.py` |
| 分析 P1 | 不可变资料与定义版本、实际 Run、文稿及导出；单调版本序号、哈希验证 | `foundry/analysis.py`、`analysis_data.py`、`analysis_sql.py`、`analysis_cli.py` |
| 工作台 P1 | 新任务直接从问题/资料开始，参数/假设与文稿编辑，方法跨任务应用；旧入口收纳到单一选择框 | `app/src/views/Analysis.tsx`、`analysis.css`、`App.tsx`、`Workbench.tsx`、`Shell.tsx` |
| 桌面调用 | 原生文件选择、成果读取与导出统一经 CLI；session 登记完成才显示；等待启动完成再交接 | `app/electron/ipc/register.ts`、`preload.ts`、`main.ts`、`harness/host.ts`、`app/src/bridge.ts` |
| 隔离执行 P2 | macOS Seatbelt、只读输入、独立 scratch、代码和环境记录、输出哈希；source/frozen 均真实验证 | `foundry/runner.py`、`runner_entry.py`、`app/scripts/build-foundry.mjs` |
| 任务执行 P2 | 持久脚本 job、真实 spawn/fork、取消/重试、PID 与进程出生标识恢复；子任务固定原上下文 | `foundry/analysis_jobs.py`、`dsh-plugin/analysis-runtime.js` |
| Harness P2 | `analysis` preset、17 个分析工具、检索与计划；通用执行必须走相同 broker；所有镜像同步 | `dsh-plugin/analysis.js`、`index.js`、`presets/analysis/`、`foundry/resources/dsh-plugin/` |
| 方法 P3 | 从已保存 SQL 显式沉淀方法，移除注释并将字面值参数化；跨任务只暴露已保存方法，不暴露原资料 | `foundry/analysis.py`、`app/src/views/Analysis.tsx` |
| 文档 | README 改为当前使用流程；旧期间文档单独保留，原方案与当前证据分开 | `README.md`、`docs/legacy-period-workflow.md`、本记录 |

新服务统一使用现有 CLI/IPC，没有增加第二套数据库、计算引擎或通用事件总线。建账、资金管理未来通过独立写模型及 connector 引入；管理口径调整不会变成凭证，现金预测不会触发付款。

## 验证结果

| 验证 | 实际结果 |
| --- | --- |
| Python 全量，启用真实 staged dsh | **529 passed，2 skipped，68.90 秒** |
| 桌面测试 | **283 passed，19 个测试文件** |
| TypeScript / Vite | 两套 TypeScript 编译和生产构建通过 |
| 静态检查 | Python compileall、Node 语法、资源镜像、`git diff --check` 通过；新后端文件另经 Ruff 检查 |
| 真实 harness | 实际工具调用 CLI、SQL、隔离脚本及 MD/XLSX 产物；确定性模型适配器驱动真实 Agent loop、spawn/fork、取消、retry 与上下文继承通过 |
| 冻结 CLI | 引擎自检及 macOS 隔离实际执行通过；禁止宿主范围外读取、网络、fork；Decimal/openpyxl/图表生成通过 |
| 冻结后台任务 | 最小环境、无源码 cwd，后台完成→读成果→刷新后重试旧输入→取消并回收 PID→原 runtime 退出恢复均通过 |
| Formulator | 实际启动冻结服务，确认进程身份并从 connector API 读到 `locked_catalog` |
| macOS 打包 | `npm run package --prefix app` 通过；arm64 应用包含 Electron、harness、冻结 foundry 和 Formulator |
| 财务场景 | 打包应用自带 CLI 执行 14 项场景通过，详见下表及 JSON |
| 真实桌面 | 使用独立测试 profile/资料，原生 IPC 导入、计算、修订、文稿保存/归档、XLSX 导出；冷启动、A→B→A、返回刷新、未保存文稿、换端口重启恢复通过 |

最终窗口验收发现并修复两项交接缺陷：固定版本客户端要求 `dsh.sessions.current` 为 `{sessionId}` 对象；会话必须通过 `workspace.create` 与 `session.create({workspaceId})` 登记工作区，单传 `cwd` 会使输入框不可用。回归现执行已安装客户端的实际 store/构造器，并从最终 `.app` 验证首次问题、A→B→A 草稿隔离以及换端口后的真实可编辑输入框。

两项跳过是源码虚拟环境未安装 `pyarrow` 和 `data_formulator` 的可选直接导入测试。冻结 Formulator 的真实启动和 connector 验证已执行并通过；不把这些跳过项计为通过。

### 财务验收的具体值

| 场景 | 期望与实测 |
| --- | --- |
| 利润对预算 | 实际 30，预算 25，差异 5，差异率 20% |
| 差异桥接 | 收入 +20，成本 −10，费用 −5，总差异 +5 |
| 华东环比 | 上期 20，本期 30，增加 10 / 50%；西南数据未混入 |
| 缺预算 | 实际利润仍为 30，明确记录预算缺失 |
| 修改管理假设 | 单列费用 5 后利润 35，原计算保留 30 |
| 方法复用 | 同任务新参数结果 40；换任务、换资料后结果 100 |
| 应收账龄 | 合成甲客户逾期 35 天 |
| 回款延迟 | 基准期末现金 90，晚两周后为 −10 |
| 可复算/文稿版本 | 相同 SQL 重跑输出 hash 相同；改稿生成新版，已归档文件字节不变 |
| 资料/导出 | Markdown 背景段落可定位，XLSX 为真实工作簿；任务切换回原数据 |

后台额外验证：原预算快照 42；父会话补入 99 并刷新后，retry 仍计算 42，context hash 与 input hashes 完全一致，且新 job id 与原记录分离。

测试只用合成资料，不读取用户凭证、不调用付费模型。真实 Electron 文件选择器以固定 fixture 替代人工选择；导出使用真实 CLI 写盘并校验文件，OS 外部打开在测试中被捕获。不能据此声称已经验证 Excel 应用内编辑或真实 provider 的回答质量。

## 本地产物与证据

- 应用：`app/release/mac-arm64/FA Foundry.app`，本地未签名 arm64 测试包；已从该 `.app` 启动测试，无须开发服务器。
- 财务场景复跑入口：`tools/verify_analysis_workbench.py`。
- 完整测试日志、场景 JSON、桌面截图、视觉判断与二进制 hash：`build/verification/`。
- 后台完整冻包证据：`build/verification/frozen-jobs.json`。
- 原基线问题及方案：[审查报告](../reviews/2026-09-05-codex-review.md)、[方案](2026-09-05-finance-analysis-workbench-plan.md)、[验收设计](2026-09-05-finance-analysis-workbench-test-spec.md)。

`build/` 与应用产物由 gitignore 排除；源码、回归测试和文档保留为可审查 diff。

## 明确限制与后续扩展

- P2 交付的是经过验证的任务内执行能力。脚本隔离仅支持 macOS；Bash 不支持任意子进程/网络。文件总量是周期检查，单文件和执行时间有强制上限；这不是磁盘配额系统。
- Office 通过隔离 Python/openpyxl 生成和修改新工作簿；没有新增完整嵌入式表格编辑器或 Excel 公式重算。缺少公式缓存的源表会报错，不能当零读入。
- SQL 关联两侧须为明确快照；需要关联派生 CTE 时先物化。浮点结果明确提示，脚本即使可重跑也暂不自动标记“可复算”。
- 方法目前保存 SQL，脚本方法、通用 connector 市场、PDF/图片解析尚未增加。跨任务方法仍需财务经理核对新的口径与参数。
- 未运行真实付费 provider 的自然语言解释质量评测，未在其它 macOS 版本/Intel Mac 测试，未做签名、公证或公开分发，也未覆盖 `/Applications` 中已有安装。
- P4 建账、过账、银行支付及其幂等/回执属于后续独立业务实现，本轮没有把预测或草稿状态当作这些能力已完成。
