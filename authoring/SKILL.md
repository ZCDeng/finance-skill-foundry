---
name: finance-analysis-skill
description: Author a portable finance analysis skill. Method and 整理重点 only. This-window questions live on the window, not in this file.
---

# Finance analysis skill (authoring)

You are helping a finance manager author a portable analysis skill on the **pinned FA Foundry harness**.

## Write only

- Method: how she names tables, locks a window, and writes this-window questions.
- 整理重点: what this manager emphasizes. The executable form is the analysis map, not a rewritten chart of accounts.

## Do not write

- This-window questions into the skill tree (`questions.md` / `questions.json` are forbidden here).
- Period numbers, lock files, or Formulator cache.
- Provider keys.

## Done

Foundry `mark_done` validates the legacy capability contract and runs the model-free engine fixture. Its receipt separates `contract_status=valid`, `engine_status=passed`, and `method_status=not_executed`. It does not execute the authored instructions or certify that the method works. A method needs its own actual scenario execution before being described as verified. New analysis tasks can run directly and optionally save a method afterwards.

`python -m foundry.probe --var VAR --fixtures FIXTURES` and `foundry --var VAR probe --fixtures FIXTURES` are the same gate and report the same thing: `0` passed, `3` refused with the reason on stderr, `2` for an argparse usage error.

Required `foundry.json`:

```json
{
  "schema": "finance-skill-foundry/f2-skill@1",
  "capability": "f2-period-analysis",
  "period_tools": ["import", "lock", "record-questions", "emit-brief", "query-locked"],
  "safety": {
    "questions_in_window": true,
    "no_read_document_books": true,
    "tag_followups": true
  },
  "method_docs": ["FOUNDRY.md", "CONNECTORS.md"]
}
```

## Period loop the skill must run

1. Import chart of accounts, optional auxiliary dimensions, analysis map, and named statements. A units file may still be imported as a shortcut dim of aux. She may paperclip-drop those files; pass the `@` paths (or the upload folder) to `import`. Do not `read_document` a GL or map — that dumps rows into the model. Uploads are not books.
2. Lock. Empty CoA or a zero-row named table refuse lock. Missing aux or map still locks; a provided empty aux/map refuses.
3. She writes this-window questions on the window. One question answers from one named table; a question naming two named tables is refused.
4. Emit a conclusion brief. A map-cut question aggregates by analysis node and tags `我重算`. Some items may be `not-in-this-window`. The same lock write writes a calculation workpaper (`workpaper.md`) she can tick: account + aux + amount, plus unmapped and conflicts. The model does not draft that file.
5. Leader follow-up recomputes from the brief's window id and tags `稿外追问` / `我重算`. `split_by=analysis_node` reads the locked map; a window without map refuses.

## Bundled method skills

The kit ships four close methods under `method/`. They are not this authored skill and must not receive this-window questions.

- `financial-statements` — P&L / balance sheet / cash flow from locked named tables
- `reconciliation` — GL to bank, subledger, or intercompany
- `variance-analysis` — decompose a locked total or analysis-node cut
- `journal-entry` — draft a balanced entry for review; do not post

Inside foundry they follow `method/FOUNDRY.md`: numbers from the lock only.
