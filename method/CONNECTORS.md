# Connectors

Extracted from Anthropic's finance plugin in knowledge-work-plugins. Licensed Apache-2.0.

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `~~data warehouse` might mean Snowflake, BigQuery, or any other warehouse with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (data warehouse, chat, project tracker, etc.) rather than specific products. This Foundry package does not ship a configured upstream `.mcp.json`, connector service, ERP tenant, or data-warehouse credential. A placeholder becomes usable only when the current session or installed app explicitly configures that service.

## Connectors for this plugin

| Category | Placeholder | Foundry status | Examples outside this package |
|----------|-------------|----------------|-------------------------------|
| Data warehouse | `~~data warehouse` | Placeholder only; no bundled connection | Snowflake, Databricks, BigQuery, Redshift, PostgreSQL |
| Email | `~~email` | Placeholder only; no bundled connection | Microsoft 365 |
| Office suite | `~~office suite` | Placeholder only; no bundled connection | Microsoft 365 |
| Chat | `~~chat` | Placeholder only; no bundled connection | Slack, Microsoft Teams |
| ERP / Accounting | `~~erp` | Placeholder only; no bundled connection | NetSuite, SAP, QuickBooks, Xero |
| Analytics / BI | `~~analytics` | Placeholder only; no bundled connection | Tableau, Looker, Power BI |

File uploads, registered datasets, SQL/Python runs, and saved drafts are the available local Foundry path when no connector is configured.
