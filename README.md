# Finance Skill Foundry

A finance manager authors a portable analysis skill, then each period imports and locks named statements, writes this-window questions, and emits a conclusion brief. Leader follow-up recomputes from that brief's window and tags `稿外追问` / `我重算`.

v1 kit: native DeepSeek harness (`dsh-plugin/index.js`, the single Cordis module that execs this CLI), DuckDB lock catalog, Data Formulator live attach, Skill creator with a fixture done-gate.

## Store

```text
var/windows/<window_id>/{catalog.duckdb,lock.json,questions.json,brief.md,schedules.json,workpaper.md,followup.jsonl}
var/current
var/formulator/<window_id>/
var/skills/<skill_id>/{SKILL.md,foundry.json}
method/{financial-statements,reconciliation,variance-analysis,journal-entry}/SKILL.md
```

## Pin

- DuckDB 1.5.x
- DeepSeek Harness: `@deepseek-ai/dsh@0.1.0-rc.7` (bundled CLI used at install). Upgrades are breaking. Period tools are the Cordis bundle in `dsh-plugin/`. Headless smoke is `foundry --var VAR host-smoke`.
- File drop: `dsh-file-upload@0.4.3` ([HongMing-Huang/dsh-file-upload](https://github.com/HongMing-Huang/dsh-file-upload)). Companion only. Period and F3 omit `read_document`.
- Data Formulator: `data-formulator==0.7.0` (`data_formulator` binary, `pip install -e ".[formulator]"`). Do not pass `--disable-database` or `--disable-data-connectors`.
- `node` on PATH for `host-smoke`, which loads the shipped dsh bundle. Nothing else in the period loop needs it.
- `ps` on PATH lets `launch-formulator` confirm the served process is this window's Formulator. Without it the launch still runs and says `identity: unconfirmed` in its payload and on stderr.

Provider keys stay in the process environment. Never write a key into the window, skill, or Formulator home. Data Formulator writes its own `credentials.db` into `DATA_FORMULATOR_HOME` unconditionally; the foundry gives each window a `0700` home for it and `purge-formulator` removes it. Set `CREDENTIAL_VAULT_KEY` and the cleartext `.vault_key` stays out of that home too.

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
