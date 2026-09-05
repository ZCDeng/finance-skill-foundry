# Finance baseline fixtures

This folder holds deterministic finance-analysis fixtures for r2 stage 0 sample preparation. `cases.json` is reserved for live model-session cases and is not changed by this baseline set.

The baseline set has three synthetic company scenarios:

- `service_ledger.csv` / `service_budget.csv`: service company management P&L, budget bridge, prior-period comparison, AR aging, cash delay, and multi-organization controls.
- `commerce_ledger.csv` / `commerce_budget.csv`: goods sales company price/quantity bridge, unit policy, and inventory-like cost lines.
- `multi_org_ledger.csv` / `account_map_conflicts.csv`: organization, currency, unit, debit/credit direction, duplicate/change/delete, and mapping-conflict inputs for future A01-A09 tests.
- `g5_account_movements.csv`: same-account opening + period debit - period credit = ending examples, credit-normal signed policy, red-letter, closing-transfer, adjustment-period, and unposted rows.
- `g6_source_identity.csv`: same voucher with multiple lines, same document number across ledgers, duplicate pull, changed row, and deleted row examples.

Expected truth values live in `expected_truth.json`. These files intentionally stay as source fixtures and do not implement a future finance domain model.

Current boundary: this is sample preparation, not implementation of A01-A09 tests. G1/G2 have exact truth rows. G3 has a simple cash-delay input. G4 includes overdue and not-yet-due receivables; subsequent receipt, partial write-off, and credit memo cases remain out of this stage-0 slice. G5 and G6 now have the minimum static rows needed for their stage-0 edge inputs.
