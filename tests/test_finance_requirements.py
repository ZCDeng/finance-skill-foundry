"""Task coverage cannot be hidden by narrowing a draft's run list."""
import json

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
    record = _new(
        analysis.task,
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
