# Excel 与外部助手的实现依据

调研日期：2026-09-06。以下是官方技术文档确认的基础能力，不代表 Foundry 已实现或已在真实 Excel／第三方助手验收。

## Excel：两种交付等级

**文件往返**：读取源工作簿中的表格或命名区域，冻结此次输入，生成独立结果工作簿或受约束的模板副本。这适合先补强现有能力，但不等于原工作簿内在线刷新。openpyxl 的 `data_only` 读取 Excel 上次保存的公式缓存值；它对工作簿对象的读写覆盖也有限，不能据此承诺任意复杂工作簿无损往返。[openpyxl Tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html)

**Excel 内持续协作**：由 Excel 插件绑定范围、读写结果，让 Excel 负责工作簿计算与保存。Office Add-ins 支持 Excel 的 Windows、Mac、Web 等宿主，可访问工作表、区域、表、图表和命名对象；这一跨平台能力不意味着每个 API 在所有宿主版本可用。[Microsoft：Excel Add-ins overview](https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-overview)

文档支持将绑定保存于文件并跨会话访问，绑定对象可指向命名区域或表。由此推导 Foundry 的设计：保存 workbook identity、table／named range、输入输出角色、指标／情景 ID 和上次刷新版本，避免只存易漂移的坐标。[Microsoft：Bind to regions](https://learn.microsoft.com/en-us/office/dev/add-ins/develop/bind-to-regions-in-a-document-or-spreadsheet)

Excel API 能设置计算模式和请求重算。Foundry 可以将“写入输入→宿主重算→读取结果→冻结分析输入”的链路交给 Excel；这只是可行实现方向，需要独立验证公式、外链和具体工作簿的行为。[Microsoft：Manage Excel workbooks](https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-workbooks)

实施前要选定最小 API requirement set 并做运行时能力判断，不能只写“支持 Mac”。宿主版本不具备所需功能时退回文件工作流，同时明确能力差异。[Microsoft：Specify Office hosts and API requirements](https://learn.microsoft.com/en-us/office/dev/add-ins/develop/specify-office-hosts-and-api-requirements)

**方案判断**：先形成可数值计算的输出、稳定绑定合同和刷新冲突规则；随后独立验证 Office.js 插件。当前没有依赖变更授权，不在此次规划中安装 Office.js、插件脚手架或额外服务。未来如选择插件路线，依赖清单、部署位置、本机／HTTPS 通道与 Excel 实测是该阶段的前置决策，不作为已经完成的事项。

## MCP：工具暴露与财务语义是不同问题

MCP 的 HTTP 授权规范规定客户端资源标识、令牌受众和权限范围处理。使用 MCP 不会自动建立 Foundry 的账套／任务边界，也不会替产品决定具体财务工具。[MCP Authorization，2025-11-25 版本](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

**方案判断**：Foundry 对外可优先暴露列数据、查询指标、下钻、情景计算和读取依据；这些工具复用内部同一计算与数据服务。外部助手只是另一个交互入口。写工作簿专用结果区域、写分析草稿、修改预算假设属于可配置的工作权限；正式过账或支付以后由独立业务域实现。不能因信任用户就把凭据传入任意模型脚本，也不能因增加接口就要求经理每次查询重复确认。

## 来源与证据强度

| 来源 | 类型／日期 | 本次支持的结论 | 未证明的事情 |
|---|---|---|---|
| [openpyxl Tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html) | 官方技术文档；页面版本显示 3.1.3，访问 2026-09-06 | 缓存读取、对象保留边界 | Foundry 对任意 Excel 文件无损编辑 |
| [Excel Add-ins overview](https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-overview) | 官方技术文档；页面标注更新 2026-06-16，访问 2026-09-06 | 多宿主插件与读写能力 | 本机已经部署插件或跨平台功能全等 |
| [Bind to regions](https://learn.microsoft.com/en-us/office/dev/add-ins/develop/bind-to-regions-in-a-document-or-spreadsheet) | 官方技术文档；访问 2026-09-06 | 持久范围绑定 | 业务级冲突合并、账套映射 |
| [Manage Excel workbooks](https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-workbooks) | 官方技术文档；访问 2026-09-06 | 宿主计算控制 | 任意公式／外部连接计算结果正确 |
| [API requirements](https://learn.microsoft.com/en-us/office/dev/add-ins/develop/specify-office-hosts-and-api-requirements) | 官方技术文档；访问 2026-09-06 | API 版本与宿主支持条件 | WPS 兼容性 |
| [MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | 官方协议规范；版本 2025-11-25，访问 2026-09-06 | HTTP 授权的协议要求 | 第三方产品的商业授权、Foundry 工具语义和数据准确性 |
