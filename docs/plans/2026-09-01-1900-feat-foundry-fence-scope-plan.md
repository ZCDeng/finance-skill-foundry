---
title: Foundry Fence Scope - Plan
type: feat
date: 2026-09-01
topic: foundry-fence-scope
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: user-directed
execution: code
extends: 2026-08-30-2100-feat-foundry-task-chain-plan.md
---

# Foundry Fence Scope - Plan

Addendum to `2026-08-30-2100-feat-foundry-task-chain-plan.md`. That plan owns U7–U12 and
built the fence. This one draws its edge: what the fence is actually for, what it was
accidentally also doing, and where it stops. R1–R9 and KTD1–KTD9 are unchanged; KTD10 below
is new and constrains U11's preset.

## Goal Capsule

- **Objective:** A finance manager using this product can do the work a finance manager does —
  including reading something published outside this window — without the fence either
  refusing it or letting it be mistaken for this period's arithmetic.
- **Means:** Every figure carries where it came from. The fence stops being a rule about what
  the model may know and becomes a rule about what a number may claim.
- **Product authority:** R7 (a figure on the brief is derivable from the locked catalog)
  stands verbatim. It was never a rule that the brief may contain nothing else; it was read
  as one.
- **Execution profile:** code. `foundry/references.py`, `foundry/tags.py`, `basis` on
  `brief_facts.json`, `app/electron/harness/workspace.ts`.
- **Stop conditions:** Do not give the period preset a shell, a file tool, or a subagent. Do
  not let external material into `我重算`. Do not make the app a second mutator.

---

## Ground Truth

Three facts established 2026-09-01, two by reading the runtime and one by running a real
month's close against a 24-sheet workbook.

### G9. Every session stood at the root of the disk — gap, now closed

`dsh-host-apiproxy` resolves a session's working directory as
`workspace?.path ?? payload.cwd ?? defaults.cwd`, and `defaults.cwd` is `process.cwd()`. The
app created sessions without a `cwd` and was itself launched from the Finder, so the measured
answer was `/`. An authoring session carries the stock editor and shell; those were standing
at the root of the machine.

Closed by `app/electron/harness/workspace.ts`: one directory per task under the app's own
`userData`, created before the session that stands in it. Deliberately not the window
directory — a window holds `inputs/`, the archived books the fence exists to stop a model
reading around.

### G10. The fence had no way to say "someone else published this" — gap, now closed

The August close carried thirteen industry benchmarks — 82% collection, 106 days' turnover, a
17.4% provision rate — into the analysis with no source and no date on any of them, because
the period preset had no verb that would take one. The only vocabulary available was the
lock's own three words, so material from outside either got smuggled in wearing `我重算` or
was left out of the document that needed it.

Closed by `record-reference` and the `外部引用` mark. What makes it safe is not that it is
scarce, it is that it is marked: source and date are required, `RESERVED_WORDS` are refused in
the text, and `_facts()` filters `basis == "lock"` so a cited line can never be quoted back as
this window's arithmetic.

### G11. A reference is asked for after the brief, not before — verified

The moment a leader asks how a figure compares to the industry is while they are reading the
brief. The first version of `record_reference` allowed only `Locked`, which is exactly the
window in which nobody has yet seen a number worth comparing. Widened to `QUERYABLE`; past the
brief it lands on the workpaper and files a deliverable version, the same road a follow-up
takes.

---

## Key Decisions

- **KTD10. The period fence is about provenance, not about ignorance** `(session-settled:
  user-directed — she asked whether the lock was drawn too tight for a human finance manager,
  and named Youmind's separation of harness / task / deliverable as the shape that works)`.
  A figure must say where it came from. It does not have to come from the catalog. Two
  vocabularies, kept apart by construction:

  | Basis | Marks | Written by |
  | --- | --- | --- |
  | `lock` | `报表声称` `我重算` `两者一致` | the catalog, through `foundry/` |
  | `external` | `外部引用` | the analyst, through `record-reference`, with a source and a date |

  Instantiates R7. Supersedes nothing; it names what R7 always said.

- **KTD11. What stays out of `period`, permanently.** Measured against upstream's `standard`
  preset, `period` deletes six rows and keeps the rest verbatim:

  | Deleted row | What it would have given the session |
  | --- | --- |
  | `tool-bash` | a shell |
  | `tool-pwsh` | a shell, on Windows |
  | `tool-fs` | read and write any path |
  | `tool-fs-search` | find any path |
  | `tool-jobs` | background processes outliving the turn |
  | `delegation` | subagents, forks, codex, claude-code, workflow, ralph |

  A second belt sits at the profile: `period.omit` names `bash`, `dsh-tool-fs`,
  `str-replace-editor` and `read_document` by their runtime names, and `sandbox: read-only`
  with `cwd_writable: false` under them. None of this is up for reconsideration when a
  scenario gets harder. The line is not "what could a careful analyst use safely" — it is
  **structural versus procedural**:

  - A structural capability changes what a figure can be traced to. `record-reference` adds a
    kind of figure and a required provenance; the trail is still complete afterwards.
  - A procedural capability changes what the model can reach. A shell or a file reader lets a
    session read the archived workbook directly, and a number obtained that way is
    indistinguishable, in the brief, from one the catalog produced. There is no mark that
    fixes this, because the mark would be applied by the same session that went around.

  `tool-web` stays on, and belongs to the structural side: what it returns can only enter the
  document through `record-reference`, which demands a source and refuses the lock's words.
  Web access with no reference verb is what produced the thirteen unsourced benchmarks in G10.
  `planning` and `tool-todo` stay for the same reason — they change how the session thinks,
  not what it can reach.

- **A session's cwd is named by the app, never inherited.** `ensureTaskWorkspace` before
  `session.create`, one directory per task, never the window. Instantiates KTD2.

---

## Scope Boundaries

**Not in this work**

- Office / spreadsheet plugins in the harness (`dsh-univer-office`). Read and assessed, not
  installed. Third-party plugin code runs with the operator's full privileges, and the
  decision to accept that is the user's, not a packaging change. If it is ever bundled,
  `DO_NOT_TRACK=1` goes in `harnessEnv` explicitly — our operators do not get to make that
  choice for themselves.
- A leader-operated session. KTD7 stands.
- Re-emitting a brief after a late reference. The brief is what was known when it was written;
  the workpaper is what was learned since. Conflating them would make the version trail lie.

**Risks**

- `外部引用` is a mark an operator has to learn. It is documented in `method/FOUNDRY.md`, drawn
  as its own chip in the reader, and named in the period persona; nothing else teaches it.
- The reference text is free prose. `RESERVED_WORDS` stops it borrowing the brief's marks, but
  a wrong benchmark with a real source is still wrong. That is a review problem, and the
  source and date are what make review possible.
