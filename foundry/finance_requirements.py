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
PRICE_QUANTITY_METHODS = {'quantity_then_price', 'base_weights_with_interaction'}
PRICE_QUANTITY_REQUIRED_COLUMNS = (
    'total_variance', 'quantity_contribution', 'price_contribution', 'interaction'
)
RESULT_SET_METRICS = {'control_totals'}
INTENT_DIMENSION_KEYS = {'dimension', 'scenario_compare'}
PROFIT_BRIDGE_REQUIRED_LINES = ('revenue', 'cost', 'expense', 'profit')
CONTROL_TOTAL_COMPARISON_GRAIN_KEYS = (
    'ledger', 'ledger_id', 'organization', 'organization_id', 'period', 'currency', 'unit',
    'management_account', 'account_id', 'account_code',
)


def _canonical_metric_name(metric):
    from foundry.finance_requirement_support import canonical_metric
    return canonical_metric(metric)


def _canonical_method_name(method):
    from foundry.finance_requirement_support import canonical_method
    return canonical_method(method)


def _assess_requirement_support(analysis, spec):
    from foundry.finance_requirement_support import assess_requirement_support
    return assess_requirement_support(analysis, spec)


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
        periods = item.get('periods', [])
        if not isinstance(dimensions, dict) or not isinstance(item.get('requires_drilldown', False), bool):
            raise FoundryError('invalid requirement dimensions or drilldown flag')
        if isinstance(dimensions.get('period'), (list, tuple, set, frozenset, dict)):
            raise FoundryError('requirement dimensions.period must be a scalar; use periods for a set')
        if periods in (None, ''):
            periods = []
        if (
            not isinstance(periods, list)
            or len(periods) > 120
            or any(not isinstance(period, str) or not period.strip() for period in periods)
        ):
            raise FoundryError('requirement periods must be an array of non-empty strings')
        from foundry.finance_requirement_support import canonical_dimensions
        normalized_item = {'id': item['id'], 'metric': metric,
                           'label': _safe_text(item.get('label', metric), 'requirement label', maximum=500),
                           'dimensions': canonical_dimensions(dimensions),
                           'requires_drilldown': item.get('requires_drilldown', False)}
        if periods:
            normalized_item['periods'] = list(dict.fromkeys(periods))
        normalized.append(normalized_item)
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
        assessed_spec = {**spec, 'question': question, 'scope': scope, 'items': normalized, 'bindings': bindings}
        from foundry.finance_requirement_semantics import requirement_semantics
        semantics = requirement_semantics(analysis, {**assessed_spec, 'removed_item_ids': removed})
        record = _new(analysis.task, **semantics, question=question, scope=scope, bindings=bindings, context_id=spec.get("context_id"),
                      items=normalized, parent_id=(parent or {}).get('id'),
                      removed_item_ids=removed, change_reason=reason,
                      support=_assess_requirement_support(analysis, assessed_spec),
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
            actual_candidate = _merge_scope_with_row(actual_scope, row, expected['actual'])
            baseline_candidate = _merge_scope_with_row(baseline_scope, row, expected['baseline'])
            baseline_matches = (
                _scope_dict_matches(baseline_candidate, expected['baseline'])
                if expected['baseline'] or isinstance(baseline_scope, dict)
                else True
            )
            return (
                _scope_dict_matches(actual_candidate, expected['actual'])
                and baseline_matches
            )
        if isinstance(source_scope, dict):
            return _scope_dict_matches(_merge_scope_with_row(source_scope, row, expected['source']), expected['source'])
        bound_scopes = [scope for scope in scopes.values() if isinstance(scope, dict)]
        if bound_scopes:
            return _bound_scopes_match(bound_scopes, expected, row)
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


def _merge_scope_with_row(scope, row, expected):
    if not isinstance(scope, dict):
        return scope
    merged = dict(scope)
    for key in expected:
        row_value = row.get(key)
        if row_value in (None, ''):
            continue
        if key in merged and merged[key] != row_value:
            return {}
        merged.setdefault(key, row_value)
    return merged


def _bound_scopes_match(candidates, expected, row=None):
    if len(candidates) != 1:
        return False
    candidate = _merge_scope_with_row(candidates[0], row or {}, expected['actual'])
    if not _scope_dict_matches(candidate, expected['actual']):
        return False
    baseline_scope = expected['baseline']
    if baseline_scope and not _scope_dict_matches(candidates[0], baseline_scope):
        return False
    source_scope = expected['source']
    return not source_scope or _scope_dict_matches(candidate, source_scope)


def _matches(item, row, column, run=None):
    if not _dimensions_match(item, row, run or {}):
        return False
    metric = _canonical_metric_name(item['metric'])
    aliases = METRIC_LABELS.get(metric, (metric,))
    labels = [str(row.get(key, '')).lower() for key in ('metric', 'line', 'contribution_line', 'management_account')]
    if column == metric or column in {f'{alias}_{suffix}' for alias in aliases for suffix in ('variance','difference','contribution','change','impact')}:
        return True
    return any(alias.lower() in labels for alias in aliases) and column in {
        'contribution','profit_impact','amount_change','variance','difference','value','amount','open_amount',
    }


def _run_method(run):
    return _canonical_method_name(run.get('result', {}).get('method') or run.get('method'))


def _dimensions_match(item, row, run=None):
    dimensions = item.get('dimensions', {})
    if not isinstance(dimensions, dict):
        return False
    method = _canonical_method_name(dimensions.get('method'))
    if method is not None and _run_method(run or {}) != method:
        return False
    for key, value in dimensions.items():
        if key in {'method', *INTENT_DIMENSION_KEYS}:
            continue
        if row.get(key) != value:
            return False
    if 'scenario_compare' in dimensions and not _scenario_compare_matches(dimensions['scenario_compare'], row, run or {}):
        return False
    if 'dimension' in dimensions and not _dimension_intent_matches(dimensions['dimension'], row, run or {}):
        return False
    return True


def _scenario_compare_matches(value, row, run):
    if value != 'actual_vs_budget':
        return False
    result = run.get('result', {}) if isinstance(run, dict) else {}
    if result.get('metric_id') == 'control_totals':
        return _control_totals_actual_budget_pairs_complete(
            [(index, item) for index, item in enumerate(result.get('rows', [])) if isinstance(item, dict)]
        )
    scopes = run.get('finance_scope', {}) if isinstance(run, dict) else {}
    actual_scope = row.get('actual_scope') if isinstance(row.get('actual_scope'), dict) else scopes.get('actual')
    baseline_scope = row.get('baseline_scope') if isinstance(row.get('baseline_scope'), dict) else scopes.get('baseline') or scopes.get('budget')
    actual_scenario = actual_scope.get('scenario') if isinstance(actual_scope, dict) else row.get('actual_scenario')
    baseline_scenario = baseline_scope.get('scenario') if isinstance(baseline_scope, dict) else row.get('baseline_scenario')
    return actual_scenario == 'actual' and baseline_scenario == 'budget'


def _dimension_intent_matches(value, row, run):
    if value != 'management_account':
        return False
    if row.get('management_account') is not None:
        return True
    if _run_method(run) == 'revenue_minus_cost_minus_expense' and row.get('metric') in set(METRIC_LABELS):
        return True
    return False


def _run_finance_metric(analysis, run):
    if run.get('engine') != 'finance':
        return None
    result = run.get('result', {})
    if not isinstance(result, dict) or result.get('metric_id') not in {'account_total', 'control_totals'}:
        return None
    analysis_id = run.get('analysis_id')
    if not analysis_id:
        return None
    try:
        revision = analysis.get_analysis(analysis_id)
    except FoundryError:
        return None
    if (
        revision.get('engine') != 'finance'
        or revision.get('operation') != 'metric'
        or revision.get('finance_context_id') != run.get('finance_context_id')
        or revision.get('bindings') != run.get('bindings')
    ):
        return None
    spec = revision.get('finance_spec', {})
    if not isinstance(spec, dict):
        return None
    metric = spec.get('metric')
    if not isinstance(metric, dict) or metric.get('kind') != result.get('metric_id'):
        return None
    return metric


def _prepared_evidence(analysis, runs):
    from foundry.finance_explanations import prepare_explanation

    prepared = prepare_explanation(analysis, list(runs.values())) if runs else {'evidence_groups': []}
    member_map = {}
    group_map = {}
    for group in prepared.get('evidence_groups', []):
        if not isinstance(group, dict):
            continue
        group_key = (group.get('run_id'), group.get('row'))
        if group_key[0] is not None and group_key[1] is not None:
            group_map[group_key] = group
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
    return {'members': member_map, 'groups': group_map}


def _price_quantity_requirement_matches(item, run, row, group):
    method = _canonical_method_name(item.get('dimensions', {}).get('method'))
    run_method = _run_method(run)
    metric = _canonical_metric_name(item.get('metric'))
    if metric == 'amount':
        if method not in PRICE_QUANTITY_METHODS:
            return False
    elif metric in {'revenue', 'price_quantity'}:
        if method is not None and method not in PRICE_QUANTITY_METHODS:
            return False
    else:
        return False
    if run_method not in PRICE_QUANTITY_METHODS:
        return False
    if method is not None and run_method != method:
        return False
    if not isinstance(group, dict) or group.get('group_type') != 'price_quantity_bridge':
        return False
    if group.get('status') != 'complete' or (group.get('closure') or {}).get('status') != 'passed':
        return False
    if any(row.get(k) != value for k, value in item.get('dimensions', {}).items() if k != 'method'):
        return False
    members = _price_quantity_required_members(group)
    return {member.get('column') for member in members} == set(PRICE_QUANTITY_REQUIRED_COLUMNS)


def _price_quantity_required_members(group):
    if not isinstance(group, dict):
        return []
    members = [
        member for member in group.get('members', [])
        if isinstance(member, dict) and member.get('column') in PRICE_QUANTITY_REQUIRED_COLUMNS
    ]
    complete = []
    for column in PRICE_QUANTITY_REQUIRED_COLUMNS:
        matches = [member for member in members if member.get('column') == column]
        if len(matches) != 1 or matches[0].get('fact_id') is None:
            return []
        complete.append(matches[0])
    return complete


def _account_total_requirement_matches(analysis, item, run, row, column):
    if column != 'amount':
        return False
    metric = _run_finance_metric(analysis, run)
    if not metric or metric.get('kind') != 'account_total':
        return False
    accounts = metric.get('accounts')
    if not isinstance(accounts, list) or len(accounts) != 1:
        return False
    if str(accounts[0]) != item.get('metric'):
        return False
    return not any(row.get(k) != value for k, value in item.get('dimensions', {}).items())


def _account_amount_claim_requires_native_total(item, row, column):
    return (
        column == 'amount'
        and _canonical_metric_name(item.get('metric')) not in METRIC_LABELS
        and row.get('management_account') == item.get('metric')
    )


def _result_set_requirement_status(analysis, item, latest, runs, claimed, checks, evidence):
    kind = _result_set_kind(item)
    if not kind:
        return None
    bases = []
    for run in runs.values():
        if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
            continue
        metric = _run_finance_metric(analysis, run)
        if not metric or metric.get('kind') != kind:
            continue
        if kind == 'account_total' and not _account_total_metric_matches_item(metric, item):
            continue
        if _run_scope_is_narrower_than_requirement(run, item, latest['scope']):
            continue
        rows = _result_set_required_rows(item, run, latest['scope'])
        if rows and _result_set_comparison_complete(kind, item, latest, run, rows):
            bases.append((run, rows))
    if not bases:
        return {'locations': [], 'status': 'pending'}
    max_rows = max(len(rows) for _, rows in bases)
    for run, rows in bases:
        if len(rows) != max_rows:
            continue
        locations = [
            {'run_id': run['id'], 'row': index, 'column': 'amount', 'output_hash': run.get('output_hash')}
            for index, _ in rows
        ]
        if not all((run['id'], location['row'], 'amount') in claimed for location in locations):
            continue
        if not all(_source_verified(location, checks) for location in locations):
            return {
                'locations': [
                    _result_set_location(location, evidence, 'pending')
                    for location in locations
                ],
                'status': 'pending',
            }
        return {
            'locations': [
                _result_set_location(location, evidence, 'answered')
                for location in locations
            ],
            'status': 'answered',
        }
    return {'locations': [], 'status': 'pending'}


def _result_set_kind(item):
    metric = _canonical_metric_name(item.get('metric'))
    if metric in RESULT_SET_METRICS:
        return metric
    if item.get('periods') and metric not in RESULT_SET_METRICS and metric not in METRIC_LABELS:
        return 'account_total'
    return None


def _account_total_metric_matches_item(metric, item):
    accounts = metric.get('accounts')
    return (
        isinstance(accounts, list)
        and len(accounts) == 1
        and str(accounts[0]) == item.get('metric')
    )


def _run_scope_is_narrower_than_requirement(run, item, scope):
    scopes = run.get('finance_scope', {})
    if not isinstance(scopes, dict):
        return False
    expected = _comparison_scopes(scope)
    periods = set(item.get('periods', []))
    for candidate in scopes.values():
        if not isinstance(candidate, dict):
            continue
        for key, value in candidate.items():
            if value in (None, ''):
                continue
            if key in expected['actual'] or key in expected['source']:
                expected_value = expected['actual'].get(key, expected['source'].get(key))
                if expected_value != value:
                    return True
                continue
            if (
                key == 'scenario'
                and _result_set_kind(item) == 'control_totals'
                and not expected['actual'].get('scenario')
                and not expected['source'].get('scenario')
                and value in {'actual', 'budget'}
            ):
                continue
            if key in item.get('dimensions', {}):
                if item['dimensions'][key] != value:
                    return True
                continue
            if key == 'period' and periods:
                if periods == {value}:
                    continue
                return True
            return True
    return False


def _result_set_required_rows(item, run, scope):
    periods = set(item.get('periods', []))
    rows = []
    for index, row in enumerate(run.get('result', {}).get('rows', [])):
        if not _scope_matches(run, row, scope):
            continue
        if not _item_dimensions_match(item, row, run):
            continue
        if periods and row.get('period') not in periods:
            continue
        rows.append((index, row))
    if periods and {row.get('period') for _, row in rows} != periods:
        return []
    return rows


def _item_dimensions_match(item, row, run=None):
    return _dimensions_match(item, row, run or {})


def _result_set_comparison_complete(kind, item, latest, run, rows):
    if kind != 'control_totals':
        return True
    bindings = latest.get('bindings', {})
    dimensions = item.get('dimensions', {}) if isinstance(item.get('dimensions'), dict) else {}
    needs_actual_budget = (
        {'actual', 'budget'}.issubset(set(bindings))
        or dimensions.get('scenario_compare') == 'actual_vs_budget'
    )
    if not needs_actual_budget:
        return True
    return _control_totals_actual_budget_pairs_complete(rows)


def _control_totals_actual_budget_pairs_complete(rows):
    scenarios_by_grain = {}
    for _, row in rows:
        if not isinstance(row, dict):
            return False
        scenario = row.get('scenario')
        if scenario not in {'actual', 'budget'}:
            return False
        grain = tuple((key, row.get(key)) for key in CONTROL_TOTAL_COMPARISON_GRAIN_KEYS if row.get(key) not in (None, ''))
        if not grain:
            return False
        scenarios_by_grain.setdefault(grain, set()).add(scenario)
    return bool(scenarios_by_grain) and all(scenarios == {'actual', 'budget'} for scenarios in scenarios_by_grain.values())


def _profit_bridge_group_required(item):
    dimensions = item.get('dimensions', {}) if isinstance(item.get('dimensions'), dict) else {}
    return (
        _canonical_metric_name(item.get('metric')) == 'profit'
        and _canonical_method_name(dimensions.get('method')) == 'revenue_minus_cost_minus_expense'
        and dimensions.get('dimension') == 'management_account'
        and dimensions.get('scenario_compare') == 'actual_vs_budget'
    )


def _run_finance_variance_method(analysis, run):
    if run.get('engine') != 'finance':
        return None
    analysis_id = run.get('analysis_id')
    if not analysis_id:
        return None
    try:
        revision = analysis.get_analysis(analysis_id)
    except FoundryError:
        return None
    if (
        revision.get('engine') != 'finance'
        or revision.get('operation') != 'variance'
        or revision.get('finance_context_id') != run.get('finance_context_id')
        or revision.get('bindings') != run.get('bindings')
    ):
        return None
    result = run.get('result', {})
    if not isinstance(result, dict):
        return None
    return _canonical_method_name(result.get('method'))


def _profit_bridge_candidate_locations(analysis, item, run, evidence, scope):
    by_line = _profit_bridge_native_group(analysis, item, run, evidence, scope)
    if by_line is None:
        return []
    return [by_line[line] for line in PROFIT_BRIDGE_REQUIRED_LINES]


def _profit_bridge_locations(analysis, item, run, claimed_by_row, evidence, scope):
    locations = _profit_bridge_candidate_locations(analysis, item, run, evidence, scope)
    if not locations:
        return []
    if any('contribution' not in claimed_by_row.get((run['id'], location['row']), set()) for location in locations):
        return []
    return locations


def _profit_bridge_native_group(analysis, item, run, evidence, scope):
    if not _profit_bridge_group_required(item):
        return None
    method = 'revenue_minus_cost_minus_expense'
    if _run_finance_variance_method(analysis, run) != method:
        return None
    rows = run.get('result', {}).get('rows', [])
    by_line = {}
    group_ids = set()
    for index, row in enumerate(rows):
        if not _scope_matches(run, row, scope) or not _dimensions_match(item, row, run):
            continue
        metric = row.get('metric')
        if metric not in PROFIT_BRIDGE_REQUIRED_LINES:
            continue
        member = evidence['members'].get((run['id'], index, 'contribution'))
        if not member or member.get('group_type') != 'profit_bridge':
            return None
        if member.get('group_status') != 'complete' or member.get('closure_status') != 'passed':
            return None
        group_ids.add(member.get('group_id'))
        by_line[metric] = {'run_id': run['id'], 'row': index, 'column': 'contribution', 'output_hash': run.get('output_hash')}
    if set(by_line) != set(PROFIT_BRIDGE_REQUIRED_LINES) or len(group_ids) != 1:
        return None
    return by_line


def _result_set_location(location, evidence, status):
    member = evidence['members'].get((location['run_id'], location['row'], location['column']))
    metadata = {}
    if member:
        metadata = {
            'fact_id': member.get('fact_id'),
            'group_id': member.get('group_id'),
            'group_type': member.get('group_type'),
            'group_status': member.get('group_status'),
            'closure_status': member.get('closure_status'),
            'member_state': member.get('member_state'),
        }
    return {**location, 'evidence': metadata, 'status': status}


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


def _claim_fixup(item, run, row_index, row, column, evidence, reason='valid_candidate_not_claimed'):
    location = {'run_id': run['id'], 'row': row_index, 'column': column, 'output_hash': run.get('output_hash')}
    status, metadata = _location_evidence_status(item, location, evidence['members'].get((run['id'], row_index, column)))
    fact_id = metadata.get('fact_id')
    if status != 'answered' or not fact_id:
        return None
    return {
        'code': 'add_calculation_claim',
        'requirement_item_id': item['id'],
        **location,
        'value': row.get(column),
        'fact_id': fact_id,
        'reason': reason,
    }


def _run_inputs_match_requirement(run, requirement):
    basis = requirement.get('semantic_basis') if isinstance(requirement, dict) else None
    sources = basis.get('sources') if isinstance(basis, dict) else None
    if not sources:
        return True
    for alias, source in sources.items():
        if (run.get('bindings', {}).get(alias) != source.get('dataset_id')
                or run.get('input_hashes', {}).get(alias) != source.get('data_hash')
                or run.get('source_hashes', {}).get(alias) != source.get('source_hash')):
            return False
    return True


def _source_fixup(item, location, checks):
    if not item.get('requires_drilldown') or _source_verified(location, checks):
        return None
    fact_id = (location.get('evidence') or {}).get('fact_id')
    if not fact_id:
        return None
    return {
        'code': 'verify_source',
        'requirement_item_id': item['id'],
        'location': {key: location[key] for key in ('run_id', 'row', 'column', 'output_hash')},
        'fact_id': fact_id,
        'reason': 'drilldown_required',
    }


def _dedupe_fixups(fixups):
    seen = set()
    deduped = []
    for fixup in fixups:
        if not isinstance(fixup, dict):
            continue
        key = _hash(fixup)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fixup)
    return deduped


def _result_set_candidate_fixups(analysis, item, latest, runs, checks, evidence, claimed):
    kind = _result_set_kind(item)
    if not kind:
        return []
    fixups = []
    for run in runs.values():
        if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
            continue
        if not _run_inputs_match_requirement(run, latest):
            continue
        metric = _run_finance_metric(analysis, run)
        if not metric or metric.get('kind') != kind:
            continue
        if kind == 'account_total' and not _account_total_metric_matches_item(metric, item):
            continue
        if _run_scope_is_narrower_than_requirement(run, item, latest['scope']):
            continue
        rows = _result_set_required_rows(item, run, latest['scope'])
        if not rows:
            continue
        if run.get('result', {}).get('truncated'):
            fixups.append({
                'code': 'result_set_incomplete',
                'requirement_item_id': item['id'],
                'run_id': run['id'],
                'row_count': run.get('result', {}).get('row_count', len(run.get('result', {}).get('rows', []))),
                'reason': 'run_result_truncated',
            })
            continue
        row_fixups = []
        source_fixups = []
        for index, row in rows:
            if (run['id'], index, 'amount') in claimed:
                continue
            claim = _claim_fixup(item, run, index, row, 'amount', evidence)
            if not claim:
                row_fixups = []
                break
            row_fixups.append(claim)
            location = _result_set_location(
                {'run_id': run['id'], 'row': index, 'column': 'amount', 'output_hash': run.get('output_hash')},
                evidence, 'answered'
            )
            source = _source_fixup(item, location, checks)
            if source:
                source_fixups.append(source)
        fixups.extend(row_fixups)
        fixups.extend(source_fixups)
    return fixups


def _price_quantity_candidate_fixups(item, latest, runs, checks, evidence, claimed):
    fixups = []
    for run in runs.values():
        if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
            continue
        if not _run_inputs_match_requirement(run, latest):
            continue
        for index, row in enumerate(run.get('result', {}).get('rows', [])):
            group = evidence['groups'].get((run['id'], index))
            if not _scope_matches(run, row, latest['scope']):
                continue
            if not _price_quantity_requirement_matches(item, run, row, group):
                continue
            for member in _price_quantity_required_members(group):
                if (run['id'], index, member['column']) in claimed:
                    continue
                claim = _claim_fixup(item, run, index, row, member['column'], evidence)
                if claim:
                    fixups.append(claim)
                    location = _result_set_location(
                        {'run_id': run['id'], 'row': index, 'column': member['column'], 'output_hash': run.get('output_hash')},
                        evidence, 'answered'
                    )
                    source = _source_fixup(item, location, checks)
                    if source:
                        fixups.append(source)
    return fixups


def _generic_candidate_fixups(item, latest, runs, checks, evidence, claimed):
    if _profit_bridge_group_required(item):
        return []
    fixups = []
    for run in runs.values():
        if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
            continue
        if not _run_inputs_match_requirement(run, latest):
            continue
        for index, row in enumerate(run.get('result', {}).get('rows', [])):
            if not _scope_matches(run, row, latest['scope']):
                continue
            for column in row:
                if _account_amount_claim_requires_native_total(item, row, column):
                    continue
                if not _matches(item, row, column, run):
                    continue
                if (run['id'], index, column) in claimed:
                    continue
                claim = _claim_fixup(item, run, index, row, column, evidence)
                if claim:
                    fixups.append(claim)
                    location = _result_set_location(
                        {'run_id': run['id'], 'row': index, 'column': column, 'output_hash': run.get('output_hash')},
                        evidence, 'answered'
                    )
                    source = _source_fixup(item, location, checks)
                    if source:
                        fixups.append(source)
    return fixups


def _profit_bridge_candidate_fixups(analysis, item, latest, runs, checks, evidence, claimed):
    if not _profit_bridge_group_required(item):
        return []
    fixups = []
    for run in runs.values():
        if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
            continue
        if not _run_inputs_match_requirement(run, latest):
            continue
        if _profit_bridge_native_group(analysis, item, run, evidence, latest['scope']) is None:
            continue
        for location in _profit_bridge_candidate_locations(analysis, item, run, evidence, latest['scope']):
            key = (location['run_id'], location['row'], location['column'])
            if key not in claimed:
                row = run['result']['rows'][location['row']]
                claim = _claim_fixup(item, run, location['row'], row, location['column'], evidence)
                if claim:
                    fixups.append(claim)
            source = _source_fixup(item, _result_set_location(location, evidence, 'answered'), checks)
            if source:
                fixups.append(source)
    return fixups


def _method_conflict_fixups(item, latest, runs, evidence):
    expected_method = _canonical_method_name(item.get('dimensions', {}).get('method'))
    if expected_method is None:
        return []
    fixups = []
    for run in runs.values():
        actual_method = _run_method(run)
        if actual_method in (None, expected_method):
            continue
        if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
            continue
        if not _run_inputs_match_requirement(run, latest):
            continue
        for index, row in enumerate(run.get('result', {}).get('rows', [])):
            if not _scope_matches(run, row, latest['scope']):
                continue
            relaxed = {**item, 'dimensions': {k: v for k, v in item.get('dimensions', {}).items() if k != 'method'}}
            group = evidence['groups'].get((run['id'], index))
            if not (
                _price_quantity_requirement_matches(relaxed, run, row, group)
                or any(_matches(relaxed, row, column, run) for column in row)
            ):
                continue
            fixups.append({
                'code': 'method_conflict',
                'requirement_item_id': item['id'],
                'run_id': run['id'],
                'row': index,
                'expected_method': expected_method,
                'actual_method': actual_method,
                'reason': 'requirement_method_does_not_match_run',
            })
            break
    return fixups


def _requirement_fixups(analysis, item, latest, runs, checks, evidence, claimed):
    return _dedupe_fixups([
        *_result_set_candidate_fixups(analysis, item, latest, runs, checks, evidence, claimed),
        *_price_quantity_candidate_fixups(item, latest, runs, checks, evidence, claimed),
        *_generic_candidate_fixups(item, latest, runs, checks, evidence, claimed),
        *_profit_bridge_candidate_fixups(analysis, item, latest, runs, checks, evidence, claimed),
        *_method_conflict_fixups(item, latest, runs, evidence),
    ])


def check_requirements(analysis, spec, *, _requirements_record=None):
    latest = _requirements_record or latest_requirements(analysis)
    if not latest:
        return {'requirements_id': None, 'items': [], 'coverage': {'status': 'not_assessed'},
                'provenance': {'status': 'not_assessed'}, 'scope_changed': False,
                'original_requirements_completed': False}
    selected_id = spec.get('requirements_id') or latest['id']
    selected = latest if _requirements_record and latest.get('id') == selected_id else analysis._get('requirements', selected_id)
    # Public checks use current obligations; only internal appendix reconstruction
    # supplies an immutable historical record to recover its original text.
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
    claimed_by_row = {}
    for run_id, index, column in claimed:
        claimed_by_row.setdefault((run_id, index), set()).add(column)
    fixup_runs = {run_id: runs[run_id] for run_id in spec.get('run_ids', []) if run_id in runs}
    checks = analysis._list('evidence_checks')
    source_failures = _source_read_failures(spec.get('source_read_failures', []))
    items = []
    for item in latest['items']:
        locations = []
        statuses = []
        processed_groups = set()
        result_set = _result_set_requirement_status(analysis, item, latest, runs, claimed, checks, evidence)
        if result_set is not None:
            locations = result_set['locations']
            statuses = [result_set['status']]
        else:
            result_set = None
        for run_id, index, column in claimed:
            if result_set is not None:
                break
            run = runs[run_id]
            if not _bindings_match(latest.get('bindings', {}), run.get('bindings', {})):
                continue
            row = run['result']['rows'][index]
            group = evidence['groups'].get((run_id, index))
            profit_bridge_locations = _profit_bridge_locations(analysis, item, run, claimed_by_row, evidence, latest['scope'])
            if profit_bridge_locations and ('profit_bridge', run_id) not in processed_groups:
                processed_groups.add(('profit_bridge', run_id))
                for location in profit_bridge_locations:
                    status, metadata = _location_evidence_status(
                        item, location, evidence['members'].get((run_id, location['row'], location['column']))
                    )
                    locations.append({**location, 'evidence': metadata, 'status': status})
                    statuses.append(status)
                continue
            if (
                _price_quantity_requirement_matches(item, run, row, group)
                and (run_id, index) not in processed_groups
                and set(PRICE_QUANTITY_REQUIRED_COLUMNS).issubset(claimed_by_row.get((run_id, index), set()))
                and _scope_matches(run, row, latest['scope'])
            ):
                processed_groups.add((run_id, index))
                for member in _price_quantity_required_members(group):
                    location = {'run_id': run_id, 'row': index, 'column': member['column'], 'output_hash': run.get('output_hash')}
                    status, metadata = _location_evidence_status(
                        item, location, evidence['members'].get((run_id, index, member['column']))
                    )
                    locations.append({**location, 'evidence': metadata, 'status': status})
                    statuses.append(status)
                continue
            if _profit_bridge_group_required(item):
                continue
            account_total_match = _account_total_requirement_matches(analysis, item, run, row, column)
            generic_match_allowed = not _account_amount_claim_requires_native_total(item, row, column)
            if (account_total_match and _scope_matches(run, row, latest['scope'])) or (
                generic_match_allowed and _matches(item, row, column, run) and _scope_matches(run, row, latest['scope'])
            ):
                location = {'run_id': run_id, 'row': index, 'column': column, 'output_hash': run.get('output_hash')}
                status, metadata = _location_evidence_status(
                    item, location, evidence['members'].get((run_id, index, column))
                )
                locations.append({**location, 'evidence': metadata, 'status': status})
                statuses.append(status)
        item_status = _item_status(statuses)
        failed_source = item['id'] in source_failures
        source_matches = [_source_verified(location, checks) for location in locations]
        source_complete = (
            bool(source_matches) and all(source_matches)
            if _profit_bridge_group_required(item)
            else any(source_matches)
        )
        sourced = (
            item_status == 'answered'
            and not failed_source
            and source_complete
        )
        provenance_status = 'not_requested'
        if item['requires_drilldown']:
            provenance_status = 'verified' if sourced else 'failed' if failed_source else 'pending'
        fixups = _requirement_fixups(analysis, item, latest, fixup_runs, checks, evidence, claimed)
        if item_status == 'answered':
            fixups = [fixup for fixup in fixups if fixup.get('code') == 'verify_source']
        item_record = {**item, 'status': item_status, 'locations': locations,
                       'source_read_failure': source_failures.get(item['id']),
                       'provenance_status': provenance_status}
        source_fixups = [fixup for location in locations
                         for fixup in [_source_fixup(item, location, checks)] if fixup]
        fixups = _dedupe_fixups([*fixups, *source_fixups])
        if fixups:
            item_record['fixups'] = fixups
        items.append(item_record)
    scope_changed = False if _requirements_record else selected['id'] != latest['id']
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
    if not matching and location.get('column') is not None:
        row_base = {**base, 'column': None}
        matching = [
            check for check in checks
            if check.get('status') == 'verified'
            and _location_matches(check.get('location'), row_base)
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
    from foundry.finance_requirement_support import with_input_gaps
    requirements = with_input_gaps(analysis, requirements)
    issues = list(quality.get('issues', []))
    if requirements['scope_changed']:
        issues.append({'code': 'requirements_changed', 'severity': 'warning', 'message': '分析范围已更新，请按当前要求复核文稿。'})
    for item in requirements['items']:
        if item['status'] != 'answered':
            issues.append({'code': 'requirement_unanswered', 'severity': 'warning', 'message': f'尚未提供“{item["label"]}”的计算依据。', 'requirement_item_id': item['id'],
                           **({'fixups': item['fixups']} if item.get('fixups') else {})})
        if item['provenance_status'] in {'pending', 'failed'}:
            source_fixups = [fixup for fixup in item.get('fixups', []) if fixup.get('code') == 'verify_source']
            issues.append({'code': 'requested_source_missing', 'severity': 'warning', 'message': f'尚未完成“{item["label"]}”的指定来源核查。', 'requirement_item_id': item['id'],
                           **({'fixups': source_fixups} if source_fixups else {})})
    return {**quality, 'issues': issues, 'status': 'needs_attention' if issues else quality['status'],
            'requirements': requirements,
            'checks': {'numbers': {'status': quality['status']}, 'coverage': requirements['coverage'], 'provenance': requirements['provenance']}}
