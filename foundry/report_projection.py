"""Canonical report export projections.

The projection is the server-owned boundary between an editable draft and
format-specific renderers.  It carries the draft identity, review state and a
stable projection hash so every exported format can be traced to the same
business document.
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from foundry.errors import FoundryError
from foundry.report_documents import (
    INLINE_TYPES,
    MAX_TABLE_ATTR_TEXT,
    report_document_from_markdown_body,
    report_document_markdown,
    report_nodes_from_markdown,
    validate_report_document,
)

REPORT_PROJECTION_MODES = {"management", "audit"}
ESTIMATE_LABEL = "（估算）"
_SCALE = r"(?:百万|千万|亿|万|千)"
_CURRENCY = r"(?:美元|港元|港币|欧元|日元|英镑|人民币|元)"
_MEASURE = (r"(?:平方公里|平方米|平米|立方米|千瓦时|兆瓦|千瓦|千克|公斤|公里|千米|吨|人次|人|户|台|辆|套|间|座|张|股|份"
            r"|箱|桶|升|床|件|册)")
_PER = r"(?:平方米|平米|千克|公斤|公里|小时|人次|人|吨|月|年|日|天|户|台|件|次|股|份|辆|套|间|个|座|张|床|箱|桶|升)"
# The whole unit written right after a number stays with it (万, 万元, 万元人民币, 万吨, 万平方米, 亿股, 万元/人, 元/吨);
# the label goes after it. A bare measure word counts only where no more of a word follows it (120 吨。, not 120 吨钢).
_UNIT_AFTER = re.compile(
    rf"[^\S\n]?(?:{_SCALE}?{_CURRENCY}(?:人民币)?|{_SCALE}{_MEASURE}|{_MEASURE}(?![一-鿿])|{_SCALE})(?:/{_PER})?"
)
# A money unit, to compare a number with an estimate kept in another scale (11.78 亿元 and 117,814.56 万元).
_MONEY_UNIT = re.compile(rf"[^\S\n]?(?:(?P<scale>{_SCALE}?)(?:元|人民币)(?:人民币)?|(?P<bare>{_SCALE}))")
_MONEY_SCALES = {"": 1, "千": 10**3, "万": 10**4, "百万": 10**6, "千万": 10**7, "亿": 10**8}
# A classifier after a number makes it a count (3 个区域, 0 项, 2 级, 1.5 倍); a count is never an estimate here.
_COUNT_AFTER = re.compile(r"[^\S\n]?(?:个|项|家|次|笔|条|名|位|类|级|倍|季度)")
# A rounded copy keeps at least this many significant digits of the estimate (117,815, 11.78 亿元); a number with
# fewer (1, 12) is too coarse to tell from an unrelated number, so it is never taken for a rounded estimate.
_ROUNDED_DIGITS = 3
# 估算 said right after the number or its unit: a bracketed label (（估算）, （估算值）, （按集团进度估算）) or the rest of
# the clause (估算, ，系估算). A note that says more than that (（批复数，已取代估算）, （非估算）) is no label.
_LABEL_AFTER = re.compile(
    r"[^\S\n]*(?:[（(](?P<note>[^（）()\n]{0,20})[）)]"
    r"|[，,]?[^\S\n]*(?P<said>(?:系|为|属|是|均为|均系|即|按[^\d。；;，,、！？!?\n|（）()]{0,10}?)?估算[值数]?)"
    r"(?=[^\S\n]*(?:[。；;，,、！？!?）)|\n]|$)))"
)
_LABEL_NOTE = re.compile(r"(?:系|为|属|即|按[^，,、；;。！？!?（）()\n\d]{0,10}?)?估算(?:值|数|口径)?")
# 估算 said before the number in its clause, alone or before the noun it names: 估算 117,814.57, （估算值）117,814.57,
# 估算为 117,814.57, 估算预算 117,814.57, 同期估算预算为 117,814.57. 取代估算 or 非估算 there is no label.
_LABEL_BEFORE = re.compile(
    r"(?:[（(]估算[值数]?[）)]|(?<![非不未无没否代换])估算[一-鿿]{0,12}?)(?:[^\S\n]|[：:])*$"
)
_CLAUSE_BREAK = re.compile(r"[。；;，,、！？!?\n|]")
# Words that deny or replace the estimate: 估算 beside one of them does not label the number (非估算, 已取代估算, 批复数).
_CONTRADICTION = re.compile(r"[非不未无没否]|取代|替代|代替|替换|批复|审定|核定|作废")
_FOOTNOTE = re.compile(r"\[\^\d+\]")
_SPACES = "    　"
# Stands in for an inline image when inline nodes are read as text.
_OBJECT = chr(0xFFFC)
# What estimate_label_issues reports for each kind of number the export cannot label: the issue field listing the
# numbers, what the text says, and how to fix it.
_UNPLACED = {
    "rounded": ("uncited_numbers",
                "文稿中的 {numbers} 按所写位数与它相同，但没有绑定到这个估算单元格，导出无法确认它就是估算，未标注“（估算）”",
                "若它就是这个估算，请用 claim 绑定到该单元格（舍入展示时写 presentation），或在数值旁写明“估算”；若不是，请改写这个数"),
    "ambiguous": ("same_as_counted_numbers",
                  "正文里的 {numbers} 同时是一个已计入的数，导出分不清哪一处是估算，未标注“（估算）”",
                  "请在估算值旁写明“估算”，或用 presentation 以不同小数位展示估算值"),
    "code": ("in_code_numbers", "代码块里的 {numbers} 按原样导出，不能标注“（估算）”",
             "请把它写到正文或表格里，或在代码块里该数值旁写明“估算”"),
    "caption": ("in_caption_numbers", "表题里的 {numbers} 加上“（估算）”会超过表题 300 字的上限，未标注",
                "请缩短表题，或在数值旁写明“估算”"),
}


def build_report_projection(draft: dict[str, Any], mode: str = "management", resolved_datasets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if mode not in REPORT_PROJECTION_MODES:
        raise FoundryError("report projection mode must be management or audit")
    title = _text(draft.get("title") or "分析报告")
    base = _draft_document(draft)
    document = _dedupe_leading_title(base, title)
    # Estimates are the cells the server's requirement check stored for this draft found `estimated`.
    quality = draft.get("quality") if isinstance(draft.get("quality"), dict) else {}
    binding = _estimate_binding(draft.get("claims"), estimate_cells(quality.get("requirements")), quality.get("facts"))
    title = _label_text(title, binding)[0]
    limitations: list[str] = []
    limitation_labels = 0
    for item in draft.get("limitations", []):
        text, added, _found = _label_text(str(item).strip(), binding)
        if text:
            limitations.append(text)
            limitation_labels += added
    marker = _review_marker(draft)

    appendix = str(draft.get("evidence_appendix") or "")
    trusted_appendix = appendix if _trusted_appendix(draft, appendix) else ""
    document = _strip_generated_appendix_suffix(document, trusted_appendix)
    if mode == "audit" and trusted_appendix:
        document = _append_markdown(document, "系统生成计算依据附录", trusted_appendix)
    elif mode == "audit" and appendix:
        document = _append_markdown(document, "未认证计算依据附录", appendix)
    if mode == "audit":
        audit_appendix = _audit_history_appendix(draft)
        if audit_appendix:
            document = _append_markdown(document, "审计质量与证据记录", audit_appendix)
    sources = _compact_sources(document, resolved_datasets)
    document, labels, _found = _label_estimates(document, binding)
    # Main exports this text without the labels and without the 估算标注待核对 section. Exactly the text the server
    # adds for estimates gets room beyond the text limit, so an export that fits there fits here; the author's
    # text gets none.
    headroom = len(ESTIMATE_LABEL) * (labels + limitation_labels)
    unplaced = [
        issue.get("message") for issue in quality.get("issues", []) or []
        if isinstance(issue, dict) and issue.get("code") == "estimate_label_unplaced" and issue.get("message")
    ]
    if unplaced:
        section = "\n".join(f"- {item}" for item in unplaced)
        headroom += _text_length(report_nodes_from_markdown(f"## 估算标注待核对\n\n{section}"))
        document = _append_markdown(document, "估算标注待核对", section, text_headroom=headroom)
    if limitations:
        document = _append_markdown(document, "局限与待确认事项", "\n".join(f"- {item}" for item in limitations),
                                    text_headroom=headroom)
    document = _append_markdown(document, "导出身份与来源", _identity_appendix(draft, mode, sources), text_headroom=headroom)

    body = report_document_markdown(document, title=title, text_headroom=headroom).strip()
    if marker:
        body = f"{marker}\n\n{body}" if body else marker
    body += "\n"
    projection_base = {
        "schema_version": 1,
        "draft_id": draft["id"],
        "task_id": draft.get("task_id"),
        "title": title,
        "content_hash": draft["content_hash"],
        "content_mode": mode,
        "publication_status": draft.get("publication_status", "draft"),
        "review_status": draft.get("review_status", "unreviewed"),
        "reproducibility_status": draft.get("reproducibility_status", "unverified"),
        "marker": marker,
        "body": body,
        "document": document,
        "limitations": limitations,
        "sources": sources,
        # Characters of document text the server added for estimates beyond the author's text (see text_headroom).
        **({"estimate_text_headroom": headroom} if headroom else {}),
    }
    projection_hash = _hash(projection_base)
    return {
        **projection_base,
        "projection_hash": projection_hash,
    }


def estimate_cells(requirements: Any) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    """Cited cells of grains a requirement check found `estimated`, keyed by (run_id, row, column).

    Only the check's own estimated_grains count: a cell restating an answered number belongs to an
    answered grain, and an estimate cited for an undeclared grain is pending, so neither is an estimate.
    """
    cells: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    items = requirements.get("items") if isinstance(requirements, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        for grain in item.get("estimated_grains") or []:
            if not isinstance(grain, dict):
                continue
            for location in grain.get("locations") or []:
                key = _cell_key(location)
                if key is None:
                    continue
                cells.setdefault(key, {
                    "requirement_item_id": item.get("id"),
                    "label": item.get("label") or item.get("metric") or item.get("id"),
                    "business_key": {"metric": item.get("metric"),
                                     **{name: grain[name] for name in ("organization", "period", "scenario") if name in grain}},
                    "run_id": key[0], "row": key[1], "column": key[2],
                })
    return cells


def estimate_label_issues(spec: dict[str, Any], requirements: Any, facts: Any = None) -> list[dict[str, Any]]:
    """Fail loud where the export cannot label an estimate the text writes.

    The export labels a number only where it is bound to an estimate (see _estimate_binding). This check reads
    the text the export labels (the document or body without the trusted appendix, the limitations, the title)
    the same way and reports, per estimate cell:
    - a number bound to no cell that equals the estimate rounded to the digits it shows (117,815, 11.78 亿元):
      it may be the estimate, and nothing binds it to label it;
    - the estimate written in a code block, or in a table caption with no room left for the label;
    - the estimate written only in a form a counted cell also states, when it is labelled nowhere else.
    An estimate the text never writes has nothing to label, and numbers that cannot be it (see _classify)
    raise nothing.
    """
    binding = _estimate_binding(spec.get("claims"), estimate_cells(requirements), facts)
    if not binding["estimates"]:
        return []
    document = _check_document(spec)
    if document is not None:
        found = _label_estimates(document, binding, apply=False)[2]
    else:
        found = _scan(_without_trusted_appendix(str(spec.get("body") or ""), spec), binding)[1]
    limitations = spec.get("limitations")
    for text in [*(str(item).strip() for item in (limitations if isinstance(limitations, list) else [])),
                 str(spec.get("title") or "")]:
        found.extend(_scan(text, binding)[1])
    located = {cell for kind, cells, _number in found if kind in {"bound", "located"} for cell in cells}
    reported: dict[tuple[Any, Any, Any], dict[str, list[str]]] = {}
    for kind, cells, number in found:
        if kind in {"bound", "located"}:
            continue
        for cell in cells:
            # A number a counted cell also states is most likely that cell where the estimate is labelled elsewhere.
            if kind == "ambiguous" and cell in located:
                continue
            reported.setdefault(cell, {}).setdefault(kind, []).append(number)
    result = []
    for key, cell in binding["estimates"].items():
        if key not in reported:
            continue
        grain = "、".join(str(value) for name, value in cell["business_key"].items() if name != "metric")
        detail, parts, fixes = {}, [], []
        for kind, (field, said, fix) in _UNPLACED.items():
            numbers = list(dict.fromkeys(reported[key].get(kind, [])))[:10]
            if numbers:
                detail[field] = numbers
                parts.append(said.format(numbers="、".join(numbers)))
                fixes.append(fix)
        result.append({
            "code": "estimate_label_unplaced",
            "severity": "warning",
            "requirement_item_id": cell["requirement_item_id"],
            "business_key": cell["business_key"],
            "run_id": cell["run_id"], "row": cell["row"], "column": cell["column"],
            **detail,
            "message": (f"“{cell['label']}”" + (f"的 {grain}" if grain else "") + " 为估算；"
                        + "；".join(parts) + "。" + "；".join(fixes) + "。"),
        })
    return result


def _cell_key(record: Any) -> tuple[str, int, str] | None:
    """(run_id, row, column) of a claim, fact or location; None when it names no cell (the number check
    reports a malformed claim location, invalid_claim_location)."""
    if not isinstance(record, dict):
        return None
    run_id, row, column = record.get("run_id"), record.get("row"), record.get("column")
    if isinstance(run_id, str) and isinstance(column, str) and isinstance(row, int) and not isinstance(row, bool):
        return run_id, row, column
    return None


def _estimate_binding(claims: Any, estimates: dict[tuple[Any, Any, Any], dict[str, Any]], facts: Any = None) -> dict[str, Any]:
    """How the text writes each estimate, and which numbers the draft's other cells state.

    `forms` holds exactly how an estimate cell is rendered: its value as its claim and its fact write it, the
    claim's presentation (117814.56 for 117814.5625 at two places) and the fact's display, which a {{fact:…}}
    template writes; commas aside. A number in the text is that estimate only when it is written in one of
    these forms, never because its value is close. A zero estimate has no form: 0 is written for too many
    things (0 项, 0%, a counted 0) to be bound to an estimate by how it reads.

    `counted` holds every value a cell that is no estimate states (the runs' other numeric cells, their claims
    and presentations, and other claims): a number written in an estimate's form that is also one of these could
    be either. `values` keeps each estimate's value and money unit to recognise a rounded copy of it.
    """
    from foundry.finance_explanations import NUMBER, _allowed_numbers, _normalize_number

    binding: dict[str, Any] = {"estimates": {}, "forms": {}, "counted": set(), "values": {}, "rounded": {}}
    if not estimates:
        return binding
    by_cell: dict[tuple[str, int, str], dict[str, Any]] = {}
    for fact in facts if isinstance(facts, list) else []:
        key = _cell_key(fact)
        if key is not None:
            by_cell.setdefault(key, fact)
    claims = [claim for claim in claims if isinstance(claim, dict)] if isinstance(claims, list) else []
    for key, cell in estimates.items():
        fact = by_cell.get(key) or {}
        written = [fact.get("value"), *(claim.get("value") for claim in claims
                                        if claim.get("basis") == "calculation" and _cell_key(claim) == key)]
        value = next((number for number in map(_decimal, written) if number is not None), None)
        if value is None or value == 0:
            continue
        binding["estimates"][key] = cell
        binding["values"][key] = (value, _money_scale(str(fact.get("unit") or "")))

    def add_form(key: tuple[str, int, str], text: Any) -> None:
        form = _plain_form(_written(text))
        if form is not None:
            binding["forms"].setdefault(form, set()).add(key)

    for key in binding["estimates"]:
        fact = by_cell.get(key)
        if fact:
            add_form(key, fact.get("value"))
            for match in NUMBER.finditer(str(fact.get("display_value") or "")):
                add_form(key, match.group(0))
    for claim in claims:
        key = _cell_key(claim)
        if claim.get("basis") == "calculation" and key in binding["estimates"]:
            add_form(key, claim.get("value"))
            add_form(key, _presented(claim, by_cell.get(key)))
        elif claim.get("basis") != "calculation" or (key is not None and key not in estimates):
            # Numbers another claim states (a counted cell, a source) are that claim's, not an estimate's.
            for value in (claim.get("value"), _presented(claim, by_cell.get(key)) if key else None):
                if value not in (None, ""):
                    binding["counted"].add(_normalize_number(str(value)))
    for key, fact in by_cell.items():
        if key not in estimates:
            try:
                binding["counted"].update(_allowed_numbers([fact]))
            except (KeyError, TypeError, AttributeError, InvalidOperation):
                continue
    return binding


def _presented(claim: dict[str, Any], fact: dict[str, Any] | None) -> str | None:
    """The claim's presentation of its value as the text writes it (117814.56, 62.50%), or None."""
    from foundry.finance_explanations import _fact_percent_value, _presentation_number

    presentation = claim.get("presentation")
    if not isinstance(presentation, dict):
        return None
    target = fact if fact is not None else {name: claim.get(name) for name in ("run_id", "row", "column", "value")}
    result, _issue = _presentation_number(claim, target)
    if not result:
        return None
    value = Decimal(str(target["value"]))
    percent = presentation["scale"] == "percent"
    if percent:
        value = _fact_percent_value(target, value)
    places = presentation["decimal_places"]
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + places + 4)
        rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return format(rounded, f".{places}f") + ("%" if percent else "")


def _written(value: Any) -> str | None:
    """A number as written, grouping commas and a leading '+' aside."""
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    return text.removeprefix("+") or None


def _plain_form(written: str | None) -> str | None:
    """A written number with padding zeros aside (117814.5625000 is 117814.5625, 62.50% is 62.5%), so the same
    rendering matches however many zeros pad it; it keeps every digit that matters and the percent sign."""
    if not written:
        return None
    percent = written.endswith("%")
    number = _decimal(written.removesuffix("%"))
    if number is None:
        return None
    return format(number.normalize(), "f") + ("%" if percent else "")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _money_scale(unit: str) -> int | None:
    match = _MONEY_UNIT.fullmatch(unit)
    return _MONEY_SCALES[match.group("scale") or match.group("bare") or ""] if match else None


def _number_tokens(text: str) -> list[tuple[int, int, str]]:
    """Numbers a reader sees in the text: (start, end, number as written).

    Unlike the number check, a number right after 年/月/日 or beside '-' or '/' still counts (1-8月117,814.56万元,
    117,814.56-109,742.028, 实际/预算 a/b). Dates, periods (1-8 月), footnote marks and sheet references do not.
    """
    from foundry.finance_explanations import DATE_SPAN, NUMBER, PERIOD_RANGE, _is_spreadsheet_reference_number

    spans: list[list[int]] = []
    for start, end in sorted(match.span() for pattern in (DATE_SPAN, PERIOD_RANGE, _FOOTNOTE)
                             for match in pattern.finditer(text)):
        if spans and start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    starts = [span[0] for span in spans]
    tokens = []
    for match in NUMBER.finditer(text):
        start, end = match.span()
        index = bisect.bisect_left(starts, end) - 1
        if index >= 0 and spans[index][1] > start:
            continue
        token = match.group(0)
        if token.lstrip("+-").isdigit():
            after = text[end:end + 4].lstrip(_SPACES)[:1]
            before = text[max(0, start - 4):start].rstrip(_SPACES)[-1:]
            # A year, month or day (2026 年 8 月), not an amount.
            if (after and after in "年月日") or (before and before in "年月" and len(token) <= 2):
                continue
        if _is_spreadsheet_reference_number(text, match):
            continue
        tokens.append((start, end, token))
    return tokens


def _classify(text: str, start: int, end: int, token: str, binding: dict[str, Any]) -> tuple[str, set] | None:
    """What a number in the text is to the estimates.

    ('bound', cells) where it is written in an estimate's own form; ('ambiguous', cells) where a counted cell
    states it too; ('rounded', cells) where no cell states it but it equals an estimate rounded to the digits it
    shows, in the money unit written after it. None for every other number: zeros, counts, percentages that are
    no estimate's presentation, and numbers another cell states.
    """
    from foundry.finance_explanations import _normalize_number

    written = _written(token) or ""
    value = _decimal(written.removesuffix("%"))
    if value is None or value == 0 or _COUNT_AFTER.match(text, end):
        return None
    counted = _normalize_number(token) in binding["counted"]
    cells = binding["forms"].get(_plain_form(written) or "")
    if cells:
        return ("ambiguous" if counted else "bound"), cells
    if counted or written.endswith("%") or len(written.lstrip("-").replace(".", "").lstrip("0")) < _ROUNDED_DIGITS:
        return None
    unit = _UNIT_AFTER.match(text, end)
    places = len(written.partition(".")[2])
    cells = _rounded_cells(binding, value, places, _money_scale(unit.group(0)) if unit else None)
    return ("rounded", cells) if cells else None


def _rounded_cells(binding: dict[str, Any], value: Decimal, places: int, scale: int | None) -> set | None:
    """Estimate cells that, rounded half up to `places` in the money scale of the number, are `value`."""
    table = binding["rounded"].get((places, scale))
    if table is None:
        table = {}
        quantum = Decimal(1).scaleb(-places)
        with localcontext() as context:
            context.prec = 60
            for cell, (estimate, unit_scale) in binding["values"].items():
                shown = estimate * unit_scale / scale if scale and unit_scale and scale != unit_scale else estimate
                try:
                    table.setdefault(shown.quantize(quantum, rounding=ROUND_HALF_UP), set()).add(cell)
                except InvalidOperation:
                    continue
        binding["rounded"][(places, scale)] = table
    return table.get(value)


def _scan(text: str, binding: dict[str, Any]) -> tuple[list[int], list[tuple[str, set, str]]]:
    """Where labels go in this text, and what the label check reads there: (kind, cells, number) for each number
    that is or may be an estimate (see _classify). A number the text already marks 估算 gets no label and is
    'located' when bound, else nothing."""
    points: list[int] = []
    found: list[tuple[str, set, str]] = []
    if not binding["estimates"]:
        return points, found
    for start, end, token in _number_tokens(text):
        classified = _classify(text, start, end, token, binding)
        if classified is None:
            continue
        kind, cells = classified
        if _labelled_beside(text, start, end):
            if kind == "bound":
                found.append(("located", cells, token))
            continue
        if kind == "bound":
            unit = _UNIT_AFTER.match(text, end)
            points.append(unit.end() if unit else end)
        found.append((kind, cells, token))
    return sorted(set(points)), found


def _label_estimates(
    document: dict[str, Any], binding: dict[str, Any], *, apply: bool = True
) -> tuple[dict[str, Any], int, list[tuple[str, set, str]]]:
    """Write （估算） beside every estimate number in prose, tables and table captions; code blocks are data and
    stay as written.

    Returns the document, how many labels its text gained, and what the label check reads (see _scan): an
    estimate bound in a code block, or in a caption with no room left for the label, is found as 'code' or
    'caption'. With apply=False the document is only read."""
    if not binding["estimates"]:
        return document, 0, []
    labelled = copy.deepcopy(validate_report_document(document)) if apply else document
    count = 0
    found: list[tuple[str, set, str]] = []

    def unplaced(kind: str, items: list[tuple[str, set, str]]) -> list[tuple[str, set, str]]:
        return [(kind if what == "bound" else what, cells, number) for what, cells, number in items]

    def walk(nodes: list[dict[str, Any]]) -> None:
        nonlocal count
        for node in nodes:
            if node.get("type") == "codeBlock":
                code = "".join(str(child.get("text", "")) for child in node.get("content") or [] if child.get("type") == "text")
                found.extend(unplaced("code", _scan(code, binding)[1]))
                continue
            attrs = node.get("attrs")
            if node.get("type") == "table" and isinstance(attrs, dict) and isinstance(attrs.get("caption"), str):
                caption, added, caption_found = _label_text(attrs["caption"], binding)
                if len(caption) <= MAX_TABLE_ATTR_TEXT:
                    if apply and added:
                        attrs["caption"] = caption
                    found.extend(caption_found)
                else:
                    found.extend(unplaced("caption", caption_found))
            children = node.get("content") or []
            if any(child.get("type") == "text" for child in children):
                added, inline_found = _label_inline(children, binding, apply=apply)
                count += added
                found.extend(inline_found)
            walk([child for child in children if child.get("type") not in INLINE_TYPES])

    walk(labelled.get("content", []))
    if apply:
        # Captions are attributes, outside the text limit; only the labels in text need its room.
        labelled = validate_report_document(labelled, text_headroom=len(ESTIMATE_LABEL) * count)
    return labelled, count, found


def _label_text(text: str, binding: dict[str, Any]) -> tuple[str, int, list[tuple[str, set, str]]]:
    node = {"type": "text", "text": text}
    added, found = _label_inline([node], binding)
    return node["text"], added, found


def _label_inline(
    children: list[dict[str, Any]], binding: dict[str, Any], *, apply: bool = True
) -> tuple[int, list[tuple[str, set, str]]]:
    """Label estimate numbers in one run of inline nodes, read as the text a reader sees. Returns the labels
    written and what the label check reads there (see _scan)."""
    if not binding["estimates"]:
        return 0, []
    offsets: list[int] = []
    pieces: list[str] = []
    total = 0
    for child in children:
        piece = str(child.get("text", "")) if child.get("type") == "text" else "\n" if child.get("type") == "hardBreak" else _OBJECT
        offsets.append(total)
        pieces.append(piece)
        total += len(piece)
    points, found = _scan("".join(pieces), binding)
    if apply:
        for point in reversed(points):
            # The character before the label ends the number or its unit, so it sits in a text node.
            index = bisect.bisect_right(offsets, point - 1) - 1
            cut = point - offsets[index]
            children[index]["text"] = children[index]["text"][:cut] + ESTIMATE_LABEL + children[index]["text"][cut:]
    return len(points), found


def _labelled_beside(text: str, start: int, end: int) -> bool:
    """Whether the text already labels this number 估算 in its own clause, with nothing there denying it."""
    unit = _UNIT_AFTER.match(text, end)
    after = _LABEL_AFTER.match(text, unit.end() if unit else end)
    if after:
        note, said = after.group("note"), after.group("said")
        if note is not None and _LABEL_NOTE.fullmatch(note.strip()) and not _CONTRADICTION.search(note):
            return True
        if said and not _CONTRADICTION.search(said):
            return True
    clause = _CLAUSE_BREAK.split(text[max(0, start - 32):start])[-1]
    return bool(_LABEL_BEFORE.search(clause)) and not _CONTRADICTION.search(clause)


def _check_document(spec: dict[str, Any]) -> dict[str, Any] | None:
    """The document the export labels, read for the label check: the draft's document where the body is its
    markdown, else the body read as markdown; the trusted evidence appendix is the server's and is left out.
    None when the body cannot be read as a document; it is then checked as plain text."""
    body = str(spec.get("body") or "")
    appendix = str(spec.get("evidence_appendix") or "")
    try:
        document = spec.get("document")
        if document is not None:
            document = validate_report_document(copy.deepcopy(document))
            if report_document_markdown(document).strip() != body.strip():
                document = None
        if document is None:
            document = report_document_from_markdown_body(body)
        return _strip_generated_appendix_suffix(document, appendix if _trusted_appendix(spec, appendix) else "")
    except FoundryError:
        return None


def _text_length(nodes: list[dict[str, Any]]) -> int:
    return sum(len(str(node.get("text", ""))) if node.get("type") == "text" else _text_length(node.get("content") or [])
               for node in nodes if isinstance(node, dict))


def _without_trusted_appendix(body: str, draft: dict[str, Any]) -> str:
    appendix = str(draft.get("evidence_appendix") or "")
    if not _trusted_appendix(draft, appendix):
        return body
    trimmed = body.rstrip()
    for variant in _appendix_variants(appendix):
        if trimmed.endswith(variant):
            return trimmed[: -len(variant)]
    return body


def _draft_document(draft: dict[str, Any]) -> dict[str, Any]:
    if draft.get("document") is not None:
        return validate_report_document(copy.deepcopy(draft["document"]))
    return report_document_from_markdown_body(str(draft.get("body") or ""))


def _dedupe_leading_title(document: dict[str, Any], title: str) -> dict[str, Any]:
    clean = copy.deepcopy(validate_report_document(document))
    content = clean.get("content", [])
    if content and content[0].get("type") == "heading" and _normalize_title(_node_text(content[0])) == _normalize_title(title):
        clean["content"] = content[1:]
    return validate_report_document(clean)


def _strip_generated_appendix_suffix(document: dict[str, Any], appendix: str) -> dict[str, Any]:
    if not appendix.strip():
        return document
    clean = copy.deepcopy(validate_report_document(document))
    content = clean.get("content", [])
    for variant in _appendix_variants(appendix):
        suffix = report_nodes_from_markdown(variant)
        if suffix and _node_suffix_matches(content, suffix):
            next_content = content[: -len(suffix)]
            if next_content and next_content[-1].get("type") == "horizontalRule":
                next_content = next_content[:-1]
            clean["content"] = next_content
            return validate_report_document(clean)
    return document


def _appendix_variants(markdown: str) -> list[str]:
    raw = markdown.strip()
    if not raw:
        return []
    try:
        canonical = report_document_markdown(report_document_from_markdown_body(raw)).strip()
    except Exception:
        canonical = raw
    return list(dict.fromkeys([raw, canonical]))


def _node_suffix_matches(content: list[dict[str, Any]], suffix: list[dict[str, Any]]) -> bool:
    if len(content) < len(suffix):
        return False
    return _stable_json(content[-len(suffix):]) == _stable_json(suffix)


def _append_markdown(document: dict[str, Any], heading: str, markdown: str, *, text_headroom: int = 0) -> dict[str, Any]:
    if not markdown.strip():
        return document
    addition = markdown.strip()
    if not addition.startswith("#"):
        addition = f"## {heading}\n\n{addition}"
    extended = copy.deepcopy(validate_report_document(document, text_headroom=text_headroom))
    if extended.get("content"):
        extended["content"].append({"type": "horizontalRule"})
    extended["content"].extend(report_nodes_from_markdown(addition))
    return validate_report_document(extended, text_headroom=text_headroom)




def _identity_appendix(draft: dict[str, Any], mode: str, sources: list[str]) -> str:
    lines = [
        "- 草稿版本：" + str(draft.get("id", "")),
        "- 导出模式：" + mode,
        "- 内容 SHA-256：" + str(draft.get("content_hash", "")),
        "- 发布状态：" + str(draft.get("publication_status", "draft")),
        "- 复核状态：" + str(draft.get("review_status", "unreviewed")),
        "- 可复现状态：" + str(draft.get("reproducibility_status", "unverified")),
    ]
    if sources:
        lines.append("- 授权来源：")
        lines.extend("  - " + source for source in sources)
    else:
        lines.append("- 授权来源：未附加外部文稿来源。")
    return "\n".join(lines)


def _compact_sources(document: dict[str, Any], resolved_datasets: list[dict[str, Any]] | None = None) -> list[str]:
    sources: list[str] = []
    seen: set[tuple[str, str]] = set()
    for source in document.get("sources", []) or []:
        if not isinstance(source, dict):
            continue
        rendered = _format_source(
            name=source.get("name") or source.get("id") or "未命名来源",
            kind=source.get("format") or "report",
            source_id=source.get("id"),
            sha=source.get("sha256"),
        )
        key = (_safe_inline(source.get("id") or "", 64), _safe_inline(source.get("sha256") or "", 64))
        if rendered and key not in seen:
            seen.add(key)
            sources.append(rendered)
    for dataset in resolved_datasets or []:
        if not isinstance(dataset, dict):
            continue
        rendered = _format_source(
            name=dataset.get("name") or dataset.get("source_name") or dataset.get("id") or "未命名数据源",
            kind=dataset.get("kind") or "dataset",
            source_id=dataset.get("id"),
            sha=dataset.get("source_hash"),
        )
        key = (_safe_inline(dataset.get("id") or "", 64), _safe_inline(dataset.get("source_hash") or "", 64))
        if rendered and key not in seen:
            seen.add(key)
            sources.append(rendered)
    return sources[:12]


def _format_source(*, name: Any, kind: Any, source_id: Any, sha: Any) -> str:
    clean_name = _safe_inline(name, 120)
    clean_kind = _safe_inline(kind or "unknown", 24)
    clean_id = _safe_inline(source_id or "", 48)
    clean_sha = _safe_inline(sha or "", 64)
    if not clean_name and not clean_id and not clean_sha:
        return ""
    suffix = []
    if clean_id:
        suffix.append("ID " + clean_id)
    if clean_sha:
        suffix.append("SHA-256 " + clean_sha[:12])
    return f"{clean_name or '未命名来源'}（{clean_kind}" + ("；" + "；".join(suffix) if suffix else "") + "）"


def _audit_history_appendix(draft: dict[str, Any]) -> str:
    payload = {
        key: draft.get(key)
        for key in (
            "requirements_id",
            "materiality",
            "run_ids",
            "fact_ids",
            "claims",
            "source_read_failures",
            "evidence_recipes",
            "evidence_report",
            "revision_comparison",
            "explanation_check",
            "quality",
            "evidence_appendix_meta",
            "consistency_rules",
            "consistency_report",
            "consistency_sources",
            "consistency_source_report",
            "sources_report",
            "source_report",
        )
        if draft.get(key) not in (None, "", [], {})
    }
    if not payload:
        return ""
    # Audit diagnostics can be large. Whitespace is not evidence: compact JSON
    # keeps every field while avoiding indentation consuming the document budget.
    return "```json\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str) + "\n```"


def _safe_inline(value: Any, maximum: int) -> str:
    return re.sub(r"[\r\n]+", " ", str(value).strip())[:maximum]


def _trusted_appendix(draft: dict[str, Any], appendix: str) -> bool:
    if not appendix.strip():
        return False
    meta = draft.get("evidence_appendix_meta")
    if not isinstance(meta, dict):
        return False
    expected = hashlib.sha256(appendix.encode("utf-8")).hexdigest()
    return meta.get("body_sha256") == expected


def _review_marker(draft: dict[str, Any]) -> str:
    if draft.get("review_status", "unreviewed") == "accepted" and draft.get("publication_status") == "archived":
        return ""
    return "分析草稿·待复核"


def _node_text(node: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(item: dict[str, Any]) -> None:
        if item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        for child in item.get("content", []) or []:
            if isinstance(child, dict):
                walk(child)

    walk(node)
    return "".join(parts)


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value).strip().casefold()


def _text(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise FoundryError("report projection title is required")
    return text[:1000]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()
