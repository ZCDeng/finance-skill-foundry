"""Public seeding boundaries for the independent frozen supplement."""
from copy import deepcopy
import json

import pytest

from tools import finance_supplement_cases as helper


def test_frozen_suite_has_three_independent_cases_and_exact_public_projection():
    suite = helper.load_suite(helper.DEFAULT_FIXTURES)
    assert len(suite['cases']) == 3
    for case in suite['cases']:
        public = helper.case_public({**case, 'oracle': {'private_sentinel': 'NEVER_SEED'}})
        assert 'NEVER_SEED' not in json.dumps(public)
        assert set(public) == {'id', 'question', 'datasets', 'attachments', 'runnable'}
        assert len(public['datasets']) == 3
        request = helper.request_from_public(public)
        assert request['case_id'] == case['case_id']
        assert len(request['required_metrics']) == 13
        specs = helper.precondition_specs(public, {d['name']: 'id-' + d['name'] for d in public['datasets']})
        assert len(specs['scenario_inputs']['source_bindings']) == 24
        assert specs['context']['reporting_profile'] == request['reporting_profile']


def test_loader_rejects_changed_frozen_artifact(tmp_path):
    import shutil
    shutil.copytree(helper.DEFAULT_FIXTURES, tmp_path / 'suite')
    path = next((tmp_path / 'suite/public').glob('*/template_inputs.json'))
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='hash'):
        helper.load_suite(tmp_path / 'suite')


def test_public_request_is_explicit_and_cannot_be_replaced_by_private_controller_data():
    public = helper.case_public(helper.load_suite(helper.DEFAULT_FIXTURES)['cases'][0])
    bad = deepcopy(public)
    bad['attachments'][0]['text'] = json.dumps({'oracle': {'closing_cash': '192'}})
    with pytest.raises(ValueError):
        helper.request_from_public(bad)


@pytest.mark.parametrize('collection', ['runs', 'requirements', 'drafts', 'completions'])
def test_seed_refuses_preexisting_answer_artifacts(collection):
    state = {name: [] for name in helper.EMPTY_COLLECTIONS}
    state[collection] = [{'id': 'precomputed'}]
    with pytest.raises(ValueError, match='preexisting'):
        helper.empty_counts(state)


def test_missing_collection_is_not_proof_of_zero_seed_artifacts():
    with pytest.raises(ValueError, match='missing'):
        helper.empty_counts({})


def test_binding_identity_and_explicit_period_are_preserved():
    public = helper.case_public(helper.load_suite(helper.DEFAULT_FIXTURES)['cases'][0])
    specs = helper.precondition_specs(public, {d['name']: 'id-' + d['name'] for d in public['datasets']})
    bindings = specs['scenario_inputs']['source_bindings']
    assert bindings['opening_cash']['period'] == '2026-09'
    assert bindings['revenue']['period'] == '2026-10'
    assert bindings['revenue']['scope'] == {'organization': 'Supplement Fixture Co', 'ledger': 'supplement-ledger-01', 'scenario': 'management-forecast'}


def test_seed_precondition_signature_cannot_accept_an_oracle():
    import inspect
    assert list(inspect.signature(helper.prepare_preconditions).parameters) == [
        'foundry', 'var', 'task', 'output', 'publiccase', 'dataset_ids']
