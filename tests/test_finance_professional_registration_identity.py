"""Professional registration proves its context before immutable authoring."""
import json
from copy import deepcopy

import pytest

from foundry.analysis import _hash, _new
from foundry.errors import FoundryError
from foundry.finance_professional import requirement_rule_identity
from foundry.finance_requirement_semantics import capture_requirements, requirement_semantics, verified_requirement_fingerprint
from foundry.finance_requirement_support import assess_requirement_support, with_input_gaps
from foundry.finance_requirements import save_requirements
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def setup(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / 'var').create(title='专业登记身份'))
    bindings = {}
    for alias, rows in {
        'sales': [{'product': 'A', 'scenario': scenario, 'quantity': quantity, 'price': '7',
                   'amount': str(quantity * 7), 'quantity_unit': '件', 'unit': '元', 'currency': 'CNY',
                   'period': '2026-09', 'organization': 'O1', 'ledger': 'L1'}
                  for scenario, quantity in [('budget', 10), ('actual', 12)]],
        'public_facts': [{'fact': 'basis', 'value': 'management'}],
    }.items():
        path = tmp_path / (alias + '.json')
        path.write_text(json.dumps(rows))
        bindings[alias] = service.analysis.add_dataset(path, name=alias)['id']
    return service, bindings


def spec(bindings, **extra):
    return {'question': '量结构价完整桥', 'bindings': bindings,
            'items': [{'id': 'bridge', 'metric': 'price_quantity',
                       'dimensions': {'method': 'volume_mix_price'}}], **extra}


def legacy_invalid(service, bindings):
    value = spec(bindings)
    value['items'][0].update(label='price_quantity', requires_drilldown=False)
    semantics = requirement_semantics(service.analysis, value)
    record = _new(service.task, **value, context_id=None, scope={}, parent_id=None,
                  removed_item_ids=[], change_reason=None, selection=None, **semantics)
    return service.analysis._write(service.analysis._object_path('requirements', record['id']), record)


@pytest.mark.parametrize('entry', ['service', 'low_level'])
def test_missing_professional_context_is_refused_before_immutable_write(tmp_path, entry):
    service, bindings = setup(tmp_path)
    with pytest.raises(FoundryError, match='professional.*context.*required_bindings'):
        if entry == 'service':
            service.analysis_requirements_save(spec(bindings))
        else:
            save_requirements(service.analysis, spec(bindings))
    assert service.analysis._list('requirements') == []
    assert service.analysis._list('runs') == []


@pytest.mark.parametrize('explicit', ['superset', 'subset', 'different'])
def test_explicit_binding_mismatch_cannot_be_silently_overwritten(tmp_path, explicit):
    service, bindings = setup(tmp_path)
    context_bindings = {'sales': bindings['sales']} if explicit == 'superset' else bindings
    context = service.save_context({'bindings': context_bindings})
    provided = bindings if explicit == 'superset' else {'sales': bindings['sales']}
    if explicit == 'different':
        provided = {**bindings, 'sales': bindings['public_facts']}
    with pytest.raises(FoundryError, match='bindings.*context'):
        service.analysis_requirements_save(spec(provided, context_id=context['id']))
    assert service.analysis._list('requirements') == []


def test_valid_identity_ignores_caller_identity_and_retains_all_sources(tmp_path):
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': bindings})
    record = service.analysis_requirements_save(spec(bindings, context_id=context['id'],
        professional_identity={'rule_fingerprint': 'forged', 'professional_status': 'supported'},
        semantic_fingerprint='forged', confirmed_by='manager'))
    identity = record['semantic_basis']['professional_identity']
    assert identity['rule_dependencies'] == [{'id': 'variance.volume_mix_price', 'version': 1}]
    assert identity['rule_basis'] == {}
    assert identity['rule_fingerprint'] == _hash({'version': 1, 'dependencies': identity['rule_dependencies'], 'basis': {}})
    assert identity['professional_status'] == 'supported'
    assert record['bindings'] == bindings
    assert verified_requirement_fingerprint(service.analysis, record) == record['semantic_fingerprint']
    preflight = record['support']['preflight']
    assert preflight['professional_identity_status'] == 'supported'
    assert preflight['professional_context_id'] == context['id']
    assert service._list('profile_confirmations') == []


def test_old_null_identity_never_becomes_a_verified_semantic_proof(tmp_path):
    service, bindings = setup(tmp_path)
    record = legacy_invalid(service, bindings)
    archived = deepcopy(record)
    assert record['semantic_fingerprint']
    assert verified_requirement_fingerprint(service.analysis, record) is None
    assert service.analysis._get('requirements', record['id']) == archived
    with pytest.raises(FoundryError, match='professional.*context'):
        capture_requirements(service.analysis)


def test_background_facts_cannot_turn_professional_failure_into_missing_main_data(tmp_path):
    service, bindings = setup(tmp_path)
    record = legacy_invalid(service, bindings)
    service.save_context({'bindings': bindings})
    support = assess_requirement_support(service.analysis, record)
    assert support['items'][0]['status'] != 'requires_input'
    assert support['preflight']['professional_identity_status'] != 'supported'
    checked = with_input_gaps(service.analysis, {'requirements_id': record['id'],
        'items': [{'id': 'bridge', 'status': 'pending', 'professional_reason': 'professional_context_unavailable'}]})
    assert checked['items'][0]['status'] == 'pending'
    assert 'input_gap' not in checked['items'][0]


def test_restricted_session_cannot_register_an_unreadable_professional_context(tmp_path):
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': bindings})
    restricted = FinanceStore(service.task, snapshot_ids=[bindings['sales']], session_id='restricted')
    with pytest.raises(FoundryError, match='outside this session'):
        restricted.analysis_requirements_save(spec(bindings, context_id=context['id']))
    assert service.analysis._list('requirements') == []


def test_context_binding_integrity_is_rechecked_by_low_level_registration(tmp_path):
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': {'sales': bindings['sales']}})
    with pytest.raises(FoundryError, match='bindings.*context'):
        save_requirements(service.analysis, spec(bindings, context_id=context['id']))
    assert service.analysis._list('requirements') == []


def test_missing_profile_approval_stays_blocked_with_complete_structural_identity(tmp_path):
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': bindings})
    record = service.analysis_requirements_save(spec(bindings, context_id=context['id'], items=[{
        'id': 'model', 'metric': 'closing_cash',
        'dimensions': {'template_id': 'linked_three_statement_management_v1'}}]))
    identity = requirement_rule_identity(service.analysis, record)
    assert identity['rule_fingerprint'] and identity['professional_status'] == 'awaiting_profile_confirmation'
    assert verified_requirement_fingerprint(service.analysis, record)
    assert service._list('profile_confirmations') == []


def test_ordinary_requirement_needs_no_professional_context(tmp_path):
    service, bindings = setup(tmp_path)
    record = service.analysis_requirements_save(spec(bindings, items=[{'id': 'total', 'metric': 'control_totals'}]))
    assert record['context_id'] is None
    assert record['semantic_version'] == 1


@pytest.mark.parametrize('corruption', ['context', 'dataset'])
def test_corrupt_context_or_source_is_refused_without_new_records(tmp_path, corruption):
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': bindings})
    path = (service._path('contexts', context['id']) if corruption == 'context'
            else service.analysis.root / 'datasets' / bindings['sales'] / 'data.json')
    path.write_text('{}')
    with pytest.raises((FoundryError, KeyError)):
        service.analysis_requirements_save(spec(bindings, context_id=context['id']))
    assert service.analysis._list('requirements') == []
    assert service.analysis._list('runs') == []


def test_real_revision_repairs_future_identity_without_rewriting_history(tmp_path):
    service, bindings = setup(tmp_path)
    old = legacy_invalid(service, bindings)
    old_bytes = service.analysis._object_path('requirements', old['id']).read_bytes()
    context = service.save_context({'bindings': bindings})
    revised = service.analysis_requirements_save(spec(bindings, context_id=context['id'],
        parent_id=old['id'], change_reason='绑定真实完整财务口径'))
    captured = capture_requirements(service.analysis)
    assert captured['requirements_id'] == revised['id']
    assert captured['requirements_rule_identity']['professional_status'] == 'supported'
    assert captured['requirements_semantic_fingerprint'] != old['semantic_fingerprint']
    assert service.analysis._object_path('requirements', old['id']).read_bytes() == old_bytes


def test_runtime_vmp_requires_current_professional_registration_before_calculation(tmp_path):
    manager, bindings = setup(tmp_path)
    context = manager.save_context({'bindings': bindings})
    runtime = FinanceStore(manager.task, snapshot_ids=list(bindings.values()), session_id='runtime')
    calculation = {'context_id': context['id'], 'kind': 'price_quantity', 'method': 'volume_mix_price'}
    with pytest.raises(FoundryError, match='professional_requirements_required'):
        runtime.explain_variance(calculation)
    assert manager.analysis._list('runs') == []
    record = runtime.analysis_requirements_save(spec(bindings, context_id=context['id']))
    run = runtime.explain_variance(calculation)
    assert run['execution_status'] == 'succeeded'
    assert run['requirements_id'] == record['id']
    assert run['requirements_rule_identity']['rule_fingerprint']
    other = manager.save_context({'bindings': bindings})
    with pytest.raises(FoundryError, match='professional_requirements_required'):
        runtime.explain_variance({**calculation, 'context_id': other['id']})


def test_circle_select_professional_preflight_does_not_leave_an_orphan_context(tmp_path):
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': bindings})
    first = service.analysis_requirements_save(spec(bindings, context_id=context['id']))
    document = {'schema_version': 1, 'template_version': 'annual-v1', 'content': [
        {'type': 'table', 'attrs': {'caption': '口径表'}, 'content': [
            {'type': 'tableRow', 'content': [{'type': 'tableHeader', 'content': [
                {'type': 'paragraph', 'content': [{'type': 'text', 'text': '说明'}]}]}]}]}]}
    draft = service.analysis.save_draft({'document': document})
    updated = service.analysis_circle_select({'kind': 'draft_table', 'context_id': context['id'],
        'draft_id': draft['id'], 'block_id': '口径表', 'range': 'A1', 'instruction': '复核完整范围'})
    assert updated['requirements']['parent_id'] == first['id']
    assert updated['requirements']['context_id'] == updated['context']['id']
    assert updated['requirements']['semantic_basis']['professional_identity']['rule_fingerprint']
    assert len(service._list('contexts')) == 2


def test_identity_diagnostic_does_not_claim_a_historical_approval_changed(tmp_path):
    service, bindings = setup(tmp_path)
    old = legacy_invalid(service, bindings)
    draft = service.save_explanation_draft({'requirements_id': old['id'], 'body': '当前要求仍待完成核验。'})
    completion = draft['completion']
    assert completion['original_requirements_completed'] is False
    assert completion['repair_allowed'] is False
    assert '已变化' not in completion['actions'][0]['message']
    assert 'context' in completion['actions'][0]['message']


def test_identity_loss_during_semantic_authoring_cannot_downgrade_to_v1(tmp_path, monkeypatch):
    from foundry import finance_requirement_semantics
    service, bindings = setup(tmp_path)
    context = service.save_context({'bindings': bindings})
    monkeypatch.setattr(finance_requirement_semantics, 'requirement_semantics', lambda *_args, **_kwargs: {
        'semantic_version': 1, 'semantic_basis': None, 'semantic_fingerprint': None})
    with pytest.raises(FoundryError, match='professional_identity_invalid'):
        service.analysis_requirements_save(spec(bindings, context_id=context['id']))
    assert service.analysis._list('requirements') == []
