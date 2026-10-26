"""A delivery read must prove the current saved version without creating evidence."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from foundry.finance_completion_operations import CompletionOperationStore
from foundry.finance_service import FinanceStore
from foundry.finance_delivery_verification import verify_delivery
from test_finance_completion_fingerprint import ratio_case, rewrite_test_record
from test_finance_saved_delivery import ratio_spec
from test_finance_runtime_payload import ROOT


@pytest.fixture
def delivery(tmp_path):
    manager, req, run, context = ratio_case(tmp_path)
    session = 'delivery-boundary-session'
    manager.task.record_session(session, role='analysis')
    snapshots = list(context['bindings'].values())
    service = FinanceStore(manager.task, snapshot_ids=snapshots, session_id=session)
    request_key = f'{session}:message:user-one:seq:1'
    operation = CompletionOperationStore(manager.task, session, snapshots).begin(request_key)
    saved = service.save_completion_draft(operation['id'], 'save-call', ratio_spec(service, run))
    assert saved['completion']['status'] == 'complete'
    spec = {'request_key': request_key, 'call_id': 'save-call', 'saved_result': saved}
    return service, manager, req, run, spec


def tree(task):
    return {str(p.relative_to(task.root)): p.read_bytes() for p in task.root.rglob('*') if p.is_file()}


def test_current_authorized_delivery_is_exact_and_read_only(delivery):
    service, _, _, _, spec = delivery
    before = tree(service.task)
    result = verify_delivery(service, spec)
    assert result['verified'] is True
    assert result['final_response'] == spec['saved_result']['final_response']
    assert result['bindings']['draft_id'] == spec['saved_result']['id']
    assert result['bindings']['receipt_id'] == spec['saved_result']['completion']['id']
    assert result['bindings']['run_ids'] == spec['saved_result']['run_ids']
    assert tree(service.task) == before


@pytest.mark.parametrize('field', ['request_key', 'call_id', 'task_id', 'body', 'content_hash',
                                  'requirements_id', 'run_ids', 'final_response', 'receipt', 'contract'])
def test_changed_request_or_saved_proof_never_substitutes(delivery, field):
    service, _, _, _, original = delivery
    spec = deepcopy(original)
    if field in {'request_key', 'call_id'}:
        spec[field] = 'another-request'
    elif field == 'receipt':
        spec['saved_result']['completion']['status'] = 'repair_available'
    elif field == 'contract':
        spec['saved_result']['delivery_contract']['receipt_id'] = 'f' * 32
    else:
        spec['saved_result'][field] = [] if field == 'run_ids' else 'forged'
    before = tree(service.task)
    result = verify_delivery(service, spec)
    assert result == {'verified': False, 'reason': 'delivery_proof_not_current'}
    assert tree(service.task) == before


@pytest.mark.parametrize('mutation', ['new_requirement', 'new_draft', 'hidden', 'other_session', 'manager',
                                     'corrupt_draft', 'corrupt_receipt', 'corrupt_run', 'corrupt_output'])
def test_current_authority_and_artifact_integrity_are_rechecked(delivery, mutation):
    service, manager, req, run, spec = delivery
    if mutation == 'new_requirement':
        manager.analysis_requirements_save({'parent_id': req['id'], 'question': '新请求',
                                           'bindings': req['bindings'], 'items': req['items']})
    elif mutation == 'new_draft':
        manager.save_explanation_draft({**ratio_spec(manager, run), 'title': 'Later version'})
    elif mutation == 'hidden':
        service = FinanceStore(manager.task, snapshot_ids=[], session_id=service.session_id)
    elif mutation == 'other_session':
        service = FinanceStore(manager.task, snapshot_ids=list(req['bindings'].values()), session_id='different')
    elif mutation == 'manager':
        service = manager
    elif mutation == 'corrupt_output':
        path = service.analysis.root / 'test-output.json'
        path.write_bytes(b'{}')
        changed = {**run, 'outputs': [{'artifact_path': path.name,
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
        rewrite_test_record(service.analysis._object_path('runs', run['id']), changed)
        path.write_bytes(b'corrupt')
    else:
        kind, record_id = {'corrupt_draft': ('drafts', spec['saved_result']['id']),
                           'corrupt_receipt': ('completions', spec['saved_result']['completion']['id']),
                           'corrupt_run': ('runs', run['id'])}[mutation]
        path = service.analysis._object_path(kind, record_id)
        data = json.loads(path.read_text())
        data['task_id'] = 'corrupted'
        path.write_text(json.dumps(data))
    before = tree(service.task)
    assert verify_delivery(service, spec) == {'verified': False, 'reason': 'delivery_proof_not_current'}
    assert tree(service.task) == before


def test_actual_cli_registered_session_rechecks_without_new_records(delivery, tmp_path):
    service, _, _, _, spec = delivery
    path = tmp_path / 'delivery.json'
    path.write_text(json.dumps(spec))
    before = tree(service.task)
    result = subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'foundry.cli', '--var',
                             str(tmp_path / 'var'), '--session', service.session_id,
                             'finance-delivery-verify', '--spec-file', str(path)],
                            cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['final_response'] == spec['saved_result']['final_response']
    assert tree(service.task) == before


def test_elapsed_deadline_cannot_reuse_unexpired_stored_status(delivery):
    service, _, _, _, spec = delivery
    path = service.analysis.root / 'completion_operations' / (spec['saved_result']['completion_operation_id'] + '.json')
    operation = json.loads(path.read_text())
    assert operation['status'] == 'complete'
    operation['deadline_at'] = '2000-01-01T00:00:00Z'
    rewrite_test_record(path, operation)
    before = tree(service.task)
    assert verify_delivery(service, spec)['verified'] is False
    assert tree(service.task) == before


def test_new_request_save_binds_its_own_operation_and_keeps_prior_draft_bytes(delivery):
    service, _, _, _, old = delivery
    key = service.session_id + ':message:refresh:seq:20'
    operation = CompletionOperationStore(service.task, service.session_id, service.allowed).begin(key)
    before_draft = service.analysis._object_path('drafts', old['saved_result']['id']).read_bytes()
    saved = service.save_completion_draft(operation['id'], 'refresh-call', {
        **ratio_spec(service, service.analysis.get_run(old['saved_result']['run_ids'][0])), 'title': 'New request'})
    spec = {'request_key': key, 'call_id': 'refresh-call', 'saved_result': saved}
    assert saved['id'] != old['saved_result']['id']
    before = tree(service.task)
    assert verify_delivery(service, spec)['verified'] is True
    assert tree(service.task) == before
    assert service.analysis._object_path('drafts', old['saved_result']['id']).read_bytes() == before_draft


def test_native_rule_epoch_change_blocks_previous_runtime_delivery(tmp_path):
    from test_finance_statement_draft_template import statement
    service, _, _, _, _, prepared = statement.__wrapped__(tmp_path)
    service.task.record_session(service.session_id, role='analysis')
    key = service.session_id + ':message:epoch:seq:1'
    operation = CompletionOperationStore(service.task, service.session_id, service.allowed).begin(key)
    saved = service.save_completion_draft(operation['id'], 'epoch-call', prepared['save_template_spec'])
    spec = {'request_key': key, 'call_id': 'epoch-call', 'saved_result': saved}
    assert verify_delivery(service, spec)['verified'] is True
    manager = FinanceStore(service.task, actor='manager')
    manager.finance_rule_epoch_advance({'rule_id': 'statements.linked_management', 'expected_epoch': 0,
                                       'reason': 'Synthetic change'})
    before = tree(service.task)
    assert verify_delivery(service, spec)['verified'] is False
    assert tree(service.task) == before


@pytest.mark.parametrize('period', ['2026-08', '2026-09'])
def test_visible_unrelated_source_does_not_invalidate_delivery(delivery, tmp_path, period):
    service, manager, _, _, spec = delivery
    path = tmp_path / 'unrelated.json'
    path.write_text(json.dumps([{'amount': '999', 'period': period}]))
    new = manager.analysis.add_dataset(path, name=f'Other logical source {period}')
    service.allowed.add(new['id'])
    assert verify_delivery(service, spec)['verified'] is True


def test_only_visible_source_replacement_invalidates_current_delivery(delivery, tmp_path):
    service, manager, req, _, spec = delivery
    old = manager.analysis.read_dataset(next(iter(req['bindings'].values())))
    path = tmp_path / 'replacement.json'
    path.write_text(json.dumps([{**row, 'amount': '111'} for row in old['rows']]))
    new = manager.analysis.add_dataset(path, name=old['name'])
    assert verify_delivery(service, spec)['verified'] is True
    service.allowed.add(new['id'])
    before = tree(service.task)
    assert verify_delivery(service, spec)['verified'] is False
    assert tree(service.task) == before
