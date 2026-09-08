# Financial documents: implementation contract

Approved scope: management reports, visual editing, DOCX/PDF/HTML/Markdown/XLSX import and export. Follow the annual-report hierarchy and restrained financial tables; reading follows theme, print is white A4 with 20 mm margins. Preserve original numbers, sources, draft revisions, and financial validation. No collaboration, PPTX, cloud conversion or bundled OCR model.

## Sequence and ownership

1. Protect existing draft/export/financial behavior with regression tests.
2. Backend: versioned document validation and deterministic Markdown, immutable source snapshots and export receipts, structured Excel, CLI contracts.
3. Converters: offline import and DOCX/HTML/PDF rendering, explicit conversion warnings and isolation.
4. Frontend: Tiptap editor, reading/outline/print preview, import preview, five-format export.
5. Integrate and test genuine report/workbook round trips, hostile and failed inputs, native UI and printed pages. Push verified commit, install and verify /Applications/FA Foundry.app, then remove superseded bundles.

## Shared document contract

`ReportDocument = {schema_version:1, template_version:'annual-v1', metadata:{company,period,currency,unit}, content:ReportNode[], sources?:ReportSource[]}`.

Nodes follow Tiptap names: doc (only transient editor wrapper), paragraph, heading (level 1–6), text, hardBreak, bulletList, orderedList, listItem, blockquote, codeBlock, horizontalRule, table, tableRow, tableCell, tableHeader, image, reportNote, reportPageBreak. Marks: bold, italic, strike, code, link, underline. Table cells retain colspan/rowspan/colwidth and textAlign. Table attrs may contain caption, unit, period; note attrs contain id; image attrs contain src (bounded local PNG/JPEG data URL), alt, title. Node source attrs can hold source_id/page/sheet/range. Numeric contents remain text; formatting must not round them.

`ReportSource = {id:string, name:string, sha256:string, format:'docx'|'pdf'|'html'|'md'|'xlsx'}`. Original source bytes are task-owned backend snapshots, not in renderer working copies.

Saved draft optional `document: ReportDocument`. Backend validates and derives `body`; client body cannot override projection. An explicit body-only revision of a rich document invalidates inherited document structure. Legacy body-only drafts remain unchanged on read/export. Include document in new content hashes. Imported content does not inherit external review/claims.

## Desktop API contract

`reportImport(task, options?:{sourceId?:string, sheet?:string, range?:string, ocr?:boolean})` opens native file picker when no sourceId, snapshots via backend and returns `{cancelled?, document?, title?, warnings:string[], source?:ReportSource, sheets?:string[], needsReview?:boolean}`. Reusing sourceId permits sheet/range selection and OCR retry. No renderer-supplied paths.

`reportSource(task, sourceId)` returns `{source, data_base64}` for original PDF comparison. `reportCancel(task)` cancels this window/task's conversion. `reportPreview(task, document, title)` returns `{html:string}` using the exact export template without headers/footers injected from arbitrary imports. `analysisExport(task,id,format)` gains the five-format union; existing method name retained.

Electron converts only, Foundry owns formal record writes. Conversion modules operate on supplied bytes/document and return bytes/HTML and warnings. New backend CLI operations: `report-source-add --path`, `report-source-read --source`, `report-export-register --draft --format --path`, `report-xlsx-read --source [--sheet --range]`. Source read result includes task-resolved path for Electron, never accepted from renderer. Existing analysis-export md/xlsx remains supported. `analysis-draft --spec-file` supports larger structured drafts without argv limits.

## Acceptance

Regression: legacy exact appendix handling, save-as-new-version, quality checks, existing MD/XLSX exports. New: deterministic projection and integrity, merged cells/notes/images, Unicode and exact decimals, five-format round trips, long/wide tables, headings with following content, image/font completion, cancellation, corrupt/oversized files, missing formula caches, OCR unavailable/partial and inert imported HTML. Use the supplied property workbooks without modifying originals. Final acceptance is the installed native bundle and actual export files, not build success alone.
