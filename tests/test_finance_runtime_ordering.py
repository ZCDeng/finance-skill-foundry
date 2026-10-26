"""Runtime ordering failures reproduced with independent engineering source data."""
from copy import deepcopy
import hashlib
import json

import pytest

from foundry.errors import FoundryError
from foundry.finance_driver_templates import BOUNDARY_INPUTS, TEMPLATE_ID
from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def setup_case(tmp_path, *, scenario_name=None):
    manager = FinanceStore(TaskStore(tmp_path / 'var').create(title='Runtime ordering engineering case'), actor='manager')
    scope = {'organization': 'Ordering Engineering Co', 'currency': 'CNY', 'unit': '元'}
    if scenario_name is not None:
        scope['scenario'] = scenario_name
    values = dict(opening_cash=160, opening_receivables=80, opening_ppe=300, opening_payables=60,
                  opening_debt=120, opening_equity=360, revenue=210, customer_receipts=190,
                  operating_expense=95, supplier_payments=90, depreciation=15, capex=35,
                  debt_drawdowns=10, debt_principal_repayments=25, dividends_paid=5, closing_restricted_cash=12)
    values.update(dict.fromkeys(BOUNDARY_INPUTS, 0))
    rows = [{**scope, 'input_name': name, 'amount': str(value),
             'period': '2026-10' if name.startswith('opening_') else '2026-11'} for name, value in values.items()]
    source = tmp_path / 'engineering.json'
    source.write_text(json.dumps(rows))
    dataset = manager.analysis.add_dataset(source, name='Engineering inputs')
    context = manager.save_context({'bindings': {'inputs': dataset['id']}, 'scopes': {'inputs': scope},
        'reporting_profile': {'schema_version': 1, 'basis': 'management', 'basis_version': 'management-v1',
            'fiscal_year_start': '2026-01-01', 'early_adoption': False,
            'purpose': 'forecast', 'effective_period': {'start': '2026-01', 'end': '2026-12'},
            'functional_currency': 'CNY', 'presentation_currency': 'CNY', 'presentation_unit': '元',
            'entity_scope': scope['organization']}})
    manager.finance_profile_confirm({'context_id': context['id'], 'confirmed_fields': sorted(BASE_FIELDS | STANDARD_FIELDS)})
    inputs = {'template_id': TEMPLATE_ID, 'period': '2026-11', 'scope': scope,
              'source_bindings': {row['input_name']: {'alias': 'inputs', 'column': 'amount',
                    'selector': {'input_name': row['input_name']}, 'aggregation': 'single', 'scope': scope,
                    'period': row['period'], 'currency': 'CNY', 'unit': '元'} for row in rows}}
    scenario = manager.save_scenario({'context_id': context['id'], 'kind': 'driver_model', 'label': 'Three statements', 'inputs': inputs})
    manager.finance_profile_confirm({'context_id': context['id'], 'scenario_id': scenario['id'],
                                      'confirmed_model_boundaries': list(BOUNDARY_INPUTS)})
    runtime = FinanceStore(manager.task, snapshot_ids=[dataset['id']], session_id='engineering-runtime')
    return manager, runtime, context, scenario


def register(service, context, scenario, **overrides):
    spec = {'context_id': context['id'], 'question': 'Compute source-bound management statement outputs',
            'scope': {**scenario['inputs']['scope'], 'period': scenario['inputs']['period']},
            'items': [{'id': 'profit', 'metric': 'net_income', 'dimensions': {'template_id': TEMPLATE_ID, 'scenario_id': scenario['id']},
                       'requires_drilldown': False}]}
    return service.analysis_requirements_save({**spec, **overrides})


def task_bytes(service):
    return {str(path.relative_to(service.task.root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in service.task.root.rglob('*') if path.is_file() and path.suffix == '.json'}


@pytest.mark.parametrize('caller', ['session', 'assistant', 'manager_session'])
def test_missing_requirements_refused_before_any_revision_or_run(tmp_path, caller):
    manager, runtime, _, scenario = setup_case(tmp_path)
    if caller == 'assistant':
        runtime = FinanceStore(manager.task)
    elif caller == 'manager_session':
        runtime = FinanceStore(manager.task, actor='manager', session_id='model-runtime')
    before = task_bytes(manager)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        runtime.run_scenario({'scenario_id': scenario['id'], 'actor': 'manager'})
    assert task_bytes(manager) == before
    assert not manager.analysis._list('requirements')


def test_late_registration_never_rebinds_historical_run_and_new_run_captures_current_fp(tmp_path):
    manager, runtime, context, scenario = setup_case(tmp_path)
    # A trusted native manager may inspect arithmetic before defining a deliverable.
    old = manager.run_scenario({'scenario_id': scenario['id']})
    assert old['execution_status'] == 'succeeded' and old['requirements_id'] is None
    old_path = manager.analysis._object_path('runs', old['id'])
    original = old_path.read_bytes()
    requirement = register(runtime, context, scenario)
    fresh = runtime.run_scenario({'scenario_id': scenario['id']})
    assert fresh['execution_status'] == 'succeeded', fresh.get('error')
    assert fresh['id'] != old['id'] and fresh['seq'] > requirement['seq']
    assert fresh['requirements_id'] == requirement['id']
    assert fresh['requirements_semantic_fingerprint'] == requirement['semantic_fingerprint']
    assert old_path.read_bytes() == original
    assert manager.analysis.get_run(old['id'])['requirements_id'] is None


@pytest.mark.parametrize('mismatch', ['context', 'binding', 'period', 'organization', 'currency', 'unit', 'template', 'scenario', 'metric'])
def test_requirement_must_match_context_source_and_requested_output_scope(tmp_path, mismatch):
    manager, runtime, context, scenario = setup_case(tmp_path)
    options = {}
    if mismatch == 'context':
        context = manager.save_context({'bindings': context['bindings'], 'scopes': context['scopes']})
    elif mismatch == 'binding':
        source = tmp_path / 'other.json'
        source.write_text('[{"amount":"9"}]')
        other = manager.analysis.add_dataset(source, name='Other')
        other_context = manager.save_context({'bindings': {'inputs': other['id']}})
        options = {'context_id': other_context['id'], 'bindings': {'inputs': other['id']}}
        runtime = FinanceStore(manager.task, session_id='runtime')
    elif mismatch in {'period', 'organization', 'currency', 'unit'}:
        options = {'scope': {**scenario['inputs']['scope'], 'period': '2026-11',
                            mismatch: {'period': '2026-12', 'organization': 'Other Co', 'currency': 'USD', 'unit': '万元'}[mismatch]}}
    else:
        dimensions = {'template_id': TEMPLATE_ID, 'scenario_id': scenario['id']}
        if mismatch == 'template':
            dimensions['template_id'] = 'unregistered-template'
        elif mismatch == 'scenario':
            dimensions['scenario_id'] = 'f' * 32
        options = {'items': [{'id': 'out', 'metric': 'unsupported_output' if mismatch == 'metric' else 'net_income',
                             'dimensions': dimensions, 'requires_drilldown': False}]}
    register(manager, context, scenario, **options)
    before = task_bytes(manager)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        runtime.run_scenario({'scenario_id': scenario['id']})
    assert task_bytes(manager) == before


def test_latest_unreadable_requirement_cannot_fall_back_to_visible_older_one(tmp_path):
    manager, runtime, context, scenario = setup_case(tmp_path)
    previous = register(manager, context, scenario)
    path = tmp_path / 'hidden.json'
    path.write_text('[{"amount":"17"}]')
    hidden = manager.analysis.add_dataset(path, name='Hidden')
    manager.analysis_requirements_save({'bindings': {'hidden': hidden['id']}, 'parent_id': previous['id'],
                                       'change_reason': 'Replace with a restricted source obligation',
                                       'question': 'Current restricted obligation',
                                       'items': [{'id': 'restricted', 'metric': 'profit'}]})
    before = task_bytes(manager)
    with pytest.raises(FoundryError, match='context|analysis_requirements_save'):
        runtime.run_scenario({'scenario_id': scenario['id']})
    assert task_bytes(manager) == before


def test_direct_revision_path_has_same_guard(tmp_path):
    manager, runtime, context, scenario = setup_case(tmp_path)
    revision = manager._save_revision(context, 'scenario', {'scenario_id': scenario['id']})
    before = task_bytes(manager)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        runtime.run_revision(revision)
    assert task_bytes(manager) == before


def test_invalid_requirement_fingerprint_is_not_current_authority(tmp_path):
    from foundry.analysis import _hash
    manager, runtime, context, scenario = setup_case(tmp_path)
    req = deepcopy(register(manager, context, scenario))
    req['semantic_fingerprint'] = '0' * 64
    req.pop('_integrity_hash')
    req['_integrity_hash'] = _hash(req)
    manager.analysis._object_path('requirements', req['id']).write_text(json.dumps(req))
    before = task_bytes(manager)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        runtime.run_scenario({'scenario_id': scenario['id']})
    assert task_bytes(manager) == before


def test_unrelated_driver_model_keeps_existing_native_behavior(tmp_path):
    _, runtime, context, _ = setup_case(tmp_path)
    scenario = runtime.save_scenario({'context_id': context['id'], 'kind': 'driver_model', 'label': 'Arithmetic scratch',
                                     'inputs': {'drivers': [{'name': 'x', 'formula': '3'}, {'name': 'y', 'formula': 'x * 2'}]}})
    run = runtime.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    assert run['requirements_id'] is None


@pytest.mark.parametrize('rule_id,refused', [('statements.linked_management', True),
                                          ('driver.source_binding', True),
                                          ('variance.volume_mix_price', False)])
def test_requirement_professional_identity_must_still_be_current(tmp_path, rule_id, refused):
    manager, runtime, context, scenario = setup_case(tmp_path)
    requirement = register(manager, context, scenario)
    manager.finance_rule_epoch_advance({'rule_id': rule_id, 'expected_epoch': 0,
                                      'reason': 'Independent engineering invalidation test'})
    if refused:
        before = task_bytes(manager)
        with pytest.raises(FoundryError, match='analysis_requirements_save'):
            runtime.run_scenario({'scenario_id': scenario['id']})
        assert task_bytes(manager) == before
    else:
        run = runtime.run_scenario({'scenario_id': scenario['id']})
        assert run['execution_status'] == 'succeeded'
        assert run['requirements_semantic_fingerprint'] == requirement['semantic_fingerprint']


def test_matching_one_requested_period_can_run_without_claiming_other_periods(tmp_path):
    _, runtime, context, scenario = setup_case(tmp_path)
    requirement = register(runtime, context, scenario, scope=scenario['inputs']['scope'],
        items=[{'id': 'profit', 'metric': 'net_income', 'dimensions': {'template_id': TEMPLATE_ID,
                'scenario_id': scenario['id']}, 'periods': ['2026-11', '2026-12']}])
    run = runtime.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    assert run['requirements_id'] == requirement['id']
    assert {row['period'] for row in run['result']['rows']} == {'2026-11'}


def test_direct_revision_refuses_requirement_changed_after_capture(tmp_path, monkeypatch):
    from foundry import finance_requirement_semantics
    manager, runtime, context, scenario = setup_case(tmp_path)
    previous = register(runtime, context, scenario)
    revision = manager._save_revision(context, 'scenario', {'scenario_id': scenario['id']})
    original_capture = finance_requirement_semantics.capture_requirements
    captured = {}

    def revise_after_capture(*args, **kwargs):
        snapshot = original_capture(*args, **kwargs)
        current = register(runtime, context, scenario, parent_id=previous['id'],
                           question='Changed delivery question after capture')
        captured.update(snapshot=snapshot, current=current, bytes=task_bytes(manager))
        return snapshot

    monkeypatch.setattr(finance_requirement_semantics, 'capture_requirements', revise_after_capture)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        runtime.run_revision(revision)
    assert captured['snapshot']['requirements_id'] == previous['id']
    assert captured['current']['id'] != previous['id']
    assert task_bytes(manager) == captured['bytes']
    assert not manager.analysis._list('runs')


def test_registering_current_rule_basis_restores_runtime_eligibility(tmp_path):
    manager, runtime, context, scenario = setup_case(tmp_path)
    previous = register(runtime, context, scenario)
    manager.finance_rule_epoch_advance({'rule_id': 'statements.linked_management', 'expected_epoch': 0,
                                      'reason': 'Engineering change requires refreshed registration'})
    current = register(runtime, context, scenario, parent_id=previous['id'])
    run = runtime.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    assert run['requirements_id'] == current['id']
    assert run['requirements_semantic_fingerprint'] == current['semantic_fingerprint']
    assert current['semantic_fingerprint'] != previous['semantic_fingerprint']


@pytest.mark.parametrize('actual,requested,placement,refused', [
    ('management-forecast', 'actual', 'scope', True),
    ('actual', 'budget', 'scope', True),
    (None, 'actual', 'scope', True),
    ('management-forecast', 'management-forecast', 'scope', False),
    ('actual', 'actual', 'scope', False),
    ('management-forecast', 'actual', 'item', True),
    (None, 'actual', 'item', True),
    ('management-forecast', 'management-forecast', 'item', False),
])
def test_explicit_common_or_item_scenario_requires_same_model_identity(tmp_path, actual, requested, placement, refused):
    manager, runtime, context, scenario = setup_case(tmp_path, scenario_name=actual)
    scope = {**scenario['inputs']['scope'], 'period': scenario['inputs']['period']}
    items = [{'id': 'profit', 'metric': 'net_income', 'dimensions': {
        'template_id': TEMPLATE_ID, 'scenario_id': scenario['id']}}]
    if placement == 'scope':
        scope['scenario'] = requested
    else:
        scope.pop('scenario', None)
        items[0]['scenarios'] = [requested]
    requirement = register(runtime, context, scenario, scope=scope, items=items)
    before = task_bytes(manager)
    if refused:
        with pytest.raises(FoundryError, match='analysis_requirements_save'):
            runtime.run_scenario({'scenario_id': scenario['id']})
        assert task_bytes(manager) == before
    else:
        run = runtime.run_scenario({'scenario_id': scenario['id']})
        assert run['execution_status'] == 'succeeded'
        assert run['requirements_id'] == requirement['id']


def test_matching_period_and_scenario_within_multigrain_requirement_can_run(tmp_path):
    _, runtime, context, scenario = setup_case(tmp_path, scenario_name='management-forecast')
    requirement = register(runtime, context, scenario,
        scope={key: value for key, value in scenario['inputs']['scope'].items() if key != 'scenario'},
        items=[{'id': 'profit', 'metric': 'net_income', 'dimensions': {'template_id': TEMPLATE_ID,
                'scenario_id': scenario['id']}, 'periods': ['2026-11', '2026-12'],
                'scenarios': ['management-forecast', 'budget']}])
    run = runtime.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    assert run['requirements_id'] == requirement['id']
