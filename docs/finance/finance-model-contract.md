# Finance Model Contract

This is the stage 1 pure finance contract for parent services. It does not own persistence, UI state, mapping approval, ERP refresh, posting, or payment execution.

## Normalization

`normalize_finance_dataset(dataset: dict, scope: dict, account_map: dict | list[dict] | None = None, policy: dict | None = None) -> dict`

The input `dataset` is the JSON-friendly shape returned by `AnalysisStore.read_dataset`: `id`, `rows`, `schema`, `metadata`, hashes, and source metadata. The function is pure and can also accept test dictionaries with the same `rows` field.

`scope` filters and preserves the finance identity fields. If a row lacks a scoped field, the explicit scope still defines the analysis boundary; if a row has a conflicting value, it is filtered out. `scope.unit` can also name the target reporting unit when `policy.target_unit` is used, so source rows in `元` can convert into a `万元` scope without being discarded.

- `ledger`
- `organization`
- `period`
- `currency`
- `unit`
- `scenario`

`policy.field_map` or `policy.source_mappings` can map source columns to canonical fields. Built-in mappings cover the current fixture names, including account code, account direction, management account, amount, debit/credit flag, posting status, line type, source row, and common auxiliary columns.

The result shape is:

- `domain`: namespaced input/output contract and explicit exclusion of posting/payment execution.
- `dataset_id`, `scope`, `provenance`.
- `rows`: normalized facts with `dataset_id`, `source_row`, `source`, finance identity fields, leading-zero account code as text, management account, original and converted amount strings, debit-positive signed amount string, auxiliary dimension values, voucher drilldown availability, and trace fields.
- `diagnostics`: warnings/errors/info with stable `code`.
- `control_totals`: grouped by ledger, organization, period, currency, unit, scenario, and management account. Totals remain split by currency and unit.
- `movement_checks`: G5-style opening + period activity = ending checks in debit-positive signed terms.

Amounts stay as exact Decimal-derived strings at the public boundary. `元` and `万元` conversion is explicit through `policy.target_unit` or `scope.unit`; unsupported conversions are diagnostics. Mixed currencies or units are diagnosed unless the scope filters them or the policy explicitly allows them.

Account maps may be versioned dictionaries with `rows` or a list of row dictionaries. Duplicate mappings, parent-child overlaps, and unmapped accounts are diagnostics. `policy.manager_mappings` can select a manager-chosen mapping for this run; the parent service persists mapping versions and old reports continue to reference their prior version.

Rows without voucher keys remain usable for balance-level analysis. They set `drilldown_available: false` and emit `voucher_detail_unavailable`; no voucher links are fabricated.

## Metrics

`evaluate_metric(normalized: dict, spec: dict) -> dict`

The first stage supports deterministic metric evaluation over normalized rows:

- `management_pnl`: groups by ledger, organization, period, requested dimensions, scenario, currency, and unit by default; computes revenue, cost, expense, and profit with explicit `scenario_bindings` for actual/budget/forecast.
- `ratio`: recomputes the ratio from numerator and denominator accounts. It does not average or sum stored ratios, and it keeps the same default finance identity partition.
- `account_total`: sums account totals by finance identity, scenario, currency, and unit, except stock accounts declared in `account_behavior` are returned by period when period is not already a dimension.
- `control_totals`: returns the normalization control totals.

Every result row carries `source_rows` evidence, and management P&L includes per-result evidence for revenue, cost, expense, and profit. The evaluator works on pre-normalized rows and does not perform joins, so parent integration should preaggregate relationship inputs before calling it when source tables have different grains.

If a manager intentionally wants a cross-ledger, cross-organization, or cross-period aggregate, the metric spec must set `aggregate_dimensions: true` and name the desired dimensions explicitly.

All outputs remain namespaced as finance analysis outputs. Management adjustments, scenario edits, voucher drafts, posted entries, and payments are separate future domains.
