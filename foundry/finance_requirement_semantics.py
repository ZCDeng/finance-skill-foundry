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
    return {'semantic_version': SEMANTIC_VERSION, 'semantic_basis': basis,
            'semantic_fingerprint': _hash(basis)}


def verified_requirement_fingerprint(analysis, record):
    if not record or record.get('semantic_version') != SEMANTIC_VERSION:
        return None
    computed = requirement_semantics(analysis, record)
    fingerprint = computed['semantic_fingerprint']
    return fingerprint if (fingerprint and record.get('semantic_fingerprint') == fingerprint
                           and record.get('semantic_basis') == computed['semantic_basis']) else None


def capture_requirements(analysis, authorize=None):
    """Capture at execution start so a concurrent revision cannot relabel a run."""
    from foundry.finance_requirements import latest_requirements
    record = latest_requirements(analysis)
    if record and authorize is not None:
        try:
            authorize(record.get('bindings', {}))
        except FoundryError:
            record = None
    return {'requirements_id': record['id'] if record else None,
            'requirements_semantic_fingerprint': verified_requirement_fingerprint(analysis, record)}


def run_has_equivalent_requirements(analysis, run, current):
    fingerprint = verified_requirement_fingerprint(analysis, current)
    if not fingerprint or run.get('requirements_semantic_fingerprint') != fingerprint:
        return False
    try:
        original = analysis._get('requirements', run['requirements_id'])
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return False
    if original.get('seq', -1) >= run.get('seq', -1):
        return False
    if verified_requirement_fingerprint(analysis, original) != fingerprint:
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
