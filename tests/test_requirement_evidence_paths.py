"""Phase 1 requirement evidence paths (decisions of 2026-09-24).

Every requirement is an amount unless it is a known non-amount (a ratio, an item asking only for ratio
scenarios, a count or a physical quantity whose name names no amount). Script values never answer an amount.
An amount is answered by a cited cell backed by a passing, server-evaluated direct/sum/diff recipe on the
requirement's own snapshots with a unit scale; by finance-engine closure (revenue/profit/cost/expense items
without scenarios, and the price-quantity bridge); by the finance engine's own run_metric account_total of an
account item, or its run_metric result set; and, outside revenue/profit/cost/expense and the price-quantity
bridge, by the finance engine's own output of that amount or a server-side structured_aggregate of it.
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
    _scope_matches,
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
    _verify_run_column,
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

    # Confirming the structure alone would not open the engine path: the requirement is bound to the workbook
    # files, which give the engine no rows (review round 6).
    assert controls['awaiting_manager'] == ['bindings_without_engine_rows', 'structure_pending_confirmation']
    assert blocked['needs_manager'] is True
    assert blocked['blocked_evidence'][0]['blockers'] == ['structure_pending_confirmation', 'bindings_without_engine_rows']
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
    assert completion['manager_reasons'] == ['bindings_without_engine_rows', 'structure_pending_confirmation']


def _control_totals_on_workbooks(analysis, tmp_path):
    budget = _workbook(analysis, tmp_path, 'budget', {'01·年度预算总表': {'A12': '营业收入', 'I12': 44163.6526}})
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'A5': '营业收入', 'B5': 414696250}})
    bindings = {'budget': budget['id'], 'close': close['id']}
    requirement = save_requirements(analysis, spec(scope={'ledger': '预算工作簿 + 月结套表'}, bindings=bindings, items=[
        {'id': 'control_totals', 'metric': 'control_totals', 'label': '区域与集团合计勾稽',
         'organizations': ['集团合并'], 'periods': ['2026-01:2026-08']}]))
    return bindings, requirement


def test_engine_paths_are_not_offered_on_bound_workbooks_the_engine_reads_no_rows_from(analysis, tmp_path):
    """Review round 6 (Huachen): once the manager had confirmed the workbook structures, control_totals told
    the assistant to save a finance context for the bound data and run run_metric. The requirement is bound
    to the workbook files, which give the engine no rows: the context saved cleanly, run_metric returned 0
    rows, the run was then offered as the accepted path, and completion kept spending repairs on it."""
    bindings, requirement = _control_totals_on_workbooks(analysis, tmp_path)
    service = FinanceStore(analysis.task)
    # The old guidance, followed literally.
    context = service.save_context({'bindings': bindings})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'},
                              'requirements_id': requirement['id']})
    assert run['result']['rows'] == []

    request = {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': []}
    item = _item(check_requirements(analysis, request))
    message = _unanswered_message(item)
    blocked = next(f for f in item['fixups'] if f['code'] == 'evidence_path_blocked')

    assert item['status'] == 'pending'
    assert item['evidence_paths']['accepted'] == []
    assert [(path['path'], path['blockers']) for path in item['evidence_paths']['blocked']] == [
        ('run_metric_result_set', ['bindings_without_engine_rows'])]
    assert item['awaiting_manager'] == ['bindings_without_engine_rows']
    assert blocked['needs_manager'] is True
    assert '读不出财务引擎的数据行' in message
    assert '助手不要重复计算' in message
    assert 'finance_context_save' not in message and '可计入的依据' not in message

    quality = augment_quality(analysis, request, {'status': 'pass', 'issues': []})
    completion = record_completion(analysis, {'id': 'w' * 32, 'content_hash': 'workbooks', 'run_ids': [run['id']]}, quality)
    assert completion['status'] == 'awaiting_manager'
    assert completion['repair_allowed'] is False
    assert completion['manager_reasons'] == ['bindings_without_engine_rows']

    support = service.analysis_requirements_save({**{key: requirement[key] for key in ('question', 'scope', 'bindings', 'items')},
                                                  'parent_id': requirement['id']})['support']['items'][0]
    assert support['accepted_evidence'] == []
    assert support['blocked_evidence'][0]['blockers'] == ['bindings_without_engine_rows']


def test_a_context_on_other_snapshots_does_not_unblock_the_engine_path(analysis, tmp_path):
    """The other reading of the old guidance: a context on table snapshots the requirement is not bound to.
    Its runs never count (run bindings differ), so it must not turn the engine path into an accepted one."""
    bindings, requirement = _control_totals_on_workbooks(analysis, tmp_path)
    path = tmp_path / 'rows.json'
    path.write_text(json.dumps([{'ledger': 'L1', 'organization': '集团合并', 'period': '2026-08', 'currency': 'CNY',
                                 'unit': '万元', 'management_account': 'revenue', 'amount': '1'}]), encoding='utf-8')
    table = analysis.add_dataset(path, name='table')
    service = FinanceStore(analysis.task)
    service.save_context({'bindings': {'budget': table['id'], 'close': bindings['close']}})

    item = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [], 'claims': []}))

    assert item['evidence_paths']['accepted'] == []
    assert item['evidence_paths']['blocked'][0]['blockers'] == ['bindings_without_engine_rows']
    assert 'finance_context_save' not in _unanswered_message(item)


def test_engine_paths_on_bound_tables_stay_open_and_answer_when_followed(tmp_path):
    """Opposite direction: a requirement bound to tables the engine reads keeps run_metric as its accepted
    path, only a context on exactly those bindings counts as one, and following the path answers."""
    service, context, bindings = _finance_service_from_rows(
        tmp_path,
        {'actual': [{'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元',
                     'scenario': 'actual', 'management_account': 'revenue', 'amount': '120', 'source_row': 1}],
         'budget': [{'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元',
                     'scenario': 'budget', 'management_account': 'revenue', 'amount': '100', 'source_row': 1}]},
        {'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
         'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'budget'}},
        title='tables')
    analysis = service.analysis
    requirement = service.analysis_requirements_save({
        'question': '实际与预算控制数对照', 'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                                                 'currency': 'CNY', 'unit': '万元'},
        'bindings': bindings, 'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}]})
    item = _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [], 'claims': []}))
    assert [path['path'] for path in item['evidence_paths']['accepted']] == ['run_metric_result_set']
    assert item['evidence_paths']['blocked'] == []
    assert 'awaiting_manager' not in item

    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    _verify_run_column(service, run, 'amount')
    answered = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                             'claims': _claims_for_columns(run, 'amount')})
    assert _item(answered)['status'] == 'answered'


def test_a_context_on_part_of_the_bindings_is_not_a_finance_context_for_the_requirement(tmp_path):
    """A context that covers only one of two bound tables cannot produce a run with the requirement's
    bindings, so the engine path stays blocked on no_finance_context (the assistant's to clear)."""
    rows = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元',
            'management_account': 'revenue', 'source_row': 1}
    service, _context, bindings = _finance_service_from_rows(
        tmp_path, {'actual': [{**rows, 'scenario': 'actual', 'amount': '120'}]},
        {'actual': {'ledger': 'L1', 'scenario': 'actual'}}, title='partial')
    path = tmp_path / 'budget.json'
    path.write_text(json.dumps([{**rows, 'scenario': 'budget', 'amount': '100'}]), encoding='utf-8')
    budget = service.analysis.add_dataset(path, name='budget')
    requirement = service.analysis_requirements_save({
        'question': '实际与预算控制数对照', 'scope': {'ledger': 'L1'},
        'bindings': {**bindings, 'budget': budget['id']},
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}]})
    item = _item(check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [], 'claims': []}))

    assert item['evidence_paths']['blocked'][0]['blockers'] == ['no_finance_context']
    assert 'awaiting_manager' not in item
    assert 'finance_context_save' in _unanswered_message(item)


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


# --- review fixes, round 4 (PR #23) -----------------------------------------------------------------
#
# The head-word exemption read price_quantity, price_volume and revenue_by_area as physical quantities.
# A count, quantity or area head now exempts a name only when nothing else in it names an amount
# (sales_volume stays a quantity; sales_price_volume is a price-volume bridge, revenue_by_area a split of
# revenue). Ratio heads keep decision 4's phase-1 script rule whatever they are a ratio of.


PRICE_VOLUME_AND_AREA_SPLITS = ['price_quantity', 'revenue_price_quantity', 'price_volume', 'sales_price_volume',
                                'revenue_by_area', 'profit_by_area', 'revenue/area', '收入按面积']


@pytest.mark.parametrize('label', PRICE_VOLUME_AND_AREA_SPLITS)
def test_price_volume_bridges_and_amounts_split_by_area_are_gated_not_read_as_quantities(analysis, tmp_path, label):
    """A python cell (999-style, no recipe) answered these items, coverage passed and the draft completed,
    because the last word (quantity/volume/area) made them physical quantities."""
    case = _label_case(analysis, tmp_path, label)
    result = check_requirements(analysis, case.base)
    item = _item(result)
    support = case.requirement['support']['items'][0]

    assert item['status'] == 'not_applicable'
    assert item['uncounted_grains'] == [{'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']}]
    assert result['coverage']['status'] == 'needs_attention'
    assert result['original_requirements_completed'] is False
    # The support report no longer offers a plain cited row, and its evidence names only offered paths.
    assert 'cited_result_row' not in support['accepted_evidence']
    offered = {*support['accepted_evidence'], *(path['path'] for path in support.get('blocked_evidence', []))}
    assert {part.split(' (')[0] for part in support['evidence'].split(' / ')} <= offered
    draft = FinanceStore(analysis.task).save_explanation_draft({'body': '金额为 997 万元。', 'run_ids': [case.run['id']],
                                                                'claims': case.base['claims']})
    assert draft['completion']['status'] != 'complete'
    assert draft['completion']['original_requirements_completed'] is False
    # The recipe path the guidance names answers it.
    answered = _item(check_requirements(analysis, {**case.base, 'evidence_recipes': [case.recipe]}))
    assert answered['status'] == 'answered'
    assert answered['locations'][0]['evidence']['evidence_basis'] == 'source_value'


def test_a_draft_that_policy_6_completed_on_a_price_volume_name_is_checked_again(analysis, tmp_path):
    """Under completion policy 6 a script value answered price_volume and the draft completed. The narrowed
    quantity exemption changes that verdict, so a resend must not replay the policy-6 draft."""
    from foundry.analysis import _hash
    from foundry.fsutil import write_json_atomic

    case = _label_case(analysis, tmp_path, 'price_volume')
    service = FinanceStore(analysis.task)
    request = {'body': '量价影响为 997 万元。', 'run_ids': [case.run['id']], 'claims': case.base['claims']}
    first = service.save_explanation_draft(request)
    path = analysis._object_path('drafts', first['id'])
    stored = {key: value for key, value in json.loads(path.read_text()).items() if key != '_integrity_hash'}
    check = stored['explanation_check']
    old = {**check, 'status': 'pass', 'issues': [], 'requirements': {
        **check['requirements'], 'coverage': {'status': 'pass'}, 'original_requirements_completed': True,
        'items': [{**item, 'status': 'answered'} for item in check['requirements']['items']]}}
    record = {**stored, 'check_policy_version': 6, 'explanation_check': old, 'quality': old}
    write_json_atomic(path, {**record, '_integrity_hash': _hash(record)})

    again = service.save_explanation_draft(request)

    assert again.get('replayed') is not True
    assert again['completion']['status'] != 'complete'
    assert again['completion']['original_requirements_completed'] is False


def test_every_native_metric_but_ratio_is_gated_as_an_amount():
    from foundry.finance_requirement_support import NATIVE_METRICS
    from foundry.finance_requirements import _closed_metric_key

    exempt = [metric for metric in NATIVE_METRICS if _closed_metric_key({'metric': metric}) is None]

    assert exempt == ['ratio']
    # A price and a volume named together is the price-quantity bridge, which engine closure or a recipe answers.
    for label in ('price_quantity', 'price_volume', 'sales_price_volume', 'price_volume_mix', '价量分析'):
        assert _closed_metric_key({'metric': label}) == 'price_quantity', label


def test_a_price_quantity_item_is_offered_the_engine_bridge_and_only_the_engine_bridge_closes_it(analysis):
    """price_quantity is the price-quantity bridge (NATIVE_METRICS). Its support report named the bridge while
    accepting a plain cited row; the guidance now names the bridge and the recipe, and a python copy of the
    engine's bridge still does not answer."""
    requirement = _require_pq(analysis, metric='price_quantity', dimensions={'product': '商品A'})
    support = requirement['support']['items'][0]
    engine = _pq_run(analysis)
    record = _new(analysis.task, engine='python', execution_status='succeeded', output_hash='pq-python-copy',
                  bindings=engine['bindings'], finance_scope=engine['finance_scope'], result=engine['result'])
    script = analysis._write(analysis._object_path('runs', record['id']), record)

    def check(run):
        return _item(check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                   'claims': _pq_claims(run)}))

    offered = {*support['accepted_evidence'], *(path['path'] for path in support.get('blocked_evidence', []))}
    assert 'cited_result_row' not in offered
    assert {'price_quantity_bridge', 'evidence_recipe'} <= offered
    assert {part.split(' (')[0] for part in support['evidence'].split(' / ')} <= offered
    assert check(script)['status'] != 'answered'
    answered = check(engine)
    assert answered['status'] == 'answered'
    assert {location['evidence']['evidence_basis'] for location in answered['locations']} == {'engine_closed'}


QUANTITIES_AND_RATIOS_OF_AMOUNTS = ['sales_volume', 'sales_units', 'sales_headcount', 'floor_area', '销售面积', '销售数量',
                                    'revenue_growth_rate', 'price_change_ratio', '价格变动率', 'profit_margin_pct']


@pytest.mark.parametrize('label', QUANTITIES_AND_RATIOS_OF_AMOUNTS)
def test_quantities_and_ratios_of_amounts_keep_the_phase_1_script_rule(analysis, tmp_path, label):
    """Opposite direction: a quantity that sales qualifies, an area, and any ratio (decision 4) stay exempt."""
    case = _label_case(analysis, tmp_path, label)

    assert _item(check_requirements(analysis, case.base))['status'] == 'answered'


def test_a_cited_script_estimate_without_a_recipe_is_told_how_to_declare_its_grain(analysis, tmp_path):
    """Huachen revenue_1_8/profit_1_8 regional budgets: the script emits 区域全年预算 × 进度率 and cites it.
    No archived cell holds the value, yet the message and the fixup only offered a direct/sum/diff recipe;
    the grain_basis route that reaches the spec outcome appeared only after a wrong turn."""
    case = _estimate_case(analysis, tmp_path, declare=False, cite_estimate=False)
    claims = [*case.spec['claims'], _claim(case.run, row=3, column='value', value='112860.000')]
    item = _item(check_requirements(analysis, {**case.spec, 'claims': claims}))
    fixup = next(f for f in item['fixups'] if f.get('reason') == 'cited_result_not_counted')
    message = _unanswered_message(item)

    assert item['uncounted_grains'] == [{'organization': '华东区域', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8',
                                         'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']}]
    assert [cell['row'] for cell in fixup['evidence_recipe_cells']] == [3]
    assert fixup['if_source_lacks_value']['field'] == 'grain_basis'
    assert 'grain_basis' in message and 'factor_reproducible' in message

    # Following it: declared an estimate with a factor recipe, the grain reaches `estimated` (never answered)…
    record = case.requirement
    declared = save_requirements(analysis, spec(
        question=record['question'], scope=record['scope'], bindings=record['bindings'], parent_id=record['id'],
        items=[{**record['items'][0], 'grain_basis': [
            {'basis': 'estimate', 'organizations': ['华东区域'], 'scenarios': ['budget_1_8'],
             'method': '区域全年收入预算 × 集团1-8月收入预算进度'}]}]))
    estimate = {**_recipe(case.budget, '05·区域预算分解', 'C5', case.run, 3, recipe_id='east_budget_estimate'),
                'factor_recipe_id': 'phasing', 'business_key': {'metric_key': 'revenue', 'period': '2026-01:2026-08'}}
    estimated = _item(check_requirements(analysis, {**case.spec, 'requirements_id': declared['id'], 'claims': claims,
                                                    'evidence_recipes': [*case.spec['evidence_recipes'], estimate]}))
    assert estimated['status'] == 'estimated'
    assert estimated['awaiting_manager'] == ['estimate_requires_acceptance']

    # …and declared non-reproducible, it waits for the manager.
    manager = save_requirements(analysis, spec(
        question=record['question'], scope=record['scope'], bindings=record['bindings'], parent_id=declared['id'],
        items=[{**record['items'][0], 'grain_basis': [
            {'basis': 'estimate', 'organizations': ['华东区域'], 'scenarios': ['budget_1_8'], 'method': '预算 × 62.20%',
             'factor_reproducible': False, 'reason': '系数须先相减再相除，现有规则写不出'}]}]))
    pending = _item(check_requirements(analysis, {**case.spec, 'requirements_id': manager['id'], 'claims': claims}))
    assert pending['status'] == 'pending'
    assert pending['awaiting_manager'] == ['estimate_factor_not_reproducible']


def test_a_grain_whose_cited_value_the_source_states_is_not_offered_grain_basis(analysis, monthly):
    """Opposite direction: a rounded run value, or a recipe on a snapshot outside the bindings, shows the source
    has the number; the fix is full precision or the bound snapshot, never declaring the grain an estimate."""
    rows = [REVENUE_ROWS[0], {**REVENUE_ROWS[1], 'value': '41469.63'}]
    rounded_run = _script_run(analysis, monthly.datasets, rows, suffix='rounded-hint')
    rounded = _item(_check(analysis, monthly, run=rounded_run, claims=[
        _claim(rounded_run, row=0, column='value', value='44163.6526'), _claim(rounded_run, row=1, column='value', value='41469.63')],
        recipes=[_recipe(monthly.budget, '01·年度预算总表', 'I12', rounded_run, 0, recipe_id='budget'),
                 _recipe(monthly.close, '04·合并利润表', 'B5', rounded_run, 1, scale='0.0001', recipe_id='actual')]))
    outside = _item(_check(analysis, monthly, recipes=[
        monthly.good[0], _recipe(monthly.outside, '04·合并利润表', 'B5', monthly.run, 1, scale='0.0001', recipe_id='outside')]))

    for item, reason in ((rounded, 'recipe_failed_precision'), (outside, 'recipe_source_outside_bindings')):
        assert item['uncounted_grains'][0]['reasons'] == [reason]
        assert not any(fixup.get('if_source_lacks_value') for fixup in item['fixups'])
        assert 'grain_basis' not in _unanswered_message(item)


def _float_estimate_case(analysis, tmp_path, *, factor_value, estimate_value, source=180576, left=344487.0552,
                         right=527999.9999):
    """Huachen revenue_1_8 East budget: 05!C5 × (Σ01!B12:I12 ÷ 01!N12), the factor written as a ratio recipe."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    book = _workbook(analysis, tmp_path, 'budget', {'S': {'F5': source, 'G1': left, 'G2': right}})
    requirement = save_requirements(analysis, spec(
        scope={'currency': 'CNY', 'unit': '万元'}, bindings={'budget': book['id']},
        items=[{'id': 'revenue_1_8', 'metric': 'revenue', 'scenarios': ['budget_1_8'], 'requires_drilldown': False,
                'grain_basis': [{'basis': 'estimate', 'scenarios': ['budget_1_8'], 'method': '区域全年预算 × 进度'}]}]))
    rows = [{'metric_key': 'revenue', 'scenario': 'budget_1_8', 'period': '2026-01:2026-08', 'value': estimate_value,
             'currency': 'CNY', 'unit': '万元'},
            {'metric_key': 'revenue', 'scenario': 'progress', 'period': '2026-01:2026-08', 'value': factor_value}]
    run = _script_run(analysis, {'budget': book}, rows, suffix='float-' + factor_value)

    def cell(reference):
        return {'dataset_id': book['id'], 'source_hash': book['source_hash'], 'sheet': 'S', 'range': reference}

    key = {'metric_key': 'revenue', 'period': '2026-01:2026-08'}
    recipes = [{'id': 'factor', 'kind': 'ratio', 'claim': {'run_id': run['id'], 'row': 1, 'column': 'value'},
                'left': cell('G1'), 'right': cell('G2'), 'business_key': key},
               {'id': 'estimate', 'kind': 'direct', **cell('F5'), 'factor_recipe_id': 'factor', 'business_key': key,
                'claim': {'run_id': run['id'], 'row': 0, 'column': 'value'}}]
    return SimpleNamespace(recipes=recipes, spec={
        'requirements_id': requirement['id'], 'run_ids': [run['id']], 'evidence_recipes': recipes,
        'claims': [_claim(run, row=0, column='value', value=estimate_value)]})


def test_a_float_computed_factor_and_estimate_get_the_full_precision_hint(analysis, tmp_path):
    """A python script computes the factor and the estimate in float. Its repr is not a decimal rounding of
    the exact value, so the ratio failed with no precision_hint, the estimate failed as plain recipe_failed,
    and the message never said to keep full precision although precision was the only cause."""
    from decimal import Decimal

    from foundry.financial_evidence import _rounding_hint

    factor = 344487.0552 / 527999.9999
    case = _float_estimate_case(analysis, tmp_path, factor_value=repr(factor), estimate_value=repr(180576 * factor))
    report = evaluate_evidence_recipes(analysis, case.recipes)
    results = {result['recipe_id']: result for result in report['results']}
    item = _item(check_requirements(analysis, case.spec))

    assert _rounding_hint(Decimal('117814.5729007133660796805618'), Decimal(repr(180576 * factor)))
    assert results['factor']['status'] == 'mismatch'
    assert results['factor']['precision_hint'] == 'full_precision_required'
    assert results['estimate']['status'] == 'unreadable'
    assert results['estimate']['precision_hint'] == 'full_precision_required'
    assert all('完整精度' in issue['message'] for issue in report['issues'])
    assert item['locations'][0]['evidence']['not_counted_reason'] == 'recipe_failed_precision'
    assert '保存完整精度' in _unanswered_message(item)

    # Stored at full precision, the same recipes reach `estimated`.
    exact = Decimal('344487.0552') / Decimal('527999.9999')
    other = AnalysisStore(TaskStore(tmp_path / 'full-var').create(title='全精度'))
    full = _float_estimate_case(other, tmp_path / 'full', factor_value=str(exact), estimate_value=str(180576 * exact))
    assert _item(check_requirements(other, full.spec))['status'] == 'estimated'


def test_a_value_off_by_more_than_float_error_gets_no_precision_hint(analysis, tmp_path):
    """Opposite direction: the hint only explains a precision loss; a wrong factor is a plain failure."""
    from decimal import Decimal

    from foundry.financial_evidence import _rounding_hint

    factor = 344487.0552 / 527999.9999
    case = _float_estimate_case(analysis, tmp_path, factor_value='0.6524376046690999', estimate_value=repr(180576 * factor))
    results = {result['recipe_id']: result for result in evaluate_evidence_recipes(analysis, case.recipes)['results']}
    item = _item(check_requirements(analysis, case.spec))

    assert not _rounding_hint(Decimal('117814.5729007133660796805618'), Decimal('117814.5729008'))
    # Seventeen digits like a float repr, but 1e-9 away: about 70 ulps, not float noise.
    assert not _rounding_hint(Decimal('117814.5729007133660796805618'), Decimal('117814.57290171336'))
    assert not _rounding_hint(Decimal('0.6524376046690222736115572488'), Decimal('0.6524376046690999'))
    assert 'precision_hint' not in results['factor']
    assert 'precision_hint' not in results['estimate']
    assert item['locations'][0]['evidence']['not_counted_reason'] == 'recipe_failed'


def _aggregate_case(tmp_path, metric):
    """A JSON dataset bound to the requirement and a server-side structured_aggregate of 华东's amount."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    task = TaskStore(tmp_path / f'{metric}-var').create(title='汇总')
    analysis = AnalysisStore(task)
    path = tmp_path / f'{metric}.json'
    path.write_text(json.dumps([{'region': '华东', 'amount': '120.50', 'currency': 'CNY', 'unit': '万元'},
                                {'region': '华南', 'amount': '80.25', 'currency': 'CNY', 'unit': '万元'}],
                               ensure_ascii=False), encoding='utf-8')
    dataset = analysis.add_dataset(path, name='actual')
    requirement = save_requirements(analysis, {'question': f'华东{metric}', 'bindings': {'actual': dataset['id']},
                                               'items': [{'id': 'east', 'metric': metric, 'requires_drilldown': True}]})
    definition = analysis.save_analysis({'question': f'华东{metric}', 'engine': 'structured_aggregate',
                                         'bindings': {'actual': dataset['id']}, 'aggregate_plan': {
                                             'dataset_alias': 'actual', 'group_by': ['region'],
                                             'filters': [{'field': 'region', 'op': 'eq', 'value': '华东'}],
                                             'measures': [{'name': metric, 'field': 'amount', 'aggregation': 'sum'}],
                                             'dedupe': {'policy': 'none'}}})
    run = analysis.run_analysis(definition['id'])
    claim = {'basis': 'calculation', 'run_id': run['id'], 'row': 0, 'column': metric, 'value': run['result']['rows'][0][metric]}
    return SimpleNamespace(analysis=analysis, service=FinanceStore(task), dataset=dataset, requirement=requirement,
                           run=run, claim=claim, spec={'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                       'claims': [claim]})


def test_a_structured_aggregate_answers_an_amount_outside_the_pnl_lines(tmp_path):
    """A server-side structured_aggregate is not a script: its cell answered other_income on main and
    drilldown_fact verifies it. The inverted gate called it script output, told the writer 只有脚本输出, and
    sent it to a verify_source step that could not fix anything."""
    case = _aggregate_case(tmp_path, 'other_income')
    before = _item(check_requirements(case.analysis, case.spec))

    assert before['status'] == 'answered'
    assert before['locations'][0]['evidence']['evidence_basis'] == 'aggregate_output'
    assert 'aggregate_output' in [path['path'] for path in before['evidence_paths']['accepted']]
    assert [fixup['code'] for fixup in before['fixups']] == ['verify_source']

    case.service.drilldown_fact({'run_id': case.run['id'], 'row': 0, 'column': 'other_income'})
    after = check_requirements(case.analysis, case.spec)
    assert _item(after)['provenance_status'] == 'verified'
    assert after['coverage']['status'] == 'pass'
    draft = case.service.save_explanation_draft({'body': '华东其他收益 120.5 万元。', 'run_ids': [case.run['id']],
                                                 'claims': case.spec['claims']})
    assert draft['completion']['status'] == 'complete'
    support = case.requirement['support']['items'][0]
    assert 'aggregate_output' in support['accepted_evidence']


def test_a_script_copy_of_an_aggregate_or_an_aggregated_pnl_line_is_still_not_counted(tmp_path):
    """Opposite direction: a python copy of the aggregate cell is script output, and a revenue/profit/cost/expense
    amount still needs engine closure or a recipe (decision 1), aggregate or not."""
    case = _aggregate_case(tmp_path, 'other_income')
    copy = _script_run(case.analysis, {'actual': case.dataset}, case.run['result']['rows'], suffix='aggregate-copy')
    script = _item(check_requirements(case.analysis, {**case.spec, 'run_ids': [copy['id']],
                                                      'claims': [{**case.claim, 'run_id': copy['id']}]}))
    assert script['status'] == 'not_applicable'
    assert script['locations'][0]['evidence']['not_counted_reason'] == 'script_output_without_recipe'

    # The price-quantity bridge is closed only by the finance engine, so an aggregate named after it is not it.
    for metric in ('revenue', 'price_quantity', 'price_volume'):
        aggregated = _aggregate_case(tmp_path / metric, metric)
        item = _item(check_requirements(aggregated.analysis, aggregated.spec))
        assert item['status'] == 'not_applicable', metric
        assert item['locations'][0]['evidence']['evidence_basis'] == 'aggregate_output'
        assert item['locations'][0]['evidence']['not_counted_reason'] == 'aggregate_output_without_closure'
        assert 'aggregate_output' not in [path['path'] for path in item['evidence_paths']['accepted']]
        assert '只有脚本输出' not in _unanswered_message(item)
        assert [fixup['code'] for fixup in item['fixups'] if fixup['code'] == 'verify_source'] == []


def _table_xlsx_case(analysis, tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = '利润表'
    sheet['A1'], sheet['B1'] = '项目', '本年累计'
    sheet['A2'], sheet['B2'] = '营业收入', 3256440000
    source = tmp_path / 'close.xlsx'
    book.save(source)
    book.close()
    dataset = analysis.add_dataset(source, name='close')  # one sheet, the default mode: filed as a table
    requirement = save_requirements(analysis, {'question': '1-8月收入', 'scope': {'currency': 'CNY', 'unit': '万元'},
                                               'bindings': {'close': dataset['id']},
                                               'items': [{'id': 'revenue_1_8', 'metric': 'revenue', 'periods': ['2026-01:2026-08']}]})
    rows = [{'metric_key': 'revenue', 'period': '2026-01:2026-08', 'value': '325644.0000', 'unit': '万元', 'currency': 'CNY'}]
    run = _script_run(analysis, {'close': dataset}, rows, suffix='table-xlsx')
    return SimpleNamespace(dataset=dataset, requirement=requirement, run=run,
                           spec={'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                 'claims': [_claim(run, row=0, column='value', value='325644.0000')]},
                           recipe=_recipe(dataset, '利润表', 'B2', run, 0, scale='0.0001'))


def test_a_single_sheet_xlsx_filed_as_a_table_offers_the_recipe_path_that_answers(analysis, tmp_path):
    """The recipe path was reported blocked (no_workbook_source) for an XLSX filed as a table, while a recipe on
    that file answers: evaluate_evidence_recipes reads any archived XLSX bytes."""
    case = _table_xlsx_case(analysis, tmp_path)
    support = case.requirement['support']['items'][0]
    item = _item(check_requirements(analysis, case.spec))
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')
    message = _unanswered_message(item)

    assert case.dataset['kind'] == 'table'
    assert support['accepted_evidence'] == ['evidence_recipe']
    assert 'no_workbook_source' not in json.dumps(support.get('blocked_evidence', []))
    assert fixup['accepted_evidence'] == ['evidence_recipe']
    assert 'no_workbook_source' not in json.dumps(fixup.get('blocked_evidence', []))
    assert '没有可复算的归档工作簿' not in message
    assert 'evidence_recipe' in message
    assert _item(check_requirements(analysis, {**case.spec, 'evidence_recipes': [case.recipe]}))['status'] == 'answered'


def test_a_csv_or_json_binding_still_reports_the_recipe_path_blocked(analysis, tmp_path):
    """Opposite direction: without archived XLSX bytes no recipe can read a cell."""
    path = tmp_path / 'rev.json'
    path.write_text(json.dumps([{'organization': '华东', 'period': '2026-08', 'revenue': '120.5'}], ensure_ascii=False),
                    encoding='utf-8')
    dataset = analysis.add_dataset(path, name='rev')
    requirement = save_requirements(analysis, {'question': '8月华东收入', 'bindings': {'rev': dataset['id']},
                                               'items': [{'id': 'rev_08', 'metric': 'revenue'}]})
    blocked = requirement['support']['items'][0]['blocked_evidence']

    assert ('evidence_recipe', ['no_workbook_source']) in [(path['path'], path['blockers']) for path in blocked]


def test_a_scope_level_an_earlier_version_dropped_is_dropped_again_not_refused(analysis):
    """The scope card kept the legacy drilldown it loaded at mount and resent it on the next save. The parent
    version had already dropped it, so the save was refused and the manager's edit was lost."""
    legacy = _new(analysis.task, question='华宸 1-8 月', scope={'ledger': 'L1', 'unit': '万元', 'drilldown': '城市公司'},
                  bindings={}, context_id=None, parent_id=None, removed_item_ids=[], change_reason='', selection=None,
                  items=[{'id': 'profit', 'metric': 'profit', 'label': 'profit', 'dimensions': {}, 'requires_drilldown': True}])
    analysis._write(analysis._object_path('requirements', legacy['id']), legacy)
    first = save_requirements(analysis, spec(scope={**legacy['scope'], 'period': '2026-08'}, parent_id=legacy['id'],
                                             items=legacy['items']))
    second = save_requirements(analysis, spec(scope={**legacy['scope'], 'period': '2026-08', 'currency': 'CNY'},
                                              parent_id=first['id'], items=first['items']))
    third = save_requirements(analysis, spec(scope={**second['scope'], 'drilldown': '城市公司'},
                                             parent_id=second['id'], items=second['items']))

    assert first['scope'] == {'ledger': 'L1', 'unit': '万元', 'period': '2026-08'}
    assert second['scope'] == {'ledger': 'L1', 'unit': '万元', 'period': '2026-08', 'currency': 'CNY'}
    assert [warning['code'] for warning in second['authoring_warnings']] == ['hierarchy_scope_dropped']
    # Two versions after the drop, a stale copy is still recognised as the legacy level.
    assert 'drilldown' not in third['scope']
    assert [warning['code'] for warning in third['authoring_warnings']] == ['hierarchy_scope_dropped']

    # Opposite direction: another value, or a level no earlier version had, is newly written and refused.
    for scope in ({**third['scope'], 'drilldown': '区域'}, {**third['scope'], 'level': '城市公司'}):
        with pytest.raises(FoundryError) as refused:
            save_requirements(analysis, spec(scope=scope, parent_id=third['id'], items=third['items']))
        assert refused.value.details['code'] == 'requirement_scope_not_row_filter'


def _context_with_level(tmp_path, level):
    """A finance context whose scope holds a hierarchy level (finance_context_save accepts any key)."""
    task = TaskStore(tmp_path / 'ctx-var').create(title='口径')
    service = FinanceStore(task)
    path = tmp_path / 'g1.json'
    path.write_text(json.dumps([{'ledger': 'L1', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY',
                                 'unit': '万元', 'management_account': 'expense', 'amount': '20'}]), encoding='utf-8')
    dataset = service.analysis.add_dataset(path, name='g1')
    scope = {'ledger': 'L1', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元', **level}
    context = service.save_context({'bindings': {'actual': dataset['id']}, 'scopes': {'actual': scope}})
    return service, context


EXPENSE_ITEM = {'id': 'expense', 'metric': 'expense', 'label': '费用', 'dimensions': {}, 'requires_drilldown': False}


def test_a_first_save_seeded_from_a_contexts_scope_drops_the_contexts_hierarchy_level(tmp_path):
    """Review round 6: RequirementsPanel seeds its scope from the selected context and resends every key.
    A context whose scope held drilldown=城市公司 made the first save refused as a newly written level, and
    the panel has no field to remove it; analysis_requirements_save with only context_id fell back to the
    same scope and was refused too. A level the context itself holds is carried over, not written."""
    service, context = _context_with_level(tmp_path, {'drilldown': '城市公司', 'granularity': '区域'})
    panel = {'question': '解释费用', 'scope': dict(context['scopes']['actual']), 'bindings': context['bindings'],
             'context_id': context['id'], 'items': [EXPENSE_ITEM]}

    first = service.analysis_requirements_save(panel)
    fallback = service.analysis_requirements_save({'question': '解释费用', 'context_id': context['id'],
                                                   'parent_id': first['id'], 'items': [EXPENSE_ITEM]})

    for saved in (first, fallback):
        assert 'drilldown' not in saved['scope']
        # granularity only describes the analysis and is kept.
        assert saved['scope']['granularity'] == '区域'
        assert saved['scope']['organization'] == '华东'
        warning = next(w for w in saved['authoring_warnings'] if w['code'] == 'hierarchy_scope_dropped')
        assert warning['keys'] == {'drilldown': '城市公司'}
        assert '财务口径' in warning['message']


def test_a_level_the_context_does_not_hold_is_still_refused(tmp_path):
    """Opposite direction: only the context's own (key, value) is carried over. Another value, another level,
    a context without levels, or a save with no context still refuse a hierarchy level written into scope."""
    service, context = _context_with_level(tmp_path, {'drilldown': '城市公司'})
    plain_service, plain = _context_with_level(tmp_path / 'plain', {})
    cases = [
        (service, {'context_id': context['id'], 'scope': {**context['scopes']['actual'], 'drilldown': '项目'}}),
        (service, {'context_id': context['id'], 'scope': {**context['scopes']['actual'], 'level': '城市公司'}}),
        (plain_service, {'context_id': plain['id'], 'scope': {**plain['scopes']['actual'], 'drilldown': '城市公司'}}),
        (service, {'bindings': context['bindings'], 'scope': dict(context['scopes']['actual'])}),
    ]
    for store, extra in cases:
        with pytest.raises(FoundryError) as refused:
            store.analysis_requirements_save({'question': '解释费用', 'items': [EXPENSE_ITEM], **extra})
        assert refused.value.details['code'] == 'requirement_scope_not_row_filter'
        assert store.analysis._list('requirements') == []


def test_the_panel_leaves_out_exactly_the_scope_levels_save_refuses():
    """RequirementsPanel keeps its own copy of the refused scope levels for the context seed; it must not drift."""
    import re

    from foundry.finance_requirements import SCOPE_REFUSED_HIERARCHY_KEYS

    panel = (ROOT / 'app' / 'src' / 'views' / 'analysis' / 'RequirementsPanel.tsx').read_text(encoding='utf-8')
    listed = re.search(r'contextOnlyScopeLevels = new Set\(\[([^\]]*)\]\)', panel).group(1)
    assert set(re.findall(r"'([^']+)'", listed)) == set(SCOPE_REFUSED_HIERARCHY_KEYS)
    assert 'granularity' not in listed


def test_tool_descriptions_say_engine_paths_need_bound_rows():
    """Round 6: the engine paths answer only when the bound snapshots give the engine rows; the tools say so,
    and say that contexts or runs on the confirmed table snapshots do not count."""
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    preset = (ROOT / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')['description']

    assert 'bindings_without_engine_rows' in tools and 'bindings_without_engine_rows' in draft
    assert '在其他快照上保存财务口径或运行都不计入' in tools
    assert 'never counts (other bindings)' in draft
    assert '引擎路径交经理' in preset
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(
        encoding='utf-8') == preset


def test_tool_descriptions_name_the_aggregate_and_price_quantity_paths_and_exact_decimals():
    """Round 4 changed what answers: structured aggregates answer amounts outside the four P&L lines, the
    price-quantity bridge answers price_quantity, and float-computed run values fail like rounded ones."""
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    preset = (ROOT / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')['description']

    for text in (tools, draft, preset):
        assert 'structured_aggregate' in text
        assert 'price_quantity' in text
        assert 'revenue_by_area' in text
    assert '不要用二进制浮点数' in tools and '不要用二进制浮点数' in preset
    assert 'not binary floats' in draft
    assert 'drilldown_fact 只核查 finance 引擎和 structured_aggregate 的行' in tools
    assert 'drilldown_fact only verifies finance-engine and structured_aggregate rows' in draft
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(
        encoding='utf-8') == preset


# --- round 5: a finance run on several bound inputs ------------------------------------------------

SCENARIO_SCOPE = {'ledger': 'L1', 'organization': 'O1', 'currency': 'CNY', 'unit': '万元'}


def _scenario_case(tmp_path, kind, aliases, *, scopes=None, requirement_scope=None):
    """A finance context binding `aliases`, a requirement saved on it (the context's scope unless
    `requirement_scope`), and one finance_scenario_run of `kind` with every engine-amount cell cited:
    closing_cash for cash_13_weeks, open_amount for receivables_aging."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    service = FinanceStore(TaskStore(tmp_path / 'var').create(title=kind))
    data = {
        'receipts': [{'id': 'R1', 'date': '2026-09-25', 'amount': '100'}],
        'payments': [{'id': 'P1', 'date': '2026-09-28', 'amount': '60'}],
        'invoices': [{'id': 'I1', **SCENARIO_SCOPE, 'issue_date': '2026-08-01', 'due_date': '2026-08-01',
                      'amount': '100'}],
        'activity': [{'id': 'A1', 'invoice_id': 'I1', 'kind': 'payment', **SCENARIO_SCOPE,
                      'effective_date': '2026-08-20', 'amount': '40'}],
    }
    bindings = {}
    for alias in aliases:
        path = tmp_path / f'{alias}.json'
        path.write_text(json.dumps(data[alias], ensure_ascii=False), encoding='utf-8')
        bindings[alias] = service.analysis.add_dataset(path, name=alias)['id']
    context = service.save_context({'bindings': bindings,
                                    'scopes': scopes or {alias: dict(SCENARIO_SCOPE) for alias in bindings}})
    column = 'closing_cash' if kind == 'cash_13_weeks' else 'open_amount'
    requirement = service.analysis_requirements_save({
        'context_id': context['id'], 'question': column, 'items': [{'id': 'amount', 'metric': column}],
        **({'scope': requirement_scope} if requirement_scope else {})})
    inputs = ({'opening_cash': '50', 'start_date': '2026-09-24', 'actual_cutoff': '2026-09-23'}
              if kind == 'cash_13_weeks' else {'as_of': '2026-09-05'})
    scenario = service.save_scenario({'context_id': context['id'], 'kind': kind, 'label': kind,
                                      'inputs': {**inputs, 'scope': SCENARIO_SCOPE}})
    run = service.run_scenario({'scenario_id': scenario['id']})
    claims = [{'basis': 'calculation', 'run_id': run['id'], 'row': index, 'column': column, 'value': row[column]}
              for index, row in enumerate(run['result']['rows']) if row.get(column) not in (None, '')]
    return SimpleNamespace(service=service, analysis=service.analysis, run=run, requirement=requirement,
                           claims=claims, column=column,
                           spec={'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims})


@pytest.mark.parametrize('kind, aliases', [
    ('cash_13_weeks', ('receipts',)), ('cash_13_weeks', ('receipts', 'payments')),
    ('receivables_aging', ('invoices',)), ('receivables_aging', ('invoices', 'activity')),
])
def test_a_finance_run_on_every_bound_input_in_the_requirement_scope_answers_its_engine_amount(tmp_path, kind, aliases):
    """The guidance names finance_scenario_run closing_cash/open_amount, but a run binding both inputs
    (receipts + payments, invoices + activity) has a finance_scope keyed by both aliases, and the matcher
    refused every run with more than one bound scope: the cited cells stayed pending as 没有已引用的结果行
    while the message repeated the same path."""
    case = _scenario_case(tmp_path, kind, aliases)
    result = check_requirements(case.analysis, case.spec)
    item = _item(result)

    assert case.run['engine'] == 'finance' and sorted(case.run['finance_scope']) == sorted(aliases)
    assert 'engine_output' in case.requirement['support']['items'][0]['accepted_evidence']
    assert case.claims
    assert item['status'] == 'answered'
    assert len(item['locations']) == len(case.claims)
    assert {location['evidence']['evidence_basis'] for location in item['locations']} == {'engine_output'}
    assert result['coverage']['status'] == 'pass'

    facts = case.service.prepare_explanation({'run_ids': [case.run['id']]})['facts']
    body = '、'.join('{{fact:%s}}' % fact['id'] for fact in facts if fact.get('column') == case.column) + '。'
    draft = case.service.save_explanation_draft({'title': case.column, 'body': body, 'run_ids': [case.run['id']],
                                                 'requirements_id': case.requirement['id']})
    assert _item(draft['explanation_check']['requirements'])['status'] == 'answered'
    assert 'requirement_unanswered' not in [issue.get('code') for issue in draft['explanation_check']['issues']]


@pytest.mark.parametrize('payments, requirement_scope', [
    ({**SCENARIO_SCOPE, 'unit': '元'}, SCENARIO_SCOPE),
    ({**SCENARIO_SCOPE, 'ledger': 'L2'}, SCENARIO_SCOPE),
    (SCENARIO_SCOPE, {**SCENARIO_SCOPE, 'unit': '元'}),
])
def test_a_finance_run_with_a_bound_input_outside_the_requirement_scope_is_cited_but_not_counted(
        tmp_path, payments, requirement_scope):
    """Opposite direction: every bound input must lie in the requirement scope. One input in another unit or
    ledger (or a requirement in another unit than all of them) leaves the output's scope unproven, so the
    cells do not count; they are reported as cited but not counted with the scope the run needs (ruling
    (a)), never as uncited."""
    scopes = {'receipts': dict(SCENARIO_SCOPE), 'payments': dict(payments)}
    case = _scenario_case(tmp_path, 'cash_13_weeks', ('receipts', 'payments'), scopes=scopes,
                          requirement_scope=requirement_scope)
    item = _item(check_requirements(case.analysis, case.spec))

    assert case.claims
    assert item['status'] == 'pending'
    assert len(item['locations']) == len(case.claims)
    assert {location['evidence']['not_counted_reason'] for location in item['locations']} == {'run_scope_differs'}
    assert 'missing_grains' not in item
    assert item['uncounted_grains'][0]['reasons'] == ['run_scope_differs']
    fixup = next(fixup for fixup in item['fixups'] if fixup['code'] == 'rescope_run')
    assert fixup['required_scope'] == requirement_scope
    assert fixup['runs'] == [{'run_id': case.run['id'], 'finance_scope': scopes}]
    # A finance run's inputs are fixed by rerunning, not by row fields: no row-field advice for it.
    assert 'row_field_gaps' not in item
    message = _unanswered_message(item)
    assert '没有已引用的结果行' not in message
    assert '已引用了结果但未计入' in message and 'finance_scope' in message


def test_a_draft_that_policy_7_left_pending_on_a_two_input_finance_run_is_checked_again(tmp_path):
    """Under completion policy 7 a finance run on two bound inputs never matched a scoped requirement, so the
    draft stayed pending. The rule changed, so a resend must not replay that verdict."""
    from foundry.analysis import _hash
    from foundry.finance_completion import COMPLETION_POLICY_VERSION
    from foundry.fsutil import write_json_atomic

    case = _scenario_case(tmp_path, 'cash_13_weeks', ('receipts', 'payments'))
    facts = case.service.prepare_explanation({'run_ids': [case.run['id']]})['facts']
    request = {'title': '现金', 'run_ids': [case.run['id']], 'requirements_id': case.requirement['id'],
               'body': '、'.join('{{fact:%s}}' % fact['id'] for fact in facts if fact.get('column') == 'closing_cash')}
    first = case.service.save_explanation_draft(request)
    assert first['check_policy_version'] == COMPLETION_POLICY_VERSION
    path = case.analysis._object_path('drafts', first['id'])
    stored = {key: value for key, value in json.loads(path.read_text()).items() if key != '_integrity_hash'}
    check = stored['explanation_check']
    old = {**check, 'status': 'needs_attention', 'requirements': {
        **check['requirements'], 'coverage': {'status': 'needs_attention'}, 'original_requirements_completed': False,
        'items': [{**item, 'status': 'pending', 'locations': []} for item in check['requirements']['items']]}}
    record = {**stored, 'check_policy_version': 7, 'explanation_check': old, 'quality': old}
    write_json_atomic(path, {**record, '_integrity_hash': _hash(record)})

    again = case.service.save_explanation_draft(request)

    assert again.get('replayed') is not True
    assert _item(again['explanation_check']['requirements'])['status'] == 'answered'


def test_bound_scopes_keyed_by_alias_match_only_when_every_one_is_in_the_requirement_scope():
    scope = {'ledger': 'L1', 'organization': 'O1', 'unit': '万元'}
    row = {'closing_cash': '90', 'ledger': 'L1', 'organization': 'O1', 'unit': '万元'}

    def run(**scopes):
        return {'finance_scope': scopes}

    assert _scope_matches(run(receipts=scope), row, scope)
    assert _scope_matches(run(receipts=scope, payments=scope), row, scope)
    assert not _scope_matches(run(receipts=scope, payments={**scope, 'unit': '元'}), row, scope)
    assert not _scope_matches(run(receipts=scope, payments=scope), {**row, 'organization': 'O2'}, scope)
    assert not _scope_matches(run(receipts={**scope, 'ledger': 'L2'}, payments={**scope, 'ledger': 'L2'}), row, scope)
    # Several bound scopes match exactly when each would match as the run's only bound scope.
    others = [scope, {**scope, 'unit': '元'}, {'ledger': 'L1', 'organization': 'O1'}, {'unit': '万元'}, {}]
    for other in others:
        assert _scope_matches(run(receipts=scope, payments=other), row, scope) == _scope_matches(
            run(payments=other), row, scope)
    # A comparison run's inputs named other than actual/baseline stay ambiguous, as on main.
    variance = {**run(pq=scope, other=scope), 'result': {'domain': 'foundry.finance.variance.v1'}}
    assert not _scope_matches(variance, row, scope)
    assert _scope_matches({**run(pq=scope), 'result': {'domain': 'foundry.finance.variance.v1'}}, row, scope)


def test_tool_descriptions_say_every_bound_input_of_a_finance_run_must_lie_in_the_requirement_scope():
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')['description']

    assert 'every bound input' in draft and 'rescope_run' in draft
    assert '每个绑定别名的口径' in tools and 'rescope_run' in tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools


# --- review fixes, round 7 (PR #23) -----------------------------------------------------------------


def _second_value_request(analysis, case, rows, recipes_for, *, suffix):
    run = _script_run(analysis, case.datasets, rows, suffix=suffix, requirements_id=case.requirement['id'],
                      requirements_semantic_fingerprint=case.requirement['semantic_fingerprint'])
    claims = [_claim(run, row=index, column='value', value=row['value']) for index, row in enumerate(rows)]
    recipes = [_recipe(dataset, sheet, cell, run, row, recipe_id=f'r{row}', **extra)
               for row, (dataset, sheet, cell, extra) in recipes_for.items()]
    return run, {'requirements_id': case.requirement['id'], 'run_ids': [run['id']], 'claims': claims,
                 'evidence_recipes': recipes}


def test_a_script_only_value_cited_beside_a_counted_one_keeps_the_grain_unanswered(analysis, monthly):
    """Round 7: revenue_2026_08's actual grain was answered by 04!B5 × 0.0001 while the draft also cited a
    fabricated 52000.0000 for the same grain from a script row with no recipe. The grain stayed answered,
    coverage and provenance passed, and the completion saved complete although the body said 52000.0000.
    Every value the draft cites for a grain must count."""
    fake = {**REVENUE_ROWS[1], 'value': '52000.0000'}
    run, request = _second_value_request(analysis, monthly, [*REVENUE_ROWS, fake], {
        0: (monthly.budget, '01·年度预算总表', 'I12', {}),
        1: (monthly.close, '04·合并利润表', 'B5', {'scale': '0.0001'})}, suffix='second-value')
    result = check_requirements(analysis, request)
    item = _item(result)

    assert item['status'] == 'pending'
    assert result['coverage']['status'] == 'needs_attention'
    assert result['original_requirements_completed'] is False
    assert [(location['row'], location['status']) for location in item['locations']] == [
        (0, 'answered'), (1, 'answered'), (2, 'not_applicable')]
    assert item['uncounted_grains'] == [{'organization': '集团合并', 'period': '2026-08', 'scenario': 'actual_2026_08',
                                          'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe'],
                                          'counted_cells': 1}]
    assert 'missing_grains' not in item and 'awaiting_manager' not in item
    fixup = next(fixup for fixup in item['fixups'] if fixup['reason'] == 'cited_result_not_counted')
    assert fixup['evidence_recipe_cells'] == [{'run_id': run['id'], 'row': 2, 'column': 'value', 'value': '52000.0000',
                                                'not_counted_reason': 'script_output_without_recipe'}]
    # The source states this grain (another cited cell counts), so declaring it an estimate is no way out.
    assert 'if_source_lacks_value' not in fixup
    message = _unanswered_message(item)
    assert '同一组合另有已计入的引用' in message and 'grain_basis' not in message

    service = FinanceStore(analysis.task)
    saved = service.save_explanation_draft({'title': '8月收入', 'body': '8 月营业收入实际 52000.0000 万元，预算 44163.6526 万元。',
                                            **{key: request[key] for key in ('run_ids', 'claims', 'evidence_recipes',
                                                                              'requirements_id')}})
    assert saved['explanation_check']['checks']['coverage']['status'] == 'needs_attention'
    assert saved['completion']['status'] == 'repair_available'
    assert saved['completion']['original_requirements_completed'] is False

    # Following the fixup literally: drop the value nothing backs, and the counted cells answer the grain.
    kept = check_requirements(analysis, {**request, 'claims': request['claims'][:2]})
    assert _item(kept)['status'] == 'answered'
    assert kept['coverage']['status'] == 'pass'


@pytest.mark.parametrize('lists', [
    {'organizations': ['集团合并'], 'periods': ['2026-08']},
    {'periods': ['2026-08']},
    {},
])
def test_an_item_without_scenarios_needs_every_cited_value_of_its_grain_to_count(analysis, monthly, lists):
    """The same gap on an item without scenario lists: actual and budget fall in one grain, and a recipe on
    the budget cell answered it while the reported actual was script-only. The opposite direction: once
    both cited cells are backed, the item is answered."""
    requirement = save_requirements(analysis, spec(
        parent_id=monthly.requirement['id'], question='8 月营业收入', scope={'ledger': '华宸', 'currency': 'CNY', 'unit': '万元'},
        bindings={alias: dataset['id'] for alias, dataset in monthly.datasets.items()},
        items=[{'id': 'revenue_2026_08', 'metric': 'revenue', 'requires_drilldown': True, **lists}]))
    case = SimpleNamespace(**{**vars(monthly), 'requirement': requirement})
    budget_only = {0: (monthly.budget, '01·年度预算总表', 'I12', {})}
    _script, script_actual = _second_value_request(
        analysis, case, [REVENUE_ROWS[0], {**REVENUE_ROWS[1], 'value': '52000.0000'}], budget_only,
        suffix='no-scenario-' + '-'.join(lists))
    item = _item(check_requirements(analysis, script_actual))

    assert item['status'] != 'answered'
    assert [location['status'] for location in item['locations']] == ['answered', 'not_applicable']
    assert item['uncounted_grains'][0]['counted_cells'] == 1

    _backed, both = _second_value_request(analysis, case, REVENUE_ROWS, {
        **budget_only, 1: (monthly.close, '04·合并利润表', 'B5', {'scale': '0.0001'})},
        suffix='no-scenario-backed-' + '-'.join(lists))
    assert _item(check_requirements(analysis, both))['status'] == 'answered'


def test_two_script_values_for_one_ratio_grain_keep_the_phase_1_ratio_rule(analysis, tmp_path):
    """Opposite direction: a ratio's script value still counts in phase 1 (decision 4), so two cited ratio
    values for one grain leave it answered; only amounts need every cited value backed."""
    book = _workbook(analysis, tmp_path, 'book', {'S': {'B5': 1}})
    requirement = save_requirements(analysis, spec(
        scope={}, bindings={'book': book['id']},
        items=[{'id': 'progress', 'metric': 'ratio', 'periods': ['2026-08'], 'requires_drilldown': False}]))
    rows = [{'metric_key': 'ratio', 'period': '2026-08', 'value': '0.9390'},
            {'metric_key': 'ratio', 'period': '2026-08', 'value': '0.9391'}]
    run = _script_run(analysis, {'book': book}, rows, suffix='ratio-two')
    item = _item(check_requirements(analysis, {
        'requirements_id': requirement['id'], 'run_ids': [run['id']],
        'claims': [_claim(run, row=index, column='value', value=row['value']) for index, row in enumerate(rows)]}))

    assert item['status'] == 'answered'


def test_a_cited_restatement_of_a_counted_number_does_not_unanswer_the_grain(tmp_path):
    """Opposite direction: an explain_variance revenue row closes on its contribution, and a writer who also
    cites that row's amount_change and profit_impact (the same 20, cells with no closure of their own) states
    no new number. Only a cited value no counted cell states keeps the grain open."""
    from foundry.finance_requirements import _matches

    scope = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'}
    rows = {side: [{**scope, 'scenario': side, 'management_account': account, 'amount': amount, 'source_row': index}
                   for index, (account, amount) in enumerate(pairs, start=1)]
            for side, pairs in (('actual', (('revenue', '120'), ('cost', '50'), ('expense', '20'))),
                                ('budget', (('revenue', '100'), ('cost', '40'), ('expense', '10'))))}
    service, context, _bindings = _finance_service_from_rows(
        tmp_path, rows, {side: {**scope, 'scenario': side} for side in rows}, title='restated')
    requirement = service.analysis_requirements_save({'question': '收入差异', 'context_id': context['id'], 'scope': scope,
                                                      'items': [{'id': 'revenue', 'metric': 'revenue',
                                                                 'requires_drilldown': False}]})
    run = service.explain_variance({'context_id': context['id']})
    item_spec = requirement['items'][0]
    cells = [{'basis': 'calculation', 'run_id': run['id'], 'row': index, 'column': column, 'value': value}
             for index, row in enumerate(run['result']['rows']) for column, value in row.items()
             if isinstance(value, str) and _matches(item_spec, row, column, run)]
    item = _item(check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                       'run_ids': [run['id']], 'claims': cells}))

    assert sorted(cell['column'] for cell in cells) == ['amount_change', 'contribution', 'profit_impact']
    assert {location['column']: location['status'] for location in item['locations']} == {
        'amount_change': 'pending', 'contribution': 'answered', 'profit_impact': 'pending'}
    assert item['status'] == 'answered'


def _exact_decimal_estimate(source, *, prec=None, order='factor_first', left='344487.0552', right='527999.9999'):
    """The factor and the estimate as a script computing in exact Decimal writes them."""
    from decimal import Decimal, localcontext

    source, left, right = Decimal(source), Decimal(left), Decimal(right)
    with localcontext() as context:
        if prec:
            context.prec = prec
        factor = left / right
        estimate = source * factor if order == 'factor_first' else source / right * left
    return str(factor), str(estimate)


@pytest.mark.parametrize('prec, order', [
    (None, 'factor_first'), (30, 'factor_first'), (40, 'factor_first'), (None, 'divide_first'), (30, 'divide_first'),
])
def test_a_factor_estimate_computed_in_exact_decimals_reaches_estimated_whatever_its_precision_or_order(
        analysis, tmp_path, prec, order):
    """Round 7 (Huachen revenue_1_8): the assistant followed the estimate guidance and computed in exact
    Decimal at full precision. At 30 digits (more precise than the server's 28) the ratio recipe failed, and
    computed as C ÷ N12 × ΣB12:I12 the estimates failed on the last digit; both were reported as precision
    loss, and redoing the computation as the message asked gave the same result. A quotient that does not
    terminate has no exact decimal, so a value that keeps at least 28 significant digits and agrees with the
    exact quotient to that precision passes, however it was computed."""
    factor, estimate = _exact_decimal_estimate(123457, prec=prec, order=order)
    case = _float_estimate_case(analysis, tmp_path, factor_value=factor, estimate_value=estimate, source=123457)
    results = {result['recipe_id']: result for result in evaluate_evidence_recipes(analysis, case.recipes)['results']}
    item = _item(check_requirements(analysis, case.spec))

    assert (results['factor']['status'], results['estimate']['status']) == ('pass', 'pass')
    assert item['status'] == 'estimated'
    assert item['locations'][0]['evidence']['evidence_basis'] == 'estimate'
    quality = augment_quality(analysis, case.spec, {'status': 'pass', 'issues': []})
    completion = record_completion(analysis, {'id': 'q' * 32, 'content_hash': f'{prec}-{order}', 'run_ids': []}, quality)
    assert (completion['status'], completion['stop_reason']) == ('awaiting_manager', 'estimate_requires_acceptance')


def test_the_last_digit_of_the_alternative_order_really_differs_from_the_servers_own_quotient():
    """The case above is not vacuous: at the default precision the two orders disagree in the last digit."""
    assert _exact_decimal_estimate(123457)[1] != _exact_decimal_estimate(123457, order='divide_first')[1]


def _quotient_digit_changed(text, position):
    digits = [index for index, char in enumerate(text) if char.isdigit()]
    index = digits[position - 1]
    return text[:index] + str((int(text[index]) + 1) % 10) + text[index + 1:]


@pytest.mark.parametrize('label, factor, estimate, reason, hint', [
    # Rounded for display: still a precision failure (decision 1), with the hint.
    ('display rounding', '0.6524', None, 'recipe_failed_precision', True),
    # An exact rounding at 20 digits keeps less than a Decimal context's precision: still rounded.
    ('20 digits', _exact_decimal_estimate(123457, prec=20)[0], _exact_decimal_estimate(123457, prec=20)[1],
     'recipe_failed_precision', True),
    # 28 digits, but wrong in the 20th: a different number, not a precision loss.
    ('wrong digit', _quotient_digit_changed(_exact_decimal_estimate(123457)[0], 20), None, 'recipe_failed', False),
])
def test_a_rounded_or_wrong_quotient_still_fails(analysis, tmp_path, label, factor, estimate, reason, hint):
    """Opposite direction: agreement to full precision is the only tolerance. A rounded quotient still fails
    with the full-precision hint, and a 28-digit value that is wrong gets no hint (it is not a float repr)."""
    estimate = estimate or _exact_decimal_estimate(123457)[1]
    case = _float_estimate_case(analysis, tmp_path, factor_value=factor, estimate_value=estimate, source=123457)
    results = {result['recipe_id']: result for result in evaluate_evidence_recipes(analysis, case.recipes)['results']}
    item = _item(check_requirements(analysis, case.spec))

    assert results['factor']['status'] == 'mismatch', label
    assert ('precision_hint' in results['factor']) is hint, label
    assert item['status'] == 'pending', label
    assert item['locations'][0]['evidence']['not_counted_reason'] == reason, label
    if hint:
        assert '28 位有效数字' in results['factor']['issue']['message']
        assert '28 位有效数字' in _unanswered_message(item)


def test_the_quotient_comparison_is_exact_except_for_full_precision_quotients():
    from decimal import Decimal
    from fractions import Fraction

    from foundry.financial_evidence import _matches_exact

    def matches(exact, claimed):
        server = Decimal(exact.numerator) / Decimal(exact.denominator)  # the server's 28-digit rendering
        return _matches_exact(exact, Decimal(claimed), server)

    third = Fraction(1, 3)
    assert matches(third, '0.' + '3' * 28)
    assert matches(third, '0.' + '3' * 27 + '4')  # a rounded last digit of a 28-digit quotient
    assert matches(third, '0.' + '3' * 40)  # a higher precision
    assert not matches(third, '0.' + '3' * 27)  # 27 digits: rounded below full precision
    assert not matches(third, '0.' + '3' * 20 + '4' + '3' * 7)  # wrong in the 21st digit
    assert not matches(Fraction(5, 8), '0.6250000000000000000000000001')
    assert matches(Fraction(5, 8), '0.62500')
    assert matches(Fraction(0), '0.00') and not matches(Fraction(0), '1E-30')
    assert not matches(third, '1E+999999') and not matches(third, '3E-999999')
    # Without an exact rational (a recipe touching an extreme size) the server's Decimal decides, as before.
    assert _matches_exact(None, Decimal('1E-999997'), Decimal('1E-999997'))
    assert not _matches_exact(None, Decimal('1000'), Decimal('1E-999997'))


def test_a_quotient_that_terminates_is_still_compared_exactly(analysis, tmp_path):
    """Opposite direction: 300 ÷ 480 is exactly 0.625, so a 28-digit value one unit off in its last digit
    fails; so does a direct recipe off in its last digit. Only a quotient with no exact decimal is compared
    to full precision."""
    case = _float_estimate_case(analysis, tmp_path, factor_value='0.6250000000000000000000000001',
                                estimate_value='112860.000', left=300, right=480)
    results = {result['recipe_id']: result for result in evaluate_evidence_recipes(analysis, case.recipes)['results']}
    assert results['factor']['status'] == 'mismatch'
    assert results['estimate']['status'] == 'unreadable'

    other = AnalysisStore(TaskStore(tmp_path / 'exact-var').create(title='除尽'))
    exact = _float_estimate_case(other, tmp_path / 'exact', factor_value='0.625', estimate_value='112860.000',
                                 left=300, right=480)
    assert {result['status'] for result in evaluate_evidence_recipes(other, exact.recipes)['results']} == {'pass'}
    assert _item(check_requirements(other, exact.spec))['status'] == 'estimated'


def _sheet_appendix_draft(tmp_path, sheet, metric, *, body=None, value='41469.625'):
    """One cited script value backed by a direct recipe on a sheet named `sheet` (round 7 repro)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    service = FinanceStore(TaskStore(tmp_path / 'var').create(title='appendix'))
    analysis = service.analysis
    book = _workbook(analysis, tmp_path, 'close', {sheet: {'B5': float(value)}})
    requirement = save_requirements(analysis, spec(scope={}, bindings={'close': book['id']}, items=[
        {'id': 'aug', 'metric': metric, 'organizations': ['集团合并'], 'periods': ['2026-08'],
         'scenarios': ['actual_2026_08'], 'requires_drilldown': False}]))
    rows = [{'metric_key': metric, 'organization': '集团合并', 'period': '2026-08', 'scenario': 'actual_2026_08',
             'value': value}]
    run = _script_run(analysis, {'close': book}, rows, suffix='appendix', requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'])
    draft = service.save_explanation_draft({
        'title': '8 月', 'body': body or f'8 月指标 {value}。', 'run_ids': [run['id']],
        'claims': [_claim(run, row=0, column='value', value=value)],
        'evidence_recipes': [_recipe(book, sheet, 'B5', run, 0, recipe_id='r1')]})
    return service, draft


@pytest.mark.parametrize('sheet', ['预算2026', '利润表 2026', '2026预算', '2026'])
@pytest.mark.parametrize('metric', ['ratio', 'revenue'])
def test_a_year_in_a_sheet_name_the_appendix_prints_is_not_an_uncited_number(tmp_path, sheet, metric):
    """Round 7: the server's 来源复算依据 appendix writes `sheet!range`; a year in the sheet name (2026预算) was
    read as a body number, flagged uncited_number in the generated appendix, which the writer cannot edit,
    and the draft could never reach complete. The sheet!range references it writes name archived cells."""
    service, draft = _sheet_appendix_draft(tmp_path / f'{metric}-{sheet}', sheet, metric)
    check = draft['explanation_check']

    assert f'{sheet}!B5' in draft['body'][draft['body'].index('## 来源复算依据'):]
    assert [issue for issue in check['issues'] if issue['code'] == 'uncited_number'] == []
    assert check['checks']['numbers']['status'] == 'pass'
    assert draft['completion']['status'] == 'complete'
    revalidated = service.validate_explanation({'draft_id': draft['id']})
    assert [issue for issue in revalidated['issues'] if issue['code'] == 'uncited_number'] == []


def test_the_same_sheet_year_typed_in_the_manager_body_is_still_checked(tmp_path):
    """Opposite direction: only the server's own references are exempt; the writer's prose is checked."""
    _service, draft = _sheet_appendix_draft(tmp_path, '预算2026', 'revenue', body='8 月收入 41469.625，见预算2026!B5。')
    flagged = [issue for issue in draft['explanation_check']['issues'] if issue['code'] == 'uncited_number']

    assert [(issue['text'], issue['origin']) for issue in flagged] == [('2026', 'manager_body')]
    assert draft['completion']['status'] != 'complete'


def test_the_huachen_estimate_with_years_in_its_sheet_names_still_reaches_the_manager(analysis, tmp_path, monkeypatch):
    """The Huachen revenue_1_8 estimate case reached awaiting_manager with its own sheet names and
    repair_available (4 appendix '2026' issues) once the budget sheets were named 2026预算 and 2026区域预算."""
    import test_requirement_evidence_paths as module

    rename = {'01·年度预算总表': '2026预算', '05·区域预算分解': '2026区域预算'}
    workbook, recipe = module._workbook, module._recipe
    monkeypatch.setattr(module, '_workbook', lambda analysis, tmp, name, sheets: workbook(
        analysis, tmp, name, {rename.get(key, key): value for key, value in sheets.items()}))
    monkeypatch.setattr(module, '_recipe', lambda dataset, sheet, *args, **kwargs: recipe(
        dataset, rename.get(sheet, sheet), *args, **kwargs))
    case = module._estimate_case(analysis, tmp_path)
    for entry in case.spec['evidence_recipes']:
        for side in ('left', 'right'):
            if side in entry:
                entry[side]['sheet'] = rename.get(entry[side]['sheet'], entry[side]['sheet'])
    draft = FinanceStore(analysis.task).save_explanation_draft(
        {'body': '收入说明见附表。', **{key: case.spec[key] for key in ('run_ids', 'claims', 'evidence_recipes')}})

    assert '2026区域预算!C5 × （2026预算!B12:C12 ÷ 2026预算!N12）' in draft['body']
    assert [issue for issue in draft['explanation_check']['issues'] if issue.get('origin') == 'generated_appendix'] == []
    assert (draft['completion']['status'], draft['completion']['stop_reason']) == (
        'awaiting_manager', 'estimate_requires_acceptance')


CONTROL_SCOPE = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'}
GL_ROW = {**CONTROL_SCOPE, 'scenario': 'actual', 'management_account': 'revenue', 'amount': '120', 'source_row': 1}


def _control_totals_request(service, requirement, runs=(), claims=()):
    return {'requirements_id': requirement['id'], 'run_ids': [run['id'] for run in runs], 'claims': list(claims)}


def _completion(service, request, content_hash):
    quality = augment_quality(service.analysis, request, {'status': 'pass', 'issues': []})
    return record_completion(service.analysis, {'id': content_hash[:1] * 32, 'content_hash': content_hash,
                                                'run_ids': request['run_ids']}, quality)


def test_a_workbook_bound_beside_a_table_the_engine_reads_leaves_the_engine_path_open(tmp_path):
    """Round 7: a requirement bound to a GL table plus a budget workbook kept for recipes. One workbook
    binding blocked every finance-engine path as bindings_without_engine_rows and completion stopped at
    awaiting_manager, although run_metric on exactly these bindings reads the GL rows and answers."""
    service, _context, bindings = _finance_service_from_rows(tmp_path, {'gl': [GL_ROW]},
                                                             {'gl': {**CONTROL_SCOPE, 'scenario': 'actual'}}, title='mixed')
    budget = _workbook(service.analysis, tmp_path, 'budget', {'预算': {'A1': '营业收入', 'B1': 100}})
    context = service.save_context({'bindings': {**bindings, 'book': budget['id']},
                                    'scopes': {'gl': {**CONTROL_SCOPE, 'scenario': 'actual'}}})
    requirement = service.analysis_requirements_save({
        'question': '控制数', 'context_id': context['id'], 'scope': CONTROL_SCOPE,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}]})
    support = requirement['support']['items'][0]
    request = _control_totals_request(service, requirement)
    item = _item(check_requirements(service.analysis, request))

    assert support['accepted_evidence'] == ['run_metric_result_set'] and 'blocked_evidence' not in support
    assert [path['path'] for path in item['evidence_paths']['accepted']] == ['run_metric_result_set']
    assert 'awaiting_manager' not in item
    assert '可计入的依据' in _unanswered_message(item)
    completion = _completion(service, request, 'mixed-before')
    assert (completion['status'], completion['repair_allowed']) == ('repair_available', True)

    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    _verify_run_column(service, run, 'amount')
    answered = check_requirements(service.analysis, _control_totals_request(
        service, requirement, [run], _claims_for_columns(run, 'amount')))
    assert run['bindings'] == requirement['bindings'] and run['result']['rows']
    assert _item(answered)['status'] == 'answered'


REGIONAL_TABLE = [{'区域': region, '全年预算': budget, '1-8月实际': actual}
                  for region, budget, actual in (('华东', '180576', '109742.028'), ('华南', '120000', '80000'))]


def test_bound_tables_the_finance_engine_reads_no_rows_from_are_handed_to_the_manager(tmp_path):
    """Round 7 (Huachen): the manager rebound control_totals to the confirmed table snapshots of the regional
    sheets (7 rows each, no amount column). Any snapshot with rows counted as engine-readable, so the
    assistant saved a finance context and ran run_metric, which read 0 rows; the guidance kept offering
    run_metric and completion kept spending repairs. Readability is now what the finance normaliser reads."""
    pnl = [{'区域': row['区域'], '1-8月实际': row['1-8月实际']} for row in REGIONAL_TABLE]
    service, context, bindings = _finance_service_from_rows(
        tmp_path, {'regional_budget': REGIONAL_TABLE, 'regional_pnl': pnl}, {}, title='regional')
    requirement = service.analysis_requirements_save({
        'question': '区域与集团合计勾稽', 'context_id': context['id'], 'scope': {'ledger': 'L1'},
        'items': [{'id': 'control_totals', 'metric': 'control_totals', 'requires_drilldown': False}]})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'},
                              'requirements_id': requirement['id']})
    request = _control_totals_request(service, requirement, [run])
    item = _item(check_requirements(service.analysis, request))
    message = _unanswered_message(item)

    assert run['bindings'] == requirement['bindings'] and run['result']['rows'] == []
    assert item['evidence_paths']['accepted'] == []
    assert [(path['path'], path['blockers']) for path in item['evidence_paths']['blocked']] == [
        ('run_metric_result_set', ['bindings_without_engine_rows'])]
    assert item['awaiting_manager'] == ['bindings_without_engine_rows']
    assert '没有金额列' in message and '助手不要重复计算' in message
    assert '可计入的依据' not in message and 'finance_context_save' not in message
    assert requirement['support']['items'][0]['accepted_evidence'] == []
    completion = _completion(service, request, 'regional')
    assert (completion['status'], completion['repair_allowed']) == ('awaiting_manager', False)
    assert completion['manager_reasons'] == ['bindings_without_engine_rows']


@pytest.mark.parametrize('rows, policies', [
    # Wide finance measures the normaliser reads without an amount column.
    ([{**CONTROL_SCOPE, 'scenario': 'actual', 'revenue': '120', 'cost': '80'}], {}),
    # A column the finance context maps to amount.
    ([{**CONTROL_SCOPE, 'scenario': 'actual', 'management_account': 'revenue', '本月数': '120'}],
     {'t': {'field_map': {'amount': '本月数'}}}),
])
def test_bound_tables_the_engine_reads_through_their_context_keep_the_engine_path(tmp_path, rows, policies):
    """Opposite direction: a table without an `amount` column that the finance engine still reads (wide
    revenue/cost measures, or a column the requirement's finance context maps to amount) stays open."""
    task = TaskStore(tmp_path / 'var').create(title='wide')
    analysis = AnalysisStore(task)
    path = tmp_path / 't.json'
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    dataset = analysis.add_dataset(path, name='t')
    service = FinanceStore(task)
    context = service.save_context({'bindings': {'t': dataset['id']}, 'policies': policies})
    requirement = service.analysis_requirements_save({
        'question': '控制数', 'context_id': context['id'], 'scope': CONTROL_SCOPE,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}]})
    item = _item(check_requirements(analysis, _control_totals_request(service, requirement)))
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})

    assert [path['path'] for path in item['evidence_paths']['accepted']] == ['run_metric_result_set']
    assert 'awaiting_manager' not in item
    assert run['result']['rows']


def test_a_finance_run_whose_rows_miss_the_requirement_grain_says_why(tmp_path):
    """Round 7 GL variant: bound to a GL balance table the engine reads (1 row) whose rows carry no
    organization, period or scenario and an unmapped account. The run never matched the grain and the
    same message repeated with no reason. The run and what its rows lack are now named."""
    gl = [{'ledger': 'L1', 'currency': 'CNY', 'unit': '万元', '科目代码': '6001', 'amount': '3431356426'}]
    service, context, _bindings = _finance_service_from_rows(tmp_path, {'gl': gl}, {}, title='gl')
    requirement = service.analysis_requirements_save({
        'question': '区域与集团合计勾稽', 'context_id': context['id'], 'scope': {'ledger': 'L1'},
        'items': [{'id': 'control_totals', 'metric': 'control_totals', 'organizations': ['集团合并'],
                   'periods': ['2026-08'], 'requires_drilldown': False}]})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'},
                              'requirements_id': requirement['id']})
    _verify_run_column(service, run, 'amount')
    request = _control_totals_request(service, requirement, [run], _claims_for_columns(run, 'amount'))
    item = _item(check_requirements(service.analysis, request))
    message = _unanswered_message(item)

    assert len(run['result']['rows']) == 1
    assert item['status'] == 'pending'
    assert item['engine_runs'] == [{'run_id': run['id'], 'rows': 1, 'reason': 'rows_do_not_cover_requirement',
                                    'blank_fields': ['organization', 'period'], 'unmapped_accounts': 1,
                                    'missing_grains': [{'organization': '集团合并', 'period': '2026-08'}]}]
    fixup = next(fixup for fixup in item['fixups'] if fixup['code'] == 'engine_run_does_not_cover_requirement')
    assert fixup['runs'] == item['engine_runs']
    assert run['id'] in message and '行上 organization、period 为空' in message and '__unmapped__' in message
    assert 'awaiting_manager' not in item


def test_a_draft_policy_9_completed_with_a_second_unbacked_value_is_checked_again(analysis, monthly):
    """Policy 9 completed a draft that cited a script-only value beside a counted one for the same grain.
    The rule changed, so a resend must not replay that verdict."""
    from foundry.analysis import _hash
    from foundry.finance_completion import COMPLETION_POLICY_VERSION
    from foundry.fsutil import write_json_atomic

    fake = {**REVENUE_ROWS[1], 'value': '52000.0000'}
    _run, request = _second_value_request(analysis, monthly, [*REVENUE_ROWS, fake], {
        0: (monthly.budget, '01·年度预算总表', 'I12', {}),
        1: (monthly.close, '04·合并利润表', 'B5', {'scale': '0.0001'})}, suffix='replay-9')
    service = FinanceStore(analysis.task)
    draft_request = {'title': '8月收入', 'body': '8 月营业收入实际 52000.0000 万元，预算 44163.6526 万元。',
                     **{key: request[key] for key in ('run_ids', 'claims', 'evidence_recipes', 'requirements_id')}}
    first = service.save_explanation_draft(draft_request)
    assert first['check_policy_version'] == COMPLETION_POLICY_VERSION
    path = analysis._object_path('drafts', first['id'])
    stored = {key: value for key, value in json.loads(path.read_text()).items() if key != '_integrity_hash'}
    check = stored['explanation_check']
    old = {**check, 'status': 'pass', 'issues': [], 'requirements': {
        **check['requirements'], 'coverage': {'status': 'pass'}, 'original_requirements_completed': True,
        'items': [{**item, 'status': 'answered'} for item in check['requirements']['items']]}}
    record = {**stored, 'check_policy_version': 9, 'explanation_check': old, 'quality': old}
    write_json_atomic(path, {**record, '_integrity_hash': _hash(record)})

    again = service.save_explanation_draft(draft_request)

    assert again.get('replayed') is not True
    assert _item(again['explanation_check']['requirements'])['status'] == 'pending'
    assert again['completion']['status'] != 'complete'


def test_tool_descriptions_state_the_round_7_rules():
    """The tools say what the checker now does: every cited value of a grain counts, a non-terminating
    quotient keeps 28 significant digits, and only bindings no snapshot of which the engine reads block."""
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    preset = (ROOT / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')['description']

    assert 'Every value the draft cites for a requirement grain must count' in draft
    assert '同一个要求组合引用的每个数都要按上述依据计入' in tools and '同一要求组合引用的每个数都要计入' in preset
    assert '28 significant digits' in draft and '28 位有效数字' in tools and '28位有效数字' in preset
    assert 'A workbook bound beside a table the engine reads blocks nothing' in draft
    assert '没有金额列的表' in tools and '没有金额列的表' in preset
    assert 'engine_run_does_not_cover_requirement' in draft and 'engine_run_does_not_cover_requirement' in tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(
        encoding='utf-8') == preset


# --- review fixes, round 8 (PR #23) -----------------------------------------------------------------


def _pnl_account_case(tmp_path, account):
    """A ledger whose management account is named like a P&L line; 2026-08 is 110 + 5 = 115."""
    rows = [{'ledger': 'L', 'organization': '总部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元',
             'scenario': 'actual', 'management_account': account, 'amount': amount, 'source_row': str(index),
             'doc_id': f'D{index}', 'line_id': '1'}
            for index, amount in enumerate(('110', '5'), start=1)]
    scope = {'ledger': 'L', 'organization': '总部', 'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}
    service, context, bindings = _finance_service_from_rows(tmp_path, {'actual': rows}, {'actual': scope},
                                                            title=f'pnl-{account}')
    requirement = save_requirements(service.analysis, {
        'question': f'8 月{account}', 'context_id': context['id'], 'bindings': bindings, 'scope': {'actual': scope},
        'items': [{'id': 'line_08', 'metric': account, 'organizations': ['总部'], 'periods': ['2026-08'],
                   'scenarios': ['actual'], 'requires_drilldown': False}]})
    return SimpleNamespace(service=service, context=context, requirement=requirement)


def _account_total_claim(service, context, account, filters=None, period='2026-08'):
    metric = {'kind': 'account_total', 'accounts': [account], **({'filters': filters} if filters else {})}
    run = service.run_metric({'context_id': context['id'], 'metric': metric})
    index = next(index for index, row in enumerate(run['result']['rows']) if row.get('period') == period)
    return run, {'basis': 'calculation', 'run_id': run['id'], 'row': index, 'column': 'amount',
                 'value': run['result']['rows'][index]['amount']}


@pytest.mark.parametrize('filters', [None, {'source_row': 2}])
@pytest.mark.parametrize('account', ['revenue', 'cost', 'expense', 'profit'])
def test_run_metric_account_total_does_not_answer_a_revenue_cost_expense_or_profit_item(tmp_path, account, filters):
    """Round 8: decision 1 answers the four P&L lines only by engine closure or a source recipe, and neither
    the support record nor the message offers account_total for them. A cited run_metric account_total cell
    still answered them, filters included: a source_row filter gave 5 for a 2026-08 total of 115, and the
    draft completed with original_requirements_completed True."""
    from decimal import Decimal

    case = _pnl_account_case(tmp_path, account)
    run, claim = _account_total_claim(case.service, case.context, account, filters)
    result = check_requirements(case.service.analysis, {'requirements_id': case.requirement['id'],
                                                        'run_ids': [run['id']], 'claims': [claim]})
    item = _item(result)
    draft = case.service.save_explanation_draft({'title': 't', 'body': f'8 月{account} {claim["value"]} 元。',
                                                 'run_ids': [run['id']], 'claims': [claim]})

    assert run['engine'] == 'finance' and Decimal(claim['value']) == Decimal('5' if filters else '115')
    assert item['status'] == 'pending'
    assert item['locations'][0]['evidence']['not_counted_reason'] == 'engine_output_without_closure'
    assert result['coverage']['status'] == 'needs_attention'
    assert 'run_metric_account_total' not in case.requirement['support']['items'][0]['accepted_evidence']
    assert 'account_total' not in _unanswered_message(item)
    assert draft['completion']['status'] != 'complete'
    assert draft['completion']['original_requirements_completed'] is False


def _filtered_ledger_case(tmp_path, account='管理费用'):
    """A ledger account item with dimensions.period; 2026-08 is 110 (source row 2) + 5 (source row 3) = 115."""
    rows = [{'ledger': 'L', 'organization': '总部', 'period': period, 'currency': 'CNY', 'unit': '元', 'scenario': 'actual',
             'management_account': account, 'amount': amount, 'source_row': str(index), 'doc_id': f'D{index}',
             'line_id': '1', 'product': product}
            for index, (period, amount, product) in enumerate(
                (('2026-07', '100', '物业费'), ('2026-08', '110', '物业费'), ('2026-08', '5', '车位')), start=1)]
    scope = {'ledger': 'L', 'organization': '总部', 'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}
    service, context, bindings = _finance_service_from_rows(tmp_path, {'actual': rows}, {'actual': scope}, title='ledger-f')
    requirement = save_requirements(service.analysis, {
        'question': f'8 月{account}', 'context_id': context['id'], 'bindings': bindings, 'scope': {'actual': scope},
        'items': [{'id': 'account_08', 'metric': account, 'dimensions': {'period': '2026-08'}, 'requires_drilldown': False}]})
    return SimpleNamespace(service=service, context=context, requirement=requirement, account=account)


@pytest.mark.parametrize('filters, value', [({'source_row': 3}, '5'), ({'source_row': [2]}, '110')])
def test_a_filtered_account_total_does_not_answer_a_ledger_account_item(tmp_path, filters, value):
    """Same defect on a ledger account item (on main too): the native account total never looked at the
    run's filters, so a total over one source row answered the account's 8 月 amount of 115."""
    from decimal import Decimal

    case = _filtered_ledger_case(tmp_path)
    run, claim = _account_total_claim(case.service, case.context, case.account, filters)
    item = _item(check_requirements(case.service.analysis, {'requirements_id': case.requirement['id'],
                                                            'run_ids': [run['id']], 'claims': [claim]}))

    assert Decimal(claim['value']) == Decimal(value)
    assert item['status'] == 'pending'
    assert item['locations'][0]['evidence']['not_counted_reason'] == 'metric_filters_differ'
    assert 'filters' in _unanswered_message(item)


@pytest.mark.parametrize('filters', [None, {'period': '2026-08'}, {'organization': '总部'}])
def test_an_account_total_filtered_only_to_the_items_own_scope_still_answers(tmp_path, filters):
    """Opposite direction: the engine's own total of the account, unfiltered or filtered only to the
    requirement's own period or organization, still answers a ledger account item."""
    from decimal import Decimal

    case = _filtered_ledger_case(tmp_path)
    run, claim = _account_total_claim(case.service, case.context, case.account, filters)
    result = check_requirements(case.service.analysis, {'requirements_id': case.requirement['id'],
                                                        'run_ids': [run['id']], 'claims': [claim]})

    assert Decimal(claim['value']) == Decimal('115')
    assert _item(result)['status'] == 'answered'
    assert _item(result)['locations'][0]['evidence']['evidence_basis'] == 'engine_output'
    assert result['coverage']['status'] == 'pass'


def _estimate_beside_source(analysis, tmp_path, *, cite_estimate=True):
    """_estimate_case plus a sixth row that states 华东区域 budget_1_8 as 05!C5 (180576) by a direct recipe."""
    case = _estimate_case(analysis, tmp_path)
    close = analysis.read_dataset(case.run['bindings']['close'])
    extra = {'metric_key': 'revenue', 'period': '2026-01:2026-08', 'unit': '万元', 'currency': 'CNY',
             'organization': '华东区域', 'scenario': 'budget_1_8', 'value': '180576'}
    run = _script_run(analysis, {'budget': case.budget, 'close': close}, [*case.run['result']['rows'], extra],
                      suffix='beside', requirements_id=case.requirement['id'],
                      requirements_semantic_fingerprint=case.requirement['semantic_fingerprint'])
    recipes = [{**recipe, 'claim': {**recipe['claim'], 'run_id': run['id']}} for recipe in case.spec['evidence_recipes']
               if cite_estimate or recipe['id'] != 'east_budget_estimate']
    recipes.append(_recipe(case.budget, '05·区域预算分解', 'C5', run, 5, recipe_id='east_source'))
    claims = [{**claim, 'run_id': run['id']} for claim in case.spec['claims'] if cite_estimate or claim['row'] != 3]
    claims.append(_claim(run, row=5, column='value', value='180576'))
    return SimpleNamespace(requirement=case.requirement, run=run, spec={
        'requirements_id': case.requirement['id'], 'run_ids': [run['id']], 'claims': claims, 'evidence_recipes': recipes})


def test_an_unaccepted_estimate_cited_beside_a_source_value_of_its_grain_is_not_answered(analysis, tmp_path):
    """Round 8: a declared estimate grain whose draft also cites a source-backed number (a different one)
    was answered, so coverage passed and the draft completed with an estimate no manager accepted. A grain
    is only as good as every number the draft cites for it: the estimate keeps it `estimated`."""
    case = _estimate_beside_source(analysis, tmp_path)
    result = check_requirements(analysis, case.spec)
    item = _item(result)
    east = next(grain for grain in item.get('estimated_grains', []) if grain.get('organization') == '华东区域')
    draft = FinanceStore(analysis.task).save_explanation_draft({
        'body': '华东区域 1-8 月收入预算。', **{key: case.spec[key] for key in ('run_ids', 'claims', 'evidence_recipes')}})
    issues = [issue['code'] for issue in draft['explanation_check']['issues']]

    assert item['status'] == 'estimated'
    assert result['coverage']['status'] == 'needs_attention'
    assert result['original_requirements_completed'] is False
    assert east['scenario'] == 'budget_1_8' and east['accepted'] is False
    assert east['locations'] == [{'run_id': case.run['id'], 'row': 3, 'column': 'value'}]
    assert 'requirement_estimated' in issues
    assert (draft['completion']['status'], draft['completion']['stop_reason']) == (
        'awaiting_manager', 'estimate_requires_acceptance')
    assert draft['completion']['original_requirements_completed'] is False


def test_the_source_value_alone_still_answers_its_grain(analysis, tmp_path):
    """Opposite direction: dropping the estimate leaves the grain to the source-backed number."""
    case = _estimate_beside_source(analysis, tmp_path, cite_estimate=False)
    result = check_requirements(analysis, case.spec)

    assert _item(result)['status'] == 'answered'
    assert result['coverage']['status'] == 'pass'


def _ungrained_estimate(analysis, tmp_path, *, cite_estimate=True):
    """An item without grain lists: one cell backed by S!F5 (1200), one estimated as S!F5 × S!G1/S!G2."""
    book = _workbook(analysis, tmp_path, 'book', {'S': {'F5': 1200, 'G1': 2, 'G2': 4}})
    requirement = save_requirements(analysis, spec(
        scope={'currency': 'CNY', 'unit': '万元'}, bindings={'book': book['id']},
        items=[{'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False,
                'grain_basis': [{'basis': 'estimate', 'method': '全年 × 2/4'}]}]))
    key = {'metric_key': 'revenue', 'period': '2026-01:2026-08'}
    base = {'metric_key': 'revenue', 'period': '2026-01:2026-08'}
    rows = [{**base, 'value': '1200', 'currency': 'CNY', 'unit': '万元'},
            {**base, 'value': '600', 'currency': 'CNY', 'unit': '万元'},
            {**base, 'scenario': 'factor', 'value': '0.5'}]
    run = _script_run(analysis, {'book': book}, rows, suffix='ungrained', requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'])

    def cell(reference):
        return {'dataset_id': book['id'], 'source_hash': book['source_hash'], 'sheet': 'S', 'range': reference}

    recipes = [{'id': 'source', 'kind': 'direct', **cell('F5'), 'claim': {'run_id': run['id'], 'row': 0, 'column': 'value'}},
               {'id': 'f', 'kind': 'ratio', 'claim': {'run_id': run['id'], 'row': 2, 'column': 'value'},
                'left': cell('G1'), 'right': cell('G2'), 'business_key': key},
               {'id': 'estimate', 'kind': 'direct', **cell('F5'), 'claim': {'run_id': run['id'], 'row': 1, 'column': 'value'},
                'factor_recipe_id': 'f', 'business_key': key}]
    claims = [_claim(run, row=0, column='value', value='1200')]
    if cite_estimate:
        claims.append(_claim(run, row=1, column='value', value='600'))
    return {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims, 'evidence_recipes': recipes}


def test_an_item_without_grain_lists_is_estimated_when_it_cites_an_estimate_beside_a_source_value(analysis, tmp_path):
    result = check_requirements(analysis, _ungrained_estimate(analysis, tmp_path))
    item = _item(result)

    assert [location['status'] for location in item['locations']] == ['answered', 'estimated']
    assert item['status'] == 'estimated'
    assert result['coverage']['status'] == 'needs_attention'


def test_an_item_without_grain_lists_is_answered_by_its_source_value_alone(analysis, tmp_path):
    result = check_requirements(analysis, _ungrained_estimate(analysis, tmp_path, cite_estimate=False))

    assert _item(result)['status'] == 'answered'
    assert result['coverage']['status'] == 'pass'


def _typed_columns(rows):
    return [{'name': name, 'nullable': name not in {'metric_key', 'value'},
             'type': 'DECIMAL(38,28)' if name == 'value' else 'DECIMAL(38,4)' if name == 'variance' else 'VARCHAR'}
            for name in dict.fromkeys(key for row in rows for key in row)]


def _variance_column_case(analysis, tmp_path, mode):
    """Huachen stage B in miniature: revenue_1_8 (declared estimate for 华东区域 budget_1_8) plus a ratio item.
    The writer adds a `variance` column (actual − budget) to the 集团合并 actual row only; the stored run pads
    that column with null on every other row, as run_script does."""
    case = _estimate_case(analysis, tmp_path)
    current = case.requirement
    period = '2026-01:2026-08'
    progress = {'id': 'progress', 'metric': 'ratio', 'organizations': ['集团合并'], 'periods': [period],
                'scenarios': ['achievement_ratio'], 'dimensions': {'metric_key': 'revenue'}, 'requires_drilldown': False}
    requirement = save_requirements(analysis, spec(
        question=current['question'], scope=current['scope'], bindings=current['bindings'], parent_id=current['id'],
        items=[*current['items'], progress]))
    rows = [dict(row) for row in case.run['result']['rows']]
    rows.append({'metric_key': 'revenue', 'organization': '集团合并', 'period': period, 'scenario': 'achievement_ratio',
                 'value': '1085.48', 'unit': '-'})
    for index, row in enumerate(rows):
        row['variance'] = '325344' if index == 0 else None
    close = analysis.read_dataset(case.run['bindings']['close'])
    run = _script_run(analysis, {'budget': case.budget, 'close': close}, rows, suffix=f'variance-{mode}',
                      requirements_id=requirement['id'], requirements_semantic_fingerprint=requirement['semantic_fingerprint'],
                      result={'columns': _typed_columns(rows), 'rows': rows})
    recipes = [{**recipe, 'claim': {**recipe['claim'], 'run_id': run['id']}} for recipe in case.spec['evidence_recipes']]
    claims = [{**claim, 'run_id': run['id']} for claim in case.spec['claims']]
    claims.append(_claim(run, row=5, column='value', value='1085.48'))
    if mode in {'cite', 'diff'}:
        claims.append(_claim(run, row=0, column='variance', value='325344'))
    if mode == 'diff':
        close_d11 = {'dataset_id': close['id'], 'source_hash': close['source_hash'], 'sheet': '10·区域经营损益表', 'range': 'D11'}
        budget_b12 = {'dataset_id': case.budget['id'], 'source_hash': case.budget['source_hash'],
                      'sheet': '01·年度预算总表', 'range': 'B12:C12'}
        recipes.append({'id': 'variance', 'kind': 'diff', 'left': close_d11, 'right': budget_b12,
                        'claim': {'run_id': run['id'], 'row': 0, 'column': 'variance'}})
    return SimpleNamespace(requirement=requirement, run=run, spec={
        'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims, 'evidence_recipes': recipes})


@pytest.mark.parametrize('mode', ['drop', 'diff'])
def test_a_numeric_column_on_another_row_does_not_void_estimates_or_ratio_rows(analysis, tmp_path, mode):
    """Round 8 (Huachen stage B): one row got a `variance` column, the stored run padded it with null on every
    other row, and each plain result row became a missing_data group. The factor-estimate cells and the ratio
    rows then stopped counting, and neither backing the variance (diff) nor dropping its claim brought them
    back; the message never named the padded column. A plain result row has no closure rule, so an empty
    sibling column says nothing about a cited cell of it."""
    case = _variance_column_case(analysis, tmp_path, mode)
    result = check_requirements(analysis, case.spec)
    revenue, progress = _item(result, 'revenue_1_8'), _item(result, 'progress')
    completion = _completion(FinanceStore(analysis.task), case.spec, f'variance-{mode}')

    assert case.run['result']['rows'][3]['variance'] is None
    assert revenue['status'] == 'estimated'
    assert [location['status'] for location in revenue['locations'] if location['row'] == 3] == ['estimated']
    assert progress['status'] == 'answered'
    assert 'uncounted_grains' not in revenue
    assert (completion['status'], completion['stop_reason']) == ('awaiting_manager', 'estimate_requires_acceptance')


def test_an_unbacked_extra_column_only_unanswers_its_own_grain(analysis, tmp_path):
    """The round-7 rule still holds for the cited variance itself: it is a script value for the 集团合并
    actual grain, so only that grain is not counted; the estimates and the ratio row are unaffected."""
    case = _variance_column_case(analysis, tmp_path, 'cite')
    result = check_requirements(analysis, case.spec)
    revenue, progress = _item(result, 'revenue_1_8'), _item(result, 'progress')

    assert revenue['status'] == 'pending'
    assert [(grain['organization'], grain['scenario'], grain['reasons']) for grain in revenue['uncounted_grains']] == [
        ('集团合并', 'actual_1_8', ['script_output_without_recipe'])]
    assert progress['status'] == 'answered'


def test_an_empty_member_of_a_rule_bearing_group_still_voids_its_cited_cell(analysis):
    """Opposite direction: a ratio row (numerator/denominator/ratio) has a closure rule, so a missing
    denominator still leaves its cited ratio as missing_data."""
    save_requirements(analysis, spec(scope={}, items=[{'id': 'ratio', 'metric': 'ratio', 'requires_drilldown': False}]))
    full = _script_run(analysis, {}, [{'numerator': '3', 'denominator': '6', 'ratio': '0.5'}], suffix='ratio-full')
    empty = _script_run(analysis, {}, [{'numerator': '3', 'denominator': None, 'ratio': '0.5'}], suffix='ratio-empty')

    def status(run):
        item = _item(check_requirements(analysis, {'run_ids': [run['id']],
                                                   'claims': [_claim(run, row=0, column='ratio', value='0.5')]}))
        return item['status'], [location['status'] for location in item['locations']]

    assert status(full) == ('answered', ['answered'])
    assert status(empty) == ('missing_data', ['missing_data'])


def test_an_engine_run_whose_rows_lack_the_requirements_ledger_currency_and_unit_names_them(tmp_path):
    """Round 8 (Huachen GL variant): after the scopes stated organization and period as the round-7 message
    advised, the one result row covered the grain, but the message still said the grain had no result row
    and named no blank field. The row lacked the requirement's ledger, currency and unit, which the check
    compares and the blank-field scan never looked at. Following the new message answers."""
    required = {'ledger': 'L1', 'currency': 'CNY', 'unit': '万元'}
    table = [{'management_account': 'revenue', '科目代码': '6001', 'amount': '120', 'source_row': 1}]
    grain = {'organization': '集团合并', 'period': '2026-08'}
    service, context, bindings = _finance_service_from_rows(tmp_path, {'gl': table}, {'gl': grain}, title='gl-scope')
    requirement = service.analysis_requirements_save({
        'question': '区域与集团合计勾稽', 'context_id': context['id'], 'scope': required,
        'items': [{'id': 'control_totals', 'metric': 'control_totals', 'organizations': ['集团合并'],
                   'periods': ['2026-08'], 'requires_drilldown': False}]})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'},
                              'requirements_id': requirement['id']})
    _verify_run_column(service, run, 'amount')
    item = _item(check_requirements(service.analysis, _control_totals_request(
        service, requirement, [run], _claims_for_columns(run, 'amount'))))
    gap = item['engine_runs'][-1]
    message = _unanswered_message(item)

    assert {key: run['result']['rows'][0].get(key) for key in grain} == grain
    assert gap['blank_fields'] == ['currency', 'ledger', 'unit']
    assert gap['required_scope'] == required
    assert 'missing_grains' not in gap
    assert gap['out_of_scope_grains'] == [grain]
    assert '没有结果行' not in message
    assert '行上 currency、ledger、unit 为空' in message and 'currency=CNY、ledger=L1、unit=万元' in message

    rescoped = service.save_context({'bindings': bindings, 'scopes': {'gl': {**grain, **required}}})
    rerun = service.run_metric({'context_id': rescoped['id'], 'metric': {'kind': 'control_totals'},
                                'requirements_id': requirement['id']})
    _verify_run_column(service, rerun, 'amount')
    answered = check_requirements(service.analysis, _control_totals_request(
        service, requirement, [rerun], _claims_for_columns(rerun, 'amount')))
    assert _item(answered)['status'] == 'answered'


def test_an_engine_run_whose_rows_state_another_unit_says_which(tmp_path):
    """A row that states a field differently from the requirement is named with the required value; it is
    neither blank nor a grain without rows."""
    table = [{'management_account': 'revenue', 'organization': '集团合并', 'period': '2026-08', 'ledger': 'L1',
              'currency': 'CNY', 'unit': '元', 'amount': '1200000', 'source_row': 1}]
    service, context, _bindings = _finance_service_from_rows(tmp_path, {'gl': table}, {}, title='gl-unit')
    requirement = service.analysis_requirements_save({
        'question': '勾稽', 'context_id': context['id'], 'scope': {'ledger': 'L1', 'currency': 'CNY', 'unit': '万元'},
        'items': [{'id': 'control_totals', 'metric': 'control_totals', 'organizations': ['集团合并'],
                   'periods': ['2026-08'], 'requires_drilldown': False}]})
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'},
                              'requirements_id': requirement['id']})
    item = _item(check_requirements(service.analysis, _control_totals_request(service, requirement, [run])))
    gap = item['engine_runs'][-1]

    assert run['result']['rows'][0]['unit'] == '元'
    assert 'blank_fields' not in gap
    assert gap['differing_fields'] == {'unit': '万元'}
    assert 'unit' in _unanswered_message(item) and '没有结果行' not in _unanswered_message(item)


MAPPED_SCOPE = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'}


def _mapped_column_case(tmp_path, rows_by_alias, items):
    """A requirement bound to detail tables whose amount column has a name the default reading does not know,
    saved before any finance context (the preset's order)."""
    task = TaskStore(tmp_path / 'var').create(title='mapped')
    analysis = AnalysisStore(task)
    bindings = {}
    for alias, rows in rows_by_alias.items():
        path = tmp_path / f'{alias}.json'
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        bindings[alias] = analysis.add_dataset(path, name=alias)['id']
    service = FinanceStore(task)
    requirement = service.analysis_requirements_save({'question': '控制数', 'scope': MAPPED_SCOPE, 'bindings': bindings,
                                                      'items': items})
    return SimpleNamespace(service=service, analysis=analysis, bindings=bindings, requirement=requirement,
                           request={'requirements_id': requirement['id'], 'run_ids': [], 'claims': []})


def test_a_detail_table_whose_amount_column_needs_a_field_map_is_the_assistants_to_open(tmp_path):
    """Round 8: a GL table whose amounts sit under 本期发生额 was rowless for the default reading, so every
    engine path was blocked with bindings_without_engine_rows, handed to the manager, and the tools said not to
    save a finance context. One finance_context_save with policies.field_map on the same binding opens it."""
    rows = [{**MAPPED_SCOPE, 'scenario': 'actual', 'management_account': account, '本期发生额': amount, 'source_row': index}
            for index, (account, amount) in enumerate((('revenue', '120'), ('cost', '80')), start=1)]
    case = _mapped_column_case(tmp_path, {'gl': rows},
                               [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}])
    item = _item(check_requirements(case.analysis, case.request))
    blocked = item['evidence_paths']['blocked']
    message = _unanswered_message(item)
    completion = _completion(case.service, case.request, 'mapped-before')
    support = case.requirement['support']['items'][0]

    assert [(path['path'], path['blockers']) for path in blocked] == [('run_metric_result_set', ['amount_column_unmapped'])]
    assert blocked[0]['amount_columns'] == {'gl': ['本期发生额']}
    assert 'awaiting_manager' not in item
    assert 'field_map' in message and '本期发生额' in message and 'finance_context_save' in message
    assert '助手不要重复计算' not in message
    assert support['blocked_evidence'][0]['blockers'] == ['amount_column_unmapped']
    assert (completion['status'], completion['repair_allowed']) == ('repair_available', True)

    context = case.service.save_context({'bindings': case.bindings, 'scopes': {'gl': {**MAPPED_SCOPE, 'scenario': 'actual'}},
                                         'policies': {'gl': {'field_map': {'amount': '本期发生额'}}}})
    opened = _item(check_requirements(case.analysis, case.request))
    run = case.service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'},
                                   'requirements_id': case.requirement['id']})
    _verify_run_column(case.service, run, 'amount')
    answered = check_requirements(case.analysis, {**case.request, 'run_ids': [run['id']],
                                                  'claims': _claims_for_columns(run, 'amount')})

    assert [path['path'] for path in opened['evidence_paths']['accepted']] == ['run_metric_result_set']
    assert run['bindings'] == case.requirement['bindings'] and len(run['result']['rows']) == 2
    assert _item(answered)['status'] == 'answered' and answered['coverage']['status'] == 'pass'


def test_a_revenue_item_on_tables_whose_amount_column_needs_a_field_map_is_opened_by_the_assistant(tmp_path):
    rows = {side: [{**MAPPED_SCOPE, 'scenario': side, 'management_account': account, '本期发生额': amount, 'source_row': index}
                   for index, (account, amount) in enumerate(pairs, start=1)]
            for side, pairs in (('actual', (('revenue', '120'), ('cost', '50'), ('expense', '20'))),
                                ('budget', (('revenue', '100'), ('cost', '40'), ('expense', '10'))))}
    case = _mapped_column_case(tmp_path, rows, [{'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False}])
    item = _item(check_requirements(case.analysis, case.request))
    completion = _completion(case.service, case.request, 'mapped-revenue')

    assert ('engine_closure', ['amount_column_unmapped']) in [
        (path['path'], path['blockers']) for path in item['evidence_paths']['blocked']]
    assert 'awaiting_manager' not in item
    assert 'field_map' in _unanswered_message(item)
    assert completion['repair_allowed'] is True

    context = case.service.save_context({
        'bindings': case.bindings, 'scopes': {side: {**MAPPED_SCOPE, 'scenario': side} for side in rows},
        'policies': {side: {'field_map': {'amount': '本期发生额'}} for side in rows}})
    run = case.service.explain_variance({'context_id': context['id']})
    index = next(index for index, row in enumerate(run['result']['rows']) if row.get('metric') == 'revenue')
    answered = check_requirements(case.analysis, {**case.request, 'run_ids': [run['id']], 'claims': [
        _claim(run, row=index, column='contribution', value=run['result']['rows'][index]['contribution'])]})
    assert _item(answered)['status'] == 'answered'


def test_a_table_without_accounts_or_an_amount_column_is_still_the_managers(tmp_path):
    """Opposite direction: the Huachen regional sheets (region × budget columns, no account column) still give
    the engine nothing a field map could fix, so they stay bindings_without_engine_rows for the manager."""
    case = _mapped_column_case(tmp_path, {'regional_budget': REGIONAL_TABLE},
                               [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}])
    item = _item(check_requirements(case.analysis, case.request))

    assert [(path['path'], path['blockers']) for path in item['evidence_paths']['blocked']] == [
        ('run_metric_result_set', ['bindings_without_engine_rows'])]
    assert item['awaiting_manager'] == ['bindings_without_engine_rows']


def _legacy_revenue(tmp_path):
    analysis = AnalysisStore(TaskStore(tmp_path / 'var').create(title='legacy'))
    budget = _workbook(analysis, tmp_path, 'budget', {'01·年度预算总表': {'A12': '营业收入', 'I12': 44163.6526}})
    close = _workbook(analysis, tmp_path, 'close', {'04·合并利润表': {'B5': 414696250}})
    datasets = {'budget': budget, 'close': close}
    legacy = _legacy_drilldown_record(analysis, {alias: dataset['id'] for alias, dataset in datasets.items()}, [
        {'id': 'revenue_2026_08', 'metric': 'revenue', 'label': '8月收入', 'dimensions': {'drilldown': '城市公司'},
         'organizations': ['集团合并'], 'periods': ['2026-08'], 'scenarios': ['actual_2026_08', 'budget_2026_08'],
         'requires_drilldown': False}])
    return analysis, datasets, legacy


def _legacy_draft(run, datasets, **extra):
    claims = [_claim(run, row=0, column='value', value='44163.6526'), _claim(run, row=1, column='value', value='41469.6250')]
    recipes = [_recipe(datasets['budget'], '01·年度预算总表', 'I12', run, 0, recipe_id='budget'),
               _recipe(datasets['close'], '04·合并利润表', 'B5', run, 1, scale='0.0001', recipe_id='actual')]
    return {'title': '8月收入', 'body': '8月收入预算 44163.6526 万元，实际 41469.6250 万元。', 'run_ids': [run['id']],
            'claims': claims, 'evidence_recipes': recipes, **extra}


def _fixup(saved, code):
    return next(fixup for action in saved['completion']['actions'] for fixup in action.get('fixups', [])
                if fixup['code'] == code)


def test_a_draft_revision_after_a_legacy_requirement_revision_can_complete(tmp_path):
    """Round 8: revise_requirement_dimension sends the assistant to re-save the requirement; its next draft
    revision (parent_id, as the tool says) inherited the legacy requirements_id, so scope_changed stayed
    True, requirements_changed said nothing about requirements_id (which neither tool schema exposed) and
    the next repair stalled. The fixups now name the version to pass, and following them completes."""
    analysis, datasets, legacy = _legacy_revenue(tmp_path)
    service = FinanceStore(analysis.task)
    first_run = _script_run(analysis, datasets, REVENUE_ROWS, suffix='legacy-1', requirements_id=legacy['id'])
    first = service.save_explanation_draft(_legacy_draft(first_run, datasets))
    revise = _fixup(first, 'revise_requirement_dimension')
    listed = service.analysis_requirements_list({})['current']
    current = service.analysis_requirements_save({'question': listed['question'], 'scope': listed['scope'],
                                                  'bindings': listed['bindings'], 'parent_id': listed['id'],
                                                  'items': [revise['suggested_item']]})
    run = _script_run(analysis, datasets, REVENUE_ROWS, suffix='legacy-2', requirements_id=current['id'],
                      requirements_semantic_fingerprint=current['semantic_fingerprint'])

    pinned = service.save_explanation_draft(_legacy_draft(run, datasets, parent_id=first['id']))
    repin = _fixup(pinned, 'repin_requirements')
    followed = service.save_explanation_draft(_legacy_draft(run, datasets, parent_id=pinned['id'],
                                                            requirements_id=repin['requirements_id']))

    assert 'requirements_id' in revise['after_save']
    assert pinned['requirements_id'] == legacy['id']
    assert pinned['explanation_check']['requirements']['scope_changed'] is True
    assert repin['requirements_id'] == current['id'] and repin['draft_requirements_id'] == legacy['id']
    changed = next(action for action in pinned['completion']['actions'] if action['code'] == 'requirements_changed')
    assert 'requirements_id' in changed['message'] and current['id'] in changed['message']
    assert followed['requirements_id'] == current['id']
    assert followed['explanation_check']['requirements']['scope_changed'] is False
    assert followed['completion']['status'] == 'complete'


def test_a_revision_that_names_no_requirements_id_keeps_its_parents_pin(tmp_path):
    """Opposite direction: a revision without requirements_id is still checked as written for its parent's
    version (the manager's edits keep the 旧范围 banner); only naming the version re-pins it."""
    analysis, datasets, legacy = _legacy_revenue(tmp_path)
    service = FinanceStore(analysis.task)
    first_run = _script_run(analysis, datasets, REVENUE_ROWS, suffix='legacy-1', requirements_id=legacy['id'])
    first = service.save_explanation_draft(_legacy_draft(first_run, datasets))
    listed = service.analysis_requirements_list({})['current']
    service.analysis_requirements_save({'question': listed['question'], 'scope': listed['scope'],
                                        'bindings': listed['bindings'], 'parent_id': listed['id'],
                                        'items': [_fixup(first, 'revise_requirement_dimension')['suggested_item']]})

    revised = service.save_explanation_draft(_legacy_draft(first_run, datasets, parent_id=first['id']))

    assert revised['requirements_id'] == legacy['id']
    assert revised['explanation_check']['requirements']['scope_changed'] is True
    assert revised['completion']['status'] != 'complete'


def test_the_draft_tools_expose_requirements_id():
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')

    assert 'requirements_id' in draft['inputSchema']['properties']
    assert 'requirements_id' in draft['description']
    section = tools[tools.index('save_explanation_draft: specTool'):tools.index('finance_background_save: specTool')]
    assert 'requirements_id: text(' in section
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools


def test_a_draft_policy_10_completed_on_a_revenue_account_total_is_checked_again(tmp_path):
    """Policy 10 completed a revenue draft that cited run_metric account_total. The rule changed, so a resend
    must not replay that verdict."""
    from foundry.analysis import _hash
    from foundry.finance_completion import COMPLETION_POLICY_VERSION
    from foundry.fsutil import write_json_atomic

    case = _pnl_account_case(tmp_path, 'revenue')
    run, claim = _account_total_claim(case.service, case.context, 'revenue')
    request = {'title': 't', 'body': f'8 月营业收入 {claim["value"]} 元。', 'run_ids': [run['id']], 'claims': [claim]}
    first = case.service.save_explanation_draft(request)
    assert first['check_policy_version'] == COMPLETION_POLICY_VERSION == 11
    analysis = case.service.analysis
    path = analysis._object_path('drafts', first['id'])
    stored = {key: value for key, value in json.loads(path.read_text()).items() if key != '_integrity_hash'}
    check = stored['explanation_check']
    old = {**check, 'status': 'pass', 'issues': [], 'requirements': {
        **check['requirements'], 'coverage': {'status': 'pass'}, 'original_requirements_completed': True,
        'items': [{**item, 'status': 'answered'} for item in check['requirements']['items']]}}
    record = {**stored, 'check_policy_version': 10, 'explanation_check': old, 'quality': old}
    write_json_atomic(path, {**record, '_integrity_hash': _hash(record)})

    again = case.service.save_explanation_draft(request)

    assert again.get('replayed') is not True
    assert _item(again['explanation_check']['requirements'])['status'] == 'pending'
    assert again['completion']['status'] != 'complete'


def test_tool_descriptions_state_the_round_8_rules():
    """The tools say which paths answer: account_total only for ledger-account names and only unfiltered (or
    filtered to the requirement itself); an estimate beside another number stays an estimate; a detail table
    whose amount column needs a field_map is the assistant's to open; a revision names requirements_id."""
    from foundry.finance_mcp import _tools

    tools = (ROOT / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8')
    preset = (ROOT / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(encoding='utf-8')
    draft = next(tool for tool in _tools() if tool['name'] == 'save_explanation_draft')['description']

    assert 'not revenue/cost/expense/profit, which only (1) and (2) answer' in draft
    assert '不是 revenue、cost、expense、profit 这类规范指标名；这四项只按①②作答' in tools
    assert 'revenue、cost、expense、profit四项不走这条路' in preset
    assert 'filters may only restate' in draft and 'filters 只能写要求本身的组织、期间、情景或维度' in tools
    assert 'keeps the grain estimated until the manager accepts it' in draft
    assert '该组合仍按估算计' in tools and '该组合仍按估算计' in preset
    for text in (draft, tools, preset):
        assert 'amount_column_unmapped' in text and 'field_map' in text
    assert 'requirements_id names the current one' in draft
    assert 'requirements_id 为当前版本 id' in tools and 'requirements_id为当前版本id' in preset
    assert 'required_scope' in draft and 'required_scope' in tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'finance-tools.js').read_text(encoding='utf-8') == tools
    assert (ROOT / 'foundry' / 'resources' / 'dsh-plugin' / 'presets' / 'analysis' / 'agent.cordis.yml').read_text(
        encoding='utf-8') == preset
