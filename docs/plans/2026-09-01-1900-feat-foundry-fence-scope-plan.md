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

- **KTD12. A companion's tools are global, so the close seat needs a scope of its own**
  `(session-settled: user-directed — she asked for the Office plugin so that reading a
  deliverable feels like the spreadsheet software a finance manager actually uses)`.
  `dsh-univer-office@0.2.12` is staged into `extra/dsh` and named in the profile. It
  registers thirteen `univer_*` tools at profile level, and a preset built by deleting rows
  cannot delete a row it never had — so `period` gets `period-scope`, which calls
  `ctx.tools.restrict({deny})` with all thirteen, the same seam `f3-scope` uses.

  Measured on a real boot (`test_the_office_tools_reach_the_authoring_seat_and_not_the_close_seat`):
  `standard` is offered all thirteen, `period` and `f3` none.

  All thirteen rather than a careful subset, for two different reasons. `univer_execute` runs
  arbitrary Facade JavaScript and takes an absolute `codeFile`, and `univer_import` reads an
  xlsx off disk into a unit — both are reach in the plain sense. The other eleven fail the
  provenance test instead: a figure typed into a cell and exported is neither `我重算`, since
  no catalog produced it, nor `外部引用`, since nobody published it. The bundle's own skills
  teach exactly that, including editing a percentage by string replacement.

  Two switches are set on the operator's behalf because they cannot set them themselves:
  `DO_NOT_TRACK=1` and an empty `UNIVER_TELEMETRY_ENDPOINT`. This build already ships an empty
  endpoint; a later one could bake one in.

- **KTD13. The workbook is written by `foundry`, from the two files the documents are
  written from** `(session-settled: user-directed — 做吧，从锁库写 xlsx)`. `foundry/sheet.py`
  renders `brief_facts.json` and `schedules.json`; so do `brief.md` and `workpaper.md`.
  Three renderings of one set of facts cannot disagree, three computations of them could.
  Nothing in `sheet.py` computes.

  Two rules the format forces. An xlsx number is binary64, so a figure that does not
  survive a `Decimal -> float -> Decimal` round trip goes in as text, exact, rather than as
  a number a spreadsheet would round — the symmetric answer to `catalog.py` refusing to
  import such a value. And an account code is written as text, because it is an identifier
  that happens to be digits and 0501 is not 501.

  The `条目 / 标签 / 依据` columns repeat on every row. A heading above a block is a markdown
  idea; filtering a 400-row schedule for `我重算` has to hand back rows that still say what
  they belong to.

  It is a button, not a tool. Rendering a locked window computes nothing, so a model could
  hold it without touching the fence — but it would only be doing what the operator can ask
  for the moment they want the file, and `export:xlsx` stays an operator's cause in the
  timeline rather than a model's.

- **KTD14. A window and a conversation each belong to exactly one task**
  `(session-settled: user-directed — 修跨任务洞)`. Two calls could reach across the task
  chain, and both reproduced on a real store before the guards existed:

  | Door | What happened |
  | --- | --- |
  | session | a session recorded on task A recomputed against B's catalog, landed on both session lists, and B grew a workpaper version caused by a conversation held about A |
  | window | `--task A query-locked --brief-window <B's>` put B's window in A's chain while that window's back-pointer still said B |

  Neither broke provenance — both figures were derivable from the lock they named and both
  wore `稿外追问`. What broke was the timeline: a version on a task, from a conversation that
  task never had.

  The window door was an asymmetry, not an oversight in principle. `Window.bind_task` has
  always refused to move a back-pointer that is set; `Task.bind_window` had no such guard,
  and adoption skipped the first check entirely when the window was already owned. The two
  directions of one binding now refuse on the same rule. The session door is `record_session`
  refusing a conversation another task already holds — on the writer, because that is the one
  place the row is appended.

  Adoption on touch is unchanged: a window nobody owns still joins the first task that
  reaches it. The rule only fires when a second claimant appears.

- **KTD15. What a call archived is reported by the side that archived it**
  `(session-settled: user-directed — 做题一 foundry 那一半)`. `emit-brief`, `query-locked`
  and `record-reference` take `--receipt`, which wraps stdout as `{text, filed}`. Without the
  flag stdout is byte-for-byte what it was, verified against the stashed tree.

  Derived would have been wrong twice over. `seq` is allocated under the task lock across
  every window, so a concurrent follow-up on the same task lands in the gap; and the read
  side resolves its own task, which is not always the one that was written. So `register_bytes`
  returns `Filed(row, appended)` — the row alone cannot say whether a re-render archived
  anything, and `_register_period_outputs` runs on every emit, so a receipt that called the
  second run an archive would announce a version the operator had already seen, every time.

  `filed` is a collector parameter rather than a return value. The text is what all ninety-odd
  callers of these three functions want; the versions are what one of them wants, and turning
  the return into a pair would have rewritten every one of them to reach through a tuple for
  what they already had.

  An empty `filed` means there was no timeline to file against, which is not the same claim
  as nothing having been produced — the brief is on disk either way.

- **KTD16. The receipt is drawn where the call is, and the model never reads it**
  `(session-settled: user-directed — 开吧，动 dsh-plugin)`. `output.presentationMeta` projects
  `{filed}` off the value `execute` already returned, and a keyed `tool.call.toolview`
  occupant draws it on the three tools that file versions. `output.render` still emits
  `stdout` alone, so the context these tools produce is byte-for-byte what it was.

  Four upstream facts hold it up, each read from the staged tree and each pinned by a test,
  because every one of them fails by drawing nothing:

  | Fact | Where |
  | --- | --- |
  | `presentationMeta?(args, value): JsonValue` on `ToolOutputDefinition` | `dsh-tools/lib/types/index.d.ts` |
  | called only when `exec.parent === void 0`, and a throw becomes `projectionError` | `dsh-tools/lib/index.js` |
  | the payload lands on the settled node as `meta?: unknown` | `dsh-client-runtime/.../conversation.d.ts` |
  | `tool.call.toolview` is `kind: 'keyed'`, dispatched on the wire tool name | `dsh-client-ui-tool/.../contract/slots.d.ts` |

  The projector is total by construction. The runtime calls it after `execute` has resolved
  and turns a throw into a failed call — so a projector bug would report a failure for a
  close that completed, which is the worst thing this product could say. Every tool declares
  it, including the eight that file nothing; they project an empty list, which is true of
  them, and a roster where only three carried the field would be a second rule to keep in
  step. `readReceipt` degrades the same way: an unparsable stdout is far likelier to be an
  older `foundry` on the PATH than a corrupted document, and the honest report is the text
  with no receipt attached.

  Taking a key takes the whole row, refusals included. A refusal is the fence working, and
  the row marks it as one rather than letting it read as an answer.

- **KTD17. A deliverable's bytes may not contain the clock.** `openpyxl` writes
  `dcterms:modified` from `datetime.now()` inside `save_workbook`, and `ZipFile` stamps every
  member from the clock at two-second resolution. A version is keyed on its bytes, so an
  unchanged window filed a new version whenever a render straddled a tick — the timeline
  filling with versions that are not versions, which is the exact thing `register_bytes`
  dedupes to prevent.

  Found as an intermittent test failure, twice, and the first time wrongly written off as a
  mid-edit import. The test that would have caught it renders across a real tick; the one
  that existed rendered twice in the same instant and passed. `_settle` rebuilds the archive
  with a sentinel date, and the honest timestamp stays where the store stamps it, on the
  deliverable row.

- **KTD18. One instance owns the store, and the profile manifest is written only when it
  changes** `(session-settled: user-directed — 加单实例锁 + 清单只在变了才写)`. An operator saw
  an unstyled upstream page reading `failed to import loader entry
  (@deepseek-ai/dsh-session-log-export)`, naming a bundle that served `200` before and after.

  Two facts made that reachable, and neither is upstream's. `main.ts` took no single-instance
  lock, and the harness home is derived from `userData`, which is one path for every copy of
  this app — so a second launch composed its own runtime against the first one's profile
  directory. And `installPlugin` rewrote `harness/profiles/web/package.json` unconditionally
  on every start, which in the ordinary case rewrites a file that already says exactly this.
  A reader catching that mid-write fails to compose the whole plugin tree.

  The lock is taken at module scope, above `whenReady`, so the losing process quits without
  reading or writing anything; the winner surfaces its window, which is what a second launch
  was asking for. The manifest write now compares first and goes through a rename, so a
  reader sees the old file or the new one and never half of either — that half also covers an
  operator editing the file or a backup tool reading it.

  Measured on the packaged app: first launch leaves the manifest's mtime untouched, a second
  launch neither writes nor starts a runtime, and one harness server is listening.

  A different `--user-data-dir` takes its own lock, so a scratch instance still runs beside a
  real one — which is how this app gets driven under test.

- **KTD19. An action nobody can scroll to is an action that does not exist**
  `(session-settled: user-directed — 依然没有找到导出的入口)`. The workbook export shipped with
  one entry point, on the task screen, below the input archive. Measured in the packaged app:
  on a real close that archive is twenty-odd rows each carrying a full source path, and the
  button sat 1344px below the fold of an 828px viewport. The screen actually named 交付物 had
  no export at all — which is where an operator goes to look for one, and did.

  Two placements now. The task screen's button moved to the top of the window panel, above the
  archive; measured again, it lands at 367px in the same 828px viewport. And reading any
  document on the 交付物 screen offers `把这个窗口出成表格` for that document's own window,
  because that is the moment someone wants one.

  It was found by driving the packaged app over CDP and asking the button for its
  `getBoundingClientRect`, after twice telling the operator where it was. Reading the source
  and believing the feature exists is how it went unnoticed; a rendered-order assertion is
  what pins it now.

- **KTD20. A workbook can be looked at in this window, in a gateway this app fences,
  starts and stops itself, with no model in the loop** `(session-settled: user-directed —
  做只读预览，模型碰不到 univer 工具; 接受：我按上面三条做)`. The operator asked why the Univer
  bundle was installed and nothing showed a workbook. The bundle's viewer is not a file
  renderer: it opens a *unit* inside a `.univer` container that its collaboration gateway
  serves over HTTP and a WebSocket. So a look at a filed `.xlsx` is a gateway process, a
  scratch container, the bundle's one-shot worker turning the bytes into a snapshot, and a
  page — and `univer.ts` owns all four.

  Three conditions were put to the operator before the gateway was ever run, because it is
  third-party server code and the audit of its bytes found it binds loopback only, has no
  authentication, reflects any `Origin` in its CORS headers, and reads one environment name as
  its only filesystem boundary. The operator accepted all three, and each is now a fact with a
  test rather than a promise:

  1. `UNIVER_ALLOWED_ROOT` is the task's own artifacts directory, set on the gateway this app
     spawns. Read from `gateway.cjs`: `UniverfileManager._assertWithinAllowedRoot` refuses a
     container outside the root *and one at it*, which is why the container is
     `<artifacts>/preview/<sha256>.univer` and not `<artifacts>/<sha256>.univer`.
  2. The gateway runs while a preview is open and not otherwise. The renderer takes it down
     when the strip above the viewer stops naming this version on this screen; main kills the
     child and removes the container; `shutDown` does the same on quit.
  3. No tool is registered anywhere on this path. Main calls the gateway over HTTP itself; the
     thirteen `univer_*` tools stay denied on the close seat (KTD12).

  Every wire shape is read from the bundle's bytes and pinned by a test that reads them again:
  the banner and the port-in-use exit from `gateway-entry.ts`; the worker protocol (`{operation:
  "import", sourcePath, unitType}` on stdin, `{ok, result}` on stdout) from
  `adapters/unit-content/worker.ts`; the container key (`base64url` of the absolute path) from
  `file-api.ts`; the viewer URL (`/?file=<key>`) from `gateway-univer-service.ts`. A trunk unit
  cannot be created with content — the route takes a name and nothing else — so the snapshot
  goes into a draft worktree and is merged, which is the plugin's own `univer_import` sequence
  minus the model.

  Two things this is not. It was not read-only at the page on the first build: the trunk viewer
  could be typed into. What it typed into was a container derived from the archived bytes,
  made fresh on every open and deleted on close, and the filed `.xlsx` is never opened by the
  gateway at all — the worker reads it once. The viewer's own switches closed that: its URL
  reader honours `editable=false` only under `mode=embedded`, and in that layout 39 of 42
  toolbar controls are disabled against 27 of 43 without it; the same layout drops the file
  sidebar that showed the container's base64 key, and `lang=zh-CN` puts the ribbon in the
  app's language. Its appearance is one localStorage key, `light` or `dark`, default `light`,
  never `prefers-color-scheme` — `nativeTheme` turned the harness page dark and left the
  viewer white — so the key is written on the viewer's origin from the gateway's own 404 page
  before the viewer loads. And it is not a fence on the plugin's own gateway. An earlier version
  of this session set `UNIVER_ALLOWED_ROOT` on the harness child and asserted it, which
  measured as present and did nothing: `gatewayLaunch` in `lib/index.js` builds that gateway's
  environment from an explicit list (`HOME LANG LC_ALL PATH TMPDIR` plus its own three names).
  That plumbing is removed, the test now asserts its absence, and the plugin's gateway is kept
  from the close seat by preset rather than by a boundary it cannot be given.

  Measured on the packaged app, driven over CDP against a scratch store: the first open answered
  `running` within three seconds, the viewer drew the four sheets, and the gateway child's
  environment was exactly the allowlist plus the three names -- `UNIVER_ALLOWED_ROOT` the task's
  artifacts directory, no key-shaped name, no `DSH_*`. So `libsql`, the formula engine and the
  Office exchange bindings do load under Electron-as-Node. Closing from the strip took the
  gateway off its port and removed the container within a second. The same run found that
  `Pane.detach` left the viewer's renderer alive after the view was gone -- harmless for the two
  panes that detach once at quit, a leak for one that opens and closes per version -- so detach
  now closes the page's process too. Not measured: a second task's preview while the first is
  open (the second replaces the first by design), and a machine whose natives are a different
  architecture from the staged ones.

## Scope Boundaries

**Not in this work**

- Letting the model author a spreadsheet. The Office bundle is installed for the authoring
  seat and for a rendering path we have not built yet; the close seat cannot see it.
- Rendering the close in a viewer we host, as the way the close is delivered. `foundry export
  --format xlsx` writes the window as a workbook and the app hands it to the operator's own
  spreadsheet software; that stays the deliverable. KTD20 adds a look at it in this window, on
  a scratch copy, for the question "what is in this version" — not a second Excel, and not on
  the path of the document they need every month, which is why the licence expiry below is a
  risk to the look and not to the close.
- A leader-operated session. KTD7 stands.
- Re-emitting a brief after a late reference. The brief is what was known when it was written;
  the workpaper is what was learned since. Conflating them would make the version trail lie.

**Risks**

- The Univer Pro licence embedded in the bundle expires 2026-11-15, and after that the
  rendering path draws a watermark. Decoded from the JWT in `lib/index.js`: `et` 1794758400,
  domain-bound to `localhost`. Seventy-five days from the install. Whatever we build on this
  has to survive a bundle upgrade, or an expiry, or both.
- The bundle's own audit was run by seven independent readers and its cross-checking pass
  died on an infrastructure error, so the findings behind KTD12 are one-pass rather than
  adversarially verified. The two that decide anything — the licence expiry and the egress
  hosts — were re-measured by hand.
- `外部引用` is a mark an operator has to learn. It is documented in `method/FOUNDRY.md`, drawn
  as its own chip in the reader, and named in the period persona; nothing else teaches it.
- The reference text is free prose. `RESERVED_WORDS` stops it borrowing the brief's marks, but
  a wrong benchmark with a real source is still wrong. That is a review problem, and the
  source and date are what make review possible.
