"""Task coverage cannot be hidden by narrowing a draft's run list."""
import json
from decimal import Decimal

import pytest

from foundry.analysis import AnalysisStore
from foundry.analysis import _new
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.finance_requirements import (
    augment_quality,
    check_requirements,
    latest_requirements,
    save_requirements,
)
from foundry.task import TaskStore


@pytest.fixture
def analysis(tmp_path):
    return AnalysisStore(TaskStore(tmp_path / 'var').create(title='利润分析'))


def spec(**updates):
    return {'question': '解释利润变动并下钻利润', 'scope': {'ledger': 'L1'},
            'items': [{'id': 'profit', 'metric': 'profit', 'requires_drilldown': True}], **updates}


def _run(analysis, **updates):
    # Closure only counts for finance-engine runs; a script run must say engine='python' explicitly.
    record = _new(
        analysis.task,
        engine='finance',
        execution_status='succeeded',
        output_hash='hash-' + updates.get('id_suffix', '1'),
        bindings={'actual': 'actual-dataset', 'budget': 'budget-dataset'},
        finance_scope={
            'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                       'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
            'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                       'currency': 'CNY', 'unit': '万元', 'scenario': 'budget'},
        },
        result={
            'method': 'revenue_minus_cost_minus_expense',
            'columns': ['metric', 'actual', 'baseline', 'contribution'],
            'rows': [
                {'metric': 'revenue', 'actual': '120', 'baseline': '100', 'contribution': '20'},
                {'metric': 'cost', 'actual': '70', 'baseline': '60', 'contribution': '-10'},
                {'metric': 'expense', 'actual': '20', 'baseline': '15', 'contribution': '-5'},
                {'metric': 'profit', 'actual': '30', 'baseline': '25', 'contribution': '5'},
            ],
        },
    )
    record.update({key: value for key, value in updates.items() if key != 'id_suffix'})
    return analysis._write(analysis._object_path('runs', record['id']), record)


def _claim(run, row=3, column='contribution', value='5'):
    return {'basis': 'calculation', 'run_id': run['id'], 'row': row, 'column': column, 'value': value}


def _verified_source(analysis, location):
    record = _new(analysis.task, location=location, status='verified', sources=[{'dataset_id': 'actual-dataset'}])
    return analysis._write(analysis._object_path('evidence_checks', record['id']), record)


def _paged_source(analysis, location, *, offset, read_count, total, has_more):
    record = _new(analysis.task, location=location, status='verified',
                  sources=[{'dataset_id': 'actual-dataset'}],
                  offset=offset, read_count=read_count, total=total, has_more=has_more)
    return analysis._write(analysis._object_path('evidence_checks', record['id']), record)


def test_requirements_are_immutable_versions_and_reject_stale_updates(analysis):
    first = save_requirements(analysis, spec())
    second = save_requirements(analysis, spec(parent_id=first['id'], question='解释本期利润'))
    assert latest_requirements(analysis)['id'] == second['id']
    assert analysis._get('requirements', first['id'])['question'] != second['question']
    with pytest.raises(FoundryError, match='latest'):
        save_requirements(analysis, spec(parent_id=first['id']))


def test_omitting_all_runs_still_reports_missing_required_profit(analysis):
    requirement = save_requirements(analysis, spec())
    result = check_requirements(analysis, {'body': '已完成', 'run_ids': [], 'claims': []})
    assert result['requirements_id'] == requirement['id']
    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'


def test_removed_item_preserves_original_obligation(analysis):
    first = save_requirements(analysis, spec())
    second = save_requirements(analysis, spec(parent_id=first['id'], items=[], change_reason='经理改为只核对范围'))
    assert second['removed_item_ids'] == ['profit']
    result = check_requirements(analysis, {'requirements_id': first['id'], 'run_ids': [], 'claims': []})
    assert result['scope_changed'] is True
    assert result['original_requirements_completed'] is False


def test_removed_item_ids_accumulate_across_versions(analysis):
    first = save_requirements(analysis, spec(items=[
        {'id': 'profit', 'metric': 'profit', 'requires_drilldown': True},
        {'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False},
        {'id': 'expense', 'metric': 'expense', 'requires_drilldown': False},
    ]))
    second = save_requirements(analysis, spec(
        parent_id=first['id'],
        items=[
            {'id': 'profit', 'metric': 'profit', 'requires_drilldown': True},
            {'id': 'expense', 'metric': 'expense', 'requires_drilldown': False},
        ],
        change_reason='收入已由经营报表单独覆盖',
    ))
    third = save_requirements(analysis, spec(
        parent_id=second['id'],
        items=[{'id': 'expense', 'metric': 'expense', 'requires_drilldown': False}],
        change_reason='利润改由经营复盘覆盖',
    ))

    assert third['removed_item_ids'] == ['profit', 'revenue']


def test_unrelated_revision_after_removed_item_does_not_require_another_removal_reason(analysis):
    first = save_requirements(analysis, spec(items=[
        {'id': 'profit', 'metric': 'profit'},
        {'id': 'revenue', 'metric': 'revenue'},
    ]))
    reduced = save_requirements(analysis, spec(parent_id=first['id'],
        items=[{'id': 'profit', 'metric': 'profit'}], change_reason='经理取消收入要求'))
    revised = save_requirements(analysis, spec(parent_id=reduced['id'],
        items=[{'id': 'profit', 'metric': 'profit', 'label': '营业利润'}]))

    assert revised['removed_item_ids'] == ['revenue']
    assert revised['change_reason'] == ''


def test_metric_key_matches_only_declared_metric_aliases_for_generic_values(analysis):
    from foundry.finance_requirements import _matches

    assert _matches({'metric': 'profit', 'dimensions': {}}, {'metric_key': 'operating_profit', 'value': '1'}, 'value')
    assert _matches({'metric': 'profit', 'dimensions': {}}, {'metric_key': 'gross_profit', 'value': '1'}, 'value')
    assert _matches({'metric': 'profit', 'dimensions': {'metric_key': 'operating_profit'}},
                    {'metric_key': 'operating_profit', 'value': '1'}, 'value')
    assert not _matches({'metric': 'profit', 'dimensions': {'metric_key': 'operating_profit'}},
                        {'metric_key': 'gross_profit', 'value': '1'}, 'value')
    assert not _matches({'metric': 'profit', 'dimensions': {'metric_key': 'revenue'}},
                        {'metric_key': 'revenue', 'value': '1'}, 'value')
    assert _matches({'metric': 'expense', 'dimensions': {}}, {'metric_key': 'period_expense', 'value': '1'}, 'value')
    assert _matches({'metric': 'other_income', 'dimensions': {}}, {'metric_key': 'other_income_and_gains_4items', 'value': '1'}, 'value')
    assert _matches({'metric': 'ratio', 'dimensions': {}}, {'metric_key': 'achievement_ratio', 'value': '0.9'}, 'value')
    assert _matches({'metric': 'ratio', 'dimensions': {'metric_key': 'revenue'}},
                    {'metric_key': 'revenue', 'scenario': 'achievement_ratio', 'value': '0.9'}, 'value')
    assert _matches({'metric': 'ratio', 'dimensions': {'metric_key': 'revenue'}},
                    {'metric_key': 'revenue', 'scenario': 'achievement_ratio_estimate', 'value': '0.9'}, 'value')
    assert _matches({'metric': 'ratio', 'dimensions': {'metric_key': 'revenue'}},
                    {'metric_key': 'revenue', 'scenario': 'budget_phase_ratio', 'value': '0.9'}, 'value')
    assert not _matches({'metric': 'ratio', 'dimensions': {'metric_key': 'revenue'}},
                        {'metric_key': 'revenue', 'scenario': 'actual', 'value': '120'}, 'value')
    assert not _matches({'metric': 'ratio', 'dimensions': {'metric_key': 'revenue'}},
                        {'metric_key': 'revenue', 'value': '120'}, 'value')

    assert not _matches({'metric': 'revenue', 'dimensions': {}}, {'metric_key': 'not_revenue', 'value': '1'}, 'value')
    assert not _matches({'metric': 'revenue', 'dimensions': {}}, {'metric_key': 'revenue_noise', 'value': '1'}, 'value')
    assert not _matches({'metric': 'revenue', 'dimensions': {}}, {'metric_key': 'revenue', 'note': '1'}, 'note')


@pytest.mark.parametrize('first_period', ['2026-07', '2026-01:2026-08'])
def test_generic_ratio_periods_require_each_declared_period(analysis, first_period):
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'two_period_ratios', 'metric': 'ratio',
                'periods': [first_period, '2026-08'], 'requires_drilldown': True}],
    ))
    run = _run(analysis, id_suffix='ratio-periods', finance_scope={
        'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'},
    }, result={
        'columns': ['period', 'metric_key', 'value'],
        'rows': [
            {'period': first_period, 'metric_key': 'ratio', 'value': '0.8'},
            {'period': '2026-08', 'metric_key': 'ratio', 'value': '0.9'},
            {'period': '2026-09', 'metric_key': 'ratio', 'value': '1.0'},
        ],
    })
    first = _claim(run, row=0, column='value', value='0.8')
    second = _claim(run, row=1, column='value', value='0.9')
    out_of_scope = _claim(run, row=2, column='value', value='1.0')

    partial = check_requirements(analysis, {'requirements_id': requirement['id'],
                                            'run_ids': [run['id']], 'claims': [first]})
    wrong_period = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                 'run_ids': [run['id']], 'claims': [first, out_of_scope]})
    complete = check_requirements(analysis, {'requirements_id': requirement['id'],
                                             'run_ids': [run['id']], 'claims': [first, second]})

    assert partial['items'][0]['status'] == 'pending'
    assert wrong_period['items'][0]['status'] == 'pending'
    assert complete['items'][0]['status'] == 'answered'
    assert {location['row'] for location in complete['items'][0]['locations']} == {0, 1}
    assert complete['provenance']['status'] == 'needs_attention'

    first_location, second_location = sorted(complete['items'][0]['locations'], key=lambda location: location['row'])
    _verified_source(analysis, {key: first_location[key] for key in ('run_id', 'row', 'column', 'output_hash')})
    one_source = check_requirements(analysis, {'requirements_id': requirement['id'],
                                               'run_ids': [run['id']], 'claims': [first, second]})
    assert one_source['provenance']['status'] == 'needs_attention'

    _verified_source(analysis, {key: second_location[key] for key in ('run_id', 'row', 'column', 'output_hash')})
    both_sources = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                 'run_ids': [run['id']], 'claims': [first, second]})
    assert both_sources['provenance']['status'] == 'pass'


def test_generic_requirement_requires_each_organization_and_period(analysis):
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'regional_ratio', 'metric': 'ratio',
                'organizations': ['总部', '华东'], 'periods': ['2026-07', '2026-08'],
                'requires_drilldown': True}],
    ))
    run = _run(analysis, id_suffix='regional-ratio', finance_scope={
        'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'},
    }, result={
        'columns': ['organization', 'period', 'metric_key', 'value'],
        'rows': [
            {'organization': organization, 'period': period, 'metric_key': 'ratio', 'value': str(index + 1)}
            for index, (organization, period) in enumerate([
                ('总部', '2026-07'), ('总部', '2026-08'),
                ('华东', '2026-07'), ('华东', '2026-08'),
                ('华南', '2026-08'),
            ])
        ],
    })
    claims = [_claim(run, row=index, column='value', value=str(index + 1)) for index in range(5)]

    partial = check_requirements(analysis, {'requirements_id': requirement['id'],
                                            'run_ids': [run['id']], 'claims': claims[:3]})
    wrong_organization = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                       'run_ids': [run['id']], 'claims': claims[:3] + claims[4:]})
    complete = check_requirements(analysis, {'requirements_id': requirement['id'],
                                             'run_ids': [run['id']], 'claims': claims[:4]})

    assert requirement['items'][0]['organizations'] == ['总部', '华东']
    assert partial['items'][0]['status'] == 'pending'
    assert wrong_organization['items'][0]['status'] == 'pending'
    assert complete['items'][0]['status'] == 'answered'
    assert {location['row'] for location in complete['items'][0]['locations']} == {0, 1, 2, 3}
    assert complete['provenance']['status'] == 'needs_attention'

    for location in complete['items'][0]['locations'][:3]:
        _verified_source(analysis, {key: location[key] for key in ('run_id', 'row', 'column', 'output_hash')})
    one_missing_source = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                       'run_ids': [run['id']], 'claims': claims[:4]})
    assert one_missing_source['provenance']['status'] == 'needs_attention'

    last = complete['items'][0]['locations'][3]
    _verified_source(analysis, {key: last[key] for key in ('run_id', 'row', 'column', 'output_hash')})
    sourced = check_requirements(analysis, {'requirements_id': requirement['id'],
                                            'run_ids': [run['id']], 'claims': claims[:4]})
    assert sourced['provenance']['status'] == 'pass'


def test_generic_requirement_requires_each_declared_scenario_grain(analysis):
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'scenario_ratio', 'metric': 'ratio',
                'organizations': ['总部'], 'periods': ['2026-08'], 'scenarios': ['actual', 'budget'],
                'requires_drilldown': True}],
    ))
    run = _run(analysis, id_suffix='scenario-ratio', finance_scope={
        'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'},
    }, result={
        'columns': ['organization', 'period', 'scenario', 'metric_key', 'value'],
        'rows': [
            {'organization': '总部', 'period': '2026-08', 'scenario': 'actual', 'metric_key': 'ratio', 'value': '0.8'},
            {'organization': '总部', 'period': '2026-08', 'scenario': 'budget', 'metric_key': 'ratio', 'value': '0.9'},
            {'organization': '总部', 'period': '2026-08', 'scenario': 'forecast', 'metric_key': 'ratio', 'value': '1.1'},
        ],
    })
    actual = _claim(run, row=0, column='value', value='0.8')
    budget = _claim(run, row=1, column='value', value='0.9')
    forecast = _claim(run, row=2, column='value', value='1.1')

    assert requirement['items'][0]['scenarios'] == ['actual', 'budget']
    partial = check_requirements(analysis, {'requirements_id': requirement['id'],
                                            'run_ids': [run['id']], 'claims': [actual]})
    wrong_scenario = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [run['id']], 'claims': [actual, forecast]})
    complete = check_requirements(analysis, {'requirements_id': requirement['id'],
                                             'run_ids': [run['id']], 'claims': [actual, budget]})

    assert partial['items'][0]['status'] == 'pending'
    assert wrong_scenario['items'][0]['status'] == 'pending'
    assert complete['items'][0]['status'] == 'answered'
    assert {location['row'] for location in complete['items'][0]['locations']} == {0, 1}
    assert complete['provenance']['status'] == 'needs_attention'

    _verified_source(analysis, {key: complete['items'][0]['locations'][0][key]
                                for key in ('run_id', 'row', 'column', 'output_hash')})
    one_source = check_requirements(analysis, {'requirements_id': requirement['id'],
                                               'run_ids': [run['id']], 'claims': [actual, budget]})
    assert one_source['provenance']['status'] == 'needs_attention'

    _verified_source(analysis, {key: complete['items'][0]['locations'][1][key]
                                for key in ('run_id', 'row', 'column', 'output_hash')})
    sourced = check_requirements(analysis, {'requirements_id': requirement['id'],
                                            'run_ids': [run['id']], 'claims': [actual, budget]})
    assert sourced['provenance']['status'] == 'pass'


def test_pending_grain_requirement_names_missing_combinations_and_row_keys(analysis):
    """Huachen rerun: wide 收入_1-8月实际_万元 rows answered nothing and the warning said only “尚未提供”."""
    from foundry.finance_requirements import _unanswered_message

    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'scenario_ratio', 'metric': 'ratio',
                'organizations': ['总部'], 'periods': ['2026-08'], 'scenarios': ['actual', 'budget'],
                'requires_drilldown': True}],
    ))
    run = _run(analysis, id_suffix='scenario-missing', finance_scope={
        'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'},
    }, result={
        'columns': ['organization', 'period', 'scenario', 'metric_key', 'value'],
        'rows': [
            {'organization': '总部', 'period': '2026-08', 'scenario': 'actual', 'metric_key': 'ratio', 'value': '0.8'},
        ],
    })

    partial = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                            'claims': [_claim(run, row=0, column='value', value='0.8')]})
    item = partial['items'][0]
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')

    assert item['status'] == 'pending'
    assert item['missing_grains'] == [{'organization': '总部', 'period': '2026-08', 'scenario': 'budget'}]
    assert fixup['missing_count'] == 1
    assert fixup['row_keys'] == ['metric_key', 'organization', 'period', 'scenario', 'value']
    assert '1 个要求组合没有已引用的结果行（如 总部、2026-08、budget）' in _unanswered_message(item)

    complete = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': []})
    assert len(complete['items'][0]['missing_grains']) == 2


def _workbook(analysis, tmp_path, name, sheets):
    """An archived workbook snapshot, as the manager files it; recipes recompute from its bytes."""
    from openpyxl import Workbook

    book = Workbook()
    for index, (title, cells) in enumerate(sheets.items()):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = title
        for coordinate, value in cells.items():
            sheet[coordinate] = value
    source = tmp_path / f'{name}.xlsx'
    book.save(source)
    book.close()
    return analysis.add_dataset(source, name=name, metadata={'mode': 'workbook'})


def _script_run(analysis, datasets, rows, *, suffix, **updates):
    """A python run on the requirement's own bound snapshots; it has no finance_scope."""
    record = _new(
        analysis.task,
        engine='python',
        execution_status='succeeded',
        reproducibility_status='unverified',
        assumptions=[],
        output_hash='script-' + suffix,
        bindings={alias: dataset['id'] for alias, dataset in datasets.items()},
        input_hashes={alias: dataset['data_hash'] for alias, dataset in datasets.items()},
        source_hashes={alias: dataset['source_hash'] for alias, dataset in datasets.items()},
        result={'columns': list(dict.fromkeys(key for row in rows for key in row)), 'rows': rows},
    )
    record.update(updates)
    return analysis._write(analysis._object_path('runs', record['id']), record)


def _recipe(dataset, sheet, cell_range, run, row, *, kind='direct', recipe_id=None, **extra):
    return {'id': recipe_id or f'{kind}-{row}', 'kind': kind, 'dataset_id': dataset['id'],
            'source_hash': dataset['source_hash'], 'sheet': sheet, 'range': cell_range,
            'claim': {'run_id': run['id'], 'row': row, 'column': 'value'}, **extra}


def test_cited_rows_missing_dimension_and_scope_fields_are_named_and_fixing_them_answers(analysis, tmp_path):
    """Huachen rerun: long-form rows had metric_key/organization/period/scenario/value but not the
    dimension and scope fields the matcher needs, so nothing matched. The named fields must be exactly
    what makes the matcher accept the row. Decision 1 changed two things here: a hierarchy level such
    as drilldown is refused at save time (it is no longer a field to stamp on rows), and the ledger of a
    run without finance_scope is proven by its bound snapshot hashes, so it is never named as a row field.
    Review round 3 inverted the amount gate: other_income is an amount, so the fixed row also needs the
    source recipe the guidance names (a script value alone no longer answers it)."""
    from foundry.finance_requirements import _unanswered_message

    source = _workbook(analysis, tmp_path, 'budget', {'预算': {'A1': '其他收益', 'B1': 2902.5}})
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1', 'currency': 'CNY', 'unit': '万元'},
        bindings={'budget': source['id']},
        items=[{'id': 'other_income_1_8', 'metric': 'other_income', 'dimensions': {'product': '物业费'},
                'organizations': ['集团合并'], 'periods': ['2026-01:2026-08'], 'scenarios': ['actual_1_8'],
                'requires_drilldown': False}],
    ))
    bare = {'metric_key': 'other_income', 'organization': '集团合并', 'period': '2026-01:2026-08',
            'scenario': 'actual_1_8', 'value': '2902.5', 'unit': '万元'}
    run = _script_run(analysis, {'budget': source}, [bare, {**bare, 'product': '物业费', 'currency': 'CNY'}],
                      suffix='long-form')

    gap = check_requirements(analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                        'claims': [_claim(run, row=0, column='value', value='2902.5')]})
    item = gap['items'][0]
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')

    assert item['status'] == 'pending'
    assert item['row_field_gaps'] == {'product': '物业费', 'currency': 'CNY'}
    assert fixup['row_fields'] == {'product': '物业费'}
    assert fixup['scope_fields'] == {'currency': 'CNY', 'unit': '万元'}
    assert fixup['row_keys'] == ['metric_key', 'organization', 'period', 'scenario', 'product', 'value']
    assert fixup['metric_key'] == 'other_income'
    assert fixup['reason'] == 'cited_rows_miss_required_fields'
    assert fixup['requires_closed_evidence'] is True
    assert fixup['accepted_evidence'] == ['evidence_recipe']
    assert '已引用的行还缺少或不一致的字段：product=物业费、currency=CNY。' in _unanswered_message(item)
    assert 'ledger' not in _unanswered_message(item)

    cited = {'requirements_id': requirement['id'], 'run_ids': [run['id']],
             'claims': [_claim(run, row=1, column='value', value='2902.5')]}
    script_only = check_requirements(analysis, cited)['items'][0]
    assert script_only['status'] == 'pending'
    assert script_only['uncounted_grains'][0]['reasons'] == ['script_output_without_recipe']
    fixed = check_requirements(analysis, {**cited, 'evidence_recipes': [_recipe(source, '预算', 'B1', run, 1)]})
    assert fixed['items'][0]['status'] == 'answered'
    assert 'missing_grains' not in fixed['items'][0]


def test_revenue_script_rows_need_a_source_recipe_and_never_point_at_run_metric(analysis, tmp_path):
    """PR #17 pointed revenue/profit/cost/expense items at run_metric, whose management_pnl rows can never
    close for these metrics. Decision 1: a cited cell backed by a passing, server-evaluated direct/sum/diff
    recipe is answered evidence; the guidance names that path and the exact cells, and following it answers."""
    from foundry.finance_requirements import _unanswered_message

    budget = _workbook(analysis, tmp_path, 'budget', {'预算': {'B12': 40000.5, 'C12': 4163.1526}})
    close = _workbook(analysis, tmp_path, 'close', {'利润表': {'C5': 3256440000}})
    requirement = save_requirements(analysis, spec(
        scope={'ledger': '华宸物业预算工作簿与月结套表', 'currency': 'CNY', 'unit': '万元'},
        bindings={'budget': budget['id'], 'close': close['id']},
        items=[{'id': 'revenue_1_8', 'metric': 'revenue',
                'organizations': ['集团合并'], 'periods': ['2026-01:2026-08'], 'scenarios': ['actual_1_8', 'budget_1_8'],
                'requires_drilldown': True}],
    ))
    rows = [
        {'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026-01:2026-08', 'scenario': 'actual_1_8',
         'value': '325644.0000', 'unit': '万元', 'currency': 'CNY'},
        {'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8',
         'value': '44163.6526', 'unit': '万元', 'currency': 'CNY'},
    ]
    run = _script_run(analysis, {'budget': budget, 'close': close}, rows, suffix='script-values')
    claims = [_claim(run, row=0, column='value', value='325644.0000'),
              _claim(run, row=1, column='value', value='44163.6526')]
    base = {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims}

    result = check_requirements(analysis, base)
    item = result['items'][0]
    fixup = next(f for f in item['fixups'] if f['code'] == 'add_requirement_rows')
    message = _unanswered_message(item)

    assert item['status'] == 'pending'
    assert 'missing_grains' not in item
    assert item['uncounted_grains'] == [
        {'organization': '集团合并', 'period': '2026-01:2026-08', 'scenario': 'actual_1_8',
         'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']},
        {'organization': '集团合并', 'period': '2026-01:2026-08', 'scenario': 'budget_1_8',
         'statuses': ['not_applicable'], 'reasons': ['script_output_without_recipe']},
    ]
    assert fixup['reason'] == 'cited_result_not_counted'
    assert fixup['requires_closed_evidence'] is True
    assert fixup['accepted_evidence'] == ['evidence_recipe']
    assert [(cell['row'], cell['value']) for cell in fixup['evidence_recipe_cells']] == [(0, '325644.0000'), (1, '44163.6526')]
    assert 'run_metric' not in json.dumps(item['fixups'], ensure_ascii=False)
    assert 'run_metric' not in message
    assert 'evidence_recipe（direct、sum 或 diff' in message
    assert '只有脚本输出，没有通过的来源复算规则' in message

    # Follow the fixup literally: one passing direct/sum recipe per listed cell, sources in the bindings.
    recipes = [
        _recipe(close, '利润表', 'C5', run, 0, scale='0.0001', recipe_id='actual'),
        _recipe(budget, '预算', 'B12:C12', run, 1, kind='sum', recipe_id='budget'),
    ]
    answered = check_requirements(analysis, {**base, 'evidence_recipes': recipes})
    item = answered['items'][0]
    assert item['status'] == 'answered'
    assert [location['evidence']['evidence_basis'] for location in item['locations']] == ['source_value', 'source_calculation']
    assert all(location['evidence']['mapping_review'] == 'unreviewed' for location in item['locations'])
    assert item['provenance_status'] == 'verified'
    assert answered['coverage']['status'] == 'pass'


def test_metric_key_pin_allows_long_form_ratio_rows_for_exact_scenario(analysis):
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'revenue_ratio', 'metric': 'ratio',
                'dimensions': {'metric_key': 'revenue'}, 'scenarios': ['achievement_ratio'],
                'requires_drilldown': True}],
    ))
    run = _run(analysis, id_suffix='revenue-achievement-ratio', finance_scope={
        'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'},
    }, result={
        'columns': ['metric_key', 'scenario', 'value'],
        'rows': [
            {'metric_key': 'revenue', 'scenario': 'achievement_ratio', 'value': '0.91'},
            {'metric_key': 'operating_profit', 'scenario': 'achievement_ratio', 'value': '0.82'},
            {'metric_key': 'revenue', 'scenario': 'actual', 'value': '120'},
        ],
    })
    revenue_ratio = _claim(run, row=0, column='value', value='0.91')
    profit_ratio = _claim(run, row=1, column='value', value='0.82')
    revenue_actual = _claim(run, row=2, column='value', value='120')

    profit_ratio_result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                        'run_ids': [run['id']], 'claims': [profit_ratio]})
    non_ratio_result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                     'run_ids': [run['id']], 'claims': [revenue_actual]})
    answered = check_requirements(analysis, {'requirements_id': requirement['id'],
                                             'run_ids': [run['id']], 'claims': [revenue_ratio]})
    auto_fixup = check_requirements(analysis, {'requirements_id': requirement['id'],
                                               'run_ids': [run['id']], 'claims': []})

    assert profit_ratio_result['items'][0]['status'] == 'pending'
    assert non_ratio_result['items'][0]['status'] == 'pending'
    assert answered['items'][0]['status'] == 'answered'
    assert answered['items'][0]['locations'][0]['row'] == 0
    assert auto_fixup['items'][0]['status'] == 'pending'
    assert [(fixup['row'], fixup['column']) for fixup in auto_fixup['items'][0]['fixups']
            if fixup['code'] == 'add_calculation_claim'] == [(0, 'value')]


def test_ratio_metric_key_pin_without_declared_scenarios_still_requires_ratio_valued_row(analysis):
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1'},
        items=[{'id': 'revenue_ratio', 'metric': 'ratio',
                'dimensions': {'metric_key': 'revenue'}, 'requires_drilldown': True}],
    ))
    run = _run(analysis, id_suffix='revenue-ratio-no-scenario-obligation', finance_scope={
        'actual': {'ledger': 'L1'}, 'budget': {'ledger': 'L1'},
    }, result={
        'columns': ['metric_key', 'scenario', 'value'],
        'rows': [
            {'metric_key': 'revenue', 'scenario': 'actual', 'value': '120'},
            {'metric_key': 'revenue', 'scenario': 'attainment_rate', 'value': '0.91'},
        ],
    })
    actual_amount = _claim(run, row=0, column='value', value='120')
    ratio_value = _claim(run, row=1, column='value', value='0.91')

    amount_result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                  'run_ids': [run['id']], 'claims': [actual_amount]})
    answered = check_requirements(analysis, {'requirements_id': requirement['id'],
                                             'run_ids': [run['id']], 'claims': [ratio_value]})
    auto_fixup = check_requirements(analysis, {'requirements_id': requirement['id'],
                                               'run_ids': [run['id']], 'claims': []})

    assert amount_result['items'][0]['status'] == 'pending'
    assert answered['items'][0]['status'] == 'answered'
    assert answered['items'][0]['locations'][0]['row'] == 1
    assert [(fixup['row'], fixup['column']) for fixup in auto_fixup['items'][0]['fixups']
            if fixup['code'] == 'add_calculation_claim'] == [(1, 'value')]


def test_required_scenarios_are_deduped_and_must_be_non_empty_strings(analysis):
    requirement = save_requirements(analysis, spec(
        items=[{'id': 'profit', 'metric': 'profit', 'scenarios': [' actual ', 'budget', 'actual']}],
    ))
    assert requirement['items'][0]['scenarios'] == ['actual', 'budget']

    with pytest.raises(FoundryError, match='scenarios'):
        save_requirements(analysis, spec(
            parent_id=requirement['id'],
            items=[{'id': 'profit', 'metric': 'profit', 'scenarios': ['actual', '']}],
        ))


def test_semantic_fingerprint_changes_when_scenario_obligations_change(tmp_path):
    analysis = AnalysisStore(TaskStore(tmp_path / 'semantic-var').create(title='语义指纹'))
    path = tmp_path / 'semantic.json'
    path.write_text(json.dumps([{'amount': '1'}], ensure_ascii=False), encoding='utf-8')
    dataset = analysis.add_dataset(path, name='source')
    first = save_requirements(analysis, spec(
        bindings={'actual': dataset['id']},
        items=[{'id': 'profit', 'metric': 'profit', 'scenarios': ['actual']}],
    ))
    second = save_requirements(analysis, spec(
        parent_id=first['id'],
        bindings={'actual': dataset['id']},
        change_reason='补充预算场景复核',
        items=[{'id': 'profit', 'metric': 'profit', 'scenarios': ['actual', 'budget']}],
    ))

    assert first['semantic_fingerprint']
    assert first['semantic_fingerprint'] != second['semantic_fingerprint']
    assert first['semantic_basis']['items'][0]['scenarios'] == ['actual']
    assert second['semantic_basis']['items'][0]['scenarios'] == ['actual', 'budget']


def test_required_organizations_cannot_contradict_global_organization(analysis):
    with pytest.raises(FoundryError, match='organizations.*scope.organization'):
        save_requirements(analysis, spec(
            scope={'ledger': 'L1', 'organization': '总部'},
            items=[{'id': 'regional_revenue', 'metric': 'revenue',
                    'organizations': ['总部', '华东']}],
        ))


def test_required_periods_cannot_contradict_global_period(analysis):
    with pytest.raises(FoundryError, match='periods.*scope.period'):
        save_requirements(analysis, spec(
            scope={'ledger': 'L1', 'period': '2026-01:2026-08'},
            items=[{'id': 'revenue', 'metric': 'revenue',
                    'periods': ['2026-01:2026-08', '2026-08']}],
        ))


def test_default_context_scenario_scope_allows_valid_actual_budget_bridge(analysis):
    requirement = save_requirements(analysis, spec(
        scope={'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
               'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
    ))
    run = _run(analysis)

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': [_claim(run)]})

    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'
    assert result['items'][0]['locations'][0]['evidence']['group_status'] == 'complete'


def test_missing_data_not_applicable_and_pending_are_evidence_based(analysis):
    save_requirements(analysis, spec(items=[
        {'id': 'profit_missing', 'metric': 'profit', 'requires_drilldown': False},
        {'id': 'profit_unsupported', 'metric': 'profit', 'requires_drilldown': False,
         'dimensions': {'line': 'sql'}},
        {'id': 'profit_pending', 'metric': 'profit', 'requires_drilldown': False,
         'dimensions': {'line': 'never_claimed'}},
    ]))
    missing = _run(analysis, id_suffix='missing', result={
        'method': 'revenue_minus_cost_minus_expense',
        'columns': ['metric', 'actual', 'baseline', 'contribution'],
        'rows': [{'metric': 'profit', 'actual': '30', 'baseline': '25', 'contribution': '5'}],
    })
    unsupported = _run(analysis, id_suffix='unsupported', result={
        'method': 'free_sql',
        'columns': ['line', 'metric', 'value'],
        'rows': [{'line': 'sql', 'metric': 'profit', 'value': '5'}],
    })

    result = check_requirements(analysis, {'run_ids': [missing['id'], unsupported['id']],
                                           'claims': [_claim(missing, row=0),
                                                      _claim(unsupported, row=0, column='value')]})
    by_id = {item['id']: item for item in result['items']}

    assert by_id['profit_missing']['status'] == 'missing_data'
    assert by_id['profit_unsupported']['status'] == 'not_applicable'
    assert by_id['profit_pending']['status'] == 'pending'
    assert result['coverage']['status'] == 'needs_attention'


def test_scope_requires_comparison_sides_to_match_excluding_scenario(analysis):
    save_requirements(analysis, spec(scope={'ledger': 'L1', 'period': '2026-09', 'unit': '万元'}))
    mismatched = _run(analysis, finance_scope={
        'actual': {'ledger': 'L1', 'period': '2026-09', 'unit': '万元', 'scenario': 'actual'},
        'budget': {'ledger': 'L2', 'period': '2026-09', 'unit': '万元', 'scenario': 'budget'},
    })

    result = check_requirements(analysis, {'run_ids': [mismatched['id']],
                                           'claims': [_claim(mismatched)]})

    assert result['items'][0]['status'] == 'pending'
    assert result['coverage']['status'] == 'needs_attention'


def test_flat_period_targets_actual_and_explicit_baseline_period_targets_comparison(analysis):
    save_requirements(analysis, spec(scope={'ledger': 'L1', 'organization': 'O1',
                                            'period': '2026-09', 'baseline_period': '2025-09',
                                            'currency': 'CNY', 'unit': '万元',
                                            'scenario': 'actual'}))
    yoy = _run(analysis, id_suffix='yoy', finance_scope={
        'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                   'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
        'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2025-09',
                   'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
    })
    wrong_baseline = _run(analysis, id_suffix='wrong-baseline', finance_scope={
        'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                   'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
        'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2025-08',
                   'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
    })

    passed = check_requirements(analysis, {'run_ids': [yoy['id']], 'claims': [_claim(yoy)]})
    failed = check_requirements(analysis, {'run_ids': [wrong_baseline['id']],
                                           'claims': [_claim(wrong_baseline)]})

    assert passed['coverage']['status'] == 'pass'
    assert passed['items'][0]['status'] == 'answered'
    assert failed['coverage']['status'] == 'needs_attention'
    assert failed['items'][0]['status'] == 'pending'


def test_explicit_actual_and_baseline_scope_supports_versioned_comparison_range(analysis):
    save_requirements(analysis, spec(scope={
        'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                   'currency': 'CNY', 'unit': '万元', 'scenario': 'current'},
        'baseline': {'ledger': 'L1', 'organization': 'O1', 'period': '2025-09',
                     'currency': 'CNY', 'unit': '万元', 'scenario': 'historical'},
    }))
    run = _run(analysis, finance_scope={
        'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09',
                   'currency': 'CNY', 'unit': '万元', 'scenario': 'current'},
        'baseline': {'ledger': 'L1', 'organization': 'O1', 'period': '2025-09',
                     'currency': 'CNY', 'unit': '万元', 'scenario': 'historical'},
    })

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'


def test_source_scope_matches_source_side_without_requiring_baseline(analysis):
    save_requirements(analysis, spec(scope={'source': {'source_id': 'trial-balance',
                                                       'ledger': 'L1',
                                                       'period': '2026-09'}},
                                     items=[{'id': 'custom_margin',
                                             'metric': 'custom_margin',
                                             'requires_drilldown': False}]))
    source_run = _run(analysis, id_suffix='source', finance_scope={
        'source': {'source_id': 'trial-balance', 'ledger': 'L1', 'period': '2026-09'},
    }, result={
        'method': 'sql',
        'columns': ['metric', 'value'],
        'rows': [{'metric': 'custom_margin', 'value': '0.42'}],
    })
    wrong_source = _run(analysis, id_suffix='wrong-source', finance_scope={
        'source': {'source_id': 'trial-balance', 'ledger': 'L1', 'period': '2026-08'},
    }, result={
        'method': 'sql',
        'columns': ['metric', 'value'],
        'rows': [{'metric': 'custom_margin', 'value': '0.42'}],
    })

    passed = check_requirements(analysis, {'run_ids': [source_run['id']],
                                           'claims': [_claim(source_run, row=0, column='value', value='0.42')]})
    failed = check_requirements(analysis, {'run_ids': [wrong_source['id']],
                                           'claims': [_claim(wrong_source, row=0, column='value', value='0.42')]})

    assert passed['coverage']['status'] == 'pass'
    assert passed['items'][0]['status'] == 'answered'
    assert failed['coverage']['status'] == 'needs_attention'
    assert failed['items'][0]['status'] == 'pending'


def test_bindings_allow_single_alias_but_reject_mixed_multi_binding(analysis):
    single = save_requirements(analysis, spec(bindings={'actual': 'dataset-a'}))
    single_run = _run(analysis, id_suffix='single', bindings={'source': 'dataset-a'})
    assert check_requirements(analysis, {'requirements_id': single['id'],
                                         'run_ids': [single_run['id']],
                                         'claims': [_claim(single_run)]})['items'][0]['status'] == 'answered'
    multi = save_requirements(analysis, spec(parent_id=single['id'],
        bindings={'actual': 'dataset-a', 'budget': 'dataset-b'}, change_reason='补充预算侧绑定'))
    mixed = _run(analysis, id_suffix='mixed',
                 bindings={'actual': 'dataset-a', 'budget': 'dataset-c', 'other': 'dataset-b'})

    result = check_requirements(analysis, {'requirements_id': multi['id'],
                                           'run_ids': [mixed['id']],
                                           'claims': [_claim(mixed)]})

    assert result['items'][0]['status'] == 'pending'


def test_sql_unsupported_does_not_claim_finance_closure(analysis):
    save_requirements(analysis, spec(items=[
        {'id': 'custom_margin', 'metric': 'custom_margin', 'requires_drilldown': False},
    ]))
    run = _run(analysis, result={
        'method': 'sql',
        'columns': ['metric', 'value'],
        'rows': [{'metric': 'custom_margin', 'value': '0.42'}],
    })

    result = check_requirements(analysis, {'run_ids': [run['id']],
                                           'claims': [_claim(run, row=0, column='value', value='0.42')]})
    location = result['items'][0]['locations'][0]

    assert result['items'][0]['status'] == 'answered'
    assert location['evidence']['group_status'] == 'unsupported'
    assert result['coverage']['status'] == 'pass'



def test_row_level_source_check_verifies_same_row_claim_column(analysis):
    save_requirements(analysis, spec())
    run = _run(analysis)
    _verified_source(analysis, {'run_id': run['id'], 'row': 3, 'column': None, 'output_hash': run['output_hash']})

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert result['coverage']['status'] == 'pass'
    assert result['provenance']['status'] == 'pass'
    assert result['items'][0]['provenance_status'] == 'verified'


def test_row_level_source_check_does_not_cross_row_or_hash(analysis):
    save_requirements(analysis, spec())
    run = _run(analysis)
    _verified_source(analysis, {'run_id': run['id'], 'row': 2, 'column': None, 'output_hash': run['output_hash']})
    _verified_source(analysis, {'run_id': run['id'], 'row': 3, 'column': None, 'output_hash': 'other-hash'})

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert result['coverage']['status'] == 'pass'
    assert result['provenance']['status'] == 'needs_attention'
    assert result['items'][0]['provenance_status'] == 'pending'

def test_source_read_failure_overrides_stale_verified_source(analysis):
    save_requirements(analysis, spec())
    run = _run(analysis)
    location = {'run_id': run['id'], 'row': 3, 'column': 'contribution', 'output_hash': run['output_hash']}
    _verified_source(analysis, location)

    quality = augment_quality(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)],
                                         'source_read_failures': [
                                             {'requirement_item_id': 'profit', 'message': 'source unavailable'}
                                         ]},
                              {'status': 'pass', 'issues': []})

    assert quality['requirements']['items'][0]['status'] == 'answered'
    assert quality['requirements']['items'][0]['provenance_status'] == 'failed'
    assert quality['checks']['coverage']['status'] == 'pass'
    assert quality['checks']['provenance']['status'] == 'needs_attention'
    assert any(issue['code'] == 'requested_source_missing' for issue in quality['issues'])


def test_provenance_requires_complete_paged_source_coverage(analysis):
    save_requirements(analysis, spec())
    run = _run(analysis)
    location = {'run_id': run['id'], 'row': 3, 'column': 'contribution', 'output_hash': run['output_hash']}
    _paged_source(analysis, location, offset=0, read_count=100, total=150, has_more=True)

    incomplete = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert incomplete['coverage']['status'] == 'pass'
    assert incomplete['provenance']['status'] == 'needs_attention'
    assert incomplete['items'][0]['provenance_status'] == 'pending'

    _paged_source(analysis, location, offset=100, read_count=50, total=150, has_more=False)

    complete = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert complete['coverage']['status'] == 'pass'
    assert complete['provenance']['status'] == 'pass'
    assert complete['items'][0]['provenance_status'] == 'verified'


def test_empty_removal_without_reason_is_rejected(analysis):
    first = save_requirements(analysis, spec())
    with pytest.raises(FoundryError, match='reason'):
        save_requirements(analysis, spec(parent_id=first['id'], items=[]))


def test_duplicate_item_ids_are_rejected(analysis):
    with pytest.raises(FoundryError, match='unique'):
        save_requirements(analysis, spec(items=[{'id': 'x','metric':'profit'}, {'id':'x','metric':'expense'}]))


def test_completion_reuses_same_input_and_stops_no_progress(analysis):
    from foundry.finance_completion import record_completion
    requirement = save_requirements(analysis, spec())
    quality = {'status': 'needs_attention', 'issues': [{'code': 'missing', 'message': '利润依据缺失'}],
               'requirements': {'requirements_id': requirement['id'], 'coverage': {'status': 'needs_attention'}}}
    draft = {'id':'1'*32, 'body':'待补齐', 'content_hash':'a', 'run_ids':[]}
    first = record_completion(analysis, draft, quality)
    assert first['repair_allowed']
    assert record_completion(analysis, draft, quality)['id'] == first['id']
    second = record_completion(analysis, {**draft, 'id':'2'*32, 'body':'仍待补齐'}, quality)
    assert second['stop_reason'] == 'no_progress'
    assert second['draft_id'] == '2'*32
    assert not second['repair_allowed']


def _finance_service_from_rows(tmp_path, rows_by_alias, scopes, *, title='财务分析'):
    task = TaskStore(tmp_path / (title + '-var')).create(title=title)
    analysis = AnalysisStore(task)
    bindings = {}
    for alias, rows in rows_by_alias.items():
        path = tmp_path / f'{title}-{alias}.json'
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        bindings[alias] = analysis.add_dataset(path, name=alias)['id']
    service = FinanceStore(task)
    context = service.save_context({'bindings': bindings, 'scopes': scopes})
    return service, context, bindings


def _control_rows(amounts, *, organization='O1', period='2026-09', currency='CNY', unit='万元'):
    return [
        {'ledger': 'L1', 'organization': organization, 'period': period, 'currency': currency, 'unit': unit,
         'scenario': scenario, 'management_account': account, 'amount': amount, 'source_row': index}
        for index, (scenario, account, amount) in enumerate(amounts, start=1)
    ]


def _claims_for_columns(run, column):
    return [
        {'basis': 'calculation', 'run_id': run['id'], 'row': index, 'column': column, 'value': row[column]}
        for index, row in enumerate(run['result']['rows'])
        if column in row
    ]


def _verify_run_column(service, run, column):
    for index, row in enumerate(run['result']['rows']):
        if column in row:
            service.drilldown_fact({'run_id': run['id'], 'row': index, 'column': column})


def _regional_rows(*, organization='华东', period='2026-08', currency='CNY', unit='万元'):
    east = [
        ('actual', 'revenue', '150', 'E-A-R'),
        ('actual', 'cost', '80', 'E-A-C'),
        ('actual', 'expense', '30', 'E-A-E'),
        ('budget', 'revenue', '130', 'E-B-R'),
        ('budget', 'cost', '75', 'E-B-C'),
        ('budget', 'expense', '22', 'E-B-E'),
    ]
    rows = [
        {'ledger': 'region-ledger', 'organization': organization, 'period': period, 'currency': currency, 'unit': unit,
         'scenario': scenario, 'management_account': account, 'amount': amount, 'source_row': index,
         'doc_id': doc_id, 'line_id': str(index)}
        for index, (scenario, account, amount, doc_id) in enumerate(east, start=1)
    ]
    rows.append({'ledger': 'region-ledger', 'organization': '华南', 'period': period, 'currency': currency, 'unit': unit,
                 'scenario': 'actual', 'management_account': 'revenue', 'amount': '999', 'source_row': 7,
                 'doc_id': 'S-A-R', 'line_id': '7'})
    return rows


def _profit_bridge_requirement(service, context, bindings, *, dimensions=None, scope=None):
    return service.analysis_requirements_save({
        'question': '请只分析华东组织的本期实际对预算利润差异桥；资料里还有华南行，不能混到华东。保存说明并下钻华东利润行。',
        'context_id': context['id'],
        'scope': scope or {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'},
        'bindings': {'regional': bindings['regional']},
        'items': [{
            'id': 'east_pnl_actual_budget',
            'metric': 'profit',
            'label': '华东 2026-08 实际vs预算利润差异桥：总差异与收入/成本/费用贡献',
            'dimensions': dimensions if dimensions is not None else {
                'dimension': 'management_account',
                'method': 'profit_bridge',
                'scenario_compare': 'actual_vs_budget',
            },
            'requires_drilldown': True,
        }],
    })


def _regional_service(tmp_path, *, rows=None, scope=None, title='regional'):
    rows = rows or _regional_rows()
    return _finance_service_from_rows(
        tmp_path,
        {'regional': rows},
        {'regional': scope or {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'}},
        title=title,
    )


def _run_east_profit_bridge(service, context, *, method='revenue_minus_cost_minus_expense', actual_filters=None, baseline_filters=None):
    return service.explain_variance({
        'context_id': context['id'],
        'method': method,
        'actual_scenario': 'actual',
        'baseline_scenario': 'budget',
        'actual_filters': actual_filters or {'organization': '华东', 'period': '2026-08'},
        'baseline_filters': baseline_filters or {'organization': '华东', 'period': '2026-08'},
    })


def test_control_totals_actual_budget_scope_without_scenario_satisfies_result_set_requirement(tmp_path):
    service, context, bindings = _finance_service_from_rows(
        tmp_path,
        {
            'actual': _control_rows([('actual', 'revenue', '120'), ('actual', 'cost', '70'), ('actual', 'expense', '20')]),
            'budget': _control_rows([('budget', 'revenue', '100'), ('budget', 'cost', '60'), ('budget', 'expense', '15')]),
        },
        {
            'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
            'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'budget'},
        },
        title='controls',
    )
    requirement = service.analysis_requirements_save({
        'question': '实际与预算各科目控制数对照',
        'context_id': context['id'],
        'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'},
        'bindings': bindings,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'label': '实际与预算各科目控制数对照', 'requires_drilldown': False}],
    })
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    _verify_run_column(service, run, 'amount')

    result = check_requirements(service.analysis, {
        'requirements_id': requirement['id'],
        'run_ids': [run['id']],
        'claims': _claims_for_columns(run, 'amount'),
    })

    assert result['coverage']['status'] == 'pass'
    assert result['provenance']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'
    assert {location['row'] for location in result['items'][0]['locations']} == set(range(6))


@pytest.mark.parametrize('bad_scope', [
    {'ledger': 'L1', 'organization': 'O2', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'},
    {'ledger': 'L1', 'organization': 'O1', 'period': '2026-10', 'currency': 'CNY', 'unit': '万元'},
    {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'USD', 'unit': '万元'},
])
def test_control_totals_comparison_keeps_scope_guards(tmp_path, bad_scope):
    service, context, bindings = _finance_service_from_rows(
        tmp_path,
        {
            'actual': _control_rows([('actual', 'revenue', '120')]),
            'budget': _control_rows([('budget', 'revenue', '100')]),
        },
        {
            'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
            'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'budget'},
        },
        title='bad-controls',
    )
    requirement = service.analysis_requirements_save({
        'question': '实际与预算各科目控制数对照',
        'context_id': context['id'],
        'scope': bad_scope,
        'bindings': bindings,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}],
    })
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    _verify_run_column(service, run, 'amount')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': _claims_for_columns(run, 'amount')})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'


def test_control_totals_actual_budget_requirement_rejects_actual_only_result(tmp_path):
    service, two_sided, bindings = _finance_service_from_rows(
        tmp_path,
        {
            'actual': _control_rows([('actual', 'revenue', '120')]),
            'budget': _control_rows([('budget', 'revenue', '100')]),
        },
        {
            'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
            'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'budget'},
        },
        title='two-sided-controls',
    )
    requirement = service.analysis_requirements_save({
        'question': '实际与预算各科目控制数对照',
        'context_id': two_sided['id'],
        'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'},
        'bindings': bindings,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'dimensions': {'scenario_compare': 'actual_vs_budget'}, 'requires_drilldown': False}],
    })
    actual_only = service.save_context({
        'bindings': {'actual': bindings['actual']},
        'scopes': {'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'}},
    })
    run = service.run_metric({'context_id': actual_only['id'], 'metric': {'kind': 'control_totals'}})
    _verify_run_column(service, run, 'amount')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': _claims_for_columns(run, 'amount')})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'



def test_control_totals_actual_budget_requires_each_grain_to_have_both_sides(tmp_path):
    service, context, bindings = _finance_service_from_rows(
        tmp_path,
        {
            'actual': _control_rows([('actual', 'revenue', '120'), ('actual', 'cost', '70')]),
            'budget': _control_rows([('budget', 'revenue', '100')]),
        },
        {
            'actual': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'actual'},
            'budget': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元', 'scenario': 'budget'},
        },
        title='unpaired-controls',
    )
    requirement = service.analysis_requirements_save({
        'question': '实际与预算各科目控制数对照',
        'context_id': context['id'],
        'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'},
        'bindings': bindings,
        'items': [{'id': 'controls', 'metric': 'control_totals', 'label': '实际与预算各科目控制数对照', 'requires_drilldown': False}],
    })
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    _verify_run_column(service, run, 'amount')

    result = check_requirements(service.analysis, {
        'requirements_id': requirement['id'],
        'run_ids': [run['id']],
        'claims': _claims_for_columns(run, 'amount'),
    })

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'


def test_profit_bridge_intent_missing_claims_get_actionable_fixups(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='bridge-fixups')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = _run_east_profit_bridge(service, context)

    result = check_requirements(service.analysis, {
        'requirements_id': requirement['id'],
        'run_ids': [run['id']],
        'claims': [],
    })

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    add_claims = [fixup for fixup in result['items'][0].get('fixups', []) if fixup['code'] == 'add_calculation_claim']
    verify_sources = [fixup for fixup in result['items'][0].get('fixups', []) if fixup['code'] == 'verify_source']
    assert {(fixup['row'], fixup['column']) for fixup in add_claims} == {(0, 'contribution'), (1, 'contribution'), (2, 'contribution'), (3, 'contribution')}
    assert {(fixup['location']['row'], fixup['location']['column']) for fixup in verify_sources} == {(0, 'contribution'), (1, 'contribution'), (2, 'contribution'), (3, 'contribution')}

    _verify_run_column(service, run, 'contribution')
    sourced = check_requirements(service.analysis, {
        'requirements_id': requirement['id'],
        'run_ids': [run['id']],
        'claims': [],
    })
    sourced_add_claims = [fixup for fixup in sourced['items'][0].get('fixups', []) if fixup['code'] == 'add_calculation_claim']
    sourced_verify_sources = [fixup for fixup in sourced['items'][0].get('fixups', []) if fixup['code'] == 'verify_source']
    assert {(fixup['row'], fixup['column']) for fixup in sourced_add_claims} == {(0, 'contribution'), (1, 'contribution'), (2, 'contribution'), (3, 'contribution')}
    assert sourced_verify_sources == []


def test_profit_bridge_source_fixups_close_only_after_all_required_sources(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='bridge-source-closure')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = _run_east_profit_bridge(service, context)
    spec = {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': []}
    pending = check_requirements(service.analysis, spec)
    spec['claims'] = [
        {'basis': 'calculation', **{key: action[key] for key in ('run_id', 'row', 'column', 'value')}}
        for action in pending['items'][0]['fixups'] if action['code'] == 'add_calculation_claim'
    ]
    service.drilldown_fact({'run_id': run['id'], 'row': 3, 'column': 'contribution'})
    partial = check_requirements(service.analysis, spec)
    assert partial['coverage']['status'] == 'pass'
    assert partial['provenance']['status'] == 'needs_attention'
    assert partial['items'][0]['provenance_status'] == 'pending'
    actions = partial['items'][0]['fixups']
    assert len(actions) == 3
    assert all(action['code'] == 'verify_source' for action in actions)
    for action in actions:
        service.drilldown_fact({key: action['location'][key] for key in ('run_id', 'row', 'column')})
    completed = check_requirements(service.analysis, spec)
    assert completed['coverage']['status'] == 'pass'
    assert completed['provenance']['status'] == 'pass'
    assert completed['items'][0]['provenance_status'] == 'verified'
    assert completed['items'][0].get('fixups', []) == []


def test_profit_bridge_intent_does_not_suggest_fixups_for_wrong_scope_or_free_sql(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='no-bridge-fixups')
    requirement = _profit_bridge_requirement(
        service,
        context,
        bindings,
        scope={'ledger': 'region-ledger', 'organization': '华南', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'},
    )
    native_run = _run_east_profit_bridge(service, context)
    forged = _run(service.analysis, id_suffix='forged-bridge-fixup', bindings={'regional': bindings['regional']}, finance_scope={
        'regional': {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'},
    }, result={
        'method': 'revenue_minus_cost_minus_expense',
        'columns': ['metric', 'contribution'],
        'rows': [
            {'metric': 'revenue', 'contribution': '20'},
            {'metric': 'cost', 'contribution': '-5'},
            {'metric': 'expense', 'contribution': '-8'},
            {'metric': 'profit', 'contribution': '7'},
        ],
    })

    result = check_requirements(service.analysis, {
        'requirements_id': requirement['id'],
        'run_ids': [native_run['id'], forged['id']],
        'claims': [],
    })

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0].get('fixups', []) == []

def test_profit_bridge_intent_dimensions_accept_verified_native_actual_budget_bridge(tmp_path):
    service, context, bindings = _regional_service(tmp_path)
    requirement = _profit_bridge_requirement(service, context, bindings)
    assert requirement['items'][0]['dimensions']['method'] == 'revenue_minus_cost_minus_expense'
    run = _run_east_profit_bridge(service, context)
    _verify_run_column(service, run, 'contribution')

    result = check_requirements(service.analysis, {
        'requirements_id': requirement['id'],
        'run_ids': [run['id']],
        'claims': _claims_for_columns(run, 'contribution'),
    })

    assert result['coverage']['status'] == 'pass'
    assert result['provenance']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'
    assert {location['row'] for location in result['items'][0]['locations']} == {0, 1, 2, 3}
    assert all(location['evidence']['group_type'] == 'profit_bridge' for location in result['items'][0]['locations'])


@pytest.mark.parametrize('dimensions', [
    {'dimension': 'management_account', 'method': 'profit_bridge', 'scenario_compare': 'budget_vs_actual'},
    {'dimension': 'product', 'method': 'profit_bridge', 'scenario_compare': 'actual_vs_budget'},
    {'dimension': 'management_account', 'method': 'quantity_then_price', 'scenario_compare': 'actual_vs_budget'},
])
def test_profit_bridge_intent_dimensions_reject_conflicting_intent(tmp_path, dimensions):
    service, context, bindings = _regional_service(tmp_path, title='conflicting-intent')
    requirement = _profit_bridge_requirement(service, context, bindings, dimensions=dimensions)
    run = _run_east_profit_bridge(service, context)
    _verify_run_column(service, run, 'contribution')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': _claims_for_columns(run, 'contribution')})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'


def test_profit_bridge_intent_requires_all_contribution_claims(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='missing-bridge-claim')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = _run_east_profit_bridge(service, context)
    _verify_run_column(service, run, 'contribution')
    claims = [claim for claim in _claims_for_columns(run, 'contribution') if claim['row'] != 2]

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': claims})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'


@pytest.mark.parametrize('scope', [
    {'ledger': 'region-ledger', 'organization': '华南', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'},
    {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-09', 'currency': 'CNY', 'unit': '万元'},
    {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-08', 'currency': 'USD', 'unit': '万元'},
])
def test_profit_bridge_intent_keeps_scope_guards(tmp_path, scope):
    service, context, bindings = _regional_service(tmp_path, title='bad-bridge-scope')
    requirement = _profit_bridge_requirement(service, context, bindings, scope=scope)
    run = _run_east_profit_bridge(service, context)
    _verify_run_column(service, run, 'contribution')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': _claims_for_columns(run, 'contribution')})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'


def test_profit_bridge_intent_does_not_trust_free_sql_method_label(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='free-sql-bridge')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = _run(service.analysis, id_suffix='forged-profit-bridge', bindings={'regional': bindings['regional']}, finance_scope={
        'regional': {'ledger': 'region-ledger', 'organization': '华东', 'period': '2026-08', 'currency': 'CNY', 'unit': '万元'},
    }, result={
        'method': 'revenue_minus_cost_minus_expense',
        'columns': ['metric', 'contribution'],
        'rows': [
            {'metric': 'revenue', 'contribution': '20'},
            {'metric': 'cost', 'contribution': '-5'},
            {'metric': 'expense', 'contribution': '-8'},
            {'metric': 'profit', 'contribution': '7'},
        ],
    })

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': _claims_for_columns(run, 'contribution')})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'

def test_completion_limits_changing_failures_to_two_repairs(analysis):
    from foundry.finance_completion import record_completion
    requirement = save_requirements(analysis, spec())
    for number in range(4):
        quality = {'status':'needs_attention', 'issues':[{'code':str(number)}],
                   'requirements':{'requirements_id':requirement['id'], 'coverage':{'status':'needs_attention'}}}
        receipt = record_completion(analysis, {'id':'1'*32,'body':str(number),'content_hash':str(number),'run_ids':[]}, quality)
    assert receipt['repair_attempts'] == 2
    assert receipt['stop_reason'] == 'repair_budget_exhausted'
    assert not receipt['repair_allowed']


def test_new_runs_do_not_reset_same_requirement_repair_budget(analysis, monkeypatch):
    from foundry.finance_completion import record_completion
    requirement = save_requirements(analysis, spec())
    monkeypatch.setattr(analysis, 'get_run', lambda run_id: {'output_hash': run_id})
    for number in range(3):
        quality = {'status': 'needs_attention', 'issues': [{'code': str(number)}],
                   'requirements': {'requirements_id': requirement['id'], 'coverage': {'status': 'needs_attention'}}}
        receipt = record_completion(analysis, {'id': str(number)*32, 'body': str(number),
            'content_hash': str(number), 'run_ids': [str(number)*32]}, quality)
    assert receipt['repair_attempts'] == 2
    assert receipt['repair_allowed'] is False


def _pq_run(analysis, *, method='base_weights_with_interaction', product='商品A', period='2026-08',
            binding_value='pq-dataset', scope_alias='pq', total='32', quantity='20', price='10',
            interaction='2', residual='0', unit='元', currency='CNY', row_updates=None,
            finance_scope=None, bindings=None, columns=None):
    row = {
        'ledger': 'commerce',
        'organization': '电商部',
        'currency': currency,
        'unit': unit,
        'product': product,
        'actual': '132',
        'baseline': '100',
        'quantity_contribution': quantity,
        'price_contribution': price,
        'interaction': interaction,
        'total_variance': total,
        'residual': residual,
        'source_rows': [{'dataset_id': binding_value, 'row_index': 1, 'source_row': 1}],
    }
    if row_updates:
        row.update(row_updates)
    if columns is None:
        columns = [
            'ledger', 'organization', 'currency', 'unit', 'product', 'actual', 'baseline',
            'quantity_contribution', 'price_contribution', 'interaction', 'total_variance', 'residual',
        ]
    record = _new(
        analysis.task,
        engine='finance',
        execution_status='succeeded',
        output_hash='pq-hash-' + method + '-' + product + '-' + period + '-' + binding_value,
        bindings=bindings or {scope_alias: binding_value},
        finance_scope=finance_scope or {
            scope_alias: {'ledger': 'commerce', 'organization': '电商部', 'period': period,
                          'currency': currency, 'unit': unit},
        },
        result={
            'domain': 'foundry.finance.variance.v1',
            'method': method,
            'columns': columns,
            'rows': [row],
        },
    )
    return analysis._write(analysis._object_path('runs', record['id']), record)


def _pq_claims(run, *, row=0, columns=None):
    columns = columns or ['total_variance', 'quantity_contribution', 'price_contribution', 'interaction']
    result_row = run['result']['rows'][row]
    return [
        {'basis': 'calculation', 'run_id': run['id'], 'row': row, 'column': column, 'value': result_row[column]}
        for column in columns
    ]


def _require_pq(analysis, *, method='base_weights_with_interaction', product='商品A', period='2026-08',
                binding_value='pq-dataset', scope=None, bindings=None, metric='amount', dimensions=None):
    return save_requirements(analysis, spec(
        question='量价拆分并下钻结果行',
        scope=scope or {'ledger': 'commerce', 'organization': '电商部', 'period': period,
                        'currency': 'CNY', 'unit': '元'},
        bindings=bindings or {'pq': binding_value},
        items=[{
            'id': 'pq_split',
            'metric': metric,
            'label': '商品量价拆分：数量效应、价格效应、交互项及总差异',
            'dimensions': dimensions if dimensions is not None else {'product': product, 'method': method},
            'requires_drilldown': True,
        }],
    ))


def test_price_quantity_amount_requirement_matches_verified_closed_f10_shape(analysis):
    requirement = _require_pq(analysis)
    run = _pq_run(analysis)

    pending_source = check_requirements(analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [run['id']],
                                                   'claims': _pq_claims(run)})
    assert pending_source['coverage']['status'] == 'pass'
    assert pending_source['provenance']['status'] == 'needs_attention'
    assert pending_source['items'][0]['status'] == 'answered'
    assert {location['column'] for location in pending_source['items'][0]['locations']} == {
        'total_variance', 'quantity_contribution', 'price_contribution', 'interaction'
    }

    for location in pending_source['items'][0]['locations']:
        _paged_source(analysis, {key: location[key] for key in ('run_id', 'row', 'column', 'output_hash')},
                      offset=0, read_count=1, total=1, has_more=False)

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': _pq_claims(run)})
    assert result['coverage']['status'] == 'pass'
    assert result['provenance']['status'] == 'pass'
    assert result['items'][0]['provenance_status'] == 'verified'
    assert all(location['evidence']['group_type'] == 'price_quantity_bridge' for location in result['items'][0]['locations'])




def test_revenue_price_quantity_requirement_matches_real_service_f11_shape(tmp_path):
    task = TaskStore(tmp_path / 'var').create(title='真实量价桥')
    service = FinanceStore(task)
    bindings = {}
    rows = [
        {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元',
         'scenario': 'budget', 'product': '商品A', 'quantity': '99', 'price': '99', 'source_row': '1'},
        {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元',
         'scenario': 'actual', 'product': '商品A', 'quantity': '100', 'price': '100', 'source_row': '2'},
        {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元',
         'scenario': 'budget', 'product': '商品B', 'quantity': '20', 'price': '5', 'source_row': '3', 'doc_id': 'B-B', 'line_id': '1'},
        {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元',
         'scenario': 'actual', 'product': '商品B', 'quantity': '18', 'price': '7', 'source_row': '4', 'doc_id': 'B-A', 'line_id': '1'},
    ]
    path = tmp_path / 'multi-sku.json'
    path.write_text(json.dumps(rows, ensure_ascii=False))
    bindings['pq'] = service.analysis.add_dataset(path, name='multi-sku')['id']
    context = service.save_context({
        'bindings': bindings,
        'scopes': {'pq': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
                          'currency': 'CNY', 'unit': '元'}},
    })
    requirement = save_requirements(service.analysis, spec(
        question='只对商品B做收入量价拆分并下钻结果行',
        scope={'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08', 'currency': 'CNY', 'unit': '元'},
        bindings={'pq': bindings['pq']},
        items=[{'id': 'revenue_pq', 'metric': 'revenue', 'dimensions': {'product': '商品B'},
                'requires_drilldown': True}],
    ))

    run = service.explain_variance({
        'context_id': context['id'],
        'kind': 'price_quantity',
        'method': 'quantity_then_price',
        'field_map': {'quantity': 'quantity', 'price': 'price'},
        'dimensions': ['product'],
        'actual_scenario': 'actual',
        'baseline_scenario': 'budget',
        'actual_filters': {'product': '商品B', 'period': '2026-08'},
        'baseline_filters': {'product': '商品B', 'period': '2026-08'},
    })
    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [run['id']],
                                                   'claims': _pq_claims(run)})

    assert run['execution_status'] == 'succeeded'
    assert run['result']['method'] == 'quantity_then_price'
    assert run['result']['rows'][0]['product'] == '商品B'
    assert run['result']['rows'][0]['total_variance'] == '26'
    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'
    assert {location['column'] for location in result['items'][0]['locations']} == {
        'total_variance', 'quantity_contribution', 'price_contribution', 'interaction'
    }

def test_price_quantity_amount_requirement_with_explicit_method_matches_f11_shape(analysis):
    requirement = _require_pq(analysis, method='quantity_then_price', product='商品B')
    run = _pq_run(analysis, method='quantity_then_price', product='商品B', total='26', quantity='-10',
                  price='36', interaction='0', residual='0')

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': _pq_claims(run)})

    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'
    interaction = next(location for location in result['items'][0]['locations'] if location['column'] == 'interaction')
    assert interaction['evidence']['member_state'] == 'observed_zero'


def test_price_quantity_amount_requirement_rejects_wrong_method_product_period_and_binding(analysis):
    requirement = _require_pq(analysis, method='base_weights_with_interaction', product='商品A')
    wrong_method = _pq_run(analysis, method='quantity_then_price', product='商品A')
    wrong_product = _pq_run(analysis, method='base_weights_with_interaction', product='商品B')
    wrong_period = _pq_run(analysis, method='base_weights_with_interaction', product='商品A', period='2026-07')
    wrong_binding = _pq_run(analysis, method='base_weights_with_interaction', product='商品A',
                            binding_value='other-dataset')

    for run in (wrong_method, wrong_product, wrong_period, wrong_binding):
        result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                               'run_ids': [run['id']],
                                               'claims': _pq_claims(run)})
        assert result['coverage']['status'] == 'needs_attention'
        assert result['items'][0]['status'] == 'pending'
        assert result['items'][0]['locations'] == []


def test_price_quantity_amount_requirement_requires_all_required_component_claims(analysis):
    requirement = _require_pq(analysis)
    run = _pq_run(analysis)

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': _pq_claims(run, columns=['quantity_contribution'])})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_price_quantity_amount_requirement_rejects_ordinary_sql_amount(analysis):
    requirement = _require_pq(analysis)
    run = _run(analysis, id_suffix='sql-amount', bindings={'pq': 'pq-dataset'}, finance_scope={
        'pq': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
               'currency': 'CNY', 'unit': '元'},
    }, result={
        'method': 'sql',
        'columns': ['product', 'amount'],
        'rows': [{'product': '商品A', 'amount': '32'}],
    })

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': [_claim(run, row=0, column='amount', value='32')]})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_price_quantity_amount_requirement_rejects_ambiguous_named_scopes(analysis):
    requirement = _require_pq(analysis, bindings={'pq': 'pq-dataset', 'other': 'other-dataset'})
    run = _pq_run(analysis, bindings={'pq': 'pq-dataset', 'other': 'other-dataset'}, finance_scope={
        'pq': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
               'currency': 'CNY', 'unit': '元'},
        'other': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
                  'currency': 'CNY', 'unit': '元'},
    })

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': _pq_claims(run)})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_revenue_price_quantity_requirement_rejects_currency_and_unit_mismatch(analysis):
    requirement = _require_pq(analysis, metric='revenue', dimensions={'product': '商品A'})
    wrong_currency = _pq_run(analysis, currency='USD', finance_scope={
        'pq': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
               'currency': 'USD', 'unit': '元'},
    })
    wrong_unit = _pq_run(analysis, unit='万元', finance_scope={
        'pq': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
               'currency': 'CNY', 'unit': '万元'},
    })

    for run in (wrong_currency, wrong_unit):
        result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                               'run_ids': [run['id']],
                                               'claims': _pq_claims(run)})
        assert result['coverage']['status'] == 'needs_attention'
        assert result['items'][0]['status'] == 'pending'
        assert result['items'][0]['locations'] == []


def test_revenue_price_quantity_requirement_rejects_sql_with_same_columns_without_supported_group(analysis):
    requirement = _require_pq(analysis, metric='revenue', dimensions={'product': '商品A'})
    row = {
        'ledger': 'commerce', 'organization': '电商部', 'currency': 'CNY', 'unit': '元',
        'product': '商品A', 'actual': '132', 'baseline': '100',
        'quantity_contribution': '20', 'price_contribution': '10', 'interaction': '2',
        'total_variance': '32', 'residual': '0',
        'source_rows': [{'dataset_id': 'pq-dataset', 'row_index': 1, 'source_row': 1}],
    }
    run = _run(analysis, id_suffix='sql-pq-shaped', bindings={'pq': 'pq-dataset'}, finance_scope={
        'pq': {'ledger': 'commerce', 'organization': '电商部', 'period': '2026-08',
               'currency': 'CNY', 'unit': '元'},
    }, result={
        'method': 'sql',
        'columns': ['ledger', 'organization', 'currency', 'unit', 'product', 'actual', 'baseline',
                    'quantity_contribution', 'price_contribution', 'interaction', 'total_variance', 'residual'],
        'rows': [row],
    })

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': _pq_claims(run)})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def _cash_stock_service(tmp_path):
    task = TaskStore(tmp_path / 'var').create(title='现金余额')
    service = FinanceStore(task)
    path = tmp_path / 'cash-stock.json'
    path.write_text(json.dumps([
        {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-07', 'currency': 'CNY',
         'unit': '元', 'scenario': 'actual', 'management_account': 'cash', 'amount': '100',
         'source_row': '1', 'doc_id': 'CASH-202607', 'line_id': '1'},
        {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-08', 'currency': 'CNY',
         'unit': '元', 'scenario': 'actual', 'management_account': 'cash', 'amount': '110',
         'source_row': '2', 'doc_id': 'CASH-202608', 'line_id': '1'},
        {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-08', 'currency': 'CNY',
         'unit': '元', 'scenario': 'actual', 'management_account': 'bank', 'amount': '900',
         'source_row': '3', 'doc_id': 'BANK-202608', 'line_id': '1'},
    ], ensure_ascii=False))
    dataset = service.analysis.add_dataset(path, name='cash-stock')
    context = service.save_context({
        'bindings': {'actual': dataset['id']},
        'scopes': {'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'currency': 'CNY',
                              'unit': '元', 'scenario': 'actual'}},
    })
    return service, context


def _cash_requirements(analysis, *, scope=None, metric='cash'):
    return save_requirements(analysis, spec(
        question='读取两期现金余额并下钻8月现金行',
        scope=scope or {'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'currency': 'CNY',
                                   'unit': '元', 'scenario': 'actual'}},
        items=[
            {'id': 'cash_2026_07', 'metric': metric, 'dimensions': {'period': '2026-07'},
             'requires_drilldown': True},
            {'id': 'cash_2026_08', 'metric': metric, 'dimensions': {'period': '2026-08'},
             'requires_drilldown': True},
        ],
    ))


def _amount_claim(run, row):
    return {'basis': 'calculation', 'run_id': run['id'], 'row': row, 'column': 'amount',
            'value': run['result']['rows'][row]['amount']}


def _control_totals_service(tmp_path):
    task = TaskStore(tmp_path / 'var').create(title='控制合计')
    service = FinanceStore(task)
    path = tmp_path / 'control-totals.json'
    path.write_text(json.dumps([
        {'ledger': 'control-ledger', 'organization': '总部', 'period': '2026-08', 'currency': 'CNY',
         'unit': '元', 'scenario': 'actual', 'management_account': 'cash', 'amount': '100',
         'source_row': '1', 'doc_id': 'CNY-CASH', 'line_id': '1'},
        {'ledger': 'control-ledger', 'organization': '总部', 'period': '2026-08', 'currency': 'USD',
         'unit': '元', 'scenario': 'actual', 'management_account': 'cash', 'amount': '10',
         'source_row': '2', 'doc_id': 'USD-CASH', 'line_id': '1'},
        {'ledger': 'control-ledger', 'organization': '总部', 'period': '2026-08', 'currency': 'CNY',
         'unit': '元', 'scenario': 'actual', 'management_account': 'revenue', 'amount': '900',
         'source_row': '3', 'doc_id': 'CNY-REV', 'line_id': '1'},
    ], ensure_ascii=False))
    dataset = service.analysis.add_dataset(path, name='control-totals')
    context = service.save_context({
        'bindings': {'actual': dataset['id']},
        'scopes': {'actual': {'ledger': 'control-ledger', 'organization': '总部',
                              'period': '2026-08', 'scenario': 'actual'}},
    })
    return service, context


def _control_requirement(analysis):
    return save_requirements(analysis, spec(
        question='核对8月现金控制合计，必须覆盖CNY和USD',
        scope={'actual': {'ledger': 'control-ledger', 'organization': '总部',
                          'period': '2026-08', 'scenario': 'actual'}},
        items=[{'id': 'cash_controls', 'metric': 'control_totals',
                'dimensions': {'management_account': 'cash'}, 'periods': ['2026-08'],
                'requires_drilldown': True}],
    ))


def test_control_totals_require_all_matching_currency_rows_and_sources(tmp_path):
    service, context = _control_totals_service(tmp_path)
    requirement = _control_requirement(service.analysis)
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    cash_rows = [index for index, row in enumerate(run['result']['rows']) if row['management_account'] == 'cash']
    claims = [_amount_claim(run, index) for index in cash_rows]

    pending = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']], 'claims': claims})

    assert [run['result']['rows'][index]['currency'] for index in cash_rows] == ['CNY', 'USD']
    assert [run['result']['rows'][index]['amount'] for index in cash_rows] == ['100', '10']
    assert pending['coverage']['status'] == 'needs_attention'
    assert pending['provenance']['status'] == 'needs_attention'
    assert pending['items'][0]['status'] == 'pending'
    assert {location['row'] for location in pending['items'][0]['locations']} == set(cash_rows)
    assert {location['status'] for location in pending['items'][0]['locations']} == {'pending'}

    for location in pending['items'][0]['locations']:
        service.drilldown_fact({key: location[key] for key in ('run_id', 'row', 'column')})

    sourced = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']], 'claims': claims})
    assert sourced['coverage']['status'] == 'pass'
    assert sourced['provenance']['status'] == 'pass'
    assert sourced['items'][0]['status'] == 'answered'
    assert {location['status'] for location in sourced['items'][0]['locations']} == {'answered'}



def test_control_totals_rejects_context_narrowed_currency_for_broad_requirement(tmp_path):
    service, context = _control_totals_service(tmp_path)
    requirement = _control_requirement(service.analysis)
    narrow_context = service.save_context({
        'bindings': context['bindings'],
        'scopes': {'actual': {'ledger': 'control-ledger', 'organization': '总部',
                              'period': '2026-08', 'scenario': 'actual', 'currency': 'CNY'}},
    })
    narrow = service.run_metric({'context_id': narrow_context['id'], 'metric': {'kind': 'control_totals'}})

    narrow_result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                          'run_ids': [narrow['id']],
                                                          'claims': [_amount_claim(narrow, 0)]})
    assert [row['currency'] for row in narrow['result']['rows'] if row['management_account'] == 'cash'] == ['CNY']
    assert narrow_result['coverage']['status'] == 'needs_attention'
    assert narrow_result['items'][0]['status'] == 'pending'
    assert narrow_result['items'][0]['locations'] == []

    broad = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    cash_rows = [index for index, row in enumerate(broad['result']['rows']) if row['management_account'] == 'cash']
    claims = [_amount_claim(broad, index) for index in cash_rows]
    pending = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [broad['id']], 'claims': claims})
    for location in pending['items'][0]['locations']:
        service.drilldown_fact({key: location[key] for key in ('run_id', 'row', 'column')})

    sourced = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [broad['id']], 'claims': claims})
    assert [broad['result']['rows'][index]['currency'] for index in cash_rows] == ['CNY', 'USD']
    assert sourced['coverage']['status'] == 'pass'
    assert sourced['provenance']['status'] == 'pass'
    assert sourced['items'][0]['status'] == 'answered'


def test_control_totals_requires_each_declared_organization(tmp_path):
    task = TaskStore(tmp_path / 'var').create(title='跨组织控制合计')
    service = FinanceStore(task)
    source = tmp_path / 'regional-control-totals.json'
    source.write_text(json.dumps([
        {'ledger': 'control-ledger', 'organization': organization, 'period': '2026-08',
         'currency': 'CNY', 'unit': '元', 'scenario': 'actual', 'management_account': 'cash',
         'amount': amount, 'source_row': str(index), 'doc_id': organization, 'line_id': '1'}
        for index, (organization, amount) in enumerate([('总部', '100'), ('华东', '200')], start=1)
    ], ensure_ascii=False))
    dataset = service.analysis.add_dataset(source, name='regional-cash')
    context = service.save_context({
        'bindings': {'actual': dataset['id']},
        'scopes': {'actual': {'ledger': 'control-ledger', 'period': '2026-08', 'scenario': 'actual'}},
    })
    requirement = save_requirements(service.analysis, spec(
        scope={'actual': {'ledger': 'control-ledger', 'period': '2026-08', 'scenario': 'actual'}},
        items=[{'id': 'regional_cash', 'metric': 'control_totals',
                'dimensions': {'management_account': 'cash'},
                'organizations': ['总部', '华东'], 'periods': ['2026-08'],
                'requires_drilldown': True}],
    ))
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    claims = [_amount_claim(run, index) for index in range(len(run['result']['rows']))]

    partial = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']], 'claims': claims[:1]})
    assert partial['items'][0]['status'] == 'pending'

    for index in range(len(run['result']['rows'])):
        service.drilldown_fact({'run_id': run['id'], 'row': index, 'column': 'amount'})
    complete = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                     'run_ids': [run['id']], 'claims': claims})
    assert complete['items'][0]['status'] == 'answered'
    assert {run['result']['rows'][location['row']]['organization'] for location in complete['items'][0]['locations']} == {'总部', '华东'}


def test_control_totals_rejects_partial_row_claims_and_cross_run_stitching(tmp_path):
    service, context = _control_totals_service(tmp_path)
    requirement = _control_requirement(service.analysis)
    complete = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    cash_rows = [index for index, row in enumerate(complete['result']['rows']) if row['management_account'] == 'cash']

    partial = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [complete['id']],
                                                    'claims': [_amount_claim(complete, cash_rows[0])]})
    assert partial['coverage']['status'] == 'needs_attention'
    assert partial['items'][0]['status'] == 'pending'
    assert partial['items'][0]['locations'] == []

    cny_run = _run(service.analysis, id_suffix='control-cny', engine='finance',
                   analysis_id=complete['analysis_id'], finance_context_id=complete['finance_context_id'],
                   bindings=complete['bindings'], finance_scope=complete['finance_scope'], result={
                       'metric_id': 'control_totals',
                       'columns': complete['result']['columns'],
                       'rows': [complete['result']['rows'][cash_rows[0]]],
                   })
    usd_run = _run(service.analysis, id_suffix='control-usd', engine='finance',
                   analysis_id=complete['analysis_id'], finance_context_id=complete['finance_context_id'],
                   bindings=complete['bindings'], finance_scope=complete['finance_scope'], result={
                       'metric_id': 'control_totals',
                       'columns': complete['result']['columns'],
                       'rows': [complete['result']['rows'][cash_rows[1]]],
                   })

    stitched = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                     'run_ids': [cny_run['id'], usd_run['id']],
                                                     'claims': [_amount_claim(cny_run, 0), _amount_claim(usd_run, 0)]})
    assert stitched['coverage']['status'] == 'needs_attention'
    assert stitched['items'][0]['status'] == 'pending'
    assert stitched['items'][0]['locations'] == []


def test_control_totals_rejects_sql_with_matching_rows_and_finance_revision_id(tmp_path):
    service, context = _control_totals_service(tmp_path)
    requirement = _control_requirement(service.analysis)
    native = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    sql = _run(service.analysis, id_suffix='sql-control', engine='sql', analysis_id=native['analysis_id'],
               finance_context_id=native['finance_context_id'], bindings=native['bindings'],
               finance_scope=native['finance_scope'], result={
                   'metric_id': 'control_totals',
                   'method': 'sql',
                   'columns': native['result']['columns'],
                   'rows': [row for row in native['result']['rows'] if row['management_account'] == 'cash'],
               })

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [sql['id']],
                                                   'claims': [_amount_claim(sql, 0), _amount_claim(sql, 1)]})
    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_account_total_periods_set_requires_all_matching_rows_and_sources(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    requirement = save_requirements(service.analysis, spec(
        question='核对7月和8月现金余额集合',
        scope={'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'currency': 'CNY',
                          'unit': '元', 'scenario': 'actual'}},
        items=[{'id': 'cash_two_periods', 'metric': 'cash', 'periods': ['2026-07', '2026-08'],
                'requires_drilldown': True}],
    ))
    run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total', 'accounts': ['cash'], 'account_behavior': {'cash': 'stock'}
    }})

    partial = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']], 'claims': [_amount_claim(run, 0)]})
    assert partial['coverage']['status'] == 'needs_attention'
    assert partial['items'][0]['status'] == 'pending'

    claims = [_amount_claim(run, 0), _amount_claim(run, 1)]
    pending = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']], 'claims': claims})
    assert pending['coverage']['status'] == 'needs_attention'
    assert pending['items'][0]['status'] == 'pending'
    assert {location['row'] for location in pending['items'][0]['locations']} == {0, 1}

    for location in pending['items'][0]['locations']:
        service.drilldown_fact({key: location[key] for key in ('run_id', 'row', 'column')})

    sourced = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']], 'claims': claims})
    assert sourced['coverage']['status'] == 'pass'
    assert sourced['provenance']['status'] == 'pass'
    assert sourced['items'][0]['status'] == 'answered'


def test_account_total_rejects_metric_filter_narrower_than_requirement(tmp_path):
    service, context = _control_totals_service(tmp_path)
    requirement = save_requirements(service.analysis, spec(
        question='核对8月现金余额，覆盖所有币种',
        scope={'actual': {'ledger': 'control-ledger', 'organization': '总部',
                          'period': '2026-08', 'scenario': 'actual'}},
        items=[{'id': 'cash_all_currencies', 'metric': 'cash',
                'periods': ['2026-08'], 'requires_drilldown': True}],
    ))
    filtered = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total', 'accounts': ['cash'], 'filters': {'currency': 'CNY'},
    }})
    service.drilldown_fact({'run_id': filtered['id'], 'row': 0, 'column': 'amount'})

    narrowed = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                     'run_ids': [filtered['id']],
                                                     'claims': [_amount_claim(filtered, 0)]})
    assert narrowed['items'][0]['status'] == 'pending'
    assert narrowed['items'][0]['locations'] == []

    complete = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total', 'accounts': ['cash'],
    }})
    for index in range(len(complete['result']['rows'])):
        service.drilldown_fact({'run_id': complete['id'], 'row': index, 'column': 'amount'})
    claims = [_amount_claim(complete, index) for index in range(len(complete['result']['rows']))]
    accepted = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                     'run_ids': [complete['id']], 'claims': claims})
    assert accepted['items'][0]['status'] == 'answered'
    assert {complete['result']['rows'][location['row']]['currency'] for location in accepted['items'][0]['locations']} == {'CNY', 'USD'}


def test_price_quantity_metric_name_matches_complete_native_bridge(analysis):
    requirement = _require_pq(analysis, metric='price_quantity', dimensions={'product': '商品A'})
    run = _pq_run(analysis)

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': _pq_claims(run)})

    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'


def test_account_total_single_cash_stock_amounts_bind_from_real_run_metric_and_sources(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    requirement = _cash_requirements(service.analysis)
    run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total',
        'accounts': ['cash'],
        'account_behavior': {'cash': 'stock'},
    }})
    claims = [_amount_claim(run, 0), _amount_claim(run, 1)]

    pending_source = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                           'run_ids': [run['id']],
                                                           'claims': claims})
    assert [row['period'] for row in run['result']['rows']] == ['2026-07', '2026-08']
    assert [row['amount'] for row in run['result']['rows']] == ['100', '110']
    assert pending_source['coverage']['status'] == 'pass'
    assert pending_source['provenance']['status'] == 'needs_attention'
    assert {item['id']: item['status'] for item in pending_source['items']} == {
        'cash_2026_07': 'answered',
        'cash_2026_08': 'answered',
    }

    for item in pending_source['items']:
        location = item['locations'][0]
        service.drilldown_fact({key: location[key] for key in ('run_id', 'row', 'column')})

    sourced = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                    'run_ids': [run['id']],
                                                    'claims': claims})
    assert sourced['provenance']['status'] == 'pass'
    assert all(item['provenance_status'] == 'verified' for item in sourced['items'])





def test_account_total_scope_period_can_come_from_real_run_metric_row(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    requirement = save_requirements(service.analysis, spec(
        question='读取8月现金余额，期间由任务范围约束',
        scope={'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-08',
                          'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}},
        items=[{'id': 'cash_august', 'metric': 'cash', 'requires_drilldown': False}],
    ))
    run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total',
        'accounts': ['cash'],
        'account_behavior': {'cash': 'stock'},
    }})

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [run['id']],
                                                   'claims': [_amount_claim(run, 0), _amount_claim(run, 1)]})

    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'
    assert [(location['row'], location['column']) for location in result['items'][0]['locations']] == [(1, 'amount')]


def test_account_total_rejects_scope_period_conflict_between_binding_and_row(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    context = service.save_context({
        'bindings': context['bindings'],
        'scopes': {'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-07',
                              'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}},
    })
    requirement = save_requirements(service.analysis, spec(
        question='读取8月现金余额，绑定却固定7月',
        scope={'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-08',
                          'currency': 'CNY', 'unit': '元', 'scenario': 'actual'}},
        items=[{'id': 'cash_august', 'metric': 'cash', 'requires_drilldown': False}],
    ))
    real_run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total',
        'accounts': ['cash'],
        'account_behavior': {'cash': 'stock'},
    }})
    run = _run(service.analysis, id_suffix='scope-period-conflict', engine='finance',
               analysis_id=real_run['analysis_id'], finance_context_id=real_run['finance_context_id'],
               bindings=real_run['bindings'], finance_scope=real_run['finance_scope'], result={
                   'metric_id': 'account_total',
                   'columns': ['period', 'scenario', 'currency', 'unit', 'amount'],
                   'rows': [{'period': '2026-08', 'scenario': 'actual', 'currency': 'CNY',
                             'unit': '元', 'amount': '110'}],
               })

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [run['id']],
                                                   'claims': [_amount_claim(run, 0)]})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_account_total_single_scope_does_not_satisfy_two_sided_comparison_scope(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    requirement = save_requirements(service.analysis, spec(
        question='读取实际8月并比较7月现金余额',
        scope={
            'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-08',
                       'currency': 'CNY', 'unit': '元', 'scenario': 'actual'},
            'baseline': {'ledger': 'cash-ledger', 'organization': '总部', 'period': '2026-07',
                         'currency': 'CNY', 'unit': '元', 'scenario': 'actual'},
        },
        items=[{'id': 'cash_comparison', 'metric': 'cash', 'requires_drilldown': False}],
    ))
    run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total',
        'accounts': ['cash'],
        'account_behavior': {'cash': 'stock'},
    }})

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [run['id']],
                                                   'claims': [_amount_claim(run, 1)]})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []
def test_account_total_rejects_wrong_account_and_multi_account_totals(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    _cash_requirements(service.analysis)
    wrong_account = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total', 'accounts': ['bank'], 'dimensions': ['period']
    }})
    multi_account = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total', 'accounts': ['cash', 'bank'], 'dimensions': ['period']
    }})

    for run in (wrong_account, multi_account):
        result = check_requirements(service.analysis, {'run_ids': [run['id']],
                                                       'claims': [_amount_claim(run, 0)]})
        assert result['coverage']['status'] == 'needs_attention'
        assert all(item['status'] == 'pending' for item in result['items'])


def test_account_total_rejects_period_currency_and_unit_mismatch(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total', 'accounts': ['cash'], 'account_behavior': {'cash': 'stock'}
    }})
    claims = [_amount_claim(run, 0), _amount_claim(run, 1)]

    wrong_period = _cash_requirements(service.analysis, metric='cash')
    wrong_period = save_requirements(service.analysis, spec(
        parent_id=wrong_period['id'],
        question='只读取错误期间现金',
        scope={'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'currency': 'CNY',
                          'unit': '元', 'scenario': 'actual'}},
        items=[{'id': 'cash_2026_09', 'metric': 'cash', 'dimensions': {'period': '2026-09'},
                'requires_drilldown': True}],
        change_reason='测试错误期间不应匹配',
    ))
    period_result = check_requirements(service.analysis, {'requirements_id': wrong_period['id'],
                                                          'run_ids': [run['id']], 'claims': claims})
    assert period_result['items'][0]['status'] == 'pending'

    wrong_currency = save_requirements(service.analysis, spec(
        parent_id=wrong_period['id'],
        question='读取USD现金',
        scope={'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'currency': 'USD',
                          'unit': '元', 'scenario': 'actual'}},
        items=[{'id': 'cash_2026_08', 'metric': 'cash', 'dimensions': {'period': '2026-08'},
                'requires_drilldown': True}],
        change_reason='测试错误币种不应匹配',
    ))
    currency_result = check_requirements(service.analysis, {'requirements_id': wrong_currency['id'],
                                                            'run_ids': [run['id']], 'claims': claims})
    assert currency_result['items'][0]['status'] == 'pending'

    wrong_unit = save_requirements(service.analysis, spec(
        parent_id=wrong_currency['id'],
        question='读取万元现金',
        scope={'actual': {'ledger': 'cash-ledger', 'organization': '总部', 'currency': 'CNY',
                          'unit': '万元', 'scenario': 'actual'}},
        items=[{'id': 'cash_2026_08', 'metric': 'cash', 'dimensions': {'period': '2026-08'},
                'requires_drilldown': True}],
        change_reason='测试错误单位不应匹配',
    ))
    unit_result = check_requirements(service.analysis, {'requirements_id': wrong_unit['id'],
                                                        'run_ids': [run['id']], 'claims': claims})
    assert unit_result['items'][0]['status'] == 'pending'



def test_account_total_rejects_sql_engine_even_with_finance_revision_id(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    requirement = _cash_requirements(service.analysis)
    real_run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total',
        'accounts': ['cash'],
        'account_behavior': {'cash': 'stock'},
    }})
    forged = _run(service.analysis, id_suffix='sql-with-finance-revision',
                  engine='sql', analysis_id=real_run['analysis_id'],
                  finance_context_id=real_run['finance_context_id'],
                  bindings=real_run['bindings'], finance_scope=real_run['finance_scope'],
                  result={
                      'metric_id': 'account_total',
                      'method': 'sql',
                      'columns': ['period', 'scenario', 'currency', 'unit', 'amount'],
                      'rows': [{'period': '2026-08', 'scenario': 'actual', 'currency': 'CNY',
                                'unit': '元', 'amount': '110'}],
                  })

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [forged['id']],
                                                   'claims': [_amount_claim(forged, 0)]})

    assert result['coverage']['status'] == 'needs_attention'
    assert all(item['status'] == 'pending' for item in result['items'])
    assert all(item['locations'] == [] for item in result['items'])


def test_account_total_rejects_finance_run_with_revision_binding_mismatch(tmp_path):
    service, context = _cash_stock_service(tmp_path)
    requirement = _cash_requirements(service.analysis)
    real_run = service.run_metric({'context_id': context['id'], 'metric': {
        'kind': 'account_total',
        'accounts': ['cash'],
        'account_behavior': {'cash': 'stock'},
    }})
    forged = _run(service.analysis, id_suffix='finance-binding-mismatch',
                  engine='finance', analysis_id=real_run['analysis_id'],
                  finance_context_id='different-context', bindings={'actual': 'other-dataset'},
                  finance_scope=real_run['finance_scope'], result={
                      'metric_id': 'account_total',
                      'columns': ['period', 'scenario', 'currency', 'unit', 'amount'],
                      'rows': [{'period': '2026-08', 'scenario': 'actual', 'currency': 'CNY',
                                'unit': '元', 'amount': '110'}],
                  })

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [forged['id']],
                                                   'claims': [_amount_claim(forged, 0)]})

    assert result['coverage']['status'] == 'needs_attention'
    assert all(item['status'] == 'pending' for item in result['items'])
    assert all(item['locations'] == [] for item in result['items'])


def test_account_total_rejects_ordinary_sql_management_account_amount(analysis):
    save_requirements(analysis, spec(
        question='读取现金余额',
        scope={'source': {'ledger': 'cash-ledger', 'period': '2026-08', 'currency': 'CNY', 'unit': '元'}},
        items=[{'id': 'cash', 'metric': 'cash', 'requires_drilldown': False}],
    ))
    run = _run(analysis, id_suffix='cash-sql', bindings={'source': 'cash-dataset'}, finance_scope={
        'source': {'ledger': 'cash-ledger', 'period': '2026-08', 'currency': 'CNY', 'unit': '元'},
    }, result={
        'method': 'sql',
        'columns': ['management_account', 'amount'],
        'rows': [{'management_account': 'cash', 'amount': '110'}],
    })

    result = check_requirements(analysis, {'run_ids': [run['id']],
                                           'claims': [_claim(run, row=0, column='amount', value='110')]})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_profit_bridge_method_alias_matches_same_canonical_run_method(analysis):
    requirement = save_requirements(analysis, spec(
        items=[{'id': 'profit', 'metric': 'profit',
                'dimensions': {'method': '利润桥'}, 'requires_drilldown': False}],
    ))
    run = _run(analysis)

    result = check_requirements(analysis, {'requirements_id': requirement['id'],
                                           'run_ids': [run['id']],
                                           'claims': [_claim(run)]})

    assert result['coverage']['status'] == 'pass'
    assert result['items'][0]['status'] == 'answered'


def test_unclaimed_valid_profit_bridge_returns_claim_fixup_without_passing(analysis):
    save_requirements(analysis, spec(items=[{'id': 'profit', 'metric': 'profit',
                                             'requires_drilldown': False}]))
    run = _run(analysis)

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': []})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    fixups = result['items'][0]['fixups']
    claim_fixup = next(fixup for fixup in fixups if fixup['code'] == 'add_calculation_claim')
    assert {
        key: claim_fixup[key]
        for key in ('requirement_item_id', 'run_id', 'row', 'column', 'value', 'output_hash')
    } == {
        'requirement_item_id': 'profit',
        'run_id': run['id'],
        'row': 3,
        'column': 'contribution',
        'value': '5',
        'output_hash': run['output_hash'],
    }
    assert claim_fixup['fact_id']


def test_source_fixup_flows_to_completion_action_without_marking_complete(analysis):
    from foundry.finance_completion import record_completion

    save_requirements(analysis, spec())
    run = _run(analysis)
    quality = augment_quality(
        analysis,
        {'run_ids': [run['id']], 'claims': [_claim(run)]},
        {'status': 'pass', 'issues': []},
    )

    assert quality['checks']['coverage']['status'] == 'pass'
    assert quality['checks']['provenance']['status'] == 'needs_attention'
    source_issue = next(issue for issue in quality['issues'] if issue['code'] == 'requested_source_missing')
    source_fixup = next(fixup for fixup in source_issue['fixups'] if fixup['code'] == 'verify_source')
    assert source_fixup['location'] == {
        'run_id': run['id'],
        'row': 3,
        'column': 'contribution',
        'output_hash': run['output_hash'],
    }

    completion = record_completion(
        analysis,
        {'id': 's' * 32, 'content_hash': 'source-fixup-draft', 'run_ids': [run['id']]},
        quality,
    )

    assert completion['status'] == 'repair_available'
    assert completion['repair_allowed'] is True
    action = next(action for action in completion['actions'] if action['code'] == 'requested_source_missing')
    assert action['fixups'] == [source_fixup]


def test_control_totals_existing_valid_run_returns_complete_row_fixups_without_passing(tmp_path):
    service, context = _control_totals_service(tmp_path)
    _control_requirement(service.analysis)
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    cash_rows = [index for index, row in enumerate(run['result']['rows']) if row['management_account'] == 'cash']

    result = check_requirements(service.analysis, {'run_ids': [run['id']], 'claims': []})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    claim_fixups = [fixup for fixup in result['items'][0]['fixups'] if fixup['code'] == 'add_calculation_claim']
    assert {(fixup['row'], fixup['column'], fixup['value']) for fixup in claim_fixups} == {
        (cash_rows[0], 'amount', '100'),
        (cash_rows[1], 'amount', '10'),
    }
    assert all(fixup['fact_id'] for fixup in claim_fixups)


def test_claimed_profit_bridge_does_not_suggest_duplicate_calculation_fixup(analysis):
    save_requirements(analysis, spec(items=[{'id': 'profit', 'metric': 'profit',
                                             'requires_drilldown': False}]))
    run = _run(analysis)

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert result['items'][0]['status'] == 'answered'
    assert all(
        fixup['code'] != 'add_calculation_claim'
        for fixup in result['items'][0].get('fixups', [])
    )


def test_control_totals_fixup_only_suggests_unclaimed_required_rows(tmp_path):
    service, context = _control_totals_service(tmp_path)
    _control_requirement(service.analysis)
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    cash_rows = [index for index, row in enumerate(run['result']['rows']) if row['management_account'] == 'cash']

    result = check_requirements(service.analysis, {'run_ids': [run['id']],
                                                   'claims': [_amount_claim(run, cash_rows[0])]})

    claim_fixups = [fixup for fixup in result['items'][0]['fixups'] if fixup['code'] == 'add_calculation_claim']
    assert [(fixup['row'], fixup['column'], fixup['value']) for fixup in claim_fixups] == [
        (cash_rows[1], 'amount', '10')
    ]


def test_control_totals_fixup_rejects_same_dataset_id_with_stale_hashes(tmp_path):
    service, context = _control_totals_service(tmp_path)
    requirement = service.analysis_requirements_save({
        'question': '核对8月现金控制合计，必须覆盖CNY和USD',
        'context_id': context['id'],
        'scope': {'actual': {'ledger': 'control-ledger', 'organization': '总部',
                             'period': '2026-08', 'scenario': 'actual'}},
        'items': [{'id': 'cash_controls', 'metric': 'control_totals',
                   'dimensions': {'management_account': 'cash'}, 'periods': ['2026-08'],
                   'requires_drilldown': True}],
    })
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    stale = {key: value for key, value in run.items() if key != '_integrity_hash'}
    stale.update(_new(service.analysis.task))
    stale.update({'input_hashes': {'actual': 'stale-data-hash'},
                  'source_hashes': {'actual': 'stale-source-hash'}})
    service.analysis._write(service.analysis._object_path('runs', stale['id']), stale)

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'],
                                                   'run_ids': [stale['id']], 'claims': []})

    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0].get('fixups', []) == []


def test_profit_bridge_fixup_rejects_unclosed_fact_group(analysis):
    save_requirements(analysis, spec(items=[{'id': 'profit', 'metric': 'profit',
                                             'requires_drilldown': False}]))
    run = _run(analysis, result={
        'method': 'revenue_minus_cost_minus_expense',
        'columns': ['metric', 'actual', 'baseline', 'contribution'],
        'rows': [
            {'metric': 'revenue', 'actual': '120', 'baseline': '100', 'contribution': '20'},
            {'metric': 'cost', 'actual': '70', 'baseline': '60', 'contribution': '-10'},
            {'metric': 'expense', 'actual': '20', 'baseline': '15', 'contribution': '-5'},
            {'metric': 'profit', 'actual': '30', 'baseline': '25', 'contribution': '6'},
        ],
    })

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': []})

    assert result['items'][0]['status'] == 'pending'
    assert all(
        fixup['code'] != 'add_calculation_claim'
        for fixup in result['items'][0].get('fixups', [])
    )


def test_control_totals_fixup_reports_truncated_result_instead_of_partial_claims(tmp_path):
    service, context = _control_totals_service(tmp_path)
    _control_requirement(service.analysis)
    run = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    truncated = {key: value for key, value in run.items() if key != '_integrity_hash'}
    truncated.update(_new(service.analysis.task))
    truncated['result'] = {**run['result'], 'truncated': True, 'row_count': len(run['result']['rows'])}
    service.analysis._write(service.analysis._object_path('runs', truncated['id']), truncated)

    result = check_requirements(service.analysis, {'run_ids': [truncated['id']], 'claims': []})

    fixups = result['items'][0]['fixups']
    assert [fixup['code'] for fixup in fixups] == ['result_set_incomplete']
    assert fixups[0]['row_count'] == len(run['result']['rows'])


def test_non_string_method_dimension_does_not_crash_or_match_as_alias(analysis):
    save_requirements(analysis, spec(items=[{'id': 'profit', 'metric': 'profit',
                                             'dimensions': {'method': ['利润桥']},
                                             'requires_drilldown': False}]))
    run = _run(analysis)

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []


def test_method_conflict_fixup_does_not_relax_matching(analysis):
    save_requirements(analysis, spec(items=[{'id': 'profit', 'metric': 'profit',
                                             'dimensions': {'method': 'free_sql'},
                                             'requires_drilldown': False}]))
    run = _run(analysis)

    result = check_requirements(analysis, {'run_ids': [run['id']], 'claims': [_claim(run)]})

    assert result['coverage']['status'] == 'needs_attention'
    assert result['items'][0]['status'] == 'pending'
    assert result['items'][0]['locations'] == []
    conflict = next(fixup for fixup in result['items'][0]['fixups'] if fixup['code'] == 'method_conflict')
    assert conflict['expected_method'] == 'free_sql'
    assert conflict['actual_method'] == 'revenue_minus_cost_minus_expense'


# --- explain_variance closures count only on the inputs the requirement asks for (issues #25, #26) ---------------

BRIDGE_BASE = {'ledger': 'L1', 'organization': 'O1', 'currency': 'CNY', 'unit': '万元'}
BRIDGE_SCOPES = {
    'flat': {**BRIDGE_BASE, 'period': '2026-09'},
    'two_sided': {'actual': {**BRIDGE_BASE, 'period': '2026-09', 'scenario': 'actual'},
                  'budget': {**BRIDGE_BASE, 'period': '2026-09', 'scenario': 'budget'}},
}
# revenue 1120 vs 1000, cost 450 vs 420, expense 110 vs 100: revenue +120, profit +80.
BRIDGE_ACTUAL = [('2026-09', 'A', 'revenue', '120'), ('2026-09', 'B', 'revenue', '1000'), ('2026-09', 'A', 'cost', '50'),
                 ('2026-09', 'B', 'cost', '400'), ('2026-09', 'A', 'expense', '10'), ('2026-09', 'B', 'expense', '100')]
BRIDGE_BUDGET = [('2026-09', 'A', 'revenue', '100'), ('2026-09', 'B', 'revenue', '900'), ('2026-09', 'A', 'cost', '40'),
                 ('2026-09', 'B', 'cost', '380'), ('2026-09', 'A', 'expense', '10'), ('2026-09', 'B', 'expense', '90')]
# The prior year: revenue 1050, profit 515, so year on year revenue +70, profit +45.
BRIDGE_PRIOR = [('2025-09', 'A', 'revenue', '100'), ('2025-09', 'B', 'revenue', '950'), ('2025-09', 'A', 'cost', '45'),
                ('2025-09', 'B', 'cost', '385'), ('2025-09', 'A', 'expense', '5'), ('2025-09', 'B', 'expense', '100')]


def _bridge_check(tmp_path, scope, variance, *, credit_revenue=False, prior=False, items=None):
    """A profit bridge on actual/budget ledgers, its revenue and profit contributions cited for revenue and
    profit items; returns (check result, the run's revenue and profit contributions)."""
    def rows(scenario, amounts):
        return [{**BRIDGE_BASE, 'period': period, 'scenario': scenario, 'management_account': account,
                 'amount': ('-' + amount) if credit_revenue and account == 'revenue' else amount,
                 'product': product, 'source_row': index}
                for index, (period, product, account, amount) in enumerate(amounts, start=1)]
    service, context, _ = _finance_service_from_rows(
        tmp_path, {'actual': rows('actual', BRIDGE_ACTUAL + (BRIDGE_PRIOR if prior else [])),
                   'budget': rows('budget', BRIDGE_BUDGET)},
        {'actual': {**BRIDGE_BASE, 'scenario': 'actual'}, 'budget': {**BRIDGE_BASE, 'scenario': 'budget'}},
        title='bridge-inputs')
    requirement = service.analysis_requirements_save({
        'question': '9 月营业收入与利润差异', 'context_id': context['id'], 'scope': BRIDGE_SCOPES[scope] if isinstance(scope, str) else scope,
        'items': items or [{'id': 'revenue', 'metric': 'revenue', 'requires_drilldown': False},
                           {'id': 'profit', 'metric': 'profit', 'requires_drilldown': False}]})
    run = service.explain_variance({'context_id': context['id'], 'kind': 'profit_bridge', **variance})
    rows_ = run['result']['rows']
    claims = [{'basis': 'calculation', 'run_id': run['id'], 'row': index, 'column': 'contribution',
               'value': row['contribution']}
              for index, row in enumerate(rows_) if row['metric'] in ('revenue', 'profit')]
    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                   'claims': claims})
    return result, {row['metric']: row['contribution'] for row in rows_ if row['metric'] in ('revenue', 'profit')}


def _bridge_statuses(result):
    return {item['id']: (item['status'], [(location['evidence'].get('evidence_basis'),
                                            location['evidence'].get('not_counted_reason'))
                                           for location in item['locations']])
            for item in result['items']}


@pytest.mark.parametrize('scope', ['flat', 'two_sided'])
@pytest.mark.parametrize('scale', ['0.6524', '1000', '0', '2'])
def test_a_bridge_whose_account_signs_scale_a_line_does_not_answer_revenue_or_profit(tmp_path, scope, scale):
    """Issue #25: account_signs multiply every undirected row of the line; any factor other than a sign scales
    it, and the scaled bridge still closes. A recipe with that scale is coefficient_unbound (decision 1); an
    engine closure on scaled lines does not count either."""
    result, contributions = _bridge_check(tmp_path, scope, {'account_signs': {'revenue': scale}})

    assert contributions['revenue'] != '120'
    reason = [('engine_output', 'account_signs_not_unit')]
    assert _bridge_statuses(result) == {'revenue': ('not_applicable', reason), 'profit': ('not_applicable', reason)}
    assert result['coverage']['status'] == 'needs_attention'
    from foundry.finance_requirements import _unanswered_message
    assert 'account_signs 只能写 1 或 -1' in _unanswered_message(result['items'][0])


@pytest.mark.parametrize('variance, credit_revenue', [
    ({}, False),
    ({'account_signs': {'revenue': '1'}}, False),
    ({'account_signs': {'revenue': '1.00', 'cost': '-1', 'expense': '-1'}}, False),
    # A ledger that books revenue as negative credits states its sign with -1, and the bridge is right.
    ({'account_signs': {'revenue': '-1'}}, True),
])
@pytest.mark.parametrize('scope', ['flat', 'two_sided'])
def test_account_signs_that_only_state_a_lines_sign_still_answer(tmp_path, scope, variance, credit_revenue):
    result, contributions = _bridge_check(tmp_path, scope, variance, credit_revenue=credit_revenue)

    assert {line: Decimal(value) for line, value in contributions.items()} == {'revenue': 120, 'profit': 80}
    closed = [('engine_closed', None)]
    assert _bridge_statuses(result) == {'revenue': ('answered', closed), 'profit': ('answered', closed)}
    assert result['coverage']['status'] == 'pass'


@pytest.mark.parametrize('scope', ['flat', 'two_sided'])
@pytest.mark.parametrize('filters', [
    {'actual_filters': {'source_row': [1, 3, 5]}, 'baseline_filters': {'source_row': [1, 3, 5]}},
    {'actual_filters': {'source_row': [2, 4, 6]}, 'baseline_filters': {'source_row': [2, 4, 6]}},
    # Only the actual side is narrowed (product A's revenue row left out); the period restates the scope.
    {'actual_filters': {'period': '2026-09', 'source_row': [2, 3, 4, 5, 6]}, 'baseline_filters': {'period': '2026-09'}},
])
def test_a_bridge_over_part_of_the_rows_does_not_answer_the_whole_scope(tmp_path, scope, filters):
    """Issue #26: filters on a field the requirement never names (source rows, one product's rows) make the
    bridge a bridge of that subset. It closes, but it is not the requirement's revenue or profit."""
    result, contributions = _bridge_check(tmp_path, scope, filters)

    assert contributions['revenue'] not in (None, '120')
    reason = [(None, 'comparison_filters_differ')]
    assert _bridge_statuses(result) == {'revenue': ('pending', reason), 'profit': ('pending', reason)}
    assert result['coverage']['status'] == 'needs_attention'
    from foundry.finance_requirements import _unanswered_message
    assert '差异桥闭合的是这部分行' in _unanswered_message(result['items'][0])


@pytest.mark.parametrize('filters', [
    {},
    # Filters that restate the scope on one side, or write the same value as a list, select the same rows.
    {'baseline_filters': {'organization': 'O1'}},
    {'actual_filters': {'period': '2026-09'}, 'baseline_filters': {'period': ['2026-09']}},
    {'actual_filters': {'ledger': 'L1'}},
])
def test_a_bridge_of_a_scenario_against_itself_does_not_answer(tmp_path, filters):
    """Issue #26: with a flat scope (the Huachen style) nothing names the sides, and budget against budget
    closes at 0."""
    result, contributions = _bridge_check(tmp_path, 'flat', {'actual_scenario': 'budget', 'baseline_scenario': 'budget',
                                                             **filters})

    assert contributions == {'revenue': '0', 'profit': '0'}
    reason = [('engine_output', 'comparison_same_side')]
    assert _bridge_statuses(result) == {'revenue': ('not_applicable', reason), 'profit': ('not_applicable', reason)}
    assert result['coverage']['status'] == 'needs_attention'


def test_a_year_on_year_bridge_that_forgot_its_baseline_period_does_not_answer(tmp_path):
    """Review round 2: actual against actual with only the actual side narrowed to 2026-09 and the prior year's
    group assumed zero: the 2026-09 row compares the actual with itself (1120 vs 1120), while the 2025-09 row has
    no actual side at all."""
    result, contributions = _bridge_check(tmp_path, 'flat', {
        'actual_scenario': 'actual', 'baseline_scenario': 'actual', 'actual_filters': {'period': '2026-09'},
        'missing_groups_as_zero': True}, prior=True)

    assert contributions['revenue'] == '0'
    reason = [('engine_output', 'comparison_same_side')]
    assert _bridge_statuses(result) == {'revenue': ('not_applicable', reason), 'profit': ('not_applicable', reason)}


@pytest.mark.parametrize('scope, variance, expected', [
    # Filters that restate the requirement's own period.
    ('flat', {'actual_filters': {'period': '2026-09'}, 'baseline_filters': {'period': '2026-09'}}, ('120', '80')),
    ('two_sided', {'actual_filters': {'period': '2026-09'}, 'baseline_filters': {'period': '2026-09'}}, ('120', '80')),
    ('flat', {'actual_filters': {'organization': 'O1', 'period': '2026-09', 'ledger': 'L1'},
              'baseline_filters': {'organization': 'O1'}}, ('120', '80')),
    # Each side's own scenario restated (tests/test_finance_evals.py calls explain_variance this way).
    ('flat', {'actual_filters': {'scenario': 'actual'}, 'baseline_filters': {'scenario': 'budget'}}, ('120', '80')),
    ('flat', {'actual_filters': {'scenario': ['actual'], 'period': '2026-09'},
              'baseline_filters': {'scenario': 'budget', 'period': ['2026-09']}}, ('120', '80')),
    ('two_sided', {'actual_filters': {'scenario': 'actual'}, 'baseline_filters': {'scenario': 'budget'}}, ('120', '80')),
    ('flat', {'actual_filters': {'scenario': ['actual', 'budget']}, 'baseline_filters': {'scenario': ['actual', 'budget']}},
     ('120', '80')),
    # Filters that list the requirement's value among others of a field the bridge groups by (organization is
    # always a grouping field): the cited row is that value's whole group (review round 2).
    ('flat', {'actual_filters': {'organization': ['O1', 'O2']}, 'baseline_filters': {'organization': ['O1', 'O2']}},
     ('120', '80')),
    ('two_sided', {'actual_filters': {'organization': ['O1', 'O2'], 'scenario': 'actual'},
                   'baseline_filters': {'organization': ['O1', 'O2'], 'scenario': 'budget'}}, ('120', '80')),
    # Year on year: one scenario, two periods. A flat scope pins only the actual period, as on main.
    ('flat', {'actual_scenario': 'actual', 'baseline_scenario': 'actual', 'actual_filters': {'period': '2026-09'},
              'baseline_filters': {'period': '2025-09'}}, ('70', '45')),
    ({**BRIDGE_BASE, 'period': '2026-09', 'baseline_period': '2025-09'},
     {'actual_scenario': 'actual', 'baseline_scenario': 'actual', 'actual_filters': {'period': '2026-09'},
      'baseline_filters': {'period': '2025-09'}}, ('70', '45')),
])
def test_bridge_filters_that_restate_the_requirement_still_answer(tmp_path, scope, variance, expected):
    # The prior year's rows only for the year-on-year cases; elsewhere they would be a period with no budget.
    result, contributions = _bridge_check(tmp_path, scope, variance, prior=expected == ('70', '45'))

    assert contributions == {'revenue': expected[0], 'profit': expected[1]}
    closed = [('engine_closed', None)]
    assert _bridge_statuses(result) == {'revenue': ('answered', closed), 'profit': ('answered', closed)}


def test_the_profit_bridge_intent_is_not_answered_by_a_bridge_over_part_of_the_rows(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='partial-bridge')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = _run_east_profit_bridge(service, context,
                                  actual_filters={'organization': '华东', 'period': '2026-08', 'source_row': [1]},
                                  baseline_filters={'organization': '华东', 'period': '2026-08', 'source_row': [4]})
    _verify_run_column(service, run, 'contribution')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                   'claims': _claims_for_columns(run, 'contribution')})

    item = result['items'][0]
    assert item['status'] == 'pending' and result['coverage']['status'] == 'needs_attention'
    assert {location['evidence'].get('not_counted_reason') for location in item['locations']} == {'comparison_filters_differ'}


def test_the_profit_bridge_intent_still_answers_a_bridge_whose_filters_restate_each_sides_scenario(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='scenario-restated-bridge')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = _run_east_profit_bridge(service, context,
                                  actual_filters={'organization': '华东', 'period': '2026-08', 'scenario': 'actual'},
                                  baseline_filters={'organization': '华东', 'period': '2026-08', 'scenario': 'budget'})
    _verify_run_column(service, run, 'contribution')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                   'claims': _claims_for_columns(run, 'contribution')})

    assert result['items'][0]['status'] == 'answered' and result['coverage']['status'] == 'pass'


def test_the_profit_bridge_intent_is_not_answered_by_a_bridge_with_scaled_lines(tmp_path):
    service, context, bindings = _regional_service(tmp_path, title='scaled-bridge')
    requirement = _profit_bridge_requirement(service, context, bindings)
    run = service.explain_variance({
        'context_id': context['id'], 'method': 'revenue_minus_cost_minus_expense', 'actual_scenario': 'actual',
        'baseline_scenario': 'budget', 'actual_filters': {'organization': '华东', 'period': '2026-08'},
        'baseline_filters': {'organization': '华东', 'period': '2026-08'}, 'account_signs': {'cost': '-0.5'}})
    _verify_run_column(service, run, 'contribution')

    result = check_requirements(service.analysis, {'requirements_id': requirement['id'], 'run_ids': [run['id']],
                                                   'claims': _claims_for_columns(run, 'contribution')})

    item = result['items'][0]
    assert item['status'] != 'answered' and result['coverage']['status'] == 'needs_attention'
    assert {location['evidence'].get('not_counted_reason') for location in item['locations']} == {'account_signs_not_unit'}
