"""A completed service is not a source-bound expense/liability recognition basis."""
from copy import deepcopy
import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_recognition_basis import recognition_basis_report, recognition_claim_issues
from foundry.task import TaskStore


@pytest.fixture
def analysis(tmp_path):
    return AnalysisStore(TaskStore(tmp_path / 'var').create(title='月结子账与总账差异'))


def dataset(analysis, tmp_path, rows, name='source'):
    path = tmp_path / f'{name}.json'
    path.write_text(json.dumps(rows, ensure_ascii=False))
    return analysis.add_dataset(path, name=name)


def e12_rows(**updates):
    return [{'service_completed': 'yes', 'service_period': '2026-12',
             'subledger': '100', 'gl': '0', 'approval': 'pending', **updates}]


def report_for(analysis, tmp_path, rows=None):
    source = dataset(analysis, tmp_path, rows if rows is not None else e12_rows())
    return recognition_basis_report(analysis, {'ledger': source['id']}), source


@pytest.mark.parametrize('body', [
    '服务已完成，总账漏记费用与负债，建议借费用贷应计负债。',
    '费用和负债均少计，应当确认该费用。',
    '总账未记录义务，应补提费用。',
    '建议借：管理费用，贷：应付账款；具体科目待经理确认。',
    'The service is complete. Debit expense and credit accrued liabilities.',
    'The GL has omitted the expense and liability.',
    '费用和负债均未入账。',
    '形成尚未入账的应计义务。',
    '应计负债漏记。',
    '存在应计漏记。',
    'The expense was omitted.',
    'The liability is understated.',
    'The expenses were omitted.',
    'The expense is materially understated.',
    'The liability remains unrecorded.',
])
def test_completed_service_does_not_prove_definite_expense_or_liability(analysis, tmp_path, body):
    report, source = report_for(analysis, tmp_path)
    assert report['status'] == 'insufficient'
    assert report['missing_fields'] == ['service_direction', 'economic_nature']
    assert report['posting_authorized'] is False
    assert report['counts_as_amount_evidence'] is False
    assert report['sources'][0]['dataset_id'] == source['id']
    assert report['sources'][0]['source_hash'] == source['source_hash']
    issues = recognition_claim_issues(body, report)
    assert issues and all(issue['severity'] == 'error' for issue in issues)
    assert all(issue['code'] == 'recognition_basis_unverified' for issue in issues)
    assert all(issue['counts_as_amount_evidence'] is False for issue in issues)


@pytest.mark.parametrize('body', [
    '子账100元、总账0元，差额100元；确认方向待核，不作为过账依据。',
    '服务已完成并不说明服务是接受还是提供，尚不能认定费用与负债漏记。',
    '不能仅据服务完成认定总账漏记费用与负债。',
    '是否存在漏记费用与负债，需核对合同、凭证与接口。',
    '需核实是否应借费用、贷应付；目前不给确定分录。',
    '若经凭证核实为本企业接受且本期应费用化、尚未入账的服务，则可提出借费用贷应付的待审批草案。',
    '假设该事项是接受服务且符合费用化政策，借费用贷应计仅作条件示例。',
    '“应借费用贷应计负债”这一说法依据不足，不应采用。',
    'Service completion does not establish an omitted expense or liability.',
    'If the service was received and is an unrecorded expense, debit expense and credit accrued liabilities.',
    '费用和负债可能均未入账，尚需核实。',
    '可能形成尚未入账的应计义务，应谨慎待核。',
    '应计负债是否漏记，需核对原始凭证。',
    '存在应计漏记的可能，仍待核实。',
    '若核实后存在应计漏记，再形成待审批方案。',
    '不能认定费用和负债均未入账。',
    '未必形成尚未入账的应计义务。',
    '存在应计漏记？应谨慎待核。',
    'The expense was not omitted.',
    'The liability is not understated.',
    'Is the expense omitted?',
    'Whether the liability is understated remains to be verified.',
    'If the service was received and expensed, the expense was omitted.',
    '总账费用是否漏记？',
    '总账漏记费用是否属实？',
    '总账漏记费用，如果合同证明本企业接受且符合费用化政策。',
    'The expense was omitted is an unsupported conclusion.',
    '“The expense was omitted” is an unsupported conclusion.',
    '总账漏记费用吗，还是接口尚未同步？',
    'Was the expense omitted, or was the source interface delayed?',
    'The expenses were not omitted.',
    'The expense is possibly materially understated.',
    '借费用贷应计负债，如果该服务为本企业收受且应费用化。',
])
def test_qualified_missing_basis_questions_and_conditions_remain_editable(analysis, tmp_path, body):
    report, _ = report_for(analysis, tmp_path)
    before = deepcopy(report)
    assert recognition_claim_issues(body, report) == []
    assert report == before


@pytest.mark.parametrize('body', [
    '不能忽略期间，但是应确认费用与负债。',
    '不能直接认定费用漏记，但建议借费用贷应计负债。',
    '尚需核对接口；总账确定漏记费用。',
    'If documents are missing, request them. Debit expense and credit accrued liabilities.',
    '可能存在错配，但费用和负债均未入账。',
    '可能存在接口问题，形成尚未入账的应计义务。',
    '如果资料不齐，请联系财务，应借费用贷应计负债。',
    '若需要更多资料，请先索取，费用与负债均未入账。',
    'If documents are missing, ask finance, debit expense and credit accrued liabilities.',
    'Whether the documents are available is unknown. The expense was omitted.',
    '总账漏记费用，你是否同意？',
    '总账漏记费用，请确认是否已修复？',
    '不能忽视数据缺口而应借费用贷应计负债。',
    'The expense was not omitted and the liability is understated.',
    '总账漏记费用但是否已修复？',
    '总账漏记费用请确认是否已修复？',
    '不能忽视数据缺口且应借费用贷应计负债。',
    '如果资料不齐请联系财务，应借费用贷应计负债。',
    '若资料缺失请先补齐，费用与负债均未入账。',
    'If documents are missing please request them, debit expense and credit accrued liabilities.',
    '不能忽略合同而且费用与负债均未入账。',
    '如果费用资料不齐请联系财务，应借费用贷应计负债。',
    '借费用贷应计负债，如果资料缺失请联系财务。',
    '借费用贷应计负债，总账费用已漏记，如果该服务为本企业收受且应费用化。',
])
def test_unrelated_qualification_does_not_hide_an_affirmative_conclusion(analysis, tmp_path, body):
    report, _ = report_for(analysis, tmp_path)
    assert recognition_claim_issues(body, report)


def test_explicit_received_expense_source_is_available_but_never_posting_authority(analysis, tmp_path):
    report, source = report_for(analysis, tmp_path,
                               e12_rows(service_direction='received', economic_nature='expense'))
    assert report['status'] == 'explicit_source_basis'
    assert report['missing_fields'] == []
    assert report['sources'][0]['facts']['service_direction'] == 'received'
    assert report['sources'][0]['facts']['economic_nature'] == 'expense'
    assert recognition_claim_issues('费用按服务收受事实提出待审批草案，借费用贷应付。', report) == []
    assert report['posting_authorized'] is False
    assert report['counts_as_amount_evidence'] is False
    assert report['source_dataset_ids'] == [source['id']]


def test_provided_service_does_not_borrow_received_expense_nature(analysis, tmp_path):
    report, _ = report_for(analysis, tmp_path,
                          e12_rows(service_direction='provided', economic_nature='revenue'))
    assert report['status'] == 'explicit_source_basis'
    assert recognition_claim_issues('收入和应收按服务提供事实提出待审批草案。', report) == []
    assert recognition_claim_issues('应确认费用与负债，借费用贷应付。', report)


def test_received_capital_service_does_not_support_expense_assertion(analysis, tmp_path):
    report, _ = report_for(analysis, tmp_path,
                          e12_rows(service_direction='received', economic_nature='capitalizable_asset'))
    assert recognition_claim_issues('应确认费用与负债，借费用贷应付。', report)


def test_long_form_source_facts_preserve_row_identity_and_do_not_make_up_direction(analysis, tmp_path):
    rows = [{'name': name, 'value': value} for name, value in e12_rows()[0].items()]
    report, source = report_for(analysis, tmp_path, rows)
    assert report['status'] == 'insufficient'
    assert report['sources'][0]['dataset_id'] == source['id']
    assert report['sources'][0]['source_rows'] == [1, 2, 3, 4, 5]
    assert report['sources'][0]['facts']['service_completed'] == 'yes'
    assert report['missing_fields'] == ['service_direction', 'economic_nature']


def test_amounts_and_sql_shaped_fields_do_not_supply_economic_facts(analysis, tmp_path):
    report, _ = report_for(analysis, tmp_path,
                          e12_rows(account='expense', amount='100', metric='expense',
                                   sql='select 100 as expense', proposed_entries='expense=100'))
    assert report['status'] == 'insufficient'
    assert report['missing_fields'] == ['service_direction', 'economic_nature']
    assert recognition_claim_issues('借费用贷应计负债。', report)


def test_different_source_rows_cannot_be_fused_into_one_received_expense(analysis, tmp_path):
    report, _ = report_for(analysis, tmp_path, [
        *e12_rows(transaction_id='A', service_direction='received'),
        *e12_rows(transaction_id='B', economic_nature='expense'),
    ])
    assert report['status'] == 'insufficient'
    assert recognition_claim_issues('借费用贷应计负债。', report)


def test_duplicate_long_form_keys_do_not_launder_source_conflicts(analysis, tmp_path):
    rows = [{'name': name, 'value': value} for name, value in e12_rows()[0].items()]
    rows += [{'name': 'service_direction', 'value': 'received'},
             {'name': 'service_direction', 'value': 'provided'},
             {'name': 'economic_nature', 'value': 'expense'}]
    report, _ = report_for(analysis, tmp_path, rows)
    assert report['status'] == 'insufficient'
    assert recognition_claim_issues('借费用贷应计负债。', report)


def test_another_dataset_and_snapshot_ceiling_cannot_supply_direction(analysis, tmp_path):
    report, source = report_for(analysis, tmp_path)
    outsider = dataset(analysis, tmp_path,
                       e12_rows(service_direction='received', economic_nature='expense'), 'other')
    limited = recognition_basis_report(analysis, {'ledger': source['id'], 'other': outsider['id']},
                                       allowed=[source['id']])
    assert limited['status'] == 'insufficient'
    assert limited['source_dataset_ids'] == [source['id']]
    assert recognition_claim_issues('借费用贷应计负债。', limited)
    assert outsider['id'] not in json.dumps(limited)
    assert recognition_claim_issues('借费用贷应计负债。', report)


def test_unrelated_sources_do_not_activate_service_completion_guard(analysis, tmp_path):
    report, _ = report_for(analysis, tmp_path, [{'revenue': '100', 'cost': '80'}])
    assert report['status'] == 'not_applicable'
    assert recognition_claim_issues('根据另有凭证提出借费用贷应付草案。', report) == []


def test_read_failure_cannot_turn_partial_explicit_source_into_complete_basis(analysis, tmp_path, monkeypatch):
    source = dataset(analysis, tmp_path, e12_rows(service_direction='received', economic_nature='expense'))
    original = analysis.read_dataset
    unavailable_id = 'unreadable-bound-source'

    def read(dataset_id):
        if dataset_id == unavailable_id:
            raise FoundryError('bound source integrity failed')
        return original(dataset_id)

    monkeypatch.setattr(analysis, 'read_dataset', read)
    bindings = {'explicit': source['id'], 'other': unavailable_id}
    report = recognition_basis_report(analysis, bindings)
    assert report['status'] == 'insufficient'
    assert report['unavailable_dataset_ids'] == [unavailable_id]
    assert report['sources'][0]['dataset_id'] == source['id']
    assert recognition_claim_issues('The expense was omitted.', report)
    assert recognition_claim_issues('应借费用贷应计负债。', report)
    assert recognition_claim_issues('是否存在费用漏记，需核实不可读取的源。', report) == []
    limited = recognition_basis_report(analysis, bindings, allowed={source['id']})
    assert limited['status'] == 'explicit_source_basis'
    assert limited['unavailable_dataset_ids'] == []
    assert unavailable_id not in json.dumps(limited)
    only_unavailable = recognition_basis_report(analysis, {'other': unavailable_id})
    assert only_unavailable['status'] == 'insufficient'
    assert recognition_claim_issues('应借费用贷应计负债。', only_unavailable)
