"""Structured report documents and task-owned report conversion helpers."""

from __future__ import annotations

import base64
import copy
import io
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries

from foundry.analysis_data import MAX_COLUMNS, MAX_ROWS, MAX_SOURCE_BYTES, json_value
from foundry.errors import FoundryError

REPORT_FORMATS = {"docx", "pdf", "html", "md", "xlsx"}
REPORT_SUFFIXES = {".docx": "docx", ".pdf": "pdf", ".html": "html", ".htm": "html", ".md": "md", ".xlsx": "xlsx"}
REPORT_TEMPLATE_VERSION = "annual-v1"
MAX_DOCUMENT_NODES = 20_000
MAX_DOCUMENT_TEXT = 1_000_000
MAX_IMAGE_DATA_URL = 2 * 1024 * 1024
SOURCE_ID = re.compile(r"^[0-9a-f]{32}$")

NODE_TYPES = {
    "doc",
    "paragraph",
    "heading",
    "text",
    "hardBreak",
    "bulletList",
    "orderedList",
    "listItem",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "table",
    "tableRow",
    "tableCell",
    "tableHeader",
    "image",
    "reportNote",
    "reportPageBreak",
}
MARK_TYPES = {"bold", "italic", "strike", "code", "link", "underline"}
INLINE_TYPES = {"text", "hardBreak", "image"}
TEXT_ALIGN = {"left", "center", "right", "justify"}


def _text(value: Any, label: str, *, required: bool = False, maximum: int = 1000) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise FoundryError(f"{label} must be {'nonempty ' if required else ''}text")
    return value


def _source_id(value: Any) -> str:
    if not isinstance(value, str) or not SOURCE_ID.fullmatch(value):
        raise FoundryError("report source_id must name a task-owned source")
    return value


def report_format_for_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix not in REPORT_SUFFIXES:
        raise FoundryError("report source format must be docx, pdf, html, md or xlsx")
    return REPORT_SUFFIXES[suffix]


def check_report_source_bytes(data: bytes, fmt: str) -> None:
    if fmt not in REPORT_FORMATS:
        raise FoundryError("report format must be docx, pdf, html, md or xlsx")
    if len(data) > MAX_SOURCE_BYTES:
        raise FoundryError("report source exceeds 32 MiB limit")
    if fmt in {"docx", "xlsx"}:
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_SOURCE_BYTES * 4:
                    raise FoundryError("report source expands beyond the source limit")
        except BadZipFile as exc:
            raise FoundryError(f"invalid {fmt.upper()} source archive") from exc


def validate_report_source(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise FoundryError("report source must be an object")
    source_id = _source_id(source.get("id"))
    fmt = source.get("format")
    if fmt not in REPORT_FORMATS:
        raise FoundryError("report source format must be docx, pdf, html, md or xlsx")
    sha256 = source.get("sha256")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise FoundryError("report source requires a sha256")
    return {
        "id": source_id,
        "name": _text(source.get("name", source_id), "report source name", required=True, maximum=300),
        "sha256": sha256,
        "format": fmt,
    }


def validate_report_document(document: Any, *, registered_source_ids: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise FoundryError("report document must be an object")
    if document.get("schema_version") != 1:
        raise FoundryError("report document schema_version must be 1")
    if document.get("template_version") != REPORT_TEMPLATE_VERSION:
        raise FoundryError("report document template_version must be annual-v1")
    metadata = document.get("metadata", {})
    if not isinstance(metadata, dict):
        raise FoundryError("report document metadata must be an object")
    clean_metadata = {
        key: _text(metadata.get(key, ""), f"report metadata {key}", maximum=300)
        for key in ("company", "period", "currency", "unit")
    }
    sources = [validate_report_source(item) for item in document.get("sources", [])]
    if registered_source_ids is not None:
        for source in sources:
            if source["id"] not in registered_source_ids:
                raise FoundryError("report document cites a source outside this task")
    source_ids = {source["id"] for source in sources}
    content = document.get("content")
    if not isinstance(content, list):
        raise FoundryError("report document content must be an array")
    budget = {"nodes": 0, "text": 0}
    clean_content: list[dict[str, Any]] = []
    for node in content:
        normalized = _validate_node(node, source_ids, registered_source_ids, budget, parent=None)
        if normalized["type"] == "doc":
            clean_content.extend(normalized.get("content", []))
        else:
            clean_content.append(normalized)
    if budget["text"] > MAX_DOCUMENT_TEXT:
        raise FoundryError("report document text exceeds 1 MiB limit")
    return {
        "schema_version": 1,
        "template_version": REPORT_TEMPLATE_VERSION,
        "metadata": clean_metadata,
        "content": clean_content,
        **({"sources": sources} if sources else {}),
    }


def _validate_node(
    node: Any,
    source_ids: set[str],
    registered_source_ids: set[str] | None,
    budget: dict[str, int],
    *,
    parent: str | None,
) -> dict[str, Any]:
    if not isinstance(node, dict) or node.get("type") not in NODE_TYPES:
        raise FoundryError("report node type is not supported")
    budget["nodes"] += 1
    if budget["nodes"] > MAX_DOCUMENT_NODES:
        raise FoundryError("report document has too many nodes")
    node_type = node["type"]
    attrs = _validate_attrs(node_type, node.get("attrs", {}), source_ids, registered_source_ids)
    clean: dict[str, Any] = {"type": node_type}
    if attrs:
        clean["attrs"] = attrs
    if node_type == "text":
        text = _text(node.get("text", ""), "report text", maximum=MAX_DOCUMENT_TEXT)
        budget["text"] += len(text)
        clean["text"] = text
        marks = []
        for mark in node.get("marks", []):
            marks.append(_validate_mark(mark))
        if marks:
            clean["marks"] = marks
        return clean
    if "text" in node:
        raise FoundryError("only text nodes may carry text")
    content = node.get("content", [])
    if content is None:
        content = []
    if not isinstance(content, list):
        raise FoundryError("report node content must be an array")
    children = [_validate_node(child, source_ids, registered_source_ids, budget, parent=node_type) for child in content]
    if node_type in {"paragraph", "heading"}:
        if any(child["type"] not in INLINE_TYPES for child in children):
            raise FoundryError(f"{node_type} can contain only inline report nodes")
    if node_type in {"tableCell", "tableHeader", "reportNote"}:
        if any(child["type"] not in INLINE_TYPES and child["type"] != "paragraph" for child in children):
            raise FoundryError(f"{node_type} can contain only inline report nodes or paragraphs")
    if node_type == "table" and any(child["type"] != "tableRow" for child in children):
        raise FoundryError("report table can contain only rows")
    if node_type == "tableRow" and any(child["type"] not in {"tableCell", "tableHeader"} for child in children):
        raise FoundryError("report table row can contain only cells")
    if node_type in {"bulletList", "orderedList"} and any(child["type"] != "listItem" for child in children):
        raise FoundryError("report lists can contain only list items")
    if node_type == "listItem" and any(child["type"] not in {"paragraph", "bulletList", "orderedList"} for child in children):
        raise FoundryError("report list items can contain only paragraphs or nested lists")
    if children:
        clean["content"] = children
    return clean


def _validate_attrs(
    node_type: str,
    attrs: Any,
    source_ids: set[str],
    registered_source_ids: set[str] | None,
) -> dict[str, Any]:
    if attrs in (None, {}):
        return {}
    if not isinstance(attrs, dict):
        raise FoundryError("report node attrs must be an object")
    clean: dict[str, Any] = {}
    if "source_id" in attrs and attrs["source_id"] not in (None, ""):
        source_id = _source_id(attrs["source_id"])
        if source_id not in source_ids or (registered_source_ids is not None and source_id not in registered_source_ids):
            raise FoundryError("report node source_id is not task-owned")
        clean["source_id"] = source_id
    for key in ("page", "sheet", "range"):
        if key in attrs and attrs[key] is not None:
            clean[key] = _text(attrs[key], f"report source {key}", maximum=120)
    if node_type == "heading":
        level = attrs.get("level", 1)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
            raise FoundryError("report heading level must be 1-6")
        clean["level"] = level
    if node_type in {"table", "tableCell", "tableHeader"}:
        for key in ("caption", "period", "currency", "unit"):
            if key in attrs and attrs[key] is not None:
                clean[key] = _text(attrs[key], f"report table {key}", maximum=300)
        for key in ("colspan", "rowspan"):
            if key in attrs and attrs[key] is not None:
                value = attrs[key]
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
                    raise FoundryError(f"report table {key} must be a positive integer")
                clean[key] = value
        if "colwidth" in attrs and attrs["colwidth"] is not None:
            colwidth = attrs["colwidth"]
            if not isinstance(colwidth, list) or len(colwidth) > MAX_COLUMNS:
                raise FoundryError("report table colwidth must be an array")
            clean["colwidth"] = [
                value for value in colwidth
                if not isinstance(value, bool) and isinstance(value, int) and 0 < value <= 2000
            ]
        if "textAlign" in attrs and attrs["textAlign"] is not None:
            align = attrs["textAlign"]
            if align not in TEXT_ALIGN:
                raise FoundryError("report table textAlign is invalid")
            clean["textAlign"] = align
    if node_type == "image":
        src = _text(attrs.get("src"), "report image src", required=True, maximum=MAX_IMAGE_DATA_URL)
        if not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\r\n]+", src):
            raise FoundryError("report image src must be a bounded PNG/JPEG data URL")
        try:
            base64.b64decode(src.split(",", 1)[1], validate=True)
        except ValueError as exc:
            raise FoundryError("report image src is not valid base64") from exc
        clean["src"] = src
        for key in ("alt", "title"):
            if key in attrs:
                clean[key] = _text(attrs[key], f"report image {key}", maximum=300)
    if node_type == "reportNote" and "id" in attrs and attrs["id"] is not None:
        clean["id"] = _text(attrs["id"], "report note id", required=True, maximum=80)
    return clean


def _validate_mark(mark: Any) -> dict[str, Any]:
    if not isinstance(mark, dict) or mark.get("type") not in MARK_TYPES:
        raise FoundryError("report mark type is not supported")
    clean = {"type": mark["type"]}
    if mark["type"] == "link":
        attrs = mark.get("attrs", {})
        if not isinstance(attrs, dict):
            raise FoundryError("report link attrs must be an object")
        href = _text(attrs.get("href"), "report link href", required=True, maximum=1000)
        if not re.fullmatch(r"(?:https?|mailto):[^\s]+|#[A-Za-z0-9_.:-]+", href):
            raise FoundryError("report link href is not allowed")
        clean["attrs"] = {"href": href}
    return clean


def _document_metadata_markdown(metadata: dict[str, Any]) -> str:
    labels = (("company", "企业"), ("period", "期间"), ("currency", "币种"), ("unit", "单位"))
    parts = [f"{label}：{str(metadata.get(key, '')).strip()}" for key, label in labels if str(metadata.get(key, '')).strip()]
    return "；".join(parts)


def _table_metadata_markdown(attrs: dict[str, Any]) -> str:
    labels = (("caption", "表题"), ("period", "期间"), ("currency", "币种"), ("unit", "单位"))
    parts = [f"{label}：{str(attrs.get(key, '')).strip()}" for key, label in labels if str(attrs.get(key, '')).strip()]
    return "；".join(parts)


def _paragraph_plain_text(node: dict[str, Any]) -> str:
    if node.get("type") != "paragraph":
        return ""
    return _render_inline(_flat_inline(node.get("content", []))).strip()


def report_document_markdown(document: dict[str, Any], *, title: str | None = None) -> str:
    clean = validate_report_document(document)
    blocks: list[str] = []
    if title:
        blocks.append("# " + title.strip())
    metadata_line = _document_metadata_markdown(clean["metadata"])
    first_content_line = _paragraph_plain_text(clean["content"][0]) if clean["content"] else ""
    if metadata_line and first_content_line != metadata_line:
        blocks.append(metadata_line)
    for node in clean["content"]:
        rendered = _render_block(node, ordered_depth=0).strip("\n")
        if rendered:
            blocks.append(rendered)
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def _render_inline(nodes: list[dict[str, Any]]) -> str:
    parts = []
    for node in nodes:
        node_type = node["type"]
        if node_type == "text":
            text = _escape_markdown_text(node.get("text", ""))
            for mark in node.get("marks", []):
                if mark["type"] == "bold":
                    text = f"**{text}**"
                elif mark["type"] == "code":
                    text = f"`{text}`"
                elif mark["type"] == "link":
                    text = f"[{text}]({mark['attrs']['href']})"
            parts.append(text)
        elif node_type == "hardBreak":
            parts.append("\n")
        elif node_type == "image":
            attrs = node.get("attrs", {})
            title = f' "{attrs["title"]}"' if attrs.get("title") else ""
            parts.append(f"![{attrs.get('alt', '')}]({attrs.get('src', '')}{title})")
        else:
            parts.append(_render_inline(node.get("content", [])))
    return "".join(parts)


def _cell_text(cell: dict[str, Any]) -> str:
    return _render_inline(_flat_inline(cell.get("content", []))).strip()


def _table_cell_markdown(value: str) -> str:
    return value.replace("\n", "<br>").replace("|", r"\|")


def _escape_markdown_text(value: str) -> str:
    return re.sub(r"([\\`*\[\]\(\)])", r"\\\1", value)


def _unescape_markdown_text(value: str) -> str:
    return re.sub(r"\\([\\`*\[\]\(\)|])", r"\1", value)


def _flat_inline(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        if node["type"] == "paragraph":
            result.extend(node.get("content", []))
        else:
            result.append(node)
    return result


def _render_block(node: dict[str, Any], *, ordered_depth: int) -> str:
    node_type = node["type"]
    content = node.get("content", [])
    if node_type == "heading":
        return "#" * node.get("attrs", {}).get("level", 1) + " " + _render_inline(content).strip()
    if node_type == "paragraph":
        return _render_inline(content)
    if node_type == "image":
        return _render_inline([node])
    if node_type == "blockquote":
        text = _render_inline(content)
        return "\n".join("> " + line for line in text.splitlines())
    if node_type == "codeBlock":
        return "```\n" + _render_inline(_flat_inline(content)).rstrip("\n") + "\n```"
    if node_type == "horizontalRule":
        return "---"
    if node_type == "reportPageBreak":
        return '<div class="report-page-break"></div>'
    if node_type == "reportNote":
        note_id = node.get("attrs", {}).get("id", str(ordered_depth + 1))
        return f"[^{note_id}]: " + _render_inline(_flat_inline(content))
    if node_type in {"bulletList", "orderedList"}:
        lines: list[str] = []
        for index, child in enumerate(content, start=1):
            marker = "-" if node_type == "bulletList" else f"{index}."
            rendered = _render_block(child, ordered_depth=ordered_depth + 1).splitlines() or [""]
            lines.append(f"{marker} {rendered[0]}")
            lines.extend("  " + line for line in rendered[1:])
        return "\n".join(lines)
    if node_type == "listItem":
        return "\n".join(_render_block(child, ordered_depth=ordered_depth) for child in content)
    if node_type == "table":
        rows = []
        for row in content:
            rows.append(_expanded_row_text(row))
        width = max((len(row) for row in rows), default=0)
        if not width:
            return ""
        separator = ["---"] * width
        table_lines = ["| " + " | ".join(_table_cell_markdown(value) for value in rows[0]) + " |", "| " + " | ".join(separator) + " |"]
        table_lines.extend("| " + " | ".join(_table_cell_markdown(value) for value in row + [""] * (width - len(row))) + " |" for row in rows[1:])
        table_markdown = "\n".join(table_lines)
        table_meta = _table_metadata_markdown(node.get("attrs", {}))
        return table_meta + "\n\n" + table_markdown if table_meta else table_markdown
    if node_type == "doc":
        return "\n\n".join(_render_block(child, ordered_depth=ordered_depth) for child in content)
    return ""


def _expanded_row_text(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for cell in row.get("content", []):
        values.append(_cell_text(cell))
        colspan = cell.get("attrs", {}).get("colspan", 1)
        if isinstance(colspan, int) and not isinstance(colspan, bool):
            values.extend([""] * (max(1, min(20, colspan)) - 1))
    return values


def _parse_document_metadata_line(text: str) -> dict[str, str] | None:
    labels = {"企业": "company", "期间": "period", "币种": "currency", "单位": "unit"}
    parsed = {"company": "", "period": "", "currency": "", "unit": ""}
    found = False
    for part in text.split("；"):
        if "：" not in part:
            return None
        label, value = part.split("：", 1)
        key = labels.get(label.strip())
        if not key:
            return None
        parsed[key] = value.strip()
        found = True
    return parsed if found else None


def append_markdown_paragraph(document: dict[str, Any], markdown: str) -> dict[str, Any]:
    clean = validate_report_document(document)
    if not markdown.strip():
        return clean
    appended = copy.deepcopy(clean)
    appended["content"].append({"type": "horizontalRule"})
    for block in re.split(r"\n\s*\n", markdown.strip()):
        appended["content"].append({
            "type": "paragraph",
            "content": [{"type": "text", "text": block.strip()}],
        })
    return validate_report_document(appended)


def append_markdown_blocks(document: dict[str, Any], markdown: str) -> dict[str, Any]:
    clean = validate_report_document(document)
    if not markdown.strip():
        return clean
    appended = copy.deepcopy(clean)
    appended["content"].extend(report_nodes_from_markdown(markdown))
    return validate_report_document(appended)


def report_document_from_markdown_body(
    markdown: str,
    *,
    metadata: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nodes = report_nodes_from_markdown(markdown)
    clean_metadata = {"company": "", "period": "", "currency": "", "unit": "", **(metadata or {})}
    if nodes and not any(str(clean_metadata.get(key, "")).strip() for key in ("company", "period", "currency", "unit")):
        parsed = _parse_document_metadata_line(_paragraph_plain_text(nodes[0]))
        if parsed:
            clean_metadata = parsed
            nodes = nodes[1:]
    return validate_report_document(
        {
            "schema_version": 1,
            "template_version": REPORT_TEMPLATE_VERSION,
            "metadata": clean_metadata,
            "sources": sources or [],
            "content": nodes,
        }
    )


def report_nodes_from_markdown(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    nodes: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        note = re.match(r"^\[\^([^\]]+)\]:\s*(.*)$", line)
        if note:
            nodes.append({
                "type": "reportNote",
                "attrs": {"id": note.group(1)},
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": note.group(2)}]}],
            })
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            nodes.append({
                "type": "heading",
                "attrs": {"level": len(heading.group(1))},
                "content": [{"type": "text", "text": heading.group(2)}],
            })
            index += 1
            continue
        if re.fullmatch(r"---+", line.strip()):
            nodes.append({"type": "horizontalRule"})
            index += 1
            continue
        if line.startswith("```"):
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            nodes.append({"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code)}]})
            continue
        if _is_table_start(lines, index):
            table_lines: list[str] = []
            while index < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[index]):
                table_lines.append(lines[index])
                index += 1
            nodes.append(_parse_table(table_lines))
            continue
        list_match = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$", line)
        if list_match:
            ordered = bool(re.match(r"\d+[.)]", list_match.group(2)))
            items = []
            while index < len(lines):
                current = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$", lines[index])
                if not current or bool(re.match(r"\d+[.)]", current.group(2))) != ordered:
                    break
                items.append({"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": current.group(3)}]}]})
                index += 1
            nodes.append({"type": "orderedList" if ordered else "bulletList", "content": items})
            continue
        image = re.match(r'^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)$', line)
        if image:
            nodes.append({"type": "image", "attrs": {"alt": image.group(1), "src": image.group(2), "title": image.group(3) or ""}})
            index += 1
            continue
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip():
            if re.match(r"^(#{1,6})\s+", lines[index]) or _is_table_start(lines, index) or re.match(r"^\[\^([^\]]+)\]:", lines[index]):
                break
            if re.match(r"^(\s*)([-*+]|\d+[.)])\s+", lines[index]) or lines[index].startswith("```") or re.fullmatch(r"---+", lines[index].strip()):
                break
            paragraph.append(lines[index])
            index += 1
        nodes.append({"type": "paragraph", "content": [{"type": "text", "text": "\n".join(paragraph)}]})
    return nodes


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return bool(
        re.match(r"^\s*\|.*\|\s*$", lines[index])
        and re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[index + 1])
    )


def _parse_table(lines: list[str]) -> dict[str, Any]:
    rows = []
    for row_index, line in enumerate(line for pos, line in enumerate(lines) if pos != 1):
        cells = [
            {
                "type": "tableHeader" if row_index == 0 else "tableCell",
                "attrs": {"textAlign": "right" if _markdown_numeric_like(cell.strip()) else "left"},
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": _unescape_markdown_text(cell.strip())}]}],
            }
            for cell in _split_markdown_row(line)
        ]
        rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "content": rows}


def _split_markdown_row(line: str) -> list[str]:
    trimmed = line.strip().removeprefix("|").removesuffix("|")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in trimmed:
        if escaped:
            current.append("\\")
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _markdown_numeric_like(text: str) -> bool:
    return bool(re.fullmatch(r"[(（]?-?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?", text))



def _node_source_columns(node: dict[str, Any]) -> list[Any]:
    attrs = node.get("attrs", {})
    return [attrs.get("source_id"), attrs.get("sheet"), attrs.get("range"), attrs.get("page")]


def report_document_excel_rows(document: dict[str, Any], draft: dict[str, Any]) -> dict[str, list[list[Any]]]:
    clean = validate_report_document(document)
    overview = [["字段", "值"]]
    for label, value in (
        ("标题", draft.get("title", "")),
        ("版本", draft.get("id", "")),
        ("内容哈希", draft.get("content_hash", "")),
        ("发布状态", draft.get("publication_status", "")),
        ("复核状态", draft.get("review_status", "")),
        ("可复现性", draft.get("reproducibility_status", "")),
        ("企业", clean["metadata"].get("company", "")),
        ("期间", clean["metadata"].get("period", "")),
        ("币种", clean["metadata"].get("currency", "")),
        ("单位", clean["metadata"].get("unit", "")),
        ("来源数量", len(clean.get("sources", []))),
    ):
        overview.append([label, value])

    sections = [["序号", "类型", "层级", "文本", "source_id", "sheet", "range", "page"]]
    tables = [["表序号", "行序号", "列序号", "单元格类型", "文本", "colspan", "rowspan", "textAlign", "表题", "期间", "币种", "单位", "source_id", "sheet", "range"]]
    notes = [["附注编号", "文本", "source_id", "page", "sheet", "range"]]
    sources = [["source_id", "名称", "格式", "sha256"]]
    for source in clean.get("sources", []):
        sources.append([source.get("id"), source.get("name"), source.get("format"), source.get("sha256")])

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            node_type = node.get("type")
            attrs = node.get("attrs", {})
            if node_type == "heading":
                sections.append([len(sections), "heading", attrs.get("level", 1), _render_inline(node.get("content", [])).strip(), *_node_source_columns(node)])
            elif node_type == "paragraph":
                sections.append([len(sections), "paragraph", "", _paragraph_plain_text(node), *_node_source_columns(node)])
            elif node_type in {"bulletList", "orderedList"}:
                for item in node.get("content", []):
                    sections.append([len(sections), node_type, "", _render_block(item, ordered_depth=0).strip(), *_node_source_columns(item)])
            elif node_type == "reportNote":
                notes.append([attrs.get("id", str(len(notes))), _render_inline(_flat_inline(node.get("content", []))).strip(), attrs.get("source_id"), attrs.get("page"), attrs.get("sheet"), attrs.get("range")])
            elif node_type == "table":
                table_no = len({row[0] for row in tables[1:]}) + 1
                table_attrs = node.get("attrs", {})
                for row_index, row in enumerate(node.get("content", []), start=1):
                    col_index = 1
                    for cell in row.get("content", []):
                        cell_attrs = cell.get("attrs", {})
                        tables.append([
                            table_no, row_index, col_index, cell.get("type"), _cell_text(cell),
                            cell_attrs.get("colspan", 1), cell_attrs.get("rowspan", 1), cell_attrs.get("textAlign", ""),
                            table_attrs.get("caption", ""), table_attrs.get("period", ""), table_attrs.get("currency", ""), table_attrs.get("unit", ""),
                            cell_attrs.get("source_id") or table_attrs.get("source_id"),
                            cell_attrs.get("sheet") or table_attrs.get("sheet"),
                            cell_attrs.get("range") or table_attrs.get("range"),
                        ])
                        colspan = cell_attrs.get("colspan", 1)
                        col_index += max(1, colspan if isinstance(colspan, int) and not isinstance(colspan, bool) else 1)
            elif node_type == "image":
                sections.append([len(sections), "image", "", str(attrs.get("alt") or attrs.get("title") or ""), *_node_source_columns(node)])
            if node_type not in {"table"}:
                walk([child for child in node.get("content", []) if isinstance(child, dict) and child.get("type") not in INLINE_TYPES])

    walk(clean["content"])
    return {"报告概览": overview, "分段正文": sections, "财务表格": tables, "附注": notes, "来源": sources}

def report_document_from_xlsx(data: bytes, source: dict[str, Any], *, sheet: str | None = None, range_ref: str | None = None) -> dict[str, Any]:
    check_report_source_bytes(data, "xlsx")
    warnings: list[str] = []
    raw = _raw_xlsx_cells(data, sheet)
    cached = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    formulas = load_workbook(io.BytesIO(data), data_only=False, read_only=False)
    try:
        sheet_names = cached.sheetnames
        target_sheet = sheet or sheet_names[0]
        if target_sheet not in sheet_names:
            raise FoundryError(f"no worksheet: {target_sheet}")
        value_sheet = cached[target_sheet]
        formula_sheet = formulas[target_sheet]
        min_col, min_row, max_col, max_row = _range_bounds(value_sheet, range_ref)
        if max_col - min_col + 1 > MAX_COLUMNS or max_row - min_row + 1 > MAX_ROWS + 1:
            raise FoundryError("selected report range exceeds row/column limits")
        rows: list[dict[str, Any]] = []
        merged = _merged_index(formula_sheet)
        for row_index in range(min_row, max_row + 1):
            cells = []
            for column_index in range(min_col, max_col + 1):
                coord = f"{get_column_letter(column_index)}{row_index}"
                merge = merged.get(coord)
                if merge and merge["anchor"] != coord:
                    continue
                formula_cell = formula_sheet.cell(row_index, column_index)
                value_cell = value_sheet.cell(row_index, column_index)
                if isinstance(formula_cell.value, str) and formula_cell.value.startswith("=") and value_cell.value is None:
                    warnings.append(f"公式没有缓存值：{target_sheet}!{coord}")
                value = raw.get(coord, value_cell.value)
                attrs: dict[str, Any] = {"textAlign": "right" if _numeric_like(value) else "left"}
                if merge:
                    attrs.update({k: v for k, v in merge.items() if k in {"rowspan", "colspan"} and v > 1})
                cell_type = "tableHeader" if row_index == min_row else "tableCell"
                cells.append({"type": cell_type, "attrs": attrs, "content": [{"type": "paragraph", "content": [{"type": "text", "text": _display_value(value)}]}]})
            rows.append({"type": "tableRow", "content": cells})
        selected_range = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}"
        metadata = {"company": "", "period": "", "currency": "", "unit": ""}
        content = [
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": source["name"]}]},
            {"type": "paragraph", "content": [{"type": "text", "text": f"来源：{source['name']}；工作表：{target_sheet}；区域：{selected_range}。"}]},
            {
                "type": "table",
                "attrs": {
                    "caption": target_sheet,
                    "source_id": source["id"],
                    "sheet": target_sheet,
                    "range": selected_range,
                },
                "content": rows,
            },
        ]
        if warnings:
            content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "转换提示"}]})
            for warning in dict.fromkeys(warnings):
                content.append({"type": "reportNote", "attrs": {"id": str(len(content))}, "content": [{"type": "paragraph", "content": [{"type": "text", "text": warning}]}]})
        document = validate_report_document({
            "schema_version": 1,
            "template_version": REPORT_TEMPLATE_VERSION,
            "metadata": metadata,
            "sources": [source],
            "content": content,
        }, registered_source_ids={source["id"]})
        return {
            "document": document,
            "title": source["name"],
            "warnings": list(dict.fromkeys(warnings)),
            "source": source,
            "sheets": sheet_names,
            "needsReview": bool(warnings),
        }
    finally:
        cached.close()
        formulas.close()


def _range_bounds(sheet, range_ref: str | None) -> tuple[int, int, int, int]:
    if not range_ref:
        return 1, 1, sheet.max_column or 1, sheet.max_row or 1
    try:
        min_col, min_row, max_col, max_row = range_boundaries(range_ref)
    except ValueError as exc:
        raise FoundryError("report xlsx range must be an A1 range") from exc
    if min_col < 1 or min_row < 1 or max_col < min_col or max_row < min_row:
        raise FoundryError("report xlsx range must be an A1 range")
    return min_col, min_row, max_col, max_row


def _numeric_like(value: Any) -> bool:
    return isinstance(value, Decimal) or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _merged_index(sheet) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in sheet.merged_cells.ranges:
        min_col, min_row, max_col, max_row = item.bounds
        anchor = f"{get_column_letter(min_col)}{min_row}"
        for row_index in range(min_row, max_row + 1):
            for column_index in range(min_col, max_col + 1):
                result[f"{get_column_letter(column_index)}{row_index}"] = {
                    "anchor": anchor,
                    "rowspan": max_row - min_row + 1,
                    "colspan": max_col - min_col + 1,
                }
    return result


def _raw_xlsx_cells(data: bytes, sheet_name: str | None) -> dict[str, Decimal]:
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            book = load_workbook(io.BytesIO(data), data_only=False, read_only=True)
            try:
                target = sheet_name or book.sheetnames[0]
                if target not in book.sheetnames:
                    raise FoundryError(f"no worksheet: {target}")
                workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
                sheets = workbook_xml.find("s:sheets", ns)
                rid = next(
                    sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                    for sheet in sheets
                    if sheet.attrib["name"] == target
                )
                rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                member_target = next(rel.attrib["Target"] for rel in rels if rel.attrib["Id"] == rid)
                member = member_target.lstrip("/") if member_target.startswith("/") else "xl/" + member_target
                raw: dict[str, Decimal] = {}
                for _, cell in ET.iterparse(io.BytesIO(archive.read(member)), events=("end",)):
                    if cell.tag != "{" + ns["s"] + "}c":
                        continue
                    value = cell.find("s:v", ns)
                    if cell.attrib.get("t", "n") == "n" and value is not None and value.text:
                        raw[cell.attrib["r"]] = Decimal(value.text)
                    cell.clear()
                return raw
            finally:
                book.close()
    except BadZipFile as exc:
        raise FoundryError("invalid XLSX source archive") from exc
