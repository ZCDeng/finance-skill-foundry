# Finance Skill Foundry

A finance manager authors a portable analysis skill, then each period imports and locks named statements, writes this-window questions, and emits a conclusion brief. Leader follow-up recomputes from that brief's window and tags `稿外追问` / `我重算`.

v1 kit: native DeepSeek harness (`dsh-plugin/index.js`, the single Cordis module that execs this CLI), DuckDB lock catalog, Data Formulator live attach, Skill creator with a fixture done-gate.

## Store

```text
var/tasks/<task_id>/{task.json,windows.jsonl,sessions.jsonl,deliverables.jsonl,artifacts/<sha256>.md}
var/current-task
var/windows/<window_id>/{catalog.duckdb,lock.json,questions.json,brief.md,schedules.json,workpaper.md,followup.jsonl}
var/windows/<window_id>/{task,inputs/<role>.<ext>}
var/current
var/formulator/<window_id>/
var/skills/<skill_id>/{SKILL.md,foundry.json}
method/{financial-statements,reconciliation,variance-analysis,journal-entry}/SKILL.md
```

A task is one period's work. It owns an ordered chain of windows -- the first import
plus every successor a re-import opened -- the conversations that touched them, and every
version of every document they produced. A window still owns the caliber lock.

Import copies each source file into `<window>/inputs/` and parses the copy, so the
window holds the bytes it was built from. Delete the export afterwards and the window
still locks, still emits, and still shows an auditor the workbook. Editing a master file
between import and lock is still refused: caliber changes travel through a re-import.

`deliverables.jsonl` is append-only and content-addressed. A brief is one version per
window; the workpaper grows one every time a follow-up appends a schedule, and each
version names what caused it (`emit-brief`, `query-locked:followup-3`, `export:brief`).

## Pin

- DuckDB 1.5.5 (current stable; 1.6 is prerelease only)
- DeepSeek Harness: `@deepseek-ai/dsh@0.1.1-rc.2` (bundled CLI used at install). Upgrades are breaking. Period tools are the Cordis bundle in `dsh-plugin/`. Headless smoke is `foundry --var VAR host-smoke`.
- File drop: `dsh-file-upload@0.4.3` ([HongMing-Huang/dsh-file-upload](https://github.com/HongMing-Huang/dsh-file-upload)). Companion only. Period and F3 omit `read_document`.
- Data Formulator: `data-formulator==0.7.0` (`data_formulator` binary, `pip install -e ".[formulator]"`). Do not pass `--disable-database` or `--disable-data-connectors`.
- `node` on PATH for `host-smoke`, which loads the shipped dsh bundle. Nothing else in the period loop needs it.
- `ps` on PATH lets `launch-formulator` confirm the served process is this window's Formulator. Without it the launch still runs and says `identity: unconfirmed` in its payload and on stderr.

Provider keys stay in the process environment. Never write a key into the window, skill, or Formulator home. Data Formulator writes its own `credentials.db` into `DATA_FORMULATOR_HOME` unconditionally; the foundry gives each window a `0700` home for it and `purge-formulator` removes it. Set `CREDENTIAL_VAULT_KEY` and the cleartext `.vault_key` stays out of that home too.

## Task

```bash
foundry --var VAR task-new --title "2026-08 月度经营分析" --period 2026-08
foundry --var VAR task-list
foundry --var VAR --task TASK task-show
foundry --var VAR --task TASK deliverables
# what the leader actually asked, in their own words, kept apart from the
# question a model later executes
foundry --var VAR --task TASK --session SESSION record-session --role followup --verbatim "华东这个月怎么回事？"
# file the version the leader is handed, so a later follow-up can cite it
foundry --var VAR --task TASK export --kind brief
```

`--task` and `--session` are global. The task is resolved by the first of: `--task`,
`FOUNDRY_TASK`, the addressed window's own back-pointer. A window with no task keeps
working and is adopted by the first task that touches it. The session id is never taken
from the environment -- one harness process hosts many conversations, so it arrives per
call.

## Period loop

```bash
foundry --var VAR create
foundry --var VAR import --coa COA.xlsx --aux AUX.xlsx --map MAP.xlsx --named NAMED.json
# or, after a paperclip drop whose stems are coa/aux/map/units/gl:
foundry --var VAR import --drop-dir .dsh-uploads/SESSION
foundry --var VAR lock
foundry --var VAR record-questions --questions QUESTIONS.json
foundry --var VAR emit-brief
foundry --var VAR workpaper
# after a re-import, the follow-up's workpaper is on the brief's window, not on current
foundry --var VAR workpaper --window WINDOW
foundry --var VAR query-locked --text "..." --tables gl --split-by unit_id --brief-window WINDOW --question-id QUESTION
foundry --var VAR launch-formulator
foundry --var VAR stop-formulator
# use only after the process is stopped, to remove a stale per-window home
foundry --var VAR purge-formulator
```

CSV, XLSX/XLSM, and tabular JSON inputs are supported.

`--named` takes JSON inline, or a path to a JSON file, in one of three shapes:

```jsonc
[{"id": "gl", "path": "gl.xlsx"}]                                  // a list of entries
{"gl": "gl.xlsx", "ar": "ar.xlsx"}                                 // an id-to-path map
{"coa": "coa.xlsx", "units": "units.xlsx",                         // an envelope: defaults
 "tables": [{"id": "gl", "path": "gl.xlsx"}]}                      //   plus the table list
```

Anything else is refused by name. A dict carrying `coa`/`aux`/`map`/`units` but no `tables` key is refused as a malformed envelope rather than read as an id-to-path map. Referenced files resolve relative to, and must stay inside, the descriptor's directory. Explicit CLI paths remain available for operator-selected files.

Exit codes: `0` done, `2` argparse usage error, `3` domain refusal. `python -m foundry.probe` uses the same three.

A table id becomes a SQL identifier, so `ar-2024-08.xlsx` is the table `ar_2024_08`. Questions and `query-locked --tables` accept either spelling.

## Harness

The period tools reach a model through one command:

```bash
dsh plugin --profile PROFILE add /path/to/finance-skill-foundry/dsh-plugin
foundry --var VAR harness   # prints this line with the paths filled in
```

That is the whole wiring. `add` writes the package into the profile's dependencies
*and* appends it to `dsh.profile.bundles`, and the package carries its own
`dsh.bundle.patch`, so the insert row arrives from there. Handing
`dsh-plugin/cordis.patch.yml` to `--patch` as well composes the row a second time.

`dsh plugin add` on a local directory links rather than copies, so an edit in the
checkout is live in the profile.

Verified on the pinned runtime: after that one command, `--dump-config` shows exactly
one `id: finance-skill-foundry` row and all ten tools register. `tests/test_real_load.py`
is that check, opt-in via `FOUNDRY_DSH_BIN`.

**The period fence is not real yet.** `dsh.foundry.profiles.period.omit` names `bash`,
`dsh-tool-fs` and `str-replace-editor`, and the bundle refuses to start if any of them
are in the roster it is handed — but that check only ever sees its own list. An agent's
tool set is decided by its *preset*, which a profile row cannot reach into. On the stock
`headless` preset the model is offered foundry's ten tools and `bash`, `write`, `edit`,
`read` and `str_replace_editor` beside them. Closing it needs a foundry-owned agent
preset. Until then, do not treat the locked window as unreadable-around.

## Harness drop

Paperclip / drag-drop is an input drop for import, not a second books surface.

```bash
dsh plugin --profile web add dsh-file-upload@0.4.3
foundry --var VAR harness
```

Merge `dsh-plugin/file-upload.overlay.yml` into the installed plugin config. Do not add a second `id: file-upload` insert — that double-applies and crashes. Name files `coa.xlsx`, `aux.xlsx`, `map.xlsx`, `units.xlsx`, and one file per named table (`gl.xlsx`). Pass those `@` paths to `import`, or pass the upload folder as `--drop-dir`. Do not use `read_document` on locked books.

A drop is an untrusted upload, so `--drop-dir` refuses every symlink inside the tree it scans: copy a shared source file in rather than linking it. Both `--drop-dir` and `--named` also refuse a path reached through a symlinked directory that points outside its own parent, because that silently moves the boundary the import is allowed to read from.

If `stop-formulator` cannot confirm the pid's identity (no `ps`, or the pid belongs to another user) it refuses rather than killing an unverified process. `FOUNDRY_FORMULATOR_FORCE_STOP=1` releases the lease anyway so the window stays re-importable; it does **not** stop the server, and the payload says so. Kill that process yourself, or the next launch on this window will refuse on the port pre-flight.

## Method skills

Four close methods ship in `method/`. They are kit files, not `var/skills/`.

```bash
foundry --var VAR method-skills
```

Numbers still come from the locked window. See `method/FOUNDRY.md`.

## Authoring done-gate

`mark-done` requires both authored instructions and a machine-readable capability contract, then runs the bundled period fixture:

```text
SKILL.md
foundry.json  # schema finance-skill-foundry/f2-skill@1
```

The contract must declare the ordered F2 tools (`import`, `lock`, `record-questions`, `emit-brief`, `query-locked`), the locked-window safety policies, and bindings to `FOUNDRY.md` and `CONNECTORS.md`. This keeps per-period questions out of the portable skill.

## Dev

```bash
uv venv
uv pip install -e ".[dev]"
.venv/bin/python -m pytest tests       # node on PATH runs the bundle tests too
node dsh-plugin/test.mjs
```
