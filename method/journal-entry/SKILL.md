---
name: journal-entry
description: Prepare draft journal entries with proper debits, credits, and supporting detail. Use when drafting month-end accruals (AP, payroll, prepaid), depreciation or amortization entries, revenue recognition or deferred revenue adjustments, or documenting an entry for audit review. Drafts only; do not use to post entries. Foundry does not post to an ERP.
argument-hint: "<type> [period]"
---

# Journal Entry Preparation

> Extracted from Anthropic's `finance` plugin in [knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins/tree/main/finance/skills/journal-entry). Licensed Apache-2.0. This modified copy ships inside FA Foundry; see NOTICE.

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).
>
> When this skill runs inside finance-skill-foundry, also read [FOUNDRY.md](../FOUNDRY.md).
>
> Foundry runtime note: load this skill through the native skill tool, then read the companion notes with `method-resource {skill: "journal-entry", resource: "FOUNDRY.md"}` and `method-resource {skill: "journal-entry", resource: "CONNECTORS.md"}` when the trusted preset or session needs those rules. In analysis mode, use the current task datasets, multi-table SQL/Python, run records, and editable drafts; materiality, currency, accounting policy, and narrative judgment are manager-controlled and ordinary calculations do not require per-tool approval. Journal-entry outputs are drafts only; Foundry does not post to an ERP.

**Important**: This command assists with journal entry workflows but does not provide financial advice. All entries should be reviewed by qualified financial professionals before posting.

Prepare journal entries with proper debits, credits, supporting detail, and review documentation.

## Usage

```
/journal-entry <type> <period>
```

### Arguments

- `type` — The journal entry type. One of:
  - `ap-accrual` — Accounts payable accruals for goods/services received but not yet invoiced
  - `fixed-assets` — Depreciation and amortization entries for fixed assets and intangibles
  - `prepaid` — Amortization of prepaid expenses (insurance, software, rent, etc.)
  - `payroll` — Payroll accruals including salaries, benefits, taxes, and bonus accruals
  - `revenue` — Revenue recognition entries including deferred revenue adjustments
- `period` — The accounting period (e.g., `2024-12`, `2024-Q4`, `2024`)

## Workflow

### 1. Gather Source Data

Do not claim an ERP or data-warehouse connection unless this session has configured and named one; otherwise work from the task's files and registered datasets.

If ~~erp or ~~data warehouse is connected:
- Pull the trial balance for the specified period
- Pull subledger detail for the relevant accounts
- Pull prior period entries of the same type for reference
- Identify the current GL balances for affected accounts

If no data source is connected:
> Connect ~~erp or ~~data warehouse to pull GL data automatically. You can also paste trial balance data or upload a spreadsheet.

Prompt the user to provide:
- Trial balance or GL balances for affected accounts
- Subledger detail or supporting schedules
- Prior period entries for reference (optional)

### 2. Calculate the Entry

Based on the JE type:

**AP Accrual:**
- Identify goods/services received but not invoiced by period end
- Calculate accrual amounts from PO receipts, contracts, or estimates
- Debit: Expense accounts (or asset accounts for capitalizable items)
- Credit: Accrued liabilities

**Fixed Assets:**
- Pull the fixed asset register or depreciation schedule
- Calculate period depreciation by asset class and method (straight-line, declining balance, units of production)
- Debit: Depreciation expense (by department/cost center)
- Credit: Accumulated depreciation

**Prepaid:**
- Pull the prepaid amortization schedule
- Calculate the period amortization for each prepaid item
- Debit: Expense accounts (by type — insurance, software, rent, etc.)
- Credit: Prepaid expense accounts

**Payroll:**
- Calculate accrued salaries for days worked but not yet paid
- Calculate accrued benefits (health, retirement contributions, PTO)
- Calculate employer payroll tax accruals
- Calculate bonus accruals (if applicable, based on plan terms)
- Debit: Salary expense, benefits expense, payroll tax expense
- Credit: Accrued payroll, accrued benefits, accrued payroll taxes

**Revenue:**
- Review contracts and performance obligations
- Calculate revenue to recognize based on delivery/performance
- Adjust deferred revenue balances
- Debit: Deferred revenue (or accounts receivable)
- Credit: Revenue accounts (by stream/category)

### Source-bound transaction checks

For a supported transaction, use `finance_scenario_save` with
`kind=transaction_review`, then `finance_scenario_run`. The inputs contain
`scope`, `source_bindings`, and `proposed_entries`. Bind each original fact with
`{alias, column, selector, aggregation: "single", scope, period, currency, unit}`;
the transaction must link its original policy record by `policy_id`. Policy
applicability and effective dates must come from sources. Proposed entries are
the artifact being checked, never evidence for their own correctness.

The registered cases cover uniform service advances, consumed service expenses,
qualifying initial asset acquisitions, collection of existing receivables,
fulfilled cash sales, and dated releases of restricted cash. Read the returned
input gaps and itemized expected/actual differences. Do not replace missing
source facts, policy references or dates with assumptions to make a check pass.
Uniform service allocation is cumulative since contract start; it does not by
itself establish the current-period adjusting journal without opening balances.
An effective release requires a separate source identifying the restriction,
release amount, status and date.

Successful checks retain `source_bound_transaction_check_requires_professional_review`.
They do not qualify arbitrary SQL output as financial evidence, approve a policy,
complete a statutory report, or authorize posting. Report remaining review needs
alongside the candidate journal or statements.

### 3. Generate the Journal Entry

Present the entry in standard format:

```
Journal Entry: [Type] — [Period]
Prepared by: [User]
Date: [Period end date]

| Line | Account Code | Account Name | Debit | Credit | Department | Memo |
|------|-------------|--------------|-------|--------|------------|------|
| 1    | XXXX        | [Name]       | X,XXX |        | [Dept]     | [Detail] |
| 2    | XXXX        | [Name]       |       | X,XXX  | [Dept]     | [Detail] |
|      |             | **Total**    | X,XXX | X,XXX  |            |      |

Supporting Detail:
- [Calculation basis and assumptions]
- [Reference to supporting schedule or documentation]

Reversal: [Yes/No — if yes, specify reversal date]
```

### Accrual settlement and reversal policy

Read [accounting-basis.md](../accounting-basis.md) with
`method-resource {skill: "journal-entry", resource: "accounting-basis.md"}` and
[close-checklist.md](../close-checklist.md) with
`method-resource {skill: "journal-entry", resource: "close-checklist.md"}` before
policy-sensitive calculations. For F03/K11 coverage read [model-checks.md](../model-checks.md)
with `method-resource {skill: "journal-entry", resource: "model-checks.md"}`.

Use the confirmed policy, service period, existing entries and subsequent invoice
treatment to choose one complete path. An obligation does not disappear at a month
boundary. For services of 100 received in December and billed/paid at 100 in January,
the December draft is debit expense 100 / credit accrued liability 100. With no tax
or estimate change, either of these is valid:

- **Reverse then book:** January reversal debits accrued liability 100 and credits
  expense 100; the January invoice draft debits expense 100 and credits payable 100.
  Settlement debits payable 100 and credits cash 100. January net expense is zero.
- **Settle the accrual:** no reversal; the January invoice draft debits accrued
  liability 100 and credits payable 100. Settlement debits payable 100 and credits
  cash 100. January net expense is zero.

Do not mix the two paths or record the original expense twice. Link the original
accrual, any reversal, invoice and settlement; investigate differences between the
estimate and invoice. These are drafts for authorized review outside Foundry, not
evidence that entries have been posted.

### 4. Review Checklist

Before finalizing, verify:

- [ ] Debits equal credits in the functional currency using the confirmed exchange rates and translation policy; retain original amounts/currencies and FX differences. A normal currency exchange need not balance separately in each original currency. If this workflow cannot validate translation, state that exact gap.
- [ ] Correct accounting period
- [ ] Account codes are valid and map to the right GL accounts
- [ ] Amounts are calculated correctly with supporting detail
- [ ] Memo/description is clear and specific enough for audit
- [ ] Department/cost center coding is correct
- [ ] Entry is consistent with prior period treatment
- [ ] Reversal flag follows the confirmed policy and invoice treatment; the complete chosen path avoids duplicate expense
- [ ] Supporting documentation is referenced or attached
- [ ] Entry is within the user's approval authority
- [ ] No unusual or out-of-pattern amounts that need investigation

### 5. Output

Provide:
1. The formatted journal entry
2. Supporting calculations
3. Comparison to prior period entry of the same type (if available)
4. Any items flagged for review or follow-up
5. Review notes for manual posting outside Foundry (manual entry or upload format for the user's ERP)
