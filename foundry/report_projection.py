"""Canonical report export projections.

The projection is the server-owned boundary between an editable draft and
format-specific renderers.  It carries the draft identity, review state and a
stable projection hash so every exported format can be traced to the same
business document.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from foundry.errors import FoundryError
from foundry.report_documents import (
    report_document_from_markdown_body,
    report_document_markdown,
    report_nodes_from_markdown,
    validate_report_document,
)
from foundry.report_estimates import declare_estimates, estimated_cells, template_label_positions, text_node_count

REPORT_PROJECTION_MODES = {"management", "audit"}


def build_report_projection(
    draft: dict[str, Any],
    mode: str = "management",
    resolved_datasets: list[dict[str, Any]] | None = None,
    runs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`runs` (by id) are the draft's runs as the store read them; the estimate declaration reads an estimated
    cell's own row there for a grain field its requirement item does not list."""
    if mode not in REPORT_PROJECTION_MODES:
        raise FoundryError("report projection mode must be management or audit")
    title = _text(draft.get("title") or "分析报告")
    base = _draft_document(draft)
    # Estimates are what the server's requirement check stored on this draft found estimated or its items declare
    # estimates (issues #24, #33).
    estimates = estimated_cells(draft, runs)
    labels = template_label_positions(draft, base, estimates) if estimates else []
    document = _dedupe_leading_title(base, title)
    # Text nodes of the dropped title heading come before the body's; label positions count from the body.
    dropped = text_node_count(base["content"][: len(base["content"]) - len(document["content"])])
    limitations = [str(item).strip() for item in draft.get("limitations", []) if str(item).strip()]
    marker = _review_marker(draft)

    appendix = str(draft.get("evidence_appendix") or "")
    trusted_appendix = appendix if _trusted_appendix(draft, appendix) else ""
    document = _strip_generated_appendix_suffix(document, trusted_appendix)
    body_texts = text_node_count(document["content"])
    labels = [(index - dropped, offset) for index, offset in labels if 0 <= index - dropped < body_texts]
    if mode == "audit" and trusted_appendix:
        document = _append_markdown(document, "系统生成计算依据附录", trusted_appendix)
    elif mode == "audit" and appendix:
        document = _append_markdown(document, "未认证计算依据附录", appendix)
    if mode == "audit":
        audit_appendix = _audit_history_appendix(draft)
        if audit_appendix:
            document = _append_markdown(document, "审计质量与证据记录", audit_appendix)
    sources = _compact_sources(document, resolved_datasets)
    if limitations:
        document = _append_markdown(document, "局限与待确认事项", "\n".join(f"- {item}" for item in limitations))
    document = _append_markdown(document, "导出身份与来源", _identity_appendix(draft, mode, sources))
    headroom: dict[str, int] = {}
    if estimates:
        # Added last, so every earlier step checks the limits on main's text; the declaration and the labels get
        # exactly the room they take (see validate_report_document).
        document, headroom = declare_estimates(document, draft, estimates, labels, runs)

    body = report_document_markdown(
        document, title=title, text_headroom=headroom.get("text", 0), node_headroom=headroom.get("nodes", 0)
    ).strip()
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
        # Room beyond the text and node limits for what the server added for estimates; absent without estimates.
        **({"estimate_headroom": headroom} if estimates else {}),
    }
    projection_hash = _hash(projection_base)
    return {
        **projection_base,
        "projection_hash": projection_hash,
    }


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


def _append_markdown(document: dict[str, Any], heading: str, markdown: str) -> dict[str, Any]:
    if not markdown.strip():
        return document
    addition = markdown.strip()
    if not addition.startswith("#"):
        addition = f"## {heading}\n\n{addition}"
    extended = copy.deepcopy(validate_report_document(document))
    if extended.get("content"):
        extended["content"].append({"type": "horizontalRule"})
    extended["content"].extend(report_nodes_from_markdown(addition))
    return validate_report_document(extended)




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
