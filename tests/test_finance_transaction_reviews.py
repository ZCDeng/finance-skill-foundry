"""Trusted decisions close only a source-bound transaction-check obligation."""
from copy import deepcopy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


CHECKLIST = ('source_evidence', 'policy_applicability', 'recognition_cutoff', 'classification_measurement', 'boundaries')


def case(tmp_path, *, wrong=False, gap=False, body=None):
    service = FinanceStore(TaskStore(tmp_path / 'var').create(title='Synthetic transaction review'), actor='manager')
    scope = {'organization': 'Engineering Co', 'period': '2026-08', 'currency': 'CNY', 'unit': '元'}
    policy = 'expense_consumed_service_v1'
    row = {**scope, 'transaction_id': 'SYN-7', 'transaction_type': 'ordinary_service_consumed',
           'recognition_date': '2026-08-31', 'amount': '84', 'service_consumed_in_period': True,
           'future_economic_benefit': False, 'policy_id': policy, 'policy_reference': 'synthetic-policy-7',
           'policy_effective_from': '2026-01-01', 'policy_effective_to': '2026-12-31',
           'policy_transaction_type': 'ordinary_service_consumed'}
    if gap:
        row.pop('policy_reference')
    path = tmp_path / 'source.json'
    path.write_text(json.dumps([row]))
    dataset = service.analysis.add_dataset(path, name='Source')
    context = service.save_context({'bindings': {'source': dataset['id']}, 'scopes': {'source': scope}})
    req = service.analysis_requirements_save({'context_id': context['id'], 'question': 'Review consumed service recognition',
        'items': [{'id': 'review', 'metric': 'transaction_review', 'requires_drilldown': False}]})
    fields = (set(row) - set(scope)) | {'policy_reference'}
    inputs = {'scope': scope, 'source_bindings': {name: {'alias': 'source', 'column': name, 'aggregation': 'single',
        'selector': {'transaction_id': 'SYN-7'}, 'scope': scope, 'period': scope['period'], 'currency': 'CNY', 'unit': '元'}
        for name in fields}, 'proposed_entries': {'expense': '0' if wrong else '84', 'capitalized_asset': '84' if wrong else '0'}}
    scenario = service.save_scenario({'context_id': context['id'], 'kind': 'transaction_review', 'label': 'Synthetic check', 'inputs': inputs})
    run = service.run_scenario({'scenario_id': scenario['id']})
    facts = service.prepare_explanation({'run_ids': [run['id']]})['facts']
    draft = service.save_explanation_draft({'requirements_id': req['id'], 'run_ids': [run['id']],
        'body': body or '\n'.join('{{fact:' + fact['id'] + '}}' for fact in facts) or 'Missing source facts'})
    return service, dataset, context, req, scenario, run, draft


def prepared(service, draft):
    return service.finance_transaction_review_prepare({'draft_id': draft['id']})


def decide(service, draft, *, state=None, decision='approved', **extra):
    state = state or prepared(service, draft)
    return service.finance_transaction_review_save({'draft_id': draft['id'], 'basis_fingerprint': state['basis_fingerprint'],
        'decision': decision, 'reviewer': 'Synthetic engineering reviewer', 'reason': 'Engineering test; not a real professional sign-off',
        'checklist': dict.fromkeys(CHECKLIST, True), **extra})


def test_qualified_check_waits_for_manager_then_approved_same_draft_gets_new_receipt(tmp_path):
    service, dataset, context, req, scenario, run, draft = case(tmp_path)
    assert draft['completion']['status'] == 'awaiting_manager'
    state = prepared(service, draft)
    assert state['eligibility']['eligible'] and state['current_status'] == 'pending'
    assert state['required_checklist'] == list(CHECKLIST)
    old = {path: path.read_bytes() for folder in ('drafts', 'completions') for path in (service.analysis.root / folder).glob('*.json')}
    decision = decide(service, draft, state=state)
    assert decision['current_status'] == 'approved'
    assert decision['completion']['status'] == 'complete'
    checked = service.validate_explanation({'draft_id': draft['id']})
    assert checked['status'] == 'pass', checked
    assert checked['requirements']['items'][0]['counts_as_amount_evidence'] is False
    refreshed = service.save_explanation_draft({'draft_id': draft['id']})
    assert refreshed['id'] == draft['id'] and refreshed['completion']['status'] == 'complete'
    assert refreshed['completion']['id'] != draft['completion']['id']
    assert service.analysis.draft_in_view(service.analysis.get_draft(draft['id']), None)['quality']['status'] == 'pass'
    assert all(path.read_bytes() == data for path, data in old.items())
    assert run['result']['evidence_eligible'] is False
    assert not any(fact['evidence_eligibility']['counts_as_amount_evidence'] for fact in service.prepare_explanation({'run_ids': [run['id']]})['facts'])


@pytest.mark.parametrize('kind', ['assistant', 'runtime_manager', 'spoof'])
def test_decision_authority_comes_from_manager_call_without_session(tmp_path, kind):
    manager, *_, draft = case(tmp_path)
    caller = FinanceStore(manager.task, actor='manager' if kind == 'runtime_manager' else None,
                          session_id='runtime' if kind == 'runtime_manager' else None)
    with pytest.raises(FoundryError, match='manager|session'):
        decide(caller, draft, **({'actor': 'manager'} if kind == 'spoof' else {}))


@pytest.mark.parametrize('change', [{'checklist': {}}, {'checklist': dict.fromkeys(CHECKLIST, 1)},
                                   {'checklist': {**dict.fromkeys(CHECKLIST, True), 'posting': True}},
                                   {'checklist': {**dict.fromkeys(CHECKLIST, True), 'boundaries': False}},
                                   {'reviewer': ''}, {'actor': 'manager'}])
def test_approval_exact_fields_and_all_true_checklist(tmp_path, change):
    service, *_, draft = case(tmp_path)
    with pytest.raises(FoundryError):
        decide(service, draft, **change)


@pytest.mark.parametrize('kwargs', [{'wrong': True}, {'gap': True}, {'body': 'Unsupported amount 987654 元。'}])
def test_failed_gap_or_wrong_body_cannot_be_approved_but_rejection_is_auditable(tmp_path, kwargs):
    service, *_, draft = case(tmp_path, **kwargs)
    state = prepared(service, draft)
    assert not state['eligibility']['eligible']
    with pytest.raises(FoundryError):
        decide(service, draft, state=state)
    rejected = decide(service, draft, state=state, decision='rejected')
    assert rejected['review']['decision'] == 'rejected'
    assert rejected['completion']['status'] != 'complete'


def test_revoke_and_reprepare_reapprove_cannot_reuse_old_basis_or_complete_receipt(tmp_path):
    service, *_, draft = case(tmp_path)
    before = prepared(service, draft)
    approved = decide(service, draft, state=before)
    rejected = service.finance_transaction_review_revoke({'review_id': approved['review']['id'], 'reason': 'Synthetic withdrawal'})
    assert rejected['completion']['status'] != 'complete'
    narrow = FinanceStore(service.task, snapshot_ids=service.analysis.draft_snapshots(service.analysis.get_draft(draft['id'])), session_id='reader')
    assert prepared(narrow, draft)['current_status'] == 'revoked'
    assert narrow.analysis.completion_in_view(approved['completion'], narrow.allowed)['status'] != 'complete'
    with pytest.raises(FoundryError):
        decide(service, draft, state=before)
    assert service.save_explanation_draft({'draft_id': draft['id']})['completion']['status'] != 'complete'
    assert decide(service, draft)['completion']['status'] == 'complete'


@pytest.mark.parametrize('mutation', ['source', 'policy', 'rule', 'requirements', 'scenario'])
def test_current_basis_changes_invalidate_approval_without_rewriting_history(tmp_path, mutation):
    service, dataset, context, req, scenario, run, draft = case(tmp_path)
    approved = decide(service, draft)
    original = service.analysis._object_path('drafts', draft['id']).read_bytes()
    if mutation in {'source', 'policy'}:
        rows = deepcopy(service.analysis.read_dataset(dataset['id'])['rows'])
        rows[0]['amount' if mutation == 'source' else 'policy_reference'] = '86' if mutation == 'source' else 'replacement-policy'
        path = tmp_path / 'replacement.json'
        path.write_text(json.dumps(rows))
        service.analysis.add_dataset(path, name='Source')
    elif mutation == 'rule':
        service.finance_rule_epoch_advance({'rule_id': 'accounting.transaction_recognition', 'expected_epoch': 0, 'reason': 'Synthetic review'})
    elif mutation == 'requirements':
        service.analysis_requirements_save({'parent_id': req['id'], 'context_id': context['id'], 'question': 'Updated obligation', 'items': req['items']})
    else:
        service.save_scenario({'parent_id': scenario['id'], 'changes': {'proposed_entries': {'expense': '85', 'capitalized_asset': '0'}}, 'label': 'Replacement proposal'})
    assert prepared(service, draft)['current_status'] == 'stale'
    assert service.analysis.completion_in_view(approved['completion'], None)['status'] != 'complete'
    assert service.analysis._object_path('drafts', draft['id']).read_bytes() == original


def test_clone_override_cross_task_and_hidden_sources_cannot_inherit_decision(tmp_path):
    service, _, context, req, _, run, draft = case(tmp_path)
    approved = decide(service, draft)
    clone = service.save_explanation_draft({'parent_id': draft['id'], 'body': draft['body'], 'requirements_id': req['id'], 'run_ids': [run['id']]})
    assert clone['id'] != draft['id'] and clone['completion']['status'] != 'complete'
    assert service.validate_explanation({'draft_id': draft['id'], 'body': draft['body'] + '\nChanged.'})['status'] != 'pass'
    with pytest.raises(FoundryError):
        service.save_explanation_draft({'draft_id': draft['id'], 'body': draft['body']})
    other = FinanceStore(TaskStore(tmp_path / 'other').create(title='Other'), actor='manager')
    with pytest.raises(FoundryError):
        prepared(other, draft)
    with pytest.raises(FoundryError):
        prepared(FinanceStore(service.task, snapshot_ids=[]), draft)
    assert service.analysis.completion_in_view(approved['completion'], None)['status'] == 'complete'


def test_prepared_basis_is_compare_and_swap_under_concurrent_decisions(tmp_path):
    service, *_, draft = case(tmp_path)
    state = prepared(service, draft)
    def attempt(_):
        try:
            return decide(FinanceStore(service.task, actor='manager'), draft, state=state)['review']['decision']
        except FoundryError:
            return 'refused'
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(attempt, range(2))) == ['approved', 'refused']


def test_original_save_request_replays_current_decision_and_unrelated_rule_keeps_approval(tmp_path):
    service, _, _, req, _, run, draft = case(tmp_path)
    facts = service.prepare_explanation({'run_ids': [run['id']]})['facts']
    request = {'requirements_id': req['id'], 'run_ids': [run['id']],
               'body': '\n'.join('{{fact:' + fact['id'] + '}}' for fact in facts)}
    approved = decide(service, draft)
    service.finance_rule_epoch_advance({'rule_id': 'accounting.depreciation_start', 'expected_epoch': 0,
                                       'reason': 'Synthetic unrelated rule review'})
    assert prepared(service, draft)['current_status'] == 'approved'
    replay = service.save_explanation_draft(request)
    assert replay['id'] == draft['id'] and replay['completion']['status'] == 'complete'
    service.finance_transaction_review_revoke({'review_id': approved['review']['id'], 'reason': 'Synthetic withdrawal'})
    replay = service.save_explanation_draft(request)
    assert replay['id'] == draft['id'] and replay['completion']['status'] != 'complete'
    assert replay['quality']['transaction_review']['current_status'] == 'revoked'


def test_every_transaction_run_must_pass_and_be_fully_cited(tmp_path):
    service, _, context, req, scenario, run, _ = case(tmp_path)
    invalid = service.save_scenario({'context_id': context['id'], 'kind': 'transaction_review', 'label': 'Second invalid check',
                                    'inputs': {**scenario['inputs'], 'proposed_entries': {'expense': '0', 'capitalized_asset': '84'}}})
    bad_run = service.run_scenario({'scenario_id': invalid['id']})
    ids = [run['id'], bad_run['id']]
    facts = service.prepare_explanation({'run_ids': ids})['facts']
    draft = service.save_explanation_draft({'requirements_id': req['id'], 'run_ids': ids,
                                            'body': '\n'.join('{{fact:' + fact['id'] + '}}' for fact in facts)})
    state = prepared(service, draft)
    assert not state['eligibility']['eligible']
    assert 'transaction_check_not_passed' in state['eligibility']['reasons']
    with pytest.raises(FoundryError):
        decide(service, draft, state=state)


@pytest.mark.parametrize('mutation', ['hidden_bindings', 'session', 'sequence', 'checklist'])
def test_malformed_latest_event_fails_closed_before_snapshot_filtering(tmp_path, mutation):
    from foundry.analysis import _hash
    service, *_, draft = case(tmp_path)
    approved = decide(service, draft)
    revoked = service.finance_transaction_review_revoke({'review_id': approved['review']['id'], 'reason': 'Synthetic withdrawal'})
    record = deepcopy(revoked['review'])
    if mutation == 'hidden_bindings':
        record['bindings']['hidden'] = 'f' * 32
    elif mutation == 'session':
        record['session_id'] = 'spoofed-runtime'
    elif mutation == 'sequence':
        record['seq'] = True
    else:
        record['checklist']['boundaries'] = 'true'
    record.pop('_integrity_hash')
    record['_integrity_hash'] = _hash(record)
    service._path('transaction_reviews', record['id']).write_text(json.dumps(record))
    allowed = service.analysis.draft_snapshots(service.analysis.get_draft(draft['id']))
    for reader in (service, FinanceStore(service.task, snapshot_ids=allowed)):
        with pytest.raises(FoundryError):
            prepared(reader, draft)
        assert reader.analysis.completion_in_view(approved['completion'], reader.allowed)['status'] != 'complete'
