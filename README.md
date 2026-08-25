# Finance Skill Foundry

A finance manager authors a portable analysis skill, then each period imports and locks named statements, writes this-window questions, and emits a conclusion brief. Leader follow-up recomputes from that brief's window and tags `稿外追问` / `我重算`.

v1 kit: native DeepSeek harness (TypeScript/JS Cordis tools that exec this CLI), DuckDB lock catalog, Data Formulator live attach, Skill creator with a fixture done-gate.

## Store

```text
var/windows/<window_id>/{catalog.duckdb,lock.json,questions.json,brief.md,followup.jsonl}
var/current
var/formulator/<window_id>/
var/skills/<skill_id>/SKILL.md
```

## Pin

- DuckDB 1.5.x
- DeepSeek Harness: `@deepseek-ai/dsh@0.1.0-rc.7` (bundled CLI used at install). Upgrades are breaking. Period tools are the Cordis bundle in `dsh-plugin/`. Headless smoke is `foundry --var VAR host-smoke`.
- Data Formulator: `data-formulator==0.7.0` (`data_formulator` binary). Do not pass `--disable-database` or `--disable-data-connectors`.

Keys stay in the process environment. Never write them into the window, skill, or Formulator home.

## Period loop

```bash
foundry --var VAR create
foundry --var VAR import --coa COA.xlsx --units UNITS.xlsx --named NAMED.json
foundry --var VAR lock
foundry --var VAR record-questions --questions QUESTIONS.json
foundry --var VAR emit-brief
foundry --var VAR query-locked --text "..." --tables gl --split-by unit_id --brief-window WINDOW
```

## Dev

```bash
uv venv
uv pip install -e ".[dev]"
.venv/bin/python -m pytest tests
```
