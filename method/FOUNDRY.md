# Foundry fence for bundled method skills

Eight skills ship with the foundry kit: four close methods and four routing packs (`setup`, `close`, `bva`, `cash`, registered in `packs.json`). They are not the authored portable skill and they are not this-window questions.

- The trusted preset or session selects the runtime fence. User wording alone must not switch a session into analysis, period, F3, or any wider tool set.
- Analysis preset: does not require a locked Window. Start from the current task's registered datasets, use multi-table SQL/Python when the evidence needs it, record dataset versions and run IDs, and write editable drafts through the analysis draft tools. A finance manager may revise materiality, currency, accounting policy, assumptions, and narrative judgment; ordinary reads, calculations, reruns, and drafts do not require per-tool approval.
- Period and F3 presets: keep the old locked-window and single named-table contract. Numbers come from the locked window catalog only. Do not invent trial-balance rows. Paperclip uploads are an import drop; do not `read_document` a GL or map. One question answers from one named table. `coa` / `aux` / `map` / `units` only shape the cut. A question naming two named tables is refused at `record-questions` and at `query-locked`; split it into one question per table.
- `~~erp` / `~~data warehouse` stay placeholders unless this session has configured and named those services. File-backed analysis remains valid when no connector is configured.
- Do not write `questions.md` or `questions.json` into `authoring/` or `var/skills/`.
- Do not post journal entries. Foundry does not own the ERP.
- A map-cut or recompute is tagged `我重算`. A follow-up not on the brief is tagged `稿外追问`. The full tag vocabulary is below.
- A benchmark, a policy, a peer's number: file it with `record-reference` and it lands under `外部引用` with its source and the date you found it. A figure with no source and no date is not a reference, it is a rumour, and the call is refused.
- The tickable schedule is `workpaper.md` on the window, not a second workbook.
- In the analysis preset, use the native skill tool for the applicable method, then `method-resource` with that skill ID to read FOUNDRY.md. For variance decomposition and price/volume/mix closure, also read model-checks.md before the first calculation or missing-input diagnostic. CONNECTORS.md does not replace either resource; read it only for connection questions. Wait for successful reads before calculating, without concurrent calculation or retrospective read claims. Keep the Markdown links for hosts that can read relative references directly.

## Analysis-mode finance tools

Professional guidance has four shared resources, readable by all eight existing
entry IDs through the same fixed `method-resource` allowlist:
[accounting-basis.md](accounting-basis.md) for F01/F12 scope and evidence,
[close-checklist.md](close-checklist.md) for F02–F05/F07 close work,
[forecast-models.md](forecast-models.md) for F06/F08–F10 models, and
[model-checks.md](model-checks.md) for F11/K01–K24 check coverage.
Load the relevant resource successfully before its dependent calculation and
retain its hash in the observed trace. A failed or late read is not skill-first
evidence. Do not force all four resources on unrelated non-finance requests.
[support-matrix.json](support-matrix.json) separates implementation, deterministic
checks, actual-model evaluation and named human review; it grants no authority.

When the analysis preset is active, stay skill-first: load the relevant method skill and companion notes, then inspect the registered finance context before choosing tools. Use `list_finance_context` to see current datasets, contexts, maps, scenarios, saved metric definitions, and the available finance capabilities.

For uploaded files that are not yet registered as finance context, use `finance_source_refresh` only for file-backed snapshots. Ordinary budget, balance, and statement files without real document and line identifiers should use `file_identity_policy: "snapshot_only"`; document-line exports with genuine source keys may use `"business_key"`. Save the resulting bindings and explicit scope with `finance_context_save`, and save an account map with `finance_map_save` when presentation or rollup logic depends on it. A file refresh publishes a new immutable source version; it does not rebind old runs, infer row-level deletes from row order, or claim a live ERP connector.

Before calculation, save the current question contract with `analysis_requirements_save`: the business question, scope, required metrics, and requested drilldowns. After the applicable method reads and before that registration, professional-rule requirements must create or select a real finance context covering every original source binding and use its returned context ID. Explicit bindings must match the full context, including background sources. An ordinary requirement without professional-rule dependencies may still use bindings alone. The accepted requirements must precede both calculations and missing-input diagnostics. A nonempty semantic fingerprint by itself does not establish valid professional identity: inspect the returned professional state and support preflight, resolve missing or mismatched identity, and keep genuine manager approval blocks. Revisions use `parent_id` and a reason; removing an item does not make the original question complete. Keep analytical purpose in the question; put a field in source scope only when the bound source or verified finance scope actually declares that dimension. Resolve a rejected registration before running any diagnostic or calculation. A run made before the accepted requirements cannot answer a later registration.

Read the registration support and use its native execution contract when available. For full-ledger totals use `run_metric` with `control_totals`; for a specific ledger account register that real account identity and use account_total with the same accounts. A generic amount query or a renamed result column does not prove a registered account metric. For structured aggregates, `result_key_columns` must equal `group_by`; use the documented parameter contract instead of inventing SQL placeholders. Ensure the finance context covers every dataset binding in the registered question before dependent calculations. If a diagnostic names a missing binding, correct the context for the original requirement; do not remove an original binding or requirement to make coverage pass. After correcting scope, context or text, prepare and save the current explanation again. A successful action after a failed save is not a completed delivery until the new save verifies it. Reuse unchanged successful runs and avoid repeating source arithmetic in prose when the bound fact placeholders or prepared tables already carry it.

A service completion flag alone is not accounting recognition evidence. Establish whether the entity receives or provides the service, its economic nature, obligation or contractual right, period and account basis before giving a definite expense, asset, revenue, liability or journal-entry conclusion. A numerical reconciliation difference can be valid while recognition direction remains unresolved. Preserve that distinction; approval status alone neither proves nor negates an economic obligation, and an adjustment draft grants no posting authority.

For high-frequency analysis, prefer the finance tools when their contract matches the question: `run_metric` for management P&L, ratios, account totals, and control totals; `explain_variance` for supported profit bridges or price/quantity explanations; `finance_scenario_save` and `finance_scenario_run` for saved scenario comparisons. For receivables aging, use native `inputs.status_filter` when the manager asks for disputed, active, paused, or other status cuts; the status mapping must come from the source adapter or manager, and current status is not historical status evidence. Use `drilldown_fact` only against run rows and source-backed cells that can be traced to the run's own bindings; pass `section: "rows"`, `"detail_rows"`, or `"excluded_detail_rows"` for aging summaries, included invoices, or excluded invoices. Continue to use SQL/Python for layouts, reconciliations, joins, or analytics the finance tools do not cover.

## Analysis-mode explanations

Before drafting, call `prepare_explanation` with the successful `run_ids` that answer the registered requirements. This returns stable facts bound to the run output and source scope, including exact values, display values, units, semantics, evidence groups, and automatic supporting tables. Ordinary SQL results are supported. Choose relevant material facts; do not mechanically narrate every table cell. Inspect the referenced source cells through `drilldown_fact` where source tracing is available.

Use `save_explanation_draft` with `fact_ids` and `{{fact:FACT_ID}}` placeholders for amounts in `body`; the service renders display values and binds exact calculation claims automatically. Existing manual claims with real `run_id`, `row`, `column`, and `value` remain valid. Keep exact arithmetic separate from rounded display. For ratios, declare numerator and denominator accounts and their signs. For period comparisons, bind both periods explicitly even when both sides use the actual scenario. Distinguish `amount_change` from `profit_impact`: higher costs reduce profit. Never replace missing comparison data with zero without an explicit, disclosed policy.

Use `finance_background_list` to reuse applicable business context within the authorized task, ledger, organization, and effective period. Save manager-provided context with `finance_background_save` and its explicit scope and effective dates. Classify manager assumptions and judgment as `user_assumption` or `professional_judgment`; source facts need an authorized dataset and a matching passage. External references require source and retrieval date. Expired context and context from another ledger are not evidence for the current explanation. An arithmetic contribution is not evidence of an operational cause.

Write for management reading, not for tool logs. Start with one or two short conclusion paragraphs that state the conclusion and material financial impact; each paragraph should carry one theme. Keep `{{fact:FACT_ID}}` placeholders exactly where the amount appears in the prose, formula, or table cell: they are numeric placeholders, not citation numbers; ratio and percentage rows follow the number rules below. Use comparison tables or bullet lists for multiple drivers, conditions, or uncertainties instead of a long comma chain. Put complete formulas, bridge equations, ratio arithmetic, and basis notes in an independent paragraph or small table. Put source references in chapter-end footnotes such as `[^1]`, with the source location and retrieval date where applicable. Attach each condition or uncertainty to the related judgment. Do not invent causes, actions, zero-fill policies, sources, or approvals. Numbers follow three rules: hand-typed amounts and counts carry thousands separators (325,644.00 万元); amount rows use a `{{fact:FACT_ID}}` placeholder kept as it is, even when its rendered decimals look long or it lacks thousands separators; ratio rows and rows whose unit is `%`, `pct` or `百分比` use no placeholder: write the percentage by hand and give its claim `basis: calculation`, `run_id`, `row`, `column`, `value`, `fact_id` and a `presentation` (`decimal_places`, `rounding: half_up`, `scale: percent` for a ratio row and `identity` for a `%`/`pct`/`百分比` row) so the service rechecks it; any other hand-typed rounded number carries a presentation too (`scale: identity`); a hand-typed number equal to the fact's value or display value needs no presentation; write a negative value with its minus sign (-6.85%). A `比率`/`ratio` result row is a decimal and is written as a percentage in prose (94.53%); a `%`, `pct` or `百分比` row already is a percentage and is written as its display value plus `%` (3.30%), never multiplied by 100; a `百分点` difference row is written as 3.30 个百分点. A wide-table `*_pct` column is written as a percentage (3.30%), and a long-table row holding the difference of two ratios uses the `百分点` unit. Do not add a note that ratios are shown as decimals. Run descriptions, assumptions and prose name metrics, scenarios, currency and unit in manager words, not field names such as `metric_key`.

Call `validate_explanation` on the current draft, and use the `quality` plus `completion` returned by `save_explanation_draft` as the bounded finishing state. The finance quality status checks facts, numbers, provenance, requirements, and claims; separate readability suggestions help improve paragraphing, formulas, and notes but do not change financial pass/fail status or block ordinary draft saving. If `completion.repair_allowed` is true, repair only the affected text, citations, source check, or calculation, reusing successful runs; allow at most two repair-and-check rounds. Use the returned current requirement and source diagnostics to choose the next action. After a requirement revision, rerun affected calculations under that version, prepare with the resulting current run set, and save with that same set. Do not reattach an earlier diagnostic run. A repaired tool action still needs a fresh successful save; `repair_available` is not delivery. Keep narrative short, use verified fact placeholders, and avoid unsupported numeric lists. At a terminal receipt return exactly `final_response` without another tool call. If `completion.stop_reason` is `no_progress`, data is missing, or issues remain, preserve the editable draft and name the concrete gap. Checks do not certify business judgment or imply manager approval. A manager edit must be checked as current text; an old passed result must not carry over to changed text.

## Analysis-mode report visuals

When a chart clarifies the comparison, load [report-visuals.md](report-visuals.md) with `method-resource` using the current skill ID. This adapts selected diagram-design and huashu-report methods to Foundry; only comparison bars, trend lines, and explanatory flows are supported. Use tables for exact lookup or dense data, and prose for a single number.

For numeric visuals, first archive a successful task-owned run through `chart_deliverable_save`, then pass a structured `document` to `save_explanation_draft` with a `reportVisual` block referencing the returned `chart_id`. Select existing columns and a declared common unit; the service freezes the original values, run and snapshot identity. Never pass hand-filled series, arbitrary SVG, HTML, file paths or external data URLs. Preserve negative values, zero and missing values distinctly, and do not silently truncate categories or mix incomparable units. Keep the figure, supported takeaway, unit and source together. Flows describe author analysis, not calculation evidence or proven causality; they do not replace claims or source checks. Normal document text keeps fact placeholders and current-draft validation.

## Exit codes

Every foundry entry point (`foundry`, `python -m foundry.probe`) uses the same three.

| Code | Means |
| --- | --- |
| `0` | Done |
| `2` | Usage error from argparse: an unknown flag or a missing required one. A caller bug |
| `3` | Domain refusal: the window is not locked, the table is not in this window, the drop escaped its directory. Advance the period loop, do not retry the same call |

The dsh plugin turns `3` into an `Error` named `FoundryRefusal` with `refused: true`; anything else keeps `FoundryError`. Branch on that, not on the stderr text.

## Output tags

Every tag the foundry emits into a brief is one of these six. A reader parsing a brief may rely on this list and on nothing else.

The first three are the lock's own words, and only the locked catalog may wear them. `外部引用` is the one tag on a figure this window did not compute; it is the reason the other three stay trustworthy.

| Tag | Means |
| --- | --- |
| `报表声称` | The total the source table claims for itself, copied through unchanged |
| `我重算` | The total recomputed from the locked window catalog |
| `两者一致` | The claimed total and the recomputed total agree |
| `稿外追问` | A follow-up that is not on the brief |
| `外部引用` | A figure from outside this window, carrying who published it and when it was found. Never recomputed here, never counted as this period's arithmetic |
| `not-in-this-window` | A required table is absent from this window, so the answer is refused |

## Bundled skills

The four close methods carry the workflow. The four packs only route a question onto those methods and the finance tools; none of them is a gate for `run_metric`, and none adds posting, payment, or an ERP connection.

| Skill | Use when |
| --- | --- |
| `financial-statements` | Build P&L / balance sheet / cash flow commentary from task datasets or locked named tables |
| `reconciliation` | Tick GL to bank, subledger, or intercompany from task datasets or locked tables |
| `variance-analysis` | Decompose a total or analysis-node cut against budget or another period |
| `journal-entry` | Draft a balanced entry for review; do not post |
| `setup` | Pack: route a new session; suggest `finance_readiness` and report what can run and what is blocked |
| `close` | Pack: route period close onto the four methods; management P&L, tie-outs, and journal drafts, not a live ledger close |
| `bva` | Pack: route budget variance onto `variance-analysis` and `explain_variance` |
| `cash` | Pack: route receivables aging and 13-week cash onto `finance_scenario_save` / `finance_scenario_run`; no payment tool |
