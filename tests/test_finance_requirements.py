"""Task coverage cannot be hidden by narrowing a draft's run list."""
import pytest

from foundry.analysis import AnalysisStore
from foundry.analysis import _new
from foundry.errors import FoundryError
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
