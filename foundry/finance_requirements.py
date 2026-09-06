"""Versioned task obligations, independent of the draft's chosen executions."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from foundry.analysis import _new, _safe_text, _hash
from foundry.errors import FoundryError
from foundry.locking import exclusive

ITEM_ID = re.compile(r'^[A-Za-z0-9_\-]{1,80}$')
COMPARISON_COMMON_SCOPE_KEYS = {
    'tenant_id', 'ledger', 'ledger_id', 'organization', 'organization_id', 'currency', 'unit'
}
SCOPE_CONTROL_KEYS = {
    'actual', 'actual_scope', 'baseline', 'baseline_scope', 'budget', 'budget_scope',
    'source', 'source_scope', 'comparison_scope',
    'baseline_period', 'comparison_period', 'period_baseline', 'baseline_scenario',
}
METRIC_LABELS = {
    'profit': ('profit', 'management_profit', '利润', '管理利润', '管理利润合计'),
    'revenue': ('revenue', '收入'), 'cost': ('cost', '成本'),
    'expense': ('expense', '费用'),
}


def latest_requirements(analysis):
    records = analysis._list('requirements')
    return records[-1] if records else None


def save_requirements(analysis, spec):
    if not isinstance(spec, dict):
        raise FoundryError('analysis requirements must be an object')
    question = _safe_text(spec.get('question'), 'requirements question', required=True, maximum=10000)
    scope = spec.get('scope', {})
    items = spec.get('items')
    bindings = spec.get('bindings', {})
    if not isinstance(scope, dict) or not isinstance(bindings, dict):
        raise FoundryError('requirements scope and bindings must be objects')
    if not isinstance(items, list) or len(items) > 100:
        raise FoundryError('requirements items must be an array of at most 100 items')
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ITEM_ID.fullmatch(item['id']):
            raise FoundryError('requirement item requires a stable id')
        if item['id'] in seen:
            raise FoundryError('requirement item ids must be unique')
        seen.add(item['id'])
        metric = _safe_text(item.get('metric'), 'requirement metric', required=True, maximum=200)
        dimensions = item.get('dimensions', {})
        if not isinstance(dimensions, dict) or not isinstance(item.get('requires_drilldown', False), bool):
            raise FoundryError('invalid requirement dimensions or drilldown flag')
        normalized.append({'id': item['id'], 'metric': metric,
                           'label': _safe_text(item.get('label', metric), 'requirement label', maximum=500),
                           'dimensions': dimensions,
                           'requires_drilldown': item.get('requires_drilldown', False)})
    with exclusive(analysis.task.lock_path, timeout=10):
        parent = latest_requirements(analysis)
        if parent and spec.get('parent_id') != parent['id']:
            raise FoundryError('requirements update must reference the latest version')
        if not parent and spec.get('parent_id'):
            raise FoundryError('requirements parent does not exist')
        removed = sorted(
            set((parent or {}).get('removed_item_ids', []))
            | ({item['id'] for item in (parent or {}).get('items', [])} - seen)
        )
        reason = _safe_text(spec.get('change_reason', ''), 'requirements change reason', maximum=2000)
        if removed and not reason.strip():
            raise FoundryError('removing requirements requires a change reason')
        record = _new(analysis.task, question=question, scope=scope, bindings=bindings, context_id=spec.get("context_id"),
                      items=normalized, parent_id=(parent or {}).get('id'),
                      removed_item_ids=removed, change_reason=reason,
                      content_hash=_hash({'question': question, 'scope': scope, 'items': normalized, 'bindings': bindings}))
        return analysis._write_locked(analysis._object_path('requirements', record['id']), record)


def _same_number(left, right):
    try:
        return Decimal(str(left)).is_finite() and Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return left == right and left is not None


def _bindings_match(required, run_bindings):
    if not required:
        return True
    if not isinstance(required, dict) or not isinstance(run_bindings, dict):
        return False
    if len(required) == 1:
        key, value = next(iter(required.items()))
        return run_bindings.get(key) == value or value in set(run_bindings.values())
    return all(run_bindings.get(key) == value for key, value in required.items())


def _scope_matches(run, row, scope):
    if not scope:
        return True
    expected = _comparison_scopes(scope)
    scopes = run.get('finance_scope', {})
    if isinstance(scopes, dict):
        actual_scope = row.get('actual_scope') if isinstance(row.get('actual_scope'), dict) else scopes.get('actual')
        baseline_scope = (
            row.get('baseline_scope') if isinstance(row.get('baseline_scope'), dict)
            else scopes.get('baseline') if isinstance(scopes.get('baseline'), dict)
            else scopes.get('budget')
        )
        source_scope = (
            row.get('source_scope') if isinstance(row.get('source_scope'), dict)
            else scopes.get('source')
        )
        if isinstance(actual_scope, dict) or isinstance(baseline_scope, dict):
            return (
                _scope_dict_matches(actual_scope, expected['actual'])
                and _scope_dict_matches(baseline_scope, expected['baseline'])
            )
        if isinstance(source_scope, dict):
            return _scope_dict_matches(source_scope, expected['source'])
    return _scope_dict_matches(row, expected['actual']) or (
        isinstance(scopes, dict) and _scope_dict_matches(scopes, expected['source'])
    )


def _comparison_scopes(scope):
    flat = {
        key: value for key, value in scope.items()
        if key not in SCOPE_CONTROL_KEYS and not isinstance(value, dict)
    }
    actual = _clean_scope(scope.get('actual') or scope.get('actual_scope') or {
        key: value for key, value in flat.items() if key != 'scenario'
    })
    baseline = _clean_scope(scope.get('baseline') or scope.get('baseline_scope') or scope.get('budget') or scope.get('budget_scope') or scope.get('comparison_scope') or {
        key: value for key, value in flat.items()
        if key in COMPARISON_COMMON_SCOPE_KEYS
    })
    baseline_period = scope.get('baseline_period', scope.get('comparison_period', scope.get('period_baseline')))
    if baseline_period is not None and 'period' not in baseline:
        baseline = {**baseline, 'period': baseline_period}
    baseline_scenario = scope.get('baseline_scenario')
    if baseline_scenario is not None and 'scenario' not in baseline:
        baseline = {**baseline, 'scenario': baseline_scenario}
    source = _clean_scope(scope.get('source') or scope.get('source_scope') or {
        key: value for key, value in flat.items() if key != 'scenario'
    })
    return {'actual': actual, 'baseline': baseline, 'source': source}


def _clean_scope(scope):
    if not isinstance(scope, dict):
        return {}
    return {
        key: value for key, value in scope.items()
        if value not in (None, '')
    }


def _scope_dict_matches(candidate, scope):
    return isinstance(candidate, dict) and all(candidate.get(k) == value for k, value in scope.items())


def _matches(item, row, column):
    if any(row.get(k) != value for k, value in item['dimensions'].items()):
        return False
    metric = item['metric']
    aliases = METRIC_LABELS.get(metric, (metric,))
    labels = [str(row.get(key, '')).lower() for key in ('metric', 'line', 'contribution_line', 'management_account')]
    if column == metric or column in {f'{alias}_{suffix}' for alias in aliases for suffix in ('variance','difference','contribution','change','impact')}:
        return True
    return any(alias.lower() in labels for alias in aliases) and column in {
        'contribution','profit_impact','amount_change','variance','difference','value','amount','open_amount',
    }


def _prepared_evidence(analysis, runs):
    from foundry.finance_explanations import prepare_explanation

    prepared = prepare_explanation(analysis, list(runs.values())) if runs else {'evidence_groups': []}
    member_map = {}
    for group in prepared.get('evidence_groups', []):
        if not isinstance(group, dict):
            continue
        for member in group.get('members', []):
            if not isinstance(member, dict):
                continue
            fact_id = member.get('fact_id')
            if not fact_id:
                continue
            member_map[(group.get('run_id'), member.get('row'), member.get('column'))] = {
                'group_id': group.get('id'),
                'group_type': group.get('group_type'),
                'group_status': group.get('status'),
                'closure_status': (group.get('closure') or {}).get('status'),
                'member_state': member.get('state'),
                'fact_id': fact_id,
            }
    return member_map


def _location_evidence_status(item, location, member):
    if not member:
        return 'pending', {}
    metadata = {
        'fact_id': member.get('fact_id'),
        'group_id': member.get('group_id'),
        'group_type': member.get('group_type'),
        'group_status': member.get('group_status'),
        'closure_status': member.get('closure_status'),
        'member_state': member.get('member_state'),
    }
    if member.get('member_state') == 'missing':
        return 'missing_data', metadata
    if member.get('member_state') == 'not_applicable':
        return 'not_applicable', metadata
    if member.get('closure_status') == 'unsupported' and item.get('metric') in {'profit', 'revenue', 'cost', 'expense'}:
        return 'not_applicable', metadata
    if member.get('group_status') == 'missing_data':
        return 'missing_data', metadata
    if member.get('group_status') in {'scope_mismatch', 'unit_mismatch', 'closure_mismatch'}:
        return 'missing_data', metadata
    if member.get('group_status') == 'unsupported' and item.get('metric') in {'profit', 'revenue', 'cost', 'expense'}:
        return 'not_applicable', metadata
    return 'answered', metadata


def check_requirements(analysis, spec):
    latest = latest_requirements(analysis)
    if not latest:
        return {'requirements_id': None, 'items': [], 'coverage': {'status': 'not_assessed'},
                'provenance': {'status': 'not_assessed'}, 'scope_changed': False,
                'original_requirements_completed': False}
    selected_id = spec.get('requirements_id') or latest['id']
    selected = analysis._get('requirements', selected_id)
    # Always check the current task obligations, even when an old draft is opened.
    runs = {r['id']: r for r in analysis._list('runs') if r.get('execution_status') == 'succeeded'}
    evidence = _prepared_evidence(analysis, runs)
    claimed = set()
    for claim in spec.get('claims', []):
        if not isinstance(claim, dict) or claim.get('basis') != 'calculation':
            continue
        run = runs.get(claim.get('run_id'))
        index = claim.get('row')
        if not run or run['id'] not in spec.get('run_ids', []) or isinstance(index, bool) or not isinstance(index, int) or index < 0:
            continue
        rows = run.get('result', {}).get('rows', [])
        if index < len(rows) and claim.get('column') in rows[index] and _same_number(rows[index][claim['column']], claim.get('value')):
            claimed.add((run['id'], index, claim['column']))
    checks = analysis._list('evidence_checks')
    source_failures = _source_read_failures(spec.get('source_read_failures', []))
    items = []
    for item in latest['items']:
        locations = []
        statuses = []
        for run_id, index, column in claimed:
            run = runs[run_id]
            if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
                continue
            row = run['result']['rows'][index]
            if _matches(item, row, column) and _scope_matches(run, row, latest['scope']):
                location = {'run_id': run_id, 'row': index, 'column': column, 'output_hash': run.get('output_hash')}
                status, metadata = _location_evidence_status(
                    item, location, evidence.get((run_id, index, column))
                )
                locations.append({**location, 'evidence': metadata, 'status': status})
                statuses.append(status)
        item_status = _item_status(statuses)
        failed_source = item['id'] in source_failures
        sourced = (
            item_status == 'answered'
            and not failed_source
            and any(_source_verified(location, checks) for location in locations)
        )
        provenance_status = 'not_requested'
        if item['requires_drilldown']:
            provenance_status = 'verified' if sourced else 'failed' if failed_source else 'pending'
        items.append({**item, 'status': item_status, 'locations': locations,
                      'source_read_failure': source_failures.get(item['id']),
                      'provenance_status': provenance_status})
    scope_changed = selected['id'] != latest['id']
    complete = all(item['status'] == 'answered' for item in items) and not scope_changed
    trace_complete = all(item['provenance_status'] in {'verified', 'not_requested'} for item in items)
    return {'requirements_id': latest['id'], 'draft_requirements_id': selected['id'],
            'items': items, 'scope_changed': scope_changed,
            'coverage': {'status': 'pass' if complete else 'needs_attention'},
            'provenance': {'status': 'pass' if trace_complete else 'needs_attention'},
            'original_requirements_completed': complete and not latest.get('removed_item_ids')}


def _item_status(statuses):
    if not statuses:
        return 'pending'
    if 'answered' in statuses:
        return 'answered'
    if 'missing_data' in statuses:
        return 'missing_data'
    if 'not_applicable' in statuses:
        return 'not_applicable'
    return 'pending'


def _source_read_failures(failures):
    if not isinstance(failures, list):
        return {}
    indexed = {}
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        item_id = failure.get('requirement_item_id') or failure.get('item_id')
        if isinstance(item_id, str):
            indexed[item_id] = failure
    return indexed


def _source_verified(location, checks):
    base = {key: location[key] for key in ('run_id', 'row', 'column', 'output_hash')}
    matching = [
        check for check in checks
        if check.get('status') == 'verified'
        and _location_matches(check.get('location'), base)
    ]
    if not matching:
        return False
    if any(not _has_paging_metadata(check) for check in matching):
        return True
    totals = {check.get('total') for check in matching if isinstance(check.get('total'), int)}
    if len(totals) != 1:
        return False
    total = totals.pop()
    if total < 0:
        return False
    intervals = sorted(
        (check.get('offset'), check.get('offset') + check.get('read_count'))
        for check in matching
        if (
            isinstance(check.get('offset'), int)
            and isinstance(check.get('read_count'), int)
            and check.get('offset') >= 0
            and check.get('read_count') >= 0
        )
    )
    cursor = 0
    for start, end in intervals:
        if start > cursor:
            return False
        cursor = max(cursor, end)
        if cursor >= total:
            break
    return cursor >= total and any(check.get('has_more') is False for check in matching)


def _has_paging_metadata(check):
    return all(key in check for key in ('total', 'offset', 'read_count', 'has_more'))


def _location_matches(candidate, expected):
    return isinstance(candidate, dict) and all(candidate.get(key) == value for key, value in expected.items())


def augment_quality(analysis, spec, quality):
    requirements = check_requirements(analysis, spec)
    issues = list(quality.get('issues', []))
    if requirements['scope_changed']:
        issues.append({'code': 'requirements_changed', 'severity': 'warning', 'message': '分析范围已更新，请按当前要求复核文稿。'})
    for item in requirements['items']:
        if item['status'] != 'answered':
            issues.append({'code': 'requirement_unanswered', 'severity': 'warning', 'message': f'尚未提供“{item["label"]}”的计算依据。', 'requirement_item_id': item['id']})
        if item['provenance_status'] in {'pending', 'failed'}:
            issues.append({'code': 'requested_source_missing', 'severity': 'warning', 'message': f'尚未完成“{item["label"]}”的指定来源核查。', 'requirement_item_id': item['id']})
    return {**quality, 'issues': issues, 'status': 'needs_attention' if issues else quality['status'],
            'requirements': requirements,
            'checks': {'numbers': {'status': quality['status']}, 'coverage': requirements['coverage'], 'provenance': requirements['provenance']}}
