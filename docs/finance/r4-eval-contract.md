# r4 Finance Evaluation Contract

Status: v3 draft-frozen for the next r4 live evaluation and rescore pass. The
default evaluator remains the r3 contract unless `--r4` is passed. Historical
v2 outputs remain v2 records and must not be overwritten.

## Contract name

`r4-requirements-evidence-completion-v3`

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
4. The latest requirement sequence must precede the final draft. A selected
   final run may predate the latest requirement only when semantic reuse is
   proven by persisted requirement fingerprints.
5. The final draft quality payload must assess the latest requirements and pass
   both requirement coverage and provenance.
6. A persistent completion receipt must exist for the final draft, bind to the
   latest requirements, match the final draft content hash, and have status
   `complete` for complete analyses.
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
9. The latest requirement record must include `semantic_fingerprint` and a
   non-empty `semantic_basis`. The production semantic basis version is `1` and
   covers the question, context id, scope, source aliases with dataset/source/data
   hashes, removed item ids, and canonical items including metric, dimensions,
   sorted periods, and drilldown requirement.
10. Every selected final run must persist `requirements_id` and
    `requirements_semantic_fingerprint`. The scorer accepts a run only when its
    fingerprint equals the latest requirement fingerprint and the bound original
    requirement record exists with a matching fingerprint and semantic basis.
    The scorer rebuilds the canonical semantic basis from the requirement
    record's actual question, context id, scope, bindings, items, and removed
    item ids, then verifies the rebuilt source/data hashes against
    `analysis.state()` dataset metadata. It recomputes the fingerprint from that
    rebuilt basis instead of trusting the stored fingerprint alone. Fresh and
    older selected runs both require `bindings`, `input_hashes`, and
    `source_hashes` to match the bound requirement sources. Older run records
    additionally require the bound requirement sequence to precede the run.
    Records without this proof are rejected instead of being treated as
    implicitly compatible.

## What this contract does not score

Human financial-manager calibration remains a separate review artifact. The r4
machine scorer can prove numeric support, scope coverage, source traceability,
and completion receipts; it cannot honestly claim expert judgment quality
without human labels.

Missing-data cases are scored differently from complete analysis cases. When
the fixture truth says a required calculation cannot be performed, r3 keeps its
historical rule that the expected diagnostic must come from a calculation run.
For r4/v3, a model may instead stop after the backend has verified the input
gap and saved the final draft; the scorer accepts that no-calculation path only
after the full `awaiting_input` contract below passes. This avoids rerunning a
known-impossible native price/quantity calculation while still rejecting
invented output cells. The completion receipt must bind to the latest
requirements, match the final draft content hash, include `response_status:
ended_with_limitations`, `stop_reason: verified_input_gap`, `repair_allowed:
false`, and preserve `original_requirements_completed: false`. The draft must
state explicit limitations.

For `awaiting_input`, a status name alone is insufficient. The scorer also
requires numeric checks to pass, remaining requirement items to be marked
`missing_data`, each remaining item to carry an `input_gap`, and the latest
requirement support snapshot to contain a matching `requires_input` item. The
gap proof must use a scorer-supported gap code; v3 currently accepts
`native_price_quantity_fields_unavailable`. The proof must include stable
missing-input column groups and source snapshot hashes, including `data_hash`,
that match the bounded dataset metadata in `analysis.state()`. The dataset
schema must be present, claimed source columns must match that schema, claimed
missing columns must actually be absent from it, and any non-gap unresolved
quality issue rejects `awaiting_input`. A case must not be marked complete by
pretending that missing quantity, price, or source rows are zero.

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

For v3, record the scorer revision hash separately from the v2 freeze record.
Rescoring a historical v2 observation under v3 is allowed only as a new scoring
artifact that keeps the original observation immutable and the first-attempt
denominator unchanged.

The first-attempt denominator is the selected case count. Timeouts, provider
terminal errors, missing attempts, and ordinary scoring failures remain in that
denominator; they are reported separately from provider retry events and repair
receipts. Do not claim the 90% workflow target until a full r4 live run produces
`workflow_status: passed`, `hard_errors_status: passed`, and no failures under
this contract.
