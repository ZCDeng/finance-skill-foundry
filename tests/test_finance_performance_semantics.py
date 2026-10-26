"""Forecast performance status is an archived source assumption, not actual fulfilment proof."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS, TEMPLATE_METRICS
from foundry.finance_driver_templates import BOUNDARY_INPUTS, TEMPLATE_ID
from test_finance_professional_protocol import _profile_case

FIXTURE = Path(__file__).parent / 'fixtures/finance_supplements/three_statement_v1/public/SUP-E19-02--fulfilled-cash-sale'
BAD = '当期履约收款分属当期待履约服务合同与当月全额履约并现金收款的新增服务，均不冲减期初旧应收。'
CODE = 'forecast_performance_status_mismatch'


def performance_case(tmp_path, mutate=None, *, period='2026-10', renamed=False):
    service, seed = _profile_case(tmp_path)
    record = json.loads((FIXTURE / 'transaction_allocation.json').read_text())
    scope = deepcopy(record['scope'])
    if renamed:
        record['base_current_service']['contract_id'] = 'CLIENT-RENAMED-42'
        record['additional_sale']['contract_id'] = 'CASH-RENAMED-81'
    for name in ('base_current_service', 'additional_sale'):
        record[name]['performance_period'] = period
    if mutate:
        mutate(record)
    bindings, source_bindings = {}, {}
    for alias, key in [('template_inputs', 'input_name'), ('model_boundary', 'boundary_name')]:
        rows = json.loads((FIXTURE / f'{alias}.json').read_text())['rows']
        if renamed:
            rows.reverse()
        prior = f'{period[:5]}{int(period[5:]) - 1:02}'
        for row in rows:
            row['period'] = prior if row[key].startswith('opening_') else period
        path = tmp_path / f'{alias}.json'
        path.write_text(json.dumps(rows))
        bindings[alias] = service.analysis.add_dataset(path, name=alias)['id']
        for row in rows:
            name = row[key] if alias == 'template_inputs' else f'boundary.{row[key]}'
            source_bindings[name] = {'alias': alias, 'column': 'amount', 'selector': {key: row[key]},
                'aggregation': 'single', 'period': row['period'], 'scope': {'organization': row['organization']},
                'unit': row['unit'], 'currency': row['currency']}
    alias = 'independently_named_record' if renamed else 'transaction_allocation'
    path = tmp_path / 'allocation.json'
    path.write_text(json.dumps([{'record_type': 'transaction_allocation', 'public_record_json': json.dumps(record)}]))
    bindings[alias] = service.analysis.add_dataset(path, name='independent source')['id']
    context = service.save_context({'bindings': bindings, 'scopes': {k: scope for k in bindings},
        'reporting_profile': {**seed['reporting_profile'], 'entity_scope': scope['organization']}})
    service.finance_profile_confirm({'context_id': context['id'], 'confirmed_fields': sorted(BASE_FIELDS | STANDARD_FIELDS)})
    scenario = service.save_scenario({'context_id': context['id'], 'kind': 'driver_model', 'label': 'independent forecast',
        'inputs': {'template_id': TEMPLATE_ID, 'period': period, 'scope': scope, 'source_bindings': source_bindings}})
    service.finance_profile_confirm({'context_id': context['id'], 'scenario_id': scenario['id'],
        'confirmed_model_boundaries': list(BOUNDARY_INPUTS)})
    requirement = service.analysis_requirements_save({'context_id': context['id'], 'question': '管理预测三表',
        'items': [{'id': key, 'metric': key, 'dimensions': {'template_id': TEMPLATE_ID, 'scenario_id': scenario['id']},
                   'requires_drilldown': False} for key in sorted(TEMPLATE_METRICS)]})
    run = service.run_scenario({'scenario_id': scenario['id']})
    assert run['execution_status'] == 'succeeded'
    return service, context, requirement, run


@pytest.mark.parametrize('renamed,period', [(False, '2026-10'), (True, '2026-11')])
@pytest.mark.parametrize('short', [False, True])
def test_actual_wrong_note_is_blocked_in_both_saves(tmp_path, short, renamed, period):
    service, _, _, run = performance_case(tmp_path, period=period, renamed=renamed)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    spec = ({**prepared['save_template_spec'], 'qualitative_note': BAD} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + BAD})
    saved = service.save_explanation_draft(spec)
    assert any(i['code'] == CODE for i in saved['quality']['issues']), saved['quality']
    assert saved['completion']['status'] != 'complete'


@pytest.fixture(scope='module')
def proved(tmp_path_factory):
    from foundry.finance_explanations import _forecast_performance_sources
    service, _, _, run = performance_case(tmp_path_factory.mktemp('performance-proof'))
    proof = _forecast_performance_sources(service.analysis, [run])
    assert proof['status'] == 'verified'
    return service, run, proof


@pytest.mark.parametrize('body', [
    BAD, 'S-CUR-01 在本预测期仍待履约。', 'S-NEW-CASH-01 在本预测月尚未履约。',
    '若干资料均表明 S-CUR-01 尚待履约。',
    '并非所有客户都会赊销；S-CUR-01 在本期仍待履约。',
    '“S-CUR-01 待履约”这句话不对；但本期 S-CUR-01 确实仍待履约。',
    'S-CUR-01 is pending performance.', 'S-CUR-01 has not been performed.',
    'S-CUR-01 has not yet been performed.', 'S-CUR-01 is not yet performed.',
])
def test_bounded_contradictions(proved, body):
    from foundry.finance_claim_semantics import forecast_performance_issues
    _, run, proof = proved
    issues = forecast_performance_issues(body, performance_facts=proof['facts'])
    assert len(issues) == 1
    issue = issues[0]
    assert issue['run_id'] == run['id'] and issue['output_hash'] == run['output_hash']
    assert body[issue['position']:].startswith(issue['text'])
    assert issue['source_facts'][0]['source']['json_pointer'].endswith('/performed_in_forecast')


@pytest.mark.parametrize('body', [
    'S-CUR-01 在本预测期已履约，收款按合同归属追踪。',
    'S-NEW-CASH-01 在本预测月已履约并当月收款。',
    '本预测假设将 S-CUR-01 设为已履约，不证明现实中已经履约。',
    '不能把 S-CUR-01 称为待履约服务。',
    '“S-CUR-01 尚未履约”这一说法并不成立。',
    'S-CUR-01 is pending performance, this statement is incorrect.',
    'We cannot claim S-CUR-01 has not yet been performed.',
    'S-CUR-01 is not yet performed, this statement is incorrect.',
    'S-CUR-01 underperformed the sales budget.',
    'S-CUR-01 uses the field performed_in_forecast.',
    'S-CUR-01 uses the field unperformed_records.',
    'S-CUR-01 并非尚未履约，而是本预测期已履约。',
    'S-CUR-01 是否仍待履约？', '若 S-CUR-01 尚未履约，则需另核收入确认。',
    '待履约合同的收入确认一般需要核对履约义务。',
    'OTHER-CONTRACT 在本期尚未履约。', '该服务仍待履约。',
    'S-CUR-01 于2026-11尚待履约。',
    '收款用于清偿已识别旧债权，本期收入依据本预测履约设定。',
])
def test_correct_denial_question_unknown_object_and_other_period_preserved(proved, body):
    from foundry.finance_claim_semantics import forecast_performance_issues
    _, _, proof = proved
    assert forecast_performance_issues(body, performance_facts=proof['facts']) == []


@pytest.mark.parametrize('state', [None, 'true', 'false', 0, 1, 'partial'])
def test_strict_bool_not_truthiness(tmp_path, state):
    from foundry.finance_explanations import _forecast_performance_sources
    service, _, _, run = performance_case(tmp_path, lambda r: r['base_current_service'].update(performed_in_forecast=state))
    proof = _forecast_performance_sources(service.analysis, [run])
    fact = next(f for f in proof['facts'] if f['role'] == 'base_current_service')
    assert fact['status'] == 'unverifiable' and fact['state'] == 'unknown'


@pytest.mark.parametrize('mutation', ['missing', 'period', 'partial', 'scope', 'schema'])
def test_unsupported_or_different_source_not_inferred(tmp_path, mutation):
    from foundry.finance_explanations import _forecast_performance_sources
    from foundry.finance_claim_semantics import forecast_performance_issues
    def mutate(record):
        item = record['base_current_service']
        if mutation == 'missing':
            item.pop('performed_in_forecast')
        elif mutation == 'period':
            item['performance_period'] = '2026-11'
        elif mutation == 'partial':
            item['performance_extent'] = 'partial'
        elif mutation == 'scope':
            record['scope'] = {**record['scope'], 'organization': 'another organization'}
        else:
            record['schema_version'] = 'unregistered'
    service, _, _, run = performance_case(tmp_path, mutate)
    proof = _forecast_performance_sources(service.analysis, [run])
    assert not any(f['status'] == 'verified' and f['role'] == 'base_current_service' for f in proof['facts'])
    assert forecast_performance_issues('S-CUR-01 在本期尚待履约。', performance_facts=proof['facts']) == []


def test_false_is_explicit_forecast_pending_even_without_revenue(tmp_path):
    from foundry.finance_explanations import _forecast_performance_sources
    from foundry.finance_claim_semantics import forecast_performance_issues
    def mutate(record):
        record['base_current_service']['performed_in_forecast'] = False
        record['base_current_service'].pop('revenue')
    service, _, _, run = performance_case(tmp_path, mutate)
    proof = _forecast_performance_sources(service.analysis, [run])
    base = next(f for f in proof['facts'] if f['role'] == 'base_current_service')
    assert base['status'] == 'verified' and base['state'] == 'pending'
    assert forecast_performance_issues('S-CUR-01 尚待履约。', performance_facts=proof['facts']) == []
    assert forecast_performance_issues('S-CUR-01 已履约。', performance_facts=proof['facts'])
    assert forecast_performance_issues('该服务尚待履约。', performance_facts=proof['facts']) == []
    assert forecast_performance_issues('本期所有服务合同都已履约。', performance_facts=proof['facts'])
    assert forecast_performance_issues('本期所有服务合同都尚待履约。', performance_facts=proof['facts'])


@pytest.mark.parametrize('mutation', ['allowed', 'hash', 'data_hash', 'new_requirement', 'hidden_requirement',
                                      'superseded', 'revoked', 'epoch', 'failed', 'multiple'])
def test_current_source_authority_is_required(tmp_path, mutation):
    from foundry.finance_explanations import _forecast_performance_sources
    service, context, requirement, run = performance_case(tmp_path)
    allowed = None
    runs = [run]
    if mutation == 'allowed':
        allowed = set(context['bindings'].values()) - {context['bindings']['transaction_allocation']}
    elif mutation == 'hash':
        source = service.analysis.root / 'datasets' / context['bindings']['transaction_allocation'] / 'source.json'
        source.write_text(source.read_text() + ' ')
    elif mutation == 'data_hash':
        data = service.analysis.root / 'datasets' / context['bindings']['transaction_allocation'] / 'data.json'
        data.write_text(data.read_text() + ' ')
    elif mutation == 'new_requirement':
        service.analysis_requirements_save({'context_id': context['id'], 'question': 'new version',
            'items': deepcopy(requirement['items']), 'parent_id': requirement['id']})
    elif mutation == 'hidden_requirement':
        allowed = set(context['bindings'].values())
        path = tmp_path / 'hidden.json'
        path.write_text('[{"amount":"1"}]')
        hidden = service.analysis.add_dataset(path, name='hidden requirement source')
        service.analysis_requirements_save({'parent_id': requirement['id'], 'question': 'hidden current obligation',
            'bindings': {'hidden': hidden['id']}, 'change_reason': 'a new authorized source',
            'items': [{'id': 'current', 'metric': 'account_total', 'dimensions': {'account': 'cash'}}]})
    elif mutation == 'superseded':
        path = tmp_path / 'replacement.json'
        path.write_text('[{"amount":"1"}]')
        service.analysis.add_dataset(path, name='independent source')
    elif mutation == 'revoked':
        service.finance_profile_revoke({'id': service._list('profile_confirmations')[-1]['id'], 'reason': 'review needed'})
    elif mutation == 'epoch':
        service.finance_rule_epoch_advance({'rule_id': 'statements.linked_management', 'expected_epoch': 0,
                                           'reason': 'new professional review'})
    elif mutation == 'failed':
        # A requested unsuccessful run cannot lend another stored run's facts.
        runs = [{'id': '0' * 32, 'execution_status': 'failed'}]
    else:
        runs = [run, deepcopy(run)]
    proof = _forecast_performance_sources(service.analysis, runs, allowed=allowed)
    assert proof == {'status': 'unverifiable', 'facts': [], 'counts_as_amount_evidence': False}


def test_same_contract_conflict_is_unknown_not_reverse_proof(tmp_path):
    from foundry.finance_explanations import _forecast_performance_sources
    from foundry.finance_claim_semantics import forecast_performance_issues

    def mutate(record):
        record['additional_sale']['contract_id'] = record['base_current_service']['contract_id']
        record['additional_sale']['performed_in_forecast'] = False

    service, _, _, run = performance_case(tmp_path, mutate)
    proof = _forecast_performance_sources(service.analysis, [run])
    assert proof['status'] == 'unverifiable' and len(proof['facts']) == 2
    assert all(f['status'] == 'source_conflict' for f in proof['facts'])
    assert forecast_performance_issues('S-CUR-01 尚待履约。', performance_facts=proof['facts']) == []


def test_caller_run_metadata_cannot_supply_or_change_source_assumptions(proved):
    from foundry.finance_explanations import _forecast_performance_sources
    service, run, proof = proved
    spoof = {**deepcopy(run), 'result': {'performed_in_forecast': False}, 'forecast_performance': 'pending'}
    assert _forecast_performance_sources(service.analysis, [spoof]) == proof


def test_unreadable_source_is_rejected_before_content_read(proved, monkeypatch):
    from foundry.finance_explanations import _forecast_performance_sources
    service, run, _ = proved
    reads = []
    monkeypatch.setattr(service.analysis, 'read_dataset', lambda key: reads.append(key))
    proof = _forecast_performance_sources(service.analysis, [run], allowed=set())
    assert proof['facts'] == [] and proof['status'] == 'unverifiable'
    assert reads == []


def test_new_requirement_during_source_read_invalidates_proof(tmp_path, monkeypatch):
    from foundry.finance_explanations import _forecast_performance_sources
    service, context, requirement, run = performance_case(tmp_path)
    original = service.analysis.read_dataset
    triggered = False

    def changing(key):
        nonlocal triggered
        result = original(key)
        if not triggered:
            triggered = True
            service.analysis_requirements_save({'context_id': context['id'], 'parent_id': requirement['id'],
                'question': 'Changed while reading', 'items': deepcopy(requirement['items'])})
        return result

    monkeypatch.setattr(service.analysis, 'read_dataset', changing)
    proof = _forecast_performance_sources(service.analysis, [run])
    assert triggered and proof['status'] == 'unverifiable' and proof['facts'] == []


def test_source_proof_is_read_only_and_shared_authorization_is_sufficient(proved):
    from foundry.finance_explanations import _forecast_performance_sources
    service, run, proof = proved
    before = {str(p.relative_to(service.task.root)): p.read_bytes()
              for p in service.task.root.rglob('*') if p.is_file()}
    shared = _forecast_performance_sources(service.analysis, [run], allowed=set(run['bindings'].values()))
    assert shared == proof
    assert {str(p.relative_to(service.task.root)): p.read_bytes()
            for p in service.task.root.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('short', [False, True])
def test_real_cli_and_model_renderer_preserve_proof_and_local_diagnostics(tmp_path, capsys, short):
    from foundry.cli import main
    from test_finance_runtime_payload import ROOT, restore, restore_table

    service, _, _, run = performance_case(tmp_path)

    def cli_render(command, tool, spec):
        assert main(['--var', str(service.task.store.var_root), '--task', service.task.id,
                     command, '--spec', json.dumps(spec)]) == 0
        raw = capsys.readouterr().out
        original = json.loads(raw)
        process = subprocess.run(['node', '--input-type=module', '-e', '''
          import fs from 'node:fs';
          import {definitions} from './dsh-plugin/analysis.js';
          const tool = definitions().find(t => t.name === process.argv[1]);
          const out = tool.output.render({}, {stdout:fs.readFileSync(0,'utf8')});
          if(out.length !== 1 || out[0].type !== 'text') throw Error('unexpected render');
          process.stdout.write(out[0].text);
        ''', tool], cwd=ROOT, input=raw, text=True, capture_output=True, check=True)
        packet = json.loads(process.stdout)
        decoded = (restore_table(packet) if packet.get('_model_projection', {}).get('schema') == 'foundry.model-result.v2'
                   else restore(packet, packet))
        return original, decoded

    prepared, visible = cli_render('prepare-explanation', 'prepare_explanation', {'run_ids': [run['id']]})
    assert visible['forecast_performance'] == prepared['forecast_performance']
    facts = visible['forecast_performance']['facts']
    assert len(facts) == 2 and all(f['counts_as_amount_evidence'] is False for f in facts)
    assert all(f['scope'] and f['source']['dataset_id'] and f['source']['json_pointer'] for f in facts)
    spec = ({**prepared['save_template_spec'], 'qualitative_note': BAD} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + BAD})
    failed, visible_failed = cli_render('save-explanation-draft', 'save_explanation_draft', spec)
    expected = [i for i in failed['quality']['issues'] if i['code'] == CODE]
    assert expected and [i for i in visible_failed['quality']['issues'] if i['code'] == CODE] == expected
    assert all(i['text'] and isinstance(i['position'], int) for i in expected)
    _, fixed = cli_render('save-explanation-draft', 'save_explanation_draft', {
        **prepared['save_template_spec'], 'parent_id': failed['id'],
        'qualitative_note': '来源将两项服务均设为预测当期已履约；不是现实履约证明。'})
    assert fixed['completion']['status'] == 'complete'
    (tmp_path / 'model-delivery-evidence.json').write_text(json.dumps({
        'surface': 'real_cli_then_existing_tool_output_renderer_and_lossless_decode',
        'short_save': short, 'run_id': run['id'], 'forecast_performance': visible['forecast_performance'],
        'original_and_visible_issues_identical': True, 'local_issues': expected,
        'failed_draft_id': failed['id'], 'failed_completion_status': failed['completion']['status'],
        'repaired_draft_id': fixed['id'], 'repaired_completion': fixed['completion'],
        'provider_calls': 0,
    }, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('short', [False, True])
def test_actual_repair_then_receipt_preserves_failed_version(tmp_path, short):
    from foundry.finance_explanations import saved_claim_semantic_issues
    service, _, _, run = performance_case(tmp_path)
    before_run = deepcopy(service.analysis.get_run(run['id']))
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    assert len(prepared['forecast_performance']['facts']) == 2
    assert all(f['counts_as_amount_evidence'] is False for f in prepared['forecast_performance']['facts'])
    assert len(prepared['facts']) == 13  # qualitative proof does not become amount facts
    spec = ({**prepared['save_template_spec'], 'qualitative_note': BAD} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + BAD})
    failed = service.save_explanation_draft(spec)
    stored_bad = deepcopy(service.analysis.get_draft(failed['id']))
    good = '本预测来源将基础服务和新增现金服务均设为当期已履约；不证明现实中已发生。'
    repaired = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': failed['id'], 'qualitative_note': good})
    assert repaired['completion']['status'] == 'complete', repaired['quality']
    assert service.analysis.get_draft(failed['id']) == stored_bad
    assert saved_claim_semantic_issues(service.analysis, stored_bad)[0]['code'] == CODE
    assert service.analysis.get_run(run['id']) == before_run
    old_epoch = {**deepcopy(stored_bad), 'explanation_check': {**stored_bad['explanation_check'], 'claim_semantics_version': 12}}
    copy_before = deepcopy(old_epoch)
    assert saved_claim_semantic_issues(service.analysis, old_epoch)[0]['code'] == CODE
    assert old_epoch == copy_before
    assert service.analysis.completion_in_view(repaired['completion'], None)['status'] == 'complete'
    (tmp_path / 'save-revision-evidence.json').write_text(json.dumps({
        'short_save': short, 'run_id': run['id'], 'output_hash': run['output_hash'],
        'forecast_performance': prepared['forecast_performance'],
        'failed_draft_id': failed['id'], 'failed_quality': failed['quality']['status'],
        'local_issues': [i for i in failed['quality']['issues'] if i['code'] == CODE],
        'failed_completion_status': failed['completion']['status'],
        'repaired_draft_id': repaired['id'], 'parent_id': repaired['parent_id'],
        'repaired_quality': repaired['quality']['status'], 'repaired_completion': repaired['completion'],
        'failed_version_and_run_unchanged': True, 'old_epoch_recheck_input_unchanged': True,
        'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
