---
name: cash
description: Route cash, receivables and collection questions. Use when the manager asks about aging, whether cash will run out, collection rates, the break-even collection rate, DSO, impairment eating gross profit, renewal exposure or which city companies to look at first. Use finance_scenario_save/run for receivables_aging, cash_13_weeks and collection_health, and finance_controls_save for formula checks; do not invent payment or posting tools.
---

# /cash

Use this pack to **route** cash and collection questions onto scenario and control tools.

## When to load

- The manager asks for receivables aging.
- The manager asks whether cash covers the next 13 weeks.
- The manager asks how collection is going: the collection rate against the break-even line, days of receivables, how much impairment ate, which units or contracts carry the risk, or what the full year looks like.

Do **not** refuse `finance_scenario_save` / `finance_scenario_run` because this pack was not loaded.

## Suggested path

1. Save a scenario with `kind=receivables_aging`, `kind=cash_13_weeks` or `kind=collection_health`.
2. Run the saved scenario.
3. Drill into `rows`, `detail_rows`, or `excluded_detail_rows` as needed.

There is no payment, posting, or bank-send tool. Do not invent one.

## Collection health (collection_health)

Formulas live in the engine; you only pick cells. Bind the month-close workbook's tables, then name each input as a cell (match on the label column, or source_row) or a ledger sum (sum_where, with the same require_columns on both sides of a rate). Use entity_tables to run every row of a city-company sheet. A bare number is a manual input and is marked so.

| Question | Metric | Formula |
| --- | --- | --- |
| Does collection cover cash costs? | break-even collection rate, gap | 1 − gross margin + expense ratio; collection rate − break-even |
| How long is money out? | DSO | (AR + contract assets) ÷ trailing-12-month revenue × 365; TTM = last full year − last year to date + this year to date (estimate) |
| Do the books agree with the reported rate? | implied collection | 1 − (AR increase + impairment) ÷ (revenue × 1.06) |
| Did revenue turn into cash? | cash collection ratio | cash received from sales ÷ (revenue × 1.06) |
| How much did impairment eat? | impairment to gross profit, provision ratio, aging over 1 year, related-party share | as named |
| What does the full year look like? | full year at last year's pace, gap to LE | year to date ÷ (last year to date ÷ last full year) |
| Where is the scale going? | area growth and exits, renewal exposure, exiting vs staying collection, per-head figures | as named |
| Which units first? | risk radar score | seven screening signals, listed on the row |

Read the result this way:

- The default collection rate is the current-year billing rate (本年账单收缴率); the rate including arrears (综合收缴率) sits beside it and reads higher.
- Red, orange, yellow and green are screening hints, not conclusions. The risk radar never counts in the close.
- Never state a full year as year to date × 12 ÷ months; that row is a comparison only. Use the at-pace figure or the manager's LE, and call it an estimate.
- Industry benchmarks in the pack (13·行业对标) are side evidence only; do not compute or conclude from them.
- Rows marked 估算 stay estimates in the draft.

## Formula checks in the close

To make the pack check itself, save a control with `finance_controls_save` and `kind=formula`: signed_sum for the AR roll-forward (年初 + 新增 − 收回 − 核销 = 期末), dso to recompute the reported turnover days, implied_collection to compare the AR movement with the reported rate. They are saved as proposed; only the manager's confirmation counts them in the close.

## Standard output

An aging table, a 13-week cash view, or a collection-health run with formula, light, estimate flag and source cells on every row, bound to authorized snapshots.
