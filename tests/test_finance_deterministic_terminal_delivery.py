"""Verified terminal saves reach the SDK's public durable result without a new LLM step."""
import json
import os
import subprocess
import sys

import pytest

from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from test_finance_completion_fingerprint import ratio_case
from test_finance_saved_delivery import ratio_spec
from test_method_skill_runtime import ROOT, _runtime_or_skip


def _sdk(tmp_path, config=None):
    args = ['node', str(ROOT / 'tests/finance_deterministic_terminal_delivery_sdk.mjs'),
            str(_runtime_or_skip()), str(tmp_path)]
    env = dict(os.environ)
    if config:
        path = tmp_path / 'native.json'
        path.write_text(json.dumps(config))
        args.append(str(path))
        launcher = tmp_path / 'foundry'
        launcher.write_text(f'#!{sys.executable}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                            'runpy.run_module("foundry.cli",run_name="__main__")\n')
        launcher.chmod(0o700)
        env.update(FOUNDRY_BIN=str(launcher), FOUNDRY_VAR=str(tmp_path / 'var'))
    observed = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=90)
    assert observed.returncode == 0, observed.stderr
    result = json.loads(observed.stdout)
    assert result['passed'] and result['provider_calls'] == 0
    return result


def test_real_sdk_terminal_delivery_and_fail_closed_boundaries(tmp_path):
    result = _sdk(tmp_path)
    assert len(result['reports']) == 18


@pytest.mark.parametrize('mutation', [None, 'corrupt_body'])
def test_native_cli_complete_receipt_and_live_saved_body_verification(tmp_path, mutation):
    manager, _, run, _ = ratio_case(tmp_path)
    session = 'native-terminal-complete'
    manager.task.record_session(session, role='analysis')
    result = _sdk(tmp_path, {'session_id': session, 'spec': ratio_spec(manager, run),
                              'mutation': mutation, 'analysis_root': str(manager.analysis.root)})
    report = result['reports'][0]
    if mutation:
        assert report['deliveries'] == []
    else:
        assert report['saved_status'] == 'complete' and report['calls'] == 1
        delivery = report['deliveries'][0]
        saved = manager.analysis.get_draft(delivery['meta']['bindings']['draft_id'])
        assert saved['content_hash'] == delivery['meta']['bindings']['draft_content_hash']
        assert report['persisted_public_events_exact']


def test_native_cli_input_gap_is_delivered_with_limitations(tmp_path):
    manager = FinanceStore(TaskStore(tmp_path / 'var').create(title='合法缺资料终态'))
    scope = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-08',
             'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}
    path = tmp_path / 'amounts.json'
    path.write_text(json.dumps([{**scope, 'account_code': '1', 'management_account': 'revenue', 'amount': '25'}]))
    source = manager.analysis.add_dataset(path, name='只有金额')
    context = manager.save_context({'bindings': {'source': source['id']}, 'scopes': {'source': scope}})
    requirement = manager.analysis_requirements_save({'question': '解释量价变化并核查来源',
        'bindings': context['bindings'], 'items': [{'id': 'pq', 'metric': 'price_quantity', 'requires_drilldown': True}]})
    run = manager.run_metric({'context_id': context['id'], 'metric': {'kind': 'account_total', 'accounts': ['revenue']}})
    session = 'native-terminal-input-gap'
    manager.task.record_session(session, role='analysis')
    result = _sdk(tmp_path, {'session_id': session, 'spec': {
        'requirements_id': requirement['id'], 'run_ids': [run['id']],
        'body': '需要补充数量与单价资料；原量价分析尚未完成。'}})
    report = result['reports'][0]
    assert report['saved_status'] == 'awaiting_input' and report['calls'] == 1
    assert report['deliveries'][0]['meta']['bindings']['completion_status'] == 'awaiting_input'
    assert '已保存完成' not in report['deliveries'][0]['text']
