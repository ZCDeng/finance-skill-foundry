---
name: reconciliation
description: Reconcile accounts by comparing GL balances to subledgers, bank statements, or third-party data. Use when performing bank reconciliations, GL-to-subledger recs, intercompany reconciliations, or identifying and categorizing reconciling items. Do not use to post adjustments or initiate payments.
argument-hint: "<type> [period]"
---

# Reconciliation

> Extracted from Anthropic's `finance` plugin in [knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins/tree/main/finance/skills/reconciliation). Licensed Apache-2.0. This modified copy ships inside FA Foundry; see NOTICE.

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).
>
> When this skill runs inside finance-skill-foundry, also read [FOUNDRY.md](../FOUNDRY.md).
>
> Foundry runtime note: load this skill through the native skill tool, then read the companion notes with `method-resource {skill: "reconciliation", resource: "FOUNDRY.md"}` and `method-resource {skill: "reconciliation", resource: "CONNECTORS.md"}` when the trusted preset or session needs those rules. In analysis mode, use the current task datasets, multi-table SQL/Python, run records, and editable drafts; materiality, currency, accounting policy, and narrative judgment are manager-controlled and ordinary calculations do not require per-tool approval.

**Important**: This skill assists with reconciliation workflows but does not provide financial advice. All reconciliations should be reviewed by qualified financial professionals before sign-off.

Methodology and best practices for account reconciliation, including GL-to-subledger, bank reconciliations, and intercompany. Covers reconciling item categorization, aging analysis, and escalation.

## Foundry analysis mode

Start with `list_finance_context` to identify the registered ledgers, organizations, periods, source snapshots, account maps, and scenario bindings. If GL, bank, subledger, or intercompany files are current task uploads and not yet registered, use `finance_source_refresh` as a file-backed immutable snapshot. Use `file_identity_policy: "snapshot_only"` for ordinary balance or listing files without real document-line identifiers, and use `"business_key"` only for exports with genuine source keys. Bind the published snapshot and explicit scope with `finance_context_save` before relying on it.

Save the reconciliation requirements before calculation, including the account scope, required tie-outs, and requested drilldowns. Resolve registration errors first. Preserve every original source binding in the finance context, including recognition evidence that is not part of the arithmetic table. Use `control_totals` for full totals, or a real ledger account identity with account_total.accounts; generic amount results cannot replace a registered account identity. After any revision, rerun affected calculations before preparing and saving the same current run set. Use `run_metric` for control totals, account totals, and ratio checks that fit the finance metric contract. Use `drilldown_fact` only for source-backed cells from a saved run, and `save_explanation_draft` for the reconciliation narrative and exception support. Use `finance_scenario_save` / `finance_scenario_run` when a reconciliation depends on a named scenario such as an aging cut or cash-timing view. For receivables aging status cuts such as disputed or active invoices, use native `inputs.status_filter` with source/manager status mapping and inspect included or excluded invoices with `drilldown_fact.section`. Continue with SQL/Python for matching logic, exception aging, many-to-many joins, and reconciliations the finance tools do not model. Do not post entries, initiate payments, or claim actual ERP access unless a configured connector is named in the session.

For explanation quality, follow the analysis-mode explanation contract in `FOUNDRY.md`: prepare facts and automatic supporting tables from successful runs with `prepare_explanation`, draft with stable `fact_ids` and `{{fact:FACT_ID}}` value placeholders, then check the current text with `validate_explanation`. Use the returned `quality` and `completion` state for bounded repair: at most two targeted repair-and-check rounds, stopping on `no_progress`. Reuse only applicable scoped business context. Separate financial contributions from supported operational causes and manager judgment; preserve an editable draft when evidence is incomplete.

## Usage

```
/reconciliation <type> <period>
```

### Arguments

- `type` — The reconciliation type. One of:
  - `bank` — GL cash vs bank statement
  - `subledger` — GL control vs subledger (AR, AP, FA, inventory)
  - `intercompany` — Entity-pair receivable/payable that should eliminate
- `period` — The accounting period (e.g., `2024-12`, `2024-Q4`, `2024`)

## Reconciliation Types

### GL to Subledger Reconciliation

Compare the general ledger control account balance to the detailed subledger balance.

**Common accounts:**
- Accounts receivable (GL control vs AR subledger aging)
- Accounts payable (GL control vs AP subledger aging)
- Fixed assets (GL control vs fixed asset register)
- Inventory (GL control vs inventory valuation report)
- Prepaid expenses (GL control vs prepaid amortization schedule)
- Accrued liabilities (GL control vs accrual detail schedules)

**Process:**
1. Pull GL balance for the control account as of period end
2. Pull subledger trial balance or detail report as of the same date
3. Compare totals — they should match if posting is real-time
4. Investigate any differences (timing of posting, manual entries not reflected, interface errors)

**Common causes of differences:**
- Manual journal entries posted to the control account but not reflected in the subledger
- Subledger transactions not yet interfaced to the GL
- Timing differences in batch posting
- Reclassification entries in the GL without subledger adjustment
- System interface errors or failed postings

### Bank Reconciliation

Compare the GL cash balance to the bank statement balance.

**Process:**
1. Obtain the bank statement balance as of period end
2. Pull the GL cash account balance as of the same date
3. Identify outstanding checks (issued but not cleared at the bank)
4. Identify deposits in transit (recorded in GL but not yet credited by bank)
5. Identify bank charges, interest, or adjustments not yet recorded in GL
6. Reconcile both sides to an adjusted balance

**Standard format:**

```
Balance per bank statement:         $XX,XXX
Add: Deposits in transit            $X,XXX
Less: Outstanding checks           ($X,XXX)
Add/Less: Bank errors               $X,XXX
Adjusted bank balance:              $XX,XXX

Balance per general ledger:         $XX,XXX
Add: Interest/credits not recorded  $X,XXX
Less: Bank fees not recorded       ($X,XXX)
Add/Less: GL errors                 $X,XXX
Adjusted GL balance:                $XX,XXX

Difference:                         $0.00
```

### Intercompany Reconciliation

Reconcile balances between related entities to ensure they net to zero on consolidation.

**Process:**
1. Pull intercompany receivable/payable balances for each entity pair
2. Compare Entity A's receivable from Entity B to Entity B's payable to Entity A
3. Identify and resolve differences
4. Confirm all intercompany transactions have been recorded on both sides
5. Verify elimination entries are correct for consolidation

**Common causes of differences:**
- Transactions recorded by one entity but not the other (timing)
- Different FX rates used by each entity
- Misclassification (intercompany vs third-party)
- Disputed amounts or unapplied payments
- Different period-end cut-off practices across entities

## Reconciling Item Categorization

Before matching or drawing a cut-off conclusion, read [close-checklist.md](../close-checklist.md)
with `method-resource {skill: "reconciliation", resource: "close-checklist.md"}` for
F04/F05 coverage, duplicate keys and rollforward rules. Read [model-checks.md](../model-checks.md)
with `method-resource {skill: "reconciliation", resource: "model-checks.md"}` and
[accounting-basis.md](../accounting-basis.md) with
`method-resource {skill: "reconciliation", resource: "accounting-basis.md"}` for
applicable policy and evidence identity. Every input belongs in a matched or
unmatched set; those sets must reconstruct both source totals.

### Category 1: Timing Differences

Items already recorded in the GL can be bank timing differences when supported by
transaction evidence and the correct period cut-off:

- **Outstanding checks:** Checks issued and recorded in GL, pending bank clearance
- **Deposits in transit:** Deposits made and recorded in GL, pending bank credit
- **Interface delays:** inspect both records and cut-off; an interface delay alone does not establish correct period recognition

**Expected resolution:** Record the expected clearing date from the actual process
and follow up with subsequent settlement evidence. A valid outstanding cheque or
deposit already recorded correctly need not generate a duplicate GL adjustment.
Do not assign a universal clearing period or assume every timing difference needs
no adjustment. Subsequent clearance is evidence, not an automatic change to the
period-end recognition judgment.

A source flag such as `service_completed=yes` establishes operational completion
only. Before proposing accounting recognition, establish whether the entity
received or provided the service, its economic nature, contract or obligation,
period, and relevant GL account scope. A subledger/GL difference proves a
reconciliation difference; it does not by itself prove an expense, liability,
revenue, asset, or a missing journal entry. A received service may be an expense
or an asset depending on its nature and the applicable policy. Keep unresolved
direction or recognition facts visible; use conditional illustrations rather
than a definite debit/credit recommendation when those facts are absent.

An **unrecorded obligation** for a documented service received before period end
is a cut-off/accrual question when the obligation and appropriate account basis
are supported. Investigate the missing recognition and prepare an adjustment
draft for authorized review. When an item is pending approval, that status alone does not justify
omitting a supported expense, asset or liability; approval status governs the
authorized action and does not establish the economic substance. Foundry does
not post the adjustment.

### Category 2: Adjustments Required

Items that require a journal entry to correct:

- **Unrecorded bank charges:** Bank fees, wire charges, returned item fees
- **Unrecorded interest:** Interest income or expense from bank/lender
- **Recording errors:** Wrong amount, wrong account, duplicates
- **Missing entries:** Transactions in one system with no corresponding entry in the other
- **Classification errors:** Correctly recorded but in the wrong account

**Action:** Prepare adjusting journal entry to correct the GL or subledger.

### Category 3: Requires Investigation

Items that cannot be immediately explained:

- **Unidentified differences:** Variances with no obvious cause
- **Disputed items:** Amounts contested between parties
- **Aged outstanding items:** Items that have not cleared within expected timeframes
- **Recurring unexplained differences:** Same type of difference appearing each period

**Action:** Investigate root cause, document findings, escalate if unresolved.

## Aging Analysis for Outstanding Items

Track the age of reconciling items to identify stale items requiring escalation:

| Age Bucket | Status | Action |
|-----------|--------|--------|
| 0-30 days | Current | Monitor — within normal processing cycle |
| 31-60 days | Aging | Investigate — follow up on why item has not cleared |
| 61-90 days | Overdue | Escalate — notify supervisor, document investigation |
| 90+ days | Stale | Escalate to management — potential write-off or adjustment needed |

### Aging Report Format

| Item # | Description | Amount | Date Originated | Age (Days) | Category | Status | Owner |
|--------|-------------|--------|-----------------|------------|----------|--------|-------|
| 1 | [Detail] | $X,XXX | [Date] | XX | [Type] | [Status] | [Name] |

### Trending

Track reconciling item totals over time to identify growing balances:

- Compare total outstanding items to prior period
- Flag if total reconciling items exceed materiality threshold
- Flag if number of items is growing period over period
- Identify recurring items that appear every period (may indicate process issue)

## Escalation Thresholds

Define escalation triggers based on your organization's risk tolerance:

| Trigger | Threshold (Example) | Escalation |
|---------|---------------------|------------|
| Individual item amount | > $10,000 | Supervisor review |
| Individual item amount | > $50,000 | Controller review |
| Total reconciling items | > $100,000 | Controller review |
| Item age | > 60 days | Supervisor follow-up |
| Item age | > 90 days | Controller / management review |
| Unreconciled difference | Any amount | Cannot close — must resolve or document |
| Growing trend | 3+ consecutive periods | Process improvement investigation |

*Note: Set thresholds based on your organization's materiality level and risk appetite. The examples above are illustrative.*

## Reconciliation Best Practices

1. **Timeliness:** Complete reconciliations within the close calendar deadline (typically T+3 to T+5 business days after period end)
2. **Completeness:** Reconcile all balance sheet accounts on a defined frequency (monthly for material accounts, quarterly for immaterial)
3. **Documentation:** Every reconciliation should include preparer, reviewer, date, and clear explanation of all reconciling items
4. **Segregation:** The person who reconciles should not be the same person who processes transactions in that account
5. **Follow-through:** Track open items to resolution — do not just carry items forward indefinitely
6. **Root cause analysis:** For recurring reconciling items, investigate and fix the underlying process issue
7. **Standardization:** Use consistent templates and procedures across all accounts
8. **Retention:** Maintain reconciliations and supporting detail per your organization's document retention policy
