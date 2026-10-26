"""A forecast assumption may contradict only a locally attributed forecast claim."""
from copy import deepcopy
import json

import pytest

from foundry.finance_claim_semantics import forecast_performance_issues
from foundry.finance_explanations import _forecast_performance_sources
from test_finance_performance_semantics import CODE, performance_case

ACTUAL = '现实中 S-CUR-01 尚未履约；来源仅假设本预测期已履约。'


@pytest.mark.parametrize('short', [False, True])
def test_real_ordinary_and_compact_do_not_invert_forecast_into_reality(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    spec = ({**prepared['save_template_spec'], 'qualitative_note': ACTUAL} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + ACTUAL})
    saved = service.save_explanation_draft(spec)
    issues = [i for i in saved['quality']['issues'] if i['code'] == CODE]
    (tmp_path / 'actual-modality-save.json').write_text(json.dumps({
        'short': short, 'note': ACTUAL, 'draft_id': saved['id'], 'issues': issues,
        'quality': saved['quality']['status'], 'completion': saved['completion']['status'],
        'run_id': run['id'], 'output_hash': run['output_hash'], 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert not issues
    assert saved['quality']['status'] == 'pass' and saved['completion']['status'] == 'complete'


@pytest.fixture(scope='module')
def proof(tmp_path_factory):
    service, _, _, run = performance_case(tmp_path_factory.mktemp('scope-proof'))
    proof = _forecast_performance_sources(service.analysis, [run])
    assert proof['status'] == 'verified'
    return proof['facts']


@pytest.mark.parametrize('body', [
    ACTUAL,
    'S-CUR-01 实际尚未履约，不影响本预测假定其本月已履约。',
    'In reality S-CUR-01 is not yet performed; the forecast assumes performance.',
    'S-CUR-01 与 OTHER-CONTRACT 中 OTHER-CONTRACT 尚待履约。',
    'S-CUR-01 已履约而 OTHER-CONTRACT 尚待履约。',
    'S-CUR-01 对照 OTHER-CONTRACT，后者尚待履约。',
    'S-CUR-01 尚待履约（2026-11）。',
    'S-CUR-01 尚待履约的期间是 2026-11。',
    'S-CUR-01 is pending performance in 2026-11.',
    '本期服务在待履约时不得确认收入。',
    '本期服务须待履约后才确认收入。',
    'S-CUR-01 在尚未履约时不能确认收入。',
    'S-CUR-01 须待履约后才确认收入。',
    'S-CUR-01 在未履约时应先复核；来源未授予现实履约结论。',
])
def test_unproved_domain_subject_period_or_policy_is_not_a_contradiction(proof, body):
    assert forecast_performance_issues(body, performance_facts=proof) == []


@pytest.mark.parametrize('body', [
    '本期服务尚待履约，不能确认收入。',
    '本期服务尚待履约；如果未来履约才确认收入。',
    'S-CUR-01 本期仍待履约。',
    '现实中 S-CUR-01 尚未履约；但本预测中 S-CUR-01 尚待履约。',
    '现实状态须另核；本预测实际设为 S-CUR-01 尚待履约。',
    'S-CUR-01 与 OTHER-CONTRACT 中 S-CUR-01 尚待履约。',
    'OTHER-CONTRACT 已履约而 S-CUR-01 尚待履约。',
    'S-CUR-01 尚待履约（2026-10）。',
    'S-CUR-01 尚待履约的期间是 2026-10。',
    'S-CUR-01 尚待履约，2026-11 另有新服务。',
    'S-CUR-01 is pending performance in 2026-10.',
    'S-CUR-01 在尚未履约时不能确认收入；但本期 S-CUR-01 尚待履约。',
    '“S-CUR-01 尚待履约”这一说法错误；本预测中 S-CUR-01 仍待履约。',
])
def test_adjacent_independent_affirmative_forecast_is_still_checked(proof, body):
    issues = forecast_performance_issues(body, performance_facts=proof)
    assert len(issues) == 1
    assert issues[0]['asserted'] == 'pending' and issues[0]['source_facts'][0]['contract_id'] == 'S-CUR-01'


def test_real_false_assumption_is_not_actual_nonperformance_proof(tmp_path):
    service, _, _, run = performance_case(tmp_path, lambda r: r['base_current_service'].update(performed_in_forecast=False))
    proof = _forecast_performance_sources(service.analysis, [run])
    body = '现实中 S-CUR-01 已履约；本预测来源将 S-CUR-01 设为未履约。'
    assert forecast_performance_issues(body, performance_facts=proof['facts']) == []
    assert forecast_performance_issues('本预测中 S-CUR-01 已履约。', performance_facts=proof['facts'])


@pytest.mark.parametrize('short', [False, True])
def test_real_wrong_forecast_then_domain_clarification_keeps_failed_version(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    bad = '本期服务尚待履约，不能确认收入。'
    spec = ({**prepared['save_template_spec'], 'qualitative_note': bad} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + bad})
    failed = service.save_explanation_draft(spec)
    assert any(i['code'] == CODE for i in failed['quality']['issues'])
    old_draft = deepcopy(service.analysis.get_draft(failed['id']))
    old_run = deepcopy(service.analysis.get_run(run['id']))
    fixed = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': failed['id'],
                                           'qualitative_note': ACTUAL})
    assert fixed['completion']['status'] == 'complete'
    assert service.analysis.get_draft(failed['id']) == old_draft
    assert service.analysis.get_run(run['id']) == old_run
    (tmp_path / 'actual-scope-revision.json').write_text(json.dumps({
        'short': short, 'failed_id': failed['id'], 'failed_quality': failed['quality']['status'],
        'failed_issues': [i for i in failed['quality']['issues'] if i['code'] == CODE],
        'fixed_id': fixed['id'], 'fixed_completion': fixed['completion'],
        'historical_failed_version_and_run_unchanged': True, 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
