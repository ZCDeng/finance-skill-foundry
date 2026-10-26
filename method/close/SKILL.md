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

For F02–F05 month close, accruals, reconciliation and balance rollforwards, read
[close-checklist.md](../close-checklist.md) with
`method-resource {skill: "close", resource: "close-checklist.md"}` before calculations.
Read [accounting-basis.md](../accounting-basis.md) with
`method-resource {skill: "close", resource: "accounting-basis.md"}` for policy-sensitive
work and [model-checks.md](../model-checks.md) with
`method-resource {skill: "close", resource: "model-checks.md"}` for check coverage.

## Suggested path

1. Optionally call `finance_readiness` if scope or mapping is still unclear.
2. If readiness is `blocked` with `reason=mapping_incomplete`, call `finance_map_save` before expecting `can_run` to include `management_pnl`.
3. Load `financial-statements` for management P&L and `control_totals`.
4. Load `reconciliation` for tick-and-tie.
5. Load `journal-entry` only for **drafts**. Foundry does not post.
6. Load `variance-analysis` when the close question includes actual vs budget.
7. Reuse `finance_controls_save`, `finance_controls_run` and `finance_controls_list` for
   scoped formula/tie-out checks. Assistant-created controls remain proposed until
   the existing manager confirmation path applies; do not count them as approved.
8. Preserve material open issues with owner, due date, dependency, source locator and
   next action. A manager disposition keeps the original difference visible; it does
   not rewrite arithmetic or remove the need to recheck changed sources/rules.
9. Deliver the current close workpaper and editable adjustment drafts. Do not equate
   a saved draft, completed checklist or archive with statutory approval.

Before calculation, register the complete original requirements successfully, then bind every required source in the finance context. Keep purpose in the question unless it is a real source dimension. Use native control/account totals with the registered identity; resolve a registration or context error before running diagnostics. If the requirements change, rerun affected diagnostics and prepare/save only the current run set. A nonterminal save requires a fresh verified save after repair.

## Recognition evidence before adjustment drafts

Treat service completion, reconciliation arithmetic, accounting recognition and
posting authorization as separate checks. `service_completed=yes` without
received/provided direction, economic nature, period and account evidence is not
a basis for a definite expense/liability entry. Preserve the measured difference
and name the missing facts. Pending approval does not negate a supported
obligation, and a received service may require asset rather than expense
recognition. Keep proposed adjustments conditional until their basis is verified.

## Standard output

Management P&L, control totals, reconciliation notes, and journal drafts tied to authorized snapshots. Not a live ledger close.
