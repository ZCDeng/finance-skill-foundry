"""Missing closure evidence is judged on the saved draft through a real receipt."""
from copy import deepcopy
import json

import pytest

from foundry.errors import FoundryError
from foundry.finance_explanations import render_fact_template
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def source_bound_case(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / 'var').create(title='遗漏闭合检查'))
    rows = [{'product': p, 'scenario': scenario, 'quantity': q, 'price': price,
             'quantity_unit': '件', 'ledger': 'L1', 'organization': 'O1',
             'period': '2026-09', 'currency': 'CNY', 'unit': '元'}
            for p, scenario, q, price in [('A', 'budget', '50', '10'), ('B', 'budget', '50', '20'),
                                         ('A', 'actual', '72', '12'), ('B', 'actual', '48', '18')]]
    source = tmp_path / 'basket.json'
    source.write_text(json.dumps(rows))
    dataset = service.analysis.add_dataset(source, name='basket')
    context = service.save_context({'bindings': {'basket': dataset['id']}, 'scopes': {'basket': {
        'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '元'}}})
    requirement = service.analysis_requirements_save({'context_id': context['id'], 'question': '量结构价差异及闭合检查',
        'items': [{'id': 'vmp', 'metric': 'price_quantity', 'dimensions': {'method': 'volume_mix_price'}}]})
    run = service.explain_variance({'context_id': context['id'], 'kind': 'price_quantity',
        'method': 'volume_mix_price', 'actual_scenario': 'actual', 'baseline_scenario': 'budget'})
    facts = [f for f in service.prepare_explanation({'run_ids': [run['id']]})['facts']
             if f['column'] in {'total_variance', 'volume_contribution', 'mix_contribution', 'price_contribution', 'residual'}]
    assert {f['column']: f['value'] for f in facts} == {
        'total_variance': '228', 'volume_contribution': '300', 'mix_contribution': '-120',
        'price_contribution': '48', 'residual': '0'}
    return service, requirement, run, facts, dataset


def authoring_spec(requirement, run, facts, *, omitted=False):
    used = [f for f in facts if not omitted or f['column'] != 'residual']
    template = '\n'.join(f["column"] + ': {{fact:' + f['id'] + '}}' for f in used)
    body, ids = render_fact_template(template, facts)
    return {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'body': body,
            'body_template': template, 'fact_ids': ids, 'claims': [
                {'basis': 'calculation', 'run_id': f['run_id'], 'row': f['row'],
                 'column': f['column'], 'value': f['value'], 'fact_id': f['id']} for f in used]}


def test_saved_effective_missing_check_receives_noncomplete_receipt_without_auto_repair(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    good = service.analysis.save_draft(authoring_spec(requirement, run, facts))
    bad = service.analysis.save_draft(authoring_spec(requirement, run, facts, omitted=True))
    assert good['quality']['status'] == 'pass'
    assert [x['code'] for x in bad['quality']['issues']] == ['missing_required_fact']
    originals = {service.analysis._object_path(kind, row['id']):
                 service.analysis._object_path(kind, row['id']).read_bytes()
                 for kind in ('drafts', 'runs', 'requirements')
                 for row in service.analysis._list(kind)}
    control = service.save_explanation_draft({'draft_id': good['id']})
    assert control['completion']['status'] == 'complete'
    assert control['delivery_contract']['completion_status'] == 'complete'
    assert control['delivery_contract']['receipt_id'] == control['completion']['id']
    result = service.save_explanation_draft({'draft_id': bad['id']})
    assert result['id'] == bad['id']
    assert result['body'] == bad['body']
    assert result['claims'] == bad['claims']
    assert result['fact_ids'] == bad['fact_ids']
    assert result['completion']['draft_id'] == bad['id']
    assert result['completion']['status'] != 'complete'
    assert result['completion']['original_requirements_completed'] is False
    assert result['delivery_contract']['completion_status'] == result['completion']['status']
    assert result['delivery_contract']['receipt_id'] == result['completion']['id']
    assert any(x['code'] == 'missing_required_fact' for x in result['completion']['actions'])
    assert result['validation_basis'] == 'current_saved_explanation'
    assert all(p.read_bytes() == value for p, value in originals.items())
    replay = service.save_explanation_draft({'draft_id': bad['id']})
    assert replay['completion']['id'] == result['completion']['id']
    assert replay['body'] == bad['body']
    assert not any(row['status'] == 'complete' and row['draft_id'] == bad['id']
                   for row in service.analysis._list('completions'))


def test_refresh_cannot_replace_prose_or_smuggle_completion_authority(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    draft = service.analysis.save_draft(authoring_spec(requirement, run, facts, omitted=True))
    before = deepcopy(service.analysis._list('completions'))
    for addition in [{'body': '改写'}, {'quality': {'status': 'pass'}}, {'status': 'complete'}]:
        with pytest.raises(FoundryError):
            service.save_explanation_draft({'draft_id': draft['id'], **addition})
    assert service.analysis._list('completions') == before


def test_hidden_wrong_task_and_runtime_refresh_cannot_issue_receipt(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    draft = service.analysis.save_draft(authoring_spec(requirement, run, facts, omitted=True))
    hidden = FinanceStore(service.task, snapshot_ids=[], session_id='hidden')
    with pytest.raises(FoundryError):
        hidden.save_explanation_draft({'draft_id': draft['id']})
    other = FinanceStore(TaskStore(tmp_path / 'other').create(title='another task'))
    with pytest.raises(FoundryError):
        other.save_explanation_draft({'draft_id': draft['id']})
    runtime = FinanceStore(service.task, session_id='runtime')
    with pytest.raises(FoundryError, match='runtime'):
        runtime.save_explanation_draft({'draft_id': draft['id']})
    with pytest.raises(FoundryError, match='draft_id refresh is not supported'):
        runtime.save_completion_draft('not-an-operation', 'call', {'draft_id': draft['id']})
    assert service.analysis._list('completions') == []


def test_refresh_uses_current_requirements_instead_of_old_pass(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    draft = service.analysis.save_draft(authoring_spec(requirement, run, facts))
    first = service.save_explanation_draft({'draft_id': draft['id']})
    assert first['completion']['status'] == 'complete'
    old_receipt_path = service.analysis._object_path('completions', first['completion']['id'])
    old_receipt = old_receipt_path.read_bytes()
    old_draft_path = service.analysis._object_path('drafts', draft['id'])
    old_draft = old_draft_path.read_bytes()
    service.analysis_requirements_save({
        'parent_id': requirement['id'], 'context_id': requirement['context_id'], 'bindings': requirement['bindings'],
        'question': '量结构价差异及闭合检查，并核对利润',
        'items': [*requirement['items'], {'id': 'profit', 'metric': 'profit', 'requires_drilldown': False}],
    })
    fresh = service.save_explanation_draft({'draft_id': draft['id']})
    assert fresh['quality']['status'] == 'needs_attention'
    assert fresh['completion']['status'] != 'complete'
    assert fresh['completion']['id'] != first['completion']['id']
    assert any(issue['code'] == 'requirements_changed' for issue in fresh['quality']['issues'])
    assert old_receipt_path.read_bytes() == old_receipt
    assert old_draft_path.read_bytes() == old_draft
