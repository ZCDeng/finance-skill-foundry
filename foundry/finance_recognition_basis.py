"""Keep service completion separate from an expense or liability conclusion.

This closed, source-bound guard does not recognize or authorize a transaction.
It only checks unconditional expense/liability language against explicit service
facts in the bound snapshots. Amounts, SQL result labels, proposed entries and
approval status do not establish service direction or economic nature.
"""
from __future__ import annotations

import re

from foundry.errors import FoundryError

VERSION = 1
_FIELDS = ('service_completed', 'service_direction', 'economic_nature')
_DIRECTIONS = {'received', 'provided'}
_NATURES = {'expense', 'capitalizable_asset', 'revenue'}
_COMPLETED = {'yes', 'true', '1', 'completed', '已完成', '是'}
# Account names and numeric totals are intentionally absent: they do not prove
# transaction nature. A source may name this qualitative field explicitly.
_NATURE_FIELDS = ('economic_nature', 'recognition_nature', 'transaction_nature')
_EN_ACCOUNT = r'(?:expenses?|liabilit\w*)'
_EN_STATE = (r'(?:(?:is|was|are|were|has\s+been|have\s+been|remains?|remained)\s+)?'
             r'(?:(?:[a-z]+ly|still|already)\s+){0,2}(?:omitted|unrecorded|understated)')
_EXPENSE = re.compile(r'费用|负债|义务|应付|应计|预提|\b(?:expenses?|liabilit\w*|accru\w*)\b', re.I)
_ASSERTION = re.compile(
    r'(?:漏记|未记录|未入账|少计|未计提|补提|补记|应(?:当)?确认|应(?:当)?计提|须确认|确定|确认为|已构成|形成)[^。；;\n，,]{0,28}'
    r'(?:费用|负债|义务|应付|应计|预提)|'
    r'(?:费用|负债|义务|应付|应计|预提)[^。；;\n，,]{0,12}(?:漏记|未记录|未入账|少计|应确认|应计提)|'
    r'借\s*[：:]?[^。；;\n，,]{0,24}?(?:费用|expense)'
    r'(?:\s*贷\s*[：:]?\s*(?:应计负债|应计费用|应付账款|应付费用|其他应付款|预提费用|应付))?|'
    r'\b(?:debit\s+(?:\w+\s+){0,3}expenses?|(?:omitted|unrecorded|understated)\s+'
    r'(?:(?:the|an?)\s+)?' + _EN_ACCOUNT + r'|recognize\s+(?:an?\s+)?' + _EN_ACCOUNT + r'|'
    + _EN_ACCOUNT + r'\s+' + _EN_STATE + r')\b', re.I)
_SENTENCE = re.compile(r'[。；;\n!?！？]|\.(?!\d)')
_CONTRAST = re.compile(r'(?:但是|但|然而|不过)|\b(?:but|however)\b', re.I)
_CONDITION = re.compile(r'假设|如果|假如|倘若|仅在|若(?!干)|\b(?:if|assuming|provided\s+that)\b', re.I)
_CONDITION_FACT = re.compile(
    r'(?:接受|收受|收到|提供)[^，,。；;\n]{0,12}服务|(?:本企业|为|是)[^，,。；;\n]{0,8}(?:接受|收受|提供)|'
    r'(?:符合[^，,。；;\n]{0,12}|应(?:予)?|已经|已|须|需|可)(?:费用化|资本化)|'
    r'(?:费用|负债|义务|应付|应计|预提|总账)[^，,。；;\n]{0,12}(?:漏记|未入账|未记录)|'
    r'(?:漏记|未入账|未记录)[^，,。；;\n]{0,12}(?:费用|负债|义务|应付|应计|预提)|'
    r'\bservice\b[^，,。；;\n]{0,25}\b(?:received|provided)\b|'
    r'\b(?:received|provided)\b[^，,。；;\n]{0,15}\bservice\b|'
    r'\b(?:expensed|capitaliz\w*|qualif\w*\s+as\s+(?:an?\s+)?expenses?)\b|'
    r'\b' + _EN_ACCOUNT + r'\s+' + _EN_STATE + r'\b|'
    r'\b(?:unrecorded|omitted|understated)\s+(?:an?\s+)?' + _EN_ACCOUNT + r'\b', re.I)
_CONSEQUENT = re.compile(r'[，,]|则|那么|就(?:可|应)|请|\b(?:then|please|ask|request|contact)\b', re.I)
_NEGATION = re.compile(r'不能|不应|不得|不可|不宜|并非|不是|不代表|不等于|尚不能|未必|'
                       r'\b(?:not|never|cannot|incorrect|wrong)\b', re.I)
_QUESTION = re.compile(r'是否|待核实|待核对|尚待核|尚需核|需核实|需核对|\bwhether\b', re.I)
_TENTATIVE = re.compile(r'可能|或许|疑似|待核(?:实|对)?|\b(?:may|might|possibly|potentially)\b', re.I)
_JOIN = re.compile(r'(?:而且|并且|而|且|并)(?=应|须|建议|必须|需要|要|可|费用|负债|义务|应付|应计|总账|存在)|\band\b', re.I)
_REJECTED = re.compile(r'^[”’\"\s]*(?:这一|这种|的)?(?:说法|结论|表述)?(?:并)?'
                       r'(?:依据不足|不成立|不正确|错误|不应采用)|'
                       r'^[”’\"\s]*(?:is\s+)?(?:(?:an?|the)\s+)?(?:incorrect|wrong|unsupported)', re.I)


def _completed(value):
    return value is True or isinstance(value, (str, int)) and str(value).strip().casefold() in _COMPLETED


def _facts(row):
    facts = {field: row[field] for field in _FIELDS if field in row}
    if 'economic_nature' not in facts:
        values = {str(row[key]).strip().casefold() for key in _NATURE_FIELDS if row.get(key) not in (None, '')}
        if len(values) == 1:
            facts['economic_nature'] = values.pop()
    for field in ('service_direction', 'economic_nature'):
        if field in facts:
            facts[field] = str(facts[field]).strip().casefold()
    return facts


def _source_groups(rows):
    """Never join different wide records or duplicate/conflicting long keys."""
    wide = [(index, row) for index, row in enumerate(rows, 1)
            if isinstance(row, dict) and 'service_completed' in row]
    for index, row in wide:
        if _completed(row.get('service_completed')):
            yield [index], _facts(row)
    long_rows = [(index, row) for index, row in enumerate(rows, 1)
                 if isinstance(row, dict) and isinstance(row.get('name'), str) and 'value' in row]
    if not long_rows or not any(row['name'] == 'service_completed' and _completed(row['value']) for _, row in long_rows):
        return
    # A key/value snapshot is one explicit profile only when its keys are unique.
    # Duplicated keys retain the completion marker but never supply direction.
    keys = [row['name'] for _, row in long_rows]
    values = {row['name']: row['value'] for _, row in long_rows}
    if len(keys) != len(set(keys)):
        values = {'service_completed': 'yes'}
    yield [index for index, _ in long_rows], _facts(values)


def recognition_basis_report(analysis, bindings, *, allowed=None):
    """Read hash-checked bound source snapshots; caller-authored report fields are never proof.

    Explicit direction/nature only removes this narrow missing-basis objection;
    it confers neither amount eligibility, complete recognition, nor posting.
    """
    ceiling = None if allowed is None else set(allowed)
    ids = sorted({value for value in (bindings or {}).values() if isinstance(value, str)
                  and (ceiling is None or value in ceiling)}) if isinstance(bindings, dict) else []
    sources, unavailable = [], []
    for dataset_id in ids:
        try:
            dataset = analysis.read_dataset(dataset_id)
        except (FoundryError, OSError, ValueError, KeyError, TypeError):
            unavailable.append(dataset_id)
            continue
        for row_ids, facts in _source_groups(dataset.get('rows') or []):
            missing = [field for field, values in (('service_direction', _DIRECTIONS), ('economic_nature', _NATURES))
                       if facts.get(field) not in values]
            sources.append({'dataset_id': dataset_id, 'source_hash': dataset.get('source_hash'),
                            'data_hash': dataset.get('data_hash'), 'source_rows': row_ids,
                            'facts': facts, 'missing_fields': missing})
    missing = [field for field in ('service_direction', 'economic_nature')
               if any(field in source['missing_fields'] for source in sources)]
    status = 'insufficient' if unavailable or missing else 'explicit_source_basis' if sources else 'not_applicable'
    return {'version': VERSION, 'status': status, 'source_dataset_ids': ids,
            'sources': sources, 'missing_fields': missing, 'unavailable_dataset_ids': unavailable,
            'counts_as_amount_evidence': False, 'posting_authorized': False,
            'qualification': 'qualitative_service_basis_only',
            'message': (('绑定源存在读取失败，不能以可读取部分认定确认依据完整。' if unavailable else '')
                        + '服务完成不说明本企业接受还是提供服务，也不决定费用化或资本化。'
                        '子账与总账差额只证明算术差，不能直接认定费用、负债漏记或给确定借贷；'
                        '审批pending不等于义务不存在。核对合同、服务方向、经济性质、凭证与接口后提出待审批方案。'
                        if sources or unavailable else '')}


def _basis_condition(text, assertion=''):
    """An economic-fact condition, not an instruction to obtain documents."""
    conditions = list(_CONDITION.finditer(text))
    if not conditions:
        return False
    tail = text[conditions[-1].end():]
    consequence = _CONSEQUENT.search(tail)
    # If the assertion is itself within the condition, include its predicate.
    # A following request/consequent is never used to manufacture that predicate.
    fact_clause = tail[:consequence.start()] if consequence else tail + assertion
    return bool(_CONDITION_FACT.search(fact_clause))


def _qualified(clause, match, *, question=False):
    before, after = clause[:match.start()], clause[match.end():]
    parts = re.split(r'[，,]', before)
    # Both preposed and directly attached postposed conditions must concern
    # service direction, economic nature or whether the item was recorded.
    if _basis_condition(before, match.group()) or (
            _CONDITION.match(after.lstrip(' ，,')) and _basis_condition(after)):
        return True
    # A denial/question must govern the assertion, not an earlier comma clause.
    prefix = _JOIN.split(parts[-1])[-1]
    # Include the claim for join lookahead: its subject can start the match.
    local = _JOIN.split(parts[-1] + match.group())[-1]
    if _NEGATION.search(local) or _QUESTION.search(local) or _TENTATIVE.search(local):
        return True
    if re.match(r'^\s*(?:的)?(?:可能|待核(?:实|对)?)', after):
        return True
    if question and (re.match(r'^\s*(?:了)?吗[，,]\s*还是', after)
                     or re.match(r'^\s*(?:is|was|are|were|has|have)\b', prefix, re.I)):
        return True
    # A terminal question qualifies this very assertion, not an earlier clause
    # followed by "do you agree?" or a question about whether it was repaired.
    if question and re.fullmatch(r'\s*[”’\"\']*(?:(?:了)?(?:吗|么|呢)?|是否(?:属实|成立|正确))\s*', after):
        return True
    if _REJECTED.search(after):
        return True
    # A quoted proposal explicitly rejected after its closing quote is not an
    # affirmative posting suggestion; keep that scope local to this clause.
    quote = re.search(r'[”’\"](?P<tail>.*)', after) if re.search(r'[“‘\"]', before) else None
    return bool(quote and _REJECTED.search(quote.group('tail')))


def recognition_claim_issues(body, report):
    """Reject affirmative expense direction unsupported by a completed-service source.

    Reports are created by recognition_basis_report, not accepted from callers'
    JSON. Questions, conditional examples and denied assertions remain editable.
    A received capital asset or a provided service cannot support expense prose.
    """
    sources = report.get('sources') or []
    unavailable = report.get('unavailable_dataset_ids') or []
    if (not sources and not unavailable) or (not unavailable and all(
            source.get('facts', {}).get('service_direction') == 'received'
            and source.get('facts', {}).get('economic_nature') == 'expense'
            and not source.get('missing_fields') for source in sources)):
        return []
    issues = []
    position = 0
    for sentence in _SENTENCE.split(str(body or '')):
        sentence_at = str(body or '').find(sentence, position)
        position = sentence_at + len(sentence)
        question = str(body or '')[position:position + 1] in ('?', '？')
        offset = 0
        for clause in _CONTRAST.split(sentence):
            clause_at = sentence.find(clause, offset)
            offset = clause_at + len(clause)
            if not _EXPENSE.search(clause):
                continue
            for match in _ASSERTION.finditer(clause):
                if _qualified(clause, match, question=question and offset == len(sentence)):
                    continue
                issues.append({'code': 'recognition_basis_unverified', 'severity': 'error',
                               'position': sentence_at + clause_at + match.start(),
                               'source_dataset_ids': sorted({source['dataset_id'] for source in sources} | set(unavailable)),
                               'unavailable_dataset_ids': list(unavailable),
                               'missing_fields': list(report.get('missing_fields') or []),
                               'counts_as_amount_evidence': False, 'posting_authorized': False,
                               'message': report.get('message') or '服务源事实不支持确定的费用/负债确认方向。'})
                break
    return issues
