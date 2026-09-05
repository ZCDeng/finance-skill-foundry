# Excel 原生能力调研：Datarails / Aleph / Cube

访问日期：2026-09-06

这份调研只看一个问题：怎样把财务分析能力做成“Excel 不搬家、数据不断链、AI 可追溯、未来还能扩到建账和资金管理”的底座。下面我把来源分成三类：帮助文档、产品页宣称、答案/博客型官方内容。帮助文档优先，产品页和答案页只在边界清楚时作为官方宣称来用。

- **Datarails**：重点考察 Excel 刷新、映射、钻取和预算/差异报告。
- **Aleph**：重点考察双向表格、映射、说明记录和 Claude/ChatGPT 等入口的共同上下文。
- **Cube Software**：重点考察情景、fetch/publish、Smart Analysis 和 MCP 读写合同；表格既可查询也可提交计划数据。

## 1) Datarails：把 Excel 留在前台，把数据和流程放到云端

证据等级：以帮助中心为主，产品页为辅。帮助中心明确描述操作能力，产品页更多是官方宣称。

**官方来源描述（帮助文档与产品宣称，非本轮实测）**

- Datarails 官方把自己定义为 **Excel-native FP&A**，支持在 Excel 中继续工作，同时把各系统、各实体、各表格的数据自动汇总成单一事实源。[Datarails FP&A - Excel-Native Financial Planning & Analysis](https://www.datarails.com/datarails-fpa/)
- Flex Add-in 的 Refresh 会同步 **datasets、mappings、groupings**，不是单纯拉数，而是把映射和分组一起带回工作簿。[Datarails Flex Add-In Overview](https://support.datarails.com/hc/en-us/articles/15717939528860-Datarails-Flex-Add-In-Overview)
- Data Mapper 支持从上传的 Excel 或 ERP 集成读取原始数据，再映射进数据库；Lookups 把 **GL / COA** 关系显式化。[Data Mapper Overview](https://support.datarails.com/hc/en-us/articles/14442192827164-Data-Mapper-Overview) / [Lookups Overview](https://support.datarails.com/hc/en-us/articles/14562343034396-Lookups-Overview)
- Reporting Agent 围绕 **actuals vs budget/forecast** 做 variance、异常和 drill-down，FinanceOS AI 还能导出 Excel 报表和 audit evidence packages。[The Three Datarails AI Agents](https://support.datarails.com/hc/en-us/articles/25257484537500-The-Three-Datarails-AI-Agents) / [FinanceOS AI Introduction](https://support.datarails.com/hc/en-us/articles/26195490425244-FinanceOS-AI-Introduction-Your-Financial-Data-Powered-by-AI)
- 官方已给出 **ChatGPT（MCP，read-only）** 和 **Claude Desktop（connector + plugin）** 的接法，说明它不是只停留在展示层。[Connect Datarails to ChatGPT](https://support.datarails.com/hc/en-us/articles/25905041804444-Connect-Datarails-to-ChatGPT) / [Getting Started with Datarails on Claude Desktop](https://support.datarails.com/hc/en-us/articles/25873904696860-Getting-Started-with-Datarails-on-Claude-Desktop)

**边界**

- 公开文档没有证明它能自动把结果写回 ERP / 总账；更像是查询、分析、生成报表，不是反向入账。
- ChatGPT 侧连接器是 **read-only**，不能被理解成业务系统写操作的替代品。
- 产品页里诸如“AI 输出更准确、可审计”这类话，属于官方宣称，不应当直接当作接口或权限事实。

**可借鉴**

- Excel 继续留给财务经理，系统把刷新、映射、分组、版本追踪做稳。
- 把 drill-down 做成一等能力：从汇总值点回交易、科目、实体和期间。
- 把预算、预测、实际放进同一套对象里管理，而不是散在不同模板里。

## 2) Aleph：MCP、财务数据层与双向表格

证据等级：以产品页、发布说明和答案页为主，属于官方宣称与指南。本轮未取得完整 MCP 工具/权限合同或真实租户结果。

**官方来源描述（帮助文档与产品宣称，非本轮实测）**

- Aleph 官方写明支持 **Excel / Google Sheets 双向集成**：可一键或定时拉取汇总数据，也可把预算、场景或整张表推回 Aleph。[FP&A Software for Excel & Google Sheets](https://www.getaleph.com/platform/spreadsheets)
- mappings 页面明确说它会持续对新原始数据做 **classify and map**，并用 agent 24/7 盯住新账户、新供应商和新维度。[AI Data Mappings for FP&A](https://www.getaleph.com/platform/ai/mappings)
- Aleph 把 **MCP** 当成主入口：Claude、ChatGPT、Excel、Sheets 都能接到受管控的数据层，做问数、建报表、刷新模型、草拟 commentary 和触发 workflow。[Aleph MCP: Trusted finance data in Claude, ChatGPT, Excel & more](https://www.getaleph.com/blog/introducing-aleph-mcp) / [MCP for finance teams](https://www.getaleph.com/answers/mcp-guide-finance-teams)
- 官方对 live drillable BvA 的要求很清楚：**连接，不是导出**；需要 **GL 到 reporting lines 的 mapping**、从报表数值回到交易的 **drill path**，以及可复用的 **commentary register**。[Live, drillable BvA in Excel with AI](https://www.getaleph.com/answers/live-drillable-bva-excel-ai)
- 这些文章还明确把 **变动说明**、**模型刷新**、**上下游系统映射** 视为同一条 FP&A 工作流，但它们仍是官方指南，不等于独立实测。

**边界**

- 已公开的“push”仍然是向 **Aleph 自己的数据层** 写入，不是写回 ERP / 总账 / 银行。
- 官方强调 commentary 和 workflow，但没有公开证明可以无人工审核自动发布 board-ready 叙述。
- “24/7 映射”“自带 AI”这类表述属于官方宣称，应与帮助文档里的操作边界分开看。

**可借鉴**

- 把 MCP 当统一入口：Claude、ChatGPT、Excel、Sheets 走同一条受控通道。
- 把 account mapping + commentary register 做成核心对象，而不是后置附件。
- 把“看数”和“写说明”串成一条链：刷新 actuals、生成 BvA、写差异说明、回到可追溯来源。

## 3) Cube Software：把财务工作流做成可控的底座，Excel 只是前台

证据等级：以帮助中心为主，官网产品页为辅。帮助中心明确描述 fetch、publish、情景与 MCP 权限，本文按工具动作记录边界。

**官方来源描述（帮助文档与产品宣称，非本轮实测）**

- Cube Workspace 的维度包括 **Account、Department、Scenario、Time**，还可以扩展自定义维度；这说明它的语义模型不是简单表格，而是围绕财务维度组织的。[Cube Workspace overview](https://help.cubesoftware.com/hc/en-us/articles/4407081473556-Cube-Workspace-overview)
- Spreadsheet App 里的 **fetch** 是从 Cube 拉数据到表格；它会用 range 里定义的 dimensions 作为行列，并且表格/报表里保存的是 Cube Value，也就是映射、翻译和计算后的数据。[Cube glossary](https://help.cubesoftware.com/hc/en-us/articles/360052501091-Cube-glossary) / [Use a table with a range](https://help.cubesoftware.com/hc/en-us/articles/34911893447060-Build-and-use-a-table)
- **publish** 是把工作表中的值写回 Cube 的 scenario，不是把数据写回源 ERP；发布要求用户有对应的 data access group 权限和 range publish 权限，且 range 里的 filter 必须落在单一 member 上。[Publish data to Cube](https://help.cubesoftware.com/hc/en-us/articles/4407348689940-Publish-data-to-Cube)
- scenarios 分成 **actuals / planning / locked / AI Smart Forecast**。actuals 是写保护的源系统数据，planning 存预算和 forecast，locked 用于快照和 variance analysis，说明它把“分析”和“版本”放在同一条数据链里。[Start planning with Scenarios in Cube](https://help.cubesoftware.com/hc/en-us/articles/20680370806036-Start-planning-with-Scenarios-in-Cube)
- 报表在 Spreadsheet App 和 Workspace 之间是同一份对象：Workspace 里能 fetch 更新、分组、归档，Spreadsheet App 里能 create / edit / publish / republish，并且权限始终受控。[Reports overview](https://help.cubesoftware.com/hc/en-us/articles/360056133891-Reports-overview)
- **Smart Analysis** 会自动检测并解释重要 variance，突出异常和 top drivers；Cube 的 reporting 页面也明确写了 every figure traces to the GL transaction。[Built With Your Feedback - What's New and What's Ahead](https://help.cubesoftware.com/hc/en-us/articles/45296396197012-Momentum-at-Cube-Built-With-Your-Feedback-What-s-New-and-What-s-Ahead) / [Variance Analysis](https://www.cubesoftware.com/variance-analysis) / [Financial Reporting & Analysis](https://www.cubesoftware.com/reporting-and-analysis)
- **Planner Agents** 负责 forecasting 和 scenario planning，能把 reforecast、assumptions、driver changes 发布回 Cube；帮助中心还明确说，AI 只能写入它创建的场景，或者你显式打开给 AI write-back 的场景，且每次写都会记入 audit trail、标记为 AI-originated、并检查 Data Access Scope。[The Planner Agents: AI for Forecasting & Scenario Planning](https://www.cubesoftware.com/ai-agents/planners) / [2026 Product Updates](https://help.cubesoftware.com/hc/en-us/articles/51048387237908-2026-Product-Updates) / [Cube MCP: Example Prompts to Supercharge Your FP&A](https://help.cubesoftware.com/hc/en-us/articles/46804211093780-Cube-MCP-Example-Prompts-to-Supercharge-Your-FP-A)
- MCP Server 连接 Claude、ChatGPT 等 AI app，提供 live、secure、permission-aware 的连接；帮助中心还明确写了 MCP write 需要 **Use MCP (Write)** 权限。[Connect Cube to AI Apps via MCP Server](https://help.cubesoftware.com/hc/en-us/articles/45569561283092-Connect-Cube-to-AI-Apps-via-MCP-Server) / [Cube MCP: Example Prompts to Supercharge Your FP&A](https://help.cubesoftware.com/hc/en-us/articles/46804211093780-Cube-MCP-Example-Prompts-to-Supercharge-Your-FP-A)
- Cube 的产品页和 AI 页面把自己定位成 **workflow-native FP&A / agentic finance layer**，并明确说 Excel、Sheets、Slack、Teams、Claude、ChatGPT 都是同一层的 surface；这部分是产品定位，但和上面的帮助中心证据一致。[Platform overview](https://www.cubesoftware.com/platform-overview) / [AI at Cube](https://www.cubesoftware.com/ai-at-cube)

**边界**

- Cube 的 MCP 写入对象包括情景值、计划表和看板等；不支持通过 Cube 写入源 ERP。具体工具合同按帮助中心核验，不能把“写回”泛化为任意对象可改。
- 情景数据写入检查用户权限、数据范围和目标情景的 AI 写入设置；其他工具有各自规则，不把情景开关泛化为所有动作的通用要求。
- 产品页上“every surface”“autonomous agents”这类说法，属于官方定位，不应直接当成所有场景都可用的实测结论。

**可借鉴**

- 把 **维度、scenario、report、table** 作为第一层对象，而不是只把它们当 UI 标签。
- 分别定义 fetch 取数、publish 提交计划输入和 MCP 写入动作，声明目标情景、版本与范围，避免把所有动作都称为“同步”。
- 把 Smart Analysis 放成默认能力，但保留每次写入的权限、审计和可回滚。
- 多入口复用同一模型的结构可供 Foundry 借鉴；未来建账和资金执行仍需自己的领域对象与回执，不能从计划写回直接外推。

## 4) 对 Foundry 的落地判断

如果目标是“让财务经理继续用 Excel，但又能直接问数、看差异、写说明、追溯来源”，我建议把三家的能力拆成三层来借：

- **前台操作层**：借 Datarails 的 Excel 留驻、刷新、版本控制、钻取和报表分发。
- **工作流智能层**：借 Aleph 的 MCP、双向表格、account mapping、commentary register 和 BvA 迭代。
- **语义底座层**：借 Cube Software 的维度、scenario、fetch/publish、MCP write 约束和审计轨迹。

最应该自建的，不是某个单点 AI 文案功能，而是财务经理真正需要的 **可信工作链**：

1. 连接真实数据源。
2. 把科目、实体、部门、场景和期间映射成稳定语义。
3. 允许在 Excel 里看、改、刷新、钻取。
4. 让 AI 生成差异说明和下一步建议。
5. 保留留痕和回滚。

当前优先分析闭环，建账与资金执行后续独立扩展。财务经理可以连续改假设、改情景、写说明；任务内草稿和计划版本不增加逐步审批。写入外部业务系统时再按目标、既有授权与动作影响定义执行合同。

## 5) 来源表

| 产品 | 官方来源 | 关键证据 | 日期 / 状态 |
| --- | --- | --- | --- |
| Datarails | [Datarails FP&A - Excel-Native Financial Planning & Analysis](https://www.datarails.com/datarails-fpa/) | 产品页：Excel-native、自动汇总、多系统统一事实源 | 页面实时更新，访问于 2026-09-06 |
| Datarails | [Datarails Flex Add-In Overview](https://support.datarails.com/hc/en-us/articles/15717939528860-Datarails-Flex-Add-In-Overview) | 帮助文档：Refresh 同步 datasets、mappings、groupings | 页面实时更新，访问于 2026-09-06 |
| Datarails | [Data Mapper Overview](https://support.datarails.com/hc/en-us/articles/14442192827164-Data-Mapper-Overview) | 帮助文档：上传 Excel 或 ERP 集成后映射进数据库 | 页面实时更新，访问于 2026-09-06 |
| Datarails | [Lookups Overview](https://support.datarails.com/hc/en-us/articles/14562343034396-Lookups-Overview) | 帮助文档：GL / COA 关系显式化 | 页面实时更新，访问于 2026-09-06 |
| Datarails | [The Three Datarails AI Agents](https://support.datarails.com/hc/en-us/articles/25257484537500-The-Three-Datarails-AI-Agents) | 帮助文档：Reporting Agent、variance、drill-down | 页面实时更新，访问于 2026-09-06 |
| Datarails | [FinanceOS AI Introduction](https://support.datarails.com/hc/en-us/articles/26195490425244-FinanceOS-AI-Introduction-Your-Financial-Data-Powered-by-AI) | 帮助文档：数据底座、Excel 导出、audit evidence packages | 页面实时更新，访问于 2026-09-06 |
| Datarails | [Connect Datarails to ChatGPT](https://support.datarails.com/hc/en-us/articles/25905041804444-Connect-Datarails-to-ChatGPT) | ChatGPT 通过 MCP 连接，且明确是 read-only | Updated May 31, 2026 |
| Datarails | [Getting Started with Datarails on Claude Desktop](https://support.datarails.com/hc/en-us/articles/25873904696860-Getting-Started-with-Datarails-on-Claude-Desktop) | Claude connector + plugin 分层 | Updated Aug 27, 2026 |
| Aleph | [FP&A Software for Excel & Google Sheets](https://www.getaleph.com/platform/spreadsheets) | 产品页：双向表格、pull / push、150+ connectors | 页面实时更新，访问于 2026-09-06 |
| Aleph | [AI Data Mappings for FP&A](https://www.getaleph.com/platform/ai/mappings) | 产品页：持续分类和映射原始数据，24/7 监控映射 | 页面实时更新，访问于 2026-09-06 |
| Aleph | [Aleph MCP](https://www.getaleph.com/blog/introducing-aleph-mcp) | Claude / ChatGPT 等入口 + 财务数据层 | 访问于 2026-09-06；本轮未确认精确发布日期 |
| Aleph | [MCP for finance teams](https://www.getaleph.com/answers/mcp-guide-finance-teams) | 官方指南：MCP 场景、工作流、受管控数据层 | 2026-09（页面显示为月度更新） |
| Aleph | [Live, drillable BvA in Excel with AI](https://www.getaleph.com/answers/live-drillable-bva-excel-ai) | 官方指南：BvA、account mapping、commentary register | 2026-09 更新 |
| Cube Software | [Cube Workspace overview](https://help.cubesoftware.com/hc/en-us/articles/4407081473556-Cube-Workspace-overview) | 帮助文档：Account / Department / Scenario / Time 维度 | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Reports overview](https://help.cubesoftware.com/hc/en-us/articles/360056133891-Reports-overview) | 帮助文档：fetch / publish / drill / permissions | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Cube glossary](https://help.cubesoftware.com/hc/en-us/articles/360052501091-Cube-glossary) | 帮助文档：Cube Value / mapped data 语义 | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Build and use a table](https://help.cubesoftware.com/hc/en-us/articles/34911893447060-Build-and-use-a-table) | 帮助文档：table / range 取数语义 | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Publish data to Cube](https://help.cubesoftware.com/hc/en-us/articles/4407348689940-Publish-data-to-Cube) | 帮助文档：publish 需要权限且写入 Cube scenario | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Start planning with Scenarios in Cube](https://help.cubesoftware.com/hc/en-us/articles/20680370806036-Start-planning-with-Scenarios-in-Cube) | 帮助文档：actuals / planning / locked / AI Smart Forecast | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Built With Your Feedback - What's New and What's Ahead](https://help.cubesoftware.com/hc/en-us/articles/45296396197012-Momentum-at-Cube-Built-With-Your-Feedback-What-s-New-and-What-s-Ahead) | 帮助文档：Smart Analysis 自动解释 variance | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Variance Analysis](https://www.cubesoftware.com/variance-analysis) | 产品页：trace to GL transaction | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Financial Reporting & Analysis](https://www.cubesoftware.com/reporting-and-analysis) | 产品页：trace to truth / reporting surfaces | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [2026 Product Updates](https://help.cubesoftware.com/hc/en-us/articles/51048387237908-2026-Product-Updates) | 帮助文档：AI write-back / audit / access boundary | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [The Planner Agents: AI for Forecasting & Scenario Planning](https://www.cubesoftware.com/ai-agents/planners) | 产品页：Planner Agents、MCP read/write、approval / audit trail | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Connect Cube to AI Apps via MCP Server](https://help.cubesoftware.com/hc/en-us/articles/45569561283092-Connect-Cube-to-AI-Apps-via-MCP-Server) | 帮助文档：AI apps via MCP、live secure connection | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Cube MCP: Example Prompts to Supercharge Your FP&A](https://help.cubesoftware.com/hc/en-us/articles/46804211093780-Cube-MCP-Example-Prompts-to-Supercharge-Your-FP-A) | 帮助文档：Use MCP (Write) permission、scenario write-back | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [Platform overview](https://www.cubesoftware.com/platform-overview) | 产品页：workflow-native FP&A、Excel/Sheets/Slack/Teams/AI surfaces | 页面实时更新，访问于 2026-09-06 |
| Cube Software | [AI at Cube](https://www.cubesoftware.com/ai-at-cube) | 产品页：agentic finance layer、trace to truth、spreadsheet stays | 页面实时更新，访问于 2026-09-06 |

**局限**

- 这份调研只覆盖 Excel-native / MCP / 语义层相关能力，没有展开 Pigment、Drivetrain、Planful、Anaplan，也没有覆盖金蝶、用友、帆软。
- 对“写回”的判定很严格：能证实的只算官方文档明确写出的读写边界；展示截图、营销语、案例博客都不等于 API 或实测。
- Aleph 和 Datarails 都有自家官方内容营销文章，能说明产品意图，但我在结论里只把“文档明确写出的动作”当作已证实能力。
