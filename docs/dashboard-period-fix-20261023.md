# 看板跨月期间修复与验收

任务：先补回归，再修复 8 月看板带入 9 月时整组阻塞及缺 scope 漏拦；保留历史和经理重新认可，所有运行验收使用临时合成任务。

## 实施范围

1. 新增显式 `period_binding`。SQL 声明本期参数键或从 1 开始的位置；结构化聚合声明现有 eq 筛选字段；脚本从只读 `FOUNDRY_CONTEXT` 读取期间。只更新声明的输入，固定比较基期不变。
2. 服务端按已确认分析范围、任务、scope、资料解析期间，拒绝未知、冲突和混月；将实际期间及执行输入哈希归档。异步脚本在派发时冻结期间，重试沿用。
3. 看板预检和执行复用期间检查。缺 scope 回查原运行冻结期间、原资料；不能用缺失元数据绕过字面量防错。
4. 失败带入记录独立持久保存。文件齐备与算法可重算分别显示；9 卡同一 run 只修复一次。恢复只处理失败卡，保留已成功卡的认可状态。
5. 已有写死月份的算法使用新修复提案：在原任务临时副本回放原月，严格比较完整列和行；一致后生成目标月新运行。原任务、旧运行和旧卡不修改，提案不直接修改看板。经理继续带入后逐卡重新认可。目标期间、资料或来源看板变化会使旧提案失效。
6. 助手工具 schema、提示词、打包资源与桌面恢复入口同步接入。

## 修改文件

- `foundry/analysis_period.py`：期间声明、解析和绑定；复用现有离线 DuckDB 连接入口。
- `foundry/analysis.py`、`foundry/analysis_jobs.py`、`foundry/runner.py`：同步/异步运行、冻结证据和脚本只读上下文。
- `foundry/dashboard_recompute.py`、`foundry/finance_service.py`、`foundry/dashboard_repair.py`、`foundry/finance_cli.py`：共用预检、失败持久化、限定授权修复和经理恢复。
- `dsh-plugin/` 中的 `analysis.js`、`finance-tools.js`、`client.js`、`package.json`、`presets/analysis/agent.cordis.yml`，以及 `foundry/resources/dsh-plugin/` 对应副本：助手工具与打包合同。
- `app/src/views/analysis/Dashboard.tsx`、`dashboardModel.ts`、`Dashboard.css`：准确的可带入数、失败恢复和修复入口。
- `tests/test_analysis_period.py`、`test_dashboards.py`、`test_dashboard_carry_repair.py`、`test_dashboard_repair.py`、`test_dashboard_period_plugin.py`、`test_analysis_plugin.py`、`test_runner.py`，以及 `app/tests/dashboard.test.tsx`：回归覆盖。
- `tools/verify_dashboard_period.cjs`：真实候选 Electron 包的可重复隔离验收。

预检和执行共用同一期间检查；同一原 run 的多张卡共用一次重算/修复，恢复沿用原带入操作并只处理剩余卡。未新增依赖。

## 回归过程

- 实现前，9 卡参数绑定与缺 scope 用例均失败；预检误报 ready=9、失败记录丢失、部分恢复用例也先失败。
- 前端先覆盖全失败刷新恢复、9 卡待认可、按 run 预填、先保存授权再预填、缺资料分流和预检错误重试，再实现。
- 后端覆盖命名/位置参数、跨年、固定同比基期、真实聚合筛选、脚本只读上下文、异步冻结、期间/资料冲突、残留字面量、源任务后来改期，以及 SQL/聚合/脚本旧算法升级。
- 恢复集成覆盖全部 9 卡、部分成功后已认可卡保持、重复恢复不重复卡、历史全文件哈希不变和授权边界。

## 验证结果

- 前端完整 Vitest：107 个测试文件、1544 项测试通过；TypeScript 两个项目检查和 Vite 构建通过。
- `npm run package` 通过：foundry/Formulator 源码指纹、冻结 Formulator 实连 gate、打包字体与资源检查通过。
- 最终候选应用：`app/release/mac-arm64/FA Foundry.app`。真实 Electron 的 `app.isPackaged=true`，55 个主进程/渲染构建文件与候选包逐字节一致；两份内嵌 foundry 的源码指纹对应本次最终源码。
- 桌面隔离验收：30 项检查通过。参数绑定直接带入 9 卡，以及缺 scope 旧算法被拦、修复提议、经理继续带入 9 卡，两条路径均得到 9 月数据（合成金额 901–909），均先待认可，再逐卡署名认可。
- 原八月两个合成任务各 10 个文件的 SHA-256 前后一致，原看板、运行和认可记录均未变。修复提议阶段没有直接生成经理卡；恢复后失败状态清空。外部请求与模型 prompt 请求均为 0。
- Python 全量回归：3519 项通过、17 项跳过，耗时 432.04 秒；包含前端全量测试和两个 TypeScript 项目检查。首次全量发现的离线连接入口守卫问题已修正，本次重跑无失败。
- `git diff --check` 与验收脚本 `node --check` 通过；未新增依赖。

桌面回执、10 张截图和构建/测试日志保存在 `build/verification/dashboard-period-20261023/`；主要回执为 `dashboard-period-receipt.json`。截图包括缺 scope 的 9 卡拦截原因、经理继续带入入口、9 张卡的上下视图及认可后的署名。

## 证据边界

本节记录提交前的修复阶段验收：使用本次源码构建的候选 `.app`，独立 HOME、用户目录、harness 和 FOUNDRY_VAR。助手修复工具由确定性 CLI 调用模拟，未发送模型请求。该阶段未安装或替换 `/Applications` 中的应用，未修改真实任务数据；未提交、推送或发布，候选包未签名、公证。后续 0.14.3 发布的签名、公证和安装验收另行记录在发布回执中。未验证真实模型服务响应；本次合成场景验证了故障机制及修复闭环，不能据此声称已回放原始历史事故。
