---
name: variance-analysis
description: Decompose financial variances into drivers with narrative explanations and waterfall analysis. Use when analyzing budget vs. actual, period-over-period changes, revenue or expense variances, or preparing variance commentary for leadership. Do not use for sell-side research or valuation.
argument-hint: "<line> vs <base>"
---

# Variance Analysis

> Extracted from Anthropic's `finance` plugin in [knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins/tree/main/finance/skills/variance-analysis). Licensed Apache-2.0. This modified copy ships inside FA Foundry; see NOTICE.

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).
>
> When this skill runs inside finance-skill-foundry, also read [FOUNDRY.md](../FOUNDRY.md).
>
> Foundry runtime note: the trusted preset or session selects the runtime fence. Before the first variance calculation or missing-input diagnostic, load this skill through the native skill tool, then successfully read `method-resource {skill: "variance-analysis", resource: "FOUNDRY.md"}` and `method-resource {skill: "variance-analysis", resource: "model-checks.md"}` in this session. Wait for the reads to finish before calculation; do not issue them concurrently or count a late read as an earlier one. CONNECTORS.md is optional connection guidance, not a substitute. In analysis mode, use current task datasets, multi-table SQL/Python, run records, and editable drafts; materiality, currency, accounting policy, and narrative judgment are manager-controlled and ordinary calculations do not require per-tool approval.

**Important**: This skill assists with variance analysis workflows but does not provide financial advice. All analyses should be reviewed by qualified financial professionals before use in reporting.

Techniques for decomposing variances, materiality thresholds, narrative generation, waterfall chart methodology, and budget vs actual vs forecast comparisons.

## Foundry analysis mode

Start with `list_finance_context` to see the current source snapshots, scenario bindings, account maps, metric definitions, and available capabilities. For unregistered uploaded budget, actual, forecast, or operational-driver files, use `finance_source_refresh` only as a file snapshot refresh: ordinary files without real document-line identifiers should use `file_identity_policy: "snapshot_only"`, while `"business_key"` is reserved for files with genuine source keys. Bind the published source and scope with `finance_context_save` before running comparisons.

After those method reads, create or select a real context with every original source binding, then save the variance requirements using its returned context ID before calculation, including the target metric, comparison scope, required bridge components, and requested drilldowns. Check the returned professional identity and support preflight; a nonempty semantic fingerprint alone is insufficient, and background bindings must not be dropped. Resolve registration errors before any diagnostic run. Use `run_metric` to establish actual, baseline, and control totals before explaining the bridge. Use `explain_variance` when the question fits a supported profit bridge or price/quantity decomposition and the current scenario/source versions are explicit. Use `drilldown_fact` to inspect source-backed cells from that run, and `save_explanation_draft` for commentary with calculation claims linked to real `run_id`, `row`, `column`, and `value` fields. Keep using SQL/Python for custom joins, unsupported decompositions, cohort analysis, and data-quality checks; do not force every variance into the specialized tools. Materiality, missing-group treatment, negative budget policy, and narrative judgment remain manager-controlled.

For explanation quality, follow the analysis-mode explanation contract in `FOUNDRY.md`: prepare facts and automatic supporting tables from successful runs with `prepare_explanation`, draft with stable `fact_ids` and `{{fact:FACT_ID}}` value placeholders, then check the current text with `validate_explanation`. Use the returned `quality` and `completion` state for bounded repair: at most two targeted repair-and-check rounds, stopping on `no_progress`. Reuse only applicable scoped business context. Separate financial contributions from supported operational causes and manager judgment; preserve an editable draft when evidence is incomplete.

## Usage

```
/variance-analysis <line> vs <base>
```

### Arguments

- `line` — The P&L or operational line being explained (e.g., product revenue, S&M, payroll)
- `base` — The comparison basis: `budget`, `forecast`, `prior`, or `prior-year`

## Variance Decomposition Techniques

The preceding model-checks.md read provides K09 closure and coverage for the
variance calculation. When defining forecast drivers or a forecast model, also
read [forecast-models.md](../forecast-models.md) with
`method-resource {skill: "variance-analysis", resource: "forecast-models.md"}` for
F06 applicability. When the question requires accounting recognition, estimates
or professional evidence boundaries, also read
[accounting-basis.md](../accounting-basis.md) with
`method-resource {skill: "variance-analysis", resource: "accounting-basis.md"}`
before the dependent calculation. Do not reload an unchanged resource already
successfully read in this session or load unrelated resources by default.

### Price / Volume Decomposition

The most fundamental variance decomposition. Used for revenue, cost of goods, and any metric that can be expressed as Price x Volume.

**Formula:**
```
Total Variance = Actual - Budget (or Prior)

Volume Effect  = (Actual Volume - Budget Volume) x Budget Price
Price Effect   = (Actual Price - Budget Price) x Actual Volume
Verification:  Volume Effect + Price Effect = Total Variance
               (when mix is embedded in the price/volume terms)
```

An interaction or unexplained residual is not automatically a product mix effect.

**Three-way decomposition: volume → mix → price (fixed order):**

Let Va/Vb be actual/budget total volume, ma_i/mb_i each product's share of that
total, and pa_i/pb_i its actual/budget price. Shares sum to one within the same
comparable basket; quantities must use an additive common unit.

```
Volume Effect = (Va - Vb) * sum(mb_i * pb_i)
Mix Effect    = Va * sum((ma_i - mb_i) * pb_i)
Price Effect  = Va * sum(ma_i * (pa_i - pb_i))
Total Variance = Va * sum(ma_i * pa_i) - Vb * sum(mb_i * pb_i)
Verification: Volume Effect + Mix Effect + Price Effect = Total Variance
```

Frozen check: budget volume 100, prices 10/20, mix .5/.5; actual volume 120,
prices 12/18, mix .6/.4 produces **300 - 120 + 48 = 228**. Another ordering can
allocate interaction differently and must be named; do not mix formulas from
different orderings. Mathematical contributions do not prove business causes.

Missing baseline prices, new/discontinued products, zero total volume, negative
return quantities, or incompatible quantity units need an explicit comparable
basket or an unsupported/input-gap result. Never invent a zero price or a share.
This is a method definition, not a capability claim: use a native three-factor
mode only when the current tool advertises and validates that mode. Existing
two-factor modes do not become three-factor modes by renaming their outputs.

**Example — Revenue variance:**
- Budget: 10,000 units at $50 = $500,000
- Actual: 11,000 units at $48 = $528,000
- Total variance: +$28,000 favorable
  - Volume effect: +1,000 units x $50 = +$50,000 (favorable — sold more units)
  - Price effect: -$2 x 11,000 units = -$22,000 (unfavorable — lower ASP)
  - Net: +$28,000

### Rate / Mix Decomposition

Used when analyzing blended rates across segments with different unit economics.

**Formula:**
```
Rate Effect = Sum of (Actual Volume_i x (Actual Rate_i - Budget Rate_i))
Mix Effect  = Sum of (Budget Rate_i x (Actual Volume_i - Expected Volume_i at Budget Mix))
```

**Example — Gross margin variance:**
- Product A: 60% margin, Product B: 40% margin
- Budget mix: 50% A, 50% B → Blended margin 50%
- Actual mix: 40% A, 60% B → Blended margin 48%
- Mix effect explains 2pp of margin compression

### Headcount / Compensation Decomposition

Used for analyzing payroll and people-cost variances.

```
Total Comp Variance = Actual Compensation - Budget Compensation

Decompose into:
1. Headcount variance    = (Actual HC - Budget HC) x Budget Avg Comp
2. Rate variance         = (Actual Avg Comp - Budget Avg Comp) x Budget HC
3. Mix variance          = Difference due to level/department mix shift
4. Timing variance       = Hiring earlier/later than planned (partial-period effect)
5. Attrition impact      = Savings from unplanned departures (partially offset by backfill costs)
```

### Spend Category Decomposition

Used for operating expense analysis when price/volume is not applicable.

```
Total OpEx Variance = Actual OpEx - Budget OpEx

Decompose by:
1. Headcount-driven costs    (salaries, benefits, payroll taxes, recruiting)
2. Volume-driven costs       (hosting, transaction fees, commissions, shipping)
3. Discretionary spend       (travel, events, professional services, marketing programs)
4. Contractual/fixed costs   (rent, insurance, software licenses, subscriptions)
5. One-time / non-recurring  (severance, legal settlements, write-offs, project costs)
6. Timing / phasing          (spend shifted between periods vs plan)
```

## Materiality Thresholds and Investigation Triggers

### Setting Thresholds

Materiality thresholds determine which variances require investigation and narrative explanation. Set thresholds based on:

1. **Financial statement materiality:** Typically 1-5% of a key benchmark (revenue, total assets, net income)
2. **Line item size:** Larger line items warrant lower percentage thresholds
3. **Volatility:** More volatile line items may need higher thresholds to avoid noise
4. **Management attention:** What level of variance would change a decision?

### Recommended Threshold Framework

Examples, not fixed Foundry defaults:

| Comparison Type | Dollar Threshold | Percentage Threshold | Trigger |
|----------------|-----------------|---------------------|---------|
| Actual vs Budget | Organization-specific | 10% | Either exceeded |
| Actual vs Prior Period | Organization-specific | 15% | Either exceeded |
| Actual vs Forecast | Organization-specific | 5% | Either exceeded |
| Sequential (MoM) | Organization-specific | 20% | Either exceeded |

*Set dollar thresholds based on your organization's size. Common practice: 0.5%-1% of revenue for income statement items.*

### Investigation Priority

When multiple variances exceed thresholds, prioritize investigation by:

1. **Largest absolute dollar variance** — biggest P&L impact
2. **Largest percentage variance** — may indicate process issue or error
3. **Unexpected direction** — variance opposite to trend or expectation
4. **New variance** — item that was on track and is now off
5. **Cumulative/trending variance** — growing each period

## Narrative Generation for Variance Explanations

### Structure for Each Variance Narrative

```
[Line Item]: [Favorable/Unfavorable] variance of $[amount] ([percentage]%)
vs [comparison basis] for [period]

Driver: [Primary driver description]
[2-3 sentences explaining the business reason for the variance, with specific
quantification of contributing factors]

Outlook: [One-time / Expected to continue / Improving / Deteriorating]
Action: [None required / Monitor / Investigate further / Update forecast]
```

### Narrative Quality Checklist

Good variance narratives should be:

- [ ] **Specific:** Names the actual driver, not just "higher than expected"
- [ ] **Quantified:** Includes dollar and percentage impact of each driver
- [ ] **Causal:** Explains WHY it happened, not just WHAT happened
- [ ] **Forward-looking:** States whether the variance is expected to continue
- [ ] **Actionable:** Identifies any required follow-up or decision
- [ ] **Concise:** 2-4 sentences, not a paragraph of filler

### Common Narrative Anti-Patterns to Avoid

- "Revenue was higher than budget due to higher revenue" (circular — no actual explanation)
- "Expenses were elevated this period" (vague — which expenses? why?)
- "Timing" without specifying what was early/late and when it will normalize
- "One-time" without explaining what the item was
- "Various small items" for a material variance (must decompose further)
- Focusing only on the largest driver and ignoring offsetting items

## Waterfall Chart Methodology

### Concept

A waterfall (or bridge) chart shows how you get from one value to another through a series of positive and negative contributors. Used to visualize variance decomposition.

### Data Structure

```
Starting value:  [Base/Budget/Prior period amount]
Drivers:         [List of contributing factors with signed amounts]
Ending value:    [Actual/Current period amount]

Verification:    Starting value + Sum of all drivers = Ending value
```

### Text-Based Waterfall Format

When a charting tool is not available, present as a text waterfall:

```
WATERFALL: Revenue — Q4 Actual vs Q4 Budget

Q4 Budget Revenue                                    $10,000K
  |
  |--[+] Volume growth (new customers)               +$800K
  |--[+] Expansion revenue (existing customers)      +$400K
  |--[-] Price reductions / discounting               -$200K
  |--[-] Churn / contraction                          -$350K
  |--[+] FX tailwind                                  +$50K
  |--[-] Timing (deals slipped to Q1)                 -$150K
  |
Q4 Actual Revenue                                    $10,550K

Net Variance: +$550K (+5.5% favorable)
```

### Bridge Reconciliation Table

Complement the waterfall with a reconciliation table:

| Driver | Amount | % of Variance | Cumulative |
|--------|--------|---------------|------------|
| Volume growth | +$800K | 145% | +$800K |
| Expansion revenue | +$400K | 73% | +$1,200K |
| Price reductions | -$200K | -36% | +$1,000K |
| Churn / contraction | -$350K | -64% | +$650K |
| FX tailwind | +$50K | 9% | +$700K |
| Timing (deal slippage) | -$150K | -27% | +$550K |
| **Total variance** | **+$550K** | **100%** | |

*Note: Percentages can exceed 100% for individual drivers when there are offsetting items.*

### Waterfall Best Practices

1. Order drivers from largest positive to largest negative (or in logical business sequence)
2. Keep to 5-8 drivers maximum — aggregate smaller items into "Other"
3. Verify the waterfall reconciles (start + drivers = end)
4. Color-code: green for favorable, red for unfavorable (in visual charts)
5. Label each bar with both the amount and a brief description
6. Include a "Total Variance" summary bar

## Budget vs Actual vs Forecast Comparisons

### Three-Way Comparison Framework

| Metric | Budget | Forecast | Actual | Bud Var ($) | Bud Var (%) | Fcast Var ($) | Fcast Var (%) |
|--------|--------|----------|--------|-------------|-------------|---------------|---------------|
| Revenue | $X | $X | $X | $X | X% | $X | X% |
| COGS | $X | $X | $X | $X | X% | $X | X% |
| Gross Profit | $X | $X | $X | $X | X% | $X | X% |

### When to Use Each Comparison

- **Actual vs Budget:** Annual performance measurement, compensation decisions, board reporting. Budget is set at the beginning of the year and typically not changed.
- **Actual vs Forecast:** Operational management, identifying emerging issues. Forecast is updated periodically (monthly or quarterly) to reflect current expectations.
- **Forecast vs Budget:** Understanding how expectations have changed since planning. Useful for identifying planning accuracy issues.
- **Actual vs Prior Period:** Trend analysis, sequential performance. Useful when budget is not meaningful (new business lines, post-acquisition).
- **Actual vs Prior Year:** Year-over-year growth analysis, seasonality-adjusted comparison.

### Forecast Accuracy Analysis

Track how accurate forecasts are over time to improve planning:

```
Forecast Accuracy = 1 - |Actual - Forecast| / |Actual|

MAPE (Mean Absolute Percentage Error) = Average of |Actual - Forecast| / |Actual| across periods
```

| Period | Forecast | Actual | Variance | Accuracy |
|--------|----------|--------|----------|----------|
| Jan | $X | $X | $X (X%) | XX% |
| Feb | $X | $X | $X (X%) | XX% |
| ... | ... | ... | ... | ... |
| **Avg**| | | **MAPE** | **XX%** |

### Variance Trending

Track how variances evolve over the year to identify systematic bias:

- **Consistently favorable:** Budget may be too conservative (sandbagging)
- **Consistently unfavorable:** Budget may be too aggressive or execution issues
- **Growing unfavorable:** Deteriorating performance or unrealistic targets
- **Shrinking variance:** Forecast accuracy improving through the year (normal pattern)
- **Volatile:** Unpredictable business or poor forecasting methodology
