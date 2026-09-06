# r4 Finance Evaluation Contract

Status: v2 frozen for r4 live evaluation rescore and subsequent live runs. The
default evaluator remains the r3 contract unless `--r4` is passed.

## Contract name

`r4-requirements-evidence-completion-v2`

## Scope

The r4 contract scores the full finance analysis workflow, not only arithmetic
correctness. It keeps the existing Decimal truth checks, final draft text checks,
forbidden unsupported causal certainty scan, exact-zero handling, hard error
accounting, and denominator policy. Timeouts and failed turns remain in the
workflow denominator.

## Additional r4 checks

1. The final scored draft must be persisted.
2. A versioned analysis requirement record must exist before the final draft.
3. The final draft must bind to the latest requirement version.
4. The latest requirement sequence must precede the final draft and selected
   final runs.
5. The final draft quality payload must assess the latest requirements and pass
   both requirement coverage and provenance.
6. A persistent completion receipt must exist for the final draft, bind to the
   latest requirements, match the final draft content hash, and have status
   `complete`.
7. Required source drilldown may be proven by observed successful `drilldown_fact`
   calls or by immutable `evidence_checks` written during automatic save.
8. `evidence_checks` used as source proof must match the cited run, row, column,
   output hash, bound snapshot source hashes, source row identities, and complete
   pagination metadata. The official `analysis.state()` dataset records are
   `meta.json` snapshots containing fields such as `id`, `source_hash`, and
   `row_count`; they do not include row arrays. Row identity bounds are therefore
   verified against positive integer `row_count`. If future scoring needs source
   cell contents, it must use an existing source-fetch/read path rather than
   manufacturing rows inside the scorer.

## What this contract does not score

Human financial-manager calibration remains a separate review artifact. The r4
machine scorer can prove numeric support, scope coverage, source traceability,
and completion receipts; it cannot honestly claim expert judgment quality
without human labels.

Missing-data cases are scored differently from complete analysis cases. When
the fixture truth says a required calculation cannot be performed, the scorer
requires the expected diagnostic, rejects invented output cells, and expects a
persisted draft limitation plus a `needs_review` completion receipt with repair
stopped. Such a case must not be marked `complete` by pretending that missing
quantity, price, or source rows are zero.

## v2 freeze record

Recorded on 2026-09-06 after replacing row-array assumptions with official
`analysis.state()` dataset metadata validation. The scorer revision and fixture
validation artifacts are:

```text
bbf15ab80c1ba628a578c07294fd98345f614a1b1aea0e718ca608d63890b9b9  tools/verify_finance_evals.py
36cbda2977e3e36884274afd486478971a25ce7b4e4cdaf1cb0d7ffa1d722dca  tests/test_finance_evals.py
3778d1b6006de5d3d9fb6d7a1c88c156b7d69141c5eecf4dc8f56b207c0a6906  build/verification/r4-eval-contract-v2-20260906-220052/fixture-summary.json
```


## Invocation

Legacy/r3 scoring:

```bash
.venv/bin/python tools/verify_finance_evals.py --output build/verification/run --live
```

r4 scoring:

```bash
.venv/bin/python tools/verify_finance_evals.py --r4 --output build/verification/r4-run --live
```

r4 blind-suite live command, keeping the configured model contract
`deepseek-official / deepseek-v4-flash / max` unchanged:

```bash
.venv/bin/python tools/verify_finance_evals.py \
  --r4 \
  --fixture tests/fixtures/finance_evals/r4_blind_cases.json \
  --cases-limit 20 \
  --timeout-seconds 420 \
  --output build/verification/r4-blind-live-YYYYMMDD-HHMMSS \
  --live
```

Rescore an existing observation with the r4 contract:

```bash
.venv/bin/python tools/verify_finance_evals.py --r4 --rescore-observation build/verification/source --output build/verification/r4-rescore
```

Before a live run, validate the frozen fixture shape without invoking a model:

```bash
.venv/bin/python tools/verify_finance_evals.py \
  --r4 \
  --fixture tests/fixtures/finance_evals/r4_blind_cases.json \
  --cases-limit 20 \
  --validate-fixture-only \
  --output build/verification/r4-eval-contract-YYYYMMDD-HHMMSS
```

Current r4 blind fixture hash for the fixture file; v2 changes only the scoring
contract and does not mutate blind fixture content:

```text
c76fab049d977b01c89e34eb14d4bf6fe52be5296af16b1ffa4c48c18cba8f22  tests/fixtures/finance_evals/r4_blind_cases.json
```

Current v2 scorer revision hash should be recorded with each freeze or rescore. A
live first-attempt observation started under v1 may be rescored under v2 while
preserving its original first-attempt denominator and timeout records; it must
not be rerun and represented as the original attempt.

The first-attempt denominator is the selected case count. Timeouts, provider
terminal errors, missing attempts, and ordinary scoring failures remain in that
denominator; they are reported separately from provider retry events and repair
receipts. Do not claim the 90% workflow target until a full r4 live run produces
`workflow_status: passed`, `hard_errors_status: passed`, and no failures under
this contract.
