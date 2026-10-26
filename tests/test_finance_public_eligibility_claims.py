"""Qualification prose cannot promote source inputs through verified outputs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from foundry.finance_claim_semantics import (CLAIM_SEMANTICS_VERSION, check_claim_semantics,
                                            qualification_claim_report)
from foundry.finance_delivery_verification import verify_public_text
from foundry.finance_driver_templates import OUTPUT_SEMANTICS
from foundry.finance_explanations import saved_claim_semantic_issues
from foundry.finance_service import FinanceStore
from test_finance_performance_semantics import performance_case

CODE = 'fact_qualification_claim_mismatch'
CLAIM = ('The `prepare_explanation` returned a `save_template_spec` (short save path) plus a '
         '`draft_template` with the eligible 13-metric table, 12 model-checks summary, and '
         '16 source-bound inputs — all `model_verified`. I\'ll save using the short prepared-template '
         'spec, adding only a brief qualitative note for the old-receivable vs current-fulfilment '
         'distinction and forecast scope.')
ROOT = Path(__file__).resolve().parents[1]


def file_hashes(task):
    return {str(p.relative_to(task.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in task.root.rglob('*') if p.is_file()}


def catalog(prepared):
    return list({f['id']: f for f in [*prepared['facts'], *prepared['input_facts']]}.values())


@pytest.fixture(scope='module')
def native_qualification(tmp_path_factory):
    path = tmp_path_factory.mktemp('native-qualification')
    manager, context, requirement, initial = performance_case(path)
    session_id = 'public-qualification-native'
    session = manager.task.record_session(session_id, role='analysis')
    service = FinanceStore(manager.task, snapshot_ids=session['snapshot_ids'], session_id=session_id,
                           context_revision=session['context_revision'])
    run = service.run_scenario({'scenario_id': initial['result']['scenario_id']})
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    assert {f['metric_identity']['metric_key'] for f in prepared['facts']} == set(OUTPUT_SEMANTICS)
    assert all(f['evidence_eligibility']['status'] == 'model_verified'
               and f['evidence_eligibility']['counts_as_amount_evidence'] is True for f in prepared['facts'])
    assert prepared['input_facts'] and all(f['evidence_eligibility']['status'] == 'unverified'
               and f['evidence_eligibility']['counts_as_amount_evidence'] is False for f in prepared['input_facts'])
    spec = {'request_key': session_id + ':message:user:seq:1', 'nonce': 'qualification-red',
            'text': CLAIM, 'capture': {'session_id': session_id, 'tool_name': 'prepare_explanation',
                'call_id': 'actual-prepared-capture', 'task_id': service.task.id, 'run_id': run['id'],
                'requirements_id': requirement['id'], 'output_hash': run['output_hash'],
                'template_id': run['result']['template_id'], 'scenario_id': run['result']['scenario_id'],
                'context_revision': None}}
    return service, context, run, prepared, spec


@pytest.mark.parametrize('body', [
    CLAIM,
    'All `input_facts` are `model_verified`.',
    'All source-bound inputs have evidence_eligibility.status=model_verified.',
    '来源绑定输入的 evidence_eligibility.status 全部为 model_verified。',
    'All input_facts have counts_as_amount_evidence=true.',
    '输入事实均具备金额证据资格。',
    'Do not call output facts unverified, input_facts are model_verified.',
    'Outputs and input_facts are all model_verified.',
    'Input_facts have source_binding_status=source_verified and evidence_eligibility.status=model_verified.',
])
def test_explicit_input_qualification_and_mixed_all_do_not_borrow_output_status(native_qualification, body):
    _, _, run, prepared, _ = native_qualification
    issues = check_claim_semantics(body, [], qualification_facts=catalog(prepared), runs=[run])
    assert any(i['code'] == CODE for i in issues), issues


@pytest.mark.parametrize('body', [
    'All output facts are model_verified.',
    'All required_metrics have evidence_eligibility.status=model_verified.',
    'Outputs are model_verified, input_facts are unverified.',
    'Input_facts have source_binding_status=source_verified and evidence_eligibility.status=unverified.',
    'The outputs are model_verified; input_facts have evidence_eligibility.status=unverified.',
    'All 16 source-bound inputs are source-verified in source_binding_status.',
    '全部来源输入的 source_binding_status=source_verified；不等于金额证据资格。',
    'Source-bound inputs are traceable to archived rows.',
    '来源输入可追溯，counts_as_amount_evidence=false。',
    'Do not say all input_facts are model_verified.',
    'All input_facts are model_verified, this statement is incorrect.',
    'All input_facts are model_verified?',
    'If all input_facts are model_verified, discuss their scope.',
    '```json\n{"input_facts":{"evidence_eligibility":{"status":"model_verified"}}}\n```',
    '字段代码示例：`input_facts.evidence_eligibility.status = "model_verified"`。',
    'Other run FOREIGN-RUN input_facts have evidence_eligibility.status=model_verified.',
])
def test_binding_output_only_and_nonassertion_controls_stay_exact(native_qualification, body):
    service, _, run, prepared, spec = native_qualification
    assert not [i for i in check_claim_semantics(body, [], qualification_facts=catalog(prepared), runs=[run]) if i['code'] == CODE]
    proof = verify_public_text(service, {**spec, 'text': body})
    # An explicit foreign-run sentence receives no contradictory native proof.
    assert not [i for i in proof['issues'] if i['code'] == CODE]
    if 'FOREIGN-RUN' not in body:
        assert proof['delivered_text'] == body
    else:
        assert proof['status'] == 'unverifiable' and proof['bindings'] is None
        assert proof['delivered_text'] != body


@pytest.mark.parametrize('field,value', [('status', None), ('status', 'unknown'),
                                          ('counts_as_amount_evidence', 'true'), ('status', {}), ('status', []),
                                          ('counts_as_amount_evidence', None)])
def test_unknown_metadata_does_not_prove_the_opposite_qualification(native_qualification, field, value):
    _, _, run, prepared, _ = native_qualification
    facts = deepcopy(catalog(prepared))
    for fact in facts:
        fact['evidence_eligibility'][field] = value
    text = ('All input_facts have evidence_eligibility.status=unverified.' if field == 'status'
            else 'All input_facts have counts_as_amount_evidence=false.')
    assert not [i for i in check_claim_semantics(text, [], qualification_facts=facts, runs=[run]) if i['code'] == CODE]


def test_unknown_writing_row_is_not_a_registered_output(native_qualification):
    from foundry.analysis import _hash
    from foundry.finance_explanation_views import explanation_fact_view
    _, _, original, prepared, _ = native_qualification
    run = deepcopy(original)
    row = {'metric_key': 'unregistered_other_metric', 'value': '999', 'unit': '元'}
    run['result']['rows'].append(row)
    run['output_hash'] = _hash(run['result'])
    from foundry.finance_explanations import _facts_for_run
    facts = _facts_for_run(run, {'absolute': '0'}, analysis=native_qualification[0].analysis)
    unknown = facts[-1]
    assert unknown['row'] == len(run['result']['rows']) - 1
    assert unknown['source_trace']['output_hash'] == run['output_hash']
    assert unknown['evidence_eligibility']['status'] == 'unverified'
    assert unknown['evidence_eligibility']['counts_as_amount_evidence'] is False
    view = explanation_fact_view({'facts': facts}, [run])
    assert unknown in view['facts']  # Valid writing membership still is not output identity.
    report = qualification_claim_report('All output facts are model_verified.', facts=facts, runs=[run])
    assert not report['issues'] and not report['unverifiable_positions'], report
    reverse = qualification_claim_report('All output facts are unverified.', facts=facts, runs=[run])
    assert reverse['issues'] and unknown['id'] not in reverse['issues'][0]['fact_ids']


def test_actual_native_cli_projects_archived_mixed_claim_without_writing(native_qualification, tmp_path):
    service, _, run, prepared, spec = native_qualification
    raw = '普通进度🙂。\r\n' + CLAIM + '\r\n继续按原顺序保存。'
    path = tmp_path / 'native-proof.json'
    path.write_text(json.dumps({**spec, 'text': raw}, ensure_ascii=False))
    before = file_hashes(service.task)
    observed = subprocess.run([sys.executable, '-B', '-m', 'foundry.cli', '--var',
        str(service.task.root.parent.parent), '--task', service.task.id, '--session', service.session_id,
        'finance-public-text-verify', '--spec-file', str(path)], cwd=ROOT,
        text=True, capture_output=True, timeout=30)
    assert observed.returncode == 0, observed.stderr
    proof = json.loads(observed.stdout)
    (tmp_path / 'actual-native-cli-qualification.json').write_text(json.dumps({
        'proof': proof, 'raw': raw, 'input_metadata': [f['evidence_eligibility'] for f in prepared['input_facts']],
        'output_metadata': [f['evidence_eligibility'] for f in prepared['facts']],
        'task_unchanged': before == file_hashes(service.task), 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert file_hashes(service.task) == before
    assert proof['verified'] is True and proof['status'] == 'contradicted', proof
    assert any(i['code'] == CODE for i in proof['issues'])
    assert proof['bindings']['run_id'] == run['id']
    assert proof['bindings']['claim_semantics_version'] == CLAIM_SEMANTICS_VERSION
    assert proof['delivered_text'].startswith('普通进度🙂。\r\n')
    assert proof['delivered_text'].endswith('\r\n继续按原顺序保存。')
    assert CLAIM not in proof['delivered_text']


@pytest.mark.parametrize('short', [False, True])
def test_save_qualification_uses_full_catalog_separate_from_cited_facts(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    body = 'All input_facts have evidence_eligibility.status=model_verified.'
    spec = ({**prepared['save_template_spec'], 'qualitative_note': body} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + body})
    saved = service.save_explanation_draft(spec)
    input_ids = {f['id'] for f in prepared['input_facts']}
    assert not input_ids.intersection(saved['fact_ids'])
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    (tmp_path / 'actual-qualification-save.json').write_text(json.dumps({
        'short': short, 'body': body, 'draft_id': saved['id'], 'run_id': run['id'],
        'quality': saved['quality'], 'completion': saved['completion'], 'target_issues': issues,
        'input_fact_ids': sorted(input_ids), 'cited_fact_ids': saved['fact_ids'], 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert issues, saved['quality']
    assert saved['completion']['status'] != 'complete'
    original = deepcopy(service.analysis.get_draft(saved['id']))
    run_before = deepcopy(service.analysis.get_run(run['id']))
    good = ('Output facts are model_verified; input_facts have evidence_eligibility.status=unverified '
            'and counts_as_amount_evidence=false. Source-bound inputs remain traceable.')
    repair_spec = ({**prepared['save_template_spec'], 'qualitative_note': good} if short else
                   {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + good})
    repaired = service.save_explanation_draft({**repair_spec, 'parent_id': saved['id']})
    assert repaired['parent_id'] == saved['id']
    assert repaired['quality']['status'] == 'pass' and repaired['completion']['status'] == 'complete', repaired
    assert service.analysis.completion_in_view(repaired['completion'], None)['status'] == 'complete'
    assert service.analysis.get_draft(saved['id']) == original
    assert service.analysis.get_run(run['id']) == run_before
    assert any(i['code'] == CODE for i in saved_claim_semantic_issues(service.analysis, original))
    legacy = {**deepcopy(original), 'explanation_check': {**original['explanation_check'],
              'claim_semantics_version': CLAIM_SEMANTICS_VERSION - 1}}
    snapshot = deepcopy(legacy)
    before = file_hashes(service.task)
    assert any(i['code'] == CODE for i in saved_claim_semantic_issues(service.analysis, legacy))
    assert legacy == snapshot and file_hashes(service.task) == before
    (tmp_path / 'actual-qualification-revision.json').write_text(json.dumps({
        'short': short, 'failed_id': saved['id'], 'failed_quality': saved['quality'],
        'fixed_id': repaired['id'], 'parent_id': repaired['parent_id'], 'fixed_quality': repaired['quality'],
        'completion': repaired['completion'], 'final_response': repaired['final_response'],
        'old_and_current_readonly_recheck': True, 'old_body_claims_run_verdict_unchanged': True,
        'provider_calls': 0,
    }, ensure_ascii=False, indent=2))


def test_current_epoch_readonly_recheck_uses_input_catalog_without_rewriting(tmp_path):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    saved = service.save_explanation_draft({**prepared['save_template_spec'],
        'qualitative_note': 'All input_facts are model_verified.'})
    original = deepcopy(service.analysis.get_draft(saved['id']))
    assert original['explanation_check']['claim_semantics_version'] == CLAIM_SEMANTICS_VERSION
    before = file_hashes(service.task)
    issues = saved_claim_semantic_issues(service.analysis, original)
    (tmp_path / 'actual-current-epoch-qualification-recheck.json').write_text(json.dumps({
        'draft_id': original['id'], 'original_quality': original['quality'], 'issues': issues,
        'claim_semantics_version': CLAIM_SEMANTICS_VERSION, 'task_unchanged': before == file_hashes(service.task),
        'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert original == service.analysis.get_draft(saved['id']) and before == file_hashes(service.task)
    assert any(i['code'] == CODE for i in issues), issues


@pytest.mark.parametrize('body', [
    'Other run FOREIGN-RUN input_facts are model_verified.',
    'Run UNKNOWN-RUN output facts are unverified.',
])
def test_foreign_qualification_has_no_borrowed_current_authority(native_qualification, body):
    service, _, run, prepared, spec = native_qualification
    report = qualification_claim_report(body, facts=catalog(prepared), runs=[run])
    assert not report['issues'] and report['unverifiable_positions']
    proof = verify_public_text(service, {**spec, 'text': body})
    assert proof['status'] == 'unverifiable' and proof['bindings'] is None and proof['issues'] == []
    assert proof['delivered_text'] != body


@pytest.mark.parametrize('scope', ['period', 'scenario_id', 'unknown_subject'])
def test_explicit_scope_fields_cannot_borrow_current_qualification(native_qualification, scope):
    service, _, run, prepared, spec = native_qualification
    facts = catalog(prepared)
    if scope == 'unknown_subject':
        foreign = 'Unknown source input_facts are model_verified.'
        valid = 'Current run input_facts are model_verified.'
    else:
        actual = prepared['input_facts'][0]['metric_identity'][scope]
        other = '1900-01' if scope == 'period' else 'FOREIGN-SCENARIO'
        foreign = f'{scope}={other} input_facts are model_verified.'
        valid = f'{scope}={actual} input_facts are model_verified.'
        correct = f'{scope}={actual} input_facts are unverified.'
        assert not qualification_claim_report(correct, facts=facts, runs=[run])['issues']
        assert verify_public_text(service, {**spec, 'text': correct})['delivered_text'] == correct
    report = qualification_claim_report(foreign, facts=facts, runs=[run])
    assert not report['issues'] and report['unverifiable_positions']
    proof = verify_public_text(service, {**spec, 'text': foreign})
    assert proof['status'] == 'unverifiable' and proof['bindings'] is None and not proof['issues']
    assert proof['delivered_text'] != foreign
    assert qualification_claim_report(valid, facts=facts, runs=[run])['issues']


@pytest.mark.parametrize('body,expected', [
    ('来源绑定输入不具备金额证据资格。', 'unchanged'),
    ('来源绑定输入不具有金额证据资格。', 'unchanged'),
    ('来源绑定输入具备金额证据资格。', 'contradicted'),
    ('输出事实不具备金额证据资格。', 'contradicted'),
    ('输出事实具备金额证据资格。', 'unchanged'),
    ('不能声称输出事实不具备金额证据资格。', 'unchanged'),
    ('如果输出事实不具备金额证据资格，应继续核对。', 'unchanged'),
    ('字段代码示例：`输入事实不具备金额证据资格`。', 'unchanged'),
])
def test_literal_negative_amount_qualification_is_a_strict_boolean_assertion(native_qualification, body, expected):
    service, _, run, prepared, spec = native_qualification
    report = qualification_claim_report(body, facts=catalog(prepared), runs=[run])
    assert bool(report['issues']) is (expected == 'contradicted'), report
    proof = verify_public_text(service, {**spec, 'text': body})
    assert proof['status'] == expected, proof
    if expected == 'unchanged':
        assert proof['delivered_text'] == body
    elif '不具备' in body:
        assert report['issues'][0]['claimed_value'] is False


@pytest.mark.parametrize('field', ['run_id', 'period', 'scenario_id'])
@pytest.mark.parametrize('postposed', [False, True])
def test_postposed_scope_binds_existing_explicit_identity_fields(native_qualification, field, postposed):
    service, _, run, prepared, spec = native_qualification
    actual = run['id'] if field == 'run_id' else prepared['input_facts'][0]['metric_identity'][field]
    foreign = '1900-01' if field == 'period' else 'FOREIGN-' + field.upper()
    for value, expected, status in [(foreign, 'unverifiable', 'model_verified'),
                                    (actual, 'contradicted', 'model_verified'),
                                    (actual, 'unchanged', 'unverified')]:
        body = (f'Input_facts are {status} for {field}={value}.' if postposed else
                f'{field}={value} input_facts are {status}.')
        report = qualification_claim_report(body, facts=catalog(prepared), runs=[run])
        proof = verify_public_text(service, {**spec, 'text': body})
        assert proof['status'] == expected, (body, proof)
        if expected == 'unverifiable':
            assert proof['bindings'] is None and proof['issues'] == [] and report['unverifiable_positions']
        elif expected == 'unchanged':
            assert proof['delivered_text'] == body
        else:
            assert report['issues'] and proof['bindings']['run_id'] == run['id']


R2_WORDING = [
    ('来源绑定输入不具备金额证据资格。', 'unchanged'),
    ('Input_facts are model_verified for period=1900-01.', 'unverifiable'),
    ('Input_facts are model_verified for scenario_id=FOREIGN-SCENARIO.', 'unverifiable'),
    ('Input_facts are model_verified for run_id=FOREIGN-RUN.', 'unverifiable'),
]


@pytest.mark.parametrize('body,expected', R2_WORDING)
def test_actual_native_cli_literal_negative_and_postposed_scope(native_qualification, tmp_path, body, expected):
    service, _, _, _, spec = native_qualification
    raw = '普通进度🙂。\r\n' + body + '\r\n继续保存。'
    path = tmp_path / 'r2-native-proof.json'
    path.write_text(json.dumps({**spec, 'text': raw}, ensure_ascii=False))
    before = file_hashes(service.task)
    observed = subprocess.run([sys.executable, '-B', '-m', 'foundry.cli', '--var',
        str(service.task.root.parent.parent), '--task', service.task.id, '--session', service.session_id,
        'finance-public-text-verify', '--spec-file', str(path)], cwd=ROOT,
        text=True, capture_output=True, timeout=30)
    assert observed.returncode == 0, observed.stderr
    proof = json.loads(observed.stdout)
    (tmp_path / 'r2-actual-native-cli.json').write_text(json.dumps({'body': body, 'expected': expected,
        'proof': proof, 'task_unchanged': file_hashes(service.task) == before, 'provider_calls': 0},
        ensure_ascii=False, indent=2))
    assert before == file_hashes(service.task)
    assert proof['status'] == expected, proof
    assert proof['delivered_text'].startswith('普通进度🙂。\r\n')
    assert proof['delivered_text'].endswith('\r\n继续保存。')
    if expected == 'unchanged':
        assert proof['delivered_text'] == raw
    else:
        assert proof['bindings'] is None and proof['issues'] == []


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('body,expected', R2_WORDING)
def test_actual_save_literal_negative_and_postposed_scope(tmp_path, short, body, expected):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    wrong = service.save_explanation_draft({**prepared['save_template_spec'],
        'qualitative_note': 'Input_facts are model_verified.'})
    original = deepcopy(service.analysis.get_draft(wrong['id']))
    run_before = deepcopy(service.analysis.get_run(run['id']))
    spec = ({**prepared['save_template_spec'], 'qualitative_note': body} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + body})
    saved = service.save_explanation_draft({**spec, 'parent_id': wrong['id']})
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    (tmp_path / 'r2-actual-save.json').write_text(json.dumps({'short': short, 'body': body,
        'expected': expected, 'quality': saved['quality'], 'completion': saved['completion'],
        'failed_id': wrong['id'], 'repaired_id': saved['id'], 'parent_id': saved['parent_id'],
        'target_issues': issues, 'provider_calls': 0}, ensure_ascii=False, indent=2))
    assert not issues, issues
    if expected == 'unchanged':
        assert saved['quality']['status'] == 'pass' and saved['completion']['status'] == 'complete', saved
        assert service.analysis.completion_in_view(saved['completion'], None)['status'] == 'complete'
    assert service.analysis.get_draft(wrong['id']) == original
    assert service.analysis.get_run(run['id']) == run_before
    before = file_hashes(service.task)
    current = service.analysis.get_draft(saved['id'])
    legacy = {**deepcopy(current), 'explanation_check': {**current['explanation_check'],
              'claim_semantics_version': CLAIM_SEMANTICS_VERSION - 1}}
    snapshot = deepcopy(legacy)
    assert not [i for i in saved_claim_semantic_issues(service.analysis, current) if i['code'] == CODE]
    assert not [i for i in saved_claim_semantic_issues(service.analysis, legacy) if i['code'] == CODE]
    assert legacy == snapshot and before == file_hashes(service.task)


@pytest.mark.parametrize('field', ['run_id', 'period', 'scenario_id'])
def test_local_identity_does_not_transfer_across_next_independent_subject(native_qualification, field):
    _, _, run, prepared, _ = native_qualification
    facts = catalog(prepared)
    foreign = '1900-01' if field == 'period' else 'FOREIGN-' + field.upper()
    # A preposed qualifier for the second subject must leave the first alone.
    first_wrong = f'Input_facts are model_verified, {field}={foreign} output facts are unverified.'
    report = qualification_claim_report(first_wrong, facts=facts, runs=[run])
    assert len(report['issues']) == 1 and report['unverifiable_positions']
    assert set(report['issues'][0]['fact_ids']) == {fact['id'] for fact in prepared['input_facts']}
    # A postposed qualifier before that comma belongs only to the first subject.
    second_wrong = f'Input_facts are model_verified for {field}={foreign}, output facts are unverified.'
    report = qualification_claim_report(second_wrong, facts=facts, runs=[run])
    assert len(report['issues']) == 1 and report['unverifiable_positions']
    assert set(report['issues'][0]['fact_ids']) == {fact['id'] for fact in prepared['facts']}
    assert not qualification_claim_report(
        'Output facts are model_verified, input_facts are unverified.', facts=facts, runs=[run])['issues']
    assert qualification_claim_report(
        'Output facts and input_facts are all model_verified.', facts=facts, runs=[run])['issues']


@pytest.mark.parametrize('kind', ['input_facts', 'output facts'])
@pytest.mark.parametrize('value', [None, 'false', [], {}])
def test_literal_negative_does_not_invert_unknown_typed_metadata(native_qualification, kind, value):
    _, _, run, prepared, _ = native_qualification
    facts = deepcopy(catalog(prepared))
    for fact in facts:
        fact['evidence_eligibility']['counts_as_amount_evidence'] = value
    label = '输入事实' if kind == 'input_facts' else '输出事实'
    report = qualification_claim_report(label + '不具备金额证据资格。', facts=facts, runs=[run])
    assert not report['issues'] and report['unverifiable_positions']


@pytest.mark.parametrize('field', ['run_id', 'period', 'scenario_id'])
def test_postposed_scope_unknown_and_mixed_ids_are_unverifiable(native_qualification, field):
    service, _, run, prepared, spec = native_qualification
    current = run['id'] if field == 'run_id' else prepared['input_facts'][0]['metric_identity'][field]
    foreign = '1900-01' if field == 'period' else 'FOREIGN-' + field.upper()
    for suffix in [f'{field}=[]', f'{field}={current} and {field}={foreign}']:
        body = 'Input_facts are model_verified for ' + suffix + '.'
        report = qualification_claim_report(body, facts=catalog(prepared), runs=[run])
        assert not report['issues'] and report['unverifiable_positions']
        proof = verify_public_text(service, {**spec, 'text': body})
        assert proof['status'] == 'unverifiable' and proof['bindings'] is None and proof['issues'] == []
