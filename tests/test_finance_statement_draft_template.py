"""Concise draft aid keeps actual citations and the existing completion gate."""
from copy import deepcopy

import pytest

from foundry.finance_driver_templates import OUTPUT_SEMANTICS, TEMPLATE_ID
from foundry.finance_explanations import FACT_TOKEN
from foundry.errors import FoundryError
from test_finance_runtime_ordering import setup_case, register


@pytest.fixture
def statement(tmp_path):
    _, service, context, scenario = setup_case(tmp_path, scenario_name='management-forecast')
    requirements = register(service, context, scenario, items=[
        {'id': metric, 'metric': metric, 'dimensions': {'template_id': TEMPLATE_ID, 'scenario_id': scenario['id']},
         'requires_drilldown': False} for metric in OUTPUT_SEMANTICS])
    run = service.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    prepared = service.prepare_explanation({'run_ids': [run['id']], 'fact_view': 'inspection'})
    return service, context, scenario, requirements, run, prepared


def test_concise_template_saves_all_current_qualified_outputs_without_duplicate_claims(statement):
    service, _, _, requirements, run, prepared = statement
    template = prepared['draft_template']
    assert template and template['requirements_id'] == requirements['id']
    assert template['run_ids'] == [run['id']]
    assert template['claims'] == [] and template['fact_ids'] == []
    tokens = FACT_TOKEN.findall(template['body'])
    selected = [fact for fact in prepared['facts'] if fact['id'] in tokens]
    assert len(tokens) == len(set(tokens)) == len(OUTPUT_SEMANTICS)
    assert {f['semantics']['metric'] for f in selected} == set(OUTPUT_SEMANTICS)
    assert all(f['evidence_eligibility']['counts_as_amount_evidence'] for f in selected)
    assert '差异均为0' not in template['body']
    assert len(template['body']) < 2600
    draft = service.save_explanation_draft(template)
    assert draft['quality']['status'] == 'pass', draft['quality']['issues']
    assert draft['completion']['status'] == 'complete', draft['completion']
    assert len([i for i in draft['quality']['requirements']['items'] if i['status'] == 'answered']) == len(OUTPUT_SEMANTICS)
    assert service.validate_explanation({'draft_id': draft['id']})['status'] == 'pass'


def test_template_is_not_returned_for_a_stale_requirement(statement):
    service, context, scenario, requirements, run, _ = statement
    register(service, context, scenario, question='A new question', parent_id=requirements['id'],
             items=requirements['items'])
    assert service.prepare_explanation({'run_ids': [run['id']]})['draft_template'] is None


def test_template_is_not_returned_for_multiple_runs(statement):
    service, _, scenario, _, run, _ = statement
    other = service.run_scenario({'scenario_id': scenario['id']})
    assert service.prepare_explanation({'run_ids': [run['id'], other['id']]})['draft_template'] is None


@pytest.mark.parametrize('mutation', ['ineligible', 'metric_identity', 'missing_fact', 'duplicate_fact', 'failed_check', 'unbound'])
def test_draft_aid_never_repairs_or_qualifies_missing_evidence(statement, mutation):
    from foundry.finance_explanations import _statement_draft_template
    service, _, _, _, run, prepared = statement
    changed = deepcopy(prepared)
    proof = next(p for p in changed['structure_counts'] if p['kind'] == 'required_metrics')
    fact = next(f for f in changed['facts'] if f['id'] == proof['fact_ids'][0])
    if mutation == 'ineligible':
        fact['evidence_eligibility']['counts_as_amount_evidence'] = False
    elif mutation == 'metric_identity':
        fact['metric_identity']['metric_key'] = 'wrong_metric'
    elif mutation == 'missing_fact':
        changed['facts'].remove(fact)
    elif mutation == 'duplicate_fact':
        changed['facts'].append(deepcopy(fact))
    elif mutation == 'failed_check':
        next(p for p in changed['structure_counts'] if p['kind'] == 'model_checks')['all_pass'] = False
    else:
        proof['source_bound'] = False
    before = deepcopy(changed)
    assert _statement_draft_template(service.analysis, [run], changed) is None
    assert changed == before


def test_editing_template_still_runs_existing_financial_and_completion_checks(statement):
    service, _, _, _, _, prepared = statement
    template = deepcopy(prepared['draft_template'])
    template['body'] += '\n期末现金余额为 999999 元。'
    draft = service.save_explanation_draft(template)
    assert draft['quality']['status'] == 'needs_attention'
    assert draft['completion']['status'] != 'complete'
    assert any(i['code'] in {'uncited_number', 'fact_metric_semantics_mismatch'} for i in draft['quality']['issues'])


def test_short_save_spec_reuses_qualified_template_and_persists_complete_receipt(statement):
    service, _, _, requirements, run, prepared = statement
    spec = prepared['save_template_spec']
    assert spec == {'use_prepared_template': True, 'run_ids': [run['id']],
                    'requirements_id': requirements['id'], 'qualitative_note': ''}
    draft = service.save_explanation_draft({**spec, 'qualitative_note': '按当前已确认边界编制，保留专业复核限制。'})
    assert draft['quality']['status'] == 'pass'
    assert draft['completion']['status'] == 'complete'
    assert len(draft['claims']) == len(OUTPUT_SEMANTICS)
    assert '保留专业复核限制' in draft['body']
    assert draft['body_template'].startswith(prepared['draft_template']['body'])
    replay = service.save_explanation_draft({**spec, 'qualitative_note': '按当前已确认边界编制，保留专业复核限制。'})
    assert replay['id'] == draft['id'] and replay['replayed']


@pytest.mark.parametrize('field,value', [('body', '可用资金999999元'), ('body_template', 'forged'),
                                       ('document', {}), ('claims', []), ('fact_ids', [])])
def test_short_save_does_not_silently_discard_conflicting_user_content(statement, field, value):
    service, _, _, _, _, prepared = statement
    with pytest.raises(FoundryError, match='prepared template'):
        service.save_explanation_draft({**prepared['save_template_spec'], field: value})
    assert service.analysis._list('drafts') == []


def test_short_save_still_checks_additional_amounts_and_wrong_financial_identity(statement):
    service, _, _, _, _, prepared = statement
    draft = service.save_explanation_draft({**prepared['save_template_spec'],
        'qualitative_note': '期末现金余额为999999元。'})
    assert draft['quality']['status'] == 'needs_attention'
    assert draft['completion']['status'] != 'complete'
    assert any(i['code'] in {'uncited_number', 'fact_metric_semantics_mismatch'} for i in draft['quality']['issues'])


def test_short_save_refuses_stale_or_mismatched_requirements(statement):
    service, context, scenario, requirements, _, prepared = statement
    new = register(service, context, scenario, question='New question', parent_id=requirements['id'],
                   items=requirements['items'])
    with pytest.raises(FoundryError, match='prepared template'):
        service.save_explanation_draft(prepared['save_template_spec'])
    with pytest.raises(FoundryError, match='prepared template'):
        service.save_explanation_draft({**prepared['save_template_spec'], 'requirements_id': new['id']})
    assert service.analysis._list('drafts') == []


def test_short_save_repair_replaces_parent_text_and_obsolete_claims(statement):
    service, _, _, _, _, prepared = statement
    bad = service.save_explanation_draft({**prepared['draft_template'],
        'body': prepared['draft_template']['body'] + '\n期末现金余额999999元。',
        'claims': [{'basis': 'user_assumption', 'value': '999999', 'text': '未经确认的估计'}]})
    repaired = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': bad['id']})
    assert repaired['completion']['status'] == 'complete'
    assert '999999' not in repaired['body']
    assert all(c.get('basis') == 'calculation' for c in repaired['claims'])
    assert service.analysis.get_draft(bad['id'])['quality']['status'] == 'needs_attention'
