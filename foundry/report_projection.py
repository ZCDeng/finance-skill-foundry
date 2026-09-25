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
from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.errors import FoundryError
from foundry.report_documents import (
    INLINE_TYPES,
    report_document_from_markdown_body,
    report_document_markdown,
    report_nodes_from_markdown,
    validate_report_document,
)

REPORT_PROJECTION_MODES = {"management", "audit"}
ESTIMATE_LABEL = "（估算）"
# The whole unit written right after a number stays with it (万, 万元, 万元人民币, 元/吨); the label goes after it.
_UNIT_AFTER = re.compile(
    r"[^\S\n]?(?:(?:百万|千万|亿|万|千)(?:美元|港元|欧元|元)?|美元|港元|欧元|元)(?:人民币)?"
    r"(?:/(?:平方米|平米|千克|公斤|公里|小时|人|吨|月|年|日|天|户|台|件|次|股|份|辆|套|间|个|座|张))?"
)
# 估算 said right after the number or its unit: in brackets (（估算）, （按集团进度估算）) or as the rest of the
# clause (估算, ，系估算). A negation there (非估算, 估算口径不适用) is no label.
_LABEL_AFTER = re.compile(
    r"[^\S\n]*(?:[（(](?P<note>[^（）()\n]{0,20})[）)]"
    r"|[，,]?[^\S\n]*(?P<said>(?:系|为|属|是|均为|均系|即|按[^\d。；;，,、！？!?\n|（）()]{0,10}?)?估算[值数]?)"
    r"(?=[^\S\n]*(?:[。；;，,、！？!?）)|\n]|$)))"
)
# 估算 said right before the number, in the same clause: 估算 117,814.57, （估算值）117,814.57, 估算为 117,814.57.
_LABEL_BEFORE = re.compile(r"(?:估算[值数]?|[（(]估算[值数]?[）)])[\s：:为是约]*$")
_CLAUSE_BREAK = re.compile(r"[。；;，,、！？!?\n|]")
_NEGATION = re.compile(r"[非不未无没否]")
# Stands in for an inline image when inline nodes are read as text.
_OBJECT = chr(0xFFFC)


def build_report_projection(draft: dict[str, Any], mode: str = "management", resolved_datasets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if mode not in REPORT_PROJECTION_MODES:
        raise FoundryError("report projection mode must be management or audit")
    title = _text(draft.get("title") or "分析报告")
    base = _draft_document(draft)
    document = _dedupe_leading_title(base, title)
    # Estimates are the cells the server's requirement check stored for this draft found `estimated`.
    quality = draft.get("quality") if isinstance(draft.get("quality"), dict) else {}
    cited = _cited_numbers(draft.get("claims"), estimate_cells(quality.get("requirements")), quality.get("facts"))
    title = _label_text(title, cited)
    limitations = [
        _label_text(str(item).strip(), cited)
        for item in draft.get("limitations", [])
        if str(item).strip()
    ]
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
    unplaced = [
        issue.get("message") for issue in quality.get("issues", []) or []
        if isinstance(issue, dict) and issue.get("code") == "estimate_label_unplaced" and issue.get("message")
    ]
    if unplaced:
        document = _append_markdown(document, "估算标注待核对", "\n".join(f"- {item}" for item in unplaced))
    if limitations:
        document = _append_markdown(document, "局限与待确认事项", "\n".join(f"- {item}" for item in limitations))
    document, labels = _label_estimates(document, cited)
    # The labels are the server's text, so they get room beyond the text limit; the author's text does not.
    headroom = len(ESTIMATE_LABEL) * labels
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
        # How many （估算） labels the document text carries beyond the author's text (see text_headroom).
        **({"estimate_labels": labels} if labels else {}),
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


def estimate_label_issues(
    spec: dict[str, Any], requirements: Any, issues: list[Any], facts: Any = None
) -> list[dict[str, Any]]:
    """Fail loud where an estimate cannot be labelled in the export.

    An estimate is labelled where the manager-facing text (body, limitations, title) writes its cited value
    (or the claim's presentation of it). It cannot be labelled when the text states it only as a number bound
    to no cell (uncited_number, or any such number the number check does not read: in limitations, the title,
    or beside '/'), or as a number a counted cell also states, where no one can tell which it is.
    """
    cells = estimate_cells(requirements)
    if not cells:
        return []
    body = str(spec.get("body") or "")
    cited = _cited_numbers(spec.get("claims"), cells, facts)
    located: set[tuple[Any, Any, Any]] = set()
    ambiguous: dict[tuple[Any, Any, Any], list[str]] = {}
    scanned: list[str] = []
    limitations = spec.get("limitations")
    texts = [_without_trusted_appendix(body, spec),
             *(str(item).strip() for item in (limitations if isinstance(limitations, list) else [])),
             str(spec.get("title") or "")]
    for text in texts:
        _label_inline([{"type": "text", "text": text}], cited, located, ambiguous, scanned)
    unbound = list(dict.fromkeys([
        *(str(issue.get("text", "")) for issue in issues
          if isinstance(issue, dict) and issue.get("code") == "uncited_number"
          and issue.get("origin", "manager_body") == "manager_body"
          and not _unbound_number_says_estimate(body, issue)),
        *scanned,
    ]))[:10]
    result = []
    for key, cell in cells.items():
        if key in located or not (unbound or key in ambiguous):
            continue
        grain = "、".join(str(value) for name, value in cell["business_key"].items() if name != "metric")
        subject = f"“{cell['label']}”" + (f"的 {grain}" if grain else "") + " 为估算，"
        if key in ambiguous:
            same = list(dict.fromkeys(ambiguous[key]))
            detail = {"same_as_counted_numbers": same}
            message = (subject + "正文里的 " + "、".join(same) + " 同时是一个已计入的数，导出分不清哪一处是估算，"
                       "未标注“（估算）”。请在估算值旁写明“估算”，或用 presentation 以不同小数位展示估算值。")
        else:
            detail = {"uncited_numbers": unbound}
            message = (subject + "正文、局限和标题里找不到它引用的数值，导出无法在数值旁标注“（估算）”。"
                       "文稿有未绑定引用的数字：" + "、".join(unbound)
                       + "；若其中有这个估算值，请用 claim 绑定到该单元格（舍入展示时写 presentation），"
                       "或在数值旁写明“估算”。")
        result.append({
            "code": "estimate_label_unplaced",
            "severity": "warning",
            "requirement_item_id": cell["requirement_item_id"],
            "business_key": cell["business_key"],
            "run_id": cell["run_id"], "row": cell["row"], "column": cell["column"],
            **detail,
            "message": message,
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


def _cited_numbers(claims: Any, estimates: dict[tuple[Any, Any, Any], dict[str, Any]], facts: Any = None) -> dict[str, Any]:
    """Which cells of the draft's runs each number in the text can be, and which of those are estimates.

    A number is matched by value, the rule the number check binds text with, against the cited claims and
    every numeric cell of the runs (the stored check's facts): a counted cell the text states without a
    claim of its own is still counted. Where an estimate and a counted cell have the same value, only a
    form the claim's presentation gives the estimate and no counted cell is written in (0.00 beside a
    counted 0) tells them apart.
    """
    from foundry.finance_explanations import _allowed_numbers, _normalize_number, _presentation_number

    cited: dict[str, Any] = {"estimates": estimates, "value": {}, "shown": {}}
    if not estimates:
        return cited

    def add(key: tuple[str, int, str], values: set[str], shown: set[str]) -> None:
        for form in values:
            cited["value"].setdefault(form, set()).add(key)
        for form in shown:
            cited["shown"].setdefault(form.replace(",", ""), set()).add(key)

    for claim in claims if isinstance(claims, list) else []:
        key = _cell_key(claim)
        if key is None or claim.get("basis") != "calculation" or claim.get("value") in (None, ""):
            continue
        values, shown = {_normalize_number(str(claim["value"]))}, set()
        presentation = claim.get("presentation")
        if isinstance(presentation, dict) and presentation.get("scale") == "identity":
            result, _issue = _presentation_number(claim, {name: claim.get(name) for name in ("run_id", "row", "column", "value")})
            if result:
                values.add(result["number"])
                shown.add(format(Decimal(result["number"]), f".{presentation['decimal_places']}f"))
        # A counted cell's value as written is a form the text may use for it.
        add(key, values, shown if key in estimates else shown | {str(claim["value"])})
    for fact in facts if isinstance(facts, list) else []:
        key = _cell_key(fact)
        if key is None:
            continue
        try:
            values = _allowed_numbers([fact])
        except (KeyError, TypeError, AttributeError, InvalidOperation):
            continue
        add(key, values, set() if key in estimates else {str(fact.get("value"))})
    return cited


def _label_estimates(document: dict[str, Any], cited: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Write （估算） beside every estimate number in prose and tables; code blocks are data, not prose.

    Returns the labelled document and how many labels it gained."""
    if not cited["estimates"]:
        return document, 0
    labelled = copy.deepcopy(validate_report_document(document))
    count = 0

    def walk(nodes: list[dict[str, Any]]) -> None:
        nonlocal count
        for node in nodes:
            if node.get("type") == "codeBlock":
                continue
            children = node.get("content") or []
            if any(child.get("type") == "text" for child in children):
                count += _label_inline(children, cited, set())
            walk([child for child in children if child.get("type") not in INLINE_TYPES])

    walk(labelled.get("content", []))
    return validate_report_document(labelled, text_headroom=len(ESTIMATE_LABEL) * count), count


def _label_text(text: str, cited: dict[str, Any]) -> str:
    node = {"type": "text", "text": text}
    _label_inline([node], cited, set())
    return node["text"]


def _numbers(text: str) -> list[dict[str, Any]]:
    """Numbers as the number check reads them, and also those it skips beside '/' (实际/预算 a/b)."""
    from foundry.finance_explanations import DATE_SPAN, _body_numbers

    # A '/' inside a date (2026/08/31) still keeps its numbers a date.
    return _body_numbers(text.replace("/", " "), ignored_spans=[match.span() for match in DATE_SPAN.finditer(text)])


def _label_inline(
    children: list[dict[str, Any]],
    cited: dict[str, Any],
    located: set[tuple[Any, Any, Any]],
    ambiguous: dict[tuple[Any, Any, Any], list[str]] | None = None,
    unbound: list[str] | None = None,
) -> int:
    """Label estimate numbers in one run of inline nodes, read as the text a reader sees; returns the labels
    written. `unbound` collects the numbers that are no cell of the runs and say nothing of 估算 beside them."""
    from foundry.finance_explanations import _normalize_number

    if not cited["estimates"]:
        return 0
    offsets: list[int] = []
    pieces: list[str] = []
    total = 0
    for child in children:
        piece = str(child.get("text", "")) if child.get("type") == "text" else "\n" if child.get("type") == "hardBreak" else _OBJECT
        offsets.append(total)
        pieces.append(piece)
        total += len(piece)
    text = "".join(pieces)
    points = set()
    for token in _numbers(text):
        cells = cited["value"].get(_normalize_number(token["text"])) or set()
        estimates = {cell for cell in cells if cell in cited["estimates"]}
        if estimates and len(estimates) < len(cells):
            # A counted cell has the same value: only a form that is the estimate's own tells which is meant.
            shown = cited["shown"].get(token["text"].replace(",", "")) or set()
            if shown and shown <= estimates:
                cells = estimates = shown
        if not estimates:
            if not cells and unbound is not None and not _labelled_beside(text, token["start"], token["end"]):
                unbound.append(token["text"])
            continue
        if _labelled_beside(text, token["start"], token["end"]):
            located.update(estimates)
        elif len(estimates) < len(cells):
            if ambiguous is not None:
                for cell in estimates:
                    ambiguous.setdefault(cell, []).append(token["text"])
        else:
            located.update(estimates)
            unit = _UNIT_AFTER.match(text, token["end"])
            points.add(unit.end() if unit else token["end"])
    for point in sorted(points, reverse=True):
        # The character before the label ends the number or its unit, so it sits in a text node.
        index = bisect.bisect_right(offsets, point - 1) - 1
        cut = point - offsets[index]
        children[index]["text"] = children[index]["text"][:cut] + ESTIMATE_LABEL + children[index]["text"][cut:]
    return len(points)


def _labelled_beside(text: str, start: int, end: int) -> bool:
    """Whether the text already says 估算 beside this number, in its own clause and not negated."""
    unit = _UNIT_AFTER.match(text, end)
    after = _LABEL_AFTER.match(text, unit.end() if unit else end)
    if after:
        said = after.group("said") or after.group("note") or ""
        if "估算" in said and not _NEGATION.search(said):
            return True
    clause = _CLAUSE_BREAK.split(text[max(0, start - 16):start])[-1]
    return bool(_LABEL_BEFORE.search(clause)) and not _NEGATION.search(clause)


def _unbound_number_says_estimate(body: str, issue: dict[str, Any]) -> bool:
    position = issue.get("position")
    token = str(issue.get("text", ""))
    return (isinstance(position, int) and body[position:position + len(token)] == token
            and _labelled_beside(body, position, position + len(token)))


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
