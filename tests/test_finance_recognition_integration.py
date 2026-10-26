"""Recognition evidence is read in preparation, validation and current old-draft views."""
import hashlib
import json

import pytest

from foundry.analysis import AnalysisStore, _new
from foundry.errors import FoundryError
from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from foundry.finance_explanations import (
    _service_recognition_basis,
    prepare_explanation,
    saved_claim_semantic_issues,
    validate_explanation,
)
from foundry.finance_professional import draft_professional_view, receipt_professional_view
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def run(tmp_path, *, direction=None, nature=None, completed='yes'):
    analysis = AnalysisStore(TaskStore(tmp_path / 'var').create(title='月结子账与总账差异'))
    scope = {'ledger': 'L1', 'organization': 'O1', 'period': '2026-12',
             'scenario': 'actual', 'currency': 'CNY', 'unit': '元'}
    source = tmp_path / 'comparison.json'
    fields = {**({'service_completed': completed} if completed else {}),
              **({'service_direction': direction} if direction else {}),
              **({'economic_nature': nature} if nature else {})}
    source.write_text(json.dumps([{'management_account': account, 'amount': amount,
                                  'approval': 'pending', **fields, **scope}
                                 for account, amount in [('subledger', '100'), ('gl', '0')]]))
    dataset = analysis.add_dataset(source, name='comparison')
    service = FinanceStore(analysis.task)
    context = service.save_context({'bindings': {'cc': dataset['id']}, 'scopes': {'cc': scope}})
    result = service.run_metric({'context_id': context['id'], 'metric': {'kind': 'control_totals'}})
    return analysis, result, dataset


def test_prepare_and_validate_use_source_bound_qualitative_basis(tmp_path):
    analysis, result, _ = run(tmp_path)
    prepared = prepare_explanation(analysis, [result])
    assert prepared['recognition_basis']['status'] == 'insufficient'
    quality = validate_explanation(analysis, {'body': '子账与总账差额待核。应借费用贷应计负债。',
                                            'run_ids': [result['id']], 'claims': [], 'fact_ids': []})
    assert quality['recognition_basis_version'] == 1
    assert any(issue['code'] == 'recognition_basis_unverified' for issue in quality['issues'])
    assert quality['status'] == 'needs_attention'
    assert quality['recognition_basis']['posting_authorized'] is False


@pytest.mark.parametrize('stored_version', [17, CLAIM_SEMANTICS_VERSION])
def test_old_passed_draft_and_receipt_are_rechecked_read_only(tmp_path, stored_version):
    analysis, result, _ = run(tmp_path)
    quality = {'status': 'pass', 'issues': [], 'claim_semantics_version': stored_version}
    draft = _new(analysis.task, body='应借费用贷应计负债。', run_ids=[result['id']],
                 claims=[], fact_ids=[], quality=quality, explanation_check=quality)
    path = analysis._object_path('drafts', draft['id'])
    draft = analysis._write(path, draft)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    issues = saved_claim_semantic_issues(analysis, draft)
    assert any(issue['code'] == 'recognition_basis_unverified' for issue in issues)
    current = draft_professional_view(analysis, draft)
    assert current['quality']['status'] == 'needs_attention'
    receipt = {'draft_id': draft['id'], 'status': 'complete', 'original_requirements_completed': True}
    view = receipt_professional_view(analysis, receipt)
    assert view['status'] == 'needs_review'
    assert view['historical_status'] == 'complete'
    assert view['original_requirements_completed'] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert receipt['status'] == 'complete'  # Existing stored object is never rewritten.


def test_explicit_received_expense_and_pending_approval_do_not_block_direction(tmp_path):
    analysis, result, _ = run(tmp_path, direction='received', nature='expense')
    quality = validate_explanation(analysis, {'body': '据源事实提出费用草案，借费用贷应付；待专业审核，不作过账授权。',
                                            'run_ids': [result['id']], 'claims': [], 'fact_ids': []})
    assert quality['recognition_basis']['status'] == 'explicit_source_basis'
    assert not any(issue['code'] == 'recognition_basis_unverified' for issue in quality['issues'])
    assert quality['recognition_basis']['posting_authorized'] is False


def test_saved_view_does_not_read_a_run_outside_snapshot_ceiling(tmp_path):
    analysis, result, dataset = run(tmp_path)
    draft = {'body': '借费用贷应计负债。', 'run_ids': [result['id']],
             'claims': [], 'fact_ids': [], 'quality': {'claim_semantics_version': CLAIM_SEMANTICS_VERSION}}
    assert saved_claim_semantic_issues(analysis, draft, allowed=set()) == []
    assert saved_claim_semantic_issues(analysis, draft, allowed={dataset['id']})


@pytest.mark.parametrize('stored_version', [17, CLAIM_SEMANTICS_VERSION])
def test_requirement_only_policy_source_is_checked_even_when_run_bound_only_comparison(tmp_path, stored_version):
    analysis, result, comparison = run(tmp_path, completed=None)
    policy_path = tmp_path / 'policy.json'
    policy_path.write_text(json.dumps([{'name': 'service_completed', 'value': 'yes'},
                                       {'name': 'approval', 'value': 'pending'}]))
    policy = analysis.add_dataset(policy_path, name='policy')
    service = FinanceStore(analysis.task)
    requirement = service.analysis_requirements_save({
        'question': '处理月结子账与总账差异', 'bindings': {'cc': comparison['id'], 'pf': policy['id']},
        'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-12',
                  'scenario': 'actual', 'currency': 'CNY', 'unit': '元'},
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}],
    })
    assert set(result['bindings'].values()) == {comparison['id']}
    prepared = prepare_explanation(analysis, [result])
    assert prepared['recognition_basis']['status'] == 'insufficient'
    assert prepared['recognition_basis']['sources'][0]['dataset_id'] == policy['id']
    spec = {'body': '费用和负债均未入账。', 'run_ids': [result['id']],
            'claims': [], 'fact_ids': [], 'requirements_id': requirement['id']}
    quality = validate_explanation(analysis, spec)
    assert any(issue['code'] == 'recognition_basis_unverified' for issue in quality['issues'])
    draft = {**spec, 'quality': {'claim_semantics_version': stored_version}}
    assert saved_claim_semantic_issues(analysis, draft)
    # The original complete-binding requirement remains unmet: this diagnostic
    # neither manufactures the missing finance context nor runs/saves anything.
    assert len(service._list('contexts')) == 1
    assert len(analysis._list('runs')) == 1
    assert not analysis._list('drafts')
    limited = prepare_explanation(analysis, [result], _allowed={comparison['id']})
    assert 'recognition_basis' not in limited
    assert policy['id'] not in json.dumps(limited)


def test_unreadable_requirement_source_cannot_borrow_an_explicit_received_expense(tmp_path):
    analysis, result, comparison = run(tmp_path, direction='received', nature='expense')
    source_path = tmp_path / 'other-policy.json'
    source_path.write_text(json.dumps([{'name': 'approval', 'value': 'pending'}]))
    policy = analysis.add_dataset(source_path, name='other-policy')
    service = FinanceStore(analysis.task)
    requirement = service.analysis_requirements_save({
        'question': '处理月结子账与总账差异', 'bindings': {'cc': comparison['id'], 'pf': policy['id']},
        'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-12',
                  'scenario': 'actual', 'currency': 'CNY', 'unit': '元'},
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}],
    })
    # Corrupt only this test's archived snapshot. The report must use the real
    # dataset integrity reader and fail closed, rather than trust surviving rows.
    archived = analysis.root / 'datasets' / policy['id'] / 'data.json'
    archived.write_text('[]')
    before = archived.read_bytes()
    prepared = prepare_explanation(analysis, [result])
    assert prepared['recognition_basis']['status'] == 'insufficient'
    assert prepared['recognition_basis']['unavailable_dataset_ids'] == [policy['id']]
    spec = {'body': 'The expense was omitted.', 'run_ids': [result['id']],
            'requirements_id': requirement['id'], 'claims': [], 'fact_ids': []}
    quality = validate_explanation(analysis, spec)
    assert any(issue['code'] == 'recognition_basis_unverified' for issue in quality['issues'])
    draft = {**spec, 'quality': {'claim_semantics_version': CLAIM_SEMANTICS_VERSION}}
    assert saved_claim_semantic_issues(analysis, draft)
    assert archived.read_bytes() == before


@pytest.mark.parametrize('body,needs_source', [
    ('本月收入由原计算结果引用。', False),
    ('查看已保存的结果。', False),
    ('总账漏记费用。', True),
    ('借费用贷应计负债。', True),
    ('The expenses were materially understated.', True),
    ('若核实为接受服务且应费用化，请借费用贷应付。', True),
])
def test_current_saved_recognition_only_loads_sources_for_candidate_assertions(body, needs_source):
    class SourceReadRequired(RuntimeError):
        pass

    class Analysis:
        def get_run(self, run_id):
            raise SourceReadRequired(run_id)

    draft = {'body': body, 'run_ids': ['current-run'],
             'explanation_check': {'claim_semantics_version': CLAIM_SEMANTICS_VERSION}}
    if needs_source:
        with pytest.raises(SourceReadRequired, match='current-run'):
            saved_claim_semantic_issues(Analysis(), draft)
    else:
        assert saved_claim_semantic_issues(Analysis(), draft) == []


def _requirements(analysis, bindings, **version):
    return FinanceStore(analysis.task).analysis_requirements_save({
        'question': '处理月结子账与总账差异', 'bindings': bindings,
        'scope': {'ledger': 'L1', 'organization': 'O1', 'period': '2026-12',
                  'scenario': 'actual', 'currency': 'CNY', 'unit': '元'},
        'items': [{'id': 'controls', 'metric': 'control_totals', 'requires_drilldown': False}],
        **version,
    })


@pytest.mark.parametrize('body,recognition_issue', [('收入。', False), ('总账漏记费用。', True)])
def test_manager_without_requirements_ignores_unused_id_but_checks_raw_service(tmp_path, body, recognition_issue):
    analysis, result, dataset = run(tmp_path)
    assert not analysis._list('requirements')
    quality = FinanceStore(analysis.task).validate_explanation({
        'requirements_id': 'e' * 32, 'body': body, 'run_ids': [result['id']],
    })
    assert quality['requirements']['coverage']['status'] == 'not_assessed'
    assert quality['recognition_basis']['source_dataset_ids'] == [dataset['id']]
    assert quality['recognition_basis']['status'] == 'insufficient'
    assert any(issue['code'] == 'recognition_basis_unverified' for issue in quality['issues']) is recognition_issue


def test_no_requirements_unknown_id_does_not_hide_unreadable_raw_source(tmp_path):
    analysis, result, dataset = run(tmp_path, direction='received', nature='expense')
    archived = analysis.root / 'datasets' / dataset['id'] / 'data.json'
    archived.write_text('[]')
    report = _service_recognition_basis(analysis, [result], requirements_id='e' * 32)
    assert report['status'] == 'insufficient'
    assert report['source_dataset_ids'] == report['unavailable_dataset_ids'] == [dataset['id']]
    from foundry.finance_recognition_basis import recognition_claim_issues
    assert recognition_claim_issues('借费用贷应计负债。', report)


@pytest.mark.parametrize('with_current', [False, True])
def test_session_unknown_requirements_remain_unavailable(tmp_path, with_current):
    analysis, result, dataset = run(tmp_path)
    if with_current:
        _requirements(analysis, {'cc': dataset['id']})
    session = FinanceStore(analysis.task, snapshot_ids=[dataset['id']], session_id='analysis-session')
    with pytest.raises(FoundryError, match='requirements version is unavailable'):
        session.validate_explanation({'requirements_id': 'e' * 32, 'body': '收入。', 'run_ids': [result['id']]})
    with pytest.raises(FoundryError, match='analysis object is unavailable'):
        _service_recognition_basis(analysis, [result], requirements_id='e' * 32, allowed={dataset['id']})


def test_manager_with_current_requirements_does_not_ignore_unknown_id(tmp_path):
    analysis, result, dataset = run(tmp_path)
    _requirements(analysis, {'cc': dataset['id']})
    with pytest.raises(FoundryError, match='analysis object is unavailable'):
        FinanceStore(analysis.task).validate_explanation({
            'requirements_id': 'e' * 32, 'body': '收入。', 'run_ids': [result['id']],
        })


@pytest.mark.parametrize('reader', ['manager', 'session'])
def test_explicit_historical_and_current_requirement_sources_are_both_checked(tmp_path, reader):
    analysis, result, dataset = run(tmp_path, completed=None)
    old_path = tmp_path / 'old-policy.json'
    old_path.write_text(json.dumps([{'service_completed': 'yes'}]))
    old_policy = analysis.add_dataset(old_path, name='old-policy')
    old = _requirements(analysis, {'cc': dataset['id'], 'pf': old_policy['id']})
    current_path = tmp_path / 'current-policy.json'
    current_path.write_text(json.dumps([{'service_completed': 'yes', 'service_direction': 'received',
                                         'economic_nature': 'expense'}]))
    current_policy = analysis.add_dataset(current_path, name='current-policy')
    current = _requirements(analysis, {'cc': dataset['id'], 'pf': current_policy['id']},
                            parent_id=old['id'], change_reason='更新确认依据来源')
    ids = {dataset['id'], old_policy['id'], current_policy['id']}
    service = (FinanceStore(analysis.task) if reader == 'manager' else
               FinanceStore(analysis.task, snapshot_ids=sorted(ids), session_id='analysis-session'))
    quality = service.validate_explanation({'requirements_id': old['id'], 'body': '总账漏记费用。',
                                            'run_ids': [result['id']]})
    assert quality['requirements']['requirements_id'] == current['id']
    assert set(quality['recognition_basis']['source_dataset_ids']) == ids
    assert quality['recognition_basis']['status'] == 'insufficient'
    assert any(issue['code'] == 'recognition_basis_unverified' for issue in quality['issues'])
    limited = FinanceStore(analysis.task, snapshot_ids=[dataset['id'], current_policy['id']],
                           session_id='limited-session')
    with pytest.raises(FoundryError, match='requirements version is unavailable'):
        limited.validate_explanation({'requirements_id': old['id'], 'body': '总账漏记费用。',
                                       'run_ids': [result['id']]})
