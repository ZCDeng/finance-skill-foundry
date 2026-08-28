# Finance Skill Foundry

A finance manager authors a portable analysis skill, then each period imports and locks named statements, writes this-window questions, and emits a conclusion brief. Leader follow-up recomputes from that brief's window and tags `稿外追问` / `我重算`.

v1 kit: native DeepSeek harness (TypeScript/JS Cordis tools that exec this CLI), DuckDB lock catalog, Data Formulator live attach, Skill creator with a fixture done-gate.

## Store

```text
var/windows/<window_id>/{catalog.duckdb,lock.json,questions.json,brief.md,schedules.json,workpaper.md,followup.jsonl}
var/current
var/formulator/<window_id>/
var/skills/<skill_id>/SKILL.md
method/{financial-statements,reconciliation,variance-analysis,journal-entry}/SKILL.md
```

## Pin

- DuckDB 1.5.x
- DeepSeek Harness: `@deepseek-ai/dsh@0.1.0-rc.7` (bundled CLI used at install). Upgrades are breaking. Period tools are the Cordis bundle in `dsh-plugin/`. Headless smoke is `foundry --var VAR host-smoke`.
- File drop: `dsh-file-upload@0.4.3` ([HongMing-Huang/dsh-file-upload](https://github.com/HongMing-Huang/dsh-file-upload)). Companion only. Period and F3 omit `read_document`.
- Data Formulator: `data-formulator==0.7.0` (`data_formulator` binary). Do not pass `--disable-database` or `--disable-data-connectors`.

Keys stay in the process environment. Never write them into the window, skill, or Formulator home.

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
foundry --var VAR query-locked --text "..." --tables gl --split-by unit_id --brief-window WINDOW
```

## Harness drop

Paperclip / drag-drop is an input drop for import, not a second books surface.

```bash
dsh plugin --profile web add dsh-file-upload@0.4.3
foundry --var VAR harness
```

Merge `dsh-plugin/file-upload.overlay.yml` into the installed plugin config. Do not add a second `id: file-upload` insert — that double-applies and crashes. Name files `coa.xlsx`, `aux.xlsx`, `map.xlsx`, `units.xlsx`, and one file per named table (`gl.xlsx`). Pass those `@` paths to `import`, or pass the upload folder as `--drop-dir`. Do not use `read_document` on locked books.

## Method skills

Four close methods ship in `method/`. They are kit files, not `var/skills/`.

```bash
foundry --var VAR method-skills
```

Numbers still come from the locked window. See `method/FOUNDRY.md`.

## Dev

```bash
uv venv
uv pip install -e ".[dev]"
.venv/bin/python -m pytest tests
```
