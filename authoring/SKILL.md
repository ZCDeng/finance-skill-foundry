---
name: finance-analysis-skill
description: Author a portable finance analysis skill. Method and 整理重点 only. This-window questions live on the window, not in this file.
---

# Finance analysis skill (authoring)

You are helping a finance manager author a portable analysis skill on the **pinned DeepSeek harness**.

## Write only

- Method: how she names tables, locks a window, and writes this-window questions.
- 整理重点: what this manager emphasizes.

## Do not write

- This-window questions into the skill tree (`questions.md` / `questions.json` are forbidden here).
- Period numbers, lock files, or Formulator cache.
- Provider keys.

## Done

Foundry `mark_done` is the only done signal. It runs the model-free fixture probe (`foundry.probe`). Chat satisfaction is ignored. Cursor "validate then proceed" is the pattern, not the host.

## Period loop the skill must run

1. Import chart of accounts, operating units, and named statements.
2. Lock. Empty names or a zero-row named table refuse lock.
3. She writes this-window questions on the window.
4. Emit a conclusion brief. Some items may be `not-in-this-window`.
5. Leader follow-up recomputes from the brief's window id and tags `稿外追问` / `我重算`.
