# Finance Scenarios Contract

This stage 5 module adds deterministic finance scenario calculations in
`foundry.finance_scenarios`. It is a pure engine: callers provide already
authorized, versioned input records and receive structured output. It does not
read or write task state, submit payments, post journal entries, call a model,
open a network connection, or install dependencies.

## Public API

- `compute_receivables_aging(invoices, activity=None, *, as_of, scope, buckets=None)`
- `forecast_cash_13_weeks(...)` with `opening_cash`, `start_date`,
  `actual_cutoff`, optional `receipts`, optional `payments`, optional
  `scenario`, required `scope`, and `weeks=13`
- `validate_driver_model(drivers, *, inputs=None, manager_assumptions=None)`
- `create_child_scenario(parent, changes, *, label, actual_cutoff=None)`

All money and driver values are parsed through `Decimal(str(value))` and are
returned as decimal strings. Dates are ISO `YYYY-MM-DD` strings or `date`
objects. Failures raise `FoundryError`.

## Aging Inputs

Invoice records require:

- `id`
- `due_date`
- `amount`

They must also carry `organization` or `org`, `ledger`, and `currency`.
Together with `id`, those fields form the receivable identity. They may also
carry `customer`.

`scope` is required for aging. It may filter by customer, organization or org,
ledger, and currency. If the same invoice `id` appears under multiple
ledger/organization/currency identities, activity for that invoice must declare
the same composite identity. The engine refuses ambiguous activity rather than
guessing.

Invoices with `issue_date`, `invoice_date`, or `effective_date` after `as_of`
are listed in `evidence.future_invoices_ignored` and excluded from the snapshot.

Activity records require:

- `id`
- `invoice_id`
- `organization` or `org`
- `ledger`
- `currency`
- `kind`: one of `payment`, `allocation`, `credit`, `writeoff`
- `effective_date`
- `amount`

Only activity with `effective_date <= as_of` reduces the invoice open amount.
Later records are listed in `evidence.future_activity_ignored` and do not
change the historical snapshot. Positive outstanding invoices are assigned to
`not_due`, `0-30`, `31-60`, `61-90`, or `90+` unless custom buckets are
provided. Summary rows include `currency`, so mixed-currency scopes produce
separate bucket totals rather than a combined amount. `detail_rows` provide the
invoice drilldown.

Negative activity amounts are ambiguous unless the row declares
`reversal: true`; undeclared negative reductions are refused. Declared reversals
reduce applied settlement amounts. Exact duplicate activity rows are ignored
once and reported in `warnings`; duplicate activity identities with different
content are refused. Overpayments and over-applied credits/writeoffs are listed
in `evidence.overapplied` rather than disappearing.

## Cash Forecast Inputs

Receipts and payments require:

- `id`
- `date`
- `amount`
- `organization` or `org`
- `ledger`
- `currency`

The forecast returns 13 weekly rows by default. Every row obeys:

`opening_cash + receipts - payments = closing_cash`

Each row's closing cash is the next row's opening cash. `scope` is required and
must declare one organization, ledger, and currency. Events outside that scope
are listed in `evidence.ignored_events` and are not mixed into the forecast.
`actual_cutoff` marks events on or before the cutoff as actual; rows declared as
`status: forecast` or `status: planned` before or on the cutoff are refused.
Receipt-delay scenarios shift only future receipts by
`scenario.delay_receipts_days`; actual history remains unchanged. Shifted
receipts outside the 13-week horizon are retained in `evidence.outside_horizon`
rather than deleted.

## Driver Model

Drivers are small declared DAG nodes. Each driver declares exactly one of:

- `direct_assumption: true`
- `formula` plus matching `depends_on`

Formulas support only references, decimal string or integer constants, unary
signs, and `+`, `-`, `*`, `/`. The parser uses `ast` and does not evaluate raw
Python expressions. Cycles, undeclared dependencies, mismatched dependencies,
unsupported operators, missing inputs, and division by zero are refused with
`FoundryError`.

When source data is missing, a direct driver may be supplied from
`manager_assumptions` with a required `label` and `value`. The returned
`assumptions` array records that source explicitly.

## Scenario Versioning

`create_child_scenario` creates a child record from a parent scenario and a
small change set. It deep-copies parent inputs, applies only the supplied
changes, records `parent_id`, `actual_cutoff`, parent and child input hashes,
and a serializable key-level `diff`. The parent object is not mutated.

Persistence of parent-child scenario records belongs to the existing analysis
revision layer and is intentionally outside this pure module.

## Output Shape

Each calculation returns:

- `columns`
- `rows`
- `row_count`
- `evidence`
- `assumptions`
- `warnings`

Receivables aging also returns `detail_columns` and `detail_rows` for drilldown.

## Acceptance Coverage

- A13: G3 cash delay, G4 scoped aging, weekly cash continuity, effective-date
  history, currency separation, and preservation of future receivables are
  covered in
  `tests/test_finance_scenarios.py`.
- A14: child scenarios preserve parent inputs and hashes while serializing the
  assumption diff.
- A15: cyclic driver definitions are refused, and manager direct assumptions
  are accepted only with explicit labels.
- A26: the module has no payment-submission or journal-posting public API.
