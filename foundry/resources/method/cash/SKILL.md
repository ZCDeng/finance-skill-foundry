---
name: cash
description: Route cash, receivables and collection questions. Use when the manager asks about aging, whether cash will run out, collection rates, the break-even collection rate, DSO, impairment eating gross profit, renewal exposure or which city companies to look at first. Use finance_scenario_save/run for receivables_aging, cash_13_weeks and collection_health, and finance_controls_save for formula checks; do not invent payment or posting tools.
---

# /cash

Use this pack to **route** cash and collection questions onto scenario and control tools.

## Before the first calculation in this session

In the current session, successfully read both resources before starting any financial
calculation (`analysis-run`, `analysis-script`, `analysis-script-start`, `run_metric`,
`explain_variance`, or `finance_scenario_run`):

1. `method-resource {skill: "cash", resource: "FOUNDRY.md"}`
2. `method-resource {skill: "cash", resource: "model-checks.md"}`

Wait for both calls to return successfully and read their content. If either read fails,
resolve the failure before calculating. Loading this skill or reading resources in another
session does not satisfy these steps. A later read does not repair a calculation already
started without them. Continue the analysis after these reads; no manager approval is needed.

## When to load

- The manager asks for receivables aging.
- The manager asks whether cash covers the next 13 weeks.
- The manager asks how collection is going: the collection rate against the break-even line, days of receivables, how much impairment ate, which units or contracts carry the risk, or what the full year looks like.

Do **not** refuse `finance_scenario_save` / `finance_scenario_run` because this pack was not loaded.

Read [close-checklist.md](../close-checklist.md) with
`method-resource {skill: "cash", resource: "close-checklist.md"}` for F07 receivables
coverage and loss-policy limits, and [forecast-models.md](../forecast-models.md) with
`method-resource {skill: "cash", resource: "forecast-models.md"}` for F08 dated cash
events and stress scenarios. For financial checks read [model-checks.md](../model-checks.md)
with `method-resource {skill: "cash", resource: "model-checks.md"}` before calculation.
Policy-sensitive work additionally reads [accounting-basis.md](../accounting-basis.md)
with `method-resource {skill: "cash", resource: "accounting-basis.md"}`.

## Suggested path

1. Save a scenario with `kind=receivables_aging`, `kind=cash_13_weeks` or `kind=collection_health`.
2. Run the saved scenario.
3. Drill into `rows`, `detail_rows`, or `excluded_detail_rows` as needed.

There is no payment, posting, or bank-send tool. Do not invent one.

## Collection health (collection_health)

Formulas live in the engine; you only pick cells. Bind the month-close workbook's tables, then name each input as a cell (match on the label column, or source_row) or a ledger sum (sum_where, with the same require_columns on both sides of a rate). Use entity_tables to run every row of a city-company sheet. A bare number is a manual input and is marked so. Set sensitivity to true on an entity to get the break-even grid; it needs an expense ratio.

### From collection components to a checked explanation

When the question asks for current-year and comprehensive collection rates, use the
native component calculation below. Inspect the registered source columns first;
read amounts from their bound cells instead of copying them into a script or a manual input.
Keep the requested organization, period, currency and source scope throughout.

1. Bind the selected registered datasets with `finance_context_save`. Use the returned
   `context_id` in `analysis_requirements_save` **before** running a calculation. This
   copies the context's source bindings into the requirements. Do not omit both
   `context_id` and `bindings`; an unbound requirement has no verified semantic fingerprint.
2. Register the two rates as distinct items. Both have `metric: "ratio"`; pin their
   actual result identity in `dimensions.metric_key`, as below. The generic type
   `ratio` is not a replacement for either result's metric key.

   ```json
   {"context_id":"RETURNED_CONTEXT_ID","question":"THE_CURRENT_USER_QUESTION",
    "items":[
      {"id":"current_rate","metric":"ratio","label":"本年账单收缴率",
       "dimensions":{"metric_key":"collection_rate_current"},"requires_drilldown":true},
      {"id":"total_rate","metric":"ratio","label":"综合收缴率",
       "dimensions":{"metric_key":"collection_rate_total"},"requires_drilldown":true}
    ]}
   ```

   Confirm the saved requirement has source `bindings` and a nonempty
   `semantic_fingerprint`. If it does not, correct the binding with a new requirement
   version referencing `parent_id`, then calculate under that version.
3. Save `kind: "collection_health"` with the same `context_id`. Under
   `inputs.entities[].values`, bind these amount inputs using the inspected source:

   | Input | Meaning |
   | --- | --- |
   | `current_due` | 本年账单应收 |
   | `current_collection` | 对本年账单的收回 |
   | `opening_ar` | 期初往年欠款 |
   | `arrears_collection` | 对期初往年欠款的收回 |

   Each input is a cell reference such as
   `{"alias":"BOUND_ALIAS","match":{"SOURCE_LABEL_COLUMN":"SOURCE_LABEL"},"column":"SOURCE_AMOUNT_COLUMN"}`.
   Use the source's real labels and units; missing components are not zero.
   The engine computes `collection_rate_current = current_collection / current_due`
   and `collection_rate_total = (current_collection + arrears_collection) / (current_due + opening_ar)`.
4. Call `finance_scenario_run` once with the saved `scenario_id`. Reuse the successful
   run. Its two rows retain those metric keys, `scenario: "本期"`, and `unit: "ratio"`;
   `value` is an exact fraction and `display_value` is its percentage display. A missing
   or zero denominator produces a diagnostic, not a substitute rate.
5. Call `prepare_explanation` for that run; select each requested row's `value` fact.
   Call `drilldown_fact` for the two result rows to verify the archived component cells.
   Explain the two formulas in words. For percentage text, cite the exact fraction
   with a calculation claim containing `run_id`, `row`, `column: "value"`, `value`,
   `fact_id` and `presentation: {"decimal_places": 2, "scale": "percent", "rounding": "half_up"}`.
   Render that checked percentage in the body; retain the fraction in the claim.
   Do not invent an uncited percentage-point gap or repeat component amounts as
   uncited numbers. The two ratios alone do not establish a cash-safety conclusion.
6. Save with the current `requirements_id`, successful `run_ids`, and both calculation
   claims. Read the returned `quality` and persisted `completion`, then
   validate the saved `draft_id`. Completion requires the current source-bound
   requirements fingerprint and both distinct cited metrics. A saved draft, correct
   numbers, or a normal model stop alone is insufficient. If checks fail, repair the
   named issue within the existing repair limit; never rename both metrics to `ratio`
   or drop a required item to make coverage pass.

| Question | Metric | Formula |
| --- | --- | --- |
| What does a simplified operating-expenditure screen indicate? | estimated break-even collection rate, gap | 1 − gross margin + expense ratio; collection rate − break-even |
| How long is money out? | DSO | (AR + contract assets) ÷ trailing-12-month revenue × 365; TTM = last full year − last year to date + this year to date (estimate) |
| Do the books agree with the reported rate? | implied collection | 1 − (AR increase + impairment) ÷ (revenue × confirmed vat_factor), an estimate subject to movement and tax reconciliation |
| Did revenue turn into cash? | cash collection ratio | cash received from sales ÷ (revenue × confirmed vat_factor), on the same period and tax basis |
| How much did impairment eat? | impairment to gross profit, provision ratio, aging over 1 year, related-party share | as named |
| What does the full year look like? | full year at last year's pace, gap to LE | year to date ÷ (last year to date ÷ last full year) |
| Where is the scale going? | area growth and exits, renewal exposure, exiting vs staying collection, per-head figures | as named |
| Which units first? | risk radar score | seven screening signals, listed on the row |

Read the result this way:

- The default collection rate is the current-year billing rate (本年账单收缴率); the rate including arrears (综合收缴率) may be higher, lower, or equal. Preserve each numerator and denominator. A zero denominator is unavailable, not zero or 100%.
- Confirm the tax basis and vat_factor rather than adopting the legacy 1.06 default as policy. The engine applies one factor per run: split mixed-rate inputs into homogeneous runs or use a separately checked row-level calculation. Income 100 at 1.06 plus 100 at 1.13 corresponds to cash 219, not 212. Do not gross up an already tax-inclusive denominator.
- The break-even line, both gaps and its sensitivity grid are estimates of a simplified operating-expenditure screen. They assume common revenue/billing, tax and period bases and cash conversion of costs and expenses. Opening cash, old arrears, working capital, capital expenditure, debt service, taxes and restricted funds need a dated cash forecast. Revenue 100, margin 40% and expense ratio 10% give a 70% screening threshold; collections 70 less cash costs 60, expenses 10 and capex 50 still leave cash −50. The threshold cannot establish cash safety.
- Red, orange, yellow and green are screening hints, not conclusions. The risk radar never counts in the close.
- Never state a full year as year to date × 12 ÷ months; that row is a comparison only. Use the at-pace figure or the manager's LE, and call it an estimate.
- Industry benchmarks in the pack (an industry-benchmark sheet such as 行业对标与假设) are side evidence only; do not compute or conclude from them.
- Rows marked 估算 stay estimates in the draft.

### When the workbook's structure is not confirmed

Binding a workbook whose table structure waits on the manager is refused with `pending_structure`. Do not fall back to a script on your own: the engine's run is the one that lands on 经营分析 and feeds the break-even table, the sensitivity grid, the board's scenario and goal cards, 本月三句话 and next month's recompute. Ask with the point-and-pick question card whether to confirm the structure first (recommended: once, and next month's workbook of the same shape is taken up by itself) or draw a script draft now. To confirm, read `structure_proposal_list`, tell the manager what each sheet was read as, and submit with `structure_proposal_confirm` on her word; a confirmation waiting on her acknowledgement can already be bound, so run the engine next. For a draft, run `analysis-script` with `topic: collection_health`; it shows on 经营分析 as a script draft and counts nowhere else.

## Formula checks in the close

To make the pack check itself, save a control with `finance_controls_save`, `kind=formula`, a formula name, named input cells and the reported figure as the right side: formula signed_sum for the AR roll-forward (年初 + 新增 − 收回 − 核销 = 期末, each input with sign 1 or -1), dso to recompute the reported turnover days (tolerance in days), implied_collection to compare the AR movement with the reported rate (the rate as a decimal; scale 0.01 for a cell written in percent). They are saved as proposed; only the manager's confirmation counts them in the close.

## Standard output

An aging table, a 13-week cash view, or a collection-health run with formula, light, estimate flag and source cells on every row, bound to authorized snapshots.
