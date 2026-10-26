"""Bind explicit financial amount assertions to server-prepared fact meanings.

This is a narrow deterministic check, not a prose understanding or accounting
recognition engine. It covers cash stock distinctions, a filtered receivables
population and contradictions of explicit transaction types. Callers pass only
referenced, server-prepared facts and stored runs;
model-authored labels, assumptions and claimed approvals are not authorities.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


CLAIM_SEMANTICS_VERSION = 19

_LABELS = {
    "available_cash": ("可用资金", "可用现金余额", "可用现金", "可动用资金", "可支配现金", "非受限现金", "非受限资金", "available cash", "unrestricted cash"),
    "closing_cash": ("期末现金余额", "期末现金", "现金余额", "closing cash", "cash balance"),
    "closing_restricted_cash": ("受限现金余额", "受限资金", "受限现金", "restricted cash"),
    "full_receivables": ("完整应收毛额", "全部应收账款", "全部应收毛额", "完整应收账款",
                         "total gross receivables", "all receivables"),
    "revenue": ("本期新增收入", "新增收入", "本期收入", "营业收入", "收入", "revenue"),
    "capitalized_asset": ("资本化资产", "资本化金额", "资本化支出", "capitalized asset", "capitalized cost"),
}
_CASH = {"available_cash", "closing_cash", "closing_restricted_cash"}
# These are explicit source/output types, not guesses from narrative words. A
# match rejects a contradiction; it never qualifies the source or recognizes an
# accounting transaction by itself.
_INCOMPATIBLE = {
    "revenue": {"prepayment_received", "unperformed_customer_prepayment", "contract_liability",
                "unearned_revenue", "old_ar_collection", "additional_old_ar_collection"},
    "capitalized_asset": {"ordinary_operating_expense", "ordinary_service_expense"},
}
_KEY = {label.casefold(): key for key, labels in _LABELS.items() for label in labels}
_LABEL = "|".join(re.escape(label) for label in sorted(_KEY, key=len, reverse=True))
_NUMBER = r"[+\-−－]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_ASSERTION = re.compile(
    rf"(?P<label>{_LABEL})\s*(?:(?:合计|共计|约|总计)?(?:为|是|达到)|合计|共计|约|总计|equals?|is|was|are|[：:=＝|])?\s*"
    rf"(?P<number>{_NUMBER})(?![\d.])", re.I)
_REVERSE = re.compile(
    rf"(?P<number>{_NUMBER})\s*(?:万元|亿元|元|CNY|USD)?\s*"
    rf"(?:计为|列为|作为|视为|视作|当作|属于|is|as)\s*(?P<label>{_LABEL})", re.I)
_CLAUSE = re.compile(r"[，,；;。\n!?！？]|但是|不过|然而|但|而|实际(?:上)?|\b(?:but|however|actually)\b", re.I)
_NEGATED = re.compile(r"(?:不能|不应|不得|不可|不宜|并非|不是|不代表|不等于|不(?:再|重复|再次)?(?:确认|认列|计入|列入|资本化)|误将|误称|错误示例|假设|如果|假如|倘若|若|"
                      r"\b(?:not|never|incorrect|wrong|if|assuming)\b)[^，,；;。\n]{0,40}$", re.I)
_REJECTED = re.compile(r"^\s*(?:万元|亿元|元|CNY|USD)?\s*[”’\"']?\s*(?:这一|这种|的)?"
                       r"(?:说法|表述|口径|结论)?\s*(?:(?:是|为)?\s*(?:错误|不正确|不成立|有误)|并非真实)")
_SCOPE_KEYS = ("ledger", "organization", "currency", "unit")
_FACT_TOKEN = re.compile(r"\{\{fact:([^{}]+)\}\}")
_CHECK_SUBJECT = re.compile(r"模型(?:联动)?(?:检查|核查)|model_checks|\bmodel\s+checks\b|"
                            r"(?:所有|全部)\s*\d+\s*项(?:检查|核查)|\ball\s+\d+\s+checks\b", re.I)
_CHECK_UNIVERSAL = re.compile(r"全部|所有|各项|每项|均|都|\b(?:all|every)\b", re.I)
_CHECK_ZERO = re.compile(
    r"(?:差异|差额|differences?|(?<![A-Za-z0-9_])diffs?(?![A-Za-z0-9_]))"
    r"(?:\s*(?:全部|均|都|为|是|等于|[=＝]|are|is|of|all|equals?(?:\s+to)?))*"
    r"\s*(?:零|zero\b|0(?:\.0+)?(?!\d|\.\d))|"
    r"(?P<leading_zero>(?<![\w.])(?:zero\b|0(?:\.0+)?(?!\d|\.\d))"
    r"\s+(?:differences?\b|diffs?(?![A-Za-z0-9_]))|零\s*(?:差异|差额))", re.I)
_CHECK_BREAK = re.compile(r"[。\n!?！？]|\.(?!\d)|但是|不过|然而|但|\b(?:but|however)\b", re.I)
_CHECK_PREFIX = re.compile(
    r"(?:[\s*#\"'“‘-]|全部|所有|各项|每项|本期|本次|当前|本运行|期初|期末|"
    r"[零一二三四五六七八九十百\d]+\s*项?|\b(?:all|every|the|twelve)\b|本例)*", re.I)
_CHECK_BRIDGE = re.compile(
    r"(?:\s|[，,；;：（(:*]|的|实际(?:值)?(?:与|和)期望(?:值)?|全部|所有|各项|每项|均|都|已|通过|合格|结果|状态|为|是|"
    r"所以|各项|\b(?:have|has|all|each|passed|pass|their|the|with|and|actual|expected|values?)\b)*", re.I)
_CHECK_INCLUDE = re.compile(r"[，,（(]\s*(?:包括|包含|including\b)[^，,；;()（）]*[，,）)]", re.I)
_CHECK_HYPOTHETICAL = re.compile(r"假设|如果|假如|倘若|若|\b(?:if|assuming)\b", re.I)
_CHECK_NEGATION = re.compile(
    r"不能|不可|不应|不得|并非|不是|不等于|不代表|不意味着|未必|假设|如果|假如|倘若|若|"
    r"\b(?:not|never|incorrect|wrong|if|assuming)\b", re.I)
_CHECK_REJECTED = re.compile(r"^[\s\"'”’)]*(?:(?:(?:this|that)\s+claim\s+)?(?:is\s+)?|"
                             r",\s*(?:this|that)\s+(?:claim|statement)\s+is\s+)(?:wrong|incorrect|false)\b", re.I)
_CHECK_CAUTION_TOPIC = re.compile(
    rf"{_CHECK_PREFIX.pattern}(?P<subject>{_CHECK_SUBJECT.pattern})\s*(?:全部|均)?通过\s*"
    r"(?:不等于|不表示|不代表|不意味着)(?:所有|全部|各(?:项)?|每(?:项)?)"
    r"(?:检查|核查)?(?:的)?(?:差额|差异)(?:一定|必然)?(?:全部|均|都)?为零[ \t]*[，,][ \t]*", re.I)
_RECEIPT_CREATES_AR = re.compile(
    r"(?:收款|客户付款)(?P<bridge>[^；;。\n!?！？]{0,48}?)(?:(?:形成|产生)(?:了)?(?:新增|新的?)?应收(?:账款)?|"
    r"(?:导致|使得?|引起)应收(?:账款)?(?:增加|新增)|增加(?:了)?应收(?:账款)?)")
_RECEIPT_BRIDGE = re.compile(
    r"(?:\s|本身|直接|自动|因此|从而|会|将|可|就|能够|视为|被视为|并且|并|且|[，,])*|"
    r"对应(?:本期|当期)?已履约(?:的)?服务\s*[，,]?(?:并且|并|且)|"
    r"(?:并非|不是)[^，,；;。\n]{1,20}而是(?:本期|当期)?(?:履约)?价款(?:并且|并|且)")
_RECEIPT_REPORTED = re.compile(r"^[”’\"'\s]*(?:(?:只|仅)(?:是|为)?假设|的(?:服务|债权|合同|款项))")
_RECEIPT_TAIL_DENIAL = re.compile(
    r"^[”’\"'\s]*(?:的)?(?:这一|这种)?(?:说法|表述|结论)?(?:并)?(?:不成立|不正确|不是事实)")
_RECEIPT_CONDITION = re.compile(r"假设|如果|假如|倘若|若(?!干)|\b(?:if|assuming)\b", re.I)
_RECEIPT_PREFIX_DENIAL = re.compile(
    r"(?:不能|不应|不得|不可|不宜|并非|不是|不代表|不等于|误将|误称|错误示例|"
    r"\b(?:not|never|incorrect|wrong)\b)[^，,；;。\n]{0,40}$", re.I)
_FLOW_SIGN = re.compile(
    r"(?P<label>(?:现金|资金)(?:净)?流(?:量)?|净现金流|\bnet\s+cash\s+flow)\s*"
    r"(?:为|是|呈|[：:]|is|was)\s*(?P<sign>正(?:数|值)?|负(?:数|值)?|零|0(?![\d.])|positive\b|negative\b|zero\b)", re.I)
_FLOW_WEEK = re.compile(r"第\s*([一二三四五六七八九十\d]+)\s*周|\bweek\s+(\d+)\b", re.I)
_FLOW_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_FLOW_CLASSIFIER = (r"经营(?:性|活动)?|投资(?:性|活动)?|筹资(?:性|活动)?|融资|自由|折现|贴现|受限|可用|非|"
                    r"\b(?:operating|investing|financing|free|discounted)(?:\s+activities)?\b")
_FLOW_CLASSIFIED_PREFIX = re.compile(rf"(?:{_FLOW_CLASSIFIER})(?:产生的|带来的|的|[\s:：，,])*$", re.I)
_FLOW_CLASSIFIED_TOPIC = re.compile(rf"(?:{_FLOW_CLASSIFIER})(?:产生的|带来的|的|\s)*(?:净)?(?:现金|资金)"
                                    r"(?:净)?流|\b(?:operating|investing|financing|free|discounted)"
                                    r"(?:\s+activities)?\s+(?:net\s+)?cash\s+flow", re.I)


def _decimal(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("−", "-").replace("－", "-"))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _fact_values(fact):
    values = {_decimal(fact.get("value"))}
    display = re.match(rf"^\s*({_NUMBER})(?![\d.])", str(fact.get("display_value") or ""))
    if display:
        values.add(_decimal(display[1]))
    return values - {None}


def _assertions(body):
    seen = set()
    for pattern in (_ASSERTION, _REVERSE):
        for match in pattern.finditer(body):
            # Avoid treating a longer qualified noun (e.g. 非受限现金) as its suffix.
            before = _CLAUSE.split(body[:match.start()])[-1]
            after = body[match.end():]
            if _NEGATED.search(before) or _REJECTED.match(after):
                continue
            if before.endswith(("非", "不")):
                continue
            key = (_KEY[match["label"].casefold()], match.start("number"))
            if key in seen:
                continue
            seen.add(key)
            yield key[0], match


def _metric(fact):
    return (fact.get("semantics") or {}).get("metric")


def _identity(fact, runs):
    run = runs.get(fact.get("run_id")) or {}
    rows = (run.get("result") or {}).get("rows") or []
    index = fact.get("row")
    row = rows[index] if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(rows) else {}
    scope = {**(fact.get("scope") or {}), **(fact.get("dimensions") or {}), **row}
    return (fact.get("run_id"), *(scope.get(key) for key in (*_SCOPE_KEYS, "period", "scenario")))


def _filtered_population(fact, runs):
    """Read the matched row's population from the engine's filter reconciliation."""
    run = runs.get(fact.get("run_id"))
    if not run or run.get("engine") != "finance" or fact.get("column") != "open_amount":
        return None
    result = run.get("result") or {}
    index = fact.get("row")
    rows = result.get("rows") or []
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rows):
        return None
    row = rows[index]
    if _decimal(row.get("open_amount")) != _decimal(fact.get("value")):
        return None
    filtered = (result.get("evidence") or {}).get("status_filter") or {}
    scope = tuple(row.get(key) for key in _SCOPE_KEYS)

    def amount(key):
        matching = [item for item in filtered.get(key, [])
                    if tuple((item.get("scope") or item).get(k) for k in _SCOPE_KEYS) == scope]
        return _decimal(matching[0].get("open_amount")) if len(matching) == 1 else None

    excluded = amount("excluded_open_amount_by_scope")
    total = amount("total_scope_open_amount_by_scope")
    included = amount("included_open_amount_by_scope")
    if excluded is None or excluded == 0 or total is None or included is None or included + excluded != total:
        return None
    return {"included": str(included), "excluded": str(excluded), "total": str(total),
            "scope": dict(zip(_SCOPE_KEYS, scope))}


def _template_numbers(template, facts):
    """Keep the exact identity of each template occurrence, including equal-valued facts."""
    by_id = {fact["id"]: fact for fact in facts}
    parts, bound, offset, end = [], {}, 0, 0
    for match in _FACT_TOKEN.finditer(template):
        prefix = template[end:match.start()]
        parts.append(prefix)
        offset += len(prefix)
        fact = by_id.get(match[1])
        if fact and _decimal(fact.get("value")) is not None:
            number = str(_decimal(fact["value"]))
            bound[offset] = fact
        else:
            number = match[0]
        parts.append(number)
        offset += len(number)
        end = match.end()
    parts.append(template[end:])
    return "".join(parts), bound


def _ineligible_amount_issue(fact, expected, *, position=None, text=None):
    eligibility = fact.get("evidence_eligibility") or {}
    reasons = eligibility.get("reason_codes") or ["amount_evidence_not_qualified"]
    return {"code": "fact_amount_evidence_ineligible", "severity": "error",
            "message": f"引用事实的指标 {expected} 不具备金额证据资格（{', '.join(reasons)}）。"
                       "来源输入存在不等于已核验输出；请移除额外金额或提供同指标、同范围的合格依据。"
                       "无合格依据时保留定性限制，不把输入事实引用改称核验金额。",
            "position": position, "text": str(fact.get("value")) if text is None else text,
            "expected_metric": expected, "fact_id": fact["id"], "run_id": fact.get("run_id"),
            "row": fact.get("row"), "column": fact.get("column"),
            "matched_fact_ids": [fact["id"]], "matched_fact_metrics": [_metric(fact)],
            "evidence_status": eligibility.get("status", "unverified"),
            "counts_as_amount_evidence": False, "reason_codes": reasons,
            "recovery": {"action": "prepare_explanation", "run_ids": [fact.get("run_id")],
                         "required_metric": expected, "scope_fact_id": fact["id"],
                         "requires_amount_eligible_fact": True,
                         "if_unavailable": "report_evidence_limitation"}}


def native_model_checks(runs):
    """Resolve one integrity-bound native result; callers own access/currentness."""
    if len(runs) != 1:
        return None
    from foundry.analysis import _hash
    from foundry.finance_driver_templates import TEMPLATE_ID

    run = next(iter(runs.values()))
    result = run.get("result") or {}
    checks = result.get("model_checks")
    if (run.get("engine") != "finance" or run.get("execution_status") != "succeeded"
            or result.get("template_id") != TEMPLATE_ID or not result.get("scenario_id")
            or run.get("output_hash") != _hash(result) or not isinstance(checks, list) or not checks
            or not all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] and item.get("status") in {"pass", "fail"}
                       and _decimal(item.get("difference")) is not None for item in checks)):
        return None
    if len({item["id"] for item in checks}) != len(checks):
        return None
    return run, checks


def _check_prose(body):
    # Keep offsets stable. Inline formatting is presentation, but fenced code
    # examples are not assertions. Do not concatenate otherwise separate words.
    body = re.sub(r"(?ms)^\s*(```|~~~)[^\n]*\n.*?^\s*\1[^\n]*$",
                  lambda m: re.sub(r"[^\n]", " ", m[0]), body)
    return re.sub(r"[`*]", " ", body)


def _model_check_difference_issues(body, runs):
    """Contradict explicit all-check zero assertions, never redefine check success."""
    raw_body = body
    body = _check_prose(body)
    authority = native_model_checks(runs)
    if not authority or not _CHECK_SUBJECT.search(body) or not _CHECK_ZERO.search(body):
        return []
    run, checks = authority
    nonzero = [{key: item.get(key) for key in ("id", "status", "actual", "expected", "difference")}
               for item in checks if _decimal(item["difference"]) != 0]
    if not nonzero:
        return []
    issues = []
    # Parentheses keep their subject, including the live-run parenthetical.
    offset, previous = 0, ""
    for segment in _CHECK_BREAK.split(body):
        position = body.find(segment, offset)
        separator = body[offset:position]
        offset = position + len(segment)
        prior, previous = previous, segment
        if body[offset:offset + 1] in {"?", "？"}:
            continue
        # Only an adjacent, complete model-check caution can supply the omitted
        # subject after a contrast. Other business/individual differences cannot.
        topic = _CHECK_CAUTION_TOPIC.fullmatch(prior) if separator in {"但", "但是", "然而", "不过"} else None
        if topic and _CHECK_ZERO.match(segment.lstrip()):
            subject = topic['subject']
            segment = subject + segment
            position -= len(subject)
        for subject in _CHECK_SUBJECT.finditer(segment):
            prefix = segment[:subject.start()]
            before = re.split(r"[，,；;:：()（）]", prefix)[-1]
            # Prefix assertions belong to their own clause. A conditional can
            # govern the following comma clause, but not a new semicolon clause.
            condition = re.split(r"[；;]", prefix)[-1]
            tail = segment[subject.end():subject.end() + 160]
            for match in _CHECK_ZERO.finditer(tail):
                start = position + subject.end() + match.start()
                # Inline marks preserve offsets but must not turn non**zero
                # into a standalone zero assertion.
                if match['leading_zero'] and re.search(r"[\w.][`*]+$", raw_body[:start]):
                    continue
                bridge = tail[:match.start()]
                assertion = before + segment[subject.start():subject.end()] + tail[:match.end()]
                if (not _CHECK_UNIVERSAL.search(assertion)
                        or not _CHECK_PREFIX.fullmatch(before)
                        or not _CHECK_BRIDGE.fullmatch(_CHECK_INCLUDE.sub(",", bridge))
                        or _CHECK_HYPOTHETICAL.search(condition)
                        or _CHECK_NEGATION.search(assertion)
                        or _REJECTED.match(tail[match.end():])
                        or _CHECK_REJECTED.match(tail[match.end():])):
                    continue
                issues.append({"code": "model_check_difference_claim_mismatch", "severity": "error",
                    "message": "正文称全部模型检查差异为零，但当前运行包含非零差异。检查通过须遵循各自等式或阈值规则；"
                               "请删除全量零差异断言，按实际检查状态说明。",
                    "run_id": run["id"], "output_hash": run["output_hash"],
                    "position": position + subject.end() + match.start(), "text": match[0],
                    "all_checks_passed": all(item["status"] == "pass" for item in checks),
                    "nonzero_checks": nonzero})
                break
    return issues


_CHECK_METADATA = re.compile(
    r"(?:(?:severity|等级|严重等级)\s*(?:为|是|[=:＝：]|is)?\s*(?P<severity>error|alert)\b|"
    r"(?P<level>error|alert)\b(?:-level)?(?:\s*(?:severity|等级))?|"
    r"blocks_evidence\s*(?:flag\s*)?(?:为|是|[=:＝：]|is)?\s*(?P<blocking>true|false)\b)", re.I)
_CHECK_METADATA_BRIDGE = re.compile(
    r"(?:\s|的|为|是|均为|都是|都为|均|[,:：，—–-]|"
    r"\b(?:is|are|have|has|all|with|checks|and|its|configured|currently|passes|passing|therefore)\b)*", re.I)
_CHECK_LAST = re.compile(r"(?:\bthe\s+last\s+three\b|后三项|最后三项)\s*(?:are|均为|都是|为|是)?\s*", re.I)


def _model_check_metadata_issues(body, runs):
    """Compare explicit named metadata, with a complete local ordinal anchor.

    Severity and a configured blocking flag never imply a failed check. An
    unresolved/duplicate/partial list is not a factual contradiction proof.
    """
    authority = native_model_checks(runs)
    if not authority:
        return []
    run, checks = authority
    by_id = {item['id']: item for item in checks}
    if not all(item.get('severity') in {'error', 'alert'} and type(item.get('blocks_evidence')) is bool
               for item in checks):
        return []
    prose = _check_prose(body)
    names = '|'.join(re.escape(key) for key in sorted(by_id, key=len, reverse=True))
    name = rf"(?<![\w])(?:{names})(?![\w])"
    named = re.compile(name)
    subjects = re.compile(rf"{name}(?:\s*(?:[,、]|\band\b|和|及)\s*{name})*")
    candidates = []
    for match in subjects.finditer(prose):
        ids = named.findall(match[0])
        if len(set(ids)) == len(ids):
            candidates.append((match.start(), match.end(), ids))
    for match in _CHECK_LAST.finditer(prose):
        # Ordinal aliases require the complete ordered native list in this
        # block, exactly once; no previous block or server-order guess.
        ids = named.findall(prose[:match.start()])
        if ids == list(by_id):
            candidates.append((match.start(), match.end(), ids[-3:]))
    issues, seen = [], set()
    for start, end, ids in candidates:
        before = re.split(r"[。\n!?！？;；]|\.(?!\d)|\b(?:but|however)\b|但是|然而|但", prose[:start], flags=re.I)[-1]
        if _CHECK_NEGATION.search(before):
            continue
        tail = re.split(r"[。\n!?！？;；]|\.(?!\d)|\b(?:but|however)\b|但是|然而|但", prose[end:], maxsplit=1, flags=re.I)[0]
        if prose[end + len(tail):end + len(tail) + 1] in {'?', '？'}:
            continue
        cursor = 0
        for claim in _CHECK_METADATA.finditer(tail[:180]):
            bridge = tail[cursor:claim.start()]
            if not _CHECK_METADATA_BRIDGE.fullmatch(bridge):
                break
            if _CHECK_REJECTED.match(tail[claim.end():]) or _REJECTED.match(tail[claim.end():]):
                break
            field = 'blocks_evidence' if claim['blocking'] else 'severity'
            asserted = claim['blocking'].lower() == 'true' if claim['blocking'] else (claim['severity'] or claim['level']).lower()
            wrong = [{'id': key, 'actual': by_id[key][field], 'status': by_id[key]['status']} for key in ids
                     if by_id[key][field] != asserted]
            position = end + claim.start()
            if wrong and (position, field) not in seen:
                seen.add((position, field))
                issues.append({'code': 'model_check_metadata_claim_mismatch', 'severity': 'error',
                    'message': '模型检查等级或证据阻断配置的表述与当前运行不符；检查状态、等级和阻断配置须分别说明。',
                    'run_id': run['id'], 'output_hash': run['output_hash'], 'position': position,
                    'text': body[position:end + claim.end()], 'field': field, 'asserted': asserted,
                    'mismatched_checks': wrong})
            cursor = claim.end()
    return issues


def model_check_claim_issues(body, *, runs=()):
    """Shared bounded checker for saved prose and pre-delivery public text."""
    by_run = {run['id']: run for run in runs if isinstance(run, dict) and run.get('id')}
    return _model_check_difference_issues(body, by_run) + _model_check_metadata_issues(body, by_run)


def _receipt_causation_issues(body, runs):
    """Reject an explicit receipt-origin assertion in a bound statement model.

    This does not infer transaction allocations from statement totals. Credit
    recognition and later collection may be described separately; denial,
    question and conditional controls are not affirmative causal assertions.
    """
    if len(runs) != 1:
        return []
    from foundry.analysis import _hash
    from foundry.finance_driver_templates import TEMPLATE_ID

    run = next(iter(runs.values()))
    result = run.get("result") or {}
    if (run.get("engine") != "finance" or run.get("execution_status") != "succeeded"
            or result.get("template_id") != TEMPLATE_ID or not result.get("scenario_id")
            or run.get("output_hash") != _hash(result)):
        return []
    issues = []
    for match in _RECEIPT_CREATES_AR.finditer(body):
        prefix = _CLAUSE.split(body[:match.start()])[-1]
        assertion = match[0]
        tail = body[match.end():]
        sentence_tail = re.split(r"[。\n!?！？]", tail, maxsplit=1)[0]
        terminator = tail[len(sentence_tail):len(sentence_tail) + 1]
        condition = re.split(r"[；;。\n!?！？]", body[:match.start()])[-1]
        if (not _RECEIPT_BRIDGE.fullmatch(match["bridge"]) or re.search(r"(?:未|没有)$", prefix)
                or _RECEIPT_PREFIX_DENIAL.search(prefix) or _RECEIPT_REPORTED.match(tail)
                or _RECEIPT_TAIL_DENIAL.match(tail)
                or _RECEIPT_CONDITION.search(condition) or _REJECTED.match(tail)
                or terminator in {"?", "？"}):
            continue
        issues.append({"code": "receipt_receivable_causation_mismatch", "severity": "error",
                       "message": "收款本身不形成新增应收。收入确认依履约假设；对已识别债权的收款用于清偿或冲减债权。"
                                  "同一债权须有来源证明足额清偿且无余额才称结清，部分清偿不能写成结清。"
                                  "汇总数不能证明具体交易分配。",
                       "run_id": run["id"], "output_hash": run["output_hash"],
                       "position": match.start(), "text": assertion})
    return issues


def _cash_flow_sign_issues(body, facts, runs):
    """Check explicit weekly net-flow signs against a cited cash forecast row.

    Cash balance sign supplies no flow proof. Ambiguous periods/runs and
    unsupported narrative forms remain outside this narrow contradiction check.
    """
    from datetime import date
    from foundry.analysis import _hash

    rows = {}
    valid_runs = {}
    for fact in facts:
        run_id = fact.get("run_id")
        run = runs.get(run_id) or {}
        result = run.get("result") or {}
        index = fact.get("row")
        if run_id not in valid_runs:
            evidence = result.get("evidence") or {}
            valid_runs[run_id] = bool(
                run.get("engine") == "finance" and run.get("execution_status") == "succeeded"
                and result.get("domain") == "foundry.finance.scenario_result.v1" and result.get("scenario_id")
                and evidence.get("horizon_start") and evidence.get("horizon_end")
                and run.get("output_hash") == _hash(result))
        output_rows = result.get("rows") or []
        if (not valid_runs[run_id] or isinstance(index, bool) or not isinstance(index, int)
                or not 0 <= index < len(output_rows)
                or fact.get("column") not in {"opening_cash", "receipts", "payments", "closing_cash"}
                or (fact.get("evidence_eligibility") or {}).get("counts_as_amount_evidence") is not True):
            continue
        row = output_rows[index]
        values = {key: _decimal(row.get(key)) for key in ("opening_cash", "receipts", "payments", "closing_cash")}
        if (None in values.values() or _decimal(fact.get("value")) != values[fact["column"]]
                or values["opening_cash"] + values["receipts"] - values["payments"] != values["closing_cash"]):
            continue
        try:
            start, end = date.fromisoformat(row["week_start"]), date.fromisoformat(row["week_end"])
        except (KeyError, TypeError, ValueError):
            continue
        if (end - start).days != 6 or type(row.get("week")) is not int:
            continue
        rows[(run_id, index)] = (row, values, start, end)

    issues = []
    chinese_weeks = {word: number for number, word in enumerate(
        ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三"), 1)}
    for match in _FLOW_SIGN.finditer(body):
        context = re.split(r"[；;。\n!?！？]", body[:match.start()])[-1]
        prefix = _CLAUSE.split(context)[-1]
        tail = body[match.end():]
        sentence_tail = re.split(r"[；;。\n!?！？]", tail, maxsplit=1)[0]
        terminator = tail[len(sentence_tail):len(sentence_tail) + 1]
        if (_NEGATED.search(prefix) or _CHECK_NEGATION.search(prefix)
                or re.search(r"\b(?:cannot|can't)\b|(?:仅|只)当|只有", prefix, re.I)
                or _FLOW_CLASSIFIED_PREFIX.search(context)
                or _FLOW_CLASSIFIED_TOPIC.search(context) and not re.search(
                    r"(?:整周|总体|总计|总|整体|全部|\btotal|\boverall)\s*$", prefix, re.I)
                or _CHECK_HYPOTHETICAL.search(context)
                or _REJECTED.match(tail) or _CHECK_REJECTED.match(tail)
                or re.match(r"^[”’\"'\s]*的(?:假设|条件|情形)", tail)
                or re.match(r"^[”’\"'\s]*(?:只|仅)?(?:是|为)(?:一个|一项|未经验证的?|未验证的?|待验证的?|尚未验证的?)*假设", tail)
                or re.match(r"^(?:常|确|责|担|向|增长|变化)|^\s+growth\b", tail, re.I)
                or terminator in {"?", "？"}):
            continue
        weeks = {chinese_weeks.get(item[0], int(item[0]) if item[0].isdigit() else None)
                 if item[0] else int(item[1]) for item in _FLOW_WEEK.findall(context)}
        dates = _FLOW_DATE.findall(context)
        candidates = []
        for (run_id, index), (row, values, start, end) in rows.items():
            if weeks and weeks != {row["week"]}:
                continue
            if dates and any(not start.isoformat() <= value <= end.isoformat() for value in dates):
                continue
            candidates.append((run_id, index, row, values))
        if len(candidates) != 1:
            continue
        run_id, index, row, values = candidates[0]
        net = values["receipts"] - values["payments"]
        actual = "positive" if net > 0 else "negative" if net < 0 else "zero"
        sign = match["sign"].casefold()
        claimed = "positive" if sign.startswith(("正", "positive")) else "negative" if sign.startswith(("负", "negative")) else "zero"
        if claimed == actual:
            continue
        issues.append({"code": "cash_flow_sign_mismatch", "severity": "error",
                       "message": "该周净现金流等于收款减付款；期末现金余额的正负不能证明资金流的正负。",
                       "run_id": run_id, "row": index, "output_hash": runs[run_id]["output_hash"],
                       "week_start": row["week_start"], "week_end": row["week_end"],
                       "receipts": str(values["receipts"]), "payments": str(values["payments"]),
                       "net_cash_flow": str(net), "claimed_sign": claimed,
                       "position": match.start(), "text": match[0]})
    return issues


_PERFORMANCE_STATE = re.compile(
    r"(?P<pending>(?:尚未|尚待|仍待|未|待)履约|(?<![A-Za-z0-9_])(?:(?:is\s+)?"
    r"(?:pending\s+performance|unperformed)|has\s+not\s+(?:yet\s+)?been\s+performed|"
    r"is\s+not\s+(?:yet\s+)?performed)(?![A-Za-z0-9_]))|"
    r"(?P<performed>(?:已(?:经)?|全额|全部)(?:完成)?履约|(?<![A-Za-z0-9_])"
    r"(?:(?:is\s+)?performed|has\s+been\s+performed)(?![A-Za-z0-9_]))", re.I)
_PERFORMANCE_BREAK = re.compile(r"[，,；;。\n!?！？]|但是|不过|然而|但|而是|\b(?:but|however)\b", re.I)
_PERFORMANCE_DENIAL = re.compile(
    r"不能|不可|不应|不得|并非|不是|不代表|未必|误将|误称|错误示例|\b(?:not|never|cannot|incorrect|wrong)\b", re.I)
_PERFORMANCE_CONDITION = re.compile(r"如果|假如|倘若|若(?!干)|(?<!预测)假设(?!将|设为)|\b(?:if|assuming)\b", re.I)
_PERFORMANCE_REFUTED = re.compile(
    r"^[\s\"'”’]*(?:(?:服务|合同)?[\s\"'”’]*(?:这(?:一|种)?(?:句话)?|的)?(?:说法|表述|结论)?"
    r"(?:并)?(?:不对|不成立|不正确|有误|错误)|,\s*(?:this|that)\s+(?:claim|statement)\s+is\s+"
    r"(?:incorrect|wrong|false)\b)", re.I)
_PERFORMANCE_OBJECT_ID = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+(?![A-Za-z0-9_-])")
_PERFORMANCE_REALITY = re.compile(
    r"现实(?:中|世界中)?|\bin\s+reality\b|(?P<actual>实际|\bactually)\s*$", re.I)
_PERFORMANCE_POST_PERIOD = re.compile(
    r"^\s*(?:[（(]\s*|(?:的)?(?:预测)?(?:期间|月份)(?:是|为)?\s*|(?:于|在)\s*|\bin\s+)"
    r"\d{4}-\d{2}(?![0-9])", re.I)
_PERFORMANCE_RECEIPT_PREFIX = re.compile(r"(?:本|当)(?:期|月)(?:全部|所有)?\s*$")
_PERFORMANCE_RECEIPT_TAIL = re.compile(r"^\s*收款")
_PERFORMANCE_RECEIPT_QUALIFIER = re.compile(r"^\s*[（(]([^()（）；;。\n!?！？]{1,100})[）)]")


def _performance_outside_forecast(prefix):
    """A local real-world assertion cannot be disproved by a forecast assumption."""
    markers = list(_PERFORMANCE_REALITY.finditer(prefix))
    if not markers:
        return False
    last = markers[-1]
    if last['actual'] and re.search(r"预测(?:期|中|月)?\s*$", prefix[:last.start()]):
        return False
    return not re.search(r"预测|\bforecast\b", prefix[last.end():], re.I)


def _performance_policy_condition(prefix, state, tail):
    """Only adjacent conditional roles, never a later consequence, exempt a state."""
    return bool(
        re.search(r"(?:在|当)\s*$", prefix) and re.match(r"(?:时|期间)(?:应|须|需|不得|不能|不可|不应)", tail)
        or state == "待履约" and re.search(r"(?:须|需|必须|需要)\s*$", prefix)
        and re.match(r"后(?:才|方可|方能)", tail))


def _performance_objects(prefix, records):
    """Unknown explicit IDs also occupy the subject slot; they lend no proof."""
    objects = [(m.start(), m.end(), m[0]) for m in _PERFORMANCE_OBJECT_ID.finditer(prefix)]
    for fact in records:
        key = fact.get('contract_id')
        if not isinstance(key, str) or not key:
            continue
        objects.extend((m.start(), m.end(), key) for m in re.finditer(
            r"(?<![A-Za-z0-9_-])" + re.escape(key) + r"(?![A-Za-z0-9_-])", prefix))
    return objects


def _performance_receipt_subject(prefix, tail):
    """A local current receipt label, never a bare category or all collections."""
    receipt = _PERFORMANCE_RECEIPT_TAIL.match(tail)
    if not _PERFORMANCE_RECEIPT_PREFIX.search(prefix) or not receipt:
        return None
    after = tail[receipt.end():]
    qualifier = _PERFORMANCE_RECEIPT_QUALIFIER.match(after)
    local = qualifier[1] if qualifier else ''
    if not qualifier:
        # Only an immediately attached ID and its adjacent period occupy this
        # slot. Never scan ahead to borrow an identity from another statement.
        direct = after.lstrip()
        identity = _PERFORMANCE_OBJECT_ID.match(direct)
        if identity:
            period = re.match(r"\s*[，,]?\s*\d{4}-\d{2}(?![0-9])", direct[identity.end():])
            local = direct[:identity.end() + (period.end() if period else 0)]
    label = rf"(?:本|当)(?:期|月)\s*(?:{_PERFORMANCE_STATE.pattern})\s*收款"
    # Both labels in an explicit two-category definition are category names,
    # not assertions that either type occurred. This relation ends locally;
    # a classification prefix or a later instance receives no exemption.
    category_after = after
    if re.search(r"(?<!\\)(?:\\\\)*\|", prefix):
        delimiter = re.search(r"(?<!\\)(?:\\\\)*\|", after)
        if delimiter:
            category_after = after[:delimiter.end() - 1]
    category_pair = (
        re.fullmatch(rf"\s*[与和及、]\s*{label}\s*是两种类别\s*", category_after, re.I)
        or re.fullmatch(r"\s*是两种类别\s*", category_after)
        and re.search(rf"{label}\s*[与和及、]\s*(?:本|当)(?:期|月)\s*$", prefix, re.I))
    return {'after': after, 'qualifier': local,
            'category': bool(category_pair or re.match(
                r"的(?:处理)?(?:政策|分类规则)|(?:应|需|须)?分别核对|两类[，,]", after))}


def forecast_performance_issues(body, *, performance_facts=()):
    """Reject bounded same-object assertions opposite to a verified forecast assumption.

    Facts are supplied only by the server's archived-source resolver. A missing,
    ambiguous, partial or conflicting fact proves neither performance state.
    No result here asserts actual business performance or professional approval.
    """
    records = [f for f in performance_facts if isinstance(f, dict)]
    verified = [f for f in records if f.get("status") == "verified"
                and f.get("authority") == "source_defined_forecast_assumption"
                and f.get("state") in {"performed", "pending"}]
    issues = []
    for match in _PERFORMANCE_STATE.finditer(body):
        prefix = _PERFORMANCE_BREAK.split(body[:match.start()])[-1]
        tail = re.split(r"[；;。\n!?！？]", body[match.end():], maxsplit=1)[0]
        terminator = body[match.end() + len(tail):match.end() + len(tail) + 1]
        receipt = _performance_receipt_subject(prefix, tail)
        if (_PERFORMANCE_DENIAL.search(prefix) or _PERFORMANCE_CONDITION.search(prefix)
                or _PERFORMANCE_REFUTED.match(tail) or terminator in {"?", "？"}
                or _performance_outside_forecast(prefix)
                or receipt and (receipt['category'] or _PERFORMANCE_REFUTED.match(receipt['after']))
                or _performance_policy_condition(prefix, match[0], tail)):
            continue
        objects = _performance_objects(prefix, records)
        period_prefix = list(prefix)
        for start, end, _key in objects:
            period_prefix[start:end] = ' ' * (end - start)
        period_text = ''.join(period_prefix)
        if _PERFORMANCE_POST_PERIOD.match(tail):
            period_text += ' ' + re.split(r"[，,；;。\n!?！？）)]", tail, maxsplit=1)[0]
        if receipt:
            qualifier = receipt['qualifier']
            post_objects = _performance_objects(qualifier, records)
            period_qualifier = list(qualifier)
            for start, end, _key in post_objects:
                period_qualifier[start:end] = ' ' * (end - start)
            period_text += ' ' + ''.join(period_qualifier)
            if not qualifier and _PERFORMANCE_POST_PERIOD.match(receipt['after']):
                period_text += ' ' + re.split(r"[，,；;。\n!?！？）)]", receipt['after'], maxsplit=1)[0]
            # A directly attached identity is more specific than a generic
            # receipt label or an earlier ID, including an unknown later ID.
            objects = post_objects or objects
        explicit_periods = set(re.findall(r"(?<![0-9])\d{4}-\d{2}(?![0-9])", period_text))
        if objects:
            # Resolve the object before checking whether its state is known.
            # An unknown later subject cannot borrow an earlier known state.
            nearest = max(objects, key=lambda item: (item[0], item[1]))[2]
            selected = [f for f in verified if f['contract_id'] == nearest]
        else:
            # Generic current-service descriptions are decidable only for a
            # homogeneous identified set, or an explicitly universal assertion.
            generic = re.search(r"(?:本|当)(?:期|月)(?:列示的)?[^；;。\n]{0,30}$", prefix)
            subject = receipt or re.search(r"服务|合同", prefix[-25:] + tail[:20])
            universal = re.search(r"所有|全部|均|都", prefix)
            if (not records or len(verified) != len(records) or not generic or not subject
                    or re.search(r"[A-Za-z][A-Za-z0-9_-]{2,}", prefix)
                    or receipt and len({f["state"] for f in verified}) > 1
                    or len({f["state"] for f in verified}) > 1 and not universal):
                continue
            selected = verified
        asserted = "pending" if match["pending"] else "performed"
        wrong = [f for f in selected if f["state"] != asserted
                 and (not explicit_periods or explicit_periods == {f["period"]})]
        if wrong:
            issues.append({"code": "forecast_performance_status_mismatch", "severity": "error",
                "message": "该履约状态表述与同一合同及预测期间的来源设定相反；按来源局部澄清，预测内状态不证明现实已履约。",
                "position": match.start(), "text": match[0], "asserted": asserted,
                "run_id": wrong[0]["run_id"], "output_hash": wrong[0]["output_hash"],
                "requirements_id": wrong[0]["requirements_id"], "period": wrong[0]["period"],
                "source_facts": wrong})
    return issues


# Explicit qualification metadata is independent of source traceability. These
# finite subjects/fields do not infer business facts from arbitrary prose.
_QUALIFICATION_SUBJECT = re.compile(
    r'(?P<input>\binput_facts\b|\b(?:source[- ]bound\s+)?inputs?\b|来源(?:绑定)?输入|输入事实)|'
    r'(?P<output>\b(?:output\s+facts?|outputs?|required_metrics)\b|输出事实|输出指标)', re.I)
_QUALIFICATION_VALUE = re.compile(
    r'(?P<amount>\bcounts_as_amount_evidence\s*(?:=|:|is|are|为|是)?\s*(?P<boolean>true|false)\b)|'
    r'(?P<status>\b(?P<status_value>model_verified|unverified|source_verified)\b)|'
    r'(?P<unqualified>不(?:具备|具有)金额证据资格)|'
    r'(?P<qualified>具备金额证据资格|具有金额证据资格|金额证据资格(?:全部|均)?(?:为|是)?\s*(?:true|合格))', re.I)
_QUALIFICATION_BREAK = re.compile(r'[；;。\n!?！？]|\.(?=\s|$)')
_QUALIFICATION_EXAMPLE = re.compile(r'代码示例|字段示例|字段代码示例|\b(?:code\s+example|example\s+code)\b', re.I)
_QUALIFICATION_NEGATION = re.compile(
    r'不得|不能|不应|不可|并非|不是|不等于|不代表|误称|错误示例|假设|如果|假如|倘若|'
    r'\b(?:do\s+not|cannot|must\s+not|never|not|incorrect|wrong|if|assuming)\b', re.I)
_QUALIFICATION_FOREIGN = re.compile(
    r'其他(?:运行|run)|另一(?:运行|run)|\b(?:other|another|foreign|unknown)\s+run\b|'
    r'\brun(?:_id)?\s*(?:[=:]\s*)?[`\"\']?(?P<id>[A-Za-z0-9][A-Za-z0-9_-]{5,})', re.I)


def _qualification_assertions(body):
    prose = _check_prose(body)
    offset = 0
    for segment in _QUALIFICATION_BREAK.split(prose):
        start = prose.find(segment, offset)
        offset = start + len(segment)
        if not segment.strip() or body[offset:offset + 1] in {'?', '？'}:
            continue
        subjects = list(_QUALIFICATION_SUBJECT.finditer(segment))
        previous_end = 0
        for match in _QUALIFICATION_VALUE.finditer(segment):
            preceding = [subject for subject in subjects if subject.start() < match.start()]
            if not preceding:
                continue
            # A new subject after a completed predicate restarts its own clause.
            # Lists before one shared predicate still retain both populations.
            restarted = [subject for subject in preceding if subject.start() >= previous_end]
            if restarted:
                preceding = restarted
            first = preceding[0].start()
            comma = max(segment.rfind(',', 0, first), segment.rfind('，', 0, first))
            scope_start = comma + 1 if restarted and previous_end else 0
            prefix = segment[scope_start:match.start()]
            suffix = segment[match.end():]
            value_start, previous_end = previous_end, match.end()
            if (_QUALIFICATION_EXAMPLE.search(prefix) or _QUALIFICATION_NEGATION.search(prefix)
                    or re.search(r'^\s*,?\s*this\s+(?:statement|claim)\s+is\s+(?:incorrect|wrong|false)\b|'
                                 r'^[”’"\s]*(?:这一|这种)?(?:说法|表述)(?:是)?(?:错误|不正确|不成立)', suffix, re.I)):
                continue
            # Bind each status literal to its nearest explicit namespace. A
            # binding status cannot borrow a later eligibility field.
            namespaces = list(re.finditer(r'\b(?:source_binding_status|evidence_eligibility)\b',
                                          segment[max(scope_start, value_start):match.start()], re.I))
            namespace = namespaces[-1][0].lower() if namespaces else None
            if match['status_value'] and (namespace == 'source_binding_status'
                    or match['status_value'].lower() == 'source_verified' and namespace != 'evidence_eligibility'):
                continue
            field = ('counts_as_amount_evidence' if match['amount'] or match['qualified'] or match['unqualified']
                     else 'status')
            expected = ((match['boolean'].lower() == 'true') if match['amount'] else False if match['unqualified']
                        else True if match['qualified'] else match['status_value'].lower())
            # Explicit identity fields can follow the predicate. Stop before
            # the comma introducing the next independent subject, so its field
            # cannot migrate to this claim (or a prior claim into that one).
            following = next((subject for subject in subjects if subject.start() >= match.end()), None)
            scope_end = len(segment)
            if following:
                boundary = re.search(r'[,，]', segment[match.end():following.start()])
                scope_end = match.end() + boundary.start() if boundary else following.start()
            local_scope = segment[scope_start:scope_end]
            foreign = _QUALIFICATION_FOREIGN.search(local_scope)
            if foreign and foreign['id'] and _QUALIFICATION_SUBJECT.fullmatch(foreign['id']):
                foreign = None  # 'current run input_facts' does not name a run ID.
            scopes = [(key.lower(), value) for key, value in re.findall(
                r'\b(run_id|period|scenario_id)\s*[=:]\s*[`\"\']?([A-Za-z0-9_-]+)', local_scope, re.I)]
            unknown = bool(re.search(r'\b(?:unknown|unregistered)\b|未知|未识别',
                                     segment[scope_start:first], re.I))
            unknown = unknown or len(re.findall(r'\b(?:run_id|period|scenario_id)\s*[=:]', local_scope, re.I)) != len(scopes)
            yield {'position': start + match.start(), 'text': body[start + match.start():start + match.end()],
                   'field': field, 'expected': expected, 'kinds': {subject.lastgroup for subject in preceding},
                   'foreign': foreign, 'scopes': scopes, 'unknown_subject': unknown}


def qualification_assertion_lines(body):
    """Disclosure positions only; no financial authority is granted here."""
    return [claim['position'] for claim in _qualification_assertions(body)]


def _qualification_catalog(facts, runs):
    """Positively match registered rows, hash-bound fact identity and role."""
    from foundry.analysis import _hash
    from foundry.finance_driver_templates import OUTPUT_SEMANTICS, TEMPLATE_ID, TEMPLATE_INPUTS, TEMPLATE_VERSION

    by_run = {run['id']: run for run in runs if isinstance(run, dict) and run.get('id')}
    valid = {key for key, run in by_run.items()
             if run.get('engine') == 'finance' and run.get('execution_status') == 'succeeded'
             and (run.get('result') or {}).get('template_id') == TEMPLATE_ID
             and (run.get('result') or {}).get('template_version') == TEMPLATE_VERSION
             and run.get('output_hash') == _hash(run.get('result') or {})}
    grouped = {'input': [], 'output': []}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        run = by_run.get(fact.get('run_id'), {})
        result = run.get('result') or {}
        index, rows = fact.get('row'), result.get('rows') or []
        if (fact.get('run_id') not in valid or fact.get('column') != 'value'
                or type(index) is not int or not 0 <= index < len(rows)):
            continue
        row, identity = rows[index], fact.get('metric_identity') or {}
        if (not isinstance(row, dict) or _decimal(row.get('value')) != _decimal(fact.get('value'))
                or (fact.get('source_trace') or {}).get('output_hash') != run['output_hash']
                or identity.get('template_id') != TEMPLATE_ID
                or identity.get('template_version') != TEMPLATE_VERSION
                or identity.get('scenario_id') != result.get('scenario_id')
                or fact.get('id') != _hash({'kind': 'finance-explanation-fact-v1', 'run_id': run['id'],
                    'output_hash': run['output_hash'], 'row': index, 'column': 'value', 'value': fact.get('value')})):
            continue
        metric = row.get('metric_key')
        if metric in OUTPUT_SEMANTICS and identity.get('metric_key') == metric:
            grouped['output'].append(fact)
        elif (row.get('driver') in TEMPLATE_INPUTS and row.get('depends_on') == [] and not metric
              and identity.get('metric_key') == row.get('driver')):
            grouped['input'].append(fact)
    return grouped, by_run


def qualification_claim_report(body, *, facts=(), runs=()):
    """Check literal eligibility claims against a separate server-only catalog.

    This checks current native metadata, not amounts, source truth, or arbitrary
    prose. Unknown subjects/typed fields cannot prove an inverse qualification.
    Callers own authorization/currentness and must never cite this full catalog
    merely because it was inspected for a metadata statement.
    """
    claims = list(_qualification_assertions(body))
    if not claims:
        return {'issues': [], 'unverifiable_positions': []}
    catalog, by_run = _qualification_catalog(facts, runs)
    issues, unavailable = [], []
    for claim in claims:
        foreign = claim['foreign']
        if claim['unknown_subject'] or foreign and (not foreign['id'] or foreign['id'] not in by_run):
            unavailable.append(claim['position'])
            continue
        targets = [fact for kind in claim['kinds'] for fact in catalog[kind]
                   if not foreign or fact['run_id'] == foreign['id']]
        if not targets or any(
                {str(fact.get('run_id') if key == 'run_id' else (fact.get('metric_identity') or {}).get(key))
                 for fact in targets} != {value}
                for key, value in claim['scopes']):
            unavailable.append(claim['position'])
            continue
        typed = [fact for fact in targets if (
            type((fact.get('evidence_eligibility') or {}).get(claim['field'])) is bool
            if claim['field'] == 'counts_as_amount_evidence' else
            isinstance((fact.get('evidence_eligibility') or {}).get(claim['field']), str)
            and (fact.get('evidence_eligibility') or {}).get(claim['field']) in
            {'model_verified', 'source_verified', 'unverified'})]
        conflicts = [fact for fact in typed if fact['evidence_eligibility'][claim['field']] != claim['expected']]
        if conflicts:
            issues.append({'code': 'fact_qualification_claim_mismatch', 'severity': 'error',
                'message': '资格表述与同一运行的原生元数据不一致；来源可追溯不代表具备金额证据资格。',
                'position': claim['position'], 'text': claim['text'], 'run_id': conflicts[0]['run_id'],
                'field': claim['field'], 'claimed_value': claim['expected'],
                'fact_ids': [fact['id'] for fact in conflicts],
                'actual_values': list(dict.fromkeys(fact['evidence_eligibility'][claim['field']] for fact in conflicts))})
        elif len(typed) != len(targets):
            unavailable.append(claim['position'])
    return {'issues': issues, 'unverifiable_positions': unavailable}


def check_claim_semantics(body: str, facts: list[dict], *, runs=(), body_template=None, trusted_fact_ids=(),
                          referenced_fact_ids=(), performance_facts=(), qualification_facts=()) -> list[dict]:
    """Return blocking issues for affirmative amount/type or population mismatches.

    Existing numeric/source checks still own uncited values and proof validity.
    A negation, comparison threshold or hypothetical is not an amount assertion.
    An unrecognized narrative is not deemed professionally verified by this check.
    body_template is optional: callers must first verify that rendering it with
    these facts reproduces the current prose (excluding trusted generated regions).
    trusted_fact_ids is server-only: a verified source recipe plus the original
    source row's metric identity must support each ID. It is not a caller flag,
    and a numerically valid recipe alone does not prove financial meaning.
    referenced_fact_ids is the server-resolved set of actual cell references;
    merely preparing a fact does not assert or qualify its amount.
    """
    facts = [fact for fact in facts if isinstance(fact, dict)]
    trusted = set(trusted_fact_ids)
    by_run = {run["id"]: run for run in runs if isinstance(run, dict) and run.get("id")}
    cash_facts = [fact for fact in facts if _metric(fact) in _CASH]
    issues = (model_check_claim_issues(body, runs=by_run.values()) + _receipt_causation_issues(body, by_run)
              + _cash_flow_sign_issues(body, facts, by_run)
              + forecast_performance_issues(body, performance_facts=performance_facts)
              + qualification_claim_report(body, facts=qualification_facts, runs=by_run.values())["issues"])
    from foundry.finance_driver_templates import TEMPLATE_ID

    # `facts` contains only references resolved by the service against actual
    # runs. A native result-cell reference cannot change its evidence category
    # by changing a label or self-declaring a different claim basis. Unreferenced
    # inputs stay visible; independent dataset/assumption claims are unaffected.
    native_ineligible = set()
    referenced = set(referenced_fact_ids)
    for fact in facts:
        run = by_run.get(fact.get("run_id")) or {}
        if (fact.get("id") in referenced and run.get("engine") == "finance"
                and (run.get("result") or {}).get("template_id") == TEMPLATE_ID
                and (fact.get("metric_identity") or {}).get("template_id") == TEMPLATE_ID
                and _decimal(fact.get("value")) is not None
                and (fact.get("evidence_eligibility") or {}).get("counts_as_amount_evidence") is not True
                and fact.get("id") not in trusted):
            issues.append(_ineligible_amount_issue(fact, _metric(fact)))
            native_ineligible.add(fact["id"])
    assertions = sorted(_assertions(body), key=lambda item: item[1].start())
    template_assertions = []
    if isinstance(body_template, str):
        numbered, bindings = _template_numbers(body_template, facts)
        template_assertions = sorted(((expected, match, bindings.get(match.start("number")))
                                      for expected, match in _assertions(numbered)), key=lambda item: item[1].start())
    for occurrence, (expected, match) in enumerate(assertions):
        value = _decimal(match["number"])
        bound_fact = None
        if occurrence < len(template_assertions):
            template_expected, template_match, template_fact = template_assertions[occurrence]
            # A stale/different template never supplies the actual body's value.
            if template_expected == expected and value == _decimal(template_match["number"]):
                bound_fact = template_fact
        candidates = [bound_fact] if bound_fact is not None else [fact for fact in facts if value in _fact_values(fact)]
        if not candidates:
            continue  # The existing uncited-number validator owns this case.
        if expected == "full_receivables":
            populations = [(fact, _filtered_population(fact, by_run)) for fact in candidates]
            conflicting = [(fact, population) for fact, population in populations
                           if population and _decimal(population["total"]) != value]
            if not conflicting:
                continue
            fact, population = conflicting[0]
            issues.append({"code": "fact_population_scope_mismatch", "severity": "error",
                           "message": "正文把筛选后的应收子集称为完整应收；请保留排除金额并调节到完整口径。",
                           "fact_id": fact["id"], "run_id": fact["run_id"], "position": match.start("number"),
                           "text": match["number"], "expected_metric": expected, "population": population})
        else:
            matching = [fact for fact in candidates if _metric(fact) == expected]
            compatible = [fact for fact in matching
                          if (fact.get("evidence_eligibility") or {}).get("counts_as_amount_evidence") is True
                          or fact.get("id") in trusted]
            mismatch = False
            if expected in _CASH and cash_facts:
                mismatch = not compatible
                # Without an exact token, equal values from another run/scope
                # cannot decide which cash stock the author actually referenced.
                if bound_fact is None and compatible:
                    identities = {_identity(fact, by_run) for fact in candidates if _metric(fact) in _CASH}
                    mismatch = len(identities) > 1 and any(_metric(fact) != expected for fact in candidates if _metric(fact) in _CASH)
            elif expected in _INCOMPATIBLE:
                conflicting = [fact for fact in candidates if _metric(fact) in _INCOMPATIBLE[expected]]
                mismatch = bool(conflicting) and (bound_fact is not None or not compatible)
            if not mismatch:
                continue
            if expected in _CASH and matching and not compatible:
                # Identity and qualification are separate failures. Keep the
                # same blocking verdict and the exact token's fact identity.
                fact = matching[0]
                if fact["id"] not in native_ineligible:
                    issues.append(_ineligible_amount_issue(fact, expected, position=match.start("number"), text=match["number"]))
                continue
            issues.append({"code": "fact_metric_semantics_mismatch", "severity": "error",
                           "message": "正文财务含义与引用事实不一致；请引用相同口径、范围及交易类型的事实。",
                           "position": match.start("number"), "text": match["number"], "expected_metric": expected,
                           "fact_id": candidates[0]["id"], "matched_fact_ids": [fact["id"] for fact in candidates],
                           "matched_fact_metrics": [_metric(fact) for fact in candidates]})
    unique = {}
    for issue in issues:
        # A rendered value and its original token describe the same mismatch.
        key = (issue["code"], issue.get("fact_id", issue.get("run_id")), issue.get("expected_metric"), issue["text"])
        unique.setdefault(key, issue)
    return list(unique.values())
