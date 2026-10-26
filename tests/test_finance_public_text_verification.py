"""A runtime-captured native result needs fresh read-only server authority."""
from copy import deepcopy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from foundry.finance_service import FinanceStore
from test_finance_professional_protocol import _template_case
from test_finance_public_check_semantics import ZERO_LIVE, METADATA_LIVE

ROOT = Path(__file__).resolve().parents[1]


def verify(service, spec):
    from foundry.finance_delivery_verification import verify_public_text
    return verify_public_text(service, spec)


def tree(task):
    return {str(p.relative_to(task.root)): p.read_bytes() for p in task.root.rglob('*') if p.is_file()}


@pytest.fixture
def public_proof(tmp_path):
    manager, context, req, initial = _template_case(tmp_path)
    session = 'public-native-session'
    row = manager.task.record_session(session, role='analysis')
    service = FinanceStore(manager.task, snapshot_ids=row['snapshot_ids'], session_id=session,
                           context_revision=row['context_revision'])
    run = service.run_scenario({'scenario_id': initial['result']['scenario_id']})
    capture = {'session_id': session, 'tool_name': 'finance_scenario_run', 'call_id': 'native-call',
               'task_id': service.task.id, 'run_id': run['id'], 'requirements_id': req['id'],
               'output_hash': run['output_hash'], 'template_id': run['result']['template_id'],
               'scenario_id': run['result']['scenario_id'], 'context_revision': run['context_revision']}
    spec = {'request_key': session + ':message:user:seq:1', 'nonce': 'validation-one',
            'capture': capture, 'text': '正在准备文稿。\n' + ZERO_LIVE + '\n随后保存。'}
    return service, manager, req, run, spec


@pytest.mark.parametrize('text', [ZERO_LIVE, METADATA_LIVE])
def test_actual_assertion_family_projects_only_check_line_and_does_not_write(public_proof, text):
    service, _, _, run, original = public_proof
    spec = {**original, 'text': '正在准备文稿。\n' + text + '\n随后保存。'}
    before = tree(service.task)
    proof = verify(service, spec)
    assert proof['verified'] is True and proof['status'] == 'contradicted', proof
    assert proof['delivered_text'].startswith('正在准备文稿。\n')
    assert proof['delivered_text'].endswith('\n随后保存。')
    assert text not in proof['delivered_text']
    assert proof['raw_text_sha256'] == hashlib.sha256(spec['text'].encode()).hexdigest()
    assert proof['delivered_text_sha256'] == hashlib.sha256(proof['delivered_text'].encode()).hexdigest()
    assert proof['bindings']['output_hash'] == run['output_hash']
    assert proof['bindings']['request_authority'] == 'runtime_must_verify_current_request_and_capture'
    assert proof['bindings']['nonce'] == spec['nonce']
    assert tree(service.task) == before


@pytest.mark.parametrize('text', ['All 12 model checks pass.',
    'cash_sufficiency is alert severity and blocks_evidence=false.',
    'Nine equality checks have zero differences.', '正在读取来源，稍后继续核对。'])
def test_normal_public_text_stays_exact(public_proof, text):
    service, _, _, _, spec = public_proof
    proof = verify(service, {**spec, 'text': text})
    assert proof['verified'] and proof['status'] == 'unchanged', proof
    assert proof['delivered_text'] == text


@pytest.mark.parametrize('field', ['run_id', 'task_id', 'session_id', 'requirements_id', 'output_hash',
                                   'template_id', 'scenario_id', 'context_revision', 'tool_name'])
def test_forged_capture_cannot_borrow_truth(public_proof, field):
    service, _, _, _, original = public_proof
    spec = deepcopy(original)
    spec['capture'][field] = 99 if field == 'context_revision' else 'forged'
    before = tree(service.task)
    result = verify(service, spec)
    assert result['verified'] is False and result['status'] == 'unverifiable'
    assert result['bindings'] is None and result['issues'] == []
    assert ZERO_LIVE not in result['delivered_text']
    assert tree(service.task) == before


@pytest.mark.parametrize('mutation', ['new_requirement', 'hidden', 'wrong_session', 'manager',
                                      'corrupt_run', 'revoked_boundary', 'new_rule_epoch'])
def test_fresh_identity_qualification_is_rechecked(public_proof, mutation):
    service, manager, req, run, spec = public_proof
    if mutation == 'new_requirement':
        manager.analysis_requirements_save({'parent_id': req['id'], 'context_id': req['context_id'], 'question': '另一期问题', 'items': req['items']})
    elif mutation == 'hidden':
        service = FinanceStore(service.task, snapshot_ids=[], session_id=service.session_id, context_revision=1)
    elif mutation == 'wrong_session':
        service = FinanceStore(service.task, snapshot_ids=service.allowed, session_id='unknown', context_revision=1)
    elif mutation == 'manager':
        service = manager
    elif mutation == 'corrupt_run':
        path = service.analysis._object_path('runs', run['id'])
        value = json.loads(path.read_text())
        value['result']['model_checks'][-1]['severity'] = 'error'
        path.write_text(json.dumps(value))
    elif mutation == 'revoked_boundary':
        confirmation = manager._list('profile_confirmations')[-1]
        manager.finance_profile_revoke({'id': confirmation['id'], 'reason': '待复核'})
    else:
        manager.finance_rule_epoch_advance({'rule_id': 'statements.linked_management', 'expected_epoch': 0, 'reason': '重新复核'})
    before = tree(service.task)
    result = verify(service, spec)
    assert result['verified'] is False and result['status'] == 'unverifiable', result
    assert result['issues'] == []
    assert tree(service.task) == before


def test_cli_is_internal_read_only_and_request_echo_is_not_authority(public_proof, tmp_path):
    service, _, _, _, spec = public_proof
    path = tmp_path / 'proof.json'
    path.write_text(json.dumps(spec))
    before = tree(service.task)
    process = subprocess.run([str(ROOT/'.venv/bin/python'), '-B', '-m', 'foundry.cli', '--var', str(tmp_path/'var'),
                              '--session', service.session_id, 'finance-public-text-verify', '--spec-file', str(path)],
                             cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)['status'] == 'contradicted'
    assert tree(service.task) == before
    # SDK request event/capture ownership must be verified by the runtime. The
    # server must disclose that this echoed correlation is not its own proof.
    result = verify(service, {**spec, 'request_key': service.session_id + ':message:other:seq:20'})
    assert result['bindings']['request_authority'] == 'runtime_must_verify_current_request_and_capture'


def test_prepare_capture_uses_stored_identity_and_no_manager_run_can_be_borrowed(public_proof):
    service, manager, _, run, original = public_proof
    spec = deepcopy(original)
    spec['capture'].update(tool_name='prepare_explanation', context_revision=None)
    assert verify(service, spec)['status'] == 'contradicted'
    other = manager.run_scenario({'scenario_id': run['result']['scenario_id']})
    assert other['output_hash'] == run['output_hash']
    spec['capture']['run_id'] = other['id']
    assert verify(service, spec)['status'] == 'unverifiable'


def test_registered_other_session_same_amount_cannot_supply_evidence(public_proof):
    service, manager, _, run, original = public_proof
    row = manager.task.record_session('other-native-session', role='analysis')
    other = FinanceStore(manager.task, snapshot_ids=row['snapshot_ids'], session_id=row['session_id'],
                         context_revision=row['context_revision'])
    newrun = other.run_scenario({'scenario_id': run['result']['scenario_id']})
    assert newrun['output_hash'] == run['output_hash']
    spec = deepcopy(original)
    spec['capture']['run_id'] = newrun['id']
    before = tree(service.task)
    assert verify(service, spec)['status'] == 'unverifiable'
    assert tree(service.task) == before


@pytest.mark.parametrize('mutation', ['context_revision', 'source_bytes', 'superseded_source', 'sql_forgery'])
def test_source_and_native_identity_cannot_be_substituted(public_proof, mutation, tmp_path):
    from test_finance_completion_fingerprint import rewrite_test_record
    from foundry.analysis import _hash
    service, manager, _, run, spec = public_proof
    if mutation == 'context_revision':
        path = tmp_path / 'new-context.json'
        path.write_text('[{"note":"new context"}]')
        added = manager.analysis.add_dataset(path, name='new context')
        manager.task.update_session_context(service.session_id, snapshot_ids=[added['id']])
    elif mutation == 'source_bytes':
        dataset = manager.analysis.read_dataset(next(iter(run['bindings'].values())))
        # Change the archived data under the existing immutable metadata.
        path = manager.analysis.root / 'datasets' / dataset['id'] / 'data.json'
        assert path.is_file()
        path.write_text('[]')
    elif mutation == 'superseded_source':
        dataset = manager.analysis.read_dataset(next(iter(run['bindings'].values())))
        changed_rows = deepcopy(dataset['rows'])
        changed_rows[0]['amount'] = '999'
        path = tmp_path / 'replacement.json'
        path.write_text(json.dumps(changed_rows))
        new = manager.analysis.add_dataset(path, name=dataset['name'])
        row = manager.task.update_session_context(service.session_id, snapshot_ids=[*service.allowed, new['id']])
        service = FinanceStore(service.task, snapshot_ids=row['snapshot_ids'], session_id=service.session_id,
                               context_revision=row['context_revision'])
        spec = deepcopy(spec)
        spec['capture']['context_revision'] = row['context_revision']
    else:
        changed = deepcopy(run)
        changed['engine'] = 'sql'
        changed['output_hash'] = _hash(changed['result'])
        rewrite_test_record(service.analysis._object_path('runs', run['id']), changed)
    before = tree(service.task)
    result = verify(service, spec)
    assert result['status'] == 'unverifiable' and result['bindings'] is None
    assert tree(service.task) == before


def test_missing_proof_does_not_erase_unrelated_progress(public_proof):
    service, _, _, _, spec = public_proof
    spec = deepcopy(spec)
    spec['capture']['session_id'] = 'unknown'
    spec['text'] = '正在查看已保存文件。\n'+ZERO_LIVE+'\n下一步准备表格。'
    result = verify(service, spec)
    assert result['delivered_text'].startswith('正在查看已保存文件。\n')
    assert result['delivered_text'].endswith('\n下一步准备表格。')
    assert result['issues'] == [] and result['bindings'] is None


@pytest.mark.parametrize('text', ['cash_sufficiency is error.', 'restricted_cash_bounds is alert.'])
def test_unverifiable_named_check_metadata_is_neutral_without_severity_word(public_proof, text):
    service, _, _, _, spec = public_proof
    spec = deepcopy(spec)
    spec['capture']['session_id'] = 'unknown'
    spec['text'] = text
    result = verify(service, spec)
    assert result['status'] == 'unverifiable' and result['issues'] == [] and result['bindings'] is None
    assert text not in result['delivered_text']


@pytest.mark.parametrize('text', ['正在读取 cash_sufficiency 的来源。', 'The request had a network error.'])
def test_unverifiable_disclosure_filter_does_not_hide_ordinary_id_or_error_mention(public_proof, text):
    service, _, _, _, spec = public_proof
    spec = deepcopy(spec)
    spec['capture']['session_id'] = 'unknown'
    spec['text'] = text
    assert verify(service, spec)['delivered_text'] == text


def test_hidden_successor_requirement_does_not_fall_back_to_old_current(public_proof, tmp_path):
    service, manager, req, _, spec = public_proof
    path = tmp_path/'hidden.json'
    path.write_text('[{"amount":"1"}]')
    hidden = manager.analysis.add_dataset(path, name='hidden requirement source')
    manager.analysis_requirements_save({'parent_id': req['id'], 'question': 'Current hidden requirement',
        'change_reason': 'Replace obligation with separately authorized source',
        'bindings': {'hidden': hidden['id']}, 'items': [{'id': 'current', 'metric': 'account_total',
                                                      'dimensions': {'account': 'cash'}}]})
    before = tree(service.task)
    result = verify(service, spec)
    assert result['status'] == 'unverifiable' and result['bindings'] is None
    assert tree(service.task) == before


def test_supersession_is_rechecked_after_expensive_qualification(public_proof, monkeypatch):
    import foundry.finance_delivery_verification as module
    service, _, _, run, spec = public_proof
    calls = []
    original = module.superseded_snapshots
    def publication_boundary(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs) if len(calls) == 1 else set(run['bindings'].values())
    monkeypatch.setattr(module, 'superseded_snapshots', publication_boundary)
    before = tree(service.task)
    result = verify(service, spec)
    assert len(calls) == 2
    assert result['status'] == 'unverifiable' and result['bindings'] is None
    assert tree(service.task) == before


@pytest.mark.parametrize('change', ['revoked_approval', 'new_requirement', 'source_bytes'])
def test_actual_change_during_qualification_invalidates_pending_proof(public_proof, monkeypatch, change):
    import foundry.finance_professional as professional
    service, manager, req, run, spec = public_proof
    original = professional.cell_evidence_eligibility
    calls = []
    run_bytes = service.analysis._object_path('runs', run['id']).read_bytes()
    def qualify(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 13:
            if change == 'revoked_approval':
                record = manager._list('profile_confirmations')[-1]
                manager.finance_profile_revoke({'id': record['id'], 'reason': 'Changed during proof'})
            elif change == 'new_requirement':
                manager.analysis_requirements_save({'parent_id': req['id'], 'context_id': req['context_id'],
                    'question': 'Changed during proof', 'items': req['items']})
            else:
                dataset_id = next(iter(run['bindings'].values()))
                (manager.analysis.root/'datasets'/dataset_id/'data.json').write_text('[]')
        return result
    monkeypatch.setattr(professional, 'cell_evidence_eligibility', qualify)
    result = verify(service, spec)
    assert len(calls) == 13
    assert result['status'] == 'unverifiable' and result['bindings'] is None
    assert service.analysis._object_path('runs', run['id']).read_bytes() == run_bytes
