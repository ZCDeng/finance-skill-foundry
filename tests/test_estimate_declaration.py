"""Exports declare estimates 估算 (issue #24; phase 1 decision 导出一律标估算).

Which values are estimates is decided by the server's own requirement check stored on the draft, and only by it:
the cited cells of its `estimated_grains`. The text of the draft decides nothing and is never scanned.
- Every management and audit export opens, right after the title, with a 估算值声明 block built from those cells:
  requirement, organization/period/scenario, the value as its fact displays it, and the estimate formula.
- A {{fact:…}} template that renders an estimated fact gets （估算） after its display (value and unit).
- The xlsx Result sheets show estimated cells through a number format carrying （估算）; the value is unchanged.
A draft with no estimated grains exports exactly as on main, and an export that fits the text and node limits on
main still fits.
"""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_explanations import render_fact_template
from foundry.finance_requirements import save_requirements
from foundry.finance_service import FinanceStore
from foundry.report_documents import (
    MAX_DOCUMENT_NODES,
    MAX_DOCUMENT_TEXT,
    report_document_from_markdown_body,
    report_document_markdown,
    validate_report_document,
)
from foundry.report_projection import build_report_projection
from foundry.task import TaskStore
from test_finance_requirements import _claim, _recipe, _script_run, _workbook, spec

MODES = ['management', 'audit']
LABEL = '（估算）'
HEADING = '估算值声明'
SENTENCE = '以下数值为估算，经理确认前不作为批复预算。'
COLUMNS = ['要求', '组织', '期间', '情景', '估算值', '估算公式']
# 华东 1-8 月收入预算 = 华东全年预算 05!C5 188503.3 × 集团 1-8 月预算进度 (01!B12:C12 300 ÷ 01!N12 480).
ESTIMATE = '117814.5625'
VALUES = ['325644', '300', '109742.028', ESTIMATE, '0.625']
FORMULA = '05·区域预算分解!C5 × （01·年度预算总表!B12:C12 ÷ 01·年度预算总表!N12）'
METHOD = '区域全年收入预算 × 集团1-8月收入预算进度'
REASON = '区域预算估算值保留 4 位小数，与系数乘积不能精确相等'
EAST_ROW = ['1-8 月营业收入', '华东区域', '2026-01:2026-08', 'budget_1_8', ESTIMATE + ' 万元', FORMULA]
DECLARATION_MD = '\n\n'.join([
    '## ' + HEADING,
    SENTENCE,
    '\n'.join([
        '| ' + ' | '.join(COLUMNS) + ' |',
        '| ' + ' | '.join(['---'] * 6) + ' |',
        '| ' + ' | '.join(EAST_ROW) + ' |',
    ]),
])
TABLE = '\n'.join([
    '| 区域 | 1-8 月实际 | 1-8 月预算 |',
    '| --- | ---: | ---: |',
    '| 集团合并 | 325,644 | 300 |',
    '| 华东区域 | 109,742.028 | 117,814.5625 |',
])
# The leading heading repeats the title, so every export drops it (as on main).
BODY = '## 区域收入\n\n华东区域 1-8 月收入实际 109,742.028 万元，同期预算 117,814.56 万元。\n\n' + TABLE
OPENING = '分析草稿·待复核\n\n# 区域收入\n\n' + DECLARATION_MD + '\n\n华东区域 1-8 月收入实际'
PRESENTED = {'decimal_places': 2, 'scale': 'identity', 'rounding': 'half_up'}


@pytest.fixture
def analysis(tmp_path):
    return AnalysisStore(TaskStore(tmp_path / 'var').create(title='估算声明'))


def _case(analysis, tmp_path, *, declare=True, value_type='DECIMAL(38,10)', organizations=True, reproducible=True,
          estimate_recipe=True, cite_estimate=True, grain_basis=None):
    """Huachen revenue_1_8 in miniature (PR #29's fixture): 华东's 1-8 budget is a declared estimate, a direct
    recipe on 05!C5 with the group 1-8 phasing ratio recipe as its factor; every other cell is counted.
    Without `organizations` the item lists no organizations and declares every budget_1_8 cell an estimate
    basis; the group's budget is still answered, so only 华东's cell is estimated. With `reproducible` False the
    declaration says no recipe can recompute the factor (issue #33); without `estimate_recipe` 华东's budget is cited
    with no recipe, and without `cite_estimate` it is not cited at all."""
    budget = _workbook(analysis, tmp_path, 'budget', {
        '01·年度预算总表': {'B12': 100, 'C12': 200, 'N12': 480},
        '05·区域预算分解': {'C5': 188503.3},
    })
    close = _workbook(analysis, tmp_path, 'close', {'10·区域经营损益表': {'D5': 109742.028, 'D11': 325644}})
    declared = [{**({'organizations': ['华东区域']} if organizations else {}), 'scenarios': ['budget_1_8'],
                 'basis': 'estimate', 'method': METHOD,
                 **({} if reproducible else {'factor_reproducible': False, 'reason': REASON})}]
    requirement = save_requirements(analysis, spec(
        question='1-8 月收入实际与同期预算',
        scope={'ledger': '预算工作簿与月结套表', 'currency': 'CNY', 'unit': '万元'},
        bindings={'budget': budget['id'], 'close': close['id']},
        items=[{'id': 'revenue_1_8', 'metric': 'revenue', 'label': '1-8 月营业收入',
                **({'organizations': ['集团合并', '华东区域']} if organizations else {}), 'periods': ['2026-01:2026-08'],
                'scenarios': ['actual_1_8', 'budget_1_8'], 'requires_drilldown': True,
                **({'grain_basis': grain_basis or declared} if declare else {})}],
    ))
    base = {'metric_key': 'revenue', 'period': '2026-01:2026-08', 'unit': '万元', 'currency': 'CNY'}
    rows = [
        {**base, 'organization': '集团合并', 'scenario': 'actual_1_8', 'value': VALUES[0]},
        {**base, 'organization': '集团合并', 'scenario': 'budget_1_8', 'value': VALUES[1]},
        {**base, 'organization': '华东区域', 'scenario': 'actual_1_8', 'value': VALUES[2]},
        {**base, 'organization': '华东区域', 'scenario': 'budget_1_8', 'value': VALUES[3]},
        {**base, 'organization': '集团合并', 'scenario': 'budget_phasing_ratio', 'value': VALUES[4], 'unit': '-'},
    ]
    names = list(dict.fromkeys(key for row in rows for key in row))
    run = _script_run(analysis, {'budget': budget, 'close': close}, rows, suffix='estimate-declaration',
                      requirements_id=requirement['id'],
                      requirements_semantic_fingerprint=requirement['semantic_fingerprint'],
                      result={'columns': [{'name': name, 'type': value_type if name == 'value' else 'VARCHAR'}
                                          for name in names], 'rows': rows})
    key = {'metric_key': 'revenue', 'period': '2026-01:2026-08'}

    def cell(reference):
        return {'dataset_id': budget['id'], 'source_hash': budget['source_hash'], 'sheet': '01·年度预算总表',
                'range': reference}

    recipes = [
        _recipe(close, '10·区域经营损益表', 'D11', run, 0, recipe_id='group_actual'),
        _recipe(budget, '01·年度预算总表', 'B12:C12', run, 1, kind='sum', recipe_id='group_budget'),
        _recipe(close, '10·区域经营损益表', 'D5', run, 2, recipe_id='east_actual'),
        {'id': 'phasing', 'kind': 'ratio', 'business_key': key, 'claim': {'run_id': run['id'], 'row': 4, 'column': 'value'},
         'left': cell('B12:C12'), 'right': cell('N12')},
        *([{**_recipe(budget, '05·区域预算分解', 'C5', run, 3, recipe_id='east_budget_estimate'),
            'factor_recipe_id': 'phasing', 'business_key': key}] if estimate_recipe else []),
    ]
    service = FinanceStore(analysis.task)
    facts = service.prepare_explanation({'run_ids': [run['id']]})['facts']
    by_row = {fact['row']: fact for fact in facts if fact['column'] == 'value'}
    claims = [_claim(run, row=index, column='value', value=value) for index, value in enumerate(VALUES)
              if cite_estimate or index != 3]
    if by_row and cite_estimate:
        claims.append({'basis': 'calculation', 'fact_id': by_row[3]['id'], 'run_id': run['id'], 'row': 3,
                       'column': 'value', 'value': ESTIMATE, 'presentation': PRESENTED})
    token = {row: '{{fact:%s}}' % fact['id'] for row, fact in by_row.items()}
    return SimpleNamespace(service=service, run=run, requirement=requirement, recipes=recipes, claims=claims,
                           estimate=token.get(3), actual=token.get(2), estimate_fact=by_row.get(3))


def _save(case, body=None, *, document=None, **extra):
    saved = case.service.save_explanation_draft({
        'title': '区域收入', **({'document': document} if document is not None else {'body': body}),
        'run_ids': [case.run['id']], 'evidence_recipes': case.recipes, 'claims': case.claims, **extra})
    return case.service.analysis.get_draft(saved['id'])


def _item(draft):
    return draft['explanation_check']['requirements']['items'][0]


def _text(node):
    if node.get('type') == 'text':
        return node.get('text', '')
    return ''.join(_text(child) for child in node.get('content', []) or [])


def _texts(nodes):
    found = []

    def walk(node):
        if node.get('type') == 'text':
            found.append(node)
        for child in node.get('content', []) or []:
            walk(child)

    for node in nodes:
        walk(node)
    return found


def _rows(table):
    return [[_text(cell) for cell in row['content']] for row in table['content']]


def _node_count(nodes):
    def count(node):
        return 1 + sum(count(child) for child in node.get('content', []) or [])
    return sum(count(node) for node in nodes)


def _text_length(nodes):
    return sum(len(node['text']) for node in _texts(nodes))


def _labels(nodes):
    return sum(node['text'].count(LABEL) for node in _texts(nodes))


def _without_estimates(draft):
    """The stored draft as a check that found no estimated grain and no declared estimate would have left it."""
    clean = copy.deepcopy(draft)
    for key in ('explanation_check', 'quality'):
        for item in ((clean.get(key) or {}).get('requirements') or {}).get('items', []):
            item.pop('estimated_grains', None)
            item.pop('grain_basis', None)
    return clean


def _is_audit_record(node):
    return node['type'] == 'codeBlock' and _text(node).startswith('{"')


def _declared(content):
    assert [node['type'] for node in content[:3]] == ['heading', 'paragraph', 'table'] and _text(content[0]) == HEADING
    return content[:3]


def _unlabelled(content):
    """The document without the declaration, without every （估算） (the author's text in these tests never writes
    one) and without the audit record, whose copy of the check differs in the reference: main's export."""
    rest = copy.deepcopy(content[len(_declared(content)):])
    for node in _texts(rest):
        node['text'] = node['text'].replace(LABEL, '')
    return [node for node in rest if not _is_audit_record(node)]


def _reference(draft, mode):
    return [node for node in build_report_projection(_without_estimates(draft), mode=mode)['document']['content']
            if not _is_audit_record(node)]


# --- the declaration ----------------------------------------------------------------------------------------


@pytest.mark.parametrize('mode', MODES)
def test_every_export_mode_opens_with_a_declaration_of_each_estimated_cell_right_after_the_title(analysis, tmp_path, mode):
    case = _case(analysis, tmp_path)
    draft = _save(case, BODY)
    assert _item(draft)['status'] == 'estimated'

    projection = build_report_projection(draft, mode=mode)
    content = projection['document']['content']

    assert content[0] == {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': HEADING}]}
    assert _text(content[1]) == SENTENCE
    assert _rows(content[2]) == [COLUMNS, EAST_ROW]
    assert projection['body'].startswith(OPENING)
    # The value is the fact's own display (value and unit), whatever precision the text presents it with.
    assert case.estimate_fact['display_value'] == ESTIMATE + ' 万元'


@pytest.mark.parametrize('mode', MODES)
def test_the_body_text_is_exported_as_written_and_the_declaration_is_the_only_addition(analysis, tmp_path, mode):
    """No scanning and no value matching: the estimate written as a number in prose or in a table stays as written."""
    case = _case(analysis, tmp_path)
    draft = _save(case, BODY + '\n\n以上区域预算为估算口径，华东 117,814.56 万元待确认。')

    projection = build_report_projection(draft, mode=mode)
    reference = build_report_projection(_without_estimates(draft), mode=mode)

    assert _labels(projection['document']['content']) == 0
    assert _unlabelled(projection['document']['content']) == _reference(draft, mode)
    if mode == 'management':
        assert projection['body'] == reference['body'].replace('# 区域收入\n\n', '# 区域收入\n\n' + DECLARATION_MD + '\n\n', 1)
    assert projection['title'] == reference['title'] and projection['limitations'] == reference['limitations']
    assert projection['sources'] == reference['sources'] and projection['marker'] == reference['marker']


def test_the_declaration_lists_only_cells_of_grains_the_server_check_found_estimated(analysis, tmp_path):
    """Undeclared, the estimate is pending (estimate_cited_for_source_grain): nothing is declared or labelled,
    whatever the text says about 估算, and a template of that estimate renders as on main."""
    case = _case(analysis, tmp_path, declare=False)
    draft = _save(case, BODY + f'\n\n以上区域预算为估算口径（{case.estimate}）。')
    assert _item(draft)['status'] == 'pending' and not _item(draft).get('estimated_grains')

    for mode in MODES:
        projection = build_report_projection(draft, mode=mode)
        assert HEADING not in projection['body'] and LABEL not in projection['body']
        assert f'以上区域预算为估算口径（{ESTIMATE} 万元）。' in projection['body']
        assert 'estimate_headroom' not in projection


def test_a_caller_supplied_quality_or_check_is_ignored(analysis, tmp_path):
    case = _case(analysis, tmp_path)
    forged = {'requirements': {'items': [{'id': 'revenue_1_8', 'label': '伪造', 'estimated_grains': [
        {'organization': '华东区域', 'scenario': 'actual_1_8',
         'locations': [{'run_id': case.run['id'], 'row': 2, 'column': 'value'}]}]}]}}
    draft = analysis.save_draft({'title': '区域收入', 'body': BODY, 'run_ids': [case.run['id']],
                                 'claims': case.claims, 'evidence_recipes': case.recipes,
                                 'requirements_id': case.requirement['id'], 'quality': forged,
                                 'explanation_check': forged})

    table = build_report_projection(draft, mode='management')['document']['content'][2]

    assert _rows(table) == [COLUMNS, EAST_ROW]


@pytest.mark.parametrize('mode', MODES)
def test_a_declared_cell_names_the_grain_its_own_row_states_where_the_item_lists_no_such_field(analysis, tmp_path, mode):
    """An item without an organizations list keeps estimated grains without an organization. The declaration
    reads the missing field off the estimated cell's own run row (华东区域), the row the check graded."""
    case = _case(analysis, tmp_path, organizations=False)
    draft = _save(case, BODY)
    assert [(grain.get('organization'), grain['scenario']) for grain in _item(draft)['estimated_grains']] == [
        (None, 'budget_1_8')]

    projection = analysis.report_projection(draft['id'], mode)

    assert _rows(projection['document']['content'][2]) == [COLUMNS, EAST_ROW]
    markdown = open(analysis.export_draft(draft['id'], 'md', mode=mode)['path'], encoding='utf-8').read()
    assert markdown.startswith(OPENING)


# --- grains the requirement declares estimates that the check does not count (issue #33) ------------------------

NOT_REPRODUCIBLE = METHOD + '（系数无法由来源复算）'
NOT_RECOMPUTED = METHOD + '（尚未由来源复算）'


def _projection(analysis, draft, mode):
    """The projection as projection_for_draft builds it (with the draft's runs), without resolved dataset names."""
    return build_report_projection(draft, mode=mode, runs={run_id: analysis.get_run(run_id) for run_id in draft['run_ids']})


def _result_labels(analysis, draft, mode):
    book = load_workbook(analysis.export_draft(draft['id'], 'xlsx', mode=mode)['path'])
    try:
        return [(ws.title, cell.row, cell.column) for ws in book for row in ws.iter_rows() for cell in row
                if LABEL in str(cell.number_format)]
    finally:
        book.close()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('estimate_recipe', [True, False])
def test_a_grain_declared_an_estimate_whose_factor_cannot_be_recomputed_is_declared_with_its_method(
        analysis, tmp_path, mode, estimate_recipe):
    """Huachen revenue_1_8/profit_1_8: the requirement declares 华东's 1-8 budget an estimate with
    factor_reproducible false. The grain stays pending for the manager, cited with the factor recipe or with none,
    and every export still declares the cited value, with the declared method and why it is not recomputed."""
    case = _case(analysis, tmp_path, reproducible=False, estimate_recipe=estimate_recipe)
    draft = _save(case, BODY + f'\n\n华东区域同期预算 {case.estimate}。')
    item = _item(draft)
    assert item['status'] == 'pending' and not item.get('estimated_grains')
    assert [grain['state'] for grain in item['declared_grains']] == ['estimate_factor_not_reproducible']

    projection = _projection(analysis, draft, mode)
    content = projection['document']['content']

    row = [*EAST_ROW[:5], NOT_REPRODUCIBLE]
    assert _rows(_declared(content)[2]) == [COLUMNS, row]
    assert f'华东区域同期预算 {ESTIMATE} 万元（估算）。' in projection['body']
    assert _unlabelled(content) == _reference(draft, mode)
    markdown = open(analysis.export_draft(draft['id'], 'md', mode=mode)['path'], encoding='utf-8').read()
    assert markdown.startswith(OPENING.replace(FORMULA, NOT_REPRODUCIBLE))
    assert f'华东区域同期预算 {ESTIMATE} 万元（估算）。' in markdown
    # The xlsx Result sheet marks the cited cell (run row 3, column value: sheet row 5, column 7) and nothing else.
    assert _result_labels(analysis, draft, mode) == [('Result 1', 5, 7)]


@pytest.mark.parametrize('mode', MODES)
def test_a_declared_estimate_grain_the_draft_cites_no_value_for_is_still_declared(analysis, tmp_path, mode):
    case = _case(analysis, tmp_path, reproducible=False, cite_estimate=False)
    draft = _save(case, BODY)
    assert [grain['state'] for grain in _item(draft)['declared_grains']] == ['estimate_factor_not_reproducible']

    projection = _projection(analysis, draft, mode)
    content = projection['document']['content']

    assert _rows(_declared(content)[2]) == [COLUMNS, [*EAST_ROW[:4], '—', NOT_REPRODUCIBLE]]
    assert _labels(content) == 0 and _unlabelled(content) == _reference(draft, mode)
    assert _result_labels(analysis, draft, mode) == []


@pytest.mark.parametrize('mode', MODES)
def test_a_declared_estimate_grain_not_yet_recomputed_by_a_recipe_is_declared_too(analysis, tmp_path, mode):
    """factor_reproducible defaults to true: until a factor recipe makes the grain `estimated`, the cited value is
    uncounted (or the grain missing), and the export still declares it an estimate, noting it is not recomputed."""
    case = _case(analysis, tmp_path, estimate_recipe=False)
    draft = _save(case, BODY + f'\n\n华东区域同期预算 {case.estimate}。')
    assert [grain['organization'] for grain in _item(draft)['uncounted_grains']] == ['华东区域']

    projection = _projection(analysis, draft, mode)

    assert _rows(_declared(projection['document']['content'])[2]) == [COLUMNS, [*EAST_ROW[:5], NOT_RECOMPUTED]]
    assert f'华东区域同期预算 {ESTIMATE} 万元（估算）。' in projection['body']
    assert _result_labels(analysis, draft, mode) == [('Result 1', 5, 7)]

    (tmp_path / 'm').mkdir()
    missing = _case(AnalysisStore(TaskStore(tmp_path / 'm' / 'var').create(title='估算声明')), tmp_path / 'm',
                    cite_estimate=False)
    missing_draft = _save(missing, BODY)
    assert [grain['organization'] for grain in _item(missing_draft)['missing_grains']] == ['华东区域']
    projection = _projection(missing.service.analysis, missing_draft, mode)
    assert _rows(_declared(projection['document']['content'])[2]) == [COLUMNS, [*EAST_ROW[:4], '—', NOT_RECOMPUTED]]


@pytest.mark.parametrize('mode', MODES)
def test_a_declared_estimate_grain_the_draft_answers_from_the_source_is_not_declared(analysis, tmp_path, mode):
    """The group's 1-8 budget is declared an estimate, but the draft answers it from the source (01!B12:C12): the
    export does not call a source value an estimate, and with nothing else to declare it is main's export."""
    case = _case(analysis, tmp_path, estimate_recipe=False, cite_estimate=False, grain_basis=[
        {'organizations': ['集团合并'], 'scenarios': ['budget_1_8'], 'basis': 'estimate', 'method': METHOD,
         'factor_reproducible': False, 'reason': REASON}])
    draft = _save(case, BODY)
    item = _item(draft)
    assert not item.get('declared_grains') and not item.get('estimated_grains')
    assert [grain['organization'] for grain in item['missing_grains']] == ['华东区域']

    projection = _projection(analysis, draft, mode)

    assert HEADING not in projection['body'] and LABEL not in projection['body']
    assert 'estimate_headroom' not in projection
    assert [node for node in projection['document']['content'] if not _is_audit_record(node)] == _reference(draft, mode)
    assert [node for node in projection['document']['content'] if not _is_audit_record(node)] == _reference(draft, mode)
    assert _result_labels(analysis, draft, mode) == []


# --- inline labels only where a {{fact:…}} template renders an estimate --------------------------------------


@pytest.mark.parametrize('mode', MODES)
def test_a_fact_template_that_renders_an_estimate_gets_the_label_after_its_display(analysis, tmp_path, mode):
    case = _case(analysis, tmp_path)
    estimate, actual = case.estimate, case.actual
    body = '\n\n'.join([
        '## 区域收入',
        f'华东区域同期预算 {estimate}，实际 {actual}。预算按 {estimate} 万元。',
        f'| 区域 | 1-8 月实际 | 1-8 月预算 |\n| --- | ---: | ---: |\n| 华东区域 | {actual} | {estimate} |',
        f'手写的 {ESTIMATE} 万元不经模板，按原样导出。',
    ])
    draft = _save(case, body)
    assert draft['body_template'].count('{{fact:') == 5

    projection = build_report_projection(draft, mode=mode)
    content = projection['document']['content']
    text = projection['body']

    # Where the prose writes the unit, the label follows the prose's unit.
    assert f'华东区域同期预算 {ESTIMATE} 万元（估算），实际 109742.028 万元。预算按 {ESTIMATE} 万元（估算）。' in text
    assert f'| 华东区域 | 109742.028 万元 | {ESTIMATE} 万元（估算） |' in text
    assert f'手写的 {ESTIMATE} 万元不经模板，按原样导出。' in text
    assert _labels(content) == 3
    assert _unlabelled(content) == _reference(draft, mode)
    # Exactly the text and nodes the server added get room beyond the limits (see the limit tests).
    assert projection['estimate_headroom'] == {
        'text': _text_length(_declared(content)) + len(LABEL) * 3, 'nodes': _node_count(_declared(content))}


def test_a_fact_template_in_a_structured_document_is_labelled_in_its_own_text_node(analysis, tmp_path):
    case = _case(analysis, tmp_path)
    estimate, actual = case.estimate, case.actual

    def cell(kind, text, align='left'):
        return {'type': kind, 'attrs': {'textAlign': align},
                'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}]}

    document = {
        'schema_version': 1, 'template_version': 'annual-v1',
        'metadata': {'company': '华宸物业', 'period': '2026-01:2026-08', 'currency': 'CNY', 'unit': '万元'},
        'content': [
            {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': '分区域收入'}]},
            {'type': 'paragraph', 'content': [
                {'type': 'text', 'text': f'华东区域同期预算 {estimate} 万元，实际 {actual}。'},
                {'type': 'text', 'text': '重点：'},
                {'type': 'text', 'text': estimate, 'marks': [{'type': 'bold'}]},
                {'type': 'text', 'text': '（按集团进度）。', 'marks': [{'type': 'italic'}]},
            ]},
            {'type': 'table', 'attrs': {'caption': '区域收入（万元）', 'period': '2026-01:2026-08', 'unit': '万元'}, 'content': [
                {'type': 'tableRow', 'content': [cell('tableHeader', '区域'), cell('tableHeader', '实际'), cell('tableHeader', '预算')]},
                {'type': 'tableRow', 'content': [cell('tableCell', '华东区域'), cell('tableCell', actual, 'right'),
                                                 cell('tableCell', estimate, 'right')]},
            ]},
        ],
    }
    draft = _save(case, document=document)
    assert '{{fact:' in draft['body_template'] and '{{fact:' not in json.dumps(draft['document'], ensure_ascii=False)

    for mode in MODES:
        projection = build_report_projection(draft, mode=mode)
        content = projection['document']['content']
        body = content[3:]
        assert _text(body[1]) == (f'华东区域同期预算 {ESTIMATE} 万元（估算），实际 109742.028 万元。'
                                  f'重点：{ESTIMATE} 万元（估算）（按集团进度）。')
        assert body[1]['content'][2] == {'type': 'text', 'text': f'{ESTIMATE} 万元（估算）', 'marks': [{'type': 'bold'}]}
        assert _rows(body[2])[1] == ['华东区域', '109742.028 万元', f'{ESTIMATE} 万元（估算）']
        assert body[2]['attrs'] == document['content'][2]['attrs']
        assert [cell['attrs'] for cell in body[2]['content'][1]['content']] == [
            {'textAlign': 'left'}, {'textAlign': 'right'}, {'textAlign': 'right'}]
        assert _labels(content) == 3
        assert _unlabelled(content) == _reference(draft, mode)
        # After the title and the document's metadata line, as the markdown export prints them.
        assert projection['body'].startswith('分析草稿·待复核\n\n# 区域收入\n\n账套：未声明；组织：未声明；企业：华宸物业；'
                                             '期间：2026-01:2026-08；币种：CNY；单位：万元\n\n## 估算值声明\n\n')


def test_the_label_lands_after_the_display_whatever_markdown_escapes_or_marks_precede_it(analysis, tmp_path):
    """Positions come from the template, so escaped characters, footnote references, links and code before the
    display do not move the label (document and body drafts alike)."""
    case = _case(analysis, tmp_path)
    estimate = case.estimate
    document = {
        'schema_version': 1, 'template_version': 'annual-v1',
        'metadata': {'ledger': '', 'organization': '', 'company': '', 'period': '', 'currency': '', 'unit': ''},
        'content': [
            {'type': 'paragraph', 'content': [
                {'type': 'text', 'text': f'[^1] 见附注；*星号* (括号) \\反斜杠 `反引号` [方括号] {estimate} 万元。'},
                {'type': 'text', 'text': f'链接 ({estimate})', 'marks': [{'type': 'link', 'attrs': {'href': 'https://example.com/a'}}]},
                {'type': 'text', 'text': f' 代码 {estimate}', 'marks': [{'type': 'code'}]},
            ]},
            {'type': 'reportNote', 'attrs': {'id': '1'}, 'content': [{'type': 'paragraph', 'content': [
                {'type': 'text', 'text': f'附注：{estimate}'}]}]},
        ],
    }
    body = '\n\n'.join([
        f'**加粗 {estimate}** 与 `代码 {estimate}` 与 [链接 {estimate}](https://example.com/b) 与 *星号* \\(括号\\) {estimate}',
        f'- 条目 {estimate} 万元',
        f'[^1]: 附注 {estimate}',
    ])
    shown = f'{ESTIMATE} 万元（估算）'
    for draft in (_save(case, document=document), _save(case, body)):
        content = build_report_projection(draft, mode='management')['document']['content']
        texts = [node['text'] for node in _texts(content[3:]) if LABEL in node['text']]
        if draft.get('document') is not None:
            assert texts == [f'[^1] 见附注；*星号* (括号) \\反斜杠 `反引号` [方括号] {ESTIMATE} 万元（估算）。',
                             f'链接 ({shown})', f' 代码 {shown}', f'附注：{shown}']
        else:
            assert texts == [f'加粗 {shown}', f'代码 {shown}', f'链接 {shown}', f' 与 *星号* (括号) {shown}',
                             f'条目 {ESTIMATE} 万元（估算）', f'附注 {shown}']
        assert _unlabelled(content) == _reference(draft, 'management')


def test_a_document_that_opens_with_its_own_metadata_line_keeps_it_once_before_the_declaration(analysis, tmp_path):
    """The markdown export prints the author's metadata paragraph in place of the generated line; the declaration
    goes right after it, so the line is not printed twice."""
    case = _case(analysis, tmp_path)
    metadata = {'ledger': '', 'organization': '', 'company': '华宸物业', 'period': '2026-01:2026-08', 'currency': 'CNY', 'unit': '万元'}
    line = '账套：未声明；组织：未声明；企业：华宸物业；期间：2026-01:2026-08；币种：CNY；单位：万元'
    document = {'schema_version': 1, 'template_version': 'annual-v1', 'metadata': metadata, 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': line}]},
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': '华东区域同期预算 117,814.56 万元。'}]},
    ]}
    draft = _save(case, document=document)

    body = build_report_projection(draft, mode='management')['body']

    assert body.startswith(f'分析草稿·待复核\n\n# 区域收入\n\n{line}\n\n' + DECLARATION_MD + '\n\n华东区域同期预算 117,814.56 万元。')
    assert body.count(line) == 1


def test_a_template_the_stored_text_is_not_the_rendering_of_places_no_label(analysis, tmp_path):
    """A body_template saved straight through analysis.save_draft beside a body it does not render to is not
    trusted to place labels; the declaration still lists the estimate."""
    case = _case(analysis, tmp_path)
    draft = analysis.save_draft({'title': '区域收入', 'body': '华东区域实际 109742.028 万元。',
                                 'body_template': f'华东区域实际 {case.estimate}。', 'run_ids': [case.run['id']],
                                 'claims': case.claims, 'evidence_recipes': case.recipes,
                                 'requirements_id': case.requirement['id']})
    assert _item(draft)['status'] == 'estimated'

    projection = build_report_projection(draft, mode='management')

    assert _labels(projection['document']['content']) == 0
    assert '华东区域实际 109742.028 万元。' in projection['body']
    assert _rows(projection['document']['content'][2]) == [COLUMNS, EAST_ROW]


def test_a_template_that_writes_the_label_after_an_estimate_itself_is_not_labelled_again(analysis, tmp_path):
    """The check's message asks the body to write 估算 beside an estimate it cites. Where the template itself
    writes （估算） right after the token (after the prose's unit where it writes the unit; also as (估算), after a
    space or after the token's closing emphasis), that is the label; the export adds none there. A token the
    template leaves unlabelled in the same draft still gets one."""
    case = _case(analysis, tmp_path)
    estimate, actual = case.estimate, case.actual
    shown = f'{ESTIMATE} 万元'
    body = '\n\n'.join([
        '## 区域收入',
        f'华东区域同期预算 {estimate}（估算），按 {estimate} 万元（估算）列示；实际 {actual}。',
        f'另记 {estimate} （估算），{estimate}(估算)，**{estimate}**（估算）。',
        f'| 区域 | 1-8 月实际 | 1-8 月预算 |\n| --- | ---: | ---: |\n| 华东区域 | {actual} | {estimate}（估算） |',
        f'未写标注的 {estimate} 由导出加注。',
    ])
    document = {
        'schema_version': 1, 'template_version': 'annual-v1',
        'metadata': {'ledger': '', 'organization': '', 'company': '', 'period': '', 'currency': '', 'unit': ''},
        'content': [
            {'type': 'paragraph', 'content': [
                {'type': 'text', 'text': f'华东区域同期预算 {estimate}（估算），按 {estimate} 万元（估算）列示；'},
                {'type': 'text', 'text': estimate, 'marks': [{'type': 'bold'}]},
                {'type': 'text', 'text': f'（估算）；另记 {estimate}(估算)。未写标注的 {estimate} 由导出加注。'},
            ]},
            {'type': 'table', 'content': [{'type': 'tableRow', 'content': [
                {'type': 'tableCell', 'content': [{'type': 'paragraph', 'content': [
                    {'type': 'text', 'text': f'{estimate}（估算）'}]}]}]}]},
        ],
    }
    expected = {
        'body': [f'华东区域同期预算 {shown}（估算），按 {shown}（估算）列示；实际 109742.028 万元。',
                 f'另记 {shown} （估算），{shown}(估算)，{shown}（估算）。',
                 f'未写标注的 {shown}（估算） 由导出加注。'],
        'document': [f'华东区域同期预算 {shown}（估算），按 {shown}（估算）列示；{shown}（估算）；另记 {shown}(估算)。'
                     f'未写标注的 {shown}（估算） 由导出加注。'],
    }
    for name, draft in (('body', _save(case, body)), ('document', _save(case, document=document))):
        for mode in MODES:
            projection = build_report_projection(draft, mode=mode)
            content = projection['document']['content']
            paragraphs = [_text(node) for node in content[3:] if node['type'] == 'paragraph']
            assert [text for text in expected[name] if text not in paragraphs] == []
            table = next(node for node in content[3:] if node['type'] == 'table')
            assert _rows(table)[-1][-1] == f'{shown}（估算）'
            assert not any('估算）（估算' in node['text'] or '估算） （估算' in node['text'] or '估算）(估算' in node['text']
                           for node in _texts(content))
            # Only the one label the export placed takes room beyond the limits.
            assert projection['estimate_headroom'] == {
                'text': _text_length(_declared(content)) + len(LABEL), 'nodes': _node_count(_declared(content))}
            markdown = open(analysis.export_draft(draft['id'], 'md', mode=mode)['path'], encoding='utf-8').read()
            assert '（估算）（估算）' not in markdown and f'{shown}（估算）（估算）' not in markdown
            book = load_workbook(analysis.export_draft(draft['id'], 'xlsx', mode=mode)['path'])
            try:
                texts = [str(cell) for sheet in ('Report', '分段正文', '财务表格')
                         for row in book[sheet].iter_rows(values_only=True) for cell in row if cell is not None]
                assert not any('（估算）（估算）' in text for text in texts)
            finally:
                book.close()


# --- every format -------------------------------------------------------------------------------------------


@pytest.mark.parametrize('mode', MODES)
def test_markdown_and_xlsx_exports_carry_the_declaration_and_the_template_labels(analysis, tmp_path, mode):
    case = _case(analysis, tmp_path)
    draft = _save(case, BODY + f'\n\n华东区域同期预算 {case.estimate}。')

    markdown = open(analysis.export_draft(draft['id'], 'md', mode=mode)['path'], encoding='utf-8').read()
    assert markdown.startswith(OPENING)
    assert f'华东区域同期预算 {ESTIMATE} 万元（估算）。' in markdown
    assert '同期预算 117,814.56 万元。' in markdown

    book = load_workbook(analysis.export_draft(draft['id'], 'xlsx', mode=mode)['path'])
    try:
        assert book['Report']['A3'].value.startswith(OPENING)
        sections = [(row[1], row[3]) for row in book['分段正文'].iter_rows(min_row=2, values_only=True)]
        assert sections[:2] == [('heading', HEADING), ('paragraph', SENTENCE)]
        assert ('paragraph', f'华东区域同期预算 {ESTIMATE} 万元（估算）。') in sections
        declaration = [row[4] for row in book['财务表格'].iter_rows(min_row=2, values_only=True) if row[0] == 1]
        assert declaration == [*COLUMNS, *EAST_ROW]
    finally:
        book.close()


@pytest.mark.parametrize('value_type', ['DECIMAL(38,10)', 'VARCHAR'])
def test_the_xlsx_result_sheet_marks_only_estimated_cells_through_their_number_format(analysis, tmp_path, value_type):
    case = _case(analysis, tmp_path, value_type=value_type)
    draft = _save(case, BODY)
    numeric = value_type != 'VARCHAR'

    for mode in MODES:
        book = load_workbook(analysis.export_draft(draft['id'], 'xlsx', mode=mode)['path'])
        try:
            sheet = book['Result 1']
            column = [cell.value for cell in sheet[1]].index('value') + 1
            cells = [sheet.cell(row, column) for row in range(2, 7)]
            assert [cell.value for cell in cells] == ([325644, 300, 109742.028, 117814.5625, 0.625] if numeric else VALUES)
            plain = '#,##0.00' if numeric else 'General'
            assert [cell.number_format for cell in cells] == [
                plain, plain, plain, ('#,##0.00' if numeric else '@') + '"（估算）"', plain]
            labelled = [(ws.title, cell.coordinate) for ws in book for row in ws.iter_rows() for cell in row
                        if LABEL in str(cell.number_format)]
            assert labelled == [('Result 1', cells[3].coordinate)]
        finally:
            book.close()


# --- a draft without estimates is main's export ---------------------------------------------------------------

RUN = '0' * 31 + '1'
ACTUAL_FACT = '1' * 64
UNDECLARED_FACT = '2' * 64
# What main (23d44f9) gives golden_drafts(); the projection hash covers the body and the document.
GOLDEN_HASHES = {
    ('body', 'management'): 'e97d0c89aed5dfce4a1c2fe2d69dc56eaff7c57f9d9ccff77ec09b9a4b0683b7',
    ('body', 'audit'): '01c33df11a0407fd0e9b64f1c8621bf9e166332829c5fc85438fe4996f50ffef',
    ('document', 'management'): '6b8d0a214675c71dab310a0cb6776ebdc216529f7560805430e66fec0fc95c71',
    ('document', 'audit'): '9f02c9cd31a243ea18570afbe5a374a7f8f3a627724268628511b6a8c8e25837',
}


def golden_drafts():
    """Stored drafts with fixed ids whose requirement check found no estimated grain: the estimate is cited for an
    undeclared grain (pending) and the actual is answered. Both are {{fact:…}} templates."""
    facts = [
        {'id': ACTUAL_FACT, 'run_id': RUN, 'row': 0, 'column': 'value', 'value': '109742.028',
         'display_value': '109742.028 万元', 'unit': '万元'},
        {'id': UNDECLARED_FACT, 'run_id': RUN, 'row': 1, 'column': 'value', 'value': ESTIMATE,
         'display_value': ESTIMATE + ' 万元', 'unit': '万元'},
    ]
    requirements = {'requirements_id': 'e' * 32, 'items': [{
        'id': 'revenue_1_8', 'label': '1-8 月营业收入', 'metric': 'revenue', 'status': 'pending',
        'organizations': ['华东区域'], 'scenarios': ['actual_1_8', 'budget_1_8'],
        'locations': [
            {'run_id': RUN, 'row': 0, 'column': 'value', 'status': 'answered',
             'evidence': {'evidence_basis': 'source_value', 'recipe_location': {'sheet': '10·区域经营损益表', 'range': 'D5'}}},
            {'run_id': RUN, 'row': 1, 'column': 'value', 'status': 'pending',
             'evidence': {'evidence_basis': None, 'not_counted_reason': 'estimate_cited_for_source_grain'}},
        ],
        'uncounted_grains': [{'organization': '华东区域', 'scenario': 'budget_1_8', 'statuses': ['pending']}],
    }]}
    check = {'status': 'needs_attention', 'facts': facts, 'requirements': requirements,
             'issues': [{'code': 'requirement_unanswered', 'severity': 'warning', 'message': '尚未回答“1-8 月营业收入”。'}]}
    actual, estimate = '{{fact:%s}}' % ACTUAL_FACT, '{{fact:%s}}' % UNDECLARED_FACT
    template = (f'## 区域收入\n\n华东区域实际 {actual}，同期预算 {estimate}（估算口径待确认）。\n\n'
                f'| 区域 | 实际 | 预算 |\n| --- | ---: | ---: |\n| 华东区域 | {actual} | {estimate} |')
    appendix = '## 计算依据\n\n### 区域收入\n- value：109742.028 万元（已引用）'
    common = {
        'task_id': 'b' * 32, 'title': '区域收入', 'content_hash': 'c' * 64, 'requirements_id': 'e' * 32,
        'run_ids': [RUN], 'fact_ids': [ACTUAL_FACT, UNDECLARED_FACT],
        'claims': [{'basis': 'calculation', 'run_id': RUN, 'row': row, 'column': 'value', 'value': value}
                   for row, value in enumerate(['109742.028', ESTIMATE])],
        'limitations': ['区域预算为估算，待业务确认。'], 'explanation_check': check, 'quality': check,
        'evidence_appendix': appendix,
        'evidence_appendix_meta': {'body_sha256': hashlib.sha256(appendix.encode('utf-8')).hexdigest()},
        'publication_status': 'draft', 'review_status': 'unreviewed', 'reproducibility_status': 'unverified',
    }
    document = {
        'schema_version': 1, 'template_version': 'annual-v1',
        'metadata': {'ledger': '', 'organization': '', 'company': '华宸物业', 'period': '2026-01:2026-08',
                     'currency': 'CNY', 'unit': '万元'},
        'content': [
            {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': '分区域收入'}]},
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': f'华东区域实际 {actual}，同期预算 {estimate}。'}]},
            {'type': 'table', 'attrs': {'caption': '区域收入'}, 'content': [{'type': 'tableRow', 'content': [
                {'type': 'tableCell', 'attrs': {'textAlign': 'right'},
                 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': estimate}]}]}]}]},
        ],
    }
    rendered_document = json.loads(json.dumps(document, ensure_ascii=False)
                                   .replace(actual, '109742.028 万元').replace(estimate, ESTIMATE + ' 万元'))
    return {
        'body': {**common, 'id': 'a' * 32, 'body_template': template,
                 'body': render_fact_template(template, facts)[0].rstrip() + '\n\n' + appendix},
        'document': {**common, 'id': 'd' * 32, 'document': rendered_document,
                     'body': report_document_markdown(rendered_document),
                     'body_template': report_document_markdown(document)},
    }


@pytest.mark.parametrize('name', ['body', 'document'])
@pytest.mark.parametrize('mode', MODES)
def test_a_draft_without_estimated_grains_projects_byte_identical_to_main(name, mode):
    projection = build_report_projection(golden_drafts()[name], mode=mode)

    assert projection['projection_hash'] == GOLDEN_HASHES[(name, mode)]
    assert 'estimate_headroom' not in projection and HEADING not in projection['body']


# --- limits ---------------------------------------------------------------------------------------------------


def _padded(analysis, draft, blocks, draft_id):
    """A stored copy of the draft with extra blocks before its generated appendix, in body and template alike."""
    appendix = draft['evidence_appendix'].lstrip()
    extra = '\n\n'.join(blocks)
    facts = draft['explanation_check']['facts']
    assert appendix and draft['body'].endswith('\n\n' + appendix)
    if draft.get('body_template') is None:
        padded = {**draft, 'body': draft['body'][:-len(appendix)] + extra + '\n\n' + appendix}
    else:
        assert draft['body'] == render_fact_template(draft['body_template'], facts)[0].rstrip() + '\n\n' + appendix
        template = draft['body_template'].rstrip() + '\n\n' + extra
        padded = {**draft, 'body_template': template,
                  'body': render_fact_template(template, facts)[0].rstrip() + '\n\n' + appendix}
    record = {key: value for key, value in padded.items() if key not in {'seq', '_integrity_hash'}}
    return analysis._write(analysis._object_path('drafts', draft_id), {**record, 'id': draft_id})


def _nodes(count):
    """Blocks of exactly `count` nodes: a rule (one node), then paragraphs (a paragraph and its text each)."""
    return ['---'] * (count % 2) + ['x'] * (count // 2)


def _main_size(analysis, draft_id, mode):
    """The most text and nodes main checks against the limits for this export: the draft's own document (a body
    still holds the generated appendix there) or the finished projection without what the server added for
    estimates, whichever is larger."""
    draft = analysis.get_draft(draft_id)
    own = report_document_from_markdown_body(draft['body'])['content']
    content = analysis.report_projection(draft_id, mode)['document']['content']
    declared = _declared(content)
    return (max(_text_length(own), _text_length(content) - _text_length(declared) - len(LABEL) * _labels(content)),
            max(_node_count(own), _node_count(content) - _node_count(declared)))


@pytest.mark.parametrize('mode', MODES)
def test_an_export_at_the_text_limit_on_main_still_exports(analysis, tmp_path, mode):
    case = _case(analysis, tmp_path)
    draft = _save(case, BODY + f'\n\n华东区域同期预算 {case.estimate}。')
    room = MAX_DOCUMENT_TEXT - _main_size(analysis, draft['id'], mode)[0]
    full = _padded(analysis, draft, ['填' * room], 'f' * 32)

    projection = analysis.report_projection(full['id'], mode)

    assert _main_size(analysis, full['id'], mode)[0] == MAX_DOCUMENT_TEXT
    assert _labels(projection['document']['content']) == 1
    headroom = projection['estimate_headroom']
    assert _text_length(projection['document']['content']) - headroom['text'] <= MAX_DOCUMENT_TEXT
    if _text_length(projection['document']['content']) > MAX_DOCUMENT_TEXT:
        with pytest.raises(FoundryError, match='1 MiB'):
            validate_report_document(projection['document'])
    assert mode == 'management' or _text_length(projection['document']['content']) - headroom['text'] == MAX_DOCUMENT_TEXT
    for fmt in ('md', 'xlsx'):
        assert analysis.export_draft(full['id'], fmt, mode=mode)['projection_hash'] == projection['projection_hash']
    # One character more does not fit on main, and does not fit here either.
    over = _padded(analysis, draft, ['填' * (room + 1)], 'e' * 32)
    with pytest.raises(FoundryError, match='1 MiB'):
        analysis.report_projection(over['id'], mode)
    if mode == 'management':
        without = _padded(analysis, _without_estimates(draft), ['填' * (room + 1)], 'd' * 32)
        with pytest.raises(FoundryError, match='1 MiB'):
            analysis.report_projection(without['id'], mode)


@pytest.mark.parametrize('mode', MODES)
def test_an_export_at_the_node_limit_on_main_still_exports(analysis, tmp_path, mode):
    case = _case(analysis, tmp_path)
    draft = _save(case, BODY)
    room = MAX_DOCUMENT_NODES - _main_size(analysis, draft['id'], mode)[1]
    full = _padded(analysis, draft, _nodes(room), 'f' * 32)

    projection = analysis.report_projection(full['id'], mode)

    assert _main_size(analysis, full['id'], mode)[1] == MAX_DOCUMENT_NODES
    with pytest.raises(FoundryError, match='too many nodes'):
        validate_report_document(projection['document'])
    headroom = projection['estimate_headroom']
    validate_report_document(projection['document'], text_headroom=headroom['text'], node_headroom=headroom['nodes'])
    for fmt in ('md', 'xlsx'):
        assert analysis.export_draft(full['id'], fmt, mode=mode)['projection_hash'] == projection['projection_hash']
    over = _padded(analysis, draft, _nodes(room + 1), 'e' * 32)
    with pytest.raises(FoundryError, match='too many nodes'):
        analysis.report_projection(over['id'], mode)
    if mode == 'management':
        without = _padded(analysis, _without_estimates(draft), _nodes(room + 1), 'd' * 32)
        with pytest.raises(FoundryError, match='too many nodes'):
            analysis.report_projection(without['id'], mode)
