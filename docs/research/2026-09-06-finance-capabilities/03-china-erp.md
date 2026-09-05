# 中国企业账套 / ERP 财务分析能力调研

访问日期：2026-09-06
研究目标：为 Foundry 补强中国企业真实账套 / ERP 的管理报表接入能力，重点看凭证、科目余额、辅助核算、多组织期间、应收应付、库存 / 销售 / 成本、增量刷新、API 授权、分页、明细下钻，以及官方公开的 AI 能力。

## 结论先行

如果目标是“把真实账套数据稳定接到 Foundry，再做管理报表和分析”，最稳妥的做法不是把三家都当成同一种“ERP API”，而是分层处理。

金蝶 `AI星辰` 和 `AI星空` 是不同产品。星辰官方产品及生态页提供开放平台、API 服务和开发平台入口（[AI星辰](https://www.jdy.com/star/)；[生态 API 入口](https://www.jdy.com/ecology/api/)；[开放平台](https://open.jdy.com/)）。官方社区出现 API 授权服务按账套绑定的答复，本轮未验证答复者身份，仅作为待向目标租户确认的线索（[社区问答](https://vip.kingdee.com/questions/835531442419017728)）。本轮未展开星辰完整账务接口目录，不能以星空文档补足这一空白。

用友这边，`YonGPT` 的 AI 能力可以保留为可借鉴方向，但本次没有核实到可直接挂到 Foundry 的公开 API / 授权文档，所以不把它写成接入建议。`YonBIP / iuap` 是平台与业务应用集合。`U8 / U9 / NC / NCC` 都是具体 ERP 产品线；本次查到的 `U8` 公开文档里确实展开了凭证、总账、辅助核算、期间和分页等对象（[U8 开放平台](https://u8open.yonyou.com/)；[API中心](https://u8open.yonyou.com/apiCenter/index)；[token](https://u8open.yonyou.com/apiCenter/tokenGet)），适合作为 Foundry 的账套接口参考，但这里只写“本次查到”，不写成绝对比较。

帆软这边，边界清晰：`FineBI` 自己就直接支持智能问数、钻取和多维分析，并且官方文档明确写了它能对接接口协议和 ERP 等平台的数据源（[FineBI产品优势](https://help.fanruan.com/finebi/doc-view-1779.html)；[问数据](https://help.fanruan.com/finebi/doc-view-2580.html)；[普通钻取](https://help.fanruan.com/finebi/doc-view-133.html)；[AI诊断](https://help.fanruan.com/finebi/doc-view-2625.html)）。`FineDataLink` 是更重的数据集成 / 同步平台，适合多源同步、ETL / ELT 和 API 化数据服务。`FineReport` 仍然是报表制作与展示工具。对 Foundry 更合适的写法是“借鉴 FineBI 的问数、下钻、指标与刷新机制；如果已有帆软资产，可按接口权限复用，不必把它写成外部强制依赖”。

## 1. 金蝶：AI星辰

### 先把边界说清楚

- `AI星辰` 官方产品页列出财税管理、智能凭证、应收应付、出纳、多维核算、经营分析等能力；这是产品宣称，具体模块依目标版本核验。[星辰产品](https://www.jdy.com/star/)
- `AI星辰` 自己的产品页、生态页和客户端页都指向 `open.jdy.com` 的开放平台、API 服务和开发平台入口。
- `open.jdy.com` 首页的官方搜索摘要能看到“提供标准 API 接口、苍穹开发平台能力及多语言版本 SDK”这类表述，说明星辰确实有自己的开放入口。
- 但本轮没有把星辰官方 API 目录页完整展开到可逐条浏览的粒度，所以不能把“凭证、科目余额、辅助余额”直接写成已完整公开的接口清单。

### 本轮公开核实到什么

- 官方社区有答复称一个 API 授权服务只能同时绑定一个账套；作为授权调查线索，不据此代替现行商业合同或租户政策。[社区问答](https://vip.kingdee.com/questions/835531442419017728)
- 星辰官方页和客户端页再次确认了 `API 服务`、`开发平台`、`帮助中心`、`应用市场` 这些官方入口都存在。
- 星辰社区资料能看到财务侧的科目余额表、辅助属性、凭证分录等账务概念，但这类资料本轮只作为“对象存在性”的旁证，不当作接口已公开的证据。

### 对 Foundry 的现实建议

1. 金蝶这条线适合做“先确认星辰自己的开放入口，再按租户验证对象粒度”的路径。
2. 本轮确认开放平台和 API 服务入口；授权粒度及凭证、科目余额、辅助余额等具体对象合同在租户联调前继续核验。

### 需要保留的未验证点

- 星辰租户里是否开放到 Foundry 需要的具体对象粒度，尤其是科目余额、辅助核算、凭证分录级下钻对象。
- 不同版本 / 套餐对 API 服务、开发平台和对象权限的开放范围。
- `open.jdy.com` 中是否还有更完整的星辰 API 目录页可直接公开核实。

## 2. 用友：YonGPT / YonBIP / U8 / U9 / NC

### 先把品牌分开

- `YonGPT` 官方介绍将其用于企业服务、财务洞察与业务协作；这是 AI 产品能力介绍，不是面向 Foundry 的账套 API 合同。[官方介绍](https://www.yonyou.com/news/2607)
- `YonBIP / iuap` 是平台与业务应用集合，负责应用、数据、集成、智能、开发等能力。
- `U8 / U9 / NC / NCC` 是具体 ERP 产品线；YonBIP 也有业务应用。适配器按实际产品/版本确定，不能用品牌层名称替代对象合同。[开发者入口](https://developer.yonyou.com/openAPI)

### U8 开放平台：本次查到的公开材料

在本次查到的公开材料里，`U8` 开放平台已经展开了凭证、总账、辅助核算、期间和分页等对象，适合作为 Foundry 的“账套 API 参考系”；这里只说“本次查到”，不把它写成对所有竞品的终局比较。

- `system/token` 文档给出 from_account、app_key、app_secret 等认证参数；实际额度、有效期及授权配置在目标租户核验。[token 文档](https://u8open.yonyou.com/apiCenter/tokenGet)
- `apiCenter/index` 的分类里，公开列出了平台类、基础档案类、总账类、网上报销类、销售管理类、采购管理类、库存管理类、应收应付类等。
- 基础档案里公开了 `period/batch_get`、`vendor/batch_get`、`customer/batch_get`、`inventory/batch_get`、`code/batch_get`、`code_auxiliary_relation_ys/batch_get`、`glaccount_ys/batch_get` 等。
- 总账类里公开了：
  - [voucherlist/batch_get](https://u8open.yonyou.com/apiCenter/voucherlist_batch_get)：凭证列表，文档有分页参数。
  - [voucherdetaillist/batch_get](https://u8open.yonyou.com/apiCenter/voucherdetaillist_batch_get)：凭证分录明细，返回部门、人员、客户、供应商、项目、现金流量项目等字段。
  - [accountsum/batch_get](https://u8open.yonyou.com/apiCenter/accountsum_batch_get)：科目总账，返回期初、借方、贷方、期末、币种与数量信息。
  - [accountass/batch_get](https://u8open.yonyou.com/apiCenter/accountass_batch_get)：辅助总账，支持部门、人员、客户、供应商与项目过滤。

### U8 公开文档对接入前提和分页的确认

- `vendor/batch_get` 这类接口都公开了 `page_index`、`rows_per_page`、`row_count`、`page_count`。
- `voucherlist/batch_get` 同样公开了分页参数和按日期、科目、外部系统号、凭证号、凭证类别、制单人过滤的参数。
- `inventory/get` 公开了单个存货信息的参数和返回字段，包含采购默认单位、销售默认单位、库存默认单位、税率、自定义项等。
- [period/batch_get](https://u8open.yonyou.com/apiCenter/period_batch_get) 给出年度、期间与起止日期等。设计推导：可作为期间映射输入，但跨账套/组织对齐规则仍由 Foundry 明确定义。

### U9 / NC / NCC / YonBIP 的公开边界

- 用友开发者中心的 `OpenAPI` 页面确认平台能力包括 API 网关、数据集成、集成总线、云主数据、语义模型、数据大屏、AI 工作坊、RPA、部署管理与监控。
- `API 网关` 页面确认其提供全生命周期管理、统一授权调用、监控预警、安全策略、NC/NCC 预置能力，并明确列出 `NC/NCC OpenAPI` 作为预置产品服务。
- 但公开网页层面，这些页面更像“平台级治理和入口说明”，没有像 U8 那样把财务对象接口目录完整展开到每个账务对象。因此，NC/U9 这几条线要把“公开平台能力”与“租户里真实可调接口范围”分开看。

### 对 Foundry 的现实建议

1. 如果你的目标是稳定接入“真实账套明细”，先从本次查到的 U8 公开文档入手，因为它公开了账务对象与分页 / 明细能力。
2. 如果是 U9 / NC / NCC / YonBIP，先把它们理解为平台与具体 ERP 形态的组合，不要和 YonGPT 混成一个层次。
3. YonGPT 只保留为“可借鉴的 AI 能力方向”，不要写成本次已验证的 Foundry 直连接口。
4. 对 U8 公开文档已经能确认的对象，Foundry 可以先设计“凭证列表 → 凭证明细 → 科目总账 → 辅助总账 → 期间 → 存货 / 客户 / 供应商”的接入链路。

## 3. 帆软：FineBI / FineDataLink / FineReport

### 官方边界

- `FineBI` 的官方文档直接确认它支持智能问数、探索分析、管理驾驶舱、专题分析报告、自定义指标看板，以及接口协议 / ERP 等平台的数据源对接。
- `FineBI` 的问数据文档直接确认，它有智能模式和极速模式，能通过自然语言问数，并在主题和字段不确定时要求用户确认，还支持多轮对话、结果校验和业务规则记忆。
- `FineBI` 的钻取文档直接说明，仪表板可以先看宏观图表，再通过页面内钻取联动逐级向下钻取，定位具体问题。
- `FineBI` 的 AI 诊断文档给出默认采样参数：明细表 100 行、其他组件 20 行，合计 1000 行、15 列；参数可配置。因此需要记录实际送入模型的覆盖范围，不宜称为全量审计。[AI诊断](https://help.fanruan.com/finebi/doc-view-2625.html)
- `FineDataLink` 是一站式数据集成平台，面向实时和离线数据采集、集成、管理，支持多源采集、零侵入式实时同步、ETL / ELT 和 API 化数据服务。
- `FineReport` 是报表制作、分析和展示工具，适合中国式复杂报表、交互分析、数据录入、权限管理、定时调度、打印输出和门户 / 移动应用。

### 对 Foundry 的落地含义

1. Foundry 借鉴 FineBI 的指标、问数、钻取和刷新机制；企业已有可授权接口时可复用其指标资产。[问数据](https://help.fanruan.com/finebi/doc-view-2580.html)、[普通钻取](https://help.fanruan.com/finebi/doc-view-133.html)
2. 多源同步可对接企业已有集成设施，FineDataLink 是可选产品，不是 Foundry 的必需组件。[产品简介](https://help.fanruan.com/finedatalink/doc-view-2.html)
3. 固定版式、填报和打印可参考 FineReport 的工作方式；首期不新增该外部依赖。[产品简介](https://help.fanruan.com/finereport/edition-view-46048-0.html)

### 公开资料能确认的刷新与增量能力

- `数据更新规范` 明确说明：如果使用抽取版本，需要做数据更新；常见策略是全量 / 增量更新。
- 文档明确提到：当表有可用的时间戳字段且历史数据不变时，优先考虑增量更新；增量删除时要尽量只 select 唯一区分字段。
- 更新策略可以做成全局定时更新 + 特殊文件夹定时更新 + 特殊单表定时更新。
- `FineDataLink` 文档确认它支持多源数据采集、实时同步、API 构建数据资产、任务调度监控，以及时间戳、触发器、全表同比、全表比对增量装载、日志解析等多种同步方式。

### 公开资料能确认的产品能力边界

- `FineBI` 主要负责“分析”和“问数”，不是“把账套的事务对象本身搬进来”。
- `FineDataLink` 负责“接入与同步”，不是最终报表呈现。
- `FineReport` 负责“复杂报表与填报”，不是自助分析主平台。

### 对 Foundry 的现实建议

1. Foundry 优先借鉴 FineBI 的指标、问数与下钻交互；企业已有资产时再考虑接口复用。
2. 固定格式报告可参考 FineReport，但不将它列为 Foundry 必须采购或部署的组件。
3. 对“增量刷新”这件事，FineBI / FineDataLink 的公开文档都已经给出明确规则，但最终仍要按数据源的时间戳、主键和历史可变性设计。
4. 如果你的数据源本来就能通过 ERP 接口直连 FineBI，不要先假设一定得经过 `FineDataLink`。

## 4. 接入优先级建议

从“能稳定拿到真实账套数据”这个目标出发，建议按下面的顺序判断：

1. **有明确开放平台和对象清单的 ERP 先接。** 典型是用友 U8 的公开对象与分页 / 明细接口。
2. **金蝶先走星辰自己的官方开放平台与租户授权。** 本轮确认产品入口与开放入口；社区授权线索、具体对象与权限仍待目标租户核验。
3. **帆软和 YonGPT 都不应被写成 Foundry 的强制前置依赖。** 前者可借鉴问数、下钻与刷新机制，后者保留为 AI 能力方向。

## 5. 待验证清单

- 金蝶 AI 星辰租户里是否开放到 Foundry 需要的科目余额、辅助核算、分录级下钻对象。
- 金蝶 `open.jdy.com` 中是否存在更完整的星辰 API 目录页可直接公开核实。
- 金蝶不同版本 / 套餐对 API 服务、开发平台和对象权限的开放范围。
- 用友 U9 / NC / NCC 在目标租户里，是否有与 U8 同等粒度的公开对象；公开网页目前只足够确认平台级能力。
- 帆软场景里，是否已经有可用于增量更新的稳定时间戳字段、主键和数据变更日志。

## 6. 来源表

| 产品 | 官方来源 | 公开确认的要点 |
|---|---|---|
| 金蝶 AI 星辰 | [金蝶AI星辰](https://www.jdy.com/star/) | 财税管理、智能凭证、应收应付、出纳管理、多维会计核算、智能分析、成本核算、经营分析、库存管理 |
| 金蝶 AI 星辰 | [金蝶小微企业api接口-财务_进销存_供应链_PaaS平台](https://www.jdy.com/ecology/api/) | API 服务、开发平台、开放能力入口 |
| 金蝶 AI 星辰 | [小微生态门户-首页](https://open.jdy.com/) | 官方开放平台入口；搜索摘要可见标准 API 接口、苍穹开发平台能力与 SDK |
| 金蝶 AI 星辰 / 授权线索 | [购买了两套星辰，新购的星辰没有办法选择对应的账套](https://vip.kingdee.com/questions/835531442419017728) | 社区答复称按账套绑定；作者身份及现行政策待核 |
| 金蝶 AI 星辰 / 客户端 | [客户端下载](https://www.jdy.com/clientdownload/) | 星辰及精斗云产品的客户端入口；再次确认 API 服务、开发平台与帮助中心入口 |
| 用友 YonGPT / YonBIP | [用友YonGPT](https://www.yonyou.com/YonBIP/product/YonGPT/) | 企业级 AI 大模型，集成于 YonBIP |
| 用友 YonGPT / 场景 | [YonGPT](https://www.yonyou.com/subject/gd-YonGPT) | 财务、供应链等场景，智能运营、业务洞察、决策支持 |
| 用友 OpenAPI | [Open API开放平台_接入文档](https://developer.yonyou.com/openAPI) | NC/NCC OpenAPI、API 生命周期、安全管控、预置产品服务 |
| 用友 API 网关 | [API网关_API全生命周期管理](https://developer.yonyou.com/product/integrated/apigateway) | 创建 / 发布 / 运行 / 下线 / 测试、统一授权调用、NC/NCC 预置 |
| 用友 U8 | [用友U8开放平台](https://u8open.yonyou.com/) | 基础档案、凭证、存货、采购等几十个接口 |
| 用友 U8 | [API中心](https://u8open.yonyou.com/apiCenter/index) | 总账、库存、销售、采购、应收应付、预算等分类 |
| 用友 U8 | [system/token](https://u8open.yonyou.com/apiCenter/tokenGet) | 认证参数；目标租户期限与配额待核 |
| 用友 U8 | [voucherlist/batch_get](https://u8open.yonyou.com/apiCenter/voucherlist_batch_get) | 分页凭证列表 |
| 用友 U8 | [voucherdetaillist/batch_get](https://u8open.yonyou.com/apiCenter/voucherdetaillist_batch_get) | 凭证明细、辅助核算、分录下钻 |
| 用友 U8 | [accountsum/batch_get](https://u8open.yonyou.com/apiCenter/accountsum_batch_get) | 科目总账、期初 / 发生 / 期末、外币、数量 |
| 用友 U8 | [accountass/batch_get](https://u8open.yonyou.com/apiCenter/accountass_batch_get) | 辅助总账、部门 / 人员 / 客户 / 供应商 / 项目维度 |
| 用友 U8 | [period/batch_get](https://u8open.yonyou.com/apiCenter/period_batch_get) | 会计期间、账套号、年度 |
| 帆软 FineBI | [FineBI产品优势](https://help.fanruan.com/finebi/doc-view-1779.html) | 智能问数、探索分析、管理驾驶舱、指标看板、接口协议 / ERP 数据源对接 |
| 帆软 FineBI | [问数据](https://help.fanruan.com/finebi/doc-view-2580.html) | 智能模式 / 极速模式、多轮对话、主题/字段确认、业务规则记忆 |
| 帆软 FineBI | [普通钻取](https://help.fanruan.com/finebi/doc-view-133.html) | 页面内逐级下钻、固定或不固定下钻顺序 |
| 帆软 FineBI | [智能问答后端开放集成说明](https://help.fanruan.com/finebi/doc-view-2640.html) | 问数功能可通过接口调用嵌入自由系统，共创式开放能力 |
| 帆软 FineBI | [AI诊断](https://help.fanruan.com/finebi/doc-view-2625.html) | 默认采样为单组件 100/20 行、合计 1000 行 15 列，可配置 |
| 帆软 FineBI | [数据更新规范](https://help.fanruan.com/finebi/doc-view-1823.html) | 全量 / 增量更新、抽取版更新、更新时间策略 |
| 帆软 FineDataLink | [FineDataLink产品简介](https://help.fanruan.com/finedatalink/doc-view-2.html) | 一站式数据集成、零侵入实时同步、ETL / ELT |
| 帆软 FineReport | [FineReport产品简介](https://help.fanruan.com/finereport/edition-view-46048-0.html) | 报表制作、分析和展示、复杂报表 |

## 7. 这版研究的可直接复用结论

Foundry 如果要补强“真实账套 / ERP 管理报表”能力，核心不是采购替代，而是把“账套接入”和“分析问数”拆开：上游先按账套和对象粒度接真实账务，下游借鉴 FineBI 的问数、下钻、指标与刷新机制；如果现场已经有帆软资产，可按权限复用。`YonGPT` 只保留为可借鉴的 AI 能力方向，不把它写成本次已验证的直连接口。对金蝶和用友的其他产品线，不要先问“能不能一把打通”，先问“公开文档确认了哪些对象、哪些分页与明细粒度、哪些授权前提”，再决定是否需要租户级验证。
