# Finance Baseline Fixtures

This document describes the r2 stage 0 finance baseline fixtures under `tests/fixtures/finance_baseline/`. The files are intentionally static inputs for future tests and evaluation. They do not add a finance domain model and do not change runtime behavior. They prepare coverage for A01-A09; they do not complete those acceptance items.

## Contents

- `scenarios/service_ledger.csv` and `scenarios/service_budget.csv` cover a service company management P&L, budget bridge, prior-period comparison, AR aging, cash delay, and multi-organization controls.
- `scenarios/commerce_ledger.csv` and `scenarios/commerce_budget.csv` cover a goods sales company price/quantity bridge with explicit unit and currency.
- `scenarios/multi_org_ledger.csv` covers organization, period, currency, unit, debit/credit direction, leading-zero account codes, duplicates, changed rows, and deleted rows.
- `scenarios/account_map_conflicts.csv` captures mapping conflicts, parent-child overlap, and manager resolution hints.
- `scenarios/g5_account_movements.csv` covers same-account opening balance, period debit, period credit, ending balance, credit-normal signed policy, red-letter, closing-transfer, adjustment-period, and unposted rows.
- `scenarios/g6_source_identity.csv` covers one voucher with multiple lines, the same document number across ledgers, duplicate pull, changed row, and deleted row identity cases.
- `expected_truth.json` records fixed truth values for G1-G6 and control totals.

`cases.json` is left untouched because it is used by live model-session verification.

## Prepared Coverage

The fixtures prepare inputs for future A01-A09 tests:

- A01: control totals by organization, period, currency, unit, and management account.
- A02: actual analysis remains possible when only balance-level data exists.
- A03: duplicate mapping, parent-child overlap, and manager resolution are explicit.
- A04: leading-zero account codes, auxiliary dimensions, organizations, currencies, and units are represented.
- A05: debit and credit normal-balance policy is visible and must not be reduced to `abs`.
- A06: G1 service-company budget bridge closes to profit variance `+5`.
- A07: G2 goods-sales price/quantity bridge closes to revenue variance `+32`.
- A08: multi-organization and relationship inputs are available for future join-cardinality checks.
- A09: actual, budget, plan, period, unit, and stock/flow semantics are explicit in fixture metadata.

Known gaps before A01-A09 can be implemented as complete tests:

- G4 currently has overdue and not-yet-due receivables only. Subsequent receipt, partial write-off, and credit memo cases are deferred to later receivables/cash scenario work.
- A08 future join-cardinality tests may still need purpose-built one-to-many and many-to-many fixture pairs when those tests are written.

## A25 Benchmark

`tools/benchmark_finance_baseline.py` generates a temporary 100,000-row ledger, imports it through `AnalysisStore.add_dataset`, saves a fixed SQL profit query, runs it through `AnalysisStore.run_analysis`, and reports five-run medians for import wall time and cold-query wall time. The query is the first run for each newly imported dataset, so it is a cold/first-query baseline, not a hot-query claim.

The script records process RSS high-water mark from `resource.getrusage(RUSAGE_SELF)`. In a 5-iteration run this is cumulative for the benchmark process; use separate processes if an independent per-run RSS peak is required. The script also records CPU count, physical memory when available, platform, Python version, fixture hashes, and an independently computed expected profit from the generated row pattern. A failed run or wrong profit exits non-zero.

Example:

```bash
python3 tools/benchmark_finance_baseline.py --output /tmp/foundry-finance-baseline.json
```

The benchmark measures the current snapshot import and SQL path. It is not a claim about future ERP refresh, Excel host refresh, or dedicated finance tools.

## Local Baseline Run

Latest local run on this machine:

- Command: `python tools/benchmark_finance_baseline.py --output /tmp/foundry-finance-baseline-a25.json`
- Rows: 100,000 generated CSV rows; 5 iterations.
- Machine: macOS arm64, Python 3.14.4, 10 CPUs, 24 GiB physical memory.
- Truth check: every run returned profit `250110`, matching the independent generator rule for 华东 / 2026-08 / CNY / 元.
- Median import wall time: 1.5748917089949828 seconds.
- Median cold-query wall time: 117.12043275000178 seconds.
- Median process high-water RSS after cold query: 439730176 bytes.

The import median is below the initial 30-second target. Hot-query and cancellation latency were not measured, so A25 is not marked passed. The 117-second first-query median exposes a path that needs optimization; it is not a measurement of the 3-second hot-query target. Raw measurement is retained in `r2-stage0-benchmark.json` alongside this document.

The source file limits remain 32 MiB, 100,000 rows and 256 columns. Saved SQL result limits are 1–10,000 rows (default 1,000); input size and returned result size are separate limits.

A bounded 5,000-row cProfile follow-up returned the expected profit `12530`: import 0.0928 seconds, first query 7.824 seconds. `_duckdb.executemany` accumulated 7.781 seconds (97.9% of the profiled run), identifying Python row-wise snapshot staging as the first optimization target. The intended follow-up is trusted bulk ingestion with explicit DECIMAL types and unchanged user SQL restrictions, followed by fresh cold/hot/cancel measurements.
