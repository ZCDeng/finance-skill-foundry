---
name: cash
description: Route cash and receivables questions. Use when the manager asks about aging or whether cash will run out. Use finance_scenario_save/run for receivables_aging and cash_13_weeks only; do not invent payment or posting tools.
---

# /cash

Use this pack to **route** cash questions onto scenario tools.

## When to load

- The manager asks for receivables aging.
- The manager asks whether cash covers the next 13 weeks.

Do **not** refuse `finance_scenario_save` / `finance_scenario_run` because this pack was not loaded.

## Suggested path

1. Save a scenario with `kind=receivables_aging` or `kind=cash_13_weeks`.
2. Run the saved scenario.
3. Drill into `rows`, `detail_rows`, or `excluded_detail_rows` as needed.

There is no payment, posting, or bank-send tool. Do not invent one.

## Standard output

An aging table or a 13-week cash view bound to authorized snapshots.
