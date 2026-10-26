"""Registration exposes executable identities before a writer spends its run budget."""
import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_requirement_support import assess_requirement_support
from foundry.finance_requirements import check_requirements, save_requirements
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def _store(tmp_path, *, purpose_column=False):
    analysis = AnalysisStore(TaskStore(tmp_path / 'var').create(title='登记前置核查'))
    datasets = {}
    for alias in ('cc', 'pf'):
        source = tmp_path / f'{alias}.json'
        row = {'management_account': 'subledger', 'amount': '100', 'currency': 'CNY', 'unit': '元', 'origin': alias}
        if purpose_column:
            row['purpose'] = 'management'
        source.write_text(json.dumps([row]))
        datasets[alias] = analysis.add_dataset(source, name=alias)
    return FinanceStore(analysis.task), {key: value['id'] for key, value in datasets.items()}


def _spec(bindings, **updates):
    return {'question': '用于管理报告的同范围核对', 'bindings': bindings,
            'items': [{'id': 'controls', 'metric': 'control_totals'}], **updates}


@pytest.mark.parametrize('scope', [
    {'purpose': 'management', 'currency': 'CNY'},
    {'actual_scope': {'purpose': 'management'}},
])
def test_reporting_purpose_without_a_source_field_is_refused_before_registration(tmp_path, scope):
    service, bindings = _store(tmp_path)
    with pytest.raises(FoundryError, match=r'scope.*purpose.*question'):
        service.analysis_requirements_save(_spec(bindings, scope=scope))
    assert service.analysis._list('requirements') == []
    assert service.analysis._list('runs') == []


def test_real_source_purpose_stays_an_exact_filter(tmp_path):
    service, bindings = _store(tmp_path, purpose_column=True)
    requirement = service.analysis_requirements_save(_spec(bindings, scope={'purpose': 'management'}))
    assert requirement['scope'] == {'purpose': 'management'}
    from foundry.finance_requirements import _scope_matches
    assert _scope_matches({}, {'purpose': 'management'}, requirement['scope'])
    assert not _scope_matches({}, {'purpose': 'external'}, requirement['scope'])
    assert not _scope_matches({}, {}, requirement['scope'])


def test_partial_context_is_exposed_at_registration_without_dropping_public_facts(tmp_path):
    service, bindings = _store(tmp_path)
    partial = service.save_context({'bindings': {'cc': bindings['cc']}})
    requirement = service.analysis_requirements_save(_spec(bindings))
    preflight = requirement['support']['preflight']
    assert preflight['requirements_before_execution'] is True
    assert preflight['required_bindings'] == bindings
    assert preflight['finance_context_status'] == 'missing'
    assert preflight['context_binding_diagnostic']['available_contexts'][0]['context_id'] == partial['id']
    assert preflight['context_binding_diagnostic']['available_contexts'][0]['missing_aliases'] == ['pf']
    execution = requirement['support']['items'][0]['execution_specs'][0]
    assert execution['tool'] == 'run_metric'
    assert execution['spec'] == {'metric': {'kind': 'control_totals'}}
    assert execution['required_bindings'] == bindings
    assert execution['status'] == 'blocked'
    assert execution['blockers'] == ['no_finance_context']
    assert execution['requires_context_id'] is True
    assert requirement['bindings'] == bindings
    assert check_requirements(service.analysis, {'run_ids': [], 'claims': []})['coverage']['status'] != 'pass'


def test_full_context_opens_the_native_spec_without_answering_unexecuted_requirement(tmp_path):
    service, bindings = _store(tmp_path)
    service.save_context({'bindings': bindings})
    requirement = service.analysis_requirements_save(_spec(bindings))
    assert requirement['support']['preflight']['finance_context_status'] == 'ready'
    execution = requirement['support']['items'][0]['execution_specs'][0]
    assert execution['status'] == 'available'
    assert execution['blockers'] == []
    assert check_requirements(service.analysis, {'run_ids': [], 'claims': []})['items'][0]['status'] == 'pending'


def test_unverified_context_id_cannot_open_a_native_path(tmp_path):
    service, bindings = _store(tmp_path)
    # The lower-level authoring API may hold a historical context id; presence
    # alone cannot prove that its sources cover the current obligation.
    requirement = save_requirements(service.analysis, _spec(bindings, context_id='missing-context'))
    support = assess_requirement_support(service.analysis, requirement)
    assert support['preflight']['finance_context_status'] == 'missing'
    assert support['items'][0]['execution_specs'][0]['status'] == 'blocked'


def test_account_total_execution_uses_the_real_registered_account_identity(tmp_path):
    service, bindings = _store(tmp_path)
    service.save_context({'bindings': bindings})
    requirement = service.analysis_requirements_save(_spec(
        bindings, items=[{'id': 'subledger', 'metric': 'subledger'}]))
    spec = requirement['support']['items'][0]['execution_specs'][0]
    assert spec['spec'] == {'metric': {'kind': 'account_total', 'accounts': ['subledger']}}
    ambiguous = assess_requirement_support(service.analysis, _spec(
        bindings, items=[{'id': 'total', 'metric': 'account_total'}]))['items'][0]
    assert ambiguous['metric_identity_diagnostic']['code'] == 'account_total_requires_account_identity'
    assert 'control_totals' in ambiguous['metric_identity_diagnostic']['next_action']
    assert service.analysis._list('runs') == []


def test_preview_and_failed_save_keep_current_preflight_and_blocked_native_spec(tmp_path):
    service, bindings = _store(tmp_path)
    partial = service.save_context({'bindings': {'cc': bindings['cc']}})
    requirement = service.analysis_requirements_save(_spec(bindings))
    run = service.run_metric({'context_id': partial['id'], 'metric': {'kind': 'control_totals'}})
    draft_spec = {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                  'body': '核对仍待补齐执行依据。'}
    preview = service.validate_explanation(draft_spec)
    assert preview['requirements']['support']['preflight']['required_bindings'] == bindings
    saved = service.save_explanation_draft(draft_spec)
    support = saved['quality']['requirements']['support']
    assert support['preflight']['required_bindings'] == bindings
    assert support['items'][0]['execution_specs'][0]['status'] == 'blocked'
    assert saved['completion']['original_requirements_completed'] is False
