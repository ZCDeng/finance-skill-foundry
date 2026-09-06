# Finance Files Contract

`foundry.finance_files.FinanceFiles` is the task-scoped service wrapper for stage 3 workbook file collaboration. It composes `AnalysisStore` datasets with `foundry.workbook_bindings` and persists workbook binding, patch, and output records under `analysis/finance/workbook_*`.

This contract does not add CLI, DSH, UI, Office.js, or native Excel host behavior.

## API Surface

Construct the service with a task:

```python
service = FinanceFiles(task, snapshot_ids=None)
```

When `snapshot_ids` is supplied, every dataset and referenced run must stay inside that session ceiling.

The public methods accept plain dictionaries:

- `inspect({"dataset_id": id})`
- `bind({"dataset_id": id, "source": source, "fields": fields, "role": role, "writable": bool, "header": bool, "parent_id": optional_id})`
- `read({"binding_id": id, "dataset_id": optional_newer_snapshot_id})`
- `preview({"binding_id": id, "dataset_id": optional_newer_snapshot_id, "writes": writes, "run_id": optional_run_id})`
- `apply({"patch_id": id, "resolutions": {"A2": "keep" | "apply"}})`

The service never accepts arbitrary workbook input paths or caller-chosen destinations. Source paths are resolved from authorized `AnalysisStore` XLSX snapshots at `analysis/datasets/<dataset_id>/source.xlsx`. Output paths are generated inside the task at `analysis/finance/workbook_outputs/files/<output_id>.xlsx`.

## Persisted Records

Binding records capture:

- dataset ID, source hash, and source workbook name
- workbook binding contract from `workbook_bindings`
- field policy, role, writable flag, header mode, and parent binding ID

Patch records capture:

- binding ID and dataset ID used for preview
- source hash at preview time
- immutable write request and rendered cell patch
- run verification status per write

Output records capture:

- patch ID, binding ID, dataset ID, source hash
- generated filename, artifact path, absolute local path, and SHA-256
- applied and kept cells
- diagnostics and run verification copied from the saved patch

Records use the existing `AnalysisStore` integrity hash and task sequence. Apply operations hold the task lock while creating the output workbook and committing the output record.

## Newer Snapshots

`read` and `preview` may receive a newer `dataset_id`. The service verifies that snapshot against the same task/session authorization and still uses the old binding contract baseline hashes. This lets a manager compare a refreshed workbook against the original binding and choose conflict resolutions explicitly.

## Run Verification

`preview` can attach a `run_id`. The run must be readable in the task and its dataset bindings must include the target workbook snapshot. For a write to be marked `matches_run`, it must include `result_row`, `result_column`, and `value`, and the supplied value must match the actual run result cell.

Writes without a run ID, or without result coordinates, are marked `manager_write_unverified`. They are still allowed, but the service does not claim calculation verification for them.

## Safety Rules

- Cross-task dataset IDs fail because `AnalysisStore.read_dataset` cannot resolve their task-owned source files.
- Session ceilings fail before inspecting, binding, reading, previewing, or applying unauthorized snapshots.
- Saved patch tampering fails the `AnalysisStore` integrity check before output generation.
- Source workbooks must be XLSX snapshots already accepted by `AnalysisStore.add_dataset`.
- Original snapshot files are never mutated. `apply` writes a generated task-owned workbook output.
- Conflict behavior, numeric/text cell policy, unsupported workbook fallback, source hash staleness, and destination overwrite refusal are delegated to `workbook_bindings`.
