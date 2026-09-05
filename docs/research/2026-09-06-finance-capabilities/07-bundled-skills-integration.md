# 随包财务技能：接入发现、复用边界与计划修订

核查日期：2026-09-06。对应实施计划 r2。本次读取当前工作树与已安装的 FA Foundry 0.1.1 资源；未启动应用或模型会话，未修改产品代码。下面明确区分已观察事实、设计决定与待执行验收。

## 结论

已有四项 Anthropic finance 技能应作为 Foundry 的财务方法基础。它们提供报表、差异、对账及分录草拟的工作方法，助手可结合现有 SQL/Python 将其用于具体资料。新计划先补齐这些技能进入分析会话的链路，再建设企业账套口径、稳定计算、Excel 绑定与来源刷新。

当前已核实文件随包存在；尚未取得实际会话发现、正文加载和使用技能完成分析的证据。宿主未显式接入方法目录，旧方法指引还包含与 analysis 模式冲突的限制，因此不能仅凭安装清单宣称“财务技能已经可用”，也不能反过来断言所有历史会话从未使用过它们。

## 本次观察到的证据

| 观察 | 代码或本地资源依据 | 可得结论 |
|---|---|---|
| canonical 只列四项技能 | `foundry/method_skills.py:7`、`:15`、`:24`；`method/README.md:3` | financial-statements、variance-analysis、reconciliation、journal-entry 是随包方法范围；它们不是完整厂商服务或 ERP 连接 |
| 已安装应用版本为 0.1.1，四项 SKILL.md 与 canonical 字节一致 | `/Applications/FA Foundry.app/Contents/Info.plist`；应用的 `Contents/Resources/foundry/_internal/foundry/resources/method/` | 证明这四项正文随安装包存在，不证明会话可见或已调用 |
| methodSkills 只是插件内声明 | `dsh-plugin/package.json:139`；已安装 skill-filesystem 的文档明确忽略包 manifest | 此声明不能代替技能目录接线 |
| preset 安装只复制 preset 目录；analysis 注册技能提供方与 loader，但没有配置方法根 | `foundry/harness.py:72`；`dsh-plugin/presets/analysis/agent.cordis.yml:10` | 注册提供方、安装 preset 和加入方法搜索目录是不同步骤 |
| 宿主为 harness 设置独立 DSH_HOME；未找到传入随包方法根的配置 | `app/electron/harness/boot.ts:110`；`app/electron/main.ts:255`；检索 app/electron、dsh-plugin 和 foundry 中的 bundledSkillDir、customSkillDirs、DSH_BUNDLED_SKILL_DIR、DSH_AGENTS_HOME | 当前源码缺少明确接线；实际会话目录仍需运行验证 |
| 已安装提供方支持默认项目/用户目录及 bundled 根 | skill-filesystem 的 README.zh.md 与下方所链接的应用内根目录解析代码 | 可以复用已有运行时能力；无需另建技能加载器或把副本装进全局目录 |
| 现有方法测试核对文件、引用和 manifest 声明 | `tests/test_method_skills.py:21`、`:49` | 这些测试不覆盖真实提供方、loader、模型选择技能或安装版会话 |
| 旧规则要求 locked window、单个 named table | `method/FOUNDRY.md:5`、`:12`；四项 SKILL.md 引用该文件；analysis persona 支持无 Window 的多表分析 | 应先按可信运行模式适配规则，再将方法接入 analysis |

已安装提供方的本地依据：[配置与发现说明](</Applications/FA Foundry.app/Contents/Resources/dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/README.zh.md>)、[根目录解析](</Applications/FA Foundry.app/Contents/Resources/dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/lib/index.js:151>)。这些依据描述本机所装版本，不作为未来所有 DSH 版本的固定合同。

## 四种状态分别证明

| 状态 | 合格证据 | 本次状态 |
|---|---|---|
| 已随包携带 | canonical、packaged、安装版的文件及内容核对 | 已只读核到当前安装版的四项正文；新包及全部配套资源仍按 A27 复验 |
| 可被会话发现 | 干净测试配置下，真实提供方返回技能目录及实际来源 | 未运行验证 |
| 正文与引用可加载 | 实际 loader 返回所选技能正文，配套引用可读取，记录版本/哈希 | 未运行验证 |
| 实际用于分析 | 模型收到自然语言任务，加载相应技能，调用现有计算工具并保存真实 run/草稿 | 未运行验证 |

技能目录摘要与正文有不同生命周期。提供方会解析 frontmatter 形成目录，loader 在调用时读取正文；正文留在既有会话历史中，后续编辑不会自动重写旧历史。因此必须覆盖新会话、模式变化、应用升级和重启；旧会话保留原使用记录，新调用记录当前实际来源。不要仅凭文件更新时间或目录摘要认定旧会话已使用新版规则。

## 复用与新增各负责什么

| 已有资产 | 保留和复用 | 需要补的能力 |
|---|---|---|
| financial-statements | 三表结构、期间比较、报表组织及现金流分析参考 | 企业内部管理损益映射、数据口径和下钻；历史现金流说明不能替代 13 周预测模型 |
| variance-analysis | 量价分解、重要性、差异桥、说明结构 | 对既定分解法进行确定性验证，连接贡献、来源与经理判断 |
| reconciliation | 总账/明细/银行/往来核对，未达项及其账龄处理 | 可复用控制总额核对，后续多表匹配；未达项账龄不直接等同完整应收应付账龄引擎 |
| journal-entry | 分录草稿与检查方法 | 保留未来建账接口；真实过账需独立领域命令、权限和业务回执 |
| 已保存的 SQL method | 成功分析经 save_method/apply_method 重绑资料复用（`foundry/analysis.py:768`、`:810`） | 与 Markdown 方法知识分别标识；不要求每个临时问题都先创建专用算子 |

计算合同服务于稳定性与复算，技能继续指导问题拆解和方法选择。新增高频算子前先检查已有方法及成功分析；不新增一套同名提示词，不把经理的专业判断变成固定审批流程。技能中的示例币种、重要性阈值和报表口径都允许经理按企业场景明确修改。

## 对实施计划的具体调整

1. **阶段 0a：接通目录。** 使用当前运行时的 bundled 根机制，从实际应用资源位置解析 `method/`，同步 canonical 与打包镜像并保留来源/许可。干净配置与同名技能覆盖分别验证；保留用户已有技能，记录所选来源。对应 A27–A29。
2. **阶段 0b：迁移旧规则。** analysis 使用任务资料与多表 SQL/Python；旧 period/f3 维持各自边界。由可信 preset/session 提供模式，配套引用一起适配。`~~erp` 等继续作为类别占位，不能被解释为已有授权连接。对应 A30、A32–A33。
3. **阶段 0c：真实调用基线。** 四项显式加载均验证；自然语言损益和量价问题分别走现有计算路径，得到 G1=+5、G2=+32 并保存引用真实 run 的草稿。该基线不依赖后续业务工具，也不等于完整 30 题评测。对应 A31。
4. **阶段 0 出口包含新包证据。** 开发态通过后重新打包，在隔离测试配置下复验发现、加载、计算、升级和重启，记录包/技能哈希、模型配置与会话 ID。四种失败层级分别报告。对应 A34。
5. **阶段 2 继续补高频工具。** 以已接通的技能和通用分析为基础，提供指标、差异、下钻与解释服务；持续回归 A27–A34。原阶段 1–7 的企业账套、Excel、ERP、现金情景和对外 MCP 目标保留。

本次修订只落实到文档。A27–A34 均为未来实施验收条件，没有在本轮被标为通过。详见 [实施计划 r2](../../../.omx/plans/2026-09-06-finance-capability-plan.md) 与 [34 条验收合同](../../../.omx/plans/2026-09-06-finance-capability-test-spec.md)。
