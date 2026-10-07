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

The declaration also carries the rows that break the result-row contract (R5) as warnings in the diagnostic shape.
A warning never fails the run and never changes how a row is declared.

It pairs its rows as the result area pairs them (businessResults.ts longScenarioPairing). A pair whose every member is
declared, in a complete declaration, gets one Chinese sentence built from the rows' own Decimal values (R6, KTD7),
unless its variance row states other than actual minus budget: then it says nothing and the declaration warns.
The sentence's basis is 脚本结果: it is never verified and never one of a draft's quotable facts, which are read
from the run's result alone.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, Inexact, InvalidOperation, localcontext
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
# Vocabulary 2: the vocabulary also decides the contract warnings.
# Vocabulary 3: the vocabulary also pairs rows and words the conclusion sentences; an estimated budget has a span.
# Vocabulary 4: a variance row that is not actual minus budget silences its pair's sentence and warns.
# Vocabulary 5: rows sharing organization, period and metric_label under different metrics warn (label_ambiguous).
# Unit table 2: 百分点 holds a difference of two percentages.
VOCABULARY_VERSION = 5
UNIT_TABLE_VERSION = 2
ESTIMATE_WORDS_VERSION = 1
# A declaration covers at most this many rows; a longer result is declared up to here and marked incomplete.
MAX_DECLARED_ROWS = 5000
# A contract warning lists at most this many rows and names; its row_count says how many rows it concerns in all.
MAX_WARNING_ROWS = 20
# How many of those names its message spells out.
MAX_WARNING_NAMES = 5

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
# 百分点 holds a difference of two percentages as written: 3.3 is 3.3 个百分点, never ×100. It fills no comparison.
POINT_UNITS = frozenset({'百分点'})

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
# How a conclusion sentence names each figure it says is an estimate.
MEASURE_WORDS = {'actual': '实际', 'budget': '预算', 'estimated_budget': '预算', 'variance': '差异',
                 'rate': '达成率', 'rate_pct': '达成率'}
CONCLUSION_BASIS = '脚本结果'
# Working precision for the one subtraction and the ×100 a sentence may need; a result it cannot hold exactly is
# not said at all.
CONCLUSION_PRECISION = 100


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
    # A scenario the requirements name once for every item (scope) or as one item's dimension is listed too.
    single = [(requirements or {}).get('scope') or {}, *((item.get('dimensions') or {}) for item in items)]
    return {
        'metrics': frozenset(RESULT_METRIC_LABELS) | {item['metric'] for item in items if item.get('metric')},
        'scenarios': frozenset(name for names in LONG_SCENARIO_MEASURES.values() for name in names)
        | {scenario for item in items for scenario in item.get('scenarios') or []}
        | {entry['scenario'] for entry in single if isinstance(entry.get('scenario'), str) and entry['scenario']},
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


def _unit(row: dict) -> str:
    """The row's unit as its facts read it (finance_explanations._row_unit): the first of unit, 单位 that is neither
    null nor empty, so 「unit: ''」 beside 「单位: '百分点'」 is in 百分点 on every side."""
    return _text(next((row[key] for key in ('unit', '单位') if row.get(key) not in (None, '')), None))


def _scenario_measure(row: dict) -> dict | None:
    scenario = _text(_first(row, ('scenario', '情景'))).strip().lower()
    if not scenario:
        return None
    # A ytd or month ending is a period class: a year-to-date actual never pairs with a monthly budget.
    span = 'ytd' if scenario.endswith('_ytd') else 'month' if scenario.endswith('_month') else None
    for measure, names in LONG_SCENARIO_MEASURES.items():
        if scenario in names:
            return {'measure': measure, 'suffix': '',
                    'span': span if measure in {'actual', 'budget', 'estimated_budget'} else None}
    match = SCENARIO_WITH_PERIOD.fullmatch(scenario)
    return {'measure': match.group(1), 'suffix': match.group(2), 'span': None} if match else None


def _unit_kind(unit: str) -> str | None:
    if unit in POINT_UNITS:
        return 'points'
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
    unit_kind = _unit_kind(_unit(row).strip().lower())
    # A difference of two percentages is neither an amount nor a 达成率 (revenue_achievement_ratio in 百分点 included).
    if unit_kind == 'points':
        return None
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
    unit = _unit(row).strip()
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


def _names(names: list[str]) -> str:
    shown = '、'.join(names[:MAX_WARNING_NAMES])
    return shown if len(names) <= MAX_WARNING_NAMES else f'{shown} 等 {len(names)} 个'


def _contract_message(code: str, count: int, names: list[str]) -> str:
    if code == 'unit_unmarked':
        return (f'{count} 行没有标明单位：单位写成「-」，或比率行没有写单位表里的单位。这些行不参与金额配对，'
                '结果区原样显示并注明「未标单位」。比率写「比率」或 ratio（小数，0.945 即 94.5%），'
                '百分数写 %、pct 或「百分比」，两个比率之差写「百分点」，金额写实际单位。')
    if code == 'scenario_undeclared':
        return (f'情景名 {_names(names)} 不在约定情景里，本次运行固定的需求版本也没有列出（共 {count} 行），'
                '这些行不参与实际与预算配对。请改用约定情景名（actual、budget、variance，或带期间后缀的 '
                'actual_1_8、budget_2026_08），或把它列进需求版本的 scenarios。')
    if code == 'metric_undeclared':
        return (f'指标名 {_names(names)} 不在约定指标里，这些行也没有写 metric_label（共 {count} 行），'
                '结果区只能显示原名。请改用约定指标名，或在 metric_label 列写口径标签。')
    if code == 'variance_mismatch':
        return (f'{_names(names)} 的差异行不等于实际减预算（共 {count} 行），这些比较不写结论句，'
                '以免结论与所引实际、预算的方向相反。差异行应写实际减预算，不写按利润影响取正负的数；'
                '请核对实际、预算与差异是否取自同一口径，改好后重跑。')
    if code == 'label_ambiguous':
        return (f'{_names(names)} 在同一组织、同一期间里被 {count} 行没有进入配对的结果行共用，这些行的指标键不同，'
                '结果区只能在名字后补中文名或指标键区分。请在 metric_label 写出对象（如「收入完成率」「营业利润完成率」），'
                '改好后重跑。')
    return (f'{count} 行的文字写了估算用语，但依据列 basis 没有写 estimate。这些行仍按估算显示；'
            '请在这些行的 basis 列写 estimate，估算就不只靠文字识别。')


def _shown_label(row: dict, entry: dict) -> str | None:
    """A row's metric_label as the result table shows it (businessResults.ts formatBusinessCell): trimmed, with
    「（估算）」 after it when the row is an estimate its label does not already name, else a metric code read as its
    Chinese name. None when the row has no label to show."""
    label = row.get('metric_label')
    if not isinstance(label, str) or not label.strip():
        return None
    label = label.strip()
    if entry['estimate'] and not mentions_estimate(label):
        return f'{label}（估算）'
    return RESULT_METRIC_LABELS.get(label, label).strip()


def label_collisions(rows: list[dict], entries: list[dict], pairs: list[dict] = ()) -> list[dict]:
    """Unpaired long-form rows of one organization and period whose shown names agree but whose metric keys differ.

    The contract businessResults.ts labelCollisions keeps, field for field (app/tests/fixtures/label-collisions.json
    is the sample both sides assert). Rows: those in no pair whose actual has a value, as the result area pairs them.
    Organization: organization, region, 区域, the first not null, as a string. Period: period, else 期间, unformatted.
    Label: _shown_label. Key: the row's own first METRIC_FIELDS value, never the base metric a pair reads it as. Two or
    more keys under one name is a collision; groups and their keys keep first-appearance order.

    The estimate a label is shown with is the declaration's own: the row's signals and the requirements version the
    run is pinned to. Estimates the task's latest requirements add at read time (merge_latest) do not recompute the
    warning, so where they give a row 「（估算）」 the result area may tell apart a group the warning still names, or
    the other way round.
    """
    by_row = {entry['row']: entry for entry in entries}
    used = {index for pair in pairs
            if (by_row.get(pair['members'].get('actual')) or {}).get('value') not in (None, '')
            for index in pair['members'].values()}
    groups: dict[tuple[str, str, str], dict] = {}
    for row, entry in zip(rows, entries):
        if entry['row'] in used:
            continue
        label = _shown_label(row, entry)
        if label is None:
            continue
        organization = _text(_first(row, ('organization', 'region', '区域')))
        period = _text(_first(row, ('period', '期间')))
        group = groups.setdefault((organization, period, label), {
            'organization': organization, 'period': period, 'label': label, 'keys': [], 'rows': []})
        key = _text(_first(row, METRIC_FIELDS))
        if key not in group['keys']:
            group['keys'].append(key)
        group['rows'].append(entry['row'])
    return [group for group in groups.values() if len(group['keys']) >= 2]


def contract_warnings(rows: list[dict], entries: list[dict], long_format: bool, requirements: dict | None, *,
                      names_known: bool = True, pairs: list[dict] = ()) -> list[dict]:
    """Where declared rows break the result-row contract, one warning per kind in the diagnostic shape.

    Scenario and metric names are checked in a long-form table only, and only when the pinned requirements could be
    read: a name they list is part of the vocabulary. A metric outside it warns only on a row that fills a
    comparison and has no metric_label to be shown by. A pair whose variance row is not its actual minus its budget
    warns on that row, whether or not the pair would get a sentence: the rows disagree either way. Unpaired long-form
    rows that share a shown name under different metric keys (label_collisions) warn too: on screen only a key added
    after the name tells them apart.
    """
    names = vocabulary(requirements)
    scenarios = {name.lower() for name in names['scenarios']}
    hits: dict[str, list[tuple[int, str | None]]] = {
        'unit_unmarked': [], 'scenario_undeclared': [], 'metric_undeclared': [], 'estimate_basis_missing': [],
        'variance_mismatch': [], 'label_ambiguous': []}
    for row, entry in zip(rows, entries):
        index = entry['row']
        if entry['unit_kind'] == 'unmarked':
            hits['unit_unmarked'].append((index, None))
        scenario = _text(_first(row, ('scenario', '情景'))).strip()
        if (long_format and names_known and scenario and scenario.lower() not in scenarios
                and not SCENARIO_WITH_PERIOD.fullmatch(scenario.lower())):
            hits['scenario_undeclared'].append((index, scenario))
        metric = _text(entry['metric'])
        if (long_format and names_known and entry['role'] is not None and entry['scope_label'] is None
                and metric not in names['metrics']):
            hits['metric_undeclared'].append((index, metric or '（空）'))
        sources = entry['estimate_sources']
        if any(source['source'] == 'text' for source in sources) and not any(
                source['source'] == 'row' and source['field'] in BASIS_FIELDS for source in sources):
            hits['estimate_basis_missing'].append((index, None))
    by_row = {entry['row']: entry for entry in entries}
    hits['variance_mismatch'] = sorted((pair['members']['variance'], _subject(pair))
                                       for pair in pairs if _variance_mismatch(pair, by_row))
    if long_format:
        hits['label_ambiguous'] = sorted((index, group['label'])
                                         for group in label_collisions(rows, entries, pairs) for index in group['rows'])
    warnings = []
    for code, found in hits.items():
        if not found:
            continue
        found_names = list(dict.fromkeys(name for _, name in found if name is not None))
        warnings.append({
            'severity': 'warning',
            'code': code,
            'rows': [index for index, _ in found[:MAX_WARNING_ROWS]],
            'row_count': len(found),
            **({'names': found_names[:MAX_WARNING_ROWS]} if found_names else {}),
            'message': _contract_message(code, len(found), found_names),
        })
    return warnings


def pair_rows(rows: list[dict], entries: list[dict], long_format: bool, metrics: frozenset) -> list[dict]:
    """The comparisons the declared rows fill, bucketed as businessResults.ts longScenarioPairing buckets them.

    A bucket holds the rows of one metric, organization and period key, each member named by its measure and given as
    its row index. Two rows for one measure, or a year-to-date figure beside a monthly one, leave that bucket unpaired;
    an amount unit or currency that differs inside any bucket leaves the whole table unpaired. An unmarked ratio takes
    no part (KTD9). A bucket pairs when its actual and one more figure have a value. The pair is declared when the
    vocabulary names its metric; one the backend knows only from its scenario is inferred and gets no sentence.
    """
    if not long_format:
        return []
    buckets: dict[tuple, dict] = {}
    for row, entry in zip(rows, entries):
        if entry['role'] is None or entry['unit_kind'] == 'unmarked':
            continue
        measure = _comparison(json_value(row))['measure']
        key = (_text(entry['metric']), _text(entry['organization']), entry['period_key'])
        bucket = buckets.setdefault(key, {'entries': [], 'units': set(), 'currencies': set(), 'spans': set()})
        bucket['entries'].append((measure, entry))
        if entry['span']:
            bucket['spans'].add(entry['span'])
        if ROLES[measure] != 'ratio':
            currency = _text(_first(row, ('currency', '币种'))).strip()
            bucket['units'].update([entry['unit']] if entry['unit'] else [])
            bucket['currencies'].update([currency] if currency else [])
    if any(len(bucket['units']) > 1 or len(bucket['currencies']) > 1 for bucket in buckets.values()):
        return []
    pairs = []
    for (metric, _, period_key), bucket in buckets.items():
        measures = [measure for measure, _ in bucket['entries']]
        if len(set(measures)) < len(measures) or len(bucket['spans']) > 1:
            continue
        values = {measure: entry['value'] for measure, entry in bucket['entries']}
        if values.get('actual') is None or all(
                value is None for measure, value in values.items() if measure != 'actual'):
            continue
        first = bucket['entries'][0][1]
        pairs.append({
            'metric': metric,
            'organization': first['organization'],
            'period': first['period'],
            'period_key': period_key,
            'span': next(iter(bucket['spans']), None),
            'unit': next(iter(bucket['units']), None),
            'members': {measure: entry['row'] for measure, entry in bucket['entries']},
            'declared': metric in metrics,
        })
    return pairs


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(value.strip() if isinstance(value, str) else str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _plain(value: Decimal) -> str:
    return format(value, 'f')


def _shown(value: Decimal) -> str:
    """A figure as the cards show it: two places, half away from zero, thousands grouped (decimalToFixed)."""
    with localcontext() as context:
        context.prec = CONCLUSION_PRECISION
        return format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), ',f')


def _period_phrase(pair: dict) -> str:
    """The period a sentence opens with: the scenario's own suffix (1_8 is 1-8 月), else the row's period."""
    period, _, suffix = _text(pair['period_key']).rpartition('|')
    months = re.fullmatch(r'(\d{1,2})_(\d{1,2})', suffix)
    if months:
        first, last = int(months.group(1)), int(months.group(2))
        return f'{first} 月' if first == last else f'{first}-{last} 月'
    month = re.fullmatch(r'(\d{4})_(\d{2})', suffix)
    if month:
        return f'{month.group(1)} 年 {int(month.group(2))} 月'
    if not period:
        return ''
    return f"{period} {'累计' if pair['span'] == 'ytd' else '单月' if pair['span'] == 'month' else ''}"


def _subject(pair: dict) -> str:
    """What a pair's sentence is about: its period, organization and metric (1-8 月集团合并收入)."""
    metric = RESULT_METRIC_LABELS.get(pair['metric'], pair['metric'])
    return f"{_period_phrase(pair)}{_text(pair['organization'])}{metric}"


def _variance_mismatch(pair: dict, entries: dict[int, dict]) -> bool:
    """Whether the pair's variance row states other than its actual minus its one budget, in Decimal.

    Without a variance row, beside both an approved and an estimated budget, or with a figure that is not a number
    or a difference that cannot be held exactly, there is nothing to hold the row against.
    """
    members = {measure: entries.get(index) or {} for measure, index in pair['members'].items()}
    if 'variance' not in members or 'actual' not in members or ('budget' in members) == ('estimated_budget' in members):
        return False
    budget = members['budget' if 'budget' in members else 'estimated_budget']
    actual, budget, stated = (_decimal(entry.get('value'))
                              for entry in (members['actual'], budget, members['variance']))
    if None in (actual, budget, stated):
        return False
    try:
        with localcontext() as context:
            context.prec, context.traps[Inexact] = CONCLUSION_PRECISION, True
            difference = actual - budget
    except Inexact:
        return False
    places = stated.as_tuple().exponent
    if isinstance(places, int) and places > difference.as_tuple().exponent:
        # A variance written to fewer places agrees when the exact difference rounds to it.
        with localcontext() as context:
            context.prec = CONCLUSION_PRECISION
            difference = difference.quantize(Decimal(1).scaleb(places), rounding=ROUND_HALF_UP)
    return stated != difference


def _pair_estimate(pair: dict, entries: dict[int, dict]) -> dict:
    measures = [measure for measure, index in pair['members'].items() if (entries.get(index) or {}).get('estimate')]
    return {'estimated': bool(measures), 'measures': measures}


def _conclusion(pair: dict, entries: dict[int, dict], complete: bool) -> dict | None:
    """One sentence for a pair whose every member is declared, in a complete declaration (KTD7).

    It says the variance the variance row states, or actual minus budget in Decimal without one; the 达成率 the ratio
    row states, by its declared unit; and which of the figures it uses are estimates. An approved and an estimated
    budget in one pair leave open which one the variance is against, so such a pair says nothing; nor does one whose
    variance row is not actual minus budget, since the sentence would contradict the figures it quotes.
    """
    members = {measure: entries.get(index) for measure, index in pair['members'].items()}
    if not complete or not pair['declared'] or any(
            entry is None or entry['role'] != ROLES[measure] or entry['unit_kind'] == 'unmarked'
            for measure, entry in members.items()):
        return None
    if 'actual' not in members or ('budget' in members) == ('estimated_budget' in members):
        return None
    used = ['actual', 'budget' if 'budget' in members else 'estimated_budget']
    actual, budget = _decimal(members[used[0]]['value']), _decimal(members[used[1]]['value'])
    rate = next((measure for measure in ('rate', 'rate_pct') if measure in members), None)
    stated = {measure: _decimal(members[measure]['value']) for measure in ('variance', rate) if measure in members}
    if actual is None or budget is None or None in stated.values() or _variance_mismatch(pair, entries):
        return None
    try:
        with localcontext() as context:
            context.prec, context.traps[Inexact] = CONCLUSION_PRECISION, True
            variance = stated['variance'] if 'variance' in stated else actual - budget
            percent = None if rate is None else (
                stated[rate].scaleb(2) if members[rate]['unit_kind'] == 'decimal' else stated[rate])
    except Inexact:
        return None
    used += [measure for measure in ('variance', rate) if measure in stated]
    unit = f" {pair['unit']}" if pair['unit'] else ''
    organization = _text(pair['organization'])
    change = '与预算持平' if variance == 0 else (
        f"比预算{'少' if variance < 0 else '多'} {_shown(variance.copy_abs())}{unit}")
    text = (f"{_subject(pair)}{change}"
            f"{'' if percent is None else f'（达成 {_shown(percent)}%）'}"
            f"，实际 {_shown(actual)}{unit}，预算 {_shown(budget)}{unit}")
    estimated = list(dict.fromkeys(MEASURE_WORDS[measure] for measure in used if members[measure]['estimate']))
    if estimated:
        text += f"；{organization}{'、'.join(estimated)}为估算"
    return {
        'text': text,
        'basis': CONCLUSION_BASIS,
        'verified': False,
        'values': {'actual': _plain(actual), 'budget': _plain(budget), 'variance': _plain(variance),
                   **({} if percent is None else {'ratio_percent': _plain(percent)})},
        'variance_from': 'row' if 'variance' in stated else 'computed',
    }


def conclude_pairs(pairs: list[dict], entries: list[dict], complete: bool) -> list[dict]:
    """Each pair with its estimates and its sentence, read from the declared rows as they now stand."""
    by_row = {entry['row']: entry for entry in entries}
    return [{**pair, 'estimate': _pair_estimate(pair, by_row), 'conclusion': _conclusion(pair, by_row, complete)}
            for pair in pairs]


def declare_rows(columns: list, rows: list[dict], requirements: dict | None, *, fingerprint: str | None,
                 complete: bool = True, incomplete_reason: str | None = None) -> dict:
    """A declaration of `rows`, which must be the full result table unless `complete` says otherwise."""
    long_format = _long_format(columns)
    declared = rows[:MAX_DECLARED_ROWS]
    if len(rows) > MAX_DECLARED_ROWS and complete:
        complete, incomplete_reason = False, 'too_many_rows'
    entries = [_declare_row(index, row, long_format, requirements) for index, row in enumerate(declared)]
    pairs = pair_rows(declared, entries, long_format, vocabulary(requirements)['metrics'])
    return {
        'rules_version': rules_version(),
        'requirements_id': (requirements or {}).get('id'),
        'requirements_fingerprint': fingerprint,
        'complete': complete,
        'incomplete_reason': None if complete else incomplete_reason,
        'row_count': len(rows),
        'rows': entries,
        'pairs': conclude_pairs(pairs, entries, complete),
        'warnings': contract_warnings(declared, entries, long_format, requirements,
                                      names_known=incomplete_reason != 'requirements_unavailable', pairs=pairs),
    }


def declare_script_result(analysis, columns: list, rows: list[dict], requirements_id: str | None, *,
                          allowed: set[str] | None = None) -> dict:
    """The declaration a script run saves: its full result rows read against its pinned requirements, with the
    fingerprint the saver (``allowed``, a session's snapshot ceiling; None: the manager) reads them with
    (AnalysisStore.fingerprint_in_view)."""
    try:
        requirements = analysis._get('requirements', requirements_id) if requirements_id else None
    except FoundryError:
        declaration = declare_rows(columns, rows, None, fingerprint=None, complete=False,
                                   incomplete_reason='requirements_unavailable')
        return {**declaration, 'requirements_id': requirements_id}
    return declare_rows(columns, rows, requirements, fingerprint=analysis.fingerprint_in_view(requirements, allowed))


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


def _pinned_requirements(analysis, requirements_id: str | None, cache: dict[str, dict | None]) -> dict | None:
    """The requirements record a declaration is pinned to, read once per state read: records are immutable."""
    if not requirements_id:
        return None
    if requirements_id not in cache:
        try:
            cache[requirements_id] = analysis._get('requirements', requirements_id)
        except FoundryError:
            cache[requirements_id] = None
    return cache[requirements_id]


def redeclare(analysis, run: dict, requirements_cache: dict[str, dict | None] | None = None) -> dict:
    """Recompute a stored declaration under the current rules; the run record itself is never rewritten.

    The pinned requirements and their fingerprint are the stored ones: the requirements record is immutable.
    Without the full result file, the stored preview rows are declared and the declaration is incomplete.
    """
    stored = run['row_declarations']
    requirements_id = stored.get('requirements_id')
    requirements = _pinned_requirements(analysis, requirements_id, {} if requirements_cache is None else requirements_cache)
    columns, rows, archived = _result_table(analysis, run)
    if requirements_id and requirements is None:
        complete, reason = False, 'requirements_unavailable'
    else:
        complete, reason = archived, None if archived else 'result_file_unavailable'
    declaration = declare_rows(columns, rows, requirements, fingerprint=stored.get('requirements_fingerprint'),
                               complete=complete, incomplete_reason=reason)
    return {**declaration, 'requirements_id': requirements_id}


def _result_table(analysis, run: dict) -> tuple[list, list[dict], bool]:
    """The run's full result table from its archived output, else its stored preview (False: not the full table)."""
    archived = _archived_result(analysis, run)
    result = run.get('result') or {}
    columns, rows = archived or (result.get('columns') or [], result.get('rows') or [])
    return columns, rows, archived is not None


def declare_against(analysis, run: dict, requirements: dict | None, fingerprint: str | None) -> dict:
    """The declaration run_script saves for this run's result had it been pinned to `requirements` (None: no version),
    `fingerprint` being that record's verified fingerprint. A reader that may not read the version a run was pinned
    to reads its declaration so (AnalysisStore.run_in_view); without the full result file, the stored preview rows
    are declared and the declaration is incomplete."""
    columns, rows, archived = _result_table(analysis, run)
    return declare_rows(columns, rows, requirements, fingerprint=fingerprint, complete=archived,
                        incomplete_reason=None if archived else 'result_file_unavailable')


def _latest_memo(latest: dict | None) -> dict:
    """What merge_latest reads from one latest requirements record, kept across the runs of one state read: whether
    it declares any estimate grain, and the sources it gives each distinct set of row fields."""
    return {'estimate_grains': _has_estimate_grains(latest), 'sources': {}}


def merge_latest(declaration: dict, latest: dict | None, memo: dict | None = None) -> dict:
    """Add the estimates the task's latest requirements declare; nothing the declaration holds is removed.

    The pairs are kept; their estimates and sentences are read again from the merged rows. `memo` (_latest_memo of
    the same `latest`) lets runs read together match rows with the same fields against it once.
    """
    if not latest or latest.get('id') == declaration.get('requirements_id'):
        return declaration
    memo = _latest_memo(latest) if memo is None else memo
    if not memo['estimate_grains']:
        return declaration
    rows = []
    for entry in declaration.get('rows') or []:
        fields = entry.get('fields') or {}
        # repr tells 1 from 1.0, True and '1', which equal tuple keys would not.
        key = repr(sorted(fields.items()))
        if key not in memo['sources']:
            memo['sources'][key] = _declared_sources(latest, fields)
        added = [dict(source) for source in memo['sources'][key] if source not in entry.get('estimate_sources', [])]
        rows.append({**entry, 'estimate': True, 'estimate_sources': [*entry.get('estimate_sources', []), *added]}
                    if added else entry)
    pairs = conclude_pairs(declaration.get('pairs') or [], rows, declaration.get('complete') is True)
    return {**declaration, 'rows': rows, 'pairs': pairs, 'latest_requirements_id': latest['id']}


def declared_run(analysis, run: dict, latest: dict | None, latest_fingerprint: str | None = None,
                 requirements_cache: dict[str, dict | None] | None = None, latest_memo: dict | None = None) -> dict:
    """The run as the workbench reads it: a stale declaration recomputed, the latest estimates merged in.

    It also names the task's current requirements version and that record's verified fingerprint, so the result
    area can tell a declaration read against an older version of the requirements from a resave that changed
    nothing they mean (R4).
    """
    declaration = run.get('row_declarations')
    if not isinstance(declaration, dict):
        return run
    if is_stale(declaration.get('rules_version')):
        declaration = redeclare(analysis, run, requirements_cache)
    declaration = merge_latest(declaration, latest, latest_memo)
    if latest:
        declaration = {**declaration, 'current_requirements': {'id': latest['id'], 'fingerprint': latest_fingerprint}}
    return run if declaration is run['row_declarations'] else {**run, 'row_declarations': declaration}


def declared_runs(analysis, runs: list[dict], latest: dict | None) -> list[dict]:
    from foundry.finance_requirement_semantics import verified_requirement_fingerprint

    fingerprint = (verified_requirement_fingerprint(analysis, latest)
                   if latest and any(isinstance(run.get('row_declarations'), dict) for run in runs) else None)
    requirements_cache: dict[str, dict | None] = {}
    memo = _latest_memo(latest)
    return [declared_run(analysis, run, latest, fingerprint, requirements_cache, memo) for run in runs]
