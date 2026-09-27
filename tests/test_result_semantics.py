"""Row declarations: what the backend states about each script result row when the run is saved.

A declaration sits beside the stored result (never inside it), so a script run's output_hash and result stay
byte-identical to the values saved before declarations existed. It is computed from the full result file, reads
grain_basis from the requirements version the run is pinned to, and at read time adds (never removes) the estimates
the task's latest requirements declare.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from foundry import result_semantics
from foundry.analysis import AnalysisStore, _bytes
from foundry.finance_requirements import save_requirements
from foundry.result_semantics import declare_rows, vocabulary
from foundry.task import TaskStore

BASE = {'currency': 'CNY', 'period': '2026-01:2026-08', 'source': '预算工作簿 09·预算执行分析；月结套表 04·合并利润表'}
# Huachen's long form in miniature (runs 84b65b7d / 269d9fd9): a group pair with its own variance and 达成率 rows,
# a full-year budget that pairs with nothing, a regional budget labelled 推算, and a regional budget whose label
# says nothing about how it was made (its estimate is declared only in grain_basis).
HUACHEN_ROWS = [
    {**BASE, 'metric_key': 'revenue', 'organization': '集团合并', 'scenario': 'actual_1_8', 'value': '325644.0000',
     'unit': '万元', 'metric_label': '营业收入 1-8 月实际'},
    {**BASE, 'metric_key': 'revenue', 'organization': '集团合并', 'scenario': 'budget_1_8', 'value': '344487.0552',
     'unit': '万元', 'metric_label': '营业收入 1-8 月预算'},
    {**BASE, 'metric_key': 'revenue_variance', 'organization': '集团合并', 'scenario': 'variance_1_8',
     'value': '-18843.0552', 'unit': '万元', 'metric_label': '营业收入差异'},
    {**BASE, 'metric_key': 'revenue_achievement_ratio', 'organization': '集团合并', 'scenario': 'budget_1_8',
     'value': '0.945301', 'unit': '比率', 'metric_label': '营业收入达成率'},
    {**BASE, 'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026', 'scenario': 'budget_bud_fy',
     'value': '527999.9999', 'unit': '万元', 'metric_label': '全年年初批复预算'},
    {**BASE, 'metric_key': 'revenue', 'organization': '华东区域', 'scenario': 'actual_1_8', 'value': '109742.0280',
     'unit': '万元', 'metric_label': '营业收入 1-8 月实际'},
    {**BASE, 'metric_key': 'revenue', 'organization': '华东区域', 'scenario': 'budget_1_8', 'value': '117814.5729',
     'unit': '万元', 'metric_label': '营业收入 1-8 月预算（推算：集团进度率×区域全年预算）'},
    {**BASE, 'metric_key': 'revenue_variance', 'organization': '华东区域', 'scenario': 'variance_1_8',
     'value': '-8072.5449', 'unit': '万元', 'metric_label': '营业收入差异'},
    {**BASE, 'metric_key': 'profit', 'organization': '华南区域', 'scenario': 'actual_1_8', 'value': '5210.1100',
     'unit': '万元', 'metric_label': '营业利润 1-8 月实际'},
    {**BASE, 'metric_key': 'profit', 'organization': '华南区域', 'scenario': 'budget_1_8', 'value': '6021.3300',
     'unit': '万元', 'metric_label': '营业利润 1-8 月预算'},
    {**BASE, 'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026-08', 'scenario': 'actual_2026_08',
     'value': '41469.6250', 'unit': '万元', 'metric_label': '8 月单月实际'},
    {**BASE, 'metric_key': 'revenue', 'organization': '集团合并', 'period': '2026-08', 'scenario': 'budget_2026_08',
     'value': '44163.6526', 'unit': '万元', 'metric_label': '8 月单月预算'},
]
# Captured on the base commit (2f0a099), before declarations existed: the same script's output_hash and the
# canonical bytes of its stored result. A declaration must leave both exactly as they were.
PRE_CHANGE_OUTPUT_HASH = 'f076a2df57c7d5c7a74b6adb47bc0bb771a7f16c1b28a2d380e1d280c2a60983'
PRE_CHANGE_RESULT_SHA256 = '0c56de185303826846165da9eac517b8d20e2bbcdb5ff52a59ffc9e9da91e527'


def script_writing(rows, name='result.json'):
    """A deterministic script that writes `rows` as its result table."""
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return (
        'from pathlib import Path\n'
        f'Path({name!r}).write_text({payload!r}, encoding="utf-8")\n'
        "print('rows written')\n"
    )


@pytest.fixture
def analysis(tmp_path):
    return AnalysisStore(TaskStore(tmp_path / 'var').create(title='行声明'))


def run_rows(analysis, rows, **spec):
    run = analysis.run_script({'code': script_writing(rows), 'bindings': {}, 'result_file': 'result.json', **spec})
    if run.get('runner_status') == 'unavailable':
        pytest.skip('OS-isolated runner unavailable')
    assert run['execution_status'] == 'succeeded', run
    return run


def result_sha256(run):
    return hashlib.sha256(_bytes(run['result'])).hexdigest()


def test_script_run_carries_a_declaration_beside_an_unchanged_output_hash(analysis):
    run = run_rows(analysis, HUACHEN_ROWS)

    assert run['output_hash'] == PRE_CHANGE_OUTPUT_HASH
    assert result_sha256(run) == PRE_CHANGE_RESULT_SHA256
    assert 'row_declarations' not in run['result']
    declaration = run['row_declarations']
    assert declaration['complete'] is True
    assert declaration['row_count'] == len(HUACHEN_ROWS)


PRE_DECLARATION_TASK = Path(__file__).parent / 'fixtures' / 'pre_declaration_task'
PRE_DECLARATION_IDS = {'task': '1ba2d5a16dfc49d1acda6cdb31134b96', 'run': '82e878aba2d1498fad465c474f68dece',
                       'analysis': '7ff3ce9aedcc4699b15b4f08bde4ada3'}


@pytest.fixture
def pre_declaration(tmp_path):
    """The task a base-commit build saved: one script version of HUACHEN_ROWS and its run, with no declaration."""
    shutil.copytree(PRE_DECLARATION_TASK, tmp_path / 'var')
    return AnalysisStore(TaskStore(tmp_path / 'var').get(PRE_DECLARATION_IDS['task']))


def test_rerunning_a_version_saved_before_declarations_keeps_its_output_byte_identical(pre_declaration):
    saved = pre_declaration.get_run(PRE_DECLARATION_IDS['run'])
    assert 'row_declarations' not in saved

    rerun = pre_declaration.run_analysis(PRE_DECLARATION_IDS['analysis'])
    if rerun.get('runner_status') == 'unavailable':
        pytest.skip('OS-isolated runner unavailable')

    assert rerun['output_hash'] == saved['output_hash'] == PRE_CHANGE_OUTPUT_HASH
    assert _bytes(rerun['result']) == _bytes(saved['result'])
    assert rerun['reproducibility_status'] == saved['reproducibility_status']
    assert rerun['execution_status'] == saved['execution_status'] == 'succeeded'
    assert rerun['row_declarations']['complete'] is True
    # The run saved before declarations keeps its inference: it is returned as it was stored.
    state_runs = {run['id']: run for run in pre_declaration.state()['runs']}
    assert state_runs[saved['id']] == saved


COLUMNS = list(dict.fromkeys(key for row in HUACHEN_ROWS for key in row))


def declare(rows, requirements=None, columns=COLUMNS):
    return declare_rows(columns, rows, requirements, fingerprint=None)


def by_row(declaration):
    return {entry['row']: entry for entry in declaration['rows']}


def estimate_grains(item_id, metric, organizations, scenarios=('budget_1_8',)):
    """A requirements item declaring its regional budget grains an estimate, as requirements 692ab0b6 does."""
    return {'id': item_id, 'metric': metric, 'organizations': ['集团合并', *organizations],
            'periods': ['2026-01:2026-08'], 'scenarios': ['actual_1_8', 'budget_1_8'],
            'grain_basis': [{'basis': 'estimate', 'method': '区域全年预算 × 集团 1-8 月预算进度',
                             'organizations': list(organizations), 'periods': ['2026-01:2026-08'],
                             'scenarios': list(scenarios)}]}


def test_huachen_long_form_rows_get_roles_and_period_keys():
    rows = by_row(declare(HUACHEN_ROWS))
    group = '2026-01:2026-08|1_8'
    expected = {
        0: ('actual', 'revenue', group), 1: ('budget', 'revenue', group),
        2: ('variance', 'revenue', group), 3: ('ratio', 'revenue', group),
        5: ('actual', 'revenue', group), 6: ('budget', 'revenue', group), 7: ('variance', 'revenue', group),
        8: ('actual', 'profit', group), 9: ('budget', 'profit', group),
        10: ('actual', 'revenue', '2026-08|2026_08'), 11: ('budget', 'revenue', '2026-08|2026_08'),
    }
    assert {index: (rows[index]['role'], rows[index]['metric'], rows[index]['period_key'])
            for index in expected} == expected
    # A full-year BUD pairs with nothing: it is declared, without a role.
    assert (rows[4]['role'], rows[4]['period_key']) == (None, None)
    assert rows[3]['unit_kind'] == 'decimal' and rows[0]['unit_kind'] == 'amount'
    assert [rows[index]['organization'] for index in (0, 5, 8)] == ['集团合并', '华东区域', '华南区域']
    # Amounts stay the Decimal strings the script wrote.
    assert rows[6]['value'] == '117814.5729' and rows[3]['value'] == '0.945301'
    assert rows[1]['scope_label'] == '营业收入 1-8 月预算'


def test_regional_budget_labelled_推算_is_an_estimate_from_its_text_without_grain_basis():
    rows = by_row(declare(HUACHEN_ROWS))
    assert rows[6]['estimate'] is True
    assert rows[6]['estimate_sources'] == [{'source': 'text', 'field': 'metric_label'}]
    assert [index for index, entry in rows.items() if entry['estimate']] == [6]


def test_grain_basis_estimate_marks_a_row_whose_label_says_nothing():
    requirements = {'id': 'a' * 32, 'items': [estimate_grains('profit_1_8', 'profit', ['华南区域'])]}
    rows = by_row(declare(HUACHEN_ROWS, requirements))
    assert rows[9]['estimate'] is True
    assert rows[9]['estimate_sources'] == [{'source': 'declared', 'requirements_id': 'a' * 32, 'item_id': 'profit_1_8'}]
    # Only the declared grain: the actual beside it and the group budget are not estimates.
    assert rows[8]['estimate'] is False and rows[1]['estimate'] is False


@pytest.mark.parametrize('label', ['营业收入 1-8 月预算（非估算）', '营业收入 1-8 月预算（不含估算调整）',
                                   '批复预算，并非推算', '预算未估计'])
def test_negated_estimate_words_do_not_mark_an_estimate(label):
    row = {**HUACHEN_ROWS[1], 'metric_label': label}
    assert declare([row])['rows'][0]['estimate'] is False


def test_an_unnegated_estimate_word_after_a_negated_one_still_counts():
    row = {**HUACHEN_ROWS[1], 'metric_label': '集团数非估算，区域数为推算'}
    assert declare([row])['rows'][0]['estimate_sources'] == [{'source': 'text', 'field': 'metric_label'}]


@pytest.mark.parametrize(('update', 'field'), [
    ({'basis': 'estimate'}, 'basis'),
    ({'row_basis': 'estimated'}, 'row_basis'),
    ({'估算方法': '区域全年预算 × 集团进度率'}, '估算方法'),
    ({'scenario': 'estimated_budget'}, 'scenario'),
])
def test_row_basis_method_and_estimated_scenario_mark_an_estimate_without_estimate_words(update, field):
    row = {**HUACHEN_ROWS[9], **update}
    columns = [*COLUMNS, *update]
    entry = declare([row], columns=columns)['rows'][0]
    assert entry['estimate'] is True
    assert entry['estimate_sources'] == [{'source': 'row', 'field': field}]
    assert entry['role'] == 'budget'


@pytest.mark.parametrize('method', ['无', '-', 'N/A', ''])
def test_an_empty_estimate_method_is_not_an_estimate(method):
    row = {**HUACHEN_ROWS[9], '估算方法': method}
    assert declare([row], columns=[*COLUMNS, '估算方法'])['rows'][0]['estimate'] is False


def test_unit_table_decides_ratio_units_and_an_unmarked_ratio_is_never_an_amount():
    percent = {**HUACHEN_ROWS[3], 'unit': '%', 'value': '94.5301'}
    unmarked = {**HUACHEN_ROWS[3], 'unit': '-'}
    unmarked_budget = {**HUACHEN_ROWS[1], 'unit': '-'}
    rows = declare([percent, unmarked, unmarked_budget])['rows']
    assert [(entry['role'], entry['unit_kind']) for entry in rows] == [
        ('ratio', 'percent'), ('ratio', 'unmarked'), (None, 'unmarked')]


def test_vocabulary_adds_the_names_the_pinned_requirements_list():
    requirements = {'id': 'a' * 32, 'items': [{'id': 'fy', 'metric': '经营现金流', 'scenarios': ['budget_bud_fy']}]}
    names = vocabulary(requirements)
    assert 'budget_bud_fy' in names['scenarios'] and 'budget_bud_fy' not in vocabulary()['scenarios']
    assert '经营现金流' in names['metrics'] and 'revenue' in names['metrics']


def plain_items():
    return [{'id': item_id, 'metric': metric, 'label': label, 'organizations': ['集团合并', '华东区域', '华南区域'],
             'periods': ['2026-01:2026-08'], 'scenarios': ['actual_1_8', 'budget_1_8'], 'requires_drilldown': False}
            for item_id, metric, label in (('revenue_1_8', 'revenue', '1-8 月营业收入'),
                                           ('profit_1_8', 'profit', '1-8 月营业利润'))]


def with_estimate(items, item_id, organizations):
    declared = {'basis': 'estimate', 'method': '区域全年预算 × 集团 1-8 月预算进度',
                'organizations': organizations, 'periods': ['2026-01:2026-08'], 'scenarios': ['budget_1_8']}
    return [{**item, 'grain_basis': [declared]} if item['id'] == item_id else item for item in items]


@pytest.fixture
def requirements(analysis, tmp_path):
    """Saves requirements versions bound to one budget snapshot, as the assistant does (parent_id after the first)."""
    source = tmp_path / 'budget.json'
    source.write_text(json.dumps([{'organization': '华东区域', 'budget': '188503.3'}], ensure_ascii=False))
    budget = analysis.add_dataset(source, name='budget')

    def save(items, parent=None):
        return save_requirements(analysis, {
            'question': '1-8 月收入与营业利润的实际与同期预算', 'scope': {'currency': 'CNY', 'unit': '万元'},
            'bindings': {'budget': budget['id']}, 'items': items, **({'parent_id': parent['id']} if parent else {})})
    return save


def run_file(analysis, run):
    return analysis._object_path('runs', run['id'])


def state_run(analysis, run):
    return next(item for item in analysis.state()['runs'] if item['id'] == run['id'])


def test_declaration_reads_the_full_result_file_past_the_stored_preview(analysis):
    # 1200 detail rows that pair with nothing, 华东's actual/budget/variance at rows 1200-1202, 297 more after.
    code = (
        'import json\nfrom pathlib import Path\n'
        f'base = {json.dumps(BASE, ensure_ascii=False)!r}\n'
        f'pair = {json.dumps(HUACHEN_ROWS[5:8], ensure_ascii=False)!r}\n'
        "detail = [dict(json.loads(base), metric_key='line_%d' % i, organization='集团合并', scenario='actual_py_1_8',\n"
        "               value='%d.0000' % i, unit='万元', metric_label='明细') for i in range(1200)]\n"
        "rows = detail + json.loads(pair) + detail[:297]\n"
        "Path('result.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')\n"
    )
    run = analysis.run_script({'code': code, 'bindings': {}, 'result_file': 'result.json'})
    if run.get('runner_status') == 'unavailable':
        pytest.skip('OS-isolated runner unavailable')
    assert run['execution_status'] == 'succeeded', run

    assert run['result']['truncated'] is True and len(run['result']['rows']) == 1000
    declaration = run['row_declarations']
    assert declaration['complete'] is True and declaration['row_count'] == 1500
    declared = by_row(declaration)
    assert len(declared) == 1500
    assert [(declared[index]['role'], declared[index]['period_key']) for index in (1200, 1201, 1202)] == [
        ('actual', '2026-01:2026-08|1_8'), ('budget', '2026-01:2026-08|1_8'), ('variance', '2026-01:2026-08|1_8')]
    assert declared[1201]['estimate'] is True


def test_without_the_full_result_file_a_recomputed_declaration_is_incomplete(analysis, monkeypatch):
    run = run_rows(analysis, HUACHEN_ROWS)
    analysis._inside(analysis.root / run['outputs'][0]['artifact_path']).unlink()
    monkeypatch.setattr(result_semantics, 'VOCABULARY_VERSION', result_semantics.VOCABULARY_VERSION + 1)

    declaration = state_run(analysis, run)['row_declarations']
    assert declaration['complete'] is False
    assert declaration['incomplete_reason'] == 'result_file_unavailable'
    # What the stored preview holds is still declared under the current rules.
    assert declaration['rules_version'] == result_semantics.rules_version()
    assert by_row(declaration)[6]['estimate'] is True


def test_requirements_revised_after_the_run_leave_the_declaration_on_the_run_version(analysis, requirements):
    first = requirements(plain_items())
    run = run_rows(analysis, HUACHEN_ROWS)
    requirements(with_estimate(plain_items(), 'profit_1_8', ['华南区域']), parent=first)

    for stored in (analysis.get_run(run['id']), state_run(analysis, run)):
        declaration = stored['row_declarations']
        assert declaration['requirements_id'] == first['id'] == stored['requirements_id']
        assert declaration['requirements_fingerprint'] == first['semantic_fingerprint'] is not None


def test_grain_basis_saved_after_the_run_marks_the_budget_an_estimate_at_read_time(analysis, requirements):
    first = requirements(plain_items())
    run = run_rows(analysis, HUACHEN_ROWS)
    assert by_row(run['row_declarations'])[9]['estimate'] is False
    before = run_file(analysis, run).read_bytes()
    latest = requirements(with_estimate(plain_items(), 'profit_1_8', ['华南区域']), parent=first)

    declaration = state_run(analysis, run)['row_declarations']
    south = by_row(declaration)[9]
    assert south['estimate'] is True
    assert south['estimate_sources'] == [{'source': 'declared', 'requirements_id': latest['id'], 'item_id': 'profit_1_8'}]
    # The run stays pinned to the version it ran against; the record itself is untouched.
    assert declaration['requirements_id'] == first['id']
    assert declaration['latest_requirements_id'] == latest['id']
    assert run_file(analysis, run).read_bytes() == before
    assert 'latest_requirements_id' not in analysis.get_run(run['id'])['row_declarations']


def test_rerun_of_a_version_bound_to_old_requirements_declares_against_the_old_version(analysis, requirements):
    old = requirements(with_estimate(plain_items(), 'profit_1_8', ['华南区域']))
    first = run_rows(analysis, HUACHEN_ROWS, requirements_id=old['id'])
    new = requirements(with_estimate(plain_items(), 'revenue_1_8', ['集团合并']), parent=old)
    assert new['semantic_fingerprint'] != old['semantic_fingerprint']

    rerun = analysis.run_analysis(first['analysis_id'])
    declaration = rerun['row_declarations']
    assert rerun['requirements_id'] == declaration['requirements_id'] == old['id']
    # The run-level fingerprint is captured from the latest requirements; the declaration's is the old version's.
    assert rerun['requirements_semantic_fingerprint'] == new['semantic_fingerprint']
    assert declaration['requirements_fingerprint'] == old['semantic_fingerprint']
    declared = by_row(declaration)
    assert declared[9]['estimate_sources'] == [{'source': 'declared', 'requirements_id': old['id'], 'item_id': 'profit_1_8'}]
    assert declared[1]['estimate'] is False
    assert all(source.get('requirements_id') in (None, old['id'])
               for entry in declared.values() for source in entry['estimate_sources'])


def test_a_bumped_rules_version_returns_a_recomputed_declaration_and_leaves_the_record_file(analysis, monkeypatch):
    run = run_rows(analysis, HUACHEN_ROWS)
    before = run_file(analysis, run).read_bytes()
    assert by_row(run['row_declarations'])[11]['estimate'] is False
    # New estimate wording, released with a new estimate-words version.
    monkeypatch.setattr(result_semantics, 'ESTIMATE_WORDS', re.compile(r'估算|推算|预估|估计|测算|单月预算|estimat', re.I))
    monkeypatch.setattr(result_semantics, 'ESTIMATE_WORDS_VERSION', result_semantics.ESTIMATE_WORDS_VERSION + 1)

    declaration = state_run(analysis, run)['row_declarations']
    assert declaration['rules_version'] == result_semantics.rules_version() != run['row_declarations']['rules_version']
    assert declaration['complete'] is True and declaration['row_count'] == len(HUACHEN_ROWS)
    assert by_row(declaration)[11]['estimate_sources'] == [{'source': 'text', 'field': 'metric_label'}]
    assert run_file(analysis, run).read_bytes() == before
    assert analysis.get_run(run['id'])['row_declarations'] == run['row_declarations']


def test_a_current_declaration_is_returned_as_stored(analysis):
    run = run_rows(analysis, HUACHEN_ROWS)
    assert state_run(analysis, run) == analysis.get_run(run['id'])


FRONTEND_RESULTS = Path(__file__).resolve().parents[1] / 'app' / 'src' / 'views' / 'analysis' / 'businessResults.ts'


def _ts_strings(text):
    return re.findall(r"'([^']*)'", text)


def _ts_declaration(source, name):
    match = re.search(rf'const {name}\b[^=]*=\s*(.+?);\n', source, re.S)
    assert match, f'businessResults.ts no longer declares {name}'
    return match.group(1)


def _ts_regex(text):
    match = re.search(r'/(.+?)/[gimsuy]*(?:;|\.exec|$)', text)
    assert match, text
    return match.group(1)


def test_backend_vocabulary_agrees_with_the_frontend_inference_lists():
    """The frontend keeps its copy only to infer runs saved without declarations; the two must not drift."""
    source = FRONTEND_RESULTS.read_text(encoding='utf-8')
    measure = source[source.index('function longScenarioMeasure'):source.index('function longScenarioEntry')]
    lists = {name: tuple(_ts_strings(names)) for names, name in
             re.findall(r"if \(\[([^\]]*)\]\.includes\(scenario\)\) return \{ measure: '(\w+)'", measure)}
    assert lists == result_semantics.LONG_SCENARIO_MEASURES
    assert _ts_regex(_ts_declaration(source, 'scenarioWithPeriod')) == result_semantics.SCENARIO_WITH_PERIOD.pattern
    entry = source[source.index('function longScenarioEntry'):source.index('function scenarioDetailLabel')]
    assert _ts_regex(entry[entry.index('const rate ='):]) == result_semantics.RATE_METRIC.pattern
    assert _ts_regex(entry[entry.index('const variance ='):]) == result_semantics.VARIANCE_METRIC.pattern

    fraction = set(_ts_strings(_ts_declaration(source, 'fractionUnits')))
    ratio = _ts_declaration(source, 'ratioUnits')
    assert '...fractionUnits' in ratio
    assert fraction == result_semantics.FRACTION_UNITS
    assert set(_ts_strings(ratio)) == result_semantics.PERCENT_UNITS
    if re.search(r'const unmarkedUnits\b', source):
        assert set(_ts_strings(_ts_declaration(source, 'unmarkedUnits'))) == result_semantics.UNMARKED_UNITS

    assert _ts_regex(_ts_declaration(source, 'estimateWords')) == result_semantics.ESTIMATE_WORDS.pattern
    assert tuple(_ts_strings(_ts_declaration(source, 'negations'))) == result_semantics.NEGATIONS
    assert set(_ts_strings(_ts_declaration(source, 'noMethod'))) == result_semantics.NO_METHOD
    assert tuple(_ts_strings(_ts_declaration(source, 'basisFields'))) == result_semantics.BASIS_FIELDS
    assert set(_ts_strings(_ts_declaration(source, 'estimateBasisValues'))) == result_semantics.ESTIMATE_BASIS_VALUES
    declares = source[source.index('function declaresEstimate'):source.index('const noMethod')]
    text_fields = re.search(r'return \[(.+?)\]\s*\.some', declares, re.S).group(1)
    assert tuple(re.findall(r"row(?:\.(\w+)|\['([^']+)'\])", text_fields)) == tuple(
        (field, '') if field.isascii() else ('', field) for field in result_semantics.TEXT_FIELDS)
    row_metric = source[source.index('function rowMetric'):source.index('export function rowPeriod')]
    assert tuple(a or b for a, b in re.findall(r"row(?:\.(\w+)|\['([^']+)'\])", row_metric)) == result_semantics.METRIC_FIELDS
    labels = _ts_declaration(source, 'metricLabels')
    assert dict(re.findall(r"'?([^\s:'{}]+)'?:\s*'([^']+)'", labels)) == result_semantics.RESULT_METRIC_LABELS
