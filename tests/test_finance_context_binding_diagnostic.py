"""A partial finance context diagnoses exact missing bindings without granting coverage."""
import json

from foundry.analysis import AnalysisStore
from foundry.finance_requirements import _unanswered_message, check_requirements
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def setup(tmp_path):
    analysis = AnalysisStore(TaskStore(tmp_path / 'var').create(title='月结差异'))
    scope = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-12',
             'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}
    datasets = {}
    for name in ('cc', 'pf', 'hidden'):
        path = tmp_path / f'{name}.json'
        path.write_text(json.dumps([{'management_account': 'subledger', 'amount': '100', 'origin': name, **scope}]))
        datasets[name] = analysis.add_dataset(path, name=name)
    service = FinanceStore(analysis.task)
    partial = service.save_context({'bindings': {'cc': datasets['cc']['id']}, 'scopes': {'cc': scope}})
    bindings = {key: datasets[key]['id'] for key in ('cc', 'pf')}
    requirement = service.analysis_requirements_save({
        'question': '核对子账总账的同范围控制数', 'scope': scope, 'bindings': bindings,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}]})
    return service, scope, datasets, partial, bindings, requirement


def item(service, requirement):
    return check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [], 'claims': []})['items'][0]


def test_partial_context_names_missing_binding_without_relaxing_complete_group(tmp_path):
    service, _, datasets, partial, bindings, requirement = setup(tmp_path)
    result = item(service, requirement)
    path = result['evidence_paths']['blocked'][0]
    assert path['blockers'] == ['no_finance_context']
    diagnostic = path['context_binding_diagnostic']
    assert diagnostic['required_bindings'] == bindings
    assert diagnostic['available_contexts'] == [{
        'context_id': partial['id'], 'bindings': {'cc': datasets['cc']['id']},
        'missing_aliases': ['pf'], 'different_snapshots': {},
    }]
    assert result['status'] == 'pending'
    assert 'awaiting_manager' not in result
    message = _unanswered_message(result)
    assert 'pf=' + datasets['pf']['id'] in message
    assert '缺少 pf' in message
    assert '重新保存并验证' in message


def test_new_full_context_opens_path_but_does_not_answer_without_new_run_and_save(tmp_path):
    service, scope, _, _, bindings, requirement = setup(tmp_path)
    before = item(service, requirement)
    frozen_before = json.dumps(before, sort_keys=True)
    service.save_context({'bindings': bindings, 'scopes': {key: scope for key in bindings}})
    after = item(service, requirement)
    assert not any('no_finance_context' in path['blockers'] for path in after['evidence_paths']['blocked'])
    assert after['status'] == 'pending'
    assert json.dumps(before, sort_keys=True) == frozen_before
    assert len(service.analysis._list('runs')) == 0
    assert len(service.analysis._list('drafts')) == 0


def test_unrelated_context_is_not_exposed_in_binding_diagnostic(tmp_path):
    service, scope, datasets, _, _, requirement = setup(tmp_path)
    hidden = service.save_context({'bindings': {'secret': datasets['hidden']['id']}, 'scopes': {'secret': scope}})
    text = json.dumps(item(service, requirement), ensure_ascii=False)
    assert datasets['hidden']['id'] not in text
    assert hidden['id'] not in text


def test_single_binding_keeps_existing_alias_equivalence(tmp_path):
    service, scope, datasets, _, _, earlier = setup(tmp_path)
    requirement = service.analysis_requirements_save({
        'parent_id': earlier['id'], 'question': '单表控制数', 'scope': scope, 'bindings': {'renamed': datasets['cc']['id']},
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}]})
    result = item(service, requirement)
    assert result['status'] == 'pending'
    assert result['evidence_paths']['accepted'][0]['path'] == 'run_metric_result_set'
    assert not any('no_finance_context' in path['blockers'] for path in result['evidence_paths']['blocked'])


def test_existing_superset_context_matching_is_preserved(tmp_path):
    service, scope, datasets, _, bindings, requirement = setup(tmp_path)
    # Diagnostics must not silently tighten the established matcher: an engine
    # context may bind additional inputs while covering all required aliases.
    expanded = {**bindings, 'extra': datasets['hidden']['id']}
    service.save_context({'bindings': expanded, 'scopes': {key: scope for key in expanded}})
    result = item(service, requirement)
    assert result['evidence_paths']['accepted'][0]['path'] == 'run_metric_result_set'
    assert not any('no_finance_context' in path['blockers'] for path in result['evidence_paths']['blocked'])
