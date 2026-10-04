"""Read-only PPTX import: the words and tables of each slide, in the order the deck shows them.

Only the standard library reads the deck (zipfile + ElementTree), as the XLSX reader does.
Charts, pictures, layout and speaker notes are not imported: a slide becomes a heading
「第 N 页」 followed by its text paragraphs and tables, every node located by `page`
(the slide number, as text) and the deck's `source_id`.
"""

from __future__ import annotations

import io
import posixpath
from typing import Any
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from foundry.errors import FoundryError
from foundry.report_documents import (
    REPORT_TEMPLATE_VERSION,
    _markdown_numeric_like,
    check_report_source_bytes,
    validate_report_document,
)

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
SLIDE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
TITLE_PLACEHOLDERS = {"title", "ctrTitle"}
# Footer, date and slide-number boxes are layout chrome, not what the slide says.
CHROME_PLACEHOLDERS = {"sldNum", "dt", "ftr", "hdr"}
MAX_SLIDES = 500
PPTX_WARNING = "PPT 导入只取文字和表格，图表、图片和版式不导入；数字需复核。"


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _xml(archive: ZipFile, member: str) -> ET.Element:
    try:
        data = archive.read(member)
    except KeyError as exc:
        raise FoundryError(f"PPTX part is missing: {member}") from exc
    # A deck never needs a DTD; refusing one keeps entity expansion out of the parser.
    if b"<!DOCTYPE" in data:
        raise FoundryError("PPTX part declares a DTD")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise FoundryError(f"invalid PPTX part: {member}") from exc


def _slide_members(archive: ZipFile) -> list[str]:
    """Slide parts in presentation order (sldIdLst), never by file name."""
    presentation = _xml(archive, "ppt/presentation.xml")
    rels = _xml(archive, "ppt/_rels/presentation.xml.rels")
    targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.iter(_q(REL, "Relationship"))
        if rel.attrib.get("Type") == SLIDE_TYPE and rel.attrib.get("TargetMode") != "External"
    }
    listing = presentation.find(_q(P, "sldIdLst"))
    members: list[str] = []
    for slide_id in [] if listing is None else listing.findall(_q(P, "sldId")):
        target = targets.get(slide_id.attrib.get(_q(R, "id")))
        if not target:
            continue
        member = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("ppt", target))
        if not member.startswith("ppt/slides/") or member.startswith("../"):
            raise FoundryError("PPTX slide target is outside the deck")
        members.append(member)
        if len(members) > MAX_SLIDES:
            raise FoundryError(f"PPTX has more than {MAX_SLIDES} slides")
    return members


def _inline(paragraph: ET.Element) -> list[dict[str, Any]]:
    """Runs and fields of one a:p as text nodes, a:br as a hard break."""
    nodes: list[dict[str, Any]] = []
    for child in paragraph:
        if child.tag in {_q(A, "r"), _q(A, "fld")}:
            text = "".join(item.text or "" for item in child.iter(_q(A, "t")))
            if text:
                if nodes and nodes[-1]["type"] == "text":
                    nodes[-1]["text"] += text
                else:
                    nodes.append({"type": "text", "text": text})
        elif child.tag == _q(A, "br") and nodes:
            nodes.append({"type": "hardBreak"})
    while nodes and nodes[-1]["type"] == "hardBreak":
        nodes.pop()
    return nodes if any(node.get("text", "").strip() for node in nodes) else []


def _paragraphs(body: ET.Element | None) -> list[list[dict[str, Any]]]:
    if body is None:
        return []
    return [inline for paragraph in body.findall(_q(A, "p")) if (inline := _inline(paragraph))]


def _cell(cell: ET.Element, header: bool, located: dict[str, str]) -> dict[str, Any]:
    paragraphs = _paragraphs(cell.find(_q(A, "txBody")))
    text = " ".join(node.get("text", "") for inline in paragraphs for node in inline).strip()
    attrs: dict[str, Any] = {**located, "textAlign": "right" if _markdown_numeric_like(text) else "left"}
    for source, key in (("gridSpan", "colspan"), ("rowSpan", "rowspan")):
        try:
            span = int(cell.attrib.get(source, "1"))
        except ValueError:
            span = 1
        if span > 1:
            attrs[key] = min(span, 100)
    content = [{"type": "paragraph", "attrs": dict(located), "content": inline} for inline in paragraphs]
    return {"type": "tableHeader" if header else "tableCell", "attrs": attrs,
            "content": content or [{"type": "paragraph", "attrs": dict(located)}]}


def _table(table: ET.Element, located: dict[str, str]) -> dict[str, Any] | None:
    rows = []
    for row_index, row in enumerate(table.findall(_q(A, "tr"))):
        # A merged cell's continuation (hMerge/vMerge) carries no text of its own; the anchor's span covers it.
        cells = [
            _cell(cell, row_index == 0, located)
            for cell in row.findall(_q(A, "tc"))
            if cell.attrib.get("hMerge") not in {"1", "true"} and cell.attrib.get("vMerge") not in {"1", "true"}
        ]
        if cells:
            rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "attrs": dict(located), "content": rows} if rows else None


def _shape_nodes(tree: ET.Element, located: dict[str, str]) -> list[dict[str, Any]]:
    """Text and tables of a shape tree in its own order; groups are read in place."""
    nodes: list[dict[str, Any]] = []
    for shape in tree:
        if shape.tag == _q(P, "sp"):
            placeholder = shape.find(f"{_q(P, 'nvSpPr')}/{_q(P, 'nvPr')}/{_q(P, 'ph')}")
            kind = placeholder.attrib.get("type") if placeholder is not None else None
            if kind in CHROME_PLACEHOLDERS:
                continue
            is_title = kind in TITLE_PLACEHOLDERS
            for inline in _paragraphs(shape.find(_q(P, "txBody"))):
                if is_title:
                    nodes.append({"type": "heading", "attrs": {**located, "level": 3},
                                  "content": [node for node in inline if node["type"] == "text"]})
                else:
                    nodes.append({"type": "paragraph", "attrs": dict(located), "content": inline})
        elif shape.tag == _q(P, "graphicFrame"):
            for table in shape.iter(_q(A, "tbl")):
                node = _table(table, located)
                if node:
                    nodes.append(node)
        elif shape.tag == _q(P, "grpSp"):
            nodes.extend(_shape_nodes(shape, located))
    return nodes


def report_document_from_pptx(data: bytes, source: dict[str, Any]) -> dict[str, Any]:
    check_report_source_bytes(data, "pptx")
    warnings = [PPTX_WARNING]
    content: list[dict[str, Any]] = []
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            members = _slide_members(archive)
            if not members:
                raise FoundryError("PPTX has no slides")
            for number, member in enumerate(members, start=1):
                slide = _xml(archive, member)
                if slide.attrib.get("show") in {"0", "false"}:
                    warnings.append(f"第 {number} 页是隐藏页，未导入。")
                    continue
                located = {"source_id": source["id"], "page": str(number)}
                content.append({"type": "heading", "attrs": {**located, "level": 2},
                                "content": [{"type": "text", "text": f"第 {number} 页"}]})
                tree = slide.find(f"{_q(P, 'cSld')}/{_q(P, 'spTree')}")
                if tree is not None:
                    content.extend(_shape_nodes(tree, located))
    except BadZipFile as exc:
        raise FoundryError("invalid PPTX source archive") from exc
    document = validate_report_document({
        "schema_version": 1,
        "template_version": REPORT_TEMPLATE_VERSION,
        "metadata": {"ledger": "", "organization": "", "company": "", "period": "", "currency": "", "unit": ""},
        "sources": [source],
        "content": content,
    }, registered_source_ids={source["id"]})
    return {
        "document": document,
        "title": source["name"],
        "warnings": warnings,
        "source": source,
        "needsReview": True,
    }
