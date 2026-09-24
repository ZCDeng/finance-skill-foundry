"""Phase 1 requirement evidence paths (decisions of 2026-09-24).

Revenue/profit/cost/expense are answered only by finance-engine closure or by a cited cell backed by a
passing, server-evaluated direct/sum/diff recipe on the requirement's own snapshots with a unit scale.
Every tightening has its opposite here, and every piece of guidance is followed literally once.
"""
import json
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


@pytest.mark.parametrize('label', ['收入达成率', '销售费用率', 'expense_ratio', 'other_income'])
def test_ratio_and_other_labels_keep_the_phase_1_script_rule(analysis, tmp_path, label):
    """Decision 4: script ratio values are not tightened in phase 1, so the amount gate must not swallow
    ratios named after an amount, nor non-P&L-class metrics such as other_income."""
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


def _estimate_case(analysis, tmp_path, *, declare=True, declaration=None, cite_estimate=True, period='2026-01:2026-08'):
    """Huachen revenue_1_8 in miniature: group actual/budget and East actual from the source; the East
    1-8 budget exists only as East full-year budget × group 1-8 budget progress (300 ÷ 480 = 0.625)."""
    budget = _workbook(analysis, tmp_path, 'budget', {
        '01·年度预算总表': {'B12': 100, 'C12': 200, 'N12': 480},
        '05·区域预算分解': {'C5': 180576},
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
                        'factor_recipe_id': 'phasing', 'business_key': key})
    values = ['325644', '300', '109742.028', '112860.000', '0.625']
    rows_cited = range(5) if cite_estimate else (0, 1, 2)
    claims = [_claim(run, row=index, column='value', value=values[index]) for index in rows_cited]
    return SimpleNamespace(requirement=requirement, run=run, spec={
        'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims, 'evidence_recipes': recipes})
