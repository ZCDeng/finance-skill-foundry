# Workbook Bindings Contract

This contract covers stage 3 file collaboration. It is a file round-trip backend for validated `.xlsx` templates and independent result workbooks. It is not proof of live Excel host integration, recalculation, or Office.js add-in behavior.

## API Surface

`foundry.workbook_bindings` exposes five service-facing functions:

- `inspect_workbook(path, bindings=None)` returns workbook SHA-256, sheet names, named ranges, tables, unsupported features, and optional resolved binding ranges with baseline cell hashes.
- `create_binding_contract(path, source, fields, role="input", writable=False, header=True, binding_id=None)` validates a table, named range, or explicit sheet/range and records the resolved address plus baseline hashes.
- `read_input(path, contract)` reads declared fields from the bound area using field policy and unit metadata.
- `preview_output_patch(path, contract, writes, baseline_hashes=None)` validates write targets, normalizes Excel-safe cell values, and returns a structured diff with conflict flags.
- `apply_output_patch(path, destination, patch, resolutions=None)` writes chosen cells to a copy or creates an independent result workbook when the source is not safe for automatic rewrite.

All functions operate on local files and return plain dictionaries. They do not mutate the source workbook in place.

## Binding Sources

A binding source must be one of:

- `{"kind": "table", "name": "InputTable"}`
- `{"kind": "named_range", "name": "ResultCell"}`
- `{"kind": "range", "sheet": "Model", "range": "G1:H20"}`

The resolved source must be one rectangular range within Excel bounds, with at most 256 columns and 100,001 rows including an optional header row.

## Field Policy

Each field has `name`, `policy`, and optional `unit`.

- `policy: "amount"` or `"decimal"` treats values as exact decimal quantities. Values that survive Excel numeric serialization are written as numeric cells so formulas such as `SUM()` can use them.
- Decimal values that exceed safe Excel numeric precision are written as exact text with a `decimal_written_as_text` diagnostic.
- `policy: "identifier"` or `"long_identifier"` reads and writes text. Numeric identifier cells produce an `identifier_not_text` diagnostic because leading zeros and long IDs are not recoverable once Excel stores them as numbers.
- Formula-like text beginning with `=`, `+`, `-`, or `@` is stored as a string cell and returns a `formula_like_text` diagnostic.

## Conflict Handling

Contracts store baseline cell hashes for declared binding ranges. `preview_output_patch()` compares those hashes with the current workbook. If a writable target changed after binding, the patch marks that cell as a conflict.

`apply_output_patch()` refuses unresolved conflicts. Callers must pass per-cell resolutions:

- `"apply"` writes the proposed value to the copy.
- `"keep"` preserves the manager-edited value in the copy.

Preauthorized result regions can pass `"apply"` for known conflict cells and continue refreshing without touching cells outside the declared writable range.

## Supported Rewrite Boundary

Automatic copy rewriting is limited to workbooks without macros, external links, drawings, or charts. For those supported templates, the backend writes a copy and relies on openpyxl to preserve ordinary workbook structure, styles, formulas outside the writable range, tables, and named ranges.

When the source archive contains macro projects, external links, drawings, or charts, the backend does not rewrite the whole workbook. `apply_output_patch()` produces an independent `Results` workbook containing the chosen output values and returns `mode: "independent_result_workbook"`.

## Non-Claims

This backend does not claim that Excel, WPS, or another host has recalculated formulas. It does not inspect live workbook state inside Excel. Native Excel collaboration remains a separate stage with its own host verification.
