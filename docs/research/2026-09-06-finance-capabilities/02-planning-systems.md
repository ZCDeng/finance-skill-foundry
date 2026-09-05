# Planning Systems 调研：Pigment / Drivetrain / Planful / Anaplan

访问日期：2026-09-06

本文只使用官方产品页、官方帮助中心、官方 API/集成文档和官方发布说明。凡是页面明确写了 roadmap、coming soon、on the way 的内容，我都按“未验证”处理，不把它当成当前已可用能力。

## 结论先行

如果 Foundry 的目标是“财务经理主导的持续对话 + 结果桌面工作台”，四个产品更值得借鉴的是各自稳定、可复核的内核：Pigment 的维度/度量/版本/场景骨架，Drivetrain 的驱动因子与滚动预测节奏，Planful 的 Office 回路与解释型 AI，Anaplan 的确定性规划模型与开放集成体系（见各节官方链接）。

对 Foundry 来说，建议先做的是可执行的财务指标和计算服务，再加一层解释与协作界面，而不是先拼一整套 EPM 套件。更具体地说：允许财务经理通过受控工具改假设、切场景、存草稿、重算结果；LLM 负责提问、摘要和 commentary，最终数字由确定性引擎产出，不能伪造结果。审批流可以保留为后续可插拔治理能力，不必作为第一阶段的硬依赖。

## Pigment：建模骨架 + AI 叠层

【文档确认】Pigment 把 Dimension Lists 定义为分析轴，Metrics 由这些维度定义结构，Tables 可把多个不同维度的 Metric 放在一起做 P&L、项目成本等分析，Versions 用于完整模型比较，Scenarios 更适合快速的假设对比（[Model with Metrics](https://kb.pigment.com/docs/model-metrics), [Understand Dimension and Transaction Lists](https://kb.pigment.com/docs/understand-dimension-transaction-lists), [Work with Tables to Summarize Information](https://kb.pigment.com/docs/tables-summarize-information), [Versions and Scenarios](https://kb.pigment.com/docs/versions-scenarios)）。

【文档确认】Pigment 还公开了围绕模型归因与下钻的功能：`BY`、`REMOVE`、`Show Values As`、`Break down by`、`Drill to data source`（[BY modifier](https://kb.pigment.com/docs/by-modifier), [REMOVE modifier](https://kb.pigment.com/docs/remove-modifier), [Show values as](https://kb.pigment.com/docs/show-values-as), [Break down by](https://kb.pigment.com/docs/break-down-metrics-grid), [Drill to data source](https://kb.pigment.com/docs/drill-data-source)）。这说明它的产品语义不是只展示数字，而是支持围绕驱动因子做聚合、分摊、下钻和归因。

【官方宣称】Pigment AI 由 Modeler、Analyst、Documentation、Custom Agent 和预测能力组成（[Pigment AI](https://kb.pigment.com/docs/pigment-ai), [Frequently Asked Questions](https://kb.pigment.com/docs/ai-faq), [Run the Analyst Agent](https://kb.pigment.com/docs/configure-and-run-the-conversational-analyst-agent)）。更细的控制点在 MCP 页面和 Supported tools 页面：MCP Server 需要 Pigment AI，访问仍受权限和 AI data access 控制；advanced mode 会开启 read/write 工具，并明确列出 `create applications`、`write formulas`、`input data`、`audit performance` 等能力；`search` 工具会暴露 Blocks 元数据但不返回实际数据（[MCP Server](https://kb.pigment.com/docs/mcp-server-1), [Supported tools](https://kb.pigment.com/docs/supported-tools), [Connect common MCP Clients](https://kb.pigment.com/docs/connect-common-mcp-clients)）。

【设计判断】因此，Pigment 的 MCP/Agent 不能简单概括成“只读”或“看不到公式”；更准确的说法是：默认访问受权限约束，而 advanced mode 可以打开建模与编辑工具。对 Foundry 来说，这更适合被理解为“受控开放口”，而不是先验给能力贴只读标签。

【官方宣称】Pigment 的 Excel Connector、原始 Block 导出 API、和非原生集成说明，说明它支持 Excel 往返与外部系统交换（[Troubleshooting Pigment Connector for Excel](https://kb.pigment.com/docs/troubleshoot-connector-excel), [Export raw data from a Pigment Block](https://kb.pigment.com/docs/raw-data-block), [Export Pigment data to Snowflake](https://kb.pigment.com/docs/export-snowflake), [Non-native integrations](https://kb.pigment.com/docs/non-native-integrations)）。

可借鉴点：

- 维度、版本、场景、度量的语义应先于 UI 组织。
- 场景和版本应分层，短期假设和长期版本不要混在一起。
- AI 适合做解释、下钻、摘要和辅助建模，不必承担数值真相。
- MCP 适合做受控开放口：先开放读、解释和有限写入，再按角色扩建模工具。

## Drivetrain：驱动因子 + 滚动节奏

【官方宣称】Drivetrain 把自己定位为 AI-native FP&A 平台，公开强调 forecast、budget、headcount、scenario、variance、collaboration（[Drivetrain 首页](https://www.drivetrain.ai/), [Driver-Based Planning Software](https://www.drivetrain.ai/solutions/driver-based-planning-software), [Financial Planning & Analysis Software](https://www.drivetrain.ai/financial-planning-analysis-software)）。

【官方宣称】它的 driver-based planning 页面明确把 headcount、price、marketing spend 等业务驱动因子连到财务结果，并支持多个 scenario 通过不同假设快速生成（[Driver-Based Planning Software](https://www.drivetrain.ai/solutions/driver-based-planning-software)）。另外，rolling forecasts、BvA variance analysis、version control、audit trails、role-based access、multi-level approval workflows 也都出现在官方页面里（[Financial Planning & Analysis Software](https://www.drivetrain.ai/financial-planning-analysis-software), [Strategic Finance Software for FP&A Teams](https://www.drivetrain.ai/use-cases/finance-teams), [Business Budgeting & Planning](https://www.drivetrain.ai/budgeting-planning)）。

【文档确认】Drivetrain 的 Excel add-in 说明它可以把 live data 带进 Excel；FAQ 也写明可以导入 Excel / Google Sheets / CSV / XLSX，并在需要时把报告或模型导出回 Excel（[Microsoft Excel add-in](https://integrations.drivetrain.ai/extending-drivetrain/microsoft-excel-add-in), [FAQ](https://www.drivetrain.ai/faq)）。

【文档确认】Drivetrain API 页面公开了两个端点：`Get metrics list API`（GET）和 `Get metrics bulk data API`（POST），并要求 API key 认证；公开页只说明这两个接口，不应直接外推为“覆盖所有对象的完整写回 API”（[Drivetrain API](https://integrations.drivetrain.ai/extending-drivetrain/drivetrain-api)）。

【未验证】公开资料里，Drivetrain 对协作、审批、版本、滚动节奏说得很清楚，但没有把计算与模型语义展开到可直接复用的程度，因此这里只把它当成“财务经理日常工作流”的参考。

可借鉴点：

- 围绕驱动因子、滚动预测、预算 owner、版本和差异来组织界面。
- Excel 继续作为工作面，但不要成为事实分叉源。
- AI 最适合出现在 variance commentary、异常提醒、追问建议和摘要里。
- API 先公开事实读取和批量拉取，再考虑更深的写回。

## Planful：Office 回路 + 可解释 AI

【官方宣称】Planful 公开把平台拆成 Planful Platform、Integrations、Spotlight for Microsoft 365、MCP Server 和 Planful AI（[Planful](https://planful.com/), [Planful AI](https://planful.com/ai/), [Planful MCP Server](https://planful.com/platform/mcp/), [Spotlight for Microsoft 365](https://planful.com/solution-hub/spotlight-microsoft/)）。

【官方宣称】Planful 的 Analyst 负责 instant, explainable insights，Planner 负责从数据构建 forecast；MCP Server 页面还明确写了“Claude 可用”，而 ChatGPT、Gemini、Copilot 仍是后续支持，因此不能在 2026-09-06 把它们当作已普遍可用能力（[Planful Analyst Assistant](https://planful.com/ai/analyst/), [Planful AI](https://planful.com/ai/), [Planful MCP Server](https://planful.com/platform/mcp/)）。

【官方宣称】Spotlight 页面说明 Excel、PowerPoint、Word 都能直接连到 Planful 数据并一键刷新，格式保持不变（[Spotlight for Microsoft 365](https://planful.com/solution-hub/spotlight-microsoft/)）。这更像是“Office 物料回路”，而不是单个 Excel 插件。

【文档确认】公开 help 里很多页面来自 Planful for Marketing 子域，例如 Forecast、Manage Page、True-Up、Import/Export Data；这些页面只覆盖 marketing budgeting / true-up workflow，能说明预算、forecast、actual spend、true-up、filters、导入导出这些交互思路，但不能直接外推成通用财务模型，而且 help 页本身有登录限制（[Forecast for Budget Planning](https://help.planful.com/planful-for-marketing/docs/forecast-for-budget-planning), [Getting to Know the Manage Page](https://help.planful.com/planful-for-marketing/docs/getting-to-know-the-manage-page), [True-Up Functionality on Manage Page](https://help.planful.com/planful-for-marketing/docs/true-up-functionality-on-manage-page), [Import/Export Data](https://help.planful.com/planful-for-marketing/docs/importexport-data), [Planful Help Access](https://planful.com/help-access/)）。

【未验证】因此，Planful 更适合作为“受治理的财务经理工作面”参考，而不是作为底层模型语义的通用答案。

可借鉴点：

- 让 Excel / PPT / Word 成为一等公民，但继续从统一数据源刷新。
- Planful 当前 MCP 页面明确只读；这只是该产品当前边界。Foundry 自身应允许已授权任务中的假设、情景和草稿修改，由同一计算服务承接。
- AI 的价值是 explainable insight，而不是替代财务判断。
- 预算、forecast、true-up、variance 评论最好在同一工作流闭环。

## Anaplan：确定性规划内核

【文档确认】Anaplan 的 Dimensions、General lists、Modules、Line items、Time、Versions、Formulas、List subsets、Production lists 清楚地区分了结构、数据、版本和生产数据（[Dimensions](https://help.anaplan.com/dimensions-e020c93d-9f3e-4cce-8294-2d34073b302a), [General lists](https://help.anaplan.com/general-lists-403a1ed1-ad7b-4ab3-b40c-61dd9d651075), [Modules](https://help.anaplan.com/modules-5d25099d-15ae-426c-ade1-33b658f58b8c), [Line items](https://help.anaplan.com/line-items-52d76cdd-2571-4400-8f34-b15dd5651b9f), [Time](https://help.anaplan.com/time-53836b4a-1238-48ef-834a-8728b24f3d8e), [Versions](https://help.anaplan.com/versions-19b4391f-5257-40ee-8dfb-36f0ab426c8f), [Formulas](https://help.anaplan.com/e1cc95b4-915d-435b-98cc-d34fbf2ab032), [List subsets](https://help.anaplan.com/list-subsets-589d9f5d-f439-40a4-905f-5027c2dc9c21), [Production lists overview](https://help.anaplan.com/production-lists-overview-def2aa72-278a-4b85-97fb-d858c1dbbe97)）。

【文档确认】Versions 页面说明默认会有 Actual 和 Forecast，且 versions 可用于比较不同 scenario；Modules 页面则说明模块会记录 data against dimensions such as Time, Versions, and lists（[Versions](https://help.anaplan.com/versions-19b4391f-5257-40ee-8dfb-36f0ab426c8f), [Modules](https://help.anaplan.com/modules-5d25099d-15ae-426c-ade1-33b658f58b8c)）。

【文档确认】Anaplan 的集成层包括 Integration API v2.0、CloudWorks API、Bulk API、Transactional APIs、Administration API、Audit API 和 Data Orchestrator（[Integration API v2.0](https://help.anaplan.com/integration-api-v20-3107aa54-d12b-4c48-9550-3561c84adbb2), [CloudWorks API](https://help.anaplan.com/cloudworks-api-94bfcdc3-fff0-48d6-be9c-0e1bba2e889c), [Bulk API index](https://help.anaplan.com/bulk-api-index-68570416-5a68-4600-8ac4-d6898cf2e56d), [Use the transactional APIs](https://help.anaplan.com/use-the-transactional-apis-cc1c1e91-39fc-4272-a4b5-16bc91e9c313), [Administration API](https://help.anaplan.com/administration-api-34c09687-9110-4672-b31b-0f959f67ea32), [Audit](https://help.anaplan.com/audit-034cf52f-8ccf-49e0-a545-96861b12a645), [Anaplan Data Orchestrator](https://help.anaplan.com/anaplan-data-orchestrator-c6188479-0975-455c-a642-bfaa17452ac0)）。

【文档确认】Excel 侧，XL Reporting 是在 Excel 里创建报表和仪表板；Excel Add-in Series 4 则是创建与 Anaplan 之间的 read-only 或 read/write 连接。Series 4 的兼容说明列出 Windows 和相应 Office 要求，不能据此承诺 macOS 宿主支持；`Create a connection in Excel` 又把连接分成 read-only 与 read/write，前者只看数据，后者可写新数据。XL Reporting 的 Web Edition 另有服务端要求，不能将这个版本的部署条件泛化到全部 XL Reporting 产品（[Anaplan XL Reporting](https://help.anaplan.com/anaplan-xl-reporting-4fa3d997-207a-4257-aba7-e73579e4f55c), [Anaplan XL Reporting Web Edition server requirements](https://help.anaplan.com/anaplan-xl-reporting-web-edition-server-requirements-4b7f1bc5-e023-4806-a7b2-438296ac8a40), [Check your software versions and settings for the Excel Add-in](https://help.anaplan.com/check-your-software-versions-and-settings-for-the-excel-add-in-0740fa5b-4a36-4b92-9169-94fecaa631ca), [Excel Add-in Series 4](https://help.anaplan.com/excel-add-in-series-4-4f3c3661-1e69-42f1-ad86-00c6898075c6), [Create a connection in Excel](https://help.anaplan.com/create-a-connection-in-excel-96026b6b-6c91-491c-804e-d6c36504b540), [Connection issues and limits in the Excel Add-in](https://help.anaplan.com/connection-issues-and-limits-in-the-excel-add-in-4f2d8c19-4a3f-4438-bf95-be29ffafc59e)）。

【官方宣称】Anaplan 的主站和 AI 页面把 deterministic calculations、probabilistic AI、connected data、workflows 和 role-based agents 放在同一平台里；CoModeler 用自然语言辅助建模，Analyst 用自然语言问数（[Anaplan](https://www.anaplan.com/), [Anaplan Intelligence](https://help.anaplan.com/intelligence-781d444c-bf7a-4930-be03-79f22a766c46), [Anaplan CoModeler](https://help.anaplan.com/comodeler-2046f091-4e8a-4561-b77b-e5e60d1ce317), [Anaplan Analyst](https://help.anaplan.com/anaplan-analyst-d72a83b2-24e3-49b9-9034-c20f9b0b3328), [AI-driven Scenario Planning & Analysis Platform](https://www.anaplan.com/platform/intelligence/)）。

【未验证】这套公开资料足以说明 Anaplan 的语义底座适合 Foundry 参考，但不代表 Foundry 需要复制它的完整企业级实施形态。

可借鉴点：

- 维度、模块、line item、版本、时间应成为 Foundry 的基础语言。
- 确定性计算与 AI 叙事要分层，避免把计算交给 LLM。
- API / workflow / audit / data orchestrator / Excel 连接应形成一条完整链路。
- 如果未来扩到建账、合并、资金管理，这类语义底座会比单纯报表工具更合适。

## 对 Foundry 的建议

【推论】四家公开资料共同指向一件事：财务经理想要的不是“纯聊天”，而是可以反复追问、改假设、切场景、看差异、回 Excel、再回到工作台的闭环（Pigment 的 MCP/advanced mode、Drivetrain 的 driver-based planning、Planful 的 Spotlight/MCP、Anaplan 的 Excel Add-in 与 API）。

【建议】Foundry 第一阶段先做三个闭环：P&L 差异、下钻和 Excel 文件往返。围绕这三个闭环，再补最小事实层、计算层和解释层，让经理能改假设、切场景、存草稿、重算并复核结果；驱动因子建模、Office 物料全家桶和更深的 MCP 写回放到第二阶段。人员安排按实际工作量确定。

【建议】审批树可以后置为可插拔治理能力；第一阶段更重要的是让经理通过受控工具改假设、改场景、存草稿、重算结果。LLM 不负责伪造结果，负责帮用户提问、组织、解释和记录。

## 明确延后的能力

下面这些能力可以保留接口和数据形状，但不建议作为 Foundry 第一阶段的主承诺：

- 全量 EPM 套件式功能：关账编排、法定合并、复杂审批树、任务中心、跨组织模板商店。
- 过重的建模向导：让非财务用户独立建出复杂模型的整套流程。
- 一次性兼容所有 Office 物料类型：先把 Excel 做深，再扩到 PPT / Word。
- 过早引入资金管理 / 建账 / 合并的完整工作流：这些是下一阶段的自然扩展，但前提是核心分析内核稳定。

## 最小验证实验

为了验证 Foundry 的新版方案是否真的对齐财务分析场景，建议先做三个小实验：

1. 单一 P&L 实验：用一个月度 P&L 模型验证维度、版本、场景、actual/budget/forecast、差异、下钻和归因是否闭环。
2. Excel 往返实验：在 Excel 中改假设/场景草稿，刷新、导入、导出，确认 Excel 是工作面，不是分叉事实源。
3. 解释实验：让 LLM 只基于已算出的差异写 commentary，验证它能否解释“为什么变了”，但不能自己发明数。

## 资源依赖

如果要把这些能力做成 Foundry 的长期底座，起步需要几类能力，不一定是四个人：

- 财务模型负责人：定义维度、版本、场景和差异口径。
- 数据/集成工程：负责 ERP、总账、仓库、Excel 和 MCP 接口。
- 前端/交互设计：负责对话、表格、报告和任务之间的主次关系。
- 财务 SME：负责验证 commentary、滚动预测、资金与账务扩展的真实业务语义。

## 来源表

| 产品 | 级别 | 官方来源 | 日期 | 主要用途 |
|---|---|---|---:|---|
| Pigment | 文档确认 | [Model with Metrics](https://kb.pigment.com/docs/model-metrics) | 2026-09-06 访问 | Metrics 结构 |
| Pigment | 文档确认 | [Understand Dimension and Transaction Lists](https://kb.pigment.com/docs/understand-dimension-transaction-lists) | 2026-09-06 访问 | 分析轴 |
| Pigment | 文档确认 | [Work with Tables to Summarize Information](https://kb.pigment.com/docs/tables-summarize-information) | 2026-09-06 访问 | P&L / 项目成本 |
| Pigment | 文档确认 | [Versions and Scenarios](https://kb.pigment.com/docs/versions-scenarios) | 2026-09-06 访问 | 版本与场景分层 |
| Pigment | 官方宣称 | [Pigment AI](https://kb.pigment.com/docs/pigment-ai) | 2026-09-06 访问 | AI 组合能力 |
| Pigment | 文档确认 | [MCP Server](https://kb.pigment.com/docs/mcp-server-1) | 2026-09-06 访问 | MCP 入口与权限 |
| Pigment | 文档确认 | [Supported tools](https://kb.pigment.com/docs/supported-tools) | 2026-09-06 访问 | advanced mode / read-write tools |
| Pigment | 文档确认 | [Connect common MCP Clients](https://kb.pigment.com/docs/connect-common-mcp-clients) | 2026-09-06 访问 | 第三方 AI 连接 |
| Pigment | 文档确认 | [Troubleshooting Pigment Connector for Excel](https://kb.pigment.com/docs/troubleshoot-connector-excel) | 2026-09-06 访问 | Excel Connector |
| Pigment | 文档确认 | [Export raw data from a Pigment Block](https://kb.pigment.com/docs/raw-data-block) | 2026-09-06 访问 | 原始数据导出 |
| Drivetrain | 官方宣称 | [Drivetrain 首页](https://www.drivetrain.ai/) | 2026-09-06 访问 | 平台定位 |
| Drivetrain | 官方宣称 | [Driver-Based Planning Software](https://www.drivetrain.ai/solutions/driver-based-planning-software) | 2026-09-06 访问 | driver-based planning |
| Drivetrain | 官方宣称 | [Financial Planning & Analysis Software](https://www.drivetrain.ai/financial-planning-analysis-software) | 2026-09-06 访问 | rolling forecast / variance |
| Drivetrain | 官方宣称 | [Strategic Finance Software for FP&A Teams](https://www.drivetrain.ai/use-cases/finance-teams) | 2026-09-06 访问 | approvals / version control |
| Drivetrain | 文档确认 | [Drivetrain API](https://integrations.drivetrain.ai/extending-drivetrain/drivetrain-api) | 2026-09-06 访问 | 2 个公开 API 端点 |
| Drivetrain | 文档确认 | [Microsoft Excel add-in](https://integrations.drivetrain.ai/extending-drivetrain/microsoft-excel-add-in) | 2026-09-06 访问 | Excel 往返 |
| Drivetrain | 未验证 | [Business Budgeting & Planning](https://www.drivetrain.ai/budgeting-planning) | 2026-09-06 访问 | budget/forecast workflow 推断 |
| Planful | 官方宣称 | [Planful](https://planful.com/) | 2026-09-06 访问 | 平台定位 |
| Planful | 官方宣称 | [Planful AI](https://planful.com/ai/) | 2026-09-06 访问 | AI 组合能力 |
| Planful | 官方宣称 | [Planful Analyst Assistant](https://planful.com/ai/analyst/) | 2026-09-06 访问 | explainable insights |
| Planful | 官方宣称 | [Planful MCP Server](https://planful.com/platform/mcp/) | 2026-09-06 访问 | governed source of truth / future clients |
| Planful | 官方宣称 | [Spotlight for Microsoft 365](https://planful.com/solution-hub/spotlight-microsoft/) | 2026-09-06 访问 | Excel/PPT/Word 往返 |
| Planful | 官方宣称 | [Rolling forecasts](https://planful.com/solution-hub/rolling-forecasts/) | 2026-09-06 访问 | 连续预测 |
| Planful | 文档确认 | [Forecast for Budget Planning](https://help.planful.com/planful-for-marketing/docs/forecast-for-budget-planning) | 2026-09-06 访问 | 子域预算逻辑 |
| Planful | 文档确认 | [Getting to Know the Manage Page](https://help.planful.com/planful-for-marketing/docs/getting-to-know-the-manage-page) | 2026-09-06 访问 | 子域预算逻辑 |
| Planful | 文档确认 | [True-Up Functionality on Manage Page](https://help.planful.com/planful-for-marketing/docs/true-up-functionality-on-manage-page) | 2026-09-06 访问 | 子域预算逻辑 |
| Planful | 文档确认 | [Planful Help Access](https://planful.com/help-access/) | 2026-09-06 访问 | help 访问限制 |
| Anaplan | 文档确认 | [Dimensions](https://help.anaplan.com/dimensions-e020c93d-9f3e-4cce-8294-2d34073b302a) | 2026-09-06 访问 | 维度定义 |
| Anaplan | 文档确认 | [Modules](https://help.anaplan.com/modules-5d25099d-15ae-426c-ade1-33b658f58b8c) | 2026-09-06 访问 | 模块上下文 |
| Anaplan | 文档确认 | [Versions](https://help.anaplan.com/versions-19b4391f-5257-40ee-8dfb-36f0ab426c8f) | 2026-09-06 访问 | 默认版本 |
| Anaplan | 文档确认 | [Integration API v2.0](https://help.anaplan.com/integration-api-v20-3107aa54-d12b-4c48-9550-3561c84adbb2) | 2026-09-06 访问 | REST 集成 |
| Anaplan | 文档确认 | [CloudWorks API](https://help.anaplan.com/cloudworks-api-94bfcdc3-fff0-48d6-be9c-0e1bba2e889c) | 2026-09-06 访问 | 自建集成 |
| Anaplan | 文档确认 | [Excel Add-in Series 4](https://help.anaplan.com/excel-add-in-series-4-4f3c3661-1e69-42f1-ad86-00c6898075c6) | 2026-09-06 访问 | Excel 连接 |
| Anaplan | 文档确认 | [Check your software versions and settings for the Excel Add-in](https://help.anaplan.com/check-your-software-versions-and-settings-for-the-excel-add-in-0740fa5b-4a36-4b92-9169-94fecaa631ca) | 2026-09-06 访问 | Windows 兼容性 |
| Anaplan | 文档确认 | [Anaplan XL Reporting Web Edition server requirements](https://help.anaplan.com/anaplan-xl-reporting-web-edition-server-requirements-4b7f1bc5-e023-4806-a7b2-438296ac8a40) | 2026-09-06 访问 | Web edition 服务端要求 |
| Anaplan | 文档确认 | [Anaplan XL Reporting](https://help.anaplan.com/anaplan-xl-reporting-4fa3d997-207a-4257-aba7-e73579e4f55c) | 2026-09-06 访问 | Excel 报表/仪表板 |
| Anaplan | 文档确认 | [Create a connection in Excel](https://help.anaplan.com/create-a-connection-in-excel-96026b6b-6c91-491c-804e-d6c36504b540) | 2026-09-06 访问 | read-only / read-write |
| Anaplan | 文档确认 | [Connection issues and limits in the Excel Add-in](https://help.anaplan.com/connection-issues-and-limits-in-the-excel-add-in-4f2d8c19-4a3f-4438-bf95-be29ffafc59e) | 2026-09-06 访问 | 权限与限制 |
| Anaplan | 官方宣称 | [Anaplan](https://www.anaplan.com/) | 2026-09-06 访问 | deterministic + probabilistic AI |
| Anaplan | 官方宣称 | [Anaplan CoModeler](https://help.anaplan.com/comodeler-2046f091-4e8a-4561-b77b-e5e60d1ce317) | 2026-09-06 访问 | 自然语言建模 |
| Anaplan | 官方宣称 | [Anaplan Analyst](https://help.anaplan.com/anaplan-analyst-d72a83b2-24e3-49b9-9034-c20f9b0b3328) | 2026-09-06 访问 | 自然语言问数 |

## 未验证项

- Planful 的公开 help 中很多关键页面需要登录，公开可见边界有限，因此不能直接把 marketing 子域的预算流程扩成通用财务模型。
- Drivetrain 的公开 API 只明示两个 metrics 相关端点，是否存在更广的对象级写回，公开页没有展开。
- 本轮找到的 Pigment 和 Anaplan 建模文档可用于参考 Foundry 的计算合同；但具体到底开放哪些写回工具，仍应按角色和场景再做验证。
