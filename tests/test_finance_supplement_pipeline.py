"""Independent observer counterexamples; no provider or product mocks claim acceptance."""
from copy import deepcopy

import pytest

from tools import finance_supplement_cases as helper
from tools import verify_finance_supplement_pipeline as driver


def numeric_sample():
    case = helper.load_suite(helper.DEFAULT_FIXTURES)['cases'][0]
    rows = [{'metric_key': key, 'value': value} for key, value in case['oracle']['expected_values'].items()]
    return case, rows


def test_exact_independent_thirteen_values():
    case, rows = numeric_sample()
    assert driver.numeric_problems(rows, case['oracle']) == []


@pytest.mark.parametrize('mutation', ['wrong_amount', 'same_value_wrong_metric', 'missing', 'duplicate', 'nan'])
def test_internal_model_checks_cannot_replace_independent_oracle(mutation):
    case, rows = numeric_sample()
    if mutation == 'wrong_amount':
        rows[0]['value'] = '101'
    elif mutation == 'same_value_wrong_metric':
        # Both balance-sheet sides are 647: equal values do not merge metric identities.
        next(r for r in rows if r['metric_key'] == 'total_assets')['metric_key'] = 'total_liabilities_equity'
    elif mutation == 'missing':
        rows.pop()
    elif mutation == 'duplicate':
        rows.append(deepcopy(rows[0]))
    else:
        rows[0]['value'] = 'NaN'
    assert driver.numeric_problems(rows, case['oracle'])


def test_negative_rejection_needs_exact_product_reason_not_any_crash():
    expected = {'must_reject_template_execution': True, 'error_contains': 'unsupported boundary', 'qualified_evidence': False}
    evidence = {'observed': True, 'current_complete': False, 'qualified_evidence': False,
                'execution_failed': True, 'execution_error': 'unsupported boundary', 'history_errors': []}
    assert driver.negative_problems(expected, evidence) == []
    evidence['execution_error'] = 'transport timeout'
    assert driver.negative_problems(expected, evidence)


@pytest.mark.parametrize('field,value', [('observed', False), ('current_complete', True), ('qualified_evidence', True),
                                        ('history_errors', ['analysis/runs/old.json'])])
def test_negative_labels_cannot_hide_invalid_evidence(field, value):
    evidence = {'observed': True, 'current_complete': False, 'qualified_evidence': False,
                'history_errors': [], 'professional_status': 'awaiting_profile_confirmation'}
    expected = {'professional_status': 'awaiting_profile_confirmation', 'qualified_evidence': False}
    assert driver.negative_problems(expected, evidence) == []
    evidence[field] = value
    assert driver.negative_problems(expected, evidence)


def test_invalidation_requires_real_completed_control_and_unchanged_original_receipt():
    expected = {'historical_complete_retained': True, 'qualified_evidence': False}
    evidence = {'observed': True, 'current_complete': False, 'qualified_evidence': False,
                'history_errors': [], 'control_passed': True, 'historical_complete_retained': True}
    assert driver.negative_problems(expected, evidence) == []
    for key in ('control_passed', 'historical_complete_retained'):
        bad = {**evidence, key: False}
        assert driver.negative_problems(expected, bad)


def test_current_receipt_and_validation_are_mandatory():
    assert driver.completion_problems({'accepted': True, 'current_draft': {'id': 'd', 'quality': {'status': 'pass'}}})


def test_history_hashes_include_binary_sources_and_only_exclude_exact_counters(tmp_path):
    for name in ('source.xlsx', 'analysis/sequence.json', 'analysis/runs/sequence.json', '.lock'):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'original')
    before = helper.history_hashes(tmp_path)
    assert set(before) == {'source.xlsx', 'analysis/runs/sequence.json'}
    (tmp_path / 'source.xlsx').write_bytes(b'changed')
    assert helper.unchanged_history(before, helper.history_hashes(tmp_path)) == ['source.xlsx']


def complete_shape():
    suite = helper.load_suite(helper.DEFAULT_FIXTURES)
    case, contract = suite['cases'][0], suite['contract']
    ids = dict.fromkeys(helper.DATASET_NAMES, 'source')
    expected = {**case['manifest_entry']['source_bindings'], **case['manifest_entry']['boundary_bindings']}
    bindings = {name: {'status': 'source_verified', **item['scope'],
                       **{key: item[key] for key in ('period', 'currency', 'unit')},
                       'source_rows': [{'dataset_id': 'source', 'column': 'amount'}]} for name, item in expected.items()}
    boundaries = contract['preconditions']['boundary_names']
    rows = []
    for metric, value in case['oracle']['expected_values'].items():
        statement, line, kind = driver.SEMANTICS[metric]
        rows.append({'metric_key': metric, 'value': value, 'statement': statement, 'statement_line': line,
                     'value_kind': kind, 'status': 'source_verified',
                     **{key: contract['scope'][key] for key in ('organization', 'period', 'currency', 'unit')},
                     'source_rows': [{'dataset_id': 'source'}], 'source_binding_ids': boundaries})
    result = {'rows': rows, 'scenario_id': 'scenario', 'template_id': contract['template_id'],
              'model_checks': [{'id': name, 'status': 'pass', 'source_rows': [{'dataset_id': 'source'}]}
                               for name in contract['required_model_checks']],
              'source_binding_status': {'all_sources_verified': True, 'bindings': bindings},
              'model_boundary': [{'name': name.removeprefix('boundary.'), 'value': '0'} for name in boundaries]}
    run = {'id': 'run', 'engine': 'finance', 'execution_status': 'succeeded', 'result': result, 'output_hash': helper.digest(result)}
    claims = [{'basis': 'calculation', 'run_id': 'run', 'row': i, 'column': 'value', 'value': row['value']}
              for i, row in enumerate(rows)]
    draft = {'id': 'draft', 'requirements_id': 'req', 'content_hash': 'content', 'quality': {'status': 'pass'},
             'claims': claims, 'explanation_check': {'requirements': {'items': [
                 {'metric': name, 'status': 'answered'} for name in contract['required_metrics']]}}}
    receipt = {'id': 'receipt', 'status': 'complete', 'draft_id': 'draft', 'requirements_id': 'req',
               'draft_content_hash': 'content', 'original_requirements_completed': True,
               'checks': {'coverage': {'status': 'pass'}}}
    outcome = {'current_draft': draft, 'current_completion': receipt,
               'validation': {'returncode': 0, 'value': {'status': 'pass'}},
               'after': {'drafts': [draft], 'completions': [receipt]}}
    facts = [{'row': i, 'column': 'value', 'evidence_eligibility': {'counts_as_amount_evidence': True}} for i in range(13)]
    return case, contract, run, outcome, facts, ids, 'scenario'


def test_complete_shape_requires_every_independent_dimension():
    assert driver.positive_problems(*complete_shape()) == []


@pytest.mark.parametrize('mutation', ['wrong_statement', 'wrong_kind', 'wrong_period', 'wrong_ledger', 'wrong_scenario',
                                      'foreign_source', 'missing_boundary', 'missing_check', 'failed_check',
                                      'missing_claim', 'unqualified_fact', 'missing_receipt', 'validation_failed'])
def test_positive_label_cannot_mask_contract_violation(mutation):
    args = complete_shape()
    _, _, run, outcome, facts, _, _ = args
    result = run['result']
    if mutation == 'wrong_statement':
        result['rows'][0]['statement'] = 'balance_sheet'
    elif mutation == 'wrong_kind':
        result['rows'][0]['value_kind'] = 'stock'
    elif mutation == 'wrong_period':
        result['rows'][0]['period'] = '2026-09'
    elif mutation == 'wrong_ledger':
        result['source_binding_status']['bindings']['revenue']['ledger'] = 'other'
    elif mutation == 'wrong_scenario':
        result['scenario_id'] = 'other'
    elif mutation == 'foreign_source':
        result['source_binding_status']['bindings']['revenue']['source_rows'][0]['dataset_id'] = 'invented'
    elif mutation == 'missing_boundary':
        result['model_boundary'].pop()
    elif mutation == 'missing_check':
        result['model_checks'].pop()
    elif mutation == 'failed_check':
        result['model_checks'][0]['status'] = 'fail'
    elif mutation == 'missing_claim':
        outcome['current_draft']['claims'].pop()
    elif mutation == 'unqualified_fact':
        facts[0]['evidence_eligibility']['counts_as_amount_evidence'] = False
    elif mutation == 'missing_receipt':
        outcome['after']['completions'] = []
    else:
        outcome['validation']['value']['status'] = 'fail'
    run['output_hash'] = helper.digest(result)
    assert driver.positive_problems(*args)


def test_historical_success_cannot_masquerade_as_current_requirement_completion():
    state = {'requirements': [{'id': 'old', 'seq': 1}, {'id': 'current', 'seq': 3}],
             'drafts': [{'id': 'old-draft', 'requirements_id': 'old', 'seq': 2},
                        {'id': 'current-draft', 'requirements_id': 'current', 'seq': 4}],
             'completions': [{'id': 'old-receipt', 'requirements_id': 'old', 'draft_id': 'old-draft', 'status': 'complete'},
                             {'id': 'current-receipt', 'requirements_id': 'current', 'draft_id': 'current-draft', 'status': 'awaiting_manager'}]}
    assert driver.current_complete(state) is False
    state['completions'][1]['status'] = 'complete'
    assert driver.current_complete(state) is True
    state['completions'].pop()
    assert driver.current_complete(state) is None


@pytest.mark.parametrize('status', [None, '', 'unknown', 'blocked'])
def test_missing_or_unknown_current_receipt_status_is_not_negative_success(status):
    state = {'requirements': [{'id': 'req', 'seq': 1}],
             'drafts': [{'id': 'draft', 'requirements_id': 'req', 'seq': 2}],
             'completions': [{'id': 'receipt', 'draft_id': 'draft', 'requirements_id': 'req', 'status': status}]}
    assert driver.current_complete(state) is None
