"""Registered native outputs retain the exact source-validated scenario grain."""
from copy import deepcopy

import pytest

from foundry.analysis import _hash
from foundry.errors import FoundryError
from foundry.finance_driver_templates import BOUNDARY_INPUTS, OUTPUT_SEMANTICS, TEMPLATE_ID
from foundry.finance_requirements import check_requirements
from foundry.finance_scenario_service import calculate_scenario
from test_finance_native_period_route import claims
from test_finance_requirements import _run
from test_finance_runtime_ordering import register, setup_case, task_bytes
from test_finance_trusted_driver import source_driver


SCENARIO = 'management-forecast'


def grain_items(scenario):
    scope = scenario['inputs']['scope']
    return [{'id': metric, 'metric': metric, 'requires_drilldown': False,
             'periods': [scenario['inputs']['period']], 'organizations': [scope['organization']],
             'scenarios': [SCENARIO],
             'dimensions': {'template_id': TEMPLATE_ID, 'scenario_id': scenario['id'], 'metric_key': metric}}
            for metric in OUTPUT_SEMANTICS]


def save_outputs(service, run, requirement):
    prepared = service.prepare_explanation({'run_ids': [run['id']], 'fact_view': 'inspection'})
    facts = [fact for fact in prepared['facts'] if fact['evidence_eligibility']['counts_as_amount_evidence']]
    assert len(facts) == 13
    return service.save_explanation_draft({'requirements_id': requirement['id'], 'run_ids': [run['id']],
        'body': '\n'.join('{{fact:%s}}' % fact['id'] for fact in facts)})


@pytest.mark.parametrize('short', [False, True])
def test_all_exact_scenario_grains_close_source_requirements_and_persist_save(tmp_path, short):
    _, service, context, scenario = setup_case(tmp_path, scenario_name=SCENARIO)
    requirement = register(service, context, scenario, items=grain_items(scenario))
    run = service.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    assert run['requirements_semantic_fingerprint'] == requirement['semantic_fingerprint']
    saved = save_outputs(service, run, requirement)
    assert saved['completion']['status'] == 'complete', saved['quality']['issues']
    assert len(saved['quality']['requirements']['items']) == 13
    assert all(item['status'] == 'answered' for item in saved['quality']['requirements']['items'])
    assert all(row['scenario'] == SCENARIO for row in run['result']['rows'])
    assert all(row['scenario'] == SCENARIO for row in run['result']['driver_model']['rows'])
    prepared = service.prepare_explanation({'run_ids': [run['id']], 'fact_view': 'inspection'})
    assert len(prepared['facts']) == 29
    assert sum(fact['evidence_eligibility']['counts_as_amount_evidence'] for fact in prepared['facts']) == 13
    if short:
        saved = service.save_explanation_draft(prepared['save_template_spec'])
        assert saved['completion']['status'] == 'complete'
    assert service.validate_explanation({'draft_id': saved['id']})['status'] == 'pass'


@pytest.mark.parametrize('change', ['scenario', 'organization', 'period', 'scenario_id', 'mixed_scenarios'])
def test_wrong_or_incomplete_grains_do_not_gain_completion(tmp_path, change):
    manager, service, context, scenario = setup_case(tmp_path, scenario_name=SCENARIO)
    items = grain_items(scenario)
    for item in items:
        if change == 'scenario_id':
            item['dimensions']['scenario_id'] = 'different-scenario'
        else:
            key, value = {'scenario': ('scenarios', ['actual']), 'organization': ('organizations', ['Other Co']),
                          'period': ('periods', ['2026-10']),
                          'mixed_scenarios': ('scenarios', [SCENARIO, 'actual'])}[change]
            item[key] = value
    requirement = register(service, context, scenario, scope={'unit': '元', 'currency': 'CNY'}, items=items)
    if change != 'mixed_scenarios':
        before = task_bytes(service)
        with pytest.raises(FoundryError, match='analysis_requirements_save'):
            service.run_scenario({'scenario_id': scenario['id']})
        assert task_bytes(service) == before
    run = manager.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    saved = save_outputs(service, run, requirement)
    assert saved['completion']['status'] != 'complete'
    assert all(item['status'] == 'pending' for item in saved['quality']['requirements']['items'])


def test_missing_model_scenario_is_not_invented_from_context_or_requirement(tmp_path):
    manager, service, context, scenario = setup_case(tmp_path)
    requirement = register(service, context, scenario, items=grain_items(scenario))
    before = task_bytes(service)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        service.run_scenario({'scenario_id': scenario['id']})
    assert task_bytes(service) == before
    run = manager.run_scenario({'scenario_id': scenario['id']})
    assert all('scenario' not in row for row in run['result']['rows'])
    assert save_outputs(service, run, requirement)['completion']['status'] != 'complete'


def test_source_and_context_scenario_cannot_replace_a_missing_model_declaration(tmp_path):
    manager, service, context, original = setup_case(tmp_path, scenario_name=SCENARIO)
    inputs = deepcopy(original['inputs'])
    del inputs['scope']['scenario']
    scenario = manager.save_scenario({'context_id': context['id'], 'kind': original['kind'],
        'label': 'Model without a declared scenario', 'inputs': inputs})
    manager.finance_profile_confirm({'context_id': context['id'], 'scenario_id': scenario['id'],
        'confirmed_model_boundaries': list(BOUNDARY_INPUTS)})
    requirement = register(service, context, scenario, items=grain_items(scenario))
    before = task_bytes(service)
    with pytest.raises(FoundryError, match='analysis_requirements_save'):
        service.run_scenario({'scenario_id': scenario['id']})
    assert task_bytes(service) == before
    run = manager.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    assert all(proof['scenario'] == SCENARIO
               for proof in run['result']['source_binding_status']['bindings'].values())
    assert all('scenario' not in row for row in run['result']['rows'])
    assert save_outputs(service, run, requirement)['completion']['status'] != 'complete'


@pytest.mark.parametrize('change', ['mixed', 'wrong'])
def test_conflicting_actual_source_scenarios_still_fail_before_projection(tmp_path, change):
    manager, _, context, scenario = setup_case(tmp_path, scenario_name=SCENARIO)
    datasets = {alias: deepcopy(manager.analysis.read_dataset(key)) for alias, key in context['bindings'].items()}
    rows = datasets['inputs']['rows']
    for row in rows if change == 'wrong' else rows[:1]:
        row['scenario'] = 'actual'
    with pytest.raises(FoundryError):
        calculate_scenario(scenario, context, datasets)


@pytest.mark.parametrize('engine', ['sql', 'python'])
def test_copied_native_scenario_labels_do_not_qualify_other_engines(tmp_path, engine):
    _, service, context, scenario = setup_case(tmp_path, scenario_name=SCENARIO)
    requirement = register(service, context, scenario, items=grain_items(scenario))
    native = service.run_scenario({'scenario_id': scenario['id']})
    result = deepcopy(native['result'])
    for row in result['rows']:
        row.update(scenario=SCENARIO, scenario_id=scenario['id'])
    fake = _run(service.analysis, engine=engine, result=result, output_hash=_hash(result),
                bindings=native['bindings'], finance_scope=native['finance_scope'],
                input_hashes=native['input_hashes'], source_hashes=native['source_hashes'],
                finance_context_id=native['finance_context_id'],
                requirements_rule_identity=native.get('requirements_rule_identity'))
    checked = check_requirements(service.analysis, {'requirements_id': requirement['id'],
        'run_ids': [fake['id']], 'claims': claims(fake)})
    assert all(item['status'] != 'answered' for item in checked['items'])
    reasons = [location.get('evidence', {}).get('not_counted_reason') for item in checked['items']
               for location in item['locations']]
    assert reasons == ['template_evidence_not_qualified'] * 13


def test_generic_driver_does_not_receive_registered_template_projection():
    scenario, context, datasets = source_driver()
    scenario['inputs']['scope'] = {'scenario': SCENARIO}
    for row in datasets['ledger']['rows']:
        row['scenario'] = SCENARIO
    result = calculate_scenario(scenario, context, datasets)
    assert all('scenario' not in row and 'metric_key' not in row for row in result['rows'])
    assert {row['driver']: row['value'] for row in result['rows']}['twice'] == '50'
