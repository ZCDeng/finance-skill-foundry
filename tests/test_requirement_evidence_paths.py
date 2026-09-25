"""Phase 1 requirement evidence paths (decisions of 2026-09-24).

Every requirement is an amount unless it is a known non-amount (a ratio, an item asking only for ratio
scenarios, a count or a physical quantity). Script values never answer an amount. An amount is answered by
a cited cell backed by a passing, server-evaluated direct/sum/diff recipe on the requirement's own snapshots
with a unit scale; by finance-engine closure (revenue/profit/cost/expense items without scenarios); by the
finance engine's own run_metric account_total of an account item, or its run_metric result set; and, outside
revenue/profit/cost/expense, by the finance engine's own output of that amount.
Every tightening has its opposite here, and every piece of guidance is followed literally once.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundry.analysis import AnalysisStore, _new
from foundry.errors import FoundryError
from foundry.finance_completion import record_completion
from foundry.finance_requirements import (
    _unanswered_message,
    augment_quality,
    check_requirements,
    save_requirements,
)
from foundry.finance_service import FinanceStore
from foundry.financial_evidence import evaluate_evidence_recipes, recipe_evidence_class
from foundry.task import TaskStore
from test_finance_requirements import (
    _claim,
    _finance_service_from_rows,
    _pq_claims,
    _pq_run,
    _recipe,
    _regional_rows,
    _claims_for_columns,
    _require_pq,
    _run,
    _script_run,
    _workbook,
    spec,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def analysis(tmp_path):
    return AnalysisStore(TaskStore(tmp_path / 'var').create(title='来源复算'))


REVENUE_ROWS = [
    {'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026-08', 'scenario': 'budget_2026_08',
     'value': '44163.6526', 'unit': '万元', 'currency': 'CNY'},
    {'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026-08', 'scenario': 'actual_2026_08',
     'value': '41469.6250', 'unit': '万元', 'currency': 'CNY'},
]


@pytest.fixture
def monthly(analysis, tmp_path):
    """Huachen revenue_2026_08: budget 01!I12, actual 04!B5 in 元 (× 0.0001 → 万元)."""
    budget = _workbook(analysis, tmp_path, 'budget', {
        '01·年度预算总表': {'A12': '营业收入', 'I3': '8月预算', 'I12': 44163.6526},
    })
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'B5': 414696250, 'D5': 82939.25, 'F5': 2}})
    outside = _workbook(analysis, tmp_path, 'outside', {'04·合并利润表': {'B5': 414696250}})
    requirement = save_requirements(analysis, spec(
        question='8 月营业收入实际与预算',
        scope={'ledger': '华宸物业2026年度预算工作簿 + 月结套表（已登记文件快照）', 'currency': 'CNY', 'unit': '万元'},
        bindings={'budget': budget['id'], 'close': close['id']},
        items=[{'id': 'revenue_2026_08', 'metric': 'revenue', 'organizations': ['集团合并'], 'periods': ['2026-08'],
                'scenarios': ['actual_2026_08', 'budget_2026_08'], 'requires_drilldown': True}],
    ))
    datasets = {'budget': budget, 'close': close}
    run = _script_run(analysis, datasets, REVENUE_ROWS, suffix='monthly')
    claims = [_claim(run, row=0, column='value', value='44163.6526'), _claim(run, row=1, column='value', value='41469.6250')]
    good = [
        _recipe(budget, '01·年度预算总表', 'I12', run, 0, recipe_id='budget'),
        _recipe(close, '04·合并利润表', 'B5', run, 1, scale='0.0001', recipe_id='actual'),
    ]
    return SimpleNamespace(budget=budget, close=close, outside=outside, requirement=requirement, datasets=datasets,
                           run=run, claims=claims, good=good)


def _check(analysis, case, *, recipes=None, claims=None, run=None, **extra):
    run = run or case.run
    return check_requirements(analysis, {'requirements_id': case.requirement['id'], 'run_ids': [run['id']],
                                         'claims': case.claims if claims is None else claims,
                                         'evidence_recipes': recipes or [], **extra})


def _item(result, item_id=None):
    return result['items'][0] if item_id is None else next(item for item in result['items'] if item['id'] == item_id)


def _actual_location(item):
    return next(location for location in item['locations'] if location['row'] == 1)


# --- what answers ----------------------------------------------------------------------------------


def test_direct_recipes_on_cited_cells_answer_and_stay_unreviewed(analysis, monthly):
    result = _check(analysis, monthly, recipes=monthly.good)
    item = _item(result)

    assert item['status'] == 'answered'
    assert result['coverage']['status'] == 'pass'
    assert [location['evidence']['evidence_basis'] for location in item['locations']] == ['source_value', 'source_value']
    assert all(location['evidence']['mapping_review'] == 'unreviewed' for location in item['locations'])
    assert _actual_location(item)['evidence']['recipe_ids'] == ['actual']
    # A counted source recipe traces the cell to the archived snapshot.
    assert item['provenance_status'] == 'verified'
    assert 'fixups' not in item


def test_empty_sibling_column_does_not_void_a_recipe_backed_cell(analysis, monthly):
    rows = [{**row, 'amount': None} for row in REVENUE_ROWS]
    run = _script_run(analysis, monthly.datasets, rows, suffix='sibling')
    claims = [_claim(run, row=0, column='value', value='44163.6526'), _claim(run, row=1, column='value', value='41469.6250')]
    recipes = [_recipe(monthly.budget, '01·年度预算总表', 'I12', run, 0, recipe_id='budget'),
               _recipe(monthly.close, '04·合并利润表', 'B5', run, 1, scale='0.0001', recipe_id='actual')]

    without = _item(_check(analysis, monthly, claims=claims, run=run))
    backed = _item(_check(analysis, monthly, recipes=recipes, claims=claims, run=run))

    assert without['locations'][0]['evidence']['group_status'] == 'missing_data'
    assert without['status'] == 'pending'
    assert backed['status'] == 'answered'


def test_python_bridge_that_closes_does_not_answer_revenue_but_the_finance_engine_does(analysis):
    save_requirements(analysis, spec(items=[{'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False}]))
    bridge = {
        'method': 'revenue_minus_cost_minus_expense',
        'columns': ['metric', 'actual', 'baseline', 'contribution'],
        'rows': [
            {'metric': 'revenue', 'actual': '1999', 'baseline': '1000', 'contribution': '999'},
            {'metric': 'cost', 'actual': '1', 'baseline': '2', 'contribution': '-1'},
            {'metric': 'expense', 'actual': '1', 'baseline': '2', 'contribution': '-1'},
            {'metric': 'profit', 'actual': '1997', 'baseline': '1000', 'contribution': '997'},
        ],
    }
    fabricated = _run(analysis, id_suffix='python-bridge', engine='python', result=bridge)
    sql = _run(analysis, id_suffix='sql-bridge', engine=None, result=bridge)
    engine = _run(analysis, id_suffix='engine-bridge', result=bridge)

    for run in (fabricated, sql):
        result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run, row=0, value='999')]})
        item = _item(result)
        assert item['status'] != 'answered'
        assert item['locations'][0]['evidence']['closure_status'] == 'passed'
        assert item['locations'][0]['evidence']['evidence_basis'] == 'internal_only'
        assert item['locations'][0]['evidence']['not_counted_reason'] == 'script_closure_not_counted'
        assert '闭合由脚本自行算出，只作展示，不计为引擎闭合' in _unanswered_message(item)

    answered = check_requirements(analysis, {'run_ids': [engine['id']], 'claims': [_claim(engine, row=0, value='999')]})
    assert _item(answered)['status'] == 'answered'
    assert _item(answered)['locations'][0]['evidence']['evidence_basis'] == 'engine_closed'


def test_python_price_quantity_bridge_does_not_answer_but_the_finance_engine_does(analysis):
    requirement = _require_pq(analysis)
    engine = _pq_run(analysis)
    record = _new(analysis.task, engine='python', execution_status='succeeded', output_hash='pq-python',
                  bindings=engine['bindings'], finance_scope=engine['finance_scope'], result=engine['result'])
    script = analysis._write(analysis._object_path('runs', record['id']), record)

    fabricated = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [script['id']],
                                               'claims': _pq_claims(script)})
    answered = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [engine['id']],
                                             'claims': _pq_claims(engine)})

    assert _item(fabricated)['status'] != 'answered'
    assert _item(answered)['status'] == 'answered'


# --- what must not answer --------------------------------------------------------------------------


def test_recipe_on_an_uncited_cell_or_run_outside_the_draft_does_not_answer(analysis, monthly):
    only_budget = _check(analysis, monthly, recipes=monthly.good, claims=monthly.claims[:1])
    item = _item(only_budget)
    assert item['status'] == 'pending'
    assert item['missing_grains'] == [{'organization': '集团合并', 'period': '2026-08', 'scenario': 'actual_2026_08'}]

    outside_draft = check_requirements(analysis, {'requirements_id': monthly.requirement['id'], 'run_ids': [],
                                                  'claims': monthly.claims, 'evidence_recipes': monthly.good})
    assert _item(outside_draft)['status'] == 'pending'
    assert _item(outside_draft)['locations'] == []


def test_ratio_recipe_never_proves_an_amount(analysis, monthly):
    # 04!D5 ÷ 04!F5 = 82939.25 ÷ 2 recomputes the cited 41469.6250 exactly, from bound snapshots.
    ratio = {'id': 'ratio', 'kind': 'ratio', 'claim': {'run_id': monthly.run['id'], 'row': 1, 'column': 'value'},
             'left': {'dataset_id': monthly.close['id'], 'source_hash': monthly.close['source_hash'],
                      'sheet': '04·合并利润表', 'range': 'D5'},
             'right': {'dataset_id': monthly.close['id'], 'source_hash': monthly.close['source_hash'],
                       'sheet': '04·合并利润表', 'range': 'F5'}}
    assert evaluate_evidence_recipes(analysis, [ratio])['results'][0]['status'] == 'pass'

    item = _item(_check(analysis, monthly, recipes=[monthly.good[0], ratio]))
    location = _actual_location(item)

    assert item['status'] == 'pending'
    assert location['status'] == 'not_applicable'
    assert location['evidence']['not_counted_reason'] == 'ratio_recipe_cannot_prove_amount'
    assert 'ratio 规则不能证明金额' in _unanswered_message(item)


def test_hand_written_scale_is_unbound_while_a_unit_power_counts(analysis, monthly):
    unbound = _recipe(monthly.close, '04·合并利润表', 'D5', monthly.run, 1, scale='0.5', recipe_id='half')
    report = evaluate_evidence_recipes(analysis, [unbound, monthly.good[1]])
    assert [(result['status'], result['evidence_class']) for result in report['results']] == [
        ('pass', 'coefficient_unbound'), ('pass', 'source_value')]

    result = _check(analysis, monthly, recipes=[monthly.good[0], unbound])
    item = _item(result)
    assert item['status'] == 'pending'
    assert _actual_location(item)['evidence']['not_counted_reason'] == 'recipe_coefficient_unbound'
    assert _item(_check(analysis, monthly, recipes=monthly.good))['status'] == 'answered'

    from decimal import Decimal

    base = {'kind': 'direct', 'factor_recipe_id': None}
    for scale, expected in (('1', 'source_value'), ('1000', 'source_value'), ('0.0001', 'source_value'),
                            ('1E+8', 'source_value'), ('0.00000001', 'source_value'), ('100', 'coefficient_unbound'),
                            ('0.6524', 'coefficient_unbound'), ('-1', 'coefficient_unbound'), ('100000', 'coefficient_unbound')):
        assert recipe_evidence_class({**base, 'scale': Decimal(scale)}, 'pass') == expected, scale
    assert recipe_evidence_class({'kind': 'sum', 'scale': Decimal('1')}, 'pass') == 'source_calculation'
    assert recipe_evidence_class({'kind': 'sum', 'scale': Decimal('1')}, 'mismatch') is None


def test_recipe_sources_outside_the_requirement_bindings_do_not_answer(analysis, monthly):
    outside = _recipe(monthly.outside, '04·合并利润表', 'B5', monthly.run, 1, scale='0.0001', recipe_id='outside')
    assert evaluate_evidence_recipes(analysis, [outside])['results'][0]['status'] == 'pass'

    item = _item(_check(analysis, monthly, recipes=[monthly.good[0], outside]))

    assert item['status'] == 'pending'
    assert _actual_location(item)['evidence']['not_counted_reason'] == 'recipe_source_outside_bindings'
    assert '复算规则的来源不在本要求绑定的资料快照内' in _unanswered_message(item)


def test_rounded_run_value_still_fails_exactly_and_asks_for_full_precision(analysis, monthly):
    rows = [REVENUE_ROWS[0], {**REVENUE_ROWS[1], 'value': '41469.63'}]
    run = _script_run(analysis, monthly.datasets, rows, suffix='rounded')
    claims = [_claim(run, row=0, column='value', value='44163.6526'), _claim(run, row=1, column='value', value='41469.63')]
    recipes = [_recipe(monthly.budget, '01·年度预算总表', 'I12', run, 0, recipe_id='budget'),
               _recipe(monthly.close, '04·合并利润表', 'B5', run, 1, scale='0.0001', recipe_id='actual')]

    report = evaluate_evidence_recipes(analysis, recipes)
    issue = report['issues'][0]
    item = _item(_check(analysis, monthly, recipes=recipes, claims=claims, run=run))

    assert report['results'][1]['status'] == 'mismatch'
    assert report['results'][1]['precision_hint'] == 'full_precision_required'
    assert issue['precision_hint'] == 'full_precision_required'
    assert (issue['actual'], issue['expected']) == ('41469.6250', '41469.63')
    assert '保存完整精度' in issue['message']
    assert item['status'] == 'pending'
    assert _actual_location(item)['evidence']['not_counted_reason'] == 'recipe_failed_precision'
    # Not a rounding difference: no hint.
    unrelated = evaluate_evidence_recipes(analysis, [_recipe(monthly.close, '04·合并利润表', 'D5', run, 1)])
    assert 'precision_hint' not in unrelated['issues'][0]


def test_caller_supplied_or_stored_evidence_report_is_never_evidence(analysis, monthly):
    fabricated = {'summary': {'status': 'pass'}, 'issues': [], 'results': [
        {'recipe_id': recipe['id'], 'status': 'pass', 'evidence_class': 'source_value', 'kind': 'direct',
         'claim': recipe['claim'], 'source_refs': [{key: recipe[key] for key in ('dataset_id', 'source_hash', 'sheet', 'range')}]}
        for recipe in monthly.good]}
    spec_with_report = {'requirements_id': monthly.requirement['id'], 'run_ids': [monthly.run['id']],
                        'claims': monthly.claims, 'evidence_report': fabricated}

    assert _item(check_requirements(analysis, spec_with_report))['status'] == 'pending'
    quality = augment_quality(analysis, spec_with_report, {'status': 'pass', 'issues': []})
    assert _item(quality['requirements'])['status'] == 'pending'

    service = FinanceStore(analysis.task)
    body = {'body': '收入说明。', 'run_ids': [monthly.run['id']], 'claims': monthly.claims}
    assert _item(service.validate_explanation({**body, 'evidence_report': fabricated})['requirements'])['status'] == 'pending'

    stored = _new(analysis.task, title='旧稿', body='收入说明。', run_ids=[monthly.run['id']], fact_ids=[],
                  claims=monthly.claims, evidence_recipes=[], evidence_report=fabricated,
                  requirements_id=monthly.requirement['id'])
    draft = analysis._write(analysis._object_path('drafts', stored['id']), stored)
    assert _item(service.validate_explanation({'draft_id': draft['id']})['requirements'])['status'] == 'pending'

    # The same recipes, evaluated by the server in this call, do answer.
    checked = service.validate_explanation({**body, 'evidence_recipes': monthly.good})
    assert _item(checked['requirements'])['status'] == 'answered'


def test_estimate_counts_only_on_declared_grains_and_never_as_answered(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path)
    result = check_requirements(analysis, case.spec)
    item = _item(result)
    east_budget = next(location for location in item['locations'] if location['row'] == 3)

    assert item['status'] == 'estimated'
    assert result['coverage']['status'] == 'needs_attention'
    assert result['original_requirements_completed'] is False
    assert east_budget['status'] == 'estimated'
    assert east_budget['evidence']['evidence_basis'] == 'estimate'
    assert item['estimated_grains'] == [{'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8',
                                         'accepted': False, 'locations': [{'run_id': case.run['id'], 'row': 3, 'column': 'value'}]}]
    assert item['provenance_status'] == 'inputs_verified'
    assert result['provenance']['status'] == 'needs_attention'

    quality = augment_quality(analysis, case.spec, {'status': 'pass', 'issues': []})
    codes = [issue['code'] for issue in quality['issues']]
    estimate = next(issue for issue in quality['issues'] if issue['code'] == 'requirement_estimated')
    assert 'requirement_unanswered' not in codes
    assert estimate['business_key'] == {'metric': 'revenue', 'organization': '华东区域',
                                        'period': '2026-01:2026-08', 'scenario': 'budget_1_8'}
    assert estimate['location']['reference']['range'] == 'C5'
    assert (estimate['location']['factor']['left']['range'], estimate['location']['factor']['right']['range']) == ('B12:C12', 'N12')
    assert '05·区域预算分解!C5 × (01·年度预算总表!B12:C12 ÷ 01·年度预算总表!N12)' in estimate['message']

    completion = record_completion(analysis, {'id': 'e' * 32, 'content_hash': 'estimate', 'run_ids': [case.run['id']]}, quality)
    assert completion['status'] == 'awaiting_manager'
    assert completion['stop_reason'] == 'estimate_requires_acceptance'
    assert completion['repair_allowed'] is False
    assert completion['response_status'] == 'ended_with_limitations'
    assert completion['original_requirements_completed'] is False


def test_estimate_cited_for_an_undeclared_grain_is_not_counted(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path, declare=False)
    item = _item(check_requirements(analysis, case.spec))
    east_budget = next(location for location in item['locations'] if location['row'] == 3)
    fixup = next(fixup for fixup in item['fixups'] if fixup['code'] == 'estimate_cited_for_source_grain')

    assert item['status'] == 'pending'
    assert east_budget['status'] == 'pending'
    assert east_budget['evidence']['not_counted_reason'] == 'estimate_cited_for_source_grain'
    assert fixup['grains'][0]['organization'] == '华东区域'
    assert 'awaiting_manager' not in item


def test_only_a_manager_acceptance_of_the_same_recipe_turns_coverage_to_accepted_estimates(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path)
    location = next(location for location in _item(check_requirements(analysis, case.spec))['locations'] if location['row'] == 3)
    grain = {'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8'}
    base = {'requirements_id': case.requirement['id'], 'requirement_item_id': 'revenue_1_8', 'grain': grain,
            'recipe_hash': location['evidence']['recipe_hash'],
            'factor_recipe_hash': location['evidence']['factor']['recipe_hash']}

    for acceptance in ({**base, 'accepted_by': 'assistant'}, {**base, 'recipe_hash': '0' * 64, 'accepted_by': 'manager'}):
        record = _new(analysis.task, **acceptance)
        analysis._write(analysis._object_path('estimate_acceptances', record['id']), record)
        assert check_requirements(analysis, case.spec)['coverage']['status'] == 'needs_attention'

    record = _new(analysis.task, **base, accepted_by='manager')
    analysis._write(analysis._object_path('estimate_acceptances', record['id']), record)
    accepted = check_requirements(analysis, case.spec)

    assert accepted['coverage']['status'] == 'pass_with_accepted_estimates'
    assert accepted['provenance']['status'] == 'pass_with_accepted_estimates'
    assert _item(accepted)['status'] == 'estimated'
    assert _item(accepted)['estimated_grains'][0]['accepted'] is True
    assert accepted['original_requirements_completed'] is False


def test_factor_that_cannot_be_reproduced_stays_pending_and_goes_to_the_manager(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path, declaration={
        'organizations': ['华东区域'], 'scenarios': ['budget_1_8'], 'basis': 'estimate',
        'method': '（Σ营业利润预算 − Σ其他收益预算）÷ 区域营业利润预算合计',
        'factor_reproducible': False, 'reason': '系数须先相减再相除，现有规则写不出'})
    # Even the passing factor recipe cannot turn a grain declared non-reproducible into an estimate.
    result = check_requirements(analysis, case.spec)
    item = _item(result)
    fixup = next(fixup for fixup in item['fixups'] if fixup['code'] == 'estimate_factor_not_reproducible')

    assert item['status'] == 'pending'
    assert item['declared_grains'] == [{'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8',
                                        'state': 'estimate_factor_not_reproducible', 'reason': '系数须先相减再相除，现有规则写不出'}]
    assert fixup['needs_manager'] is True
    assert item['awaiting_manager'] == ['estimate_factor_not_reproducible']
    assert '不得换用其他系数凑数' in _unanswered_message(item)

    quality = augment_quality(analysis, case.spec, {'status': 'pass', 'issues': []})
    completion = record_completion(analysis, {'id': 'f' * 32, 'content_hash': 'factor', 'run_ids': [case.run['id']]}, quality)
    assert completion['status'] == 'awaiting_manager'
    assert completion['stop_reason'] == 'manager_decision_required'
    assert completion['repair_allowed'] is False


def test_declared_unavailable_grain_waits_for_the_manager_and_is_not_missing_data(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path, declaration={
        'organizations': ['华东区域'], 'scenarios': ['budget_1_8'], 'basis': 'unavailable', 'reason': '源表无区域1-8月预算'},
        cite_estimate=False)
    item = _item(check_requirements(analysis, case.spec))

    assert item['status'] == 'pending'
    assert item['declared_grains'][0]['state'] == 'unavailable_declared'
    assert item['awaiting_manager'] == ['unavailable_declared']


# --- requirement authoring ----------------------------------------------------------------------------


def test_hierarchy_dimensions_are_refused_with_items_that_can_be_resubmitted(analysis):
    items = [{'id': 'revenue_1_8', 'metric': 'revenue', 'dimensions': {'drilldown': '城市公司', 'product': '物业费'},
              'organizations': ['集团合并', '华东区域'], 'periods': ['2026-01:2026-08'], 'requires_drilldown': True}]
    with pytest.raises(FoundryError) as refused:
        save_requirements(analysis, spec(items=items))

    message = str(refused.value)
    suggested = json.loads(message.split('suggested_items=', 1)[1])
    assert refused.value.details['code'] == 'requirement_dimension_not_row_filter'
    assert refused.value.details['suggested_items'] == suggested
    assert suggested[0]['dimensions'] == {'product': '物业费'}
    saved = save_requirements(analysis, spec(items=suggested))
    assert saved['items'][0]['dimensions'] == {'product': '物业费'}
    assert saved['items'][0]['organizations'] == ['集团合并', '华东区域']


def test_old_record_with_a_drilldown_dimension_gets_a_revise_fixup_and_stamped_rows_do_not_count(analysis):
    record = _new(analysis.task, question='旧要求', scope={'ledger': 'L1'}, bindings={}, context_id=None,
                  items=[{'id': 'attainment', 'metric': 'ratio', 'label': '达成率', 'dimensions': {'drilldown': '城市公司'},
                          'periods': ['2026-08'], 'requires_drilldown': False}],
                  parent_id=None, removed_item_ids=[], change_reason='', selection=None)
    analysis._write(analysis._object_path('requirements', record['id']), record)
    run = _run(analysis, id_suffix='stamped', finance_scope={'actual': {'ledger': 'L1'}}, result={
        'columns': ['metric_key', 'period', 'drilldown', 'value'],
        'rows': [{'metric_key': 'ratio', 'period': '2026-08', 'drilldown': '城市公司', 'value': '0.9'}]})

    item = _item(check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run, row=0, column='value', value='0.9')]}))
    fixup = next(fixup for fixup in item['fixups'] if fixup['code'] == 'revise_requirement_dimension')

    assert item['status'] == 'pending'
    assert fixup['keys'] == ['drilldown']
    assert fixup['suggested_item']['dimensions'] == {}
    assert '请用 parent_id 重新保存要求' in _unanswered_message(item)


def test_grain_basis_must_name_a_subset_and_a_method(analysis):
    item = {'id': 'revenue', 'metric': 'revenue', 'organizations': ['集团合并'], 'periods': ['2026-08']}
    with pytest.raises(FoundryError, match='subset'):
        save_requirements(analysis, spec(items=[{**item, 'grain_basis': [{'basis': 'estimate', 'method': 'x', 'organizations': ['华东']}]}]))
    with pytest.raises(FoundryError, match='method'):
        save_requirements(analysis, spec(items=[{**item, 'grain_basis': [{'basis': 'estimate'}]}]))
    with pytest.raises(FoundryError, match='reason'):
        save_requirements(analysis, spec(items=[{**item, 'grain_basis': [{'basis': 'unavailable'}]}]))
    saved = save_requirements(analysis, spec(items=[{**item, 'grain_basis': [{'basis': 'unavailable', 'reason': '无数'}]}]))
    assert saved['items'][0]['grain_basis'] == [{'basis': 'unavailable', 'reason': '无数'}]


def test_organizations_missing_from_bound_workbooks_only_warn(analysis, tmp_path):
    source = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'A5': '华东区域', 'A11': '合并合计'}})
    saved = save_requirements(analysis, spec(bindings={'close': source['id']}, items=[
        {'id': 'revenue', 'metric': 'revenue', 'organizations': ['华东区域', '集团合并'], 'periods': ['2026-08']}]))

    assert [(warning['code'], warning['organization']) for warning in saved['authoring_warnings']] == [
        ('organization_not_found_in_sources', '集团合并')]
    assert saved['items'][0]['organizations'] == ['华东区域', '集团合并']


def test_amount_labels_are_gated_like_their_canonical_metric(analysis, tmp_path):
    """营业收入 used to slip past the closure gate because only the raw metric was compared."""
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'B5': 414696250}})
    requirement = save_requirements(analysis, spec(
        scope={'ledger': '月结套表', 'currency': 'CNY', 'unit': '万元'}, bindings={'close': close['id']},
        items=[{'id': 'revenue', 'metric': '营业收入'}]))
    row = {'metric_key': '营业收入', 'value': '41469.6250', 'unit': '万元', 'currency': 'CNY'}
    run = _script_run(analysis, {'close': close}, [row], suffix='label')
    base = {'requirements_id': requirement['id'], 'run_ids': [run['id']],
            'claims': [_claim(run, row=0, column='value', value='41469.6250')]}

    script_only = _item(check_requirements(analysis, base))
    recipe = _recipe(close, '04·合并利润表', 'B5', run, 0, scale='0.0001')

    assert script_only['status'] == 'not_applicable'
    assert script_only['uncounted_grains'] == [{'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']}]
    assert '已引用了结果但未计入（本项不分组织、期间和情景）' in _unanswered_message(script_only)
    assert _item(check_requirements(analysis, {**base, 'evidence_recipes': [recipe]}))['status'] == 'answered'


# --- scope matching ------------------------------------------------------------------------------------


def _ratio_rows(**extra):
    return [{'metric_key': 'ratio', 'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8',
             'value': '0.607733', 'unit': '-', **extra}]


def test_ratio_item_ignores_amount_unit_and_currency_but_an_amount_item_does_not(analysis, tmp_path):
    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'A1': '华东区域'}})
    scope = {'ledger': '预算工作簿', 'currency': 'CNY', 'unit': '万元'}
    grain = {'organizations': ['华东区域'], 'periods': ['2026-01:2026-08'], 'scenarios': ['budget_1_8']}
    requirement = save_requirements(analysis, spec(scope=scope, bindings={'budget': source['id']}, items=[
        {'id': 'ratio', 'metric': 'ratio', **grain}, {'id': 'income', 'metric': 'other_income', **grain}]))
    run = _script_run(analysis, {'budget': source}, [*_ratio_rows(), {**_ratio_rows()[0], 'metric_key': 'other_income'}],
                      suffix='ratio-unit')
    result = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': [
        _claim(run, row=0, column='value', value='0.607733'), _claim(run, row=1, column='value', value='0.607733')]})

    assert _item(result, 'ratio')['status'] == 'answered'
    assert _item(result, 'income')['status'] == 'pending'
    assert _item(result, 'income')['row_field_gaps'] == {'currency': 'CNY', 'unit': '万元'}


def test_ledger_is_proven_by_bound_snapshot_hashes_never_by_row_text(analysis, tmp_path):
    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'A1': '华东区域'}})
    grain = {'organizations': ['华东区域'], 'periods': ['2026-01:2026-08'], 'scenarios': ['budget_1_8']}
    bound = save_requirements(analysis, spec(scope={'ledger': '预算工作簿'}, bindings={'budget': source['id']},
                                             items=[{'id': 'ratio', 'metric': 'ratio', **grain}]))
    same = _script_run(analysis, {'budget': source}, _ratio_rows(), suffix='same-snapshot')
    stale = _script_run(analysis, {'budget': source}, _ratio_rows(ledger='预算工作簿'), suffix='stale-snapshot',
                        input_hashes={'budget': '0' * 64})

    def status(run):
        return _item(check_requirements(analysis, {'requirements_id': bound['id'], 'run_ids': [run['id']],
                                                   'claims': [_claim(run, row=0, column='value', value='0.607733')]}))

    assert status(same)['status'] == 'answered'
    assert status(stale)['status'] == 'pending'

    unbound = save_requirements(analysis, spec(parent_id=bound['id'], scope={'ledger': '预算工作簿'}, bindings={},
                                               items=[{'id': 'ratio', 'metric': 'ratio', **grain}]))
    stamped = _script_run(analysis, {'budget': source}, _ratio_rows(ledger='预算工作簿'), suffix='stamped-ledger')
    item = _item(check_requirements(analysis, {'requirements_id': unbound['id'], 'run_ids': [stamped['id']],
                                               'claims': [_claim(stamped, row=0, column='value', value='0.607733')]}))
    assert unbound.get('semantic_basis') is None
    assert item['status'] == 'pending'
    assert item['ledger_identity'] == 'unproven_without_bound_snapshots'
    assert '行上的账套文字不计入' in _unanswered_message(item)


def test_scenario_compare_item_tolerates_a_run_without_finance_scope(analysis):
    save_requirements(analysis, spec(items=[{'id': 'bridge', 'metric': 'profit',
                                             'dimensions': {'scenario_compare': 'actual_vs_budget'}}]))
    run = _run(analysis, id_suffix='no-scope', finance_scope=None)

    item = _item(check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]}))

    assert item['status'] != 'answered'


# --- guidance that must work when followed literally ---------------------------------------------


def test_scope_organization_stays_a_named_row_field_when_the_item_lists_no_organizations(analysis, tmp_path):
    """Review of PR #17: organization/period/scenario were dropped from scope_fields as grain keys even
    when the item did not list them, so following the fixup exactly still failed."""
    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'A1': '集团合并'}})
    requirement = save_requirements(analysis, spec(
        scope={'ledger': '预算工作簿', 'organization': '集团合并'}, bindings={'budget': source['id']},
        items=[{'id': 'ratio', 'metric': 'ratio', 'periods': ['2026-08']}]))
    bare = {'metric_key': 'ratio', 'period': '2026-08', 'value': '0.9'}
    run = _script_run(analysis, {'budget': source}, [bare], suffix='no-org')
    base = {'requirements_id': requirement['id'], 'run_ids': [run['id']]}
    item = _item(check_requirements(analysis, {**base, 'claims': [_claim(run, row=0, column='value', value='0.9')]}))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')

    assert fixup['row_keys'] == ['metric_key', 'period', 'value']
    assert fixup['scope_fields'] == {'organization': '集团合并'}

    literal = {key: bare[key] for key in fixup['row_keys']}
    literal.update({'metric_key': fixup['metric_key'], **fixup['scope_fields']})
    fixed = _script_run(analysis, {'budget': source}, [literal], suffix='literal-org')
    answered = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [fixed['id']],
                                             'claims': [_claim(fixed, row=0, column='value', value='0.9')]})
    assert _item(answered)['status'] == 'answered'


def test_field_gaps_use_the_real_matcher_and_do_not_depend_on_claim_order(analysis, tmp_path):
    """Review of PR #17: the gap scan skipped ratio metric_key-pin rows, listed metric_key twice and
    depended on set order, which made the completion fingerprint irreproducible."""
    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'A1': '物业'}})
    requirement = save_requirements(analysis, spec(
        scope={'ledger': '预算工作簿', 'segment': '物业'}, bindings={'budget': source['id']},
        items=[{'id': 'attainment', 'metric': 'ratio', 'dimensions': {'metric_key': 'revenue'},
                'scenarios': ['achievement_ratio']}]))
    rows = [{'metric_key': 'revenue', 'scenario': 'achievement_ratio', 'value': '0.94'},
            {'metric_key': 'profit', 'scenario': 'achievement_ratio', 'segment': '物业', 'value': '0.78'}]
    run = _script_run(analysis, {'budget': source}, rows, suffix='pin-gaps')
    claims = [_claim(run, row=0, column='value', value='0.94'), _claim(run, row=1, column='value', value='0.78')]

    forward = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims}))
    backward = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                   'claims': list(reversed(claims))}))
    fixup = next(f for f in forward['fixups'] if f['code'] == 'add_requirement_rows')

    assert list(forward['row_field_gaps'].items()) == [('metric_key', 'revenue'), ('segment', '物业')]
    assert list(backward['row_field_gaps'].items()) == list(forward['row_field_gaps'].items())
    assert _unanswered_message(forward) == _unanswered_message(backward)
    assert forward['fixups'] == backward['fixups']
    assert fixup['row_keys'] == ['metric_key', 'scenario', 'value']
    assert fixup['row_fields'] == {'metric_key': 'revenue'}


def test_cited_but_uncounted_grains_are_not_reported_as_uncited(analysis):
    """Review of PR #15 (a): a grain whose cited row came back missing_data or pending was reported as
    “没有已引用的结果行” and the writer was told to add a row the draft already cited."""
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'attainment', 'metric': 'ratio', 'periods': ['2026-07', '2026-08', '2026-09'],
                'requires_drilldown': False}],
    ))
    scope = {'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'}}
    ratios = _run(analysis, id_suffix='ratio-closure', finance_scope=scope, result={
        'columns': ['period', 'numerator', 'denominator', 'ratio'],
        'rows': [
            {'period': '2026-08', 'numerator': '30', 'denominator': '120', 'ratio': '0.30'},  # 30/120 is 0.25
            {'period': '2026-08', 'numerator': '30', 'denominator': '120', 'ratio': '0.25'},
            {'period': '2026-07', 'numerator': '60', 'denominator': '120', 'ratio': '0.5'},
        ],
    })
    values = _run(analysis, id_suffix='ratio-values', finance_scope=scope, result={
        'columns': ['period', 'metric_key', 'value'],
        'rows': [{'period': '2026-09', 'metric_key': 'ratio', 'value': 'N/A'},
                 {'period': '2026-09', 'metric_key': 'ratio', 'value': '0.9'}],
    })
    run_ids = [ratios['id'], values['id']]

    item = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': run_ids, 'claims': [
        _claim(ratios, row=0, column='ratio', value='0.30'), _claim(values, row=0, column='value', value='N/A')]}))
    fixups = {f['reason']: f for f in item['fixups'] if f['code'] == 'add_requirement_rows'}
    message = _unanswered_message(item)

    assert item['status'] == 'pending'
    assert item['missing_grains'] == [{'period': '2026-07'}]
    assert item['uncounted_grains'] == [
        {'period': '2026-08', 'statuses': ['missing_data'], 'reasons': ['evidence_incomplete']},
        {'period': '2026-09', 'statuses': ['pending'], 'reasons': ['no_evidence_record']}]
    assert set(fixups) == {'no_cited_row_for_requested_grain', 'cited_result_not_counted'}
    assert fixups['no_cited_row_for_requested_grain']['missing'] == [{'period': '2026-07'}]
    assert fixups['cited_result_not_counted']['not_counted'] == item['uncounted_grains']
    assert 'row_keys' not in fixups['cited_result_not_counted']
    assert '1 个要求组合没有已引用的结果行（如 2026-07）' in message
    assert '2 个要求组合已引用了结果但未计入（如 2026-08）' in message
    assert '3 个要求组合' not in message

    fixed = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': run_ids, 'claims': [
        _claim(ratios, row=1, column='ratio', value='0.25'), _claim(ratios, row=2, column='ratio', value='0.5'),
        _claim(values, row=1, column='value', value='0.9')]})
    assert _item(fixed)['status'] == 'answered'
    assert 'uncounted_grains' not in _item(fixed)


def test_method_requirement_is_named_and_a_run_with_that_method_answers(analysis):
    """Review of PR #15 (b): an item pinned to a method never matched value rows from other runs."""
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'attainment', 'metric': 'ratio', 'dimensions': {'method': 'actual_over_budget'},
                'periods': ['2026-08'], 'requires_drilldown': False}],
    ))
    row = {'period': '2026-08', 'metric_key': 'ratio', 'value': '0.9'}
    scope = {'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'}}
    plain = _run(analysis, id_suffix='no-method', finance_scope=scope, result={'columns': list(row), 'rows': [row]})
    with_method = _run(analysis, id_suffix='with-method', finance_scope=scope,
                       result={'method': 'actual_over_budget', 'columns': list(row), 'rows': [row]})

    item = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [plain['id']],
                                               'claims': [_claim(plain, row=0, column='value', value='0.9')]}))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')

    assert item['status'] == 'pending'
    assert fixup['required_method'] == 'actual_over_budget'
    assert fixup['accepted_evidence'] == ['method_run']
    assert 'method 为 actual_over_budget 的运行产出的含 metric_key（ratio）、period 和 value 的结果行' in _unanswered_message(item)

    fixed = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [with_method['id']],
                                          'claims': [_claim(with_method, row=0, column='value', value='0.9')]})
    assert _item(fixed)['status'] == 'answered'


def test_profit_bridge_requirement_names_the_bridge_and_the_bridge_answers(tmp_path):
    """Review of PR #15 (b): profit-bridge items only match the four contribution cells of an
    explain_variance bridge; value rows and run_metric totals never do."""
    scope = {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'}
    east = [row for row in _regional_rows() if row['organization'] == '华东']
    service, context, bindings = _finance_service_from_rows(
        tmp_path,
        {'actual': [row for row in east if row['scenario'] == 'actual'],
         'budget': [row for row in east if row['scenario'] == 'budget']},
        {'actual': {**scope, 'scenario': 'actual'}, 'budget': {**scope, 'scenario': 'budget'}},
        title='bridge-guidance',
    )
    requirement = service.analysis_requirements_save({
        'question': '华东 2026-08 实际对预算利润差异桥', 'context_id': context['id'], 'scope': scope, 'bindings': bindings,
        'items': [{'id': 'east_bridge', 'metric': 'profit', 'periods': ['2026-08'], 'requires_drilldown': False,
                   'dimensions': {'dimension': 'management_account', 'method': 'profit_bridge',
                                  'scenario_compare': 'actual_vs_budget'}}],
    })
    run = service.explain_variance({'context_id': context['id'], 'method': 'revenue_minus_cost_minus_expense',
                                    'actual_scenario': 'actual', 'baseline_scenario': 'budget'})

    item = _item(check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': []}))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')
    message = _unanswered_message(item)

    assert item['status'] == 'pending'
    assert 'row_keys' not in fixup
    assert fixup['accepted_evidence'] == ['profit_bridge']
    assert fixup['required_method'] == 'revenue_minus_cost_minus_expense'
    assert fixup['cite_columns'] == ['contribution']
    assert fixup['cite_row_metrics'] == ['revenue', 'cost', 'expense', 'profit']
    assert 'explain_variance 按 revenue_minus_cost_minus_expense' in message
    assert '收入、成本、费用、利润四行的 contribution' in message
    assert 'run_metric' not in message and 'metric_key' not in message

    answered = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                     'claims': _claims_for_columns(run, 'contribution')})
    assert _item(answered)['status'] == 'answered'


def test_price_quantity_requirement_names_the_bridge_columns(analysis):
    requirement = save_requirements(analysis, spec(
        question='只对商品B做收入量价拆分',
        scope={'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元'},
        bindings={'pq': 'pq-dataset'},
        items=[{'id': 'revenue_pq', 'metric': 'revenue', 'periods': ['2026-08'], 'requires_drilldown': False,
                'dimensions': {'product': '商品B', 'method': 'quantity_then_price'}}],
    ))
    run = _pq_run(analysis, method='quantity_then_price', product='商品B', total='26', quantity='-10',
                  price='36', interaction='0', residual='0', row_updates={'period': '2026-08'},
                  columns=['ledger', 'organization', 'period', 'currency', 'unit', 'product', 'actual', 'baseline',
                           'quantity_contribution', 'price_contribution', 'interaction', 'total_variance', 'residual'])

    item = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': []}))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')
    message = _unanswered_message(item)

    assert 'row_keys' not in fixup
    assert fixup['accepted_evidence'] == ['price_quantity_bridge']
    assert fixup['cite_columns'] == ['total_variance', 'quantity_contribution', 'price_contribution', 'interaction']
    assert 'explain_variance 按 quantity_then_price' in message
    assert 'run_metric' not in message

    answered = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                             'claims': _pq_claims(run)})
    assert _item(answered)['status'] == 'answered'


def test_structure_awaiting_confirmation_hands_result_sets_to_the_manager(analysis, tmp_path, monkeypatch):
    from foundry.structure_records import PENDING_CONFIRMATION

    monkeypatch.setattr(FinanceStore, 'dataset_structure_state', lambda self, dataset_id: PENDING_CONFIRMATION)
    source = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'D11': 1}})
    requirement = save_requirements(analysis, spec(scope={'ledger': '月结套表'}, bindings={'close': source['id']}, items=[
        {'id': 'control_totals', 'metric': 'control_totals', 'periods': ['2026-01:2026-08']},
        {'id': 'revenue', 'metric': 'revenue', 'periods': ['2026-08']}]))

    result = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [], 'claims': []})
    controls, revenue = _item(result, 'control_totals'), _item(result, 'revenue')
    blocked = next(f for f in controls['fixups'] if f['code'] == 'evidence_path_blocked')

    assert controls['awaiting_manager'] == ['structure_pending_confirmation']
    assert blocked['needs_manager'] is True
    assert blocked['blocked_evidence'][0]['blockers'] == ['structure_pending_confirmation', 'no_finance_context']
    assert '工作簿结构待经理确认' in _unanswered_message(controls)
    # The recipe path does not need the structure, so the revenue item stays the assistant's to fix.
    assert revenue['evidence_paths']['accepted'][0]['path'] == 'evidence_recipe'
    assert revenue['evidence_paths']['blocked'][0]['path'] == 'engine_closure'
    assert 'awaiting_manager' not in revenue
    assert requirement['support']['items'][1]['accepted_evidence'] == ['evidence_recipe']
    assert 'run_metric' not in json.dumps(requirement['support']['items'][1], ensure_ascii=False)

    only_controls = save_requirements(analysis, spec(parent_id=requirement['id'], scope={'ledger': '月结套表'},
                                                     bindings={'close': source['id']}, change_reason='收入另行复核',
                                                     items=[{'id': 'control_totals', 'metric': 'control_totals',
                                                             'periods': ['2026-01:2026-08']}]))
    quality = augment_quality(analysis, {'requirements_id': only_controls['id'], 'run_ids': [], 'claims': []},
                              {'status': 'pass', 'issues': []})
    completion = record_completion(analysis, {'id': 'c' * 32, 'content_hash': 'controls', 'run_ids': []}, quality)
    assert completion['status'] == 'awaiting_manager'
    assert completion['stop_reason'] == 'manager_decision_required'
    assert completion['manager_reasons'] == ['structure_pending_confirmation']


# --- draft saving ----------------------------------------------------------------------------------


def test_save_draft_evaluates_each_recipe_once_and_uses_that_report(analysis, monthly, monkeypatch):
    import foundry.financial_evidence as evidence

    calls = []
    original = evidence._evaluate_recipe

    def counting(analysis_, recipe, *args, **kwargs):
        calls.append(recipe['id'])
        return original(analysis_, recipe, *args, **kwargs)

    monkeypatch.setattr(evidence, '_evaluate_recipe', counting)
    draft = analysis.save_draft({'title': '收入', 'body': '收入说明。', 'run_ids': [monthly.run['id']],
                                 'claims': monthly.claims, 'evidence_recipes': monthly.good})

    assert sorted(calls) == ['actual', 'budget']
    assert draft['evidence_report']['summary']['status'] == 'pass'
    assert _item(draft['quality']['requirements'])['status'] == 'answered'

    calls.clear()
    service = FinanceStore(analysis.task)
    saved = service.save_explanation_draft({'body': '收入说明。', 'run_ids': [monthly.run['id']],
                                            'claims': monthly.claims, 'evidence_recipes': monthly.good})
    assert sorted(calls) == ['actual', 'budget']
    assert _item(saved['explanation_check']['requirements'])['status'] == 'answered'


def test_generated_appendix_groups_recipe_evidence_and_labels_estimates(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path)
    service = FinanceStore(analysis.task)
    facts = service.prepare_explanation({'run_ids': [case.run['id']]})['facts']
    fact_ids = [fact['id'] for fact in facts if fact['column'] == 'value']
    draft = service.save_explanation_draft({'body': '收入说明见附表。', 'run_ids': [case.run['id']], 'fact_ids': fact_ids,
                                            'evidence_recipes': case.spec['evidence_recipes']})

    assert '## 来源复算依据' in draft['body']
    assert '- revenue_1_8（revenue）' in draft['body']
    assert '来源原值（单元格选择待复核）：10·区域经营损益表!D11；10·区域经营损益表!D5' in draft['body']
    assert '来源计算（单元格选择待复核）：01·年度预算总表!B12:C12' in draft['body']
    assert '估算（经理确认前不计为已回答）：05·区域预算分解!C5 × （01·年度预算总表!B12:C12 ÷ 01·年度预算总表!N12）' in draft['body']
    appendix_issues = [issue for issue in draft['explanation_check']['issues'] if issue.get('origin') == 'generated_appendix']
    assert appendix_issues == []
    assert _item(draft['explanation_check']['requirements'])['status'] == 'estimated'
    revalidated = service.validate_explanation({'draft_id': draft['id']})
    assert [issue for issue in revalidated['issues'] if issue.get('origin') == 'generated_appendix'] == []


def test_recipe_anchors_are_read_for_display_and_do_not_change_the_hash(analysis, monthly):
    anchored = {**monthly.good[0], 'anchors': {'row_label': 'A12', 'column_header': 'I3'}}
    plain, with_anchors = evaluate_evidence_recipes(analysis, [monthly.good[0]])['results'][0], \
        evaluate_evidence_recipes(analysis, [anchored])['results'][0]

    assert with_anchors['anchors']['row_label']['text'] == '营业收入'
    assert with_anchors['anchors']['column_header']['text'] == '8月预算'
    assert with_anchors['recipe_hash'] == plain['recipe_hash']
    assert with_anchors['status'] == plain['status'] == 'pass'
    with pytest.raises(FoundryError, match='single A1 cell'):
        evaluate_evidence_recipes(analysis, [{**monthly.good[0], 'anchors': {'row_label': 'A1:A2'}}])


# --- review fixes (PR #23) ---------------------------------------------------------------------------


UNLISTED_AMOUNT_LABELS = ['利润总额', '营业总收入', '主营业务收入', '营业总成本', '销售费用', 'total_revenue']


def _label_case(analysis, tmp_path, label):
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'B5': 9970000}})
    requirement = save_requirements(analysis, spec(scope={'ledger': '月结套表'}, bindings={'close': close['id']},
                                                   items=[{'id': 'p', 'metric': label}]))
    run = _script_run(analysis, {'close': close}, [{'metric_key': label, 'value': '997', 'unit': '万元', 'currency': 'CNY'}],
                      suffix='label', requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'])
    base = {'requirements_id': requirement['id'], 'run_ids': [run['id']],
            'claims': [_claim(run, row=0, column='value', value='997')]}
    return SimpleNamespace(close=close, requirement=requirement, run=run, base=base,
                           recipe=_recipe(close, '04·合并利润表', 'B5', run, 0, scale='0.0001'))


@pytest.mark.parametrize('label', UNLISTED_AMOUNT_LABELS)
def test_common_pnl_labels_outside_the_alias_list_are_gated_as_amounts(analysis, tmp_path, label):
    """An item saved as 利润总额 / 销售费用 / total_revenue … fell to the non-amount rule, so a plain python
    value answered it. Decision 1 gates every revenue/profit/cost/expense amount, whatever it is named."""
    case = _label_case(analysis, tmp_path, label)

    script_only = check_requirements(analysis, case.base)
    item = _item(script_only)
    support = case.requirement['support']['items'][0]

    assert item['status'] == 'not_applicable'
    assert script_only['coverage']['status'] == 'needs_attention'
    assert item['uncounted_grains'] == [{'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']}]
    assert [path['path'] for path in item['evidence_paths']['accepted']] == ['evidence_recipe']
    # The support report names the same path, not the free SQL/Python result-column advice.
    assert support['accepted_evidence'] == ['evidence_recipe']
    assert support['status'] == 'requires_execution'
    assert 'SQL/Python' not in support.get('next_action', '')
    assert 'evidence_recipe' in support['evidence']

    answered = check_requirements(analysis, {**case.base, 'evidence_recipes': [case.recipe]})
    assert _item(answered)['status'] == 'answered'
    assert _item(answered)['locations'][0]['evidence']['evidence_basis'] == 'source_value'


def test_an_unlisted_pnl_label_answered_by_a_script_value_no_longer_completes_the_draft(analysis, tmp_path):
    case = _label_case(analysis, tmp_path, '利润总额')
    service = FinanceStore(analysis.task)
    draft = service.save_explanation_draft({'body': '利润总额为 997 万元。', 'run_ids': [case.run['id']],
                                            'claims': case.base['claims']})

    assert _item(draft['explanation_check']['requirements'])['status'] == 'not_applicable'
    assert draft['completion']['status'] != 'complete'
    assert draft['completion']['original_requirements_completed'] is False


@pytest.mark.parametrize('label', ['收入达成率', '销售费用率', 'expense_ratio'])
def test_ratio_and_other_labels_keep_the_phase_1_script_rule(analysis, tmp_path, label):
    """Decision 4: script ratio values are not tightened in phase 1, so the amount gate must not swallow
    ratios named after an amount. (other_income left this list in review round 3: it is an amount, and
    the inverted gate covers it; see GATED_AMOUNT_LABELS.)"""
    case = _label_case(analysis, tmp_path, label)

    assert _item(check_requirements(analysis, case.base))['status'] == 'answered'


def test_support_evidence_names_only_the_paths_the_checker_offers(analysis, tmp_path):
    """Engine closure rows carry no scenario, so an amount item with scenarios is never offered that path."""
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'B5': 1}})
    saved = save_requirements(analysis, spec(scope={'ledger': '月结套表'}, bindings={'close': close['id']}, items=[
        {'id': 'with_scenarios', 'metric': 'revenue', 'periods': ['2026-08'], 'scenarios': ['actual_2026_08']},
        {'id': 'plain', 'metric': 'revenue', 'periods': ['2026-08']}]))
    support = {row['requirement_item_id']: row for row in saved['support']['items']}

    assert support['with_scenarios']['accepted_evidence'] == ['evidence_recipe']
    assert support['with_scenarios']['evidence'] == 'evidence_recipe'
    assert 'engine_closure' not in json.dumps(support['with_scenarios'], ensure_ascii=False)
    # Without scenarios the engine path exists; here it is blocked, and the blocker is stated.
    assert support['plain']['evidence'] == 'evidence_recipe / engine_closure (explain_variance)'
    assert [path['path'] for path in support['plain']['blocked_evidence']] == ['engine_closure']


def test_claim_cited_estimate_is_labelled_in_the_saved_body_like_a_fact_cited_one(analysis, tmp_path):
    """The generated appendix came from a provisional check that saw fact_ids only, so an estimate cited
    through claims reached quality but not the exported body. Decision 2: exports always label 估算."""
    case = _estimate_case(analysis, tmp_path)
    service = FinanceStore(analysis.task)
    draft = service.save_explanation_draft({'body': '华东区域 1-8 月收入预算 112860.000 万元。', 'run_ids': [case.run['id']],
                                            'claims': case.spec['claims'], 'evidence_recipes': case.spec['evidence_recipes']})

    assert _item(draft['explanation_check']['requirements'])['status'] == 'estimated'
    assert '## 来源复算依据' in draft['body']
    assert '估算（经理确认前不计为已回答）：05·区域预算分解!C5 × （01·年度预算总表!B12:C12 ÷ 01·年度预算总表!N12）' in draft['body']
    assert [issue for issue in draft['explanation_check']['issues'] if issue.get('origin') == 'generated_appendix'] == []
    revalidated = service.validate_explanation({'draft_id': draft['id']})
    assert _item(revalidated['requirements'])['status'] == 'estimated'
    assert [issue for issue in revalidated['issues'] if issue.get('origin') == 'generated_appendix'] == []


def test_bare_year_periods_in_the_generated_appendix_do_not_block_the_manager_handoff(analysis, tmp_path):
    """Huachen fy items: rows with period '2026' printed '… / budget_1_8 / 2026' in the server's own 计算依据
    appendix, the validator flagged each bare 2026, and the draft could never reach awaiting_manager."""
    case = _estimate_case(analysis, tmp_path, period='2026')
    service = FinanceStore(analysis.task)
    draft = service.save_explanation_draft({'body': '收入说明见附表。', 'run_ids': [case.run['id']],
                                            'claims': case.spec['claims'], 'evidence_recipes': case.spec['evidence_recipes']})
    quality = draft['explanation_check']

    assert '/ budget_1_8 / 2026' in draft['body']
    assert [issue for issue in quality['issues'] if issue['code'] == 'uncited_number'] == []
    assert _item(quality['requirements'])['status'] == 'estimated'
    assert draft['completion']['status'] == 'awaiting_manager'
    assert draft['completion']['stop_reason'] == 'estimate_requires_acceptance'
    assert draft['completion']['repair_allowed'] is False
    revalidated = service.validate_explanation({'draft_id': draft['id']})
    assert [issue for issue in revalidated['issues'] if issue['code'] == 'uncited_number'] == []


def test_a_bare_year_the_writer_types_is_still_an_uncited_number(analysis, tmp_path):
    """Only the server's own appendix labels are exempt; the same number in the manager's prose is checked."""
    case = _estimate_case(analysis, tmp_path, period='2026')
    service = FinanceStore(analysis.task)
    draft = service.save_explanation_draft({'body': '收入预算 2026 见附表。', 'run_ids': [case.run['id']],
                                            'claims': case.spec['claims'], 'evidence_recipes': case.spec['evidence_recipes']})

    flagged = [issue for issue in draft['explanation_check']['issues'] if issue['code'] == 'uncited_number']
    assert [(issue['text'], issue['origin']) for issue in flagged] == [('2026', 'manager_body')]
    assert draft['completion']['status'] != 'awaiting_manager'


def test_only_period_shaped_name_segments_of_the_trusted_appendix_are_exempt():
    """Row names come from the script's own rows, so the exemption is narrow: a later ' / ' segment (or a
    key=value segment of a group title) shaped like a period. The metric name and other numbers stay checked."""
    from foundry.finance_explanations import _generated_appendix_label_number_spans

    appendix = ('## 计算依据\n\n### 利润桥闭合依据 / period=2026\n'
                '- 收入 997 / value / budget / 2026（非可引用：未生成可核验事实）\n'
                '- revenue / value / budget / 997（非可引用：未生成可核验事实）')
    body = '正文 2026。\n\n' + appendix
    regions = [{'section': 'generated_appendix', 'start': body.index('## 计算依据'), 'end': len(body)}]
    prepared = {'evidence_groups': [{'label': '利润桥闭合依据 / period=2026', 'members': [
        {'label': '收入 997 / value / budget / 2026'}, {'label': 'revenue / value / budget / 997'}]}]}

    spans = _generated_appendix_label_number_spans(body, regions, prepared)

    assert [(body[start:end], start >= regions[0]['start']) for start, end in sorted(spans)] == [('2026', True), ('2026', True)]
    assert _generated_appendix_label_number_spans(body, [], prepared) == []


# --- helpers ---------------------------------------------------------------------------------------


def _estimate_case(analysis, tmp_path, *, declare=True, declaration=None, cite_estimate=True, period='2026-01:2026-08',
                   east_budget=180576, estimate_extra=None):
    """Huachen revenue_1_8 in miniature: group actual/budget and East actual from the source; the East
    1-8 budget exists only as East full-year budget × group 1-8 budget progress (300 ÷ 480 = 0.625)."""
    budget = _workbook(analysis, tmp_path, 'budget', {
        '01·年度预算总表': {'B12': 100, 'C12': 200, 'N12': 480},
        '05·区域预算分解': {'C5': east_budget},
    })
    close = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'D5': 109742.028, 'D11': 325644}})
    grain_basis = [declaration or {'organizations': ['华东区域'], 'scenarios': ['budget_1_8'], 'basis': 'estimate',
                                   'method': '区域全年收入预算 × 集团1-8月收入预算进度'}] if declare else []
    requirement = save_requirements(analysis, spec(
        question='1-8 月收入实际与同期预算',
        scope={'ledger': '预算工作簿与月结套表', 'currency': 'CNY', 'unit': '万元'},
        bindings={'budget': budget['id'], 'close': close['id']},
        items=[{'id': 'revenue_1_8', 'metric': 'revenue', 'organizations': ['集团合并', '华东区域'],
                'periods': [period], 'scenarios': ['actual_1_8', 'budget_1_8'], 'requires_drilldown': True,
                **({'grain_basis': grain_basis} if grain_basis else {})}],
    ))
    base = {'metric_key': 'revenue', 'period': period, 'unit': '万元', 'currency': 'CNY'}
    rows = [
        {**base, 'organization': '集团合并', 'scenario': 'actual_1_8', 'value': '325644'},
        {**base, 'organization': '集团合并', 'scenario': 'budget_1_8', 'value': '300'},
        {**base, 'organization': '华东区域', 'scenario': 'actual_1_8', 'value': '109742.028'},
        {**base, 'organization': '华东区域', 'scenario': 'budget_1_8', 'value': '112860.000'},
        {**base, 'organization': '集团合并', 'scenario': 'budget_phasing_ratio', 'value': '0.625', 'unit': '-'},
    ]
    datasets = {'budget': budget, 'close': close}
    run = _script_run(analysis, datasets, rows, suffix='estimate',
                      requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'])
    key = {'metric_key': 'revenue', 'period': period}
    recipes = [
        _recipe(close, '10·区域经营损益表', 'D11', run, 0, recipe_id='group_actual'),
        _recipe(budget, '01·年度预算总表', 'B12:C12', run, 1, kind='sum', recipe_id='group_budget'),
        _recipe(close, '10·区域经营损益表', 'D5', run, 2, recipe_id='east_actual'),
        {'id': 'phasing', 'kind': 'ratio', 'business_key': key, 'claim': {'run_id': run['id'], 'row': 4, 'column': 'value'},
         'left': {'dataset_id': budget['id'], 'source_hash': budget['source_hash'], 'sheet': '01·年度预算总表', 'range': 'B12:C12'},
         'right': {'dataset_id': budget['id'], 'source_hash': budget['source_hash'], 'sheet': '01·年度预算总表', 'range': 'N12'}},
    ]
    if cite_estimate:
        recipes.append({**_recipe(budget, '05·区域预算分解', 'C5', run, 3, recipe_id='east_budget_estimate'),
                        'factor_recipe_id': 'phasing', 'business_key': key, **(estimate_extra or {})})
    values = ['325644', '300', '109742.028', '112860.000', '0.625']
    rows_cited = range(5) if cite_estimate else (0, 1, 2)
    claims = [_claim(run, row=index, column='value', value=values[index]) for index in rows_cited]
    return SimpleNamespace(requirement=requirement, run=run, budget=budget, spec={
        'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims, 'evidence_recipes': recipes})


# --- review fixes, round 2 (PR #23) -----------------------------------------------------------------


def _non_amount_estimate(analysis, tmp_path, metric, *, declare=True):
    """The same workbook, rows and recipes as a revenue estimate, on an item that is not a P&L amount."""
    book = _workbook(analysis, tmp_path, 'book', {'S': {'F5': 1200, 'G1': 2, 'G2': 4}})
    declared = [{'basis': 'estimate', 'scenarios': ['budget_1_8'], 'method': '全年预算 × 2/4'}] if declare else []
    requirement = save_requirements(analysis, spec(
        scope={'currency': 'CNY', 'unit': '万元'}, bindings={'book': book['id']},
        items=[{'id': 'item', 'metric': metric, 'scenarios': ['budget_1_8'], 'requires_drilldown': False,
                **({'grain_basis': declared} if declared else {})}]))
    key = {'metric_key': metric, 'period': '2026-01:2026-08'}
    rows = [{'metric_key': metric, 'scenario': 'budget_1_8', 'period': '2026-01:2026-08', 'value': '600',
             'currency': 'CNY', 'unit': '万元'},
            {'metric_key': metric, 'scenario': 'factor', 'period': '2026-01:2026-08', 'value': '0.5'}]
    run = _script_run(analysis, {'book': book}, rows, suffix='non-amount', requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'])

    def cell(reference):
        return {'dataset_id': book['id'], 'source_hash': book['source_hash'], 'sheet': 'S', 'range': reference}

    recipes = [
        {'id': 'f', 'kind': 'ratio', 'claim': {'run_id': run['id'], 'row': 1, 'column': 'value'},
         'left': cell('G1'), 'right': cell('G2'), 'business_key': key},
        {'id': 'd', 'kind': 'direct', **cell('F5'), 'claim': {'run_id': run['id'], 'row': 0, 'column': 'value'},
         'factor_recipe_id': 'f', 'business_key': key},
    ]
    return SimpleNamespace(requirement=requirement, run=run, recipes=recipes,
                           claims=[_claim(run, row=0, column='value', value='600')])


@pytest.mark.parametrize('metric', ['other_income', '其他收益', 'management_pnl'])
def test_a_declared_estimate_on_a_non_amount_item_is_estimated_and_labelled(analysis, tmp_path, metric):
    """The non-amount branch dropped the factor recipe (estimate is not a source basis) and answered the
    grain as script output: coverage passed and the export lost its 估算 line. A factor recipe gives
    `estimated`, never answered, whatever the metric."""
    case = _non_amount_estimate(analysis, tmp_path, metric)
    service = FinanceStore(analysis.task)
    fact_ids = [fact['id'] for fact in service.prepare_explanation({'run_ids': [case.run['id']]})['facts']]
    draft = service.save_explanation_draft({'body': '1-8 月预算见附表。', 'run_ids': [case.run['id']],
                                            'fact_ids': fact_ids, 'claims': case.claims,
                                            'evidence_recipes': case.recipes})
    quality = draft['explanation_check']
    item = _item(quality['requirements'])

    assert item['status'] == 'estimated'
    assert [location['evidence']['evidence_basis'] for location in item['locations']] == ['estimate']
    assert quality['requirements']['coverage']['status'] == 'needs_attention'
    assert 'requirement_estimated' in [issue['code'] for issue in quality['issues']]
    assert '估算（经理确认前不计为已回答）：S!F5 × （S!G1 ÷ S!G2）' in draft['body']
    assert draft['completion']['status'] == 'awaiting_manager'
    assert draft['completion']['original_requirements_completed'] is False


def test_an_undeclared_estimate_on_a_non_amount_item_is_not_answered_either(analysis, tmp_path):
    case = _non_amount_estimate(analysis, tmp_path, 'other_income', declare=False)
    item = _item(check_requirements(analysis, {'requirements_id': case.requirement['id'], 'run_ids': [case.run['id']],
                                               'claims': case.claims, 'evidence_recipes': case.recipes}))

    assert item['status'] == 'pending'
    assert item['locations'][0]['evidence']['not_counted_reason'] == 'estimate_cited_for_source_grain'
    # Review round 3 inverted the amount gate: other_income is an amount, so its plain script value
    # does not answer either (only ratios, counts and quantities keep the phase-1 script rule).
    plain = _item(check_requirements(analysis, {'requirements_id': case.requirement['id'], 'run_ids': [case.run['id']],
                                                'claims': case.claims}))
    assert plain['status'] == 'pending'
    assert plain['uncounted_grains'][0]['reasons'] == ['script_output_without_recipe']


@pytest.mark.parametrize('label', ['net_income', 'operating_income', '管理费', '销售费', '财务费', '净收益'])
def test_more_common_pnl_amount_names_are_gated(analysis, tmp_path, label):
    """net_income, operating_income, 净收益 and 管理费/销售费/财务费 (written without 用) fell to the
    non-amount rule, so one cited python cell answered them and the draft completed."""
    case = _label_case(analysis, tmp_path, label)
    service = FinanceStore(analysis.task)

    assert _item(check_requirements(analysis, case.base))['status'] == 'not_applicable'
    draft = service.save_explanation_draft({'body': '金额为 997 万元。', 'run_ids': [case.run['id']],
                                            'claims': case.base['claims']})
    assert draft['completion']['status'] != 'complete'
    assert draft['completion']['original_requirements_completed'] is False
    assert _item(check_requirements(analysis, {**case.base, 'evidence_recipes': [case.recipe]}))['status'] == 'answered'


@pytest.mark.parametrize('label', ['sales_volume', 'sales_quantity', 'sales_qty', 'sales_count', '销量', '销售数量'])
def test_quantities_named_after_sales_keep_the_phase_1_script_rule(analysis, tmp_path, label):
    """AMOUNT_LABEL_TOKENS maps `sales` to revenue, so sales_volume was gated as a revenue amount and
    offered paths that never produce a quantity. A quantity is not an amount (decision 4)."""
    case = _label_case(analysis, tmp_path, label)

    assert _item(check_requirements(analysis, case.base))['status'] == 'answered'


def _ledger_account_case(tmp_path, account):
    """A finance context over a ledger, and an item asking for one management account with dimensions.period."""
    rows = [
        {'ledger': 'L', 'organization': '总部', 'period': period, 'currency': 'CNY', 'unit': '元', 'scenario': 'actual',
         'management_account': account, 'amount': amount, 'source_row': str(index), 'doc_id': f'D{index}', 'line_id': '1'}
        for index, (period, amount) in enumerate((('2026-07', '100'), ('2026-08', '110')), start=1)]
    scope = {'ledger': 'L', 'organization': '总部', 'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}
    service, context, bindings = _finance_service_from_rows(tmp_path, {'actual': rows}, {'actual': scope}, title='ledger')
    requirement = save_requirements(service.analysis, {
        'question': f'8 月{account}', 'context_id': context['id'], 'bindings': bindings, 'scope': {'actual': scope},
        'items': [{'id': 'account_08', 'metric': account, 'dimensions': {'period': '2026-08'}, 'requires_drilldown': False}]})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'account_total', 'accounts': [account]}})
    index = next(index for index, row in enumerate(run['result']['rows']) if row.get('period') == '2026-08')
    claim = {'basis': 'calculation', 'run_id': run['id'], 'row': index, 'column': 'amount',
             'value': run['result']['rows'][index]['amount']}
    return SimpleNamespace(service=service, context=context, bindings=bindings, requirement=requirement, run=run,
                           claims=[claim], index=index)


@pytest.mark.parametrize('account', ['管理费用', '销售费用', '主营业务成本', 'cash'])
def test_the_finance_engines_own_account_total_still_answers_an_account_item(tmp_path, account):
    """Before the label gate, run_metric account_total was the accepted path for an account-name item
    with dimensions.period; the gate caught 费用/成本/收入-named accounts, labelled the engine's own amount
    script output and pointed the writer at explain_variance."""
    case = _ledger_account_case(tmp_path, account)
    result = check_requirements(case.service.analysis, {'requirements_id': case.requirement['id'],
                                                        'run_ids': [case.run['id']], 'claims': case.claims})
    item = _item(result)
    support = case.requirement['support']['items'][0]

    assert case.run['engine'] == 'finance'
    assert item['status'] == 'answered'
    assert result['coverage']['status'] == 'pass'
    assert item['locations'][0]['evidence']['evidence_basis'] == 'engine_output'
    assert support['accepted_evidence'][0] == 'run_metric_account_total'
    if 'next_action' in support:
        assert support['next_action'].index('run_metric') < support['next_action'].find('explain_variance') or \
            'explain_variance' not in support['next_action']


def test_a_script_copy_of_the_account_total_is_still_not_counted(tmp_path):
    case = _ledger_account_case(tmp_path, '管理费用')
    analysis = case.service.analysis
    row = {'management_account': '管理费用', 'period': '2026-08', 'amount': '110'}
    record = _new(analysis.task, engine='python', execution_status='succeeded', reproducibility_status='unverified',
                  assumptions=[], output_hash='script-account', bindings=case.run['bindings'],
                  input_hashes=case.run.get('input_hashes'), source_hashes=case.run.get('source_hashes'),
                  result={'columns': list(row), 'rows': [row]})
    script = analysis._write(analysis._object_path('runs', record['id']), record)
    item = _item(check_requirements(analysis, {'requirements_id': case.requirement['id'], 'run_ids': [script['id']],
                                               'claims': [_claim(script, row=0, column='amount', value='110')]}))

    assert item['status'] != 'answered'


def test_an_engine_amount_that_is_not_counted_is_not_labelled_script_output(analysis):
    save_requirements(analysis, spec(items=[{'id': 'revenue', 'metric': 'revenue', 'scenarios': ['actual'],
                                             'requires_drilldown': False}]))
    run = _run(analysis, id_suffix='engine-values', result={
        'columns': ['metric_key', 'scenario', 'value'],
        'rows': [{'metric_key': 'revenue', 'scenario': 'actual', 'value': '120'}]})
    item = _item(check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run, row=0, column='value', value='120')]}))

    assert item['status'] != 'answered'
    assert item['locations'][0]['evidence']['evidence_basis'] == 'engine_output'


def _replay_spec(analysis, tmp_path):
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'B33': 9970000}})
    requirement = save_requirements(analysis, spec(scope={'ledger': '月结套表'}, bindings={'close': close['id']},
                                                   items=[{'id': 'profit', 'metric': 'profit', 'requires_drilldown': False}]))
    bridge = [{'metric': 'revenue', 'actual': '1999', 'baseline': '1000', 'contribution': '999'},
              {'metric': 'cost', 'actual': '1', 'baseline': '2', 'contribution': '-1'},
              {'metric': 'expense', 'actual': '1', 'baseline': '2', 'contribution': '-1'},
              {'metric': 'profit', 'actual': '1997', 'baseline': '1000', 'contribution': '997'}]
    run = _script_run(analysis, {'close': close}, bridge, suffix='bridge', requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'],
                      result={'method': 'revenue_minus_cost_minus_expense',
                              'columns': ['metric', 'actual', 'baseline', 'contribution'], 'rows': bridge})
    return {'body': '利润变动 997。', 'run_ids': [run['id']], 'claims': [_claim(run, row=3, value='997')]}


def _as_saved_before_policy_5(analysis, draft):
    """Rewrite the stored draft as one saved before this PR: its check answered the item from a script-built
    bridge, and it carries no record of the policy it was checked under."""
    from foundry.analysis import _hash
    from foundry.fsutil import write_json_atomic

    path = analysis._object_path('drafts', draft['id'])
    stored = {key: value for key, value in json.loads(path.read_text()).items()
              if key not in {'check_policy_version', '_integrity_hash'}}
    check = stored['explanation_check']
    requirements = {**check['requirements'], 'coverage': {'status': 'pass'}, 'provenance': {'status': 'pass'},
                    'original_requirements_completed': True,
                    'items': [{**item, 'status': 'answered'} for item in check['requirements']['items']]}
    old = {**check, 'status': 'pass', 'issues': [], 'requirements': requirements,
           'checks': {'numbers': {'status': 'pass'}, 'coverage': {'status': 'pass'}, 'provenance': {'status': 'pass'}}}
    record = {**stored, 'explanation_check': old, 'quality': old}
    write_json_atomic(path, {**record, '_integrity_hash': _hash(record)})
    return record


def test_replaying_a_draft_checked_under_an_older_policy_rechecks_it(analysis, tmp_path):
    """A byte-identical resend found the pre-PR draft and stamped a policy-5 `complete` receipt from the
    verdict computed under the old rules, while a fresh validate said the script bridge does not count."""
    from foundry.finance_completion import COMPLETION_POLICY_VERSION

    service = FinanceStore(analysis.task)
    request = _replay_spec(analysis, tmp_path)
    first = service.save_explanation_draft(request)
    assert first['check_policy_version'] == COMPLETION_POLICY_VERSION
    _as_saved_before_policy_5(analysis, first)

    again = service.save_explanation_draft(request)

    assert again.get('replayed') is not True
    assert again['id'] != first['id']
    assert _item(again['explanation_check']['requirements'])['status'] != 'answered'
    assert again['completion']['status'] != 'complete'
    assert again['completion']['original_requirements_completed'] is False
    assert not [row for row in analysis._list('completions')
                if row['draft_id'] == first['id'] and row['status'] == 'complete']
    # A draft checked under the current policy still replays without a new version.
    third = service.save_explanation_draft(request)
    assert third['replayed'] is True
    assert third['id'] == again['id']


def test_a_runtime_retry_of_a_draft_checked_under_an_older_policy_rechecks_it(analysis, tmp_path):
    from foundry.analysis import _hash
    from foundry.finance_completion_operations import CompletionOperationStore
    from foundry.fsutil import write_json_atomic

    service = FinanceStore(analysis.task)
    service.session_id = 'session-a'
    operation = CompletionOperationStore(analysis.task, 'session-a').begin('利润说明')
    request = _replay_spec(analysis, tmp_path)
    first = service.save_completion_draft(operation['id'], 'call-1', request)
    _as_saved_before_policy_5(analysis, first)
    # The pre-PR save wrote the draft and stopped before the receipt settled the attempt.
    path = analysis.task.root / 'analysis' / 'completion_operations' / f"{operation['id']}.json"
    raw = json.loads(path.read_text())
    raw.pop('_integrity_hash')
    for attempt in raw['revisions']:
        attempt.pop('draft_id', None)
        attempt.pop('completion_id', None)
    raw['_integrity_hash'] = _hash(raw)
    write_json_atomic(path, raw)

    again = service.save_completion_draft(operation['id'], 'call-1', request)

    assert again['id'] != first['id']
    assert _item(again['explanation_check']['requirements'])['status'] != 'answered'
    assert again['completion']['status'] != 'complete'
    assert not [row for row in analysis._list('completions')
                if row['draft_id'] == first['id'] and row['status'] == 'complete']


def test_a_declared_estimate_grain_is_told_to_use_a_factor_recipe(analysis, tmp_path):
    """Huachen revenue_1_8: the East 1-8 budget is declared an estimate. When its cited row went missing,
    or its coefficient was written as scale, the hint only offered direct/sum/diff with a unit scale,
    which can never reach the promised `estimated`."""
    case = _estimate_case(analysis, tmp_path)
    claims = [claim for claim in case.spec['claims'] if claim['row'] != 3]
    item = _item(check_requirements(analysis, {**case.spec, 'claims': claims}))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')
    message = _unanswered_message(item)

    assert item['missing_grains'] == [{'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8'}]
    assert fixup['estimate_grains'] == item['missing_grains']
    assert fixup['estimate_evidence']['factor_recipe_kind'] == 'ratio'
    assert 'factor_recipe_id' in message
    assert '只计为估算' in message

    scaled = [recipe for recipe in case.spec['evidence_recipes'] if recipe['id'] != 'east_budget_estimate']
    scaled.append(_recipe(case.budget, '05·区域预算分解', 'C5', case.run, 3, scale='0.625', recipe_id='east_budget_scaled'))
    item = _item(check_requirements(analysis, {**case.spec, 'evidence_recipes': scaled}))
    fixup = next(f for f in item['fixups'] if f.get('reason') == 'cited_result_not_counted')

    assert item['uncounted_grains'][0]['reasons'] == ['recipe_coefficient_unbound']
    assert fixup['estimate_grains'] == [{'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8'}]
    assert 'factor_recipe_id' in _unanswered_message(item)


def test_a_grain_the_source_lacks_is_told_how_to_declare_it_and_following_that_reaches_the_manager(analysis, tmp_path):
    """profit_1_8 regional budgets: nothing in the bound workbooks states them, but the hint only offered
    source recipes and never grain_basis, so literal compliance could not reach needs_manager."""
    case = _estimate_case(analysis, tmp_path, declare=False, cite_estimate=False)
    item = _item(check_requirements(analysis, case.spec))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')
    message = _unanswered_message(item)

    assert fixup['if_source_lacks_value']['field'] == 'grain_basis'
    assert 'grain_basis' in message and 'factor_reproducible' in message

    record = case.requirement
    declared = save_requirements(analysis, spec(
        question=record['question'], scope=record['scope'], bindings=record['bindings'], parent_id=record['id'],
        items=[{**record['items'][0], 'grain_basis': [
            {'basis': 'estimate', 'organizations': ['华东区域'], 'scenarios': ['budget_1_8'],
             'method': '（营业利润预算 − 其他收益预算）÷ 区域营业利润预算合计', 'factor_reproducible': False,
             'reason': '系数须先相减再相除，现有规则写不出'}]}]))
    after = _item(check_requirements(analysis, {**case.spec, 'requirements_id': declared['id']}))
    assert after['status'] == 'pending'
    assert after['awaiting_manager'] == ['estimate_factor_not_reproducible']


def test_uncounted_fixup_lists_only_cells_that_did_not_count(analysis, tmp_path):
    """An estimated cell was listed as a cell to repair, with a null reason, next to the one cell that really
    did not count."""
    case = _estimate_case(analysis, tmp_path)
    recipes = [recipe for recipe in case.spec['evidence_recipes'] if recipe['id'] != 'group_budget']
    recipes.append(_recipe(case.budget, '01·年度预算总表', 'N12', case.run, 1, scale='0.625', recipe_id='group_budget_scaled'))
    item = _item(check_requirements(analysis, {**case.spec, 'evidence_recipes': recipes}))
    fixup = next(f for f in item['fixups'] if f.get('reason') == 'cited_result_not_counted')

    assert [location['status'] for location in item['locations'] if location['row'] == 3] == ['estimated']
    assert fixup['not_counted_count'] == 1
    assert [(cell['row'], cell['not_counted_reason']) for cell in fixup['evidence_recipe_cells']] == [
        (1, 'recipe_coefficient_unbound')]


def test_an_estimate_cited_on_a_grain_declared_non_reproducible_gets_no_empty_fixup(analysis, tmp_path):
    case = _estimate_case(analysis, tmp_path, declaration={
        'organizations': ['华东区域'], 'scenarios': ['budget_1_8'], 'basis': 'estimate',
        'method': '（Σ营业利润预算 − Σ其他收益预算）÷ 区域营业利润预算合计',
        'factor_reproducible': False, 'reason': '系数须先相减再相除，现有规则写不出'})
    item = _item(check_requirements(analysis, case.spec))
    east_budget = next(location for location in item['locations'] if location['row'] == 3)

    assert item['awaiting_manager'] == ['estimate_factor_not_reproducible']
    assert east_budget['evidence']['not_counted_reason'] == 'estimate_factor_declared_not_reproducible'
    assert [f for f in item['fixups'] if f['code'] == 'estimate_cited_for_source_grain'] == []


def test_blockers_the_assistant_can_clear_do_not_tell_it_to_stop(analysis, tmp_path):
    """A CSV-bound revenue item with no finance context: both paths are blocked, but no_finance_context is
    the assistant's to clear with finance_context_save, and completion still offers repairs."""
    path = tmp_path / 'rev.csv'
    path.write_text('organization,period,revenue\n华东,2026-08,120.5\n', encoding='utf-8')
    dataset = analysis.add_dataset(path, name='rev')
    requirement = save_requirements(analysis, {'question': '8月华东收入', 'bindings': {'rev': dataset['id']},
                                               'items': [{'id': 'rev_08', 'metric': 'revenue', 'dimensions': {'period': '2026-08'},
                                                          'requires_drilldown': False}]})
    run = _script_run(analysis, {'rev': dataset}, [{'metric_key': 'revenue', 'period': '2026-08', 'value': '120.5'}],
                      suffix='csv', requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'])
    saved = FinanceStore(analysis.task).save_explanation_draft({
        'body': '华东8月收入 120.5。', 'run_ids': [run['id']],
        'claims': [_claim(run, row=0, column='value', value='120.5')]})
    action = next(action for action in saved['completion']['actions'] if action['code'] == 'requirement_unanswered')

    assert saved['completion']['status'] == 'repair_available'
    assert saved['completion']['repair_allowed'] is True
    assert '助手不要重复计算' not in action['message']
    assert 'finance_context_save' in action['message']


def _legacy_drilldown_record(analysis, bindings, items):
    record = _new(analysis.task, question='华宸 1-8 月', scope={'ledger': '月结套表', 'unit': '万元'}, bindings=bindings,
                  context_id=None, parent_id=None, removed_item_ids=[], change_reason='', selection=None, items=items)
    return analysis._write(analysis._object_path('requirements', record['id']), record)


def test_the_scope_card_can_save_over_a_legacy_drilldown_record(analysis, tmp_path):
    """AnalysisScopeCard resends the current items unchanged with a new scope. On a record saved before
    phase 1 the items still hold dimensions.drilldown, and the save was refused with a 2–3k character
    assistant message the card cannot act on. A key carried over from the parent is dropped as the
    refusal itself suggests; a newly written one is still refused."""
    close = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'A5': '华东区域'}})
    legacy = _legacy_drilldown_record(analysis, {'close': close['id']}, [
        {'id': 'revenue_1_8', 'metric': 'revenue', 'label': '收入', 'dimensions': {'drilldown': '城市公司'},
         'periods': ['2026-01:2026-08'], 'requires_drilldown': False},
        {'id': 'profit_1_8', 'metric': 'profit', 'label': '利润', 'dimensions': {'drilldown': '城市公司'},
         'periods': ['2026-01:2026-08'], 'requires_drilldown': False}])
    service = FinanceStore(analysis.task)
    listed = service.analysis_requirements_list({})['current']

    saved = service.analysis_requirements_save({
        'question': listed['question'], 'scope': {**listed['scope'], 'granularity': '月'}, 'bindings': listed['bindings'],
        'parent_id': listed['id'], 'change_reason': '更新分析前置口径。', 'items': listed['items']})

    assert saved['parent_id'] == legacy['id']
    assert [item['dimensions'] for item in saved['items']] == [{}, {}]
    assert [(warning['code'], warning['requirement_item_id']) for warning in saved['authoring_warnings']] == [
        ('hierarchy_dimension_dropped', 'revenue_1_8'), ('hierarchy_dimension_dropped', 'profit_1_8')]
    with pytest.raises(FoundryError, match='hierarchy levels'):
        service.analysis_requirements_save({
            'question': saved['question'], 'scope': saved['scope'], 'bindings': saved['bindings'], 'parent_id': saved['id'],
            'items': [{**saved['items'][0], 'dimensions': {'drilldown': '城市公司'}}, saved['items'][1]]})


def test_a_legacy_drilldown_item_is_not_handed_to_the_manager_while_the_assistant_can_revise_it(analysis, tmp_path, monkeypatch):
    from foundry.structure_records import PENDING_CONFIRMATION

    monkeypatch.setattr(FinanceStore, 'dataset_structure_state', lambda self, dataset_id: PENDING_CONFIRMATION)
    source = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'D11': 1}})
    record = _legacy_drilldown_record(analysis, {'close': source['id']}, [
        {'id': 'control_totals', 'metric': 'control_totals', 'label': '区域与城市公司小计勾稽',
         'dimensions': {'drilldown': '城市公司'}, 'periods': ['2026-01:2026-08'], 'requires_drilldown': False}])
    request = {'requirements_id': record['id'], 'run_ids': [], 'claims': []}
    item = _item(check_requirements(analysis, request))
    quality = augment_quality(analysis, request, {'status': 'pass', 'issues': []})
    completion = record_completion(analysis, {'id': 'l' * 32, 'content_hash': 'legacy', 'run_ids': []}, quality)
    action = next(action for action in completion['actions'] if action['code'] == 'requirement_unanswered')

    assert 'awaiting_manager' not in item
    assert 'revise_requirement_dimension' in [fixup['code'] for fixup in item['fixups']]
    assert completion['status'] == 'repair_available'
    assert completion['repair_allowed'] is True
    assert '助手不要重复计算' not in action['message']


# --- review fixes, round 3 (PR #23) -----------------------------------------------------------------
#
# Rounds 1-3 each found P&L names that slipped past a list of amount names. The gate is now inverted:
# every item is an amount unless it is a known non-amount (a ratio, an item asking only for ratio
# scenarios, a count or a physical quantity). A name the gate does not recognise is gated.


GATED_AMOUNT_LABELS = [
    # camelCase and Chinese P&L names that rounds 1-2 missed
    'NetProfit', 'netProfit', 'TotalRevenue', 'CostOfSales', 'GrossProfit', 'OperatingIncome', 'NetIncome', '盈利',
    # names nothing recognises: gated all the same, never exempt
    'PBT', 'SG&A', 'turnover', 'custom_formula', 'gross_margin',
    # amounts outside revenue/profit/cost/expense
    'other_income', '其他收益',
    # 率 inside an amount name is not a ratio (exchange gains and losses)
    '汇率损益',
]


@pytest.mark.parametrize('label', GATED_AMOUNT_LABELS)
def test_every_item_that_is_not_a_known_non_amount_is_gated(analysis, tmp_path, label):
    case = _label_case(analysis, tmp_path, label)
    item = _item(check_requirements(analysis, case.base))

    assert item['status'] == 'not_applicable'
    assert item['uncounted_grains'] == [{'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']}]
    draft = FinanceStore(analysis.task).save_explanation_draft({'body': '金额为 997 万元。', 'run_ids': [case.run['id']],
                                                                'claims': case.base['claims']})
    assert draft['completion']['status'] != 'complete'
    assert draft['completion']['original_requirements_completed'] is False
    # The path the guidance names answers it.
    assert _item(check_requirements(analysis, {**case.base, 'evidence_recipes': [case.recipe]}))['status'] == 'answered'


@pytest.mark.parametrize('label, key', [
    ('NetProfit', 'profit'), ('GrossProfit', 'profit'), ('OperatingIncome', 'profit'), ('NetIncome', 'profit'),
    ('盈利', 'profit'), ('TotalRevenue', 'revenue'), ('CostOfSales', 'cost'), ('PBT', 'amount'), ('custom_formula', 'amount'),
])
def test_a_recognised_pnl_name_keeps_its_class_and_anything_else_is_a_plain_amount(label, key):
    from foundry.finance_requirements import _closed_metric_key

    assert _closed_metric_key({'metric': label}) == key


KNOWN_NON_AMOUNT_LABELS = [
    'ratio', '收入达成率', '销售费用率', 'expense_ratio', 'grossMarginRate', '毛利率（%）', '收入占比',
    'sales_volume', '销量', 'headcount', 'order_count', '人数', '管理面积',
]


@pytest.mark.parametrize('label', KNOWN_NON_AMOUNT_LABELS)
def test_known_non_amounts_keep_the_phase_1_script_rule(analysis, tmp_path, label):
    """Decision 4 leaves script ratio values alone in phase 1; counts and physical quantities are not money."""
    case = _label_case(analysis, tmp_path, label)

    assert _item(check_requirements(analysis, case.base))['status'] == 'answered'


def test_only_an_item_that_asks_for_ratio_scenarios_is_a_ratio(analysis, tmp_path):
    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'A1': '收入'}})
    requirement = save_requirements(analysis, spec(scope={'ledger': '预算工作簿'}, bindings={'budget': source['id']}, items=[
        {'id': 'attainment', 'metric': 'revenue', 'scenarios': ['achievement_ratio']},
        {'id': 'mixed', 'metric': 'revenue', 'scenarios': ['actual', 'achievement_ratio']},
        {'id': 'amount', 'metric': 'revenue'}]))
    rows = [{'metric_key': 'revenue', 'scenario': 'achievement_ratio', 'value': '0.94'},
            {'metric_key': 'revenue', 'scenario': 'actual', 'value': '120'}]
    run = _script_run(analysis, {'budget': source}, rows, suffix='ratio-scenarios')
    result = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': [
        _claim(run, row=0, column='value', value='0.94'), _claim(run, row=1, column='value', value='120')]})
    mixed = _item(result, 'mixed')

    assert _item(result, 'attainment')['status'] == 'answered'
    # The ratio grain keeps the script rule; the amount grain of the same item does not.
    assert mixed['status'] == 'pending'
    assert mixed['uncounted_grains'] == [{'scenario': 'actual', 'statuses': ['not_applicable'],
                                          'reasons': ['script_output_without_recipe']}]
    # An item that asks for the amount is not answered by a ratio row that happens to name it.
    assert _item(result, 'amount')['status'] == 'not_applicable'


def test_a_draft_that_policy_5_completed_on_an_ungated_name_is_checked_again(analysis, tmp_path):
    """Under completion policy 5 a script value answered NetProfit and the draft completed. The inverted
    gate changes that verdict, so a resend must not replay the policy-5 draft."""
    from foundry.analysis import _hash
    from foundry.fsutil import write_json_atomic

    case = _label_case(analysis, tmp_path, 'NetProfit')
    service = FinanceStore(analysis.task)
    request = {'body': '净利润为 997 万元。', 'run_ids': [case.run['id']], 'claims': case.base['claims']}
    first = service.save_explanation_draft(request)
    path = analysis._object_path('drafts', first['id'])
    stored = {key: value for key, value in json.loads(path.read_text()).items() if key != '_integrity_hash'}
    check = stored['explanation_check']
    old = {**check, 'status': 'pass', 'issues': [], 'requirements': {
        **check['requirements'], 'coverage': {'status': 'pass'}, 'original_requirements_completed': True,
        'items': [{**item, 'status': 'answered'} for item in check['requirements']['items']]}}
    record = {**stored, 'check_policy_version': 5, 'explanation_check': old, 'quality': old}
    write_json_atomic(path, {**record, '_integrity_hash': _hash(record)})

    again = service.save_explanation_draft(request)

    assert again.get('replayed') is not True
    assert again['completion']['status'] != 'complete'
    assert again['completion']['original_requirements_completed'] is False


def test_a_finance_engine_cell_answers_an_amount_outside_revenue_profit_cost_expense(analysis):
    """Script values never answer an amount; the engine's own output of a non-P&L-line amount still does.
    revenue/profit/cost/expense keep the literal closure rule (see the engine-output test above)."""
    save_requirements(analysis, spec(items=[{'id': 'income', 'metric': 'other_income', 'requires_drilldown': False}]))
    rows = {'columns': ['metric_key', 'value'], 'rows': [{'metric_key': 'other_income', 'value': '12'}]}
    engine = _run(analysis, id_suffix='engine-other-income', result=rows)
    script = _run(analysis, id_suffix='script-other-income', engine='python', result=rows)

    def check(run):
        return _item(check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run, row=0, column='value', value='12')]}))

    assert check(engine)['status'] == 'answered'
    assert check(engine)['locations'][0]['evidence']['evidence_basis'] == 'engine_output'
    assert check(script)['status'] == 'not_applicable'


def _result_set_account_case(tmp_path, account, *, drilldown):
    rows = [
        {'ledger': 'L', 'organization': '总部', 'period': period, 'currency': 'CNY', 'unit': '元', 'scenario': 'actual',
         'management_account': account, 'amount': amount, 'source_row': str(index), 'doc_id': f'D{index}', 'line_id': '1'}
        for index, (period, amount) in enumerate((('2026-07', '100'), ('2026-08', '110')), start=1)]
    scope = {'ledger': 'L', 'organization': '总部', 'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}
    service, context, bindings = _finance_service_from_rows(tmp_path, {'actual': rows}, {'actual': scope}, title='ledger78')
    requirement = save_requirements(service.analysis, {
        'question': f'7-8 月{account}', 'context_id': context['id'], 'bindings': bindings, 'scope': {'actual': scope},
        'items': [{'id': 'account_78', 'metric': account, 'periods': ['2026-07', '2026-08'], 'requires_drilldown': drilldown}]})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'account_total', 'accounts': [account]}})
    return SimpleNamespace(service=service, requirement=requirement, run=run,
                           spec={'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': []})


@pytest.mark.parametrize('drilldown', [False, True])
@pytest.mark.parametrize('account', ['管理费用', '主营业务成本', '主营业务收入', 'cash'])
def test_a_result_set_account_item_names_its_rows_and_following_that_answers(tmp_path, account, drilldown):
    """The amount gate made _claim_fixup reject the engine's own account_total cells, so a 费用/成本/收入
    account item listing periods lost every add_calculation_claim and verify_source fixup. The result set
    needs every row cited and source-checked, so the source check is named even without requires_drilldown."""
    case = _result_set_account_case(tmp_path, account, drilldown=drilldown)
    analysis = case.service.analysis
    pending = _item(check_requirements(analysis, case.spec))
    codes = [fixup['code'] for fixup in pending['fixups']]

    assert pending['status'] == 'pending'
    assert codes.count('add_calculation_claim') == 2
    assert codes.count('verify_source') == 2
    assert 'run_metric' in _unanswered_message(pending)

    claims = [{'basis': 'calculation', **{key: fixup[key] for key in ('run_id', 'row', 'column', 'value')}}
              for fixup in pending['fixups'] if fixup['code'] == 'add_calculation_claim']
    for fixup in pending['fixups']:
        if fixup['code'] == 'verify_source':
            case.service.drilldown_fact({key: fixup['location'][key] for key in ('run_id', 'row', 'column')})
    done = check_requirements(analysis, {**case.spec, 'claims': claims})
    assert _item(done)['status'] == 'answered'
    assert done['coverage']['status'] == 'pass'


def test_a_run_on_the_single_bound_snapshot_under_another_alias_proves_the_ledger(analysis, tmp_path):
    """_bindings_match lets a single-binding requirement be met by a run that binds the same snapshot under
    its own alias, but the ledger check looked the snapshot up by the requirement's alias, so the cited row
    was dropped and reported as never cited."""
    source = _workbook(analysis, tmp_path, 'actual', {'PL': {'B7': 414696250}})
    requirement = save_requirements(analysis, spec(scope={'ledger': 'L1'}, bindings={'actual': source['id']}, items=[
        {'id': 'ratio', 'metric': 'ratio', 'requires_drilldown': False},
        {'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False}]))
    rows = [{'metric_key': 'ratio', 'value': '0.9453'}, {'metric_key': 'revenue', 'value': '41469.6250'}]

    def check(run):
        return check_requirements(analysis, {
            'requirements_id': requirement['id'], 'run_ids': [run['id']],
            'claims': [_claim(run, row=0, column='value', value='0.9453'), _claim(run, row=1, column='value', value='41469.6250')],
            'evidence_recipes': [_recipe(source, 'PL', 'B7', run, 1, scale='0.0001')]})

    renamed = check(_script_run(analysis, {'ledger_rows': source}, rows, suffix='renamed-alias'))
    assert _item(renamed, 'ratio')['status'] == 'answered'
    assert _item(renamed, 'revenue')['status'] == 'answered'

    # The same alias on a different snapshot proves nothing.
    stale = check(_script_run(analysis, {'ledger_rows': source}, rows, suffix='stale-alias',
                              input_hashes={'ledger_rows': '0' * 64}))
    assert _item(stale, 'ratio')['status'] == 'pending'
    assert _item(stale, 'revenue')['status'] == 'pending'


@pytest.mark.parametrize('aliases', [('bud', 'clo'), ('budget',), ('close', 'budget')])
def test_a_cited_run_whose_bindings_differ_is_reported_as_not_counted_and_says_how_to_rebind(analysis, monthly, aliases):
    """A run on the requirement's own snapshots under other alias names, or on only one of two, was dropped
    silently: the message said nothing was cited and offered grain_basis for values the source states."""
    # renamed aliases, only one of the two snapshots, and the two snapshots under each other's alias
    run = _script_run(analysis, dict(zip(aliases, [monthly.budget, monthly.close])), REVENUE_ROWS, suffix='-'.join(aliases))
    recipes = [_recipe(monthly.budget, '01·年度预算总表', 'I12', run, 0, recipe_id='budget'),
               _recipe(monthly.close, '04·合并利润表', 'B5', run, 1, scale='0.0001', recipe_id='actual')]
    claims = [_claim(run, row=0, column='value', value='44163.6526'), _claim(run, row=1, column='value', value='41469.6250')]
    item = _item(_check(analysis, monthly, recipes=recipes, claims=claims, run=run))
    rebind = next(f for f in item['fixups'] if f['code'] == 'rebind_run')
    message = _unanswered_message(item)

    assert item['status'] == 'pending'
    assert 'missing_grains' not in item
    assert {reason for grain in item['uncounted_grains'] for reason in grain['reasons']} == {'run_bindings_differ'}
    assert rebind['required_bindings'] == monthly.requirement['bindings']
    assert rebind['runs'] == [{'run_id': run['id'], 'bindings': run['bindings']}]
    assert '没有已引用的结果行' not in message
    assert 'grain_basis' not in message
    assert '运行绑定' in message
    assert not any(f.get('if_source_lacks_value') for f in item['fixups'])
    # Following it: the same rows on a run bound exactly as the requirement answer.
    assert _item(_check(analysis, monthly, recipes=monthly.good))['status'] == 'answered'


def test_an_estimate_whose_source_is_in_yuan_takes_a_unit_scale_next_to_its_factor(analysis, tmp_path):
    """The estimate hint allowed scale 1 or a unit conversion, but any scale next to factor_recipe_id made
    the whole save fail, so an estimate from a 元 source could not be written at all."""
    case = _estimate_case(analysis, tmp_path, east_budget=1805760000, estimate_extra={'scale': '0.0001'})
    service = FinanceStore(analysis.task)
    draft = service.save_explanation_draft({'body': '华东区域 1-8 月收入预算为估算。', 'run_ids': [case.run['id']],
                                            'claims': case.spec['claims'], 'evidence_recipes': case.spec['evidence_recipes']})
    item = _item(draft['explanation_check']['requirements'])
    east = next(location for location in item['locations'] if location['row'] == 3)

    assert item['status'] == 'estimated'
    assert east['evidence']['evidence_basis'] == 'estimate'
    assert east['evidence']['recipe_scale'] == '0.0001'

    # A coefficient written as scale next to a factor is still refused: it belongs in the ratio recipe.
    coefficient = [{**recipe, 'scale': '0.625'} if recipe['id'] == 'east_budget_estimate' else recipe
                   for recipe in case.spec['evidence_recipes']]
    with pytest.raises(FoundryError, match='unit'):
        service.save_explanation_draft({'body': '估算。', 'run_ids': [case.run['id']], 'claims': case.spec['claims'],
                                        'evidence_recipes': coefficient})


def test_script_cells_are_never_sent_to_drilldown_fact(analysis, tmp_path):
    """drilldown_fact can only verify finance-engine or verified-aggregate rows; for a python cell it
    returns 'missing', so a verify_source fixup on it can never be satisfied."""
    case = _estimate_case(analysis, tmp_path, declare=False)
    item = _item(check_requirements(analysis, case.spec))
    quality = augment_quality(analysis, case.spec, {'status': 'pass', 'issues': []})
    source_issue = next(issue for issue in quality['issues'] if issue['code'] == 'requested_source_missing')

    assert item['provenance_status'] == 'pending'
    assert [fixup for fixup in item['fixups'] if fixup['code'] == 'verify_source'] == []
    assert 'verify_source' not in json.dumps(source_issue)


def test_an_answered_script_ratio_cell_is_traced_by_a_recipe_not_by_drilldown(analysis, tmp_path):
    source = _workbook(analysis, tmp_path, 'budget', {'S': {'G1': 2, 'G2': 4}})
    requirement = save_requirements(analysis, spec(scope={'ledger': '预算工作簿'}, bindings={'budget': source['id']},
                                                   items=[{'id': 'ratio', 'metric': 'ratio', 'requires_drilldown': True}]))
    run = _script_run(analysis, {'budget': source}, [{'metric_key': 'ratio', 'value': '0.5'}], suffix='traced-ratio')
    base = {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': [_claim(run, row=0, column='value', value='0.5')]}
    item = _item(check_requirements(analysis, base))

    assert item['status'] == 'answered'
    assert item['provenance_status'] == 'pending'
    assert [fixup['code'] for fixup in item['fixups']] == ['add_source_recipe']
    assert item['fixups'][0]['location']['row'] == 0

    ratio = {'id': 'r', 'kind': 'ratio', 'claim': {'run_id': run['id'], 'row': 0, 'column': 'value'},
             'left': {'dataset_id': source['id'], 'source_hash': source['source_hash'], 'sheet': 'S', 'range': 'G1'},
             'right': {'dataset_id': source['id'], 'source_hash': source['source_hash'], 'sheet': 'S', 'range': 'G2'}}
    traced = _item(check_requirements(analysis, {**base, 'evidence_recipes': [ratio]}))
    assert traced['provenance_status'] == 'verified'
    assert 'fixups' not in traced


def test_scope_fields_are_asked_on_rows_because_a_script_runs_scope_is_not_read(analysis, tmp_path):
    """The draft tool said currency/unit could sit in finance_scope, but a script run's only scope setting
    is stored as run.scope, which requirement matching never reads."""
    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'N41': 43499.9999}})
    grain = {'organization': '集团合并', 'period': '2026', 'scenario': 'budget_bud_fy'}
    requirement = save_requirements(analysis, spec(scope={'ledger': '预算工作簿', 'currency': 'CNY', 'unit': '万元'},
                                                   bindings={'budget': source['id']},
                                                   items=[{'id': 'fy_profit', 'metric': 'profit', 'organizations': ['集团合并'],
                                                           'periods': ['2026'], 'scenarios': ['budget_bud_fy'],
                                                           'requires_drilldown': False}]))
    run = _script_run(analysis, {'budget': source}, [{'metric_key': 'profit', **grain, 'value': '43499.9999'}],
                      suffix='run-scope', scope={'currency': 'CNY', 'unit': '万元'})
    item = _item(check_requirements(analysis, {
        'requirements_id': requirement['id'], 'run_ids': [run['id']],
        'claims': [_claim(run, row=0, column='value', value='43499.9999')],
        'evidence_recipes': [_recipe(source, '预算', 'N41', run, 0)]}))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')

    assert item['status'] == 'pending'
    assert item['row_field_gaps'] == {'currency': 'CNY', 'unit': '万元'}
    assert fixup['scope_fields_on'] == 'rows'
    assert '写在每一条结果行上' in _unanswered_message(item)
    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    assert '或 finance_scope 里' not in tools


def test_tool_descriptions_name_every_path_that_answers_an_amount():
    """The descriptions said amounts were answered 'only' by explain_variance closure or a recipe, while
    the checker also answers them with run_metric account_total, run_metric result sets and, for amounts
    outside revenue/profit/cost/expense, the finance engine's own output."""
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')['description']

    assert '只由两种依据' not in tools
    assert 'answered only by' not in draft
    for text in (tools, draft):
        assert 'account_total' in text
        assert 'result set' in text or '结果集' in text
        assert 'explain_variance' in text
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools


def test_a_scope_granularity_is_not_a_row_filter(analysis, monthly):
    """AnalysisScopeCard saves 粒度 as scope.granularity. The checker then required it on every row, the
    fixup said to stamp it (the PR #17 pattern decision 1 reverses) and a real engine closure never counted."""
    record = monthly.requirement
    granular = save_requirements(analysis, spec(question=record['question'], bindings=record['bindings'],
                                                scope={**record['scope'], 'granularity': '城市公司'},
                                                parent_id=record['id'], items=record['items']))
    case = SimpleNamespace(**{**vars(monthly), 'requirement': granular})
    unbacked = _item(_check(analysis, case))
    backed = _item(_check(analysis, case, recipes=monthly.good))

    assert 'granularity' not in json.dumps(unbacked.get('fixups', []), ensure_ascii=False)
    assert 'granularity' not in unbacked.get('row_field_gaps', {})
    assert backed['status'] == 'answered'


def test_an_engine_closure_answers_under_a_scope_that_states_a_granularity(analysis):
    save_requirements(analysis, spec(scope={'ledger': 'L1', 'granularity': '城市公司'},
                                     items=[{'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False}]))
    run = _run(analysis, id_suffix='granular-closure')

    item = _item(check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run, row=0, value='20')]}))

    assert item['status'] == 'answered'
    assert item['locations'][0]['evidence']['evidence_basis'] == 'engine_closed'


def test_a_drilldown_written_into_scope_is_refused_like_a_dimension(analysis):
    with pytest.raises(FoundryError) as refused:
        save_requirements(analysis, spec(scope={'ledger': 'L1', 'drilldown': '城市公司'}))
    assert refused.value.details['code'] == 'requirement_scope_not_row_filter'
    assert refused.value.details['suggested_scope'] == {'ledger': 'L1'}
    # A granularity is the scope card's own field and stays; it just never filters rows.
    first = save_requirements(analysis, spec(scope={'ledger': 'L1', 'granularity': '月'}))
    assert first['scope']['granularity'] == '月'

    # A level carried over unchanged from an old record is dropped and recorded, as for dimensions.
    legacy = _new(analysis.task, question='华宸 1-8 月', scope={'ledger': '月结套表', 'drilldown': '城市公司'}, bindings={},
                  context_id=None, parent_id=first['id'], removed_item_ids=[], change_reason='', selection=None,
                  items=first['items'])
    analysis._write(analysis._object_path('requirements', legacy['id']), legacy)
    saved = save_requirements(analysis, spec(scope=legacy['scope'], parent_id=legacy['id'], items=legacy['items']))
    assert saved['scope'] == {'ledger': '月结套表'}
    assert [warning['code'] for warning in saved['authoring_warnings']] == ['hierarchy_scope_dropped']


def test_resubmitting_the_refusals_suggested_items_records_the_dropped_legacy_level(analysis, tmp_path):
    """The refusal names only the newly added level, and its suggested_items already lack the legacy one,
    so resubmitting them unchanged dropped 城市公司 with nothing recorded on the new version."""
    close = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'A5': '华东区域'}})
    legacy = _legacy_drilldown_record(analysis, {'close': close['id']}, [
        {'id': 'revenue_1_8', 'metric': 'revenue', 'label': '收入', 'dimensions': {'drilldown': '城市公司'},
         'periods': ['2026-01:2026-08'], 'requires_drilldown': False}])
    items = [*legacy['items'], {'id': 'region_split', 'metric': 'revenue', 'dimensions': {'level': '区域'}}]
    with pytest.raises(FoundryError) as refused:
        save_requirements(analysis, spec(scope=legacy['scope'], bindings=legacy['bindings'], parent_id=legacy['id'], items=items))

    saved = save_requirements(analysis, spec(scope=legacy['scope'], bindings=legacy['bindings'], parent_id=legacy['id'],
                                             items=refused.value.details['suggested_items']))
    assert [(warning['code'], warning['requirement_item_id']) for warning in saved['authoring_warnings']] == [
        ('hierarchy_dimension_dropped', 'revenue_1_8')]
    # A save with no hierarchy anywhere records nothing.
    again = save_requirements(analysis, spec(scope=saved['scope'], bindings=saved['bindings'], parent_id=saved['id'],
                                             items=saved['items']))
    assert 'authoring_warnings' not in again
