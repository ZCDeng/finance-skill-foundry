"""Row declarations: what each row of a script result states, decided on the server when the run is saved.

A declaration says, for every row of the full result file, which comparison it fills (actual, budget, variance,
ratio or none), the period it covers, whether it is an estimate and on what grounds, and the 口径 its own label
names. It lives in the run record's ``row_declarations`` field, beside ``result`` and never inside it: a script
run's output_hash covers stdout, outputs and result, so the same output keeps the same hash (KTD1).

The vocabulary here is ported from app/src/views/analysis/businessResults.ts, which keeps its own copy only to
infer rows of runs saved before declarations existed; tests/test_result_semantics.py holds the two together.
finance_requirements.RATIO_SCENARIOS / METRIC_LABELS and finance_explanations.METRIC_LABELS are deliberately
separate: they decide which requirement items close.

Estimates are a union that only ever adds (KTD3): grain_basis estimates in the requirements version the run is
pinned to, the row's own basis columns, a filled 估算方法, an estimated_ scenario, or an estimate word in its label,
note or source. The task's latest requirements are merged in at read time (``declared_runs``), since the
assistant often declares grain_basis after the run it describes.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from foundry.analysis import _hash_bytes
from foundry.analysis_data import json_value, parse_source
from foundry.errors import FoundryError
from foundry.finance_requirements import (
    _declared_basis,
    _metric_matches,
    _requested_grain_matches,
    _row_grain,
)

# The declaration rules are versioned by part; a stored declaration older than any part is recomputed on read.
VOCABULARY_VERSION = 1
UNIT_TABLE_VERSION = 1
ESTIMATE_WORDS_VERSION = 1
# A declaration covers at most this many rows; a longer result is declared up to here and marked incomplete.
MAX_DECLARED_ROWS = 5000

# Long-form scenarios by the comparison they fill (businessResults.ts longScenarioMeasure), in its order.
LONG_SCENARIO_MEASURES = {
    'actual': ('actual', 'actual_ytd', 'actual_month', 'actual_period'),
    'budget': ('budget', 'budget_ytd', 'budget_month', 'same_period_budget', 'baseline'),
    'estimated_budget': ('estimated_budget', 'estimated_budget_ytd', 'estimated_budget_month'),
    # variance_favorable is signed by effect on profit, not actual minus budget; it stays unpaired.
    'variance': ('variance', 'budget_variance', 'difference', 'amount_change', 'profit_impact', 'contribution'),
    'rate': ('achievement_ratio', 'attainment_rate', 'attainment_ratio', 'completion_rate', 'actual_budget_ratio',
             'actual_to_budget', 'ratio'),
    'rate_pct': ('achievement_pct', 'attainment_pct', 'completion_pct'),
}
# A scenario that names its own period: actual_1_8 (months 1–8), budget_2026_08. A bare year (actual_2026) cannot
# tell year-to-date from the full year, and other words after it (actual_py_1_8, budget_bud_fy) are other comparisons.
SCENARIO_WITH_PERIOD = re.compile(r'^(actual|budget|variance)_(\d{1,2}_\d{1,2}|\d{4}_\d{2})$')
# A variance or 达成率 may be its own metric named for its base (revenue_variance, revenue_achievement_ratio).
RATE_METRIC = re.compile(r'^(.+)_(?:achievement|attainment)_ratio$')
VARIANCE_METRIC = re.compile(r'^(.+)_variance$')
RESULT_METRIC_LABELS = {
    'revenue': '收入',
    'operating_profit': '营业利润',
    'profit': '利润',
    'gross_profit': '毛利',
    'period_expense': '期间费用',
    'credit_impairment_loss': '信用减值损失',
    'asset_impairment_loss': '资产减值损失',
    'impairment_loss_total': '减值损失合计',
    'other_income_and_gains_4items': '其他损益四项',
    'operating_profit_excl_other': '剔除其他损益经营利润',
    'operating_profit_excluding_other': '剔除其他损益经营利润',
    'operating_profit_excl_other_gains': '剔除其他损益经营利润',
    'other_gains': '其他收益',
    'expense': '费用',
    'cost': '成本',
    '营业收入': '营业收入',
    '收入': '收入',
    '经营利润': '经营利润',
    '营业利润': '营业利润',
}

# The unit table (KTD9): 比率 and ratio hold a fraction (0.945 = 94.5%), %, pct and 百分比 a percent, and 「-」
# says no unit was marked. Only the declared unit converts a value; a name never does.
FRACTION_UNITS = frozenset({'比率', 'ratio'})
PERCENT_UNITS = frozenset({'%', 'pct', '百分比'})
UNMARKED_UNITS = frozenset({'-'})

# The words an estimate goes by in these files, and the negations right before one that cancel it (非估算,
# 不含估算调整). An unknown wording errs toward 估算.
ESTIMATE_WORDS = re.compile(r'估算|推算|预估|估计|测算|estimat', re.IGNORECASE)
NEGATIONS = ('非', '不含', '不是', '并非', '无', '未')
NO_METHOD = frozenset({'无', '否', '-', '—', 'n/a', 'na', '不适用', 'none', 'null'})
BASIS_FIELDS = ('basis', 'row_basis', 'validation_basis', 'source_basis', 'value_basis', 'evidence_basis')
ESTIMATE_BASIS_VALUES = frozenset({'estimate', 'estimated', 'estimation', 'user_assumption', 'assumption', '估算'})
TEXT_FIELDS = ('metric_label', 'note', '说明', 'source', 'source_note', '来源', '口径与来源')

METRIC_FIELDS = ('metric', 'metric_key', 'business_key', 'result_key', 'item', 'name', '指标')
# The row fields the requirement matcher reads (metric by key or label, then organization, period, scenario).
MATCH_FIELDS = ('metric_key', 'metric', 'line', 'contribution_line', 'management_account',
                'organization', 'period', 'scenario')
ROLES = {'actual': 'actual', 'budget': 'budget', 'estimated_budget': 'budget', 'variance': 'variance',
         'rate': 'ratio', 'rate_pct': 'ratio'}


def rules_version() -> str:
    return f'{VOCABULARY_VERSION}.{UNIT_TABLE_VERSION}.{ESTIMATE_WORDS_VERSION}'


def _version_parts(value: Any) -> tuple[int, ...] | None:
    try:
        parts = tuple(int(part) for part in str(value).split('.'))
    except ValueError:
        return None
    return parts if len(parts) == 3 else None


def is_stale(version: Any) -> bool:
    """Whether a stored declaration predates any part of the current rules."""
    stored, current = _version_parts(version), _version_parts(rules_version())
    return stored is None or any(old < new for old, new in zip(stored, current))


def vocabulary(requirements: dict | None = None) -> dict:
    """The declared metric and scenario names: this module's tables plus the names the requirements list."""
    items = (requirements or {}).get('items') or []
    return {
        'metrics': frozenset(RESULT_METRIC_LABELS) | {item['metric'] for item in items if item.get('metric')},
        'scenarios': frozenset(name for names in LONG_SCENARIO_MEASURES.values() for name in names)
        | {scenario for item in items for scenario in item.get('scenarios') or []},
    }


def mentions_estimate(text: str) -> bool:
    for match in ESTIMATE_WORDS.finditer(text):
        before = text[max(0, match.start() - 2):match.start()]
        if not any(before.endswith(word) for word in NEGATIONS):
            return True
    return False


def _first(row: dict, keys: tuple[str, ...]) -> Any:
    return next((row[key] for key in keys if row.get(key) is not None), None)


def _text(value: Any) -> str:
    return '' if value is None else str(value)


def _scenario_measure(row: dict) -> dict | None:
    scenario = _text(_first(row, ('scenario', '情景'))).strip().lower()
    if not scenario:
        return None
    # A ytd or month ending is a period class: a year-to-date actual never pairs with a monthly budget.
    span = 'ytd' if scenario.endswith('_ytd') else 'month' if scenario.endswith('_month') else None
    for measure, names in LONG_SCENARIO_MEASURES.items():
        if scenario in names:
            return {'measure': measure, 'suffix': '', 'span': span if measure in {'actual', 'budget'} else None}
    match = SCENARIO_WITH_PERIOD.fullmatch(scenario)
    return {'measure': match.group(1), 'suffix': match.group(2), 'span': None} if match else None


def _unit_kind(unit: str) -> str | None:
    if unit in FRACTION_UNITS:
        return 'decimal'
    if unit in PERCENT_UNITS:
        return 'percent'
    if unit in UNMARKED_UNITS:
        return 'unmarked'
    return None


def _comparison(row: dict) -> dict | None:
    """Which comparison a long-form row fills, and for which metric (businessResults.ts longScenarioEntry).

    A variance or 达成率 named for its base metric joins that base: revenue_variance with a variance scenario, and
    revenue_achievement_ratio in a ratio unit, whose scenario word is unreliable, so only its period suffix counts.
    An unmarked unit (「-」) is a ratio's: such a row never sits beside amounts as if it were one.
    """
    scenario = _scenario_measure(row)
    if scenario is None:
        return None
    metric = _text(_first(row, METRIC_FIELDS))
    unit_kind = _unit_kind(_text(_first(row, ('unit', '单位'))).strip().lower())
    rate = RATE_METRIC.fullmatch(metric)
    if rate and unit_kind is not None:
        return {**scenario, 'measure': 'rate_pct' if unit_kind == 'percent' else 'rate', 'metric': rate.group(1)}
    # A 达成率 given in % or pct is already a percentage; as a fraction it would read 100 times too large.
    if scenario['measure'] == 'rate' and unit_kind == 'percent':
        return {**scenario, 'measure': 'rate_pct', 'metric': metric}
    if scenario['measure'] in {'rate', 'rate_pct'}:
        return {**scenario, 'metric': metric}
    # An amount comparison in a ratio unit (or none marked) would sit beside amounts as if it were one.
    if unit_kind is not None:
        return None
    variance = VARIANCE_METRIC.fullmatch(metric)
    if variance and scenario['measure'] == 'variance':
        return {**scenario, 'metric': variance.group(1)}
    return {**scenario, 'metric': metric}


def _long_format(columns: list) -> bool:
    names = {_text(column.get('name') if isinstance(column, dict) else column).lower() for column in columns}
    return 'scenario' in names and 'value' in names and bool(names & {'metric_key', 'metric', '指标'})


def _row_sources(row: dict) -> list[dict]:
    """The row's own estimate grounds: its basis columns, a filled 估算方法, an estimated scenario, its wording."""
    sources = []
    for field in BASIS_FIELDS:
        if _text(row.get(field)).strip().lower() in ESTIMATE_BASIS_VALUES:
            sources.append({'source': 'row', 'field': field})
    method = _text(row.get('估算方法')).strip()
    if method and method.lower() not in NO_METHOD:
        sources.append({'source': 'row', 'field': '估算方法'})
    for field in ('scenario', '情景'):
        if isinstance(row.get(field), str) and re.search('estimat', row[field], re.IGNORECASE):
            sources.append({'source': 'row', 'field': field})
    for field in TEXT_FIELDS:
        if isinstance(row.get(field), str) and mentions_estimate(row[field]):
            sources.append({'source': 'text', 'field': field})
    return sources


def _has_estimate_grains(requirements: dict | None) -> bool:
    return any(entry.get('basis') == 'estimate'
               for item in (requirements or {}).get('items') or [] for entry in item.get('grain_basis') or [])


def _declared_sources(requirements: dict | None, fields: dict) -> list[dict]:
    """The requirement items whose grain_basis declares this row's grain an estimate.

    The item's dimensions are not applied: a declaration errs toward saying 估算.
    """
    if not _has_estimate_grains(requirements):
        return []
    sources = []
    for item in requirements.get('items') or []:
        if not item.get('grain_basis') or not item.get('metric'):
            continue
        if not _metric_matches(item, fields, 'value') or not _requested_grain_matches(item, {}, fields):
            continue
        declared = _declared_basis(item, _row_grain(item, {}, fields))
        if declared and declared.get('basis') == 'estimate':
            sources.append({'source': 'declared', 'requirements_id': requirements['id'], 'item_id': item['id']})
    return sources


def _declare_row(index: int, row: dict, long_format: bool, requirements: dict | None) -> dict:
    row = json_value(row)
    comparison = _comparison(row) if long_format else None
    role = ROLES[comparison['measure']] if comparison else None
    unit = _text(_first(row, ('unit', '单位'))).strip()
    unit_kind = _unit_kind(unit.lower())
    if unit_kind is None and role is not None:
        unit_kind = 'unmarked' if role == 'ratio' else 'amount'
    elif unit_kind is None and unit:
        unit_kind = 'amount'
    period = _first(row, ('period', '期间'))
    fields = {key: row[key] for key in MATCH_FIELDS if row.get(key) is not None}
    sources = [*_declared_sources(requirements, fields), *_row_sources(row)]
    label = row.get('metric_label')
    return {
        'row': index,
        'fields': fields,
        'role': role,
        'metric': comparison['metric'] if comparison else _first(row, METRIC_FIELDS),
        'organization': _first(row, ('organization', 'region', '区域')),
        'period': period,
        'period_key': f"{_text(period)}|{comparison['suffix']}" if comparison else None,
        'span': comparison['span'] if comparison else None,
        'unit': unit or None,
        'unit_kind': unit_kind,
        'value': _first(row, ('value', '值')) if comparison else None,
        'scope_label': label.strip() if isinstance(label, str) and label.strip() else None,
        'estimate': bool(sources),
        'estimate_sources': sources,
    }


def declare_rows(columns: list, rows: list[dict], requirements: dict | None, *, fingerprint: str | None,
                 complete: bool = True, incomplete_reason: str | None = None) -> dict:
    """A declaration of `rows`, which must be the full result table unless `complete` says otherwise."""
    long_format = _long_format(columns)
    declared = rows[:MAX_DECLARED_ROWS]
    if len(rows) > MAX_DECLARED_ROWS and complete:
        complete, incomplete_reason = False, 'too_many_rows'
    return {
        'rules_version': rules_version(),
        'requirements_id': (requirements or {}).get('id'),
        'requirements_fingerprint': fingerprint,
        'complete': complete,
        'incomplete_reason': None if complete else incomplete_reason,
        'row_count': len(rows),
        'rows': [_declare_row(index, row, long_format, requirements) for index, row in enumerate(declared)],
    }


def declare_script_result(analysis, columns: list, rows: list[dict], requirements_id: str | None) -> dict:
    """The declaration a script run saves: its full result rows read against its pinned requirements."""
    from foundry.finance_requirement_semantics import verified_requirement_fingerprint

    try:
        requirements = analysis._get('requirements', requirements_id) if requirements_id else None
    except FoundryError:
        declaration = declare_rows(columns, rows, None, fingerprint=None, complete=False,
                                   incomplete_reason='requirements_unavailable')
        return {**declaration, 'requirements_id': requirements_id}
    return declare_rows(columns, rows, requirements,
                        fingerprint=verified_requirement_fingerprint(analysis, requirements))


def _archived_result(analysis, run: dict) -> tuple[list, list[dict]] | None:
    """The run's full result table from its archived output, checked against the manifest as run_script does."""
    source = (run.get('result') or {}).get('result_source') or {}
    path, digest = source.get('path'), source.get('sha256')
    item = next((item for item in run.get('outputs') or [] if item.get('path') == path), None)
    if not path or not digest or item is None or item.get('sha256') != digest:
        return None
    try:
        data = analysis._inside(analysis.root / item['artifact_path']).read_bytes()
        if _hash_bytes(data) != digest:
            return None
        parsed = parse_source(data, Path(path).suffix.casefold(), {})
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return None
    return (parsed['schema'], parsed['rows']) if parsed.get('kind') == 'table' else None


def redeclare(analysis, run: dict) -> dict:
    """Recompute a stored declaration under the current rules; the run record itself is never rewritten.

    The pinned requirements and their fingerprint are the stored ones: the requirements record is immutable.
    Without the full result file, the stored preview rows are declared and the declaration is incomplete.
    """
    stored = run['row_declarations']
    requirements_id = stored.get('requirements_id')
    try:
        requirements = analysis._get('requirements', requirements_id) if requirements_id else None
    except FoundryError:
        requirements = None
    archived = _archived_result(analysis, run)
    result = run.get('result') or {}
    columns, rows = archived or (result.get('columns') or [], result.get('rows') or [])
    if requirements_id and requirements is None:
        complete, reason = False, 'requirements_unavailable'
    else:
        complete, reason = archived is not None, None if archived is not None else 'result_file_unavailable'
    declaration = declare_rows(columns, rows, requirements, fingerprint=stored.get('requirements_fingerprint'),
                               complete=complete, incomplete_reason=reason)
    return {**declaration, 'requirements_id': requirements_id}


def merge_latest(declaration: dict, latest: dict | None) -> dict:
    """Add the estimates the task's latest requirements declare; nothing the declaration holds is removed."""
    if not latest or latest.get('id') == declaration.get('requirements_id') or not _has_estimate_grains(latest):
        return declaration
    rows = []
    for entry in declaration.get('rows') or []:
        added = [source for source in _declared_sources(latest, entry.get('fields') or {})
                 if source not in entry.get('estimate_sources', [])]
        rows.append({**entry, 'estimate': True, 'estimate_sources': [*entry.get('estimate_sources', []), *added]}
                    if added else entry)
    return {**declaration, 'rows': rows, 'latest_requirements_id': latest['id']}


def declared_run(analysis, run: dict, latest: dict | None) -> dict:
    """The run as the workbench reads it: a stale declaration recomputed, the latest estimates merged in."""
    declaration = run.get('row_declarations')
    if not isinstance(declaration, dict):
        return run
    if is_stale(declaration.get('rules_version')):
        declaration = redeclare(analysis, run)
    declaration = merge_latest(declaration, latest)
    return run if declaration is run['row_declarations'] else {**run, 'row_declarations': declaration}


def declared_runs(analysis, runs: list[dict], latest: dict | None) -> list[dict]:
    return [declared_run(analysis, run, latest) for run in runs]
