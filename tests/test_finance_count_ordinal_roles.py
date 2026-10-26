"""Live count caveats and inline enumerations never qualify financial numbers."""
from copy import deepcopy

import pytest

from foundry import finance_explanations as explanations
from foundry.finance_claim_semantics import check_claim_semantics
from test_finance_structure_count_closure import actual_basis as actual_basis, parse


COUNT_CAUTION = '12项模型核查全部通过不表示各检查差额一定为零，仍需专业复核。'
INLINE = '定性说明与范围：（1）本期客户收款清偿已识别债权，不产生新收入。（2）本结果为单主体管理预测，仍需专业复核。'


@pytest.mark.parametrize('subject', ['model_checks', '模型检查', '模型核查', '模型联动检查', '模型联动核查'])
@pytest.mark.parametrize('caveat', ['不表示各检查差额一定为零', '不等于所有差额均为零', '不代表各项核查的差异必然为零'])
def test_count_with_nonimplication_is_bound_to_actual_native_checks(actual_basis, subject, caveat):
    body = f'12项{subject}全部通过{caveat}，仍需专业复核。'
    spans, issues = parse(actual_basis, body)
    assert not issues
    assert [body[a:b] for a,b in spans] == ['12']
    assert explanations._body_numbers(body, ignored_spans=spans) == []


@pytest.mark.parametrize('invalid', ['wrong_count', 'missing', 'duplicate', 'wrong_requirement', 'failed_check'])
def test_caveat_does_not_waive_count_or_current_pass_proof(actual_basis, invalid):
    prepared = deepcopy(actual_basis.prepared)
    requirement_id = actual_basis.requirement['id']
    body = COUNT_CAUTION
    if invalid == 'wrong_count':
        body = body.replace('12', '11')
    elif invalid == 'missing':
        prepared['structure_counts'] = []
    elif invalid == 'duplicate':
        prepared['structure_counts'] *= 2
    elif invalid == 'wrong_requirement':
        requirement_id = 'different-requirement'
    else:
        next(p for p in prepared['structure_counts'] if p['kind'] == 'model_checks')['all_pass'] = False
    spans, issues = parse(actual_basis, body, prepared, requirement_id)
    assert not spans and issues


@pytest.mark.parametrize('tail', ['表示各检查差额一定为零', '不表示利润为零', '不表示各检查差额一定为零元', '不表示各检查差额一定为零就已批准过账'])
def test_count_caveat_accepts_no_unbounded_suffix(actual_basis, tail):
    spans, issues = parse(actual_basis, f'12项模型核查全部通过{tail}。')
    assert not spans and issues


@pytest.mark.parametrize('body', [
    '12项模型核查全部通过，所有模型检查的差额均为零。',
    COUNT_CAUTION + '但所有模型检查的差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但差额均为零。',
])
def test_count_caveat_never_hides_later_false_universal_zero(actual_basis, body):
    issues = check_claim_semantics(body, actual_basis.prepared['facts'], runs=[actual_basis.run])
    assert any(i['code'] == 'model_check_difference_claim_mismatch' for i in issues), issues


@pytest.mark.parametrize('contrast', ['但', '然而', '不过'])
def test_adjacent_omitted_check_subject_keeps_exact_zero_location(actual_basis, contrast):
    body = f'12项模型检查全部通过不等于所有差额均为零，{contrast}差额均为零。'
    issues = check_claim_semantics(body, actual_basis.prepared['facts'], runs=[actual_basis.run])
    assert len(issues) == 1
    assert issues[0]['code'] == 'model_check_difference_claim_mismatch'
    assert body[issues[0]['position']:].startswith('差额均为零')


@pytest.mark.parametrize('body', [
    '12项模型核查全部通过不表示各检查差额一定为零，但期初平衡差额为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但cash_sufficiency检查差额为零。',
    '12项模型核查全部通过不表示各检查差额一定为零。但差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零；但差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但预算差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但并非差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但差额均为零？',
    '假设12项模型核查全部通过不表示各检查差额一定为零，但差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但其他业务无异常，差额均为零。',
    '12项模型核查全部通过不表示各检查差额一定为零，但\n|检查|差额|\n|单项|零|',
])
def test_omitted_subject_does_not_cross_into_other_scopes_or_negations(actual_basis, body):
    assert not check_claim_semantics(body, actual_basis.prepared['facts'], runs=[actual_basis.run])


@pytest.mark.parametrize('body', [
    INLINE,
    '说明：(1)先复核范围；(2)再核对来源。',
    '（1）核对来源。\n（2）记录限制。\n（3）完成复核。',
    '（1）现金为931元；（2）应收为932元。',
])
def test_complete_prefixed_inline_sequence_exempts_only_marker_digits(body):
    assert [t['text'] for t in explanations._body_numbers(body)] == (['931','932'] if '931' in body else [])


@pytest.mark.parametrize('body,expected', [
    ('营收（1）/成本（2）', ['1','2']),
    ('金额：（1）万元；（2）万元。', ['1','2']),
    ('（1万元）；（2万元）', ['1','2']),
    ('（2025）收入；（2026）成本。', ['2025','2026']),
    ('（1）孤立说明。', ['1']),
    ('（2）第二条；（3）第三条。', ['2','3']),
    ('（1）第一条；（3）跳号。', ['1','3']),
    ('（1）第一条；（1）重复。', ['1','1']),
    ('（1）第一条。\n\n（2）另起段落。', ['1','2']),
    ('（1）为检查差额；（2）为另一差额。', ['1','2']),
    ('（1）元；（2）元。', ['1','2']),
    ('（1）%增长；（2）%下降。', ['1','2']),
    ('（1）\n（2）', ['1','2']),
    ('（1)第一条；(2）第二条。', ['1','2']),
    ('差额：（1）高于预算；（2）低于预算。', ['1','2']),
    ('（1）第一条,（2）逗号并不能确定下一条。', ['1','2']),
])
def test_parenthesized_amounts_years_isolated_and_broken_markers_are_not_ordinals(body, expected):
    assert [t['text'] for t in explanations._body_numbers(body)] == expected


def test_marker_roles_preserve_amounts_and_check_differences():
    body = '说明：（1）检查差额为0；（2）现金为931元，变动为25%。'
    assert [t['text'] for t in explanations._body_numbers(body)] == ['0','931','25%']


@pytest.mark.parametrize('unit', ['亿美元', '百万美元', 'EUR', '万元', '人民币', 'USD', '%', '倍', '件', '万元币', '法郎', '公里'])
@pytest.mark.parametrize('tail', ['。', '属于收入。'])
def test_consecutive_currency_or_measure_amounts_are_never_enumeration(unit, tail):
    body = f'说明：（1）{unit}{tail}（2）{unit}{tail}'
    assert [t['text'] for t in explanations._body_numbers(body)] == ['1', '2']


@pytest.mark.parametrize('short', [False, True])
def test_real_save_accepts_bound_count_and_inline_markers_but_retains_bare_zero(actual_basis, short):
    basis = actual_basis
    note = COUNT_CAUTION + '\n\n' + INLINE
    spec = {'use_prepared_template':True, 'run_ids':[basis.run['id']],
            'requirements_id':basis.requirement['id'], 'qualitative_note':note}
    if not short:
        spec = {**basis.prepared['draft_template'], 'body':basis.prepared['draft_template']['body']+'\n\n'+note}
    saved = basis.runtime.save_explanation_draft(spec)
    assert saved['quality']['status'] == 'pass', saved['quality']['issues']
    assert saved['completion']['status'] == 'complete'
    assert basis.runtime.validate_explanation({'draft_id':saved['id']})['status'] == 'pass'
    bad = dict(spec)
    key = 'qualitative_note' if short else 'body'
    bad[key] += '边界来源声明为0。'
    rejected = basis.runtime.save_explanation_draft(bad)
    assert any(i['code'] == 'uncited_number' and i['text'] == '0' for i in rejected['quality']['issues'])
    assert rejected['completion']['status'] != 'complete'
