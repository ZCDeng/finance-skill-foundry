---
name: setup
description: Route a new finance-manager analysis session. Use when the manager asks whether uploaded files can produce management P&L, what period/currency/mapping is missing, or how to start close/variance/cash work. Suggest finance_readiness first; do not treat this pack as a gate for run_metric.
---

# /setup

Use this pack to **route** a file-first session. It does not add posting, payment, or ERP connection.

## When to load

- The manager asks whether this batch of files can produce management P&L.
- Scope, mapping, or sheet choice is unclear after files are already authorized on the task.

Do **not** refuse `run_metric`, `explain_variance`, or the four method skills because this pack was not loaded.

## Suggested first tool

Call `finance_readiness` (no need to load this pack first). The report is read-only: it does not write snapshots or finance context.

When it reports `pending_structure`, the files are loaded but nobody has said what
the tables in them are yet. Read `structure_proposal_list`, tell the manager what
the engine made of each sheet — which row is the header, which column is the
amount, which rows are subtotals — and confirm with `structure_proposal_confirm`
only on her word. Say that a confirmation you submit is hers to acknowledge. If a
debit/credit side is undecided, ask her which side carries the amount; guessing
changes the numbers.

Interpret the report as:

- `can_run` — capabilities that already have declared period/currency and required mapping.
- `blocked` — named missing fields or `mapping_incomplete` / `identity_failed` / `no_dataset`.
- `proposed_scope` — values declared on the files. Never fill 本月 or a currency that the files did not declare.
- `erp_connected` — false unless this session has a named, authorized adapter. File exports are not a live ledger connection.

If header identity fails on an ERP-style export, say the files are not ready for management P&L. Do not claim the English field names are enough.

## Next skills

After readiness, load only what the question needs:

- Close / statements / journals → `close` or `financial-statements` / `reconciliation` / `journal-entry`
- Budget variance → `bva` or `variance-analysis`
- Aging or 13-week cash → `cash`

## Standard output

A readiness report the manager can act on: what can run, what is blocked, and which existing skill to load next.
