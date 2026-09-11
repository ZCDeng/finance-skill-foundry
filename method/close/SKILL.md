---
name: close
description: Route period close. Use when the manager asks to close the books, produce management P&L, tick-and-tie, or draft journals from already authorized files. Load existing statement, reconciliation, and journal skills; do not gate run_metric on this pack.
---

# /close

Use this pack to **route** close work. It does not post, pay, or connect an ERP.

## When to load

- The manager asks to close a period or produce management P&L from files already on the task.
- Tick-and-tie or journal drafts are part of the same close question.

Do **not** refuse `run_metric` or the four method skills because this pack was not loaded. If close is missing, keep using `financial-statements`, `reconciliation`, `journal-entry`, SQL, and Python.

## Suggested path

1. Optionally call `finance_readiness` if scope or mapping is still unclear.
2. If readiness is `blocked` with `reason=mapping_incomplete`, call `finance_map_save` before expecting `can_run` to include `management_pnl`.
3. Load `financial-statements` for management P&L and `control_totals`.
4. Load `reconciliation` for tick-and-tie.
5. Load `journal-entry` only for **drafts**. Foundry does not post.
6. Load `variance-analysis` when the close question includes actual vs budget.

## Standard output

Management P&L, control totals, reconciliation notes, and journal drafts tied to authorized snapshots. Not a live ledger close.
