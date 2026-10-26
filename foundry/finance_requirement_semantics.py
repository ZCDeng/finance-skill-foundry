"""Conservative, server-authored equivalence proofs for requirement revisions."""
from __future__ import annotations

from foundry.analysis import _hash
from foundry.errors import FoundryError
from foundry.finance_requirement_support import canonical_dimensions, canonical_metric

SEMANTIC_VERSION = 1


def requirement_semantics(analysis, record):
    """Fingerprint executable requirements, never a caller's equivalence claim."""
    sources = {}
    try:
        for alias, dataset_id in record.get('bindings', {}).items():
            dataset = analysis.read_dataset(dataset_id)
            sources[alias] = {'dataset_id': dataset_id, 'source_hash': dataset['source_hash'],
                              'data_hash': dataset['data_hash']}
    except (FoundryError, OSError, ValueError, KeyError, TypeError):
        return {'semantic_version': SEMANTIC_VERSION, 'semantic_basis': None,
                'semantic_fingerprint': None}
    if not sources:
        return {'semantic_version': SEMANTIC_VERSION, 'semantic_basis': None,
                'semantic_fingerprint': None}
    basis = {
        'version': SEMANTIC_VERSION,
        'question': record.get('question'),
        'context_id': record.get('context_id'),
        'scope': record.get('scope', {}),
        'sources': sources,
        'removed_item_ids': sorted(record.get('removed_item_ids', [])),
        'items': sorted([{
            'id': item['id'], 'metric': canonical_metric(item['metric']),
            'dimensions': canonical_dimensions(item.get('dimensions', {})),
            'periods': sorted(set(item.get('periods', []))),
            'requires_drilldown': item.get('requires_drilldown', False),
            **({'organizations': sorted(set(item['organizations']))} if item.get('organizations') else {}),
            **({'scenarios': sorted(set(item['scenarios']))} if item.get('scenarios') else {}),
            # Declaring a grain as estimate or unavailable changes what can answer it.
            **({'grain_basis': item['grain_basis']} if item.get('grain_basis') else {}),
        } for item in record.get('items', [])], key=lambda item: item['id']),
    }
    from foundry.finance_professional import requirement_rule_identity
    identity = requirement_rule_identity(analysis, record, historical=bool(record.get('seq')))
    version = 2 if identity else SEMANTIC_VERSION
    if identity:
        basis.update(version=version, professional_identity=identity)
    return {'semantic_version': version, 'semantic_basis': basis,
            'semantic_fingerprint': _hash(basis)}


def verified_requirement_fingerprint(analysis, record):
    if not record or record.get('semantic_version') not in {1, 2}:
        return None
    computed = requirement_semantics(analysis, record)
    from foundry.finance_professional import valid_rule_identity
    identity = (computed.get('semantic_basis') or {}).get('professional_identity')
    if identity and not valid_rule_identity(identity):
        return None
    fingerprint = computed['semantic_fingerprint']
    return fingerprint if (fingerprint and record.get('semantic_fingerprint') == fingerprint
                           and record.get('semantic_basis') == computed['semantic_basis']) else None


def capture_requirements(analysis, authorize=None, *, allowed=None):
    """Capture at execution start so a concurrent revision cannot relabel a run. A session (``allowed``, its snapshot
    ceiling) captures the newest version it may read, as it reads its current one, with the fingerprint it reads it
    with (AnalysisStore.fingerprint_in_view); the manager the latest."""
    from foundry.finance_requirements import latest_requirements
    record = latest_requirements(analysis, allowed)
    if record and authorize is not None:
        try:
            authorize(record.get('bindings', {}))
        except FoundryError:
            record = None
    from foundry.finance_professional import validate_requirement_identity, valid_rule_identity
    identity = validate_requirement_identity(analysis, record, allowed=allowed) if record else None
    if identity and (not valid_rule_identity((record.get('semantic_basis') or {}).get('professional_identity'))
                     or not verified_requirement_fingerprint(analysis, record)):
        raise FoundryError('professional_identity_invalid: revise the original requirements with their real context '
                           'and complete required_bindings before recalculating; historical records stay unchanged')
    return {'requirements_id': record['id'] if record else None,
            'requirements_semantic_fingerprint': analysis.fingerprint_in_view(record, allowed),
            **({'requirements_rule_identity': identity} if identity else {})}


def run_has_equivalent_requirements(analysis, run, current, *, allowed=None, cache=None):
    """Whether ``run``, captured under an older version, answers what ``current`` asks. A session (``allowed``, its
    snapshot ceiling; None: the manager) compares the fingerprints it reads the versions with
    (AnalysisStore.fingerprint_in_view; ``cache`` as for AnalysisStore.run_in_view)."""
    fingerprint = analysis.fingerprint_in_view(current, allowed, cache=cache)
    if not fingerprint or run.get('requirements_semantic_fingerprint') != fingerprint:
        return False
    try:
        original = analysis._get('requirements', run['requirements_id'])
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return False
    if original.get('seq', -1) >= run.get('seq', -1):
        return False
    if analysis.fingerprint_in_view(original, allowed, cache=cache) != fingerprint:
        return False
    if run.get('bindings', {}) != original.get('bindings', {}):
        return False
    # A run's own immutable data binding must agree with the captured inputs.
    for alias, source in original['semantic_basis']['sources'].items():
        if (run.get('bindings', {}).get(alias) != source['dataset_id']
                or run.get('input_hashes', {}).get(alias) != source['data_hash']
                or run.get('source_hashes', {}).get(alias) != source['source_hash']):
            return False
    return True
