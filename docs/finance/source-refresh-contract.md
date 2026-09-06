# Source Refresh Contract

Status: implemented for local file refresh and injectable transport tests. Real ERP tenant integration is unverified until a named product/version, authorized ledger, and control-total reconciliation evidence exist.

`foundry.source_refresh` publishes immutable `SourceBatch` records under the task analysis root and creates one AnalysisStore dataset snapshot for each successful non-duplicate batch. Existing analysis runs keep their original dataset bindings, so later refreshes cannot rewrite historical results.

Dataset snapshots created by this module carry `metadata.source_refresh.source_batch_id`. The matching committed batch is `analysis/source_batches/<source_batch_id>.json`; readers should treat the dataset as visible only when that batch is integrity-checked, has `publication_status: "published"`, and its `dataset_id` matches the dataset being read.

## Scope

Each refresh is bounded by a `SourceScope`:

- source product identity: `source_id`
- tenant, ledger, organization, accounting period, calendar, currency, cutoff
- refresh mode: `full_period` or `incremental`

Prior-batch lookup uses a stable source identity: source, tenant, ledger, organization, period, currency, and calendar. `cutoff_at` and `mode` are batch attributes, so a next-day cutoff refresh still compares against the previous snapshot for the same ledger scope.

Credentials are not part of the scope. Secrets must remain inside the adapter transport and are rejected if they appear in discovery payloads, rows, checkpoints, or persisted records.

## Transport Adapter

An adapter implements:

- `describe() -> SourceDescription`: declared product, version, and capabilities
- `discover(scope) -> dict`: non-secret connection facts such as visible ledgers or organizations
- `pull_page(scope, cursor, checkpoint) -> SourcePage`: one ordered page of rows

The transport is generic and injectable. The current contract does not claim Kingdee, Yonyou, or any other ERP is connected. Vendor capability must be proven against that vendor's own product/version and tenant permission.

## File Identity Policy

File refresh supports two explicit policies:

- `business_key`: rows must provide stable `document_id` and `line_id` values. This enables row-level duplicate, update, delete, and void handling.
- `snapshot_only`: ordinary balance, budget, or planning files may omit document/line keys. The system dedupes the exact same file by file hash; a changed file creates a whole new snapshot. Row-level inserted, updated, deleted, voided, and unchanged counts are recorded as `unknown_snapshot_only`.

The default remains `business_key` for file inputs with genuine row identity. `snapshot_only` must be selected explicitly by the caller. It does not infer row ordinals as business keys and must not be described as complete incremental sync.

## Publication Rules

Publication is batch-oriented:

- same file bytes produce an identifiable duplicate batch pointing to the prior snapshot; no second dataset is added
- changed files or changed transport rows create a new dataset snapshot
- failed pagination, retry exhaustion, auth failure, or row validation failure publishes no source batch
- checkpoints are written only after a successful publish
- previous datasets and runs remain immutable
- duplicate checks and prior-snapshot lookup are repeated while holding the task lock
- if publication is interrupted after dataset metadata is written but before the batch commit, the staged dataset folder is removed before the error is returned
- batch IDs are allocated before dataset materialization and written into dataset metadata as `metadata.source_refresh.source_batch_id`; the source batch commit remains the final publication marker

Rows are deduped by the business key:

`source_system`, `ledger_id`, `organization_id`, `document_id`, `line_id`

Exact duplicate rows in a batch are counted and ignored. Conflicting rows with the same business key in the same batch are refused because the adapter must provide an ordered update or a stable current row. File imports using `business_key` must provide an explicit document and line key; row ordinal is not inferred as a stable business key.

Rows that declare source, ledger, organization, period, or currency values must match the selected scope. Mismatches are refused before publication to prevent cross-ledger or cross-organization leakage.

## Updates And Deletions

Refresh output records explicit row states:

- `active`
- `deleted`
- `void`

For `full_period`, a previously active row missing from the next period reconciliation is carried forward as a deleted tombstone with `_source_deleted_by_reconciliation`.

For `incremental`, adapters with deletion capability may send explicit deleted or void rows. If an incremental source lacks deletion support, the batch declares `period_full_reconciliation_required`; the system must not market that source as complete incremental deletion sync.

## Retry And Pagination

Pagination is validated by sequence and cursor:

- page sequence starts at 1 and increments by 1
- returned cursor must match the requested cursor
- non-last pages must advance to a new next cursor
- cursor cycles are refused
- page count and total pulled rows are bounded

Rate limits, transient errors, timeouts, and connection errors are retried with a bounded attempt count. Authentication errors are not retried.

## Verification

The synthetic G6 contract lives in `tests/test_source_refresh.py` and covers A16-A18:

- duplicate file refresh, changed file snapshots, and old-run freezing
- duplicate page rows, retry, replay idempotence, missing/out-of-order page refusal, and no partial publish on failure
- explicit update, delete, void, and unsupported incremental deletion policy
- credential rejection from persisted records
- changed cutoff with stable source identity
- simultaneous duplicate import lock recheck
- interrupted publication cleanup
- cursor-cycle and scope-mismatch refusal
