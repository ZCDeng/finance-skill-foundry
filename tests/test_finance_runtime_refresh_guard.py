"""Runtime saves reject the ordinary transaction-refresh shape before mutation."""
import pytest

from foundry.errors import FoundryError
from foundry.finance_completion_operations import CompletionOperationStore
from foundry.finance_service import FinanceStore
from test_finance_completion_fingerprint import ratio_case
from test_finance_saved_delivery import ratio_spec
from test_finance_statement_draft_template import statement as _statement_fixture


statement = _statement_fixture


def runtime_for(service, context):
    session_id = 'runtime-refresh-guard'
    snapshots = list(context['bindings'].values())
    service.task.record_session(session_id, role='analysis')
    service.task.update_session_context(session_id, snapshot_ids=snapshots)
    runtime = FinanceStore(service.task, snapshot_ids=snapshots, session_id=session_id)
    operations = CompletionOperationStore(service.task, session_id, snapshot_ids=snapshots)
    operation = operations.begin('runtime-refresh-guard')
    return runtime, operations, operation


def records(service):
    return {str(path.relative_to(service.analysis.root)): path.read_bytes()
            for path in service.analysis.root.rglob('*.json')}


@pytest.mark.parametrize('shape', ['known', 'unknown', 'mixed', 'empty', 'null'])
def test_runtime_draft_id_is_rejected_before_reserving_or_writing(tmp_path, shape):
    service, _, run, context = ratio_case(tmp_path)
    spec = ratio_spec(service, run)
    saved = service.save_explanation_draft(spec)
    runtime, operations, operation = runtime_for(service, context)
    request = {'draft_id': {'unknown': 'f' * 32, 'empty': '', 'null': None}.get(shape, saved['id'])}
    if shape == 'mixed':
        request.update(spec)
    before = records(service)
    with pytest.raises(FoundryError, match='draft_id.*runtime'):
        runtime.save_completion_draft(operation['id'], 'attempt-refresh', request)
    assert records(service) == before
    assert operations.get(operation['id'])['revisions'] == []


def test_runtime_full_save_after_rejected_refresh_still_uses_the_first_attempt(tmp_path):
    service, _, run, context = ratio_case(tmp_path)
    runtime, operations, operation = runtime_for(service, context)
    with pytest.raises(FoundryError, match='draft_id.*runtime'):
        runtime.save_completion_draft(operation['id'], 'same-call', {'draft_id': 'f' * 32})
    saved = runtime.save_completion_draft(operation['id'], 'same-call', ratio_spec(service, run))
    assert saved['run_ids'] == [run['id']]
    assert saved['completion']['status'] == 'complete'
    revisions = operations.get(operation['id'])['revisions']
    assert len(revisions) == 1 and revisions[0]['revision'] == 1
    assert revisions[0]['draft_id'] == saved['id']


def test_runtime_prepared_short_save_is_not_a_draft_refresh(statement):
    service, context, _, _, run, prepared = statement
    runtime, operations, operation = runtime_for(service, context)
    spec = prepared['save_template_spec']
    assert 'draft_id' not in spec
    saved = runtime.save_completion_draft(operation['id'], 'save-template', spec)
    assert saved['run_ids'] == [run['id']]
    assert saved['completion']['status'] == 'complete'
    assert operations.get(operation['id'])['revisions'][0]['draft_id'] == saved['id']
