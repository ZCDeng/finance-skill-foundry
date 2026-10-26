"""The saved-delivery line names a verified version, never invented body detail."""
from copy import deepcopy
import json
import subprocess

import pytest

from foundry.finance_completion_operations import CompletionOperationStore
from foundry.finance_service import FinanceStore
from test_finance_completion_fingerprint import ratio_case
from test_finance_runtime_payload import ROOT, restore_table
from test_finance_statement_draft_template import statement as _statement_fixture
from test_finance_transaction_reviews import case as transaction_case, decide


LIMIT = '仍待专业复核，不作为审定或过账授权。'
statement = _statement_fixture


def ratio_spec(service, run):
    facts = service.prepare_explanation({'run_ids': [run['id']]})['facts']
    return {'run_ids': [run['id']], 'body': '核对结果：' + '；'.join('{{fact:%s}}' % f['id'] for f in facts)}


@pytest.fixture
def saved_ratio(tmp_path):
    service, req, run, context = ratio_case(tmp_path)
    spec = ratio_spec(service, run)
    saved = service.save_explanation_draft(spec)
    assert saved['completion']['status'] == 'complete'
    return service, spec, saved, context


def assert_complete_delivery(saved):
    assert saved['final_response'] == f"已保存完成，草稿{saved['id']}；{LIMIT}"
    contract = saved['delivery_contract']
    assert contract['draft_id'] == saved['id']
    assert contract['receipt_id'] == saved['completion']['id']
    assert contract['completion_status'] == 'complete'
    assert '\n' not in saved['final_response']


def test_native_save_does_not_repeat_r7_invented_check_detail_description(statement):
    service, _, _, _, run, prepared = statement
    saved = service.save_explanation_draft(prepared['save_template_spec'])
    assert saved['quality']['status'] == 'pass'
    assert run['result']['model_checks']
    assert_complete_delivery(saved)
    # R7 public reply falsely equated persisted run checks with cited draft body detail.
    old_overstatement = '完整 13 项金额与 12 项检查明细均已以真实事实占位符引用写入草稿正文'
    assert old_overstatement not in saved['final_response']
    assert '13' not in saved['delivery_contract']['content_scope']
    assert saved['delivery_contract']['content_scope'] == '正文内容以已保存草稿为准；逐项模型检查请查看对应运行结果。'


def test_saved_version_and_replay_have_identical_delivery_without_new_records(saved_ratio):
    service, spec, saved, _ = saved_ratio
    before = {p: p.read_bytes() for p in service.analysis.root.rglob('*.json')}
    assert_complete_delivery(saved)
    replay = service.save_explanation_draft(spec)
    assert replay['replayed'] and replay['id'] == saved['id']
    assert replay['completion']['id'] == saved['completion']['id']
    assert replay['final_response'] == saved['final_response']
    assert replay['delivery_contract'] == saved['delivery_contract']
    assert {p: p.read_bytes() for p in service.analysis.root.rglob('*.json')} == before
    assert 'final_response' not in service.analysis.get_draft(saved['id'])
    assert 'delivery_contract' not in service.analysis._get('completions', saved['completion']['id'])


def test_user_supplied_delivery_fields_do_not_control_server_reply(saved_ratio):
    service, spec, _, _ = saved_ratio
    saved = service.save_explanation_draft({**spec, 'final_response': '已经审定，所有检查明细已入正文。',
                                          'delivery_contract': {'completion_status': 'complete'}})
    assert_complete_delivery(saved)
    assert '所有检查明细已入正文' not in saved['final_response']


def test_needs_repair_is_not_called_complete_and_successful_repair_binds_new_draft(statement):
    service, _, _, _, _, prepared = statement
    bad = service.save_explanation_draft({**prepared['save_template_spec'], 'qualitative_note': '额外营业收入为987654元。'})
    assert bad['completion']['status'] == 'repair_available'
    assert '已保存完成' not in bad['final_response']
    assert '待修复' in bad['final_response']
    assert bad['delivery_contract']['completion_status'] == 'repair_available'
    old = service.analysis._object_path('drafts', bad['id']).read_bytes()
    fixed = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': bad['id']})
    assert_complete_delivery(fixed)
    assert fixed['id'] != bad['id']
    assert service.analysis._object_path('drafts', bad['id']).read_bytes() == old


def test_unverified_requirements_are_not_called_complete(tmp_path):
    service, _, run, _ = ratio_case(tmp_path, bound=False)
    saved = service.save_explanation_draft(ratio_spec(service, run))
    assert saved['completion']['status'] == 'needs_requirements'
    assert '已保存完成' not in saved['final_response']
    assert '有效需求' in saved['final_response']


@pytest.mark.parametrize('mutation', [
    'body', 'body_template', 'content_hash', 'claims', 'run_ids', 'task_id',
    'receipt_missing', 'receipt_id', 'receipt_draft', 'receipt_content', 'receipt_task',
    'receipt_status', 'receipt_original', 'receipt_response', 'receipt_repair', 'quality',
])
def test_mismatched_receipt_or_saved_content_cannot_claim_complete(saved_ratio, mutation):
    from foundry.finance_saved_delivery import saved_delivery
    service, _, saved, _ = saved_ratio
    changed = deepcopy(saved)
    if mutation in {'body', 'body_template', 'content_hash', 'task_id'}:
        changed[mutation] = 'forged'
    elif mutation in {'claims', 'run_ids'}:
        changed[mutation] = []
    elif mutation == 'receipt_missing':
        changed['completion'] = None
    elif mutation == 'receipt_id':
        changed['completion']['id'] = 'f' * 32
    elif mutation == 'quality':
        changed['quality']['status'] = 'needs_attention'
    else:
        field, value = {'receipt_draft': ('draft_id','f' * 32),
                        'receipt_content': ('draft_content_hash','f' * 64),
                        'receipt_task': ('task_id','f' * 32),
                        'receipt_status': ('status','repair_available'),
                        'receipt_original': ('original_requirements_completed',False),
                        'receipt_response': ('response_status','needs_review'),
                        'receipt_repair': ('repair_allowed',True)}[mutation]
        changed['completion'][field] = value
    before = deepcopy(changed)
    result = saved_delivery(service, changed)
    assert changed == before
    assert '已保存完成' not in result['final_response']
    assert result['delivery_contract']['completion_status'] != 'complete'


def test_hidden_saved_version_and_cross_task_do_not_reveal_bound_receipt(saved_ratio, tmp_path):
    from foundry.finance_saved_delivery import saved_delivery
    from foundry.task import TaskStore
    service, _, saved, _ = saved_ratio
    for reader in (FinanceStore(service.task, snapshot_ids=[]),
                   FinanceStore(TaskStore(tmp_path / 'other').create(title='Other task'))):
        delivery = saved_delivery(reader, saved)
        assert '已保存完成' not in delivery['final_response']
        assert delivery['delivery_contract']['draft_id'] is None
        assert delivery['delivery_contract']['receipt_id'] is None


@pytest.mark.parametrize('kind', ['drafts', 'completions'])
def test_corrupted_persisted_proof_does_not_reuse_old_complete_response(saved_ratio, kind):
    from foundry.finance_saved_delivery import saved_delivery
    service, _, saved, _ = saved_ratio
    object_id = saved['id'] if kind == 'drafts' else saved['completion']['id']
    path = service.analysis._object_path(kind, object_id)
    record = json.loads(path.read_text())
    record['body' if kind == 'drafts' else 'draft_content_hash'] = 'corrupt synthetic record'
    path.write_text(json.dumps(record))
    before = path.read_bytes()
    result = saved_delivery(service, saved)
    assert '已保存完成' not in result['final_response']
    assert path.read_bytes() == before


def test_refresh_and_revocation_follow_current_review_without_mutating_draft(tmp_path):
    from foundry.finance_saved_delivery import saved_delivery
    service, *_, draft = transaction_case(tmp_path)
    assert draft['completion']['status'] == 'awaiting_manager'
    assert '已保存完成' not in draft['final_response']
    before = service.analysis._object_path('drafts', draft['id']).read_bytes()
    approved = decide(service, draft)
    fresh = service.save_explanation_draft({'draft_id': draft['id']})
    assert_complete_delivery(fresh)
    service.finance_transaction_review_revoke({'review_id': approved['review']['id'], 'reason': 'Synthetic withdrawal'})
    revoked = service.save_explanation_draft({'draft_id': draft['id']})
    assert '已保存完成' not in revoked['final_response']
    assert '已保存完成' not in saved_delivery(service, fresh)['final_response']
    assert service.analysis._object_path('drafts', draft['id']).read_bytes() == before


def test_runtime_save_and_replay_use_same_verified_delivery(saved_ratio):
    service, spec, _, context = saved_ratio
    session_id = 'delivery-session'
    snapshots = list(context['bindings'].values())
    service.task.record_session(session_id, role='analysis')
    service.task.update_session_context(session_id, snapshot_ids=snapshots)
    runtime = FinanceStore(service.task, snapshot_ids=snapshots, session_id=session_id)
    ops = CompletionOperationStore(service.task, session_id, snapshot_ids=snapshots)
    operation = ops.begin('saved-delivery-test')
    saved = runtime.save_completion_draft(operation['id'], 'call-one', spec)
    assert_complete_delivery(saved)
    replay = runtime.save_completion_draft(operation['id'], 'call-one', spec)
    assert replay['replayed']
    assert replay['final_response'] == saved['final_response']
    assert replay['delivery_contract'] == saved['delivery_contract']


def test_manager_recovery_projects_delivery_without_changing_operation_rules(tmp_path):
    from foundry.task import TaskStore
    task = TaskStore(tmp_path / 'var').create(title='Recovery delivery')
    ops = CompletionOperationStore(task, 'recovery-session')
    op = ops.begin('recovery delivery')
    spec = {'body':'待补充来源和分析需求。'}
    ops.reserve(op['id'], payload=spec, call_id='call-interrupted')
    ops.stop(op['id'], 'timeout')
    manager = FinanceStore(task, actor='manager')
    request = {'operation_id':op['id'], 'revision':1, 'draft':spec}
    saved = manager.recover_completion_draft(request)
    assert saved['completion']['status'] != 'complete'
    assert '已保存完成' not in saved['final_response']
    replay = manager.recover_completion_draft(request)
    assert replay['replayed']
    assert replay['final_response'] == saved['final_response']


def test_declared_save_view_retains_server_final_response_and_contract(saved_ratio):
    _, _, saved, _ = saved_ratio
    assert_complete_delivery(saved)
    large = deepcopy(saved)
    large['body'] = 'Large document for projection test. ' * 4000
    rendered = subprocess.run(['node', '--input-type=module', '-e', '''
      import fs from 'node:fs';
      import {definitions} from './dsh-plugin/analysis.js';
      const tool = definitions().find(item => item.name === 'save_explanation_draft');
      const output = tool.output.render({}, {stdout: fs.readFileSync(0, 'utf8')});
      if (output.length !== 1 || output[0].type !== 'text') throw Error('unexpected render');
      process.stdout.write(output[0].text);
    '''], cwd=ROOT, input=json.dumps(large), text=True, capture_output=True, check=True)
    packet = json.loads(rendered.stdout)
    assert len(rendered.stdout.encode('utf-8')) <= 48000
    assert packet['_model_projection']['full_result'] is False
    decoded = restore_table(packet)
    assert decoded['final_response'] == saved['final_response']
    assert decoded['delivery_contract'] == saved['delivery_contract']
    assert '/final_response' not in packet['_model_projection']['omitted_paths']
