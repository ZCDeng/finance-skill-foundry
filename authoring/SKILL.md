---
name: finance-analysis-skill
description: Author a portable finance analysis skill. Method and 整理重点 only. This-window questions live on the window, not in this file.
---

# Finance analysis skill (authoring)

You are helping a finance manager author a portable analysis skill on the **pinned DeepSeek harness**.

## Write only

- Method: how she names tables, locks a window, and writes this-window questions.
- 整理重点: what this manager emphasizes. The executable form is the analysis map, not a rewritten chart of accounts.

## Do not write

- This-window questions into the skill tree (`questions.md` / `questions.json` are forbidden here).
- Period numbers, lock files, or Formulator cache.
- Provider keys.

## Done

Foundry `mark_done` is the only done signal. It runs the model-free fixture probe (`foundry.probe`). Chat satisfaction is ignored. Cursor "validate then proceed" is the pattern, not the host.

## Period loop the skill must run

1. Import chart of accounts, optional auxiliary dimensions, analysis map, and named statements. A units file may still be imported as a shortcut dim of aux.
2. Lock. Empty CoA or a zero-row named table refuse lock. Missing aux or map still locks; a provided empty aux/map refuses.
3. She writes this-window questions on the window.
4. Emit a conclusion brief. A map-cut question aggregates by analysis node and tags `我重算`. Some items may be `not-in-this-window`. The same lock write writes a calculation workpaper (`workpaper.md`) she can tick: account + aux + amount, plus unmapped and conflicts. The model does not draft that file.
5. Leader follow-up recomputes from the brief's window id and tags `稿外追问` / `我重算`. `split_by=analysis_node` reads the locked map; a window without map refuses.

## Bundled method skills

The kit ships four close methods under `method/`. They are not this authored skill and must not receive this-window questions.

- `financial-statements` — P&L / balance sheet / cash flow from locked named tables
- `reconciliation` — GL to bank, subledger, or intercompany
- `variance-analysis` — decompose a locked total or analysis-node cut
- `journal-entry` — draft a balanced entry for review; do not post

Inside foundry they follow `method/FOUNDRY.md`: numbers from the lock only.

