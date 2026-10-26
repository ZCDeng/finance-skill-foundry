"""Display labels match only a current source-recomputed aging result."""
from copy import deepcopy
import json

import pytest

from foundry.analysis import _hash
from foundry.finance_requirements import _dimensions_match, check_requirements
from test_finance_native_drafts import native_case, native_result


def _claims(case):
    _, _, requirement, run, prepared = case
    return {'requirements_id': requirement['id'], 'run_ids': [run['id']], 'claims': [
        {'basis': 'calculation', 'run_id': run['id'], 'row': fact['row'],
         'column': fact['column'], 'value': fact['value']} for fact in prepared['facts']]}


def test_current_source_bound_label_matches_canonical_bucket_and_native_nested_check(tmp_path):
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={'bucket': '31-60天'})
    service, _, requirement, run, _ = case
    assert any(row['bucket'] == '31-60' and row['bucket_label'] == '31-60天' for row in run['result']['rows'])
    result = check_requirements(service.analysis, _claims(case))
    assert result['items'][0]['status'] == 'answered'
    template = native_result(case)['draft_template']
    assert template is not None
    saved = service.save_explanation_draft(template)
    assert saved['requirements_id'] == requirement['id']
    assert saved['completion']['status'] == 'complete', saved['quality']['issues']


@pytest.mark.parametrize('engine', ['python', 'finance'])
def test_caller_label_and_matching_json_hash_are_not_a_verified_alias(tmp_path, engine):
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={'bucket': '31-60天'})
    _, _, requirement, run, _ = case
    copied = deepcopy(run)
    copied['engine'] = engine
    copied['output_hash'] = _hash(copied['result'])
    row = next(row for row in copied['result']['rows'] if row['bucket'] == '31-60')
    assert not _dimensions_match(requirement['items'][0], row, copied)


def test_changed_persisted_bucket_label_cannot_self_authorize_an_alias(tmp_path):
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={'bucket': '31-60天'})
    service, _, _, run, _ = case
    changed = deepcopy(run)
    changed['result']['rows'][0]['bucket_label'] = '31-60天'
    changed['output_hash'] = _hash(changed['result'])
    changed.pop('_integrity_hash')
    changed['_integrity_hash'] = _hash(changed)
    service.analysis._object_path('runs', run['id']).write_text(json.dumps(changed))
    checked = check_requirements(service.analysis, _claims(case))
    assert checked['items'][0]['status'] == 'pending'
    assert native_result(case)['draft_template'] is None
