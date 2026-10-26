"""Public native-check assertions share the saved-prose truth boundary."""
from copy import deepcopy

import pytest

from foundry.finance_claim_semantics import check_claim_semantics
from test_finance_professional_protocol import _template_case

ZERO_LIVE = 'All 12 model checks `pass` (differences = 0; `cash_sufficiency` is `alert` severity, not blocking evidence).'
METADATA_LIVE = ('12 model checks: all `pass` (opening_balance_sheet 530=530, revenue_receivables_cash 93=93, '
    'ppe_rollforward 345=345, payables_rollforward 90=90, debt_financing 165=165, equity_rollforward 392=392, '
    'cash_reconciliation 209=209, cash_flow_indirect_bridge 122=122, closing_balance_sheet 647=647, '
    'nonnegative_operating_balances, restricted_cash_bounds, cash_sufficiency — '
    'the last three are `alert` severity with positive margins, not failures).')


@pytest.fixture
def native(tmp_path):
    return _template_case(tmp_path)[-1]


@pytest.mark.parametrize('body', [ZERO_LIVE,
    'All 12 model checks pass (differences = 0).',
    'All model checks `pass` (differences = 0).',
    'All **12** model checks pass; all differences are **0**.',
    'All twelve model checks pass, and all their differences are zero.',
    '**十二**项模型检查均通过，**差额全部为零**。',
    '12 项模型检查全部通过，所以各项差额均为零。',
    '检查结论：“所有12项检查差额都是0。”',
    '并非全都为零；但本例所有12项检查的差额均为0。'])
def test_affirmative_universal_zero_claims_reject(native, body):
    issues = check_claim_semantics(body, [], runs=[native])
    assert any(i['code'] == 'model_check_difference_claim_mismatch' for i in issues)
    assert all(c['status'] == 'pass' for c in native['result']['model_checks'])


@pytest.mark.parametrize('body', [METADATA_LIVE,
    'nonnegative_operating_balances and restricted_cash_bounds have blocks_evidence=false.',
    'cash_sufficiency is error severity and blocks_evidence=true.',
    'nonnegative_operating_balances 的 severity 为 alert。'])
def test_explicit_native_metadata_claims_reject_without_redefining_status(native, body):
    before = deepcopy(native)
    issues = check_claim_semantics(body, [], runs=[native])
    assert any(i['code'] == 'model_check_metadata_claim_mismatch' for i in issues)
    assert native == before


def test_complete_unique_ordinal_list_and_configured_flag_are_separate_from_status(native):
    ordered = ', '.join(c['id'] for c in native['result']['model_checks'])
    for body in (ordered + '. The last three are alert.',
                 'nonnegative_operating_balances currently passes, therefore its configured blocks_evidence flag is false.'):
        assert any(i['code'] == 'model_check_metadata_claim_mismatch' for i in check_claim_semantics(body, [], runs=[native]))
    for body in (ordered.rsplit(', ', 1)[0] + '. The last three are alert.',
                 ordered.replace('cash_sufficiency', 'restricted_cash_bounds') + '. The last three are alert.',
                 'nonnegative_operating_balances has blocks_evidence=true but is passing, so it causes no current failed-check evidence block.',
                 'The current successful run has no failed evidence-blocking model check.'):
        assert check_claim_semantics(body, [], runs=[native]) == []


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('text', [ZERO_LIVE, METADATA_LIVE])
def test_actual_save_and_previous_epoch_views_share_checker_without_rewriting_history(tmp_path, short, text):
    from foundry.finance_explanations import saved_claim_semantic_issues
    service, _, _, run = _template_case(tmp_path)
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    spec = ({**prepared['save_template_spec'], 'qualitative_note': text} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + text})
    draft = service.save_explanation_draft(spec)
    assert draft['completion']['status'] != 'complete'
    assert any(i['code'].startswith('model_check_') for i in draft['quality']['issues'])
    legacy = deepcopy(draft)
    for key in ('quality', 'explanation_check'):
        legacy[key]['claim_semantics_version'] = 11
    before = deepcopy(legacy)
    run_before = service.analysis.get_run(run['id'])
    assert any(i['code'].startswith('model_check_') for i in saved_claim_semantic_issues(service.analysis, legacy))
    assert before == legacy and run_before == service.analysis.get_run(run['id'])


@pytest.mark.parametrize('body', [
    'All 12 model checks pass.',
    'Nine equality checks have zero differences.',
    'The three threshold checks have positive margins and pass.',
    'cash_sufficiency is alert severity and blocks_evidence=false.',
    'nonnegative_operating_balances and restricted_cash_bounds are error-level checks with blocks_evidence=true; both currently pass.',
    '虽然 nonnegative_operating_balances 的 severity 为 error，但其 status 是 pass。',
    'All 12 model checks do not have differences of zero.',
    'If all 12 model checks pass with differences = 0, discuss the result.',
    'All 12 model checks pass (differences = 0)?',
    'The claim "All 12 model checks pass (differences = 0)" is wrong.',
    'If cash_sufficiency is error severity, review the result.',
    'cash_sufficiency is error severity?',
    'The claim "cash_sufficiency is error severity" is wrong.',
    'cash_sufficiency is error severity, this claim is false.',
    'cash_sufficiency is error severity, that claim is incorrect.',
    'cash_sufficiency is error severity, this statement is incorrect.',
    '不能说 nonnegative_operating_balances 是 alert。',
    '并非后三项检查都是 alert；只有 cash_sufficiency 为 alert。',
    'All 12 checks pass. The last three are alert.',
    '收入、收款、应收列在上表。后三项都是 alert。',
    'The last three are alert.',
    'nonnegative_operating_balances, restricted_cash_bounds, cash_sufficiency — the last three are `alert` severity.',
    'cash_sufficiency, cash_sufficiency, restricted_cash_bounds — the last three are alert.',
    'cash_sufficiency, restricted_cash_bounds — the last three are alert.',
    'nonnegative_operating_balances, restricted_cash_bounds, cash_sufficiency.\nThe last three are alert.',
    '```\nAll 12 model checks pass (differences = 0).\n```',
    '正在读取来源，稍后继续核对。',
])
def test_legitimate_scoped_or_unresolved_claims_not_falsely_contradicted(native, body):
    assert check_claim_semantics(body, [], runs=[native]) == []


def test_unrelated_denial_does_not_excuse_affirmative_metadata(native):
    for body in ('cash_sufficiency is error severity; this claim is false.',
                 'cash_sufficiency is error severity; this statement is incorrect.',
                 'cash_sufficiency is error severity, the revenue claim is false.',
                 'Another claim is false, but cash_sufficiency is error severity.'):
        assert any(i['code'] == 'model_check_metadata_claim_mismatch' for i in check_claim_semantics(body, [], runs=[native]))
