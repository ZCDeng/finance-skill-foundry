"""Explicit closure-check declarations cannot be filled in by an automatic appendix."""
from copy import deepcopy

import pytest

from foundry.errors import FoundryError
from test_finance_m05_completion_closure import source_bound_case


def request(requirement, run, facts, *, omit=False):
    selected = [fact for fact in facts if not omit or fact['column'] != 'residual']
    return {
        'requirements_id': requirement['id'], 'run_ids': [run['id']],
        'body': '\n'.join(fact['column'] + ': {{fact:' + fact['id'] + '}}' for fact in selected),
        'claims': [{key: value for key, value in fact['reference_template']['claim'].items()}
                   for fact in selected],
    }


def test_manual_omission_survives_appendix_validation_and_receipt_replay(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    good = service.save_explanation_draft(request(requirement, run, facts))
    assert good['completion']['status'] == 'complete'
    bad_request = request(requirement, run, facts, omit=True)
    bad = service.save_explanation_draft(bad_request)
    assert '## 计算依据' in bad['body']
    assert 'residual' in bad['evidence_appendix']
    assert any(issue['code'] == 'missing_required_fact' for issue in bad['quality']['issues'])
    assert bad['completion']['status'] != 'complete'
    assert bad['completion']['original_requirements_completed'] is False
    check = service.validate_explanation({'draft_id': bad['id']})
    assert any(issue['code'] == 'missing_required_fact' for issue in check['issues'])
    replay = service.save_explanation_draft(bad_request)
    assert replay['id'] == bad['id']
    assert replay['completion']['id'] == bad['completion']['id']
    original = service.analysis._object_path('drafts', bad['id']).read_bytes()
    fixed = service.save_explanation_draft({**request(requirement, run, facts), 'parent_id': bad['id']})
    assert fixed['completion']['status'] == 'complete'
    assert service.analysis._object_path('drafts', bad['id']).read_bytes() == original


def test_appendix_only_and_canonical_template_still_complete(tmp_path):
    service, requirement, run, _, _ = source_bound_case(tmp_path)
    appendix = service.save_explanation_draft({
        'requirements_id': requirement['id'], 'run_ids': [run['id']],
        'body': '量结构价贡献及闭合核对见计算依据。',
    })
    assert appendix['completion']['status'] == 'complete'
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    template = service.save_explanation_draft(prepared['save_template_spec'])
    assert template['completion']['status'] == 'complete'


@pytest.mark.parametrize('selection', ['fact_ids', 'body_tokens'])
@pytest.mark.parametrize('omit', [False, True])
def test_explicit_fact_selection_preserves_author_check_coverage(tmp_path, selection, omit):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    selected = [fact for fact in facts if not omit or fact['column'] != 'residual']
    spec = {'requirements_id': requirement['id'], 'run_ids': [run['id']]}
    if selection == 'fact_ids':
        spec.update(body='量结构价贡献及闭合核对见计算依据。',
                    fact_ids=[fact['id'] for fact in selected])
    else:
        spec['body'] = '\n'.join(fact['column'] + ': {{fact:' + fact['id'] + '}}' for fact in selected)
    draft = service.save_explanation_draft(spec)
    assert 'residual' in draft['evidence_appendix']
    validation = service.validate_explanation({'draft_id': draft['id']})
    if omit:
        assert any(issue['code'] == 'missing_required_fact' for issue in validation['issues'])
        assert draft['completion']['status'] != 'complete'
        for save in (service.save_explanation_draft, service.analysis.save_draft):
            revised = save({'parent_id': draft['id'], 'title': '保留作者选择'})
            assert any(issue['code'] == 'missing_required_fact' for issue in revised['quality']['issues'])
    else:
        assert validation['status'] == 'pass'
        assert draft['completion']['status'] == 'complete'
        omitted = {**spec, 'parent_id': draft['id']}
        residual = next(fact for fact in facts if fact['column'] == 'residual')
        if selection == 'fact_ids':
            omitted['fact_ids'] = [fact_id for fact_id in spec['fact_ids'] if fact_id != residual['id']]
        else:
            omitted['body'] = '\n'.join(line for line in spec['body'].splitlines() if not line.startswith('residual:'))
        revised = service.save_explanation_draft(omitted)
        assert any(issue['code'] == 'missing_required_fact' for issue in revised['quality']['issues'])
        assert revised['completion']['status'] != 'complete'
        if selection == 'fact_ids':
            direct = service.analysis.save_draft(omitted)
            assert any(issue['code'] == 'missing_required_fact' for issue in direct['quality']['issues'])


def test_explicit_residual_token_is_an_authored_check(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    spec = request(requirement, run, facts, omit=True)
    residual = next(f for f in facts if f['column'] == 'residual')
    spec['body'] += '\n闭合余差：{{fact:' + residual['id'] + '}}'
    assert service.save_explanation_draft(spec)['completion']['status'] == 'complete'


def test_duplicate_claims_do_not_stand_in_for_missing_check(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    spec = request(requirement, run, facts, omit=True)
    spec['claims'] += deepcopy(spec['claims'])
    result = service.save_explanation_draft(spec)
    assert result['completion']['status'] != 'complete'
    assert any(issue['code'] == 'missing_required_fact' for issue in result['quality']['issues'])


@pytest.mark.parametrize('field,value', [('value', '99'), ('fact_id', '0' * 64)])
def test_forged_check_cannot_become_complete(tmp_path, field, value):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    spec = request(requirement, run, facts)
    next(c for c in spec['claims'] if c['column'] == 'residual')[field] = value
    try:
        draft = service.save_explanation_draft(spec)
    except FoundryError:
        return
    assert draft['completion']['status'] != 'complete'


def test_public_payload_cannot_confer_required_check_authority(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    spec = request(requirement, run, facts, omit=True)
    spec['required_check_authorship'] = {
        'schema_version': 1, 'run_output_hashes': {run['id']: run['output_hash']},
        'required_fact_ids': [], 'authored_fact_ids': [f['id'] for f in facts],
    }
    for save in (service.save_explanation_draft, service.analysis.save_draft):
        with pytest.raises(FoundryError, match='authorship'):
            save(spec)
    with pytest.raises(FoundryError, match='authorship'):
        service.validate_explanation(spec)


def test_plain_revision_cannot_launder_generated_check_into_authorship(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    bad = service.save_explanation_draft(request(requirement, run, facts, omit=True))
    for save in (service.save_explanation_draft, service.analysis.save_draft):
        edited = save({'parent_id': bad['id'], 'title': '只修改标题'})
        assert edited['quality']['status'] == 'needs_attention'
        assert any(issue['code'] == 'missing_required_fact' for issue in edited['quality']['issues'])


def test_saved_authorship_is_bound_to_its_runs(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    draft = service.save_explanation_draft(request(requirement, run, facts))
    with pytest.raises(FoundryError, match='authorship'):
        service.validate_explanation({'draft_id': draft['id'], 'run_ids': [], 'claims': [], 'fact_ids': []})


def test_legacy_draft_without_authorship_keeps_its_saved_contract(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    from test_finance_m05_completion_closure import authoring_spec
    legacy = service.analysis.save_draft(authoring_spec(requirement, run, facts))
    assert 'required_check_authorship' not in legacy
    path = service.analysis._object_path('drafts', legacy['id'])
    before = path.read_bytes()
    assert service.validate_explanation({'draft_id': legacy['id']})['status'] == 'pass'
    assert service.save_explanation_draft({'draft_id': legacy['id']})['completion']['status'] == 'complete'
    assert path.read_bytes() == before


def test_clearing_claims_on_a_revision_does_not_erase_missing_check(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    bad = service.save_explanation_draft(request(requirement, run, facts, omit=True))
    for save in (service.save_explanation_draft, service.analysis.save_draft):
        edited = save({'parent_id': bad['id'], 'claims': []})
        assert edited['quality']['status'] == 'needs_attention'
        assert any(issue['code'] == 'missing_required_fact' for issue in edited['quality']['issues'])
