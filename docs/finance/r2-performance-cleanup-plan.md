# R2 Performance Cleanup Plan

Date: 2026-09-06. Scope: A25 snapshot SQL staging and timeout behavior only.

## Current Constraint

`foundry/analysis_sql.py::execute_sql` validates SQL and relationship contracts before creating in-memory DuckDB tables. The current staging path builds Python tuples and inserts each row through `executemany`, which made the 100,000-row cold query median 117.1204 seconds in the stage-0 benchmark. Import itself is already below target, so this pass must not change `AnalysisStore.add_dataset`, source parsing, source hashes, loaded hashes, finance fixture truth, relationship validation, or SQL capability validation.

## Intended Change

Use DuckDB's JSON ingestion path to stage trusted, already-normalized snapshot rows from a process-owned temporary NDJSON file, then cast those string-loaded columns into the exact declared table schema. `enable_external_access` is available only for this internal staging load; before user SQL runs, set it back to `false` and then lock configuration. If a dataset has no rows, keep the explicit schema-only table creation path.

Timeout handling must cover validation, relationship checks, staging, execution, and fetching. The timer should be armed before expensive work begins, interrupt the same connection, and report a timeout consistently if the deadline expires during loading or querying.

In-memory typed-array staging was measured and rejected. With `enable_external_access=false`, `UNNEST(?::TYPE[])` preserved VARCHAR, DECIMAL, NULL, Unicode, and leading-zero codes on small samples, but it took about 2.42 seconds for only 5,000 rows using parameter casts and did not complete the 100,000-row probe in the performance window. That is far slower than the temporary NDJSON path, which staged and queried 100,000 rows in about one second.

The accepted risk is narrow: the connection starts with `enable_external_access=true` only so DuckDB can read the agent-created temporary NDJSON staging file. User SQL is parsed first, table aliases are still restricted to bound snapshots, and file/network functions remain forbidden by `validate_sql`. After staging, the same connection executes `SET enable_external_access=false` followed by `SET lock_configuration=true`; tests cover that user SQL cannot call file readers.

## Preservation Checks

- DECIMAL schema remains explicit, including `DECIMAL(38,s)`.
- Empty strings and missing values remain `NULL`; string columns preserve Unicode and leading zeros.
- Relationship checks, join-key validation, mixed currency/unit checks, and forbidden file/network SQL functions remain unchanged.
- `SET lock_configuration=true` remains the final configuration change before user SQL execution.
- `tools/benchmark_finance_baseline.py` remains the immutable stage-0 baseline. New measurements go to new `r2-performance-*` evidence files.

## Verification

Before edit: run the existing numeric/security relationship tests that protect the current behavior.

After edit: add focused staging tests for DECIMAL/null/text preservation, forbidden SQL, relationship checks, and loading timeout. Then run targeted Python tests plus the A25 benchmark with at least five 100,000-row repetitions, including import, cold query, hot query, peak RSS, and bounded cancellation evidence.
