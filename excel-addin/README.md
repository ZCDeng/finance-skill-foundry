# Finance Foundry Excel Add-in

This is a classic Office.js Excel taskpane for local use with the stdlib bridge in `foundry.excel_bridge`.

The add-in serves static assets and bridge APIs from the same local HTTPS origin. The taskpane persists a workbook identity in `Office.context.document.settings`, registers real Excel bindings, imports bound input ranges as immutable analysis snapshots, creates a finance context from the latest distinct input bindings in that workbook, previews output-cell changes, and applies only bridge-authorized cell writes inside a preauthorized output binding.

The manager-facing taskpane uses Chinese finance scope fields for `ledger`, `organization`, `period`, `currency`, `unit`, and `scenario`. JSON is still available for advanced field and metric specs. The simple metric selector covers `account_total`, `management_pnl`, `ratio`, and `control_totals` with accounts and dimensions fields.

## Local setup commands for real host testing

Generate a localhost manifest for the bridge port after wiring `foundry.excel_bridge.add_parsers(sub)` into the root CLI:

```bash
foundry --var /path/to/var excel-bridge-manifest --port 8765 > excel-addin/manifest.local.xml
```

The module entry point keeps the same operation available for development:

```bash
python -m foundry.excel_bridge manifest --port 8765 > excel-addin/manifest.local.xml
```

Create a protected bridge secret file outside shell history and argv:

```bash
umask 077
openssl rand -hex 32 > /tmp/foundry-excel-bridge.secret
```

Issue a task/session-bound token:

```bash
foundry --var /path/to/var excel-bridge-token \
  --task <task-id> \
  --session excel \
  --secret-file /tmp/foundry-excel-bridge.secret
```

Serve the add-in and API over same-origin HTTPS:

```bash
foundry --var /path/to/var excel-bridge-serve \
  --port 8765 \
  --certfile /path/to/localhost.pem \
  --keyfile /path/to/localhost-key.pem \
  --secret-file /tmp/foundry-excel-bridge.secret
```

The bridge does not create or trust certificates, sideload manifests, launch Excel, or change Office settings. On macOS, classic add-in sideloading can use the workbook add-ins folder under `~/Library/Containers/com.microsoft.Excel/Data/Documents/wef`. See Microsoft’s sideloading guide for Mac: <https://learn.microsoft.com/en-us/office/dev/add-ins/testing/sideload-an-office-add-in-on-mac>.

## Reusable real-host verification workbook

Root integration also provides `tools/verify_excel_host.py` for repeatable Mac Excel host acceptance. The tool builds a synthetic `.xlsx` fixture with the Office developer registry reference used by Microsoft Office-Addin-Scripts templates, so opening the workbook can auto-load this taskpane without relying on the add-ins picker UI. A typical root-run command is:

```bash
python tools/verify_excel_host.py \
  --fixture build/excel-host/host.xlsx \
  --manifest excel-addin/manifest.xml
```

The expected host acceptance proof is workbook-level, not just bridge API health: input/import/run/preview/apply should leave `B2=130`, `D2=40`, `G2=40`, `H2=80`, preserve the notes/formula/chart areas, and record host telemetry.

## API contract used by `taskpane.js`

All API requests use a bearer token issued by `excel-bridge-token`. Every POST body includes `workbook_id`; the workbook id is created and persisted by Office document settings in the host workbook.

- `GET /api/context` returns the task/session context, workbook buckets, recent host telemetry, finance datasets/contexts, and authorized successful finance runs for the current session snapshots.
- `POST /api/register-workbook` records workbook identity and host/API support telemetry metadata. Workbook URL is stored only as a hash.
- `POST /api/telemetry` records bounded host operation events such as ready, register, import, run, preview, apply, recalc, and save.
- `POST /api/register-bindings` registers real Office.js binding metadata and server-computed baseline hashes from the current cells. Output bindings marked `dedicated_area` become preauthorized write areas. The manager-facing management template adapts to the selected table headers, so a normal two-column `management_account`/`amount` range imports with organization, period, currency, unit, and scenario supplied by scope fields.
- `POST /api/import-binding` imports only an input binding matrix into a new immutable snapshot. It preserves existing session snapshots and all latest distinct input bindings for the workbook finance context. Child sessions cannot import new Excel snapshots.
- `POST /api/run-metric` delegates to the existing `FinanceStore` metrics path with the current session context.
- `POST /api/preview-output` accepts selected output writes and current cell snapshots. The bridge ignores caller-supplied baselines, uses the registered baseline including formulas, and returns conflicts plus exact typed cell values.
- `POST /api/apply-output` requires the same workbook, binding, range, preview id, current cell hashes, and explicit conflict resolutions. It returns only selected cells to write; Office.js applies them one cell at a time so nonselected formulas, styles, charts, and manual cells remain untouched.
- `POST /api/ack-output` is called only after Office.js `context.sync()` succeeds. It accepts the preview id plus actual snapshots for applied cells, verifies the addresses and values match the authorized writes, and then advances baseline hashes for those cells only.

## Office.js host APIs

The taskpane checks `Office.context.requirements.isSetSupported("ExcelApi", "1.1")` before using `Excel.Binding.getRange()`. Full workbook recalculation uses `context.application.calculate(Excel.CalculationType.full)`. Workbook save checks ExcelApi 1.11 before calling `context.workbook.save(Excel.SaveBehavior.save)`.

Microsoft references:

- Excel add-ins and workbook APIs: <https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-workbooks>
- ExcelApi 1.11 requirement set, including `Workbook.save`: <https://learn.microsoft.com/en-us/javascript/api/requirement-sets/excel/excel-api-1-11-requirement-set>
