# Finance Skill Foundry

A finance manager authors a portable analysis skill, then each period imports and locks named statements, writes this-window questions, and emits a conclusion brief. Leader follow-up recomputes from that brief's window and tags `稿外追问` / `我重算`.

v1 kit: native DeepSeek harness (TypeScript Cordis tools that exec this CLI), DuckDB lock catalog, Data Formulator live attach, Skill creator with a fixture done-gate.

## Store

```text
var/windows/<window_id>/{catalog.duckdb,lock.json,questions.json,brief.md,followup.jsonl}
var/current
var/formulator/<window_id>/
var/skills/<skill_id>/SKILL.md
```

## Pin

- DuckDB 1.5.x
- DeepSeek Harness: pin the installed `dsh` version in this README at install time; upgrades are breaking. Period tools are the Cordis bundle in `dsh-plugin/`. Headless smoke is `foundry --var VAR host-smoke`.
- Data Formulator: do not pass `--disable-database` or `--disable-data-connectors`

Keys stay in the process environment. Never write them into the window, skill, or Formulator home.

## Dev

```bash
uv venv
uv pip install -e ".[dev]"
.venv/bin/python -m pytest tests
```
