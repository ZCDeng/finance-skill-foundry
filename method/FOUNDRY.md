# Foundry fence for bundled method skills

These four close methods ship with the foundry kit. They are not the authored portable skill and they are not this-window questions.

- Numbers come from the locked window catalog only. Do not invent trial-balance rows. Paperclip uploads are an import drop; do not `read_document` a GL or map.
- `~~erp` / `~~data warehouse` stay placeholders unless this window has named those tables.
- Do not write `questions.md` or `questions.json` into `authoring/` or `var/skills/`.
- Do not post journal entries. Foundry does not own the ERP.
- A map-cut or recompute is tagged `我重算`. A follow-up not on the brief is tagged `稿外追问`. The full tag vocabulary is below.
- A benchmark, a policy, a peer's number: file it with `record-reference` and it lands under `外部引用` with its source and the date you found it. A figure with no source and no date is not a reference, it is a rumour, and the call is refused.
- The tickable schedule is `workpaper.md` on the window, not a second workbook.
- One question answers from one named table. `coa` / `aux` / `map` / `units` only shape the cut. A question naming two named tables is refused at `record-questions` and at `query-locked`; split it into one question per table.

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
