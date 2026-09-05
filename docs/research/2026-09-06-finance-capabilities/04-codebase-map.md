# Foundry 当前能力与扩展落点

核查日期：2026-09-06。修订：r2。主体依据当前工作树读取；本次追加读取已安装 FA Foundry 0.1.1 的技能资源与提供方代码，详见 [接入证据](07-bundled-skills-integration.md)。未启动应用、安装依赖或运行测试。下述测试引用表示已有覆盖位置，不代表本次重跑结果。文件锚点均相对仓库根目录。

**结论：Foundry 已具备“有来源的资料快照 → 显式计算 → 版本化成果”的通用底座，尚未形成持续连接企业账套、理解统一财务模型、自动解释差异的产品闭环。** 产品已明确面向财务经理，统一对话与资料/结果/文稿工作区，并将正式入账、支付执行留给独立领域能力（`PRODUCT.md:19`、`PRODUCT.md:31`、`PRODUCT.md:39`）。

## 已实现、局部能力与缺口

| 能力 | 当前事实与边界 | 状态 |
|---|---|---|
| 文件与快照 | CSV、XLSX、表格 JSON、MD/TXT；单文件 32 MiB、最多十万行/256列。原件、解析数据、schema、来源哈希、转换记录落盘，读取再验哈希（`foundry/analysis_data.py:18`、`foundry/analysis_data.py:125`；`foundry/analysis.py:262`、`foundry/analysis.py:287`）。PDF、图片、OCR未进入此解析入口。 | 已实现文件导入；缺持续数据连接 |
| Excel 读取 | 默认第一张表，可用 `metadata.sheet` 指定；首行表头。读取公式缓存，无缓存即拒绝；数值从原始 XML 以 Decimal 解析，记录工作表与物理行号（`foundry/analysis_data.py:48`、`foundry/analysis_data.py:81`、`foundry/analysis_data.py:114`）。有缓存不代表缓存新鲜，未见公式依赖重算/新鲜度检查。 | 局部；非完整工作簿模型 |
| Excel 导出/预览 | 分析导出新建 Report、Result、Evidence 工作表；金额与所有字符串按字面文本保存，避免精度丢失和公式注入（`foundry/analysis.py:677`、`foundry/analysis.py:729`）。Univer 经只读导入生成临时容器，URL 使用 `editable=false`；IPC入口按归档摘要取文件（`app/electron/univer.ts:212`、`app/electron/univer.ts:408`、`app/electron/univer.ts:500`；`app/electron/ipc/register.ts:391`）。没有原 Excel 单元格绑定、公式/样式保真双向刷新、编辑回写及冲突合并。 | 局部；非“Excel 不搬家” |
| 金额与口径 | 数值推断为 `DECIMAL(38,scale)`，拒绝精度收窄；SQL 结果将金额序列化字符串（`foundry/analysis_data.py:194`；`foundry/analysis_sql.py:385`）。跨表校验实际 JOIN 键、基数、重复/未匹配行；混币种/单位需声明 conversion_rules（`foundry/analysis_sql.py:266`、`foundry/analysis_sql.py:368`）。但 conversion_rules/metrics 主要是声明字段，尚非可执行的统一口径/汇兑/存量流量模型；DuckDB 除法可能返回浮点并提示（`foundry/analysis_sql.py:465`）。 | 已有精度与关系检查；财务语义局部 |
| 差异、账龄、情景 | 预算差异由测试显式 SQL 实现（`tests/test_analysis_workbench.py:37`）；账龄和延期现金预测使用两名客户、一条收支计划及硬编码 SQL（`tools/verify_analysis_workbench.py:76`）。这些是通用SQL底座的场景验证，不是通用账龄/滚动预测引擎。差异说明的 Driver/Outlook/Action 存在于方法提示文档（`foundry/resources/method/variance-analysis/SKILL.md:142`），未见产品级自动归因对象。 | 可计算；缺领域模型与端到端说明链 |
| 账套与连接器 | 新分析存储的对象是 datasets/revisions/runs/drafts/methods（`foundry/analysis.py:217`），没有账套/组织/会计期间/凭证行的专用模型。旧月结路径已有 coa/aux/map/units、科目映射冲突与未映射金额检查（`foundry/caliber.py:13`、`foundry/caliber.py:45`、`foundry/caliber.py:267`），应复用规则而非宣称毫无映射能力。CONNECTORS 中 ERP/BI 仍标未支持 MCP（`foundry/resources/method/CONNECTORS.md:19`）。 | 旧规则可借用；未见生产ERP适配器 |
| 刷新 | `analysis-refresh` 读取本任务已有 datasets，生成新会话上下文版本；不会请求ERP、轮询文件、做增量同步或处理删除记录（`foundry/analysis_cli.py:150`）。不存在连接游标、批次水位、源记录主键/删除事件的统一契约。 | 已有上下文刷新；缺源刷新 |
| Harness/会话 | 分析工具覆盖数据、SQL、隔离脚本、后台任务、委派、文稿与方法；另开放 web_search 等能力，原始 Office 工具不可用（`dsh-plugin/package.json:76`）。所有工具要求 session；服务按会话归属解析，不能回退到全局 current；子会话继承冻结快照上限（`dsh-plugin/analysis.js:165`；`foundry/task.py:306`、`foundry/task.py:596`）。macOS runner 无网络、无子进程，仅向自身输出目录写入；其他平台不可用时拒绝执行（`foundry/runner.py:39`、`foundry/runner.py:80`、`foundry/runner.py:259`）。 | 已实现受控开放；不是任意宿主工具总线 |
| 方法、版本与运行 | analysis 保存 SQL/参数/关系/假设与 parent_id；记录不可变，run 保存输入、代码、环境、输出哈希，重跑一致后才标可复算（`foundry/analysis.py:152`、`foundry/analysis.py:323`、`foundry/analysis.py:422`）。参数元数据绑定实际 SQL 参数，支持业务名称/类型/单位/约束（`foundry/analysis_parameters.py:138`）。方法复用目前仅SQL，去除原问题、业务参数值并重绑 schema/grain（`foundry/analysis.py:768`）。尚无版本化指标图、驱动模型、情景树或跨模型依赖重算。 | 底座已实现；计划系统局部 |
| 说明与证据 | Claim 可区分计算/假设/判断；计算引用要求成功run、行列位置和值一致，并继承快照和假设依赖（`foundry/analysis.py:499`）。文稿独立保存 review/publication 状态。正文仍是自由Markdown，UI将 claims 展示为附属依据（`app/src/views/Analysis.tsx:508`、`app/src/views/Analysis.tsx:526`）；未见“每段说明→差异贡献→明细”结构化连接，不能自动保证正文每个数字/因果句都被证据覆盖。 | 已有记录级证据；缺解释级可追溯 |

## 现有方法应如何复用

- `method/` 与 `foundry/resources/method/` 当前逐文件相同，只有 financial-statements、reconciliation、variance-analysis、journal-entry 四项；运行侧清单和文件解析见 `foundry/method_skills.py:7`、`foundry/method_skills.py:24`。
- 差异方法已有量价拆分、重要性和说明结构（`method/variance-analysis/SKILL.md:30`、`method/variance-analysis/SKILL.md:142`）；三表方法含历史现金流参考，核对方法含未达项账龄，凭证方法仅草稿工作流（`method/financial-statements/SKILL.md:17`、`method/reconciliation/SKILL.md:144`、`method/journal-entry/SKILL.md:17`）。这些内容不等同独立的 13 周现金预测或完整应收账龄执行引擎，但可以指导通用分析。
- 四项均为 Markdown 方法指导，目录内无执行代码；analysis preset 注册了技能提供方与 loader，却未配置随包方法目录（`dsh-plugin/presets/analysis/agent.cordis.yml:10`）。`methodSkills` 声明与 preset 安装不能代替目录接线（`dsh-plugin/package.json:139`；`foundry/harness.py:72`）。当前缺少真实会话发现/加载证据，不能由“有加载器”推断“四项已加载”。接通后助手可将方法实例化为显式 SQL/脚本（`dsh-plugin/analysis.js:38`）；成功分析保存的 SQL method 另可跨资料重绑（`foundry/analysis.py:768`、`foundry/analysis.py:810`）。
- 阶段 0 先接通随包目录并适配旧 FOUNDRY 指引；当前 locked-window/单表要求与新分析多表流程冲突，需按可信 preset/session 区分（`method/FOUNDRY.md:5`、`method/FOUNDRY.md:12`）。已有测试只核文件/引用/声明（`tests/test_method_skills.py:21`、`:49`），须增加真实提供方、正文与引用加载、模型计算及新包会话验证。
- 阶段 2 在技能知识和 SQL/Python 能力上补高频算子、语义合同和说明证据，保留来源归属并同步打包镜像，不重写同名提示词。重要性阈值、币种与企业口径由经理调整；没有专用算子时仍能开展通用分析。

## 建议扩展点与验收落点

以下是代码落点分组，实施先后以主计划阶段 0–7 为准。

0. **先证明随包技能实际可用。** 将已解析的方法根传入现有 skill-filesystem bundled 根机制；迁移 analysis 与旧 period/f3 的方法指引，保留用户同名技能来源解析。干净测试配置验证四项发现/加载，真实模型以现有 SQL/Python 得到 G1/G2 真值并保存 run/草稿，新包及安装版重启后复验。对应 A27–A34；不依赖未来财务领域工具。
1. **先统一企业分析语义。** 新增独立的账套来源、科目/辅助维度映射、期间/币种/金额方向契约；快照保留源版本与映射版本。借用 `foundry/caliber.py` 的未映射和总额守恒检查，经 `foundry/analysis.py:236` 接入，勿将新分析重新绑回旧 Window。验收：未映射科目可见、借贷/余额口径明确、同一数据换映射产生新版；扩展 `tests/test_analysis_workbench.py:360`、`tests/test_analysis_workbench.py:556`。
2. **把文件导入升级为可刷新来源。** 在现有 `add_dataset` 前增加 connector 的 discover/read/checkpoint，固化批次再给会话选择；`analysis-refresh` 保持上下文语义。验收：重复拉取幂等、增量删除/更正可追踪、失败不产生半批数据、旧run仍读旧快照；扩展 `tests/test_analysis_cli.py:32`，新增连接器契约测试。
3. **以可组合财务算子补强方法。** 先做差异桥、到期/账龄、现金时间轴，明确基准、粒度、零分母、舍入与重分类；情景修改绑定参数而非仅改 assumptions 文本（`dsh-plugin/analysis.js:39`）。验收从固定样例拓展到多期间、多币种、贷项/预收、空预算、延期跨月及守恒性质；落在 `tests/test_analysis_parameters.py:50`、`tests/test_analysis_parameters.py:159` 与新领域测试。
4. **先补证据说明和 Excel 交换契约。** 说明对象连接贡献明细、计算位置和经理判断；原表兼容另定义工作表/区域标识、缓存新鲜度、公式保真与回写冲突策略，不把 Univer 预览称作完成。验收：刷新后说明失效可见、经理修改不继承旧验证、长数字不失真；复用 `tests/test_analysis_workbench.py:243`、`tests/test_analysis_workbench.py:329`、`tests/test_analysis_workbench.py:350`，补工作簿往返和 `app/tests/analysis-ipc.test.ts:121`。

代码落点核查覆盖后端、DSH、Electron与前端；上文“缺口”仅指当前一方源码未提供实现，不推断第三方包、厂商产品或未配置服务的能力。
