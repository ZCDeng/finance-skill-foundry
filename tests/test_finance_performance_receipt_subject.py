"""Current receipt labels require the same local object, period and forecast authority."""
from copy import deepcopy
import json

import pytest

from foundry.finance_claim_semantics import forecast_performance_issues, _performance_receipt_subject
from foundry.finance_explanations import _forecast_performance_sources, saved_claim_semantic_issues
from test_finance_performance_semantics import CODE, performance_case
from test_finance_receipt_source_wording import E18, source_case, save_note

LABEL = '定性说明：①旧应收与本期待履约收款的区别——'
CATEGORIES = '分类说明：本期待履约收款与本期已履约收款是两种类别；本例归于后者。'
TABLE_CATEGORIES = '| 分类 | 本期待履约收款与本期已履约收款是两种类别 |'


@pytest.fixture(scope='module')
def typed_proof(tmp_path_factory):
    service, _, _, run = performance_case(tmp_path_factory.mktemp('receipt-label-proof'))
    result = _forecast_performance_sources(service.analysis, [run])
    assert result['status'] == 'verified' and len(result['facts']) == 2
    return result['facts']


@pytest.mark.parametrize('body', [
    LABEL,
    '本期待履约收款。',
    '- 当期待履约收款',
    '| 本月待履约收款 | 说明 |',
    '当月尚未履约收款。',
    '本期待履约收款（S-CUR-01）。',
    '本期待履约收款（S-CUR-01，2026-10）。',
    '不能把其他合同混入；本期待履约收款。',
])
def test_affirmative_same_period_receipt_labels_have_source_bound_status(typed_proof, body):
    issues = forecast_performance_issues(body, performance_facts=typed_proof)
    assert len(issues) == 1
    assert issues[0]['code'] == CODE and issues[0]['asserted'] == 'pending'
    assert body[issues[0]['position']:].startswith(issues[0]['text'])
    assert all(f['authority'] == 'source_defined_forecast_assumption' for f in issues[0]['source_facts'])


@pytest.mark.parametrize('body', [
    '本期已履约收款。',
    '旧应收回款与本期已履约收款分别追踪。',
    '收款不等于已经履约。',
    '上期未履约收款。',
    '本期待履约收款（OTHER-CONTRACT）。',
    'S-CUR-01 相关本期待履约收款（OTHER-CONTRACT）。',
    'OTHER-CONTRACT 本期待履约收款。',
    'S-CUR-01 与 OTHER-CONTRACT 本期待履约收款。',
    'S-CUR-01 本期待履约收款（2026-11）。',
    '本期待履约收款（2026-11）。',
    '2026-11 本期待履约收款。',
    '现实中本期待履约收款；预测来源设为已履约。',
    '不能把本期收款写成本期待履约收款。',
    '本期待履约收款？',
    '如果本期待履约收款存在，应按合同核对。',
    '“本期待履约收款”这一说法不正确。',
    '分类规则：旧应收回款与本期待履约收款应分别核对。',
    '核对旧应收回款、本期待履约收款两类，不表示本期两类均有发生。',
    '本期收款类别：待履约收款与已履约收款。',
    '本期待履约收款的处理政策仅供参考。',
    '本期在待履约时不得将收款确认为收入。',
])
def test_unresolved_specific_subject_period_or_category_does_not_borrow_forecast_proof(typed_proof, body):
    assert forecast_performance_issues(body, performance_facts=typed_proof) == []


@pytest.mark.parametrize('unknown', [True, False])
def test_mixed_or_unknown_service_facts_do_not_prove_all_current_receipts(typed_proof, unknown):
    facts = deepcopy(typed_proof)
    facts[-1]['state'] = 'unknown' if unknown else 'pending'
    facts[-1]['status'] = 'unverifiable' if unknown else 'verified'
    assert forecast_performance_issues('本期全部待履约收款。', performance_facts=facts) == []


def test_source_false_supports_pending_receipt_without_realworld_inference(tmp_path):
    def mutate(record):
        for key in ['base_current_service', 'additional_sale']:
            record[key]['performed_in_forecast'] = False
    service, _, _, run = performance_case(tmp_path, mutate)
    facts = _forecast_performance_sources(service.analysis, [run])['facts']
    assert all(f['state'] == 'pending' for f in facts)
    assert forecast_performance_issues('本期待履约收款。', performance_facts=facts) == []
    assert forecast_performance_issues('现实中本期已履约收款。', performance_facts=facts) == []
    assert forecast_performance_issues('本期已履约收款。', performance_facts=facts)


def test_receipt_identity_and_period_are_not_fixture_literals(tmp_path):
    service, _, _, run = performance_case(tmp_path, renamed=True, period='2026-11')
    proof = _forecast_performance_sources(service.analysis, [run])['facts']
    assert forecast_performance_issues('本期待履约收款（CLIENT-RENAMED-42，2026-11）。', performance_facts=proof)
    assert forecast_performance_issues('本期待履约收款（CLIENT-RENAMED-42，2026-10）。', performance_facts=proof) == []
    assert forecast_performance_issues('本期待履约收款（OTHER-CONTRACT，2026-11）。', performance_facts=proof) == []


@pytest.mark.parametrize('body,expected', [
    ('本期待履约收款 S-CUR-01。', 1),
    ('S-CUR-01 相关本期待履约收款 S-CUR-01。', 1),
    ('本期待履约收款 OTHER-CONTRACT。', 0),
    ('S-CUR-01 相关本期待履约收款 OTHER-CONTRACT。', 0),
    ('本期待履约收款 S-CUR-01，2026-11。', 0),
    ('本期待履约收款 S-CUR-01，2026-10。', 1),
])
def test_immediate_postfix_id_uses_its_own_local_identity_and_period(typed_proof, body, expected):
    assert len(forecast_performance_issues(body, performance_facts=typed_proof)) == expected


@pytest.mark.parametrize('short', [False, True])
def test_real_immediate_postfix_unknown_contract_does_not_borrow_earlier_source(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    body = 'S-CUR-01 相关本期待履约收款 OTHER-CONTRACT。'
    spec = ({**prepared['save_template_spec'], 'qualitative_note': body} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + body})
    saved = service.save_explanation_draft(spec)
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    (tmp_path / 'actual-adjacent-postfix-save.json').write_text(json.dumps({
        'short': short, 'body': body, 'draft_id': saved['id'], 'run_id': run['id'],
        'quality': saved['quality'], 'completion': saved['completion'], 'issues': issues,
        'authority_boundary': 'unknown local identity supplies neither forecast state', 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert issues == []
    assert saved['completion']['status'] == 'complete', saved['quality']


@pytest.mark.parametrize('body', [
    CATEGORIES,
    '分类说明：本期已履约收款与本期待履约收款是两种类别；本例归于前者。',
    '当月尚未履约收款与当月已经履约收款是两种类别；本例归于后者。',
])
def test_category_definition_labels_do_not_assert_current_instances(typed_proof, body):
    assert forecast_performance_issues(body, performance_facts=typed_proof) == []


@pytest.mark.parametrize('body', [
    '分类说明：本期待履约收款。',
    '分类说明：S-CUR-01 的本期待履约收款。',
    CATEGORIES + '本期待履约收款。',
    '本期已履约收款与本期待履约收款是两种类别；本期待履约收款。',
])
def test_category_prefix_or_earlier_definition_cannot_exempt_wrong_instance(typed_proof, body):
    issues = forecast_performance_issues(body, performance_facts=typed_proof)
    assert len(issues) == 1 and issues[0]['asserted'] == 'pending'


def test_pending_source_category_definition_is_symmetric_and_keeps_wrong_instance(tmp_path):
    def pending(record):
        record['base_current_service']['performed_in_forecast'] = False
    service, _, _, _, run, prepared = source_case(tmp_path, E18, pending)
    facts = prepared['forecast_performance']['facts']
    assert len(facts) == 1 and facts[0]['state'] == 'pending'
    body = '本期已履约收款与本期待履约收款是两种类别；本例归于后者。'
    assert forecast_performance_issues(body, performance_facts=facts) == []
    issues = forecast_performance_issues(body + '本期已履约收款。', performance_facts=facts)
    assert len(issues) == 1 and issues[0]['asserted'] == 'performed'
    assert service.analysis.get_run(run['id']) == run


@pytest.mark.parametrize('short', [False, True])
def test_real_e18_category_definition_does_not_block_either_save(tmp_path, short):
    service, _, _, _, run, prepared = source_case(tmp_path, E18)
    before_run = deepcopy(service.analysis.get_run(run['id']))
    assert len(prepared['forecast_performance']['facts']) == 1
    saved = save_note(service, prepared, CATEGORIES, short)
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    (tmp_path / 'actual-category-definition-save.json').write_text(json.dumps({
        'short': short, 'body': CATEGORIES, 'draft_id': saved['id'], 'run_id': run['id'],
        'quality': saved['quality'], 'completion': saved['completion'], 'issues': issues,
        'source_proof': prepared['forecast_performance'], 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert issues == []
    assert saved['completion']['status'] == 'complete', saved['quality']
    assert CATEGORIES in saved['body']
    assert service.analysis.get_run(run['id']) == before_run


@pytest.mark.parametrize('body', [
    '本期待履约收款与本期已履约收款是两种类别。',
    '## 分类：本期待履约收款与本期已履约收款是两种类别',
    '- 本期待履约收款与本期已履约收款是两种类别',
    TABLE_CATEGORIES,
    '| 分类 | 本期已履约收款与本期待履约收款是两种类别 |',
    TABLE_CATEGORIES + ' 本期已履约收款 |',
    '分类 | 本期待履约收款与本期已履约收款是两种类别 |',
])
def test_table_cell_category_termination_keeps_equivalent_layouts(typed_proof, body):
    assert forecast_performance_issues(body, performance_facts=typed_proof) == []


@pytest.mark.parametrize('body', [
    '| 分类 | 本期待履约收款与本期已履约收款是两种类别；本期待履约收款。 |',
    TABLE_CATEGORIES + ' 本期待履约收款 |',
    '| 个案 | 本期待履约收款 | 分类 | 本期待履约收款与本期已履约收款是两种类别 |',
])
def test_table_cell_category_cannot_hide_wrong_instance_in_same_or_other_cell(typed_proof, body):
    issues = forecast_performance_issues(body, performance_facts=typed_proof)
    assert len(issues) == 1 and issues[0]['asserted'] == 'pending'


@pytest.mark.parametrize('body', [
    '| 个案 | 本期待履约收款 OTHER-CONTRACT |',
    '| 政策 | 本期在待履约时不得将收款确认为收入 |',
])
def test_table_cell_termination_does_not_change_unknown_identity_or_policy(typed_proof, body):
    assert forecast_performance_issues(body, performance_facts=typed_proof) == []


@pytest.mark.parametrize('tail,category', [
    ('收款与本期已履约收款是两种类别 | 后续单元格', True),
    (r'收款与本期已履约收款是两种类别 \| 单元格内的文字 | 后续单元格', False),
])
def test_table_cell_termination_distinguishes_escaped_pipe_without_changing_tail(tail, category):
    subject = _performance_receipt_subject('| 分类 | 本期', tail)
    assert subject['category'] is category
    assert subject['after'] == tail[len('收款'):]
    assert subject['qualifier'] == ''


@pytest.mark.parametrize('short', [False, True])
def test_real_table_cell_category_definition_does_not_block_either_save(tmp_path, short):
    service, _, _, _, run, prepared = source_case(tmp_path, E18)
    before_run = deepcopy(service.analysis.get_run(run['id']))
    saved = save_note(service, prepared, TABLE_CATEGORIES, short)
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    (tmp_path / 'actual-table-category-save.json').write_text(json.dumps({
        'short': short, 'body': TABLE_CATEGORIES, 'draft_id': saved['id'], 'run_id': run['id'],
        'quality': saved['quality'], 'completion': saved['completion'], 'issues': issues,
        'source_proof': prepared['forecast_performance'], 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert issues == []
    assert saved['completion']['status'] == 'complete', saved['quality']
    assert TABLE_CATEGORIES in saved['body']
    assert service.analysis.get_run(run['id']) == before_run


@pytest.mark.parametrize('short', [False, True])
def test_real_ordinary_and_short_save_do_not_exempt_receipt_label_layout(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    proof = prepared['forecast_performance']
    spec = ({**prepared['save_template_spec'], 'qualitative_note': LABEL} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + LABEL})
    saved = service.save_explanation_draft(spec)
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    # Existing manager-body and full-output checks may report the same local
    # finding twice; diagnostic identity, rather than pipeline count, matters.
    assert len({(i['code'], i['text'], i['position']) for i in issues}) == 1
    stored = deepcopy(service.analysis.get_draft(saved['id']))
    old_run = deepcopy(service.analysis.get_run(run['id']))
    fixed = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': saved['id'],
        'qualitative_note': '旧应收回款与来源设为当期已履约的服务收款分别追踪；该设定不证明现实履约。'})
    assert fixed['completion']['status'] == 'complete', fixed['quality']
    legacy = {**deepcopy(stored), 'explanation_check': {
        **stored['explanation_check'], 'claim_semantics_version': 13}}
    old_legacy = deepcopy(legacy)
    assert any(i['code'] == CODE for i in saved_claim_semantic_issues(service.analysis, legacy))
    assert legacy == old_legacy
    assert service.analysis.get_draft(saved['id']) == stored
    assert service.analysis.get_run(run['id']) == old_run
    (tmp_path / 'actual-receipt-label-save.json').write_text(json.dumps({
        'short': short, 'label': LABEL, 'draft_id': saved['id'], 'run_id': run['id'],
        'output_hash': run['output_hash'], 'typed_proof': proof,
        'quality': saved['quality']['status'], 'completion': saved['completion']['status'],
        'issues': issues, 'provider_calls': 0,
        'revision_id': fixed['id'], 'revision_parent_id': fixed['parent_id'],
        'revision_completion': fixed['completion'], 'legacy_epoch': 13,
        'legacy_readonly_recheck_detected': True, 'old_draft_and_run_unchanged': True,
        'scope': 'two present same-source facts; optional-null combination belongs to separate source lane',
    }, ensure_ascii=False, indent=2))
    assert issues
    assert saved['completion']['status'] != 'complete'
