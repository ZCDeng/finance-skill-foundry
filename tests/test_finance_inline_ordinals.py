"""Section enumeration roles never confer financial evidence eligibility."""
import hashlib
import json

import pytest

from foundry import finance_explanations as explanations
from foundry.finance_driver_templates import BOUNDARY_INPUTS, OUTPUT_SEMANTICS, TEMPLATE_ID
from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from test_finance_ar_wording import render_saved
from test_finance_runtime_ordering import register


ACTUAL_NOTE = (
    '（1）范围：这是合成单主体管理预测（Supplement Fixture Co；management/forecast；2026-10 单月，'
    '流量为期间数、存量为期末数；CNY/元），不是法定报表、实际到预测桥接、历史事实或已签署专业意见；'
    '间接法现金流桥为管理口径，不构成法定现金流量表。'
    '（2）旧应收与本期履约收款的区别：期初应收 AR-202609-001（合同 S-OLD-01，2026-09 已履约已确认收入）'
    '本期收到的 50 是对该已识别债权的部分清偿，仍有 30 未结清，不产生新收入或新履约；'
    '本期履约服务（合同 S-CUR-01）收款 130 是对本期已履约服务的收款，两者在 transaction_allocation 中分别追踪、不混同。'
    '（3）八项模型边界均有独立来源行且为 0、经确认；available_cash 仅为现金总额扣除受限 12，'
    '不代表完整偿债能力或法定现金等价物认定。结果仍需专业复核，不构成审定或过账授权。'
)
FINANCIAL_TOKENS = ['50', '30', '130', '0', '12']


def test_exact_historical_note_exempts_only_three_section_markers():
    assert [token['text'] for token in explanations._body_numbers(ACTUAL_NOTE)] == FINANCIAL_TOKENS
    assert [ACTUAL_NOTE[a:b] for a, b in explanations._inline_ordinal_spans(ACTUAL_NOTE)] == ['1', '2', '3']


@pytest.mark.parametrize('heading', ['适用范围', '资料的区别', '处理方法', '证据来源', '执行顺序', 'Forecast scope'])
@pytest.mark.parametrize('clause', ['两条限制都需核对来源。', '若干组条件皆已确认。', '各类假设均须专业复核。',
                                    '三项资料都为独立记录。', '每个事项皆有独立依据。'])
def test_section_heading_and_quantified_clause_roles_are_not_financial_phrase_whitelists(heading, clause):
    body = f'（1）{heading}：这是待复核的说明。（2）{clause}'
    assert explanations._body_numbers(body) == []


@pytest.mark.parametrize('body', [
    '（1）范围：保留现金931元。（2）资料比较：差额为0，变化25%。（3）12项边界均需复核。',
    '(1)Scope: Review cash 931 yuan.(2)Comparison: Check difference 0 and 25%.(3)12项边界均需复核。',
])
def test_only_markers_are_exempt_and_all_internal_numeric_claims_remain(body):
    # The ASCII period is not a financial sentence separator in the original grammar.
    if 'Scope' in body:
        body = body.replace('yuan.', 'yuan;').replace('25%.', '25%;')
    assert [t['text'] for t in explanations._body_numbers(body)] == ['931', '0', '25%', '12']


@pytest.mark.parametrize('tail', [
    'USD。', 'EUR属于收入。', 'RUB：待核对。', '蜉蝣币属于收入。', '百万瑞士法郎。', '人民币。',
    '万元。', '亿美元。', '百万美元。', '%增长。', '倍。', '件。', '公里。',
    '为检查差额。', '= 0。', '+ 5。', '- 5。', '3 + 4 = 7。', '2026年期末。',
    '12元本期已收。', '现金12元。',
])
def test_earlier_headings_never_qualify_a_later_amount_unit_formula_or_year(tail):
    body = f'（1）范围：这是管理预测。（2）资料比较：需要复核。（3）{tail}'
    assert explanations._inline_ordinal_spans(body) == []


@pytest.mark.parametrize('unit', ['USD', 'EUR', 'XAU', '人民币', '万元', '亿美元', '百万美元', '蜉蝣币', '%', '倍', '件'])
def test_colon_alone_does_not_turn_a_currency_or_unit_into_a_prose_heading(unit):
    body = f'（1）{unit}：本期收入。（2）{unit}：本期成本。'
    assert explanations._inline_ordinal_spans(body) == []


@pytest.mark.parametrize('body', [
    '（1）范围：这是管理预测。',
    '（2）范围：这是管理预测。（3）限制：需要复核。',
    '（1）范围：这是管理预测。（3）限制：需要复核。',
    '（1）范围：这是管理预测。（1）限制：需要复核。',
    '（1）范围：这是管理预测。\n\n（2）限制：需要复核。',
    '（1)范围：这是管理预测。(2）限制：需要复核。',
    '（1）范围：这是管理预测，(2)限制：需要复核。',
    '金额：（1）范围：这是管理预测。（2）限制：需要复核。',
    '收入（1）范围：待核对；成本（2）限制：待核对。',
    '（1）八项边界均有来源。（2）两项限制均需复核。',
    '（1）各项边界均有来源。（2）范围：这是管理预测。',
    '（2025）范围：这是管理预测。（2026）限制：需要复核。',
    '（-1）范围：这是管理预测。（-2）限制：需要复核。',
    '（1%）范围：这是管理预测。（2%）限制：需要复核。',
])
def test_section_roles_keep_existing_sequence_and_directional_heading_requirements(body):
    assert explanations._inline_ordinal_spans(body) == []


@pytest.mark.parametrize('separator', ['\n', '\n  ', '\n\t', '\r\n', '\n\n'])
def test_new_physical_line_can_start_a_headed_list_without_losing_other_numbers(separator):
    body = '上文金额为931元。' + separator + ACTUAL_NOTE
    assert [body[a:b] for a, b in explanations._inline_ordinal_spans(body)] == ['1', '2', '3']
    assert [t['text'] for t in explanations._body_numbers(body)] == ['931', *FINANCIAL_TOKENS]


@pytest.mark.parametrize('body', [
    '上文已核对。' + ACTUAL_NOTE,
    '上文已核对。\n收入' + ACTUAL_NOTE,
    '上文已核对。\n（1）USD。（2）蜉蝣币。',
    '上文已核对。\n（1）核对来源。（2）记录限制。',
    '上文已核对。\n（1）范围：需要复核。（2）EUR。',
    '上文已核对。\n（1）范围：需要复核。（2）3 + 4 = 7。',
    '上文已核对。\n（1）范围：需要复核。（3）两项限制均需复核。',
    '上文已核对。\n（1)范围：需要复核。(2）限制：需要复核。',
    '上文已核对。\n（1）范围：需要复核，(2)限制：需要复核。',
    '金额（1）元。\n（1）范围：需要复核。（2）限制：需要复核。',
    '上文已核对。\n（2025）范围：需要复核。（2026）限制：需要复核。',
    '上文已核对。\n（-1）范围：需要复核。（-2）限制：需要复核。',
    '上文已核对。\n（1%）范围：需要复核。（2%）限制：需要复核。',
])
def test_line_start_does_not_restart_invalid_sequences_or_qualify_currency_and_data(body):
    assert explanations._inline_ordinal_spans(body) == []


@pytest.fixture
def actual_service(tmp_path):
    """New real task with independently created, explicitly bound statement inputs."""
    manager = FinanceStore(TaskStore(tmp_path / 'var').create(title='Section ordinal evidence'), actor='manager')
    scope = {'organization': 'Supplement Fixture Co', 'currency': 'CNY', 'unit': '元',
             'scenario': 'management-forecast'}
    values = dict(opening_cash=150, opening_receivables=80, opening_ppe=300, opening_payables=70,
                  opening_debt=160, opening_equity=300, revenue=210, customer_receipts=180,
                  operating_expense=95, supplier_payments=75, depreciation=15, capex=60,
                  debt_drawdowns=25, debt_principal_repayments=20, dividends_paid=8, closing_restricted_cash=12)
    values.update(dict.fromkeys(BOUNDARY_INPUTS, 0))
    rows = [{**scope, 'input_name': name, 'amount': str(value),
             'period': '2026-09' if name.startswith('opening_') else '2026-10'} for name, value in values.items()]
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(rows))
    dataset = manager.analysis.add_dataset(source, name='Independent ordinal inputs')
    context = manager.save_context({'bindings': {'inputs': dataset['id']}, 'scopes': {'inputs': scope},
        'reporting_profile': {'schema_version': 1, 'basis': 'management', 'basis_version': 'management-v1',
            'fiscal_year_start': '2026-01-01', 'early_adoption': False, 'purpose': 'forecast',
            'effective_period': {'start': '2026-01', 'end': '2026-12'}, 'functional_currency': 'CNY',
            'presentation_currency': 'CNY', 'presentation_unit': '元', 'entity_scope': scope['organization']}})
    manager.finance_profile_confirm({'context_id': context['id'], 'confirmed_fields': sorted(BASE_FIELDS | STANDARD_FIELDS)})
    inputs = {'template_id': TEMPLATE_ID, 'period': '2026-10', 'scope': scope,
              'source_bindings': {row['input_name']: {'alias': 'inputs', 'column': 'amount',
                    'selector': {'input_name': row['input_name']}, 'aggregation': 'single', 'scope': scope,
                    'period': row['period'], 'currency': 'CNY', 'unit': '元'} for row in rows}}
    scenario = manager.save_scenario({'context_id': context['id'], 'kind': 'driver_model',
                                      'label': 'Ordinal test native statements', 'inputs': inputs})
    manager.finance_profile_confirm({'context_id': context['id'], 'scenario_id': scenario['id'],
                                      'confirmed_model_boundaries': list(BOUNDARY_INPUTS)})
    runtime = FinanceStore(manager.task, snapshot_ids=[dataset['id']], session_id='ordinal-runtime')
    register(runtime, context, scenario, items=[
        {'id': metric, 'metric': metric, 'dimensions': {'metric_key': metric,
          'template_id': TEMPLATE_ID, 'scenario_id': scenario['id']}, 'requires_drilldown': False}
        for metric in OUTPUT_SEMANTICS])
    run = runtime.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    prepared = runtime.prepare_explanation({'run_ids': [run['id']]})
    assert len(prepared['facts']) == 13
    return runtime, prepared


@pytest.mark.parametrize('short,separator', [(False, '\n\n'), (False, '\n'), (True, '\n\n')],
                         ids=['ordinary', 'ordinary-single-newline', 'short'])
def test_real_save_keeps_five_financial_issues_and_preserves_parent_on_repair(actual_service, tmp_path, short, separator):
    runtime, prepared = actual_service
    spec = ({**prepared['save_template_spec'], 'qualitative_note': ACTUAL_NOTE} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + separator + ACTUAL_NOTE})
    saved = runtime.save_explanation_draft(spec)
    path = runtime.analysis._object_path('drafts', saved['id'])
    before = path.read_bytes()
    public = render_saved(saved)
    evidence = {'task_id': runtime.task.id, 'draft_id': saved['id'], 'short': short, 'separator': separator,
                'spec': spec, 'issues': saved['quality']['issues'], 'completion': saved['completion'],
                'public_issues': public['quality']['issues'], 'parent_sha256': hashlib.sha256(before).hexdigest()}
    (tmp_path / 'actual-save-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    assert ACTUAL_NOTE in saved['body']
    assert saved['quality']['status'] == 'needs_attention'
    assert saved['completion']['status'] == 'repair_available'
    assert public['quality']['issues'] == saved['quality']['issues']
    assert public['completion'] == saved['completion']
    assert [i['text'] for i in saved['quality']['issues']] == FINANCIAL_TOKENS
    assert all(i['code'] == 'uncited_number' for i in saved['quality']['issues'])
    repaired_note = ('（1）范围：这是管理预测，仍需专业复核。'
                     '（2）处理说明：旧应收回款清偿对应已识别债权，部分清偿保留余额。'
                     '（3）各项边界均有独立来源，仍需专业复核。')
    repaired_spec = ({**prepared['save_template_spec'], 'qualitative_note': repaired_note} if short else
                     {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + separator + repaired_note})
    repaired = runtime.save_explanation_draft({**repaired_spec, 'parent_id': saved['id']})
    assert repaired['quality']['status'] == 'pass', repaired['quality']['issues']
    assert repaired['completion']['status'] == 'complete'
    assert repaired['parent_id'] == saved['id']
    assert path.read_bytes() == before
    (tmp_path / 'actual-repair-evidence.json').write_text(json.dumps({
        'draft_id': repaired['id'], 'parent_id': repaired['parent_id'], 'issues': repaired['quality']['issues'],
        'completion': repaired['completion'], 'parent_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    }, ensure_ascii=False, indent=2))
