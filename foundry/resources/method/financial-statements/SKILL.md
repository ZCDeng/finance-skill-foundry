---
name: financial-statements
description: Generate financial statements (income statement, balance sheet, cash flow) with period-over-period comparison and variance analysis. Use when preparing a monthly or quarterly P&L, closing the books and need to flag material variances, comparing actuals to budget, building a financial summary for leadership review, or looking up GAAP presentation requirements and period-end adjustments. Do not claim an ERP or warehouse connection; work from the task's files.
argument-hint: "<frequency> <period>"
---

# /financial-statements

> Extracted from Anthropic's `finance` plugin in [knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins/tree/main/finance/skills/financial-statements). Licensed Apache-2.0. This modified copy ships inside FA Foundry; see NOTICE.

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).
>
> When this skill runs inside finance-skill-foundry, also read [FOUNDRY.md](../FOUNDRY.md).
>
> Foundry runtime note: load this skill through the native skill tool, then read the companion notes with `method-resource {skill: "financial-statements", resource: "FOUNDRY.md"}` and `method-resource {skill: "financial-statements", resource: "CONNECTORS.md"}` when the trusted preset or session needs those rules. In analysis mode, use the current task datasets, multi-table SQL/Python, run records, and editable drafts; materiality, currency, accounting policy, and narrative judgment are manager-controlled and ordinary calculations do not require per-tool approval.

**Important**: This command assists with financial statement workflows but does not provide financial advice. All statements should be reviewed by qualified financial professionals before use in reporting or filings.

Prepare supported financial working papers with period-over-period comparison and variance analysis. The workflow below walks through income statement generation; balance-sheet and cash-flow reference formats and common period-end adjustments are supporting material, subject to the confirmed basis, purpose and effective period.

## Foundry analysis mode

Before professional calculations, read [accounting-basis.md](../accounting-basis.md)
with `method-resource {skill: "financial-statements", resource: "accounting-basis.md"}`.
For F09/F10 driver or linked statements read [forecast-models.md](../forecast-models.md)
with `method-resource {skill: "financial-statements", resource: "forecast-models.md"}`;
for F11 model review read [model-checks.md](../model-checks.md) with
`method-resource {skill: "financial-statements", resource: "model-checks.md"}`.
Use [close-checklist.md](../close-checklist.md) with
`method-resource {skill: "financial-statements", resource: "close-checklist.md"}`
when a statement depends on accrual, reconciliation or balance-rollforward work.
These references specify methods; native capability and professional acceptance
must be established separately for the current scope.

Start with `list_finance_context` to identify the current scenarios, source snapshots, account maps, and dataset versions. If the current task includes uploaded statement, balance, or budget files that have not been registered, use `finance_source_refresh` with `file_identity_policy: "snapshot_only"` for ordinary files without real document-line identifiers, then bind the published snapshot with `finance_context_save` and any account rollups with `finance_map_save`. Use `"business_key"` only when the file carries genuine source keys.

Save the analysis requirements before calculation, including the statement question, scope, required metrics, and requested drilldowns. Use `run_metric` when the requested statement work fits a management P&L, ratio, account total, or control total. Use `explain_variance` for supported statement bridges, `finance_scenario_save` / `finance_scenario_run` when the answer depends on a saved actual/budget/forecast scenario, `drilldown_fact` for source-backed cells from the run, and `save_explanation_draft` for editable commentary with calculation claims tied to real run fields. Continue with SQL/Python for statement layouts, cash-flow reconstruction, disclosure tables, or presentation work outside those contracts. Do not claim an ERP or data-warehouse connection unless this session has configured and named one.

For explanation quality, follow the analysis-mode explanation contract in `FOUNDRY.md`: prepare facts and automatic supporting tables from successful runs with `prepare_explanation`, draft with stable `{{fact:FACT_ID}}` value placeholders. Saving already validates the current text; use `validate_explanation` separately when checking an existing draft or a specific unsaved revision. Use the returned `quality` and `completion` state for bounded repair: at most two targeted repair-and-check rounds, stopping on `no_progress`. Reuse only applicable scoped business context. Separate financial contributions from supported operational causes and manager judgment; preserve an editable draft when evidence is incomplete.

### Finish the current statement request

For a source-bound management statement template, follow this sequence:

1. Check the existing context, scenario, source snapshots and confirmed boundaries. Register the complete current question with `analysis_requirements_save` **before** `finance_scenario_run`; include the source bindings, scope, exact registered output metric keys and their template_id dimension. If dimensions.metric_key is supplied, it must name the same output as metric; a generic profit requirement does not rename a net_income output. Use the scenario and registered metric catalog returned by the tools. Do not invent a second calculation path when the native scenario covers the request.
2. Run the scenario after registration. Verify its `requirements_id` and semantic fingerprint belong to that registration, and inspect all model checks and evidence eligibility. If requirements changed, calculate a new run; a later registration cannot certify an earlier run.
3. Call `prepare_explanation` for that successful run. Its default `writing` view separates output `facts` from source input_facts; `fact_view: "inspection"` exposes the complete fact set for inspection. Input amount eligibility is unchanged in both views. When save_template_spec is present, send that short spec to `save_explanation_draft` and add only a brief qualitative_note for necessary qualitative treatment or limitations; omit amounts, formulas, counts and repeated check descriptions. Do not add body, body_template, document, claims or fact_ids to this short spec: the service regenerates the current authorized template and validates the complete saved draft. This avoids copying the table and its references. If only draft_template is present, use that complete editable save spec as the starting point: it contains the requested eligible output table, exact fact tokens, run IDs and current requirements ID. Its empty `claims` and `fact_ids` arrays are intentional: the server generates exact claims from the tokens and a repair does not inherit obsolete claims. Do not copy claims, repeat the table in prose, or recompute formulas. When the template is absent, select each requested eligible fact by metric_identity, period and unit, retain its reference_template.body_token and top-level `run_ids`; row numbers are zero-based. Ineligible facts remain ineligible.
4. Keep the draft concise. Tie headings and prose to the same-contract, same-period forecast_performance; forecast assumptions do not prove actual fulfilment. Add only necessary treatment and limitations; the run retains bindings and checks. Every additional financial amount or formula operand requires its own eligible citation. State an evidence gap for unsupported input allocations. Statement totals alone do not establish transaction composition. Recognize revenue under the fulfilment assumption; do not assign that recognition basis to collection. Collection against an identified receivable reduces that receivable: name the object and distinguish partial collection from full settlement. Reconcile its opening balance, specifically allocated receipts, other adjustments and remaining balance. Say fully settled only when sources establish that the same receivable was paid in full with no balance remaining; partial collection leaves an unpaid balance. Aggregate receipts, even when larger than one receivable, do not establish its allocation. Keep write-offs or other adjustments separate from cash collection. Describe tracing to the receivable's origin separately; do not pair revenue and collection respectively with fulfilment recognition and receivable creation, or say a collection offsets another collection. Fulfilled cash sales may recognize revenue and receive cash without assuming a prior credit sale. Unpaid consideration creates the outstanding balance; collection against an identified receivable reduces it. Specific old-receivable, unpaid credit-sale or settled cash-sale allocations need their own source evidence. Passing model checks do not mean all check differences are zero. Use returned structure_counts.body_template for optional counts; omit unnecessary input and boundary counts.
   A performance or allocation month establishes the service period, not the contract signing date. Without archived signing-date evidence, call it a current-period fulfilled contract or service; do not describe it as a newly signed contract or a new contract of that month. A contract identifier does not establish its signing date.
5. Save with `save_explanation_draft` and inspect its actual `quality` and `completion.status`. The save performs validation. Also inspect its nonblocking `readability` suggestions: ambiguous recognition/collection pairing, a repeated settlement object or an unclear parenthetical modifier calls for a targeted clarification within the existing repair budget, saved as a revision without overwriting history. These suggestions do not change financial quality or completion; an unresolved suggestion remains a wording limitation. Current semantic checks do not cover every per-receivable full-settlement assertion: readability clear, quality pass and a completed receipt do not replace independent review of the saved prose against allocation sources. Once no such wording clarification remains, a separate validation or save is unnecessary when the persisted receipt is `complete`. End by copying that saved receipt’s final_response exactly. It binds the actual saved draft and pending professional-review limitation. Do not expand it to claim that detailed checks were saved in the body: the body contains a pass summary, and individual checks remain in the run. Do not restate amounts, formulas or check differences in the final reply; do not load the full analysis state. The save receipt is sufficient to confirm this workflow; pending professional review remains a stated limitation. If repair is required, change only the diagnosed issue within the existing repair budget, keep all required outputs and clear obsolete claims explicitly. Do not repair a qualification failure by renaming the metric or repeating the same ineligible fact. A cancelled call requires inspection of persisted state before any retry; incomplete receipts must be reported accurately.

Large tool responses may use `$foundry_ref` JSON pointers for exact repeated objects. A `foundry.model-result.v2` packet instead contains `columns`, `values`, and `result`: decode `{$r:[n,items]}` by pairing `columns[n]` with the items, and decode `{$v:n}` from `values[n]`, recursively. These preserve the original values and qualifications. A save receipt marked `full_result:false` explicitly lists omitted saved-document and supporting-detail paths; inspect the retained quality issues and completion receipt, and use `prepare_explanation` / `drilldown_fact` for facts and provenance. Never infer approval from omitted detail or an overflow warning. The complete original tool result remains archived.

When visuals help management compare the result, read [report-visuals.md](../report-visuals.md) through `method-resource {skill: "financial-statements", resource: "report-visuals.md"}`. Use `bar` for category or actual/budget comparisons, `line` for ordered periods, and `flow` for explicitly attributed explanatory steps. Archive a successful run using `chart_deliverable_save`, then reference its `chart_id` in a `reportVisual` block of `save_explanation_draft.spec.document`. Keep values bound to the run, preserve units and missing/negative values, and attach the figure's supported conclusion and source. A visual does not certify a financial claim; retain the existing facts, claims and checks. Use the data table when exact lookup is the purpose or the figure is too dense.

## Usage

```
/financial-statements <period-type> <period>
```

### Arguments

- `period-type` — The reporting period type:
  - `monthly` — Single month P&L with prior month and prior year month comparison
  - `quarterly` — Quarter P&L with prior quarter and prior year quarter comparison
  - `annual` — Full year P&L with prior year comparison
  - `ytd` — Year-to-date P&L with prior year YTD comparison
- `period` — The period to report (e.g., `2024-12`, `2024-Q4`, `2024`)

## Workflow

### 1. Gather Financial Data

If ~~erp or ~~data warehouse is connected:
- Pull trial balance or income statement data for the specified period
- Pull comparison period data (prior period, prior year, budget/forecast)
- Pull account hierarchy and groupings for presentation

If no data source is connected:
> Connect ~~erp or ~~data warehouse to pull financial data automatically. You can also paste trial balance data, upload a spreadsheet, or provide income statement data for analysis.

Prompt the user to provide:
- Current period revenue and expense data (by account or category)
- Comparison period data (prior period, prior year, and/or budget)
- Any known adjustments or reclassifications

### 2. Generate Income Statement

Present in standard multi-column format:

```
INCOME STATEMENT
Period: [Period description]
(in thousands, unless otherwise noted)

                              Current    Prior      Variance   Variance   Budget    Budget
                              Period     Period     ($)        (%)        Amount    Var ($)
                              --------   --------   --------   --------   --------  --------
REVENUE
  Product revenue             $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  Service revenue             $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  Other revenue               $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
                              --------   --------   --------              --------  --------
TOTAL REVENUE                 $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX

COST OF REVENUE
  [Cost items]                $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
                              --------   --------   --------              --------  --------
GROSS PROFIT                  $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  Gross Margin                XX.X%      XX.X%

OPERATING EXPENSES
  Research & development      $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  Sales & marketing           $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  General & administrative    $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
                              --------   --------   --------              --------  --------
TOTAL OPERATING EXPENSES      $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX

OPERATING INCOME (LOSS)       $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  Operating Margin            XX.X%      XX.X%

OTHER INCOME (EXPENSE)
  Interest income             $XX,XXX    $XX,XXX    $X,XXX     X.X%
  Interest expense           ($XX,XXX)  ($XX,XXX)   $X,XXX     X.X%
  Other, net                  $XX,XXX    $XX,XXX    $X,XXX     X.X%
                              --------   --------   --------
TOTAL OTHER INCOME (EXPENSE)  $XX,XXX    $XX,XXX    $X,XXX     X.X%

INCOME BEFORE TAXES           $XX,XXX    $XX,XXX    $X,XXX     X.X%
  Income tax expense          $XX,XXX    $XX,XXX    $X,XXX     X.X%
                              --------   --------   --------

NET INCOME (LOSS)             $XX,XXX    $XX,XXX    $X,XXX     X.X%       $XX,XXX   $X,XXX
  Net Margin                  XX.X%      XX.X%
```

### 3. Variance Analysis

For each line item, calculate and flag material variances.

#### Variance Calculation

For each line item, calculate:
- **Dollar variance:** Current period - Prior period (or current period - budget)
- **Percentage variance:** (Current - Prior) / |Prior| x 100
- **Basis point change:** For margins and ratios, express change in basis points (1 bp = 0.01%)

#### Materiality Thresholds

Define what constitutes a "material" variance requiring investigation. Common approaches:

- **Fixed dollar threshold:** Variances exceeding a set dollar amount (e.g., $50K, $100K)
- **Percentage threshold:** Variances exceeding a set percentage (e.g., 10%, 15%)
- **Combined:** Either the dollar OR percentage threshold is exceeded
- **Scaled:** Different thresholds for different line items based on their size and volatility

*Example thresholds, not fixed Foundry defaults (adjust for your organization):*

| Line Item Size | Dollar Threshold | Percentage Threshold |
|---------------|-----------------|---------------------|
| > $10M        | $500K           | 5%                  |
| $1M - $10M    | $100K           | 10%                 |
| < $1M         | $50K            | 15%                 |

#### Variance Decomposition

Break down total variance into component drivers:

- **Volume/quantity effect:** Change in volume at prior period rates
- **Rate/price effect:** Change in rate/price at current period volume
- **Mix effect:** Shift in composition between items with different rates/margins
- **New/discontinued items:** Items present in one period but not the other
- **One-time/non-recurring items:** Items that are not expected to repeat
- **Timing effect:** Items shifting between periods (not a true change in run rate)
- **Currency effect:** Impact of FX rate changes on translated results

#### Investigation and Narrative

For each material variance:
1. Quantify the variance ($ and %)
2. Identify whether favorable or unfavorable
3. Decompose into drivers using the categories above
4. Provide a narrative explanation of the business reason
5. Assess whether the variance is temporary or represents a trend change
6. Note any actions required (further investigation, forecast update, process change)

### 4. Key Metrics Summary

```
KEY METRICS
                              Current    Prior      Change
Revenue growth (%)                                  X.X%
Gross margin (%)              XX.X%      XX.X%      X.X pp
Operating margin (%)          XX.X%      XX.X%      X.X pp
Net margin (%)                XX.X%      XX.X%      X.X pp
OpEx as % of revenue          XX.X%      XX.X%      X.X pp
Effective tax rate (%)        XX.X%      XX.X%      X.X pp
```

### 5. Material Variance Summary

List all material variances requiring investigation:

| Line Item | Variance ($) | Variance (%) | Direction | Preliminary Driver | Action |
|-----------|-------------|-------------|-----------|-------------------|--------|
| [Item]    | $X,XXX      | X.X%        | Unfav.    | [If known]        | Investigate |

### 6. Output

Provide:
1. Formatted income statement with comparisons
2. Key metrics summary
3. Material variance listing with investigation flags
4. Suggested follow-up questions for unexplained variances
5. Offer to drill into any specific variance with `/variance-analysis`

## Accounting basis, purpose and effective period

Route professional presentation by the confirmed accounting basis, reporting
purpose, entity scope, fiscal-year start and effective period. The reference formats
below are working-paper examples and do not establish full compliance with CAS,
IFRS or US GAAP. Missing basis information need not prevent ordinary arithmetic;
it does limit statutory presentation and basis-sensitive recognition conclusions.

| Basis / purpose | Required route and boundary |
| --- | --- |
| CAS statutory statements | Apply the relevant Chinese standards and the entity's confirmed policies. CAS 31 requires the direct method for operating cash flows, with the required reconciliation/disclosures. An indirect management bridge is not a CAS statutory cash-flow statement. |
| IFRS statements | Determine the annual reporting period and documented early adoption. IFRS 18 applies for annual periods beginning on or after 2027-01-01, with early adoption permitted; do not assume IAS 1 already ceased to apply to a 2026 non-early-adopter. Use the selected effective presentation rules and applicable IAS 7 requirements. |
| US GAAP statements | Use the applicable ASC topics and effective amendments for that entity; ASC 210/220/230 references are US-specific and must not be applied as universal CAS or IFRS rules. Verify any presentation or policy exception before asserting compliance. |
| Management reporting / forecast | State the management purpose, definitions, assumptions and reconciliation to source books. An indirect cash bridge may aid planning, but does not certify statutory presentation under any basis. |

Income, balance-sheet, cash-flow, revenue, lease, impairment and tax rules are not
interchangeable across bases. A method must be declared supported for the specific
basis, purpose and period before a professional completion claim. Otherwise deliver
the supported calculations and identify the specific unsupported judgment or data
gap. No standard is inferred from the language of a workbook or the user's location.

Source anchors: [CAS 31](https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/200806/t20080618_46250.htm)
and [IFRS 18](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/).

## Balance Sheet Reference Format

```
ASSETS
Current Assets
  Cash and cash equivalents
  Short-term investments
  Accounts receivable, net
  Inventory
  Prepaid expenses and other current assets
Total Current Assets

Non-Current Assets
  Property and equipment, net
  Operating lease right-of-use assets
  Goodwill
  Intangible assets, net
  Long-term investments
  Other non-current assets
Total Non-Current Assets

TOTAL ASSETS

LIABILITIES AND STOCKHOLDERS' EQUITY
Current Liabilities
  Accounts payable
  Accrued liabilities
  Deferred revenue, current portion
  Current portion of long-term debt
  Operating lease liabilities, current portion
  Other current liabilities
Total Current Liabilities

Non-Current Liabilities
  Long-term debt
  Deferred revenue, non-current
  Operating lease liabilities, non-current
  Other non-current liabilities
Total Non-Current Liabilities

Total Liabilities

Stockholders' Equity
  Common stock
  Additional paid-in capital
  Retained earnings (accumulated deficit)
  Accumulated other comprehensive income (loss)
  Treasury stock
Total Stockholders' Equity

TOTAL LIABILITIES AND STOCKHOLDERS' EQUITY
```

## Cash Flow Statement Reference Format (Indirect Method)

This format is a management reconciliation example. For CAS statutory operating
cash flows, use the required direct method and the applicable disclosures instead.

```
CASH FLOWS FROM OPERATING ACTIVITIES
Net income (loss)
Adjustments to reconcile net income to net cash from operations:
  Depreciation and amortization
  Stock-based compensation
  Amortization of debt issuance costs
  Deferred income taxes
  Loss (gain) on disposal of assets
  Impairment charges
  Other non-cash items
Changes in operating assets and liabilities:
  Accounts receivable
  Inventory
  Prepaid expenses and other assets
  Accounts payable
  Accrued liabilities
  Deferred revenue
  Other liabilities
Net Cash Provided by (Used in) Operating Activities

CASH FLOWS FROM INVESTING ACTIVITIES
  Purchases of property and equipment
  Purchases of investments
  Proceeds from sale/maturity of investments
  Acquisitions, net of cash acquired
  Other investing activities
Net Cash Provided by (Used in) Investing Activities

CASH FLOWS FROM FINANCING ACTIVITIES
  Proceeds from issuance of debt
  Repayment of debt
  Proceeds from issuance of common stock
  Repurchases of common stock
  Dividends paid
  Payment of debt issuance costs
  Other financing activities
Net Cash Provided by (Used in) Financing Activities

Effect of exchange rate changes on cash

Net Increase (Decrease) in Cash and Cash Equivalents
Cash and cash equivalents, beginning of period
Cash and cash equivalents, end of period
```

## Common Adjustments and Reclassifications

In Foundry this list is reference material. Foundry does not post entries or make payments, so treat any adjustment here as a draft for the manager to review.

### Period-End Adjustments

1. **Accruals:** Record expenses incurred but not yet paid (AP accruals, payroll accruals, interest accruals)
2. **Deferrals:** Adjust prepaid expenses, deferred revenue, and deferred costs for the period
3. **Depreciation and amortization:** Draft periodic depreciation/amortization entries from fixed asset and intangible schedules
4. **Bad debt provision:** Adjust allowance for credit losses based on aging analysis and historical loss rates
5. **Inventory adjustments:** Record write-downs for obsolete, slow-moving, or impaired inventory
6. **FX revaluation:** Revalue foreign-currency-denominated monetary assets and liabilities at period-end rates
7. **Tax provision:** Record current and deferred income tax expense
8. **Fair value adjustments:** Mark-to-market investments, derivatives, and other fair-value items

### Reclassifications

1. **Current/non-current reclassification:** Reclassify long-term debt maturing within 12 months to current
2. **Contra account netting:** Net allowances against gross receivables, accumulated depreciation against gross assets
3. **Intercompany elimination:** Eliminate intercompany balances and transactions in consolidation
4. **Discontinued operations:** Reclassify results of discontinued operations to a separate line item
5. **Equity method adjustments:** Record share of investee income/loss for equity method investments
6. **Segment reclassifications:** Ensure transactions are properly classified by operating segment
