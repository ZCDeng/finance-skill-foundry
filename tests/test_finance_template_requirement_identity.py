"""Explicit statement output pins cannot silently rename the requested metric."""

from copy import deepcopy

import pytest

from foundry.errors import FoundryError
from foundry.finance_driver_templates import OUTPUT_SEMANTICS, TEMPLATE_ID
from foundry.finance_requirements import check_requirements, prepare_requirements
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.fixture
def service(tmp_path):
    store = FinanceStore(TaskStore(tmp_path / 'var').create(title='Template requirement identity'))
    source = tmp_path / 'amounts.json'
    source.write_text('[{"amount":"12","currency":"CNY","unit":"元"}]')
    dataset = store.analysis.add_dataset(source, name='Engineering identity input')
    store.test_context = store.save_context({'bindings': {'source': dataset['id']}})
    return store


def requirement(metric, dimensions, service=None):
    return {**({'context_id': service.test_context['id']} if service else {}),
            'question': 'Explain the requested engineering output', 'items': [
        {'id': 'statement-output', 'metric': metric, 'label': 'Output under review', 'dimensions': dimensions},
    ]}


def persisted_json(service):
    return {str(path.relative_to(service.task.root)): path.read_bytes()
            for path in service.task.root.rglob('*.json')}


@pytest.mark.parametrize('metric,pin', [
    ('profit', 'net_income'),
    ('net_income', 'closing_cash'),
    ('net_income', 'unregistered_output'),
])
@pytest.mark.parametrize('entry', ['prepare', 'save'])
def test_conflicting_template_identity_refused_before_writes(service, metric, pin, entry):
    spec = requirement(metric, {'template_id': TEMPLATE_ID, 'metric_key': pin})
    original = deepcopy(spec)
    before = persisted_json(service)

    with pytest.raises(FoundryError) as refused:
        if entry == 'prepare':
            prepare_requirements(service.analysis, spec)
        else:
            service.analysis_requirements_save(spec)

    message = str(refused.value)
    assert 'statement-output' in message and TEMPLATE_ID in message
    assert 'conflict' in message and 'metric_key' in message
    assert metric in message and pin in message
    assert 'canonical' in message and 'net_income' in message
    assert spec == original
    assert persisted_json(service) == before


def test_conflict_does_not_replace_existing_requirement_and_explicit_correction_can_save(service):
    first = service.analysis_requirements_save(requirement('net_income', {'template_id': TEMPLATE_ID}, service))
    invalid = {**requirement('profit', {'template_id': TEMPLATE_ID, 'metric_key': 'net_income'}, service),
               'parent_id': first['id']}
    before = persisted_json(service)
    with pytest.raises(FoundryError, match='conflict'):
        service.analysis_requirements_save(invalid)
    assert persisted_json(service) == before

    corrected = deepcopy(invalid)
    corrected['items'][0]['metric'] = 'net_income'
    revised = service.analysis_requirements_save(corrected)
    assert revised['parent_id'] == first['id']
    assert revised['items'][0]['metric'] == 'net_income'
    assert revised['items'][0]['dimensions']['metric_key'] == 'net_income'
    assert service.analysis._get('requirements', first['id']) == first


def test_all_registered_output_identities_remain_exact_and_uncomputed(service):
    spec = {'context_id': service.test_context['id'], 'question': 'Register all statement outputs', 'items': [
        {'id': metric, 'metric': metric, 'dimensions': {'template_id': TEMPLATE_ID, 'metric_key': metric}}
        for metric in OUTPUT_SEMANTICS
    ]}
    saved = service.analysis_requirements_save(spec)
    assert [(item['metric'], item['dimensions']['metric_key']) for item in saved['items']] == [
        (metric, metric) for metric in OUTPUT_SEMANTICS
    ]
    result = check_requirements(service.analysis, {'run_ids': [], 'claims': []})
    assert all(item['status'] == 'pending' for item in result['items'])


@pytest.mark.parametrize('metric,dimensions', [
    ('ratio', {'metric_key': 'collection_rate_current'}),
    ('variance_ratio', {'metric_key': 'operating_margin'}),
    ('profit', {'metric_key': 'operating_profit'}),
    ('profit', {'template_id': 'custom_management_template', 'metric_key': 'net_income'}),
    ('unsupported_output', {}),
    ('unsupported_output', {'template_id': TEMPLATE_ID}),
    ('unsupported_output', {'template_id': TEMPLATE_ID, 'metric_key': 'unsupported_output'}),
])
def test_generic_pins_and_unanswered_requirements_can_still_be_registered(service, metric, dimensions):
    saved = service.analysis_requirements_save(requirement(metric, dimensions, service))
    assert saved['items'][0]['metric'] == metric
    assert saved['items'][0]['dimensions'] == dimensions
    result = check_requirements(service.analysis, {'run_ids': [], 'claims': []})
    assert result['items'][0]['status'] == 'pending'
