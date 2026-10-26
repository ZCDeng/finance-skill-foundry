#!/usr/bin/env python3
"""Actual isolated CLI checks for the frozen independent three-statement supplement.

This is engineering evidence, with zero provider calls and zero original-slot
credit. Public inputs alone construct native requests; private oracles are read
only by the observer. No stored product record is edited by this controller.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import finance_supplement_cases as shared  # noqa: E402

# Semantic checks are separate from the template's own arithmetic/check engine.
SEMANTICS = {
    'net_income': ('income_statement', 'net_income', 'flow'),
    'cash_flow_operating': ('cash_flow', 'operating_cash_flow', 'flow'),
    'cash_flow_investing': ('cash_flow', 'investing_cash_flow', 'flow'),
    'cash_flow_financing': ('cash_flow', 'financing_cash_flow', 'flow'),
    'closing_cash': ('balance_sheet', 'cash', 'stock'),
    'closing_receivables': ('balance_sheet', 'accounts_receivable', 'stock'),
    'closing_ppe': ('balance_sheet', 'property_plant_equipment_net', 'stock'),
    'closing_payables': ('balance_sheet', 'accounts_payable', 'stock'),
    'closing_debt': ('balance_sheet', 'debt_principal', 'stock'),
    'closing_equity': ('balance_sheet', 'equity', 'stock'),
    'total_assets': ('balance_sheet', 'total_assets', 'stock'),
    'total_liabilities_equity': ('balance_sheet', 'total_liabilities_equity', 'stock'),
    'available_cash': ('liquidity', 'available_cash', 'stock'),
}


def decimal_equal(actual, expected):
    try:
        a, b = Decimal(str(actual)), Decimal(str(expected))
        return a.is_finite() and b.is_finite() and a == b
    except (ValueError, InvalidOperation):
        return False


def numeric_problems(rows, oracle):
    expected = oracle['expected_values']
    selected = [r for r in rows if r.get('metric_key') in expected]
    counts = Counter(r.get('metric_key') for r in selected)
    problems = []
    for metric, value in expected.items():
        values = [r.get('value') for r in selected if r['metric_key'] == metric]
        if counts[metric] != 1:
            problems.append('metric_identity_not_unique:' + metric)
        elif not decimal_equal(values[0], value):
            problems.append('independent_oracle_mismatch:' + metric)
    return problems


def completion_problems(outcome):
    problems = []
    draft, receipt = outcome.get('current_draft') or {}, outcome.get('current_completion') or {}
    validation = outcome.get('validation') or {}
    if validation.get('returncode') != 0 or (validation.get('value') or {}).get('status') != 'pass':
        problems.append('actual_validation_not_passed')
    if draft.get('quality', {}).get('status') != 'pass':
        problems.append('current_draft_not_passed')
    if (not receipt.get('id') or receipt.get('status') != 'complete'
            or receipt.get('draft_id') != draft.get('id')
            or receipt.get('requirements_id') != draft.get('requirements_id')
            or receipt.get('draft_content_hash') != draft.get('content_hash')
            or receipt.get('original_requirements_completed') is not True
            or receipt.get('checks', {}).get('coverage', {}).get('status') != 'pass'):
        problems.append('current_bound_receipt_not_complete')
    after = outcome.get('after') or {}
    if draft not in after.get('drafts', []) or receipt not in after.get('completions', []):
        problems.append('current_surfaces_not_persisted')
    return problems


def positive_problems(case, contract, run, outcome, facts, dataset_ids, scenario_id):
    result = run.get('result') or {}
    rows = result.get('rows', [])
    problems = numeric_problems(rows, case['oracle']) + completion_problems(outcome)
    if (run.get('engine') != 'finance' or run.get('execution_status') != 'succeeded'
            or run.get('output_hash') != shared.digest(result)
            or result.get('template_id') != contract['template_id'] or result.get('scenario_id') != scenario_id):
        problems.append('native_run_identity_invalid')
    metrics = set(contract['required_metrics'])
    checks = result.get('model_checks', [])
    if (len(checks) != 12 or {c.get('id') for c in checks} != set(contract['required_model_checks'])
            or any(c.get('status') != 'pass' or not c.get('source_rows') for c in checks)):
        problems.append('twelve_source_bound_checks_not_passed')
    binding_status = result.get('source_binding_status') or {}
    bindings = binding_status.get('bindings') or {}
    expected_bindings = {**case['manifest_entry']['source_bindings'], **case['manifest_entry']['boundary_bindings']}
    if set(bindings) != set(expected_bindings) or binding_status.get('all_sources_verified') is not True:
        problems.append('twenty_four_source_bindings_not_verified')
    for name, expected in expected_bindings.items():
        proof = bindings.get(name, {})
        if (proof.get('status') != 'source_verified'
                or any(proof.get(k) != v for k, v in expected['scope'].items())
                or any(proof.get(k) != expected[k] for k in ('period', 'currency', 'unit'))
                or not proof.get('source_rows')
                or any(ref.get('dataset_id') != dataset_ids[expected['alias']] or ref.get('column') != 'amount'
                       for ref in proof.get('source_rows', []))):
            problems.append('source_binding_scope_or_reference:' + name)
    boundaries = set(contract['preconditions']['boundary_names'])
    actual_boundaries = result.get('model_boundary') or []
    if (len(actual_boundaries) != 8 or {'boundary.' + b.get('name', '') for b in actual_boundaries} != boundaries
            or any(not decimal_equal(b.get('value'), '0') for b in actual_boundaries)):
        problems.append('eight_zero_boundaries_missing')
    for row in rows:
        metric = row.get('metric_key')
        if metric not in metrics:
            continue
        if tuple(row.get(k) for k in ('statement', 'statement_line', 'value_kind')) != SEMANTICS[metric]:
            problems.append('output_semantic_identity:' + metric)
        if (any(row.get(k) != contract['scope'][k] for k in ('organization', 'period', 'currency', 'unit'))
                or row.get('status') != 'source_verified' or not row.get('source_rows')
                or not boundaries <= set(row.get('source_binding_ids', []))
                or any(ref.get('dataset_id') not in dataset_ids.values() for ref in row.get('source_rows', []))):
            problems.append('output_provenance_or_scope:' + metric)
    draft = outcome.get('current_draft') or {}
    answered = draft.get('explanation_check', {}).get('requirements', {}).get('items', [])
    if (len(answered) != 13 or {i.get('metric') for i in answered} != metrics
            or any(i.get('status') != 'answered' for i in answered)):
        problems.append('thirteen_requirements_not_answered')
    cited = set()
    for claim in draft.get('claims', []):
        if claim.get('basis') != 'calculation' or claim.get('run_id') != run.get('id') or claim.get('column') != 'value':
            continue
        index = claim.get('row')
        if type(index) is int and 0 <= index < len(rows) and decimal_equal(claim.get('value'), rows[index].get('value')):
            cited.add(rows[index].get('metric_key'))
    if not metrics <= cited:
        problems.append('thirteen_distinct_metric_citations_missing')
    output_facts = [f for f in facts if f.get('column') == 'value' and type(f.get('row')) is int
                    and 0 <= f['row'] < len(rows) and rows[f['row']].get('metric_key') in metrics]
    if (len(output_facts) != 13 or any(f.get('evidence_eligibility', {}).get('counts_as_amount_evidence') is not True
                                       for f in output_facts)):
        problems.append('thirteen_amount_facts_not_qualified')
    return sorted(set(problems))



def current_complete(state):
    """Current means latest requirements and their latest saved draft, not history."""
    if any(not isinstance(state.get(k), list) for k in ('requirements', 'drafts', 'completions')):
        return None
    if not state['requirements']:
        return None
    requirement = max(state['requirements'], key=lambda row: row.get('seq', -1))
    drafts = [d for d in state['drafts'] if d.get('requirements_id') == requirement.get('id')]
    if not drafts:
        return False
    draft = max(drafts, key=lambda row: row.get('seq', -1))
    receipts = [r for r in state['completions'] if r.get('requirements_id') == requirement['id']
                and r.get('draft_id') == draft['id']]
    if not receipts:
        return None
    status = max(receipts, key=lambda row: row.get('seq', -1)).get('status')
    if status not in {'complete', 'awaiting_input', 'awaiting_manager', 'needs_requirements', 'needs_review', 'repair_available'}:
        return None
    return status == 'complete'


def negative_problems(expected, evidence):
    problems = []
    if evidence.get('observed') is not True:
        problems.append('missing_actual_observation')
    if evidence.get('current_complete') is not False:
        problems.append('invalid_current_complete_receipt')
    if evidence.get('qualified_evidence') is not False:
        problems.append('invalid_amount_evidence_qualified')
    if evidence.get('history_errors'):
        problems.append('historical_bytes_changed')
    if 'professional_status' in expected and evidence.get('professional_status') != expected['professional_status']:
        problems.append('wrong_professional_status')
    if expected.get('must_reject_partial_confirmation') and evidence.get('partial_confirmation_rejected') is not True:
        problems.append('partial_confirmation_not_rejected')
    if expected.get('historical_complete_retained') and (evidence.get('control_passed') is not True
            or evidence.get('historical_complete_retained') is not True):
        problems.append('historical_completed_control_not_retained')
    if expected.get('old_approval_must_not_authorize_changed_source') and (
            evidence.get('source_rebound_without_confirmation') is not True
            or evidence.get('professional_status') != 'awaiting_profile_confirmation'
            or evidence.get('old_run_reuse_blocked') is not True):
        problems.append('source_rebinding_or_old_approval_rejection_not_demonstrated')
    if expected.get('model_check_fail') not in (None, *evidence.get('failing_checks', [])):
        problems.append('required_model_check_did_not_fail')
    if expected.get('must_reject_template_execution') and (evidence.get('execution_failed') is not True
            or expected['error_contains'] not in evidence.get('execution_error', '')):
        problems.append('unrelated_or_missing_template_rejection')
    if expected.get('must_not_qualify_source_free_run') and evidence.get('source_free_numeric_bindings') is not True:
        problems.append('source_free_mutation_not_demonstrated')
    return problems


def register_dataset(cli, dataset, *, suffix=''):
    path = cli.directory / 'sources' / (dataset['name'] + suffix + '.json')
    shared.write_new(path, dataset['rows'])
    return cli.call('dataset-add', '--path', path, '--name', dataset['name'],
                    '--meta', json.dumps(dataset['metadata'], ensure_ascii=False))['id']


def seed_public(cli, public):
    cli.task = cli.call('task-new', '--title', 'Independent supplement ' + public['id'], '--period', '2026-10', raw=True)
    ids = {d['name']: register_dataset(cli, d) for d in public['datasets']}
    attachment = public['attachments'][0]
    path = cli.directory / 'sources/scenario_request.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(attachment['text'])
    ids['scenario_request'] = cli.call('dataset-add', '--path', path, '--name', 'scenario_request',
                                      '--meta', json.dumps(attachment['metadata'], ensure_ascii=False))['id']
    seed = {'taskId': cli.task, 'datasetIds': ids, 'public_sha256': shared.digest(public)}
    shared.write_new(cli.directory / 'public-input.json', public)
    shared.write_new(cli.directory / 'seed.json', seed)
    return seed


def native_chain(cli, public, setup, *, parent_requirement_id=None):
    request = shared.request_from_public(public)
    # Method resources are actual CLI reads before the first persisted calculation.
    cli.call('method-skills', '--json')
    for resource in ('FOUNDRY.md', 'forecast-models.md', 'model-checks.md'):
        cli.call('method-resource', '--skill', 'financial-statements', '--resource', resource)
    requirement = cli.call('analysis-requirements-save', spec={**({'parent_id': parent_requirement_id} if parent_requirement_id else {}), 'context_id': setup['context']['id'],
        'question': request['task'], 'items': [{'id': metric, 'metric': metric,
            'dimensions': {'template_id': request['context']['template_id'], 'scenario_id': setup['scenario']['id']},
            'requires_drilldown': False} for metric in request['required_metrics']]})
    execution = cli.call('finance-scenario-run', spec={'scenario_id': setup['scenario']['id']}, required=False)
    run = execution.get('value') if isinstance(execution.get('value'), dict) else {}
    facts = []
    if run.get('id'):
        prepared = cli.call('prepare-explanation', spec={'run_ids': [run['id']]}, required=False)
        if prepared['returncode'] == 0:
            facts = prepared['value'].get('facts', [])
    rows = run.get('result', {}).get('rows', [])
    output_facts = [f for f in facts if f.get('column') == 'value' and type(f.get('row')) is int
                    and 0 <= f['row'] < len(rows) and rows[f['row']].get('metric_key') in request['required_metrics']]
    spec = {'requirements_id': requirement['id'], 'run_ids': [run['id']] if run.get('id') else [],
            'body': '合成单实体管理预测，明示范围与来源约束见公开资料。\n' + '\n'.join('{{fact:' + f['id'] + '}}' for f in output_facts),
            'claims': [{'basis': 'calculation', 'run_id': f['run_id'], 'row': f['row'], 'column': 'value',
                        'value': f['value'], 'fact_id': f['id']} for f in output_facts]}
    outcome = shared.original_driver().outcome(cli, spec)
    return {'run': run, 'execution': execution, 'facts': facts, 'requirement': requirement, 'outcome': outcome}


def crosscheck(case, contract, chain, cli, seed, elapsed_ms, proof):
    """Schema compatibility check on native evidence, never a model attempt record."""
    from tools import finance_supplement_eval as evaluator
    row = {'completed': True, 'final_draft': chain['outcome']['current_draft'], 'duration_ms': elapsed_ms,
           'calls': cli.calls, 'controller_only': True, 'provider_calls': 0}
    oracle = {'case_id': case['case_id'], 'numeric_checks': [
        {'metric': key, 'expected': value} for key, value in case['oracle']['expected_values'].items()]}
    score = evaluator.base.score_professional_artifact(chain['outcome']['after'], oracle, row)
    seed_with_proof = {**seed, 'precondition': proof}
    problems = evaluator.supplement_problems(chain['outcome']['after'], row, contract, seed_with_proof)
    return {'scope': 'controller_only_schema_compatibility_not_provider_score', 'provider_calls': 0,
            'original_slots_credit': 0, 'duration_ms': elapsed_ms, 'base_score': score, 'supplement_errors': problems,
            'passed': score.get('status') == 'passed' and not problems}


def completed_control(cli, case, contract, public, seed):
    started = time.monotonic()
    proof = shared.prepare_preconditions(cli.foundry, cli.var, cli.task, cli.directory / 'preconditions', public, seed['datasetIds'])
    initial_history = shared.history_hashes(cli.var / 'tasks' / cli.task)
    chain = native_chain(cli, public, proof['setup'])
    problems = positive_problems(case, contract, chain['run'], chain['outcome'], chain['facts'], seed['datasetIds'], proof['scenario_id'])
    history_errors = shared.unchanged_history(initial_history, shared.history_hashes(cli.var / 'tasks' / cli.task))
    problems.extend('seed_history_changed:' + p for p in history_errors)
    schema_check = crosscheck(case, contract, chain, cli, seed, round((time.monotonic() - started) * 1000), proof)
    if not schema_check['passed']:
        problems.append('existing_scorer_schema_crosscheck_failed')
    chain.update(precondition=proof, problems=sorted(set(problems)), crosscheck=schema_check,
                 initial_history=initial_history, history_errors=history_errors)
    shared.write_new(cli.directory / 'control-result.json', chain)
    return chain


def mutate_public(public, mutation):
    altered = deepcopy(public)
    dataset = next(d for d in altered['datasets'] if d['name'] == mutation['dataset_alias'])
    rows = [r for r in dataset['rows'] if all(r.get(k) == v for k, v in mutation['row_selector'].items())]
    if len(rows) != 1:
        raise ValueError('mutation must select one public source row')
    for field in ('amount', 'period'):
        if 'replacement_' + field in mutation:
            rows[0][field] = mutation['replacement_' + field]
    return altered


def fact_qualification(facts):
    if not isinstance(facts, list):
        return None
    return any(f.get('evidence_eligibility', {}).get('counts_as_amount_evidence') is True for f in facts)


def execute_negative(cli, case, contract, negative):
    mutation = negative['mutation']
    public = shared.case_public(case)
    if mutation['stage'] == 'before_source_registration':
        public = mutate_public(public, mutation)
    seed = seed_public(cli, public)
    task_root = cli.var / 'tasks' / cli.task
    before = shared.history_hashes(task_root)
    control = None
    operation = None
    rebound = False
    old_run_reuse = None
    if mutation['stage'] == 'after_completed_control':
        control = completed_control(cli, case, contract, public, seed)
        if control['problems']:
            raise ValueError('negative prerequisite control failed: ' + ','.join(control['problems']))
        chain = control
        setup = control['precondition']['setup']
        before = shared.history_hashes(task_root)
        receipt = control['outcome']['current_completion']
        receipt_path = task_root / 'analysis/completions' / (receipt['id'] + '.json')
        receipt_hash = shared.file_hash(receipt_path)
        if mutation['action'] == 'revoke_profile_confirmation':
            operation = cli.call('finance-profile-revoke', actor='manager', spec={'id': setup['profile_confirmation']['id'],
                'reason': 'Synthetic negative case: revoke the original scoped profile confirmation'})
        else:
            altered = mutate_public(public, mutation)
            dataset = next(d for d in altered['datasets'] if d['name'] == mutation['dataset_alias'])
            replacement = register_dataset(cli, dataset, suffix='-replacement')
            bindings = dict(setup['context']['bindings'], **{mutation['dataset_alias']: replacement})
            operation = cli.call('finance-context-save', spec={**setup['specs']['context'],
                'bindings': bindings, 'parent_id': setup['context']['id']})
            rebound = operation['parent_id'] == setup['context']['id'] and operation['bindings'][mutation['dataset_alias']] != seed['datasetIds'][mutation['dataset_alias']]
            # A child context is a branch until current requirements explicitly
            # select it. Follow the existing source-replacement workflow; no
            # profile or boundary confirmation is issued on this new basis.
            scenario = cli.call('finance-scenario-save', spec={'context_id': operation['id'],
                'kind': 'driver_model', 'label': 'Changed synthetic source without reconfirmation',
                'inputs': setup['specs']['scenario_inputs']})
            setup = {**setup, 'context': operation, 'scenario': scenario}
            chain = native_chain(cli, altered, setup, parent_requirement_id=control['requirement']['id'])
            old_run_reuse = shared.original_driver().outcome(cli, {**control['outcome']['request'],
                'requirements_id': chain['requirement']['id'], 'parent_id': control['outcome']['current_draft']['id']})
        status = cli.call('finance-profile-status', spec={'context_id': setup['context']['id'], 'scenario_id': setup['scenario']['id']}, required=False)
        fresh = cli.call('prepare-explanation', spec={'run_ids': [chain['run']['id']]}, required=False)
        facts = (fresh.get('value') or {}).get('facts') if fresh['returncode'] == 0 else None
        validation = cli.call('validate-explanation', spec={'draft_id': chain['outcome']['current_draft']['id']}, required=False)
        state = cli.state()
        historical = shared.file_hash(receipt_path) == receipt_hash and json.loads(receipt_path.read_text()).get('status') == 'complete'
    else:
        shared.empty_counts(cli.state())
        setup = shared.apply_preconditions(cli, public, seed['datasetIds'], mutation=mutation)
        shared.empty_counts(cli.state())
        chain = native_chain(cli, public, setup)
        facts = chain['facts']
        state = chain['outcome']['after']
        status = setup['profile_status']
        validation = chain['outcome']['validation']
        historical = False
    execution = chain['execution']
    run = chain['run']
    error = execution.get('stderr', '') + '\n' + str(run.get('error', ''))
    boundary = setup['boundary_confirmation']
    evidence = {'observed': True, 'task_id': cli.task, 'current_complete': current_complete(state),
        'qualified_evidence': fact_qualification(facts),
        'history_errors': shared.unchanged_history(before, shared.history_hashes(task_root)),
        'professional_status': (status.get('value') or {}).get('professional_status'),
        'partial_confirmation_rejected': boundary['returncode'] != 0 and 'all eight' in boundary.get('stderr', ''),
        'control_passed': control is not None and not control['problems'], 'historical_complete_retained': historical,
        'source_rebound_without_confirmation': rebound,
        'old_run_reuse_blocked': old_run_reuse is not None and old_run_reuse['save']['returncode'] == 0
            and (old_run_reuse['current_completion'] or {}).get('status') != 'complete'
            and bool(old_run_reuse['rejection_reasons']),
        'failing_checks': [c['id'] for c in run.get('result', {}).get('model_checks', []) if c.get('status') == 'fail'],
        'execution_failed': execution['returncode'] != 0 or run.get('execution_status') == 'failed', 'execution_error': error,
        'source_free_numeric_bindings': bool(setup['specs']['scenario_inputs'].get('values')) and all(
            name.startswith('boundary.') for name in setup['specs']['scenario_inputs']['source_bindings'])}
    problems = negative_problems(negative['expected'], evidence)
    result = {'case_id': negative['case_id'], 'seed': seed, 'negative_contract': negative, 'setup': setup,
              'chain': chain, 'operation': operation, 'old_run_reuse': old_run_reuse, 'current_state': state, 'validation': validation,
              'evidence': evidence, 'history_before': before, 'history_after': shared.history_hashes(task_root),
              'problems': problems, 'status': 'failed' if problems else 'passed'}
    shared.write_new(cli.directory / 'negative-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--foundry', type=Path, required=True)
    parser.add_argument('--candidate-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, default=shared.DEFAULT_FIXTURES)
    parser.add_argument('--cases', nargs='+', help='Optional exact case IDs, positives or frozen negatives')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    suite = shared.load_suite(args.fixtures)
    identity = shared.original_driver().candidate_identity(args.foundry, args.candidate_manifest)
    dependencies = {str(p.relative_to(ROOT)): shared.file_hash(p) for p in (
        Path(__file__), ROOT / 'tools/finance_supplement_cases.py', ROOT / 'tools/finance_supplement_eval.py',
        ROOT / 'tools/finance_professional_eval.py', ROOT / 'tools/verify_finance_evals.py',
        ROOT / 'tools/verify_finance_mutation_pipeline.py')}
    shared.write_new(args.output / 'identity-before.json', {'candidate': identity, 'dependencies': dependencies,
                      'suite_manifest_sha256': suite['manifest_sha256']})
    cases = {c['case_id']: c for c in suite['cases']}
    negatives = {c['case_id']: c for c in suite['contract']['negative_cases']}
    selected = args.cases or [*cases, *negatives]
    if len(selected) != len(set(selected)) or set(selected) - set(cases) - set(negatives):
        raise ValueError('unknown or duplicate selected case')
    results = []
    for case_id in selected:
        directory = args.output / case_id
        directory.mkdir()
        cli = shared.new_cli(args.foundry, directory)
        started = time.monotonic()
        try:
            if case_id in cases:
                case = cases[case_id]
                public = shared.case_public(case)
                seed = seed_public(cli, public)
                result = completed_control(cli, case, suite['contract'], public, seed)
                problems = result['problems']
            else:
                negative = negatives[case_id]
                result = execute_negative(cli, cases[negative['base_case_id']], suite['contract'], negative)
                problems = result['problems']
            entry = {'case_id': case_id, 'status': 'failed' if problems else 'passed', 'problems': problems}
        except Exception as exc:
            entry = {'case_id': case_id, 'status': 'failed', 'problems': ['controller_or_product_error:' + str(exc)],
                     'error_type': type(exc).__name__}
            shared.write_new(directory / 'failure.json', entry)
        entry.update(task_id=cli.task, duration_ms=round((time.monotonic() - started) * 1000), raw_cli_calls=len(cli.calls))
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    after = shared.original_driver().candidate_identity(args.foundry, args.candidate_manifest)
    errors = []
    if after != identity or shared.load_suite(args.fixtures)['manifest_sha256'] != suite['manifest_sha256']:
        errors.append('candidate_or_frozen_suite_changed')
    if any(shared.file_hash(ROOT / p) != value for p, value in dependencies.items()):
        errors.append('controller_dependency_changed')
    if len({r['task_id'] for r in results}) != len(results) or any(not r['task_id'] for r in results):
        errors.append('case_tasks_not_independent')
    summary = {'status': 'passed' if not errors and all(r['status'] == 'passed' for r in results) else 'failed',
               'scope': 'native_engineering_supplement_not_provider_or_business_acceptance', 'provider_calls': 0,
               'original_slots_credit': 0, 'original_release_accepted': False, 'human_signoff': False,
               'selected_subset': len(selected) != 11, 'planned_cases': len(selected), 'cases': results,
               'passed': sum(r['status'] == 'passed' for r in results), 'identity_errors': errors,
               'candidate_manifest_sha256': identity['manifest_sha256'], 'suite_manifest_sha256': suite['manifest_sha256']}
    shared.write_new(args.output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
