#!/usr/bin/env python3
"""Seed three synthetic tasks for the first-screen check in tools/verify_ui_workspace.cjs.

Each task holds one analysis result of a kind 分析结果 must open on:

- finance: a finance-engine variance run, budget against actual, whose result carries the conclusion bar;
- declared: a script run of a long-form table (actual_1_8 / budget_1_8 / revenue_variance /
  revenue_achievement_ratio in 比率, regional budgets with basis estimate), saved with row_declarations;
- legacy: the same script saved the same way, then turned into a run saved before declarations existed.

Every record is written by the packaged foundry CLI. The CLI always declares a new script run, so the legacy run
is made by deleting `row_declarations` from its stored record and sealing the record again with the store's own
foundry.analysis._hash; `seq` and every other field stay as the CLI wrote them. The store then reads it back
(foundry.analysis.AnalysisStore.get_run here, and the packaged `analysis-state`), both of which check the seal.

All names and numbers are synthetic. Usage, with the repo's virtualenv so foundry is importable:

    .venv/bin/python tools/fixtures/seed_first_screen_runs.py --bin <packaged foundry> --var <isolated var> \
        --work <fixture dir>

Prints one JSON object naming each task, its title and its run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from foundry.analysis import AnalysisStore, _hash
from foundry.fsutil import write_json_atomic
from foundry.task import TaskStore

TITLES = {
    'finance': '首屏检查 · 财务差异',
    'declared': '首屏检查 · 声明长表',
    'legacy': '首屏检查 · 旧格式长表',
}
SCOPE = {'ledger': '主账簿', 'organization': '华东公司', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'}
ACCOUNTS = [('6001', 'revenue'), ('6401', 'cost'), ('6601', 'expense')]
ACTUAL = {'revenue': '1280.00', 'cost': '820.00', 'expense': '190.00'}
BUDGET = {'revenue': '1350.00', 'cost': '840.00', 'expense': '180.00'}

BASE = {'currency': 'CNY', 'period': '2026-01:2026-08', 'unit': '万元', 'source': '合成数据：预算执行表；合并利润表'}
GROUP, EAST, WEST = '集团合并', '东部区域', '西部区域'
# One group pair with its own variance and 达成率 rows, a profit pair, and two regions whose budgets are estimates.
LONG_ROWS = [
    {**BASE, 'metric_key': 'revenue', 'organization': GROUP, 'scenario': 'actual_1_8', 'value': '48210.5000',
     'metric_label': '营业收入 1-8 月实际', 'basis': 'source'},
    {**BASE, 'metric_key': 'revenue', 'organization': GROUP, 'scenario': 'budget_1_8', 'value': '50120.0000',
     'metric_label': '营业收入 1-8 月预算', 'basis': 'source'},
    {**BASE, 'metric_key': 'revenue_variance', 'organization': GROUP, 'scenario': 'variance_1_8',
     'value': '-1909.5000', 'metric_label': '营业收入差异', 'basis': 'calculation'},
    {**BASE, 'metric_key': 'revenue_achievement_ratio', 'organization': GROUP, 'scenario': 'budget_1_8',
     'value': '0.961901', 'unit': '比率', 'metric_label': '营业收入达成率', 'basis': 'calculation'},
    {**BASE, 'metric_key': 'profit', 'organization': GROUP, 'scenario': 'actual_1_8', 'value': '5320.4000',
     'metric_label': '营业利润 1-8 月实际', 'basis': 'source'},
    {**BASE, 'metric_key': 'profit', 'organization': GROUP, 'scenario': 'budget_1_8', 'value': '5610.0000',
     'metric_label': '营业利润 1-8 月预算', 'basis': 'source'},
    {**BASE, 'metric_key': 'revenue', 'organization': EAST, 'scenario': 'actual_1_8', 'value': '21430.2000',
     'metric_label': '营业收入 1-8 月实际', 'basis': 'source'},
    {**BASE, 'metric_key': 'revenue', 'organization': EAST, 'scenario': 'budget_1_8', 'value': '22600.0000',
     'metric_label': '营业收入 1-8 月预算', 'basis': 'estimate'},
    {**BASE, 'metric_key': 'revenue_variance', 'organization': EAST, 'scenario': 'variance_1_8',
     'value': '-1169.8000', 'metric_label': '营业收入差异', 'basis': 'calculation'},
    {**BASE, 'metric_key': 'revenue', 'organization': WEST, 'scenario': 'actual_1_8', 'value': '12840.6000',
     'metric_label': '营业收入 1-8 月实际', 'basis': 'source'},
    {**BASE, 'metric_key': 'revenue', 'organization': WEST, 'scenario': 'budget_1_8', 'value': '12300.0000',
     'metric_label': '营业收入 1-8 月预算', 'basis': 'estimate'},
    {**BASE, 'metric_key': 'revenue_variance', 'organization': WEST, 'scenario': 'variance_1_8',
     'value': '540.6000', 'metric_label': '营业收入差异', 'basis': 'calculation'},
    {**BASE, 'metric_key': 'revenue_achievement_ratio', 'organization': WEST, 'scenario': 'budget_1_8',
     'value': '1.043951', 'unit': '比率', 'metric_label': '营业收入达成率', 'basis': 'calculation'},
]


def cli(bin_path: str, var: Path, command: str, *args: str, task: str | None = None):
    output = subprocess.run(
        [bin_path, '--var', str(var), *(['--task', task] if task else []), command, *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return output if command == 'task-new' else json.loads(output)


def write_rows(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def ledger_rows(scenario: str, amounts: dict[str, str], prefix: str) -> list[dict]:
    return [{**SCOPE, 'scenario': scenario, 'account_code': code, 'management_account': account,
             'amount': amounts[account], 'doc_id': f'{prefix}-{index:03d}', 'line_id': '1'}
            for index, (code, account) in enumerate(ACCOUNTS, 1)]


def seed_finance(bin_path: str, var: Path, work: Path) -> dict:
    task = cli(bin_path, var, 'task-new', '--title', TITLES['finance'], '--period', '2026-08')
    actual = cli(bin_path, var, 'dataset-add', '--path', str(write_rows(work / 'finance-actual.json', ledger_rows('actual', ACTUAL, 'SJ'))),
                 '--name', '八月实际发生', task=task)
    budget = cli(bin_path, var, 'dataset-add', '--path', str(write_rows(work / 'finance-budget.json', ledger_rows('budget', BUDGET, 'YS'))),
                 '--name', '八月预算', task=task)
    context = cli(bin_path, var, 'finance-context-save', '--spec', json.dumps({
        'name': '八月预算执行口径',
        'bindings': {'actual': actual['id'], 'budget': budget['id']},
        'scopes': {'actual': {**SCOPE, 'scenario': 'actual'}, 'budget': {**SCOPE, 'scenario': 'budget'}},
    }, ensure_ascii=False), task=task)
    run = cli(bin_path, var, 'explain-variance', '--spec', json.dumps({'context_id': context['id']}), task=task)
    assert run['execution_status'] == 'succeeded' and run['engine'] == 'finance', run
    assert run['result'].get('method') == 'revenue_minus_cost_minus_expense', run['result'].get('method')
    return {'task': task, 'title': TITLES['finance'], 'run': run['id']}


def script_writing(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return (
        'from pathlib import Path\n'
        f'Path("result.json").write_text({payload!r}, encoding="utf-8")\n'
        "print('rows written')\n"
    )


def seed_script(bin_path: str, var: Path, kind: str) -> dict:
    task = cli(bin_path, var, 'task-new', '--title', TITLES[kind], '--period', '2026-08')
    run = cli(bin_path, var, 'analysis-script', '--spec', json.dumps({
        'question': '1-8 月收入与利润预算执行', 'code': script_writing(LONG_ROWS), 'bindings': {},
        'result_file': 'result.json',
    }, ensure_ascii=False), task=task)
    assert run['execution_status'] == 'succeeded', run
    assert isinstance(run.get('row_declarations'), dict), 'the CLI saves new script runs declared'
    return {'task': task, 'title': TITLES[kind], 'run': run['id']}


def strip_declarations(bin_path: str, var: Path, seeded: dict) -> dict:
    """Make the run read as one saved before declarations existed, sealed as the store seals it."""
    store = AnalysisStore(TaskStore(var).get(seeded['task']))
    path = store._object_path('runs', seeded['run'])
    record = json.loads(path.read_text(encoding='utf-8'))
    seq = record['seq']
    del record['row_declarations']
    record.pop('_integrity_hash')
    record['_integrity_hash'] = _hash(record)
    write_json_atomic(path, record)
    # Both readers verify the seal: the repo's store, and the packaged CLI the app itself calls.
    reread = store.get_run(seeded['run'])
    assert 'row_declarations' not in reread and reread['seq'] == seq
    state = cli(bin_path, var, 'analysis-state', task=seeded['task'])
    run = next(row for row in state['runs'] if row['id'] == seeded['run'])
    assert 'row_declarations' not in run and run['seq'] == seq
    return {**seeded, 'seq': seq, 'integrity_hash': record['_integrity_hash']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bin', required=True, help='the packaged foundry CLI')
    parser.add_argument('--var', required=True, type=Path, help='an isolated var root, never a real one')
    parser.add_argument('--work', required=True, type=Path, help='where the synthetic source files are written')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    seeded = {
        'finance': seed_finance(args.bin, args.var, args.work),
        'declared': seed_script(args.bin, args.var, 'declared'),
        'legacy': strip_declarations(args.bin, args.var, seed_script(args.bin, args.var, 'legacy')),
    }
    print(json.dumps(seeded, ensure_ascii=False))


if __name__ == '__main__':
    main()
