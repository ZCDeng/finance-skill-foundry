# Foundry fence for bundled method skills

These four close methods ship with the foundry kit. They are not the authored portable skill and they are not this-window questions.

- The trusted preset or session selects the runtime fence. User wording alone must not switch a session into analysis, period, F3, or any wider tool set.
- Analysis preset: does not require a locked Window. Start from the current task's registered datasets, use multi-table SQL/Python when the evidence needs it, record dataset versions and run IDs, and write editable drafts through the analysis draft tools. A finance manager may revise materiality, currency, accounting policy, assumptions, and narrative judgment; ordinary reads, calculations, reruns, and drafts do not require per-tool approval.
- Period and F3 presets: keep the old locked-window and single named-table contract. Numbers come from the locked window catalog only. Do not invent trial-balance rows. Paperclip uploads are an import drop; do not `read_document` a GL or map. One question answers from one named table. `coa` / `aux` / `map` / `units` only shape the cut. A question naming two named tables is refused at `record-questions` and at `query-locked`; split it into one question per table.
- `~~erp` / `~~data warehouse` stay placeholders unless this session has configured and named those services. File-backed analysis remains valid when no connector is configured.
- Do not write `questions.md` or `questions.json` into `authoring/` or `var/skills/`.
- Do not post journal entries. Foundry does not own the ERP.
- A map-cut or recompute is tagged `我重算`. A follow-up not on the brief is tagged `稿外追问`. The full tag vocabulary is below.
- A benchmark, a policy, a peer's number: file it with `record-reference` and it lands under `外部引用` with its source and the date you found it. A figure with no source and no date is not a reference, it is a rumour, and the call is refused.
- The tickable schedule is `workpaper.md` on the window, not a second workbook.
- In the analysis preset, load these companion notes with `method-resource` using the current skill ID and `resource: FOUNDRY.md` or `resource: CONNECTORS.md`. Keep the Markdown links for hosts that can read relative references directly.

## Analysis-mode finance tools

When the analysis preset is active, stay skill-first: load the relevant method skill and companion notes, then inspect the registered finance context before choosing tools. Use `list_finance_context` to see current datasets, contexts, maps, scenarios, saved metric definitions, and the available finance capabilities.

For uploaded files that are not yet registered as finance context, use `finance_source_refresh` only for file-backed snapshots. Ordinary budget, balance, and statement files without real document and line identifiers should use `file_identity_policy: "snapshot_only"`; document-line exports with genuine source keys may use `"business_key"`. Save the resulting bindings and explicit scope with `finance_context_save`, and save an account map with `finance_map_save` when presentation or rollup logic depends on it. A file refresh publishes a new immutable source version; it does not rebind old runs, infer row-level deletes from row order, or claim a live ERP connector.

Before calculation, save the current question contract with `analysis_requirements_save`: the business question, scope, required metrics, and any requested drilldowns. Revisions use `parent_id` and a reason; removing an item does not make the original question complete.

For high-frequency analysis, prefer the finance tools when their contract matches the question: `run_metric` for management P&L, ratios, account totals, and control totals; `explain_variance` for supported profit bridges or price/quantity explanations; `finance_scenario_save` and `finance_scenario_run` for saved scenario comparisons. For receivables aging, use native `inputs.status_filter` when the manager asks for disputed, active, paused, or other status cuts; the status mapping must come from the source adapter or manager, and current status is not historical status evidence. Use `drilldown_fact` only against run rows and source-backed cells that can be traced to the run's own bindings; pass `section: "rows"`, `"detail_rows"`, or `"excluded_detail_rows"` for aging summaries, included invoices, or excluded invoices. Continue to use SQL/Python for layouts, reconciliations, joins, or analytics the finance tools do not cover.

## Analysis-mode explanations

Before drafting, call `prepare_explanation` with the successful `run_ids` that answer the registered requirements. This returns stable facts bound to the run output and source scope, including exact values, display values, units, semantics, evidence groups, and automatic supporting tables. Ordinary SQL results are supported. Choose relevant material facts; do not mechanically narrate every table cell. Inspect the referenced source cells through `drilldown_fact` where source tracing is available.

Use `save_explanation_draft` with `fact_ids` and `{{fact:FACT_ID}}` placeholders in `body`; the service renders display values and binds exact calculation claims automatically. Existing manual claims with real `run_id`, `row`, `column`, and `value` remain valid. Keep exact arithmetic separate from rounded display. For ratios, declare numerator and denominator accounts and their signs. For period comparisons, bind both periods explicitly even when both sides use the actual scenario. Distinguish `amount_change` from `profit_impact`: higher costs reduce profit. Never replace missing comparison data with zero without an explicit, disclosed policy.

Use `finance_background_list` to reuse applicable business context within the authorized task, ledger, organization, and effective period. Save manager-provided context with `finance_background_save` and its explicit scope and effective dates. Classify manager assumptions and judgment as `user_assumption` or `professional_judgment`; source facts need an authorized dataset and a matching passage. External references require source and retrieval date. Expired context and context from another ledger are not evidence for the current explanation. An arithmetic contribution is not evidence of an operational cause.

Write the conclusion and its material financial impact first, then the largest drivers, supported reasons, and a specific next action or missing evidence. Call `validate_explanation` on the current draft, and use the `quality` plus `completion` returned by `save_explanation_draft` as the bounded finishing state. If `completion.repair_allowed` is true, repair only the affected text, citations, source check, or calculation, reusing successful runs; allow at most two repair-and-check rounds. If `completion.stop_reason` is `no_progress`, data is missing, or issues remain, preserve the editable draft and name the concrete gap. Checks do not certify business judgment or imply manager approval, and never block ordinary draft saving. A manager edit must be checked as current text; an old passed result must not carry over to changed text.

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

| Skill | Use when |
| --- | --- |
| `financial-statements` | Build P&L / balance sheet / cash flow commentary from locked named tables |
| `reconciliation` | Tick GL to bank, subledger, or intercompany using locked tables |
| `variance-analysis` | Decompose a locked total or analysis-node cut |
| `journal-entry` | Draft a balanced entry for review; do not post |
