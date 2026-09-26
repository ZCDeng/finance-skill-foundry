"""Estimates in report exports (issue #24): which cells are estimates, the 估算值声明 block, and where a
{{fact:…}} template rendered an estimate.

Which cells are estimates is decided only by the server's requirement check that save_draft stored on the draft
(`explanation_check.requirements`): the cited cells of its `estimated_grains`, and the grains its items declare
estimates in `grain_basis` that the check left uncounted (issue #33). Nothing in the text decides it, and the text
is never scanned for numbers. The declaration is built from the check's structured data; an inline
（估算） goes only where the draft's own {{fact:…}} template rendered an estimated fact, and only when rendering that
template again reproduces the stored text exactly.
"""

from __future__ import annotations

import bisect
import re
from typing import Any

from foundry.errors import FoundryError
from foundry.finance_requirement_support import _basis_formula
from foundry.report_documents import (
    NOTE_REF,
    _document_metadata_markdown,
    _escape_markdown_literal,
    _escape_markdown_text,
    _paragraph_plain_text,
    _parse_document_metadata_line,
    report_document_markdown,
    report_nodes_from_markdown,
    validate_report_document,
)

ESTIMATE_LABEL = "（估算）"
DECLARATION_HEADING = "估算值声明"
DECLARATION_SENTENCE = "以下数值为估算，经理确认前不作为批复预算。"
DECLARATION_COLUMNS = ("要求", "组织", "期间", "情景", "估算值", "估算公式")
GRAIN_FIELDS = ("organization", "period", "scenario")
NOT_STATED = "—"
# Why a declared estimate grain the check did not count has no recomputed formula (issue #33).
NOT_REPRODUCIBLE = "系数无法由来源复算"
NOT_RECOMPUTED = "尚未由来源复算"
# Declared estimate grains listed without a cited value, per item; the rest are counted in one row.
UNCITED_GRAIN_ROWS = 12
# Private-use characters no renderer writes: _MARK stands where a label goes, _SLOT for a text node's text.
_MARK = "\ue000"
_SLOT = "\ue001"
_ESCAPED = set("\\`*[]()")
_ESCAPABLE = re.compile(r"[\\`*\[\]()]")
# The template's own label right after a token (after the prose's unit where it writes one), as the check's message
# asks the body to write it: （估算） or (估算), markdown-escaped or not, after a space or the token's closing emphasis.
_AUTHOR_LABEL = re.compile(r"[*_~`]*[ \t\u3000]*\\?[（(]估算")


def estimated_cells(
    draft: dict[str, Any], runs: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """What the draft's stored requirement check says is an estimate, in the check's order, one entry per
    requirement item and cell, with the item and the grain it belongs to:
    - the cited cells of the grains the check found `estimated`;
    - then, per item, each grain its `grain_basis` declares an estimate that the check left uncounted (declared
      non-reproducible, uncounted or missing; never an answered grain), with `declared` (the declaration): its
      cited cells that did not answer, or one entry with `cell` None where the draft cites none. Which grain a
      cited cell belongs to is read off the cell's run row in `runs` (by id), as the check read it."""
    check = draft.get("explanation_check")
    requirements = check.get("requirements") if isinstance(check, dict) else None
    items = requirements.get("items") if isinstance(requirements, dict) else None
    cells: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        seen: set[tuple[str, int, str]] = set()
        for grain in item.get("estimated_grains") if isinstance(item.get("estimated_grains"), list) else []:
            locations = grain.get("locations") if isinstance(grain, dict) else None
            for location in locations if isinstance(locations, list) else []:
                key = _cell_key(location)
                if key is not None and key not in seen:
                    seen.add(key)
                    cells.append({"item": item, "grain": grain, "cell": key})
        cells.extend(_declared_estimate_cells(item, seen, runs or {}))
    return cells


def _declared_estimate_cells(
    item: dict[str, Any], seen: set[tuple[str, int, str]], runs: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Grains the item declares an estimate (grain_basis basis estimate) that the check left unanswered and not
    estimated: declared with a factor no recipe can recompute (declared_grains), or declared reproducible and not
    yet made `estimated` by a factor recipe (uncounted_grains, missing_grains).

    A grain's cells are its cited cells that state an estimate: not an answered cell, and not a cell restating a
    number an answered cell of the grain states. A cell a factor recipe made `estimated` keeps its recipe (no
    `declared`). Where the item lists no scenarios, the grain holds cells the declaration cannot tell apart (an
    actual beside the estimate): the grain is declared with no cell. Grains
    declared with no cell are listed up to UNCITED_GRAIN_ROWS per item, the rest counted in one entry (`more`)."""
    from foundry.finance_requirements import (
        GRAIN_LISTS, _cited_value, _declared_basis, _location_grain, _same_number,
    )

    if not isinstance(item.get("grain_basis"), list) or not isinstance(item.get("locations"), list):
        return []
    grains: dict[tuple[Any, ...], tuple[dict[str, Any], dict[str, Any]]] = {}
    for field in ("declared_grains", "uncounted_grains", "missing_grains"):
        for record in item.get(field) if isinstance(item.get(field), list) else []:
            if not isinstance(record, dict) or (field == "declared_grains"
                                                and record.get("state") != "estimate_factor_not_reproducible"):
                continue
            grain = tuple(record.get(key) if item.get(plural) else None for key, plural in GRAIN_LISTS)
            declared = _declared_basis(item, grain)
            if declared and declared.get("basis") == "estimate" and grain not in grains:
                grains[grain] = (record, declared)
    if not grains:
        return []
    members: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for location in item["locations"]:
        if _cell_key(location) is None or location["run_id"] not in runs:
            continue
        try:
            grain = _location_grain(item, location, runs)
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
        if grain in grains:
            members.setdefault(grain, []).append(location)

    found: list[dict[str, Any]] = []
    uncited = 0
    for grain, (record, declared) in grains.items():
        cited = members.get(grain) or []
        answered = [_cited_value(location, runs) for location in cited if location.get("status") == "answered"]
        cells = [location for location in cited if location.get("status") != "answered"
                 and not any(_same_number(_cited_value(location, runs), value) for value in answered)]
        if not item.get("scenarios"):
            # The scenario tells an estimate from the actual; a declaration over every scenario cannot, whichever
            # column the rows name their scenario in.
            cells = []
        added = False
        for location in cells:
            key = _cell_key(location)
            if key in seen:
                continue
            seen.add(key)
            added = True
            found.append({"item": item, "grain": record, "cell": key,
                          **({} if location.get("status") == "estimated" else {"declared": declared})})
        if added or cells:
            continue
        uncited += 1
        if uncited <= UNCITED_GRAIN_ROWS:
            found.append({"item": item, "grain": record, "cell": None, "declared": declared})
    if uncited > UNCITED_GRAIN_ROWS:
        found.append({"item": item, "grain": {}, "cell": None, "more": uncited - UNCITED_GRAIN_ROWS})
    return found


def declare_estimates(
    document: dict[str, Any],
    draft: dict[str, Any],
    cells: list[dict[str, Any]],
    labels: list[tuple[int, int]],
    runs: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """The projection document with （估算） at `labels` (text node index in document order, offset) and the
    估算值声明 block right after the title; and the room beyond the text and node limits those additions take.
    `runs` (by id) give a declared cell's own row where its grain leaves a field out (see _declaration_rows)."""
    declared = {**document, "content": _copied(document["content"])}
    texts = _text_nodes(declared["content"])
    offsets: dict[int, list[int]] = {}
    for index, offset in labels:
        offsets.setdefault(index, []).append(offset)
    added = 0
    for index, positions in offsets.items():
        text = texts[index]["text"]
        pieces, cursor = [], 0
        for offset in sorted(position for position in positions if position <= len(text)):
            pieces.extend((text[cursor:offset], ESTIMATE_LABEL))
            cursor = offset
            added += 1
        texts[index]["text"] = "".join(pieces) + text[cursor:]
    nodes = _declaration_nodes(_declaration_rows(draft, cells, runs))
    content = declared["content"]
    # Right after the title: after the author's own metadata line when the document opens with it (the markdown
    # export prints that paragraph in place of the generated one), otherwise first.
    metadata = _document_metadata_markdown(declared["metadata"], declare_missing=bool(declared.get("template_id")))
    first = 1 if metadata and content and _paragraph_plain_text(content[0]) == metadata else 0
    declared["content"] = [*content[:first], *nodes, *content[first:]]
    headroom = {"text": _text_length(nodes) + len(ESTIMATE_LABEL) * added, "nodes": _node_count(nodes)}
    return (
        validate_report_document(declared, text_headroom=headroom["text"], node_headroom=headroom["nodes"]),
        headroom,
    )


def template_label_positions(
    draft: dict[str, Any], document: dict[str, Any], cells: list[dict[str, Any]]
) -> list[tuple[int, int]]:
    """Where （估算） goes in `document`, the draft's own document as the projection reads it: (index of the text
    node in document order, offset in its text) right after each display of an estimated fact that the draft's
    {{fact:…}} template rendered, after the unit where the prose writes the unit, unless the template writes the
    label there itself.

    The positions come from the template's tokens, never from the numbers in the text. Nothing is placed unless
    rendering the stored template again gives exactly the stored body or document text.
    """
    template = draft.get("body_template")
    check = draft.get("explanation_check")
    facts = check.get("facts") if isinstance(check, dict) else None
    if not isinstance(template, str) or not isinstance(facts, list):
        return []
    facts = [fact for fact in facts if isinstance(fact, dict) and isinstance(fact.get("id"), str)
             and isinstance(fact.get("display_value"), str)]
    estimated = {entry["cell"] for entry in cells}
    fact_ids = {fact["id"] for fact in facts if _cell_key(fact) is not None and _cell_key(fact) in estimated}
    rendered = _render_marked(template, facts, fact_ids) if fact_ids else None
    if rendered is None:
        return []
    plain, marked = rendered
    try:
        if draft.get("document") is not None:
            positions = _document_positions(document, plain, marked)
        else:
            positions = _body_positions(draft, document, plain, marked)
    except FoundryError:
        positions = None
    return positions or []


def _cell_key(location: Any) -> tuple[str, int, str] | None:
    if not isinstance(location, dict):
        return None
    run_id, row, column = location.get("run_id"), location.get("row"), location.get("column")
    if not isinstance(run_id, str) or isinstance(row, bool) or not isinstance(row, int) or not isinstance(column, str):
        return None
    return run_id, row, column


def _declaration_rows(
    draft: dict[str, Any], cells: list[dict[str, Any]], runs: dict[str, dict[str, Any]] | None = None
) -> list[list[str]]:
    check = draft["explanation_check"]
    facts = {_cell_key(fact): fact for fact in check.get("facts") or [] if isinstance(fact, dict)}
    claims = {_cell_key(claim): claim for claim in draft.get("claims") or [] if isinstance(claim, dict)}
    rows = []
    for entry in cells:
        item, grain, key = entry["item"], entry["grain"], entry["cell"]
        if entry.get("more"):
            rows.append([_shown(item.get("label") or item.get("metric") or item.get("id")), *[NOT_STATED] * 4,
                         f"另有 {entry['more']} 个声明为估算的组合未引用数值"])
            continue
        declared = entry.get("declared")
        fact = (facts.get(key) or {}) if key is not None else {}
        # The value as its fact displays it (value and unit), as a {{fact:…}} template writes it.
        value = fact.get("display_value") or ((claims.get(key) or {}).get("value") if key is not None else None)
        if declared:
            # No recipe recomputed this estimate: the requirement's declared method, and why.
            not_recomputed = NOT_RECOMPUTED if declared.get("factor_reproducible", True) else NOT_REPRODUCIBLE
            formula = f"{str(declared.get('method') or '').strip()}（{not_recomputed}）"
        else:
            formula = next((_formula(location.get("evidence")) for location in item.get("locations") or []
                            if _cell_key(location) == key and location.get("status") == "estimated"), "")
        rows.append([
            _shown(item.get("label") or item.get("metric") or item.get("id")),
            *(_shown(part) for part in (_cell_grain(grain, key, runs) if key is not None
                                        else [grain.get(field) for field in GRAIN_FIELDS])),
            _shown(value),
            _shown(formula),
        ])
    return rows


def _cell_grain(
    grain: dict[str, Any], key: tuple[str, int, str], runs: dict[str, dict[str, Any]] | None
) -> list[Any]:
    """Organization, period and scenario of an estimated cell. The check's grain holds only the fields its item
    lists; a field it leaves out is read off the cell's own run row the way the check reads a row's grain."""
    values = [grain.get(field) for field in GRAIN_FIELDS]
    run = (runs or {}).get(key[0])
    rows = ((run.get("result") or {}).get("rows") or []) if isinstance(run, dict) else []
    row = rows[key[1]] if 0 <= key[1] < len(rows) else None
    if all(value not in (None, "") for value in values) or not isinstance(row, dict):
        return values
    from foundry.finance_requirements import _row_organization, _row_period, _row_scenario

    read = (_row_organization, _row_period, _row_scenario)
    return [value if value not in (None, "") else reader(run, row) for value, reader in zip(values, read)]


def _formula(evidence: Any) -> str:
    """The estimate's recipe as the audit appendix's 来源复算依据 writes it: source range × (factor ratio)."""
    if not isinstance(evidence, dict):
        return ""
    try:
        return _basis_formula(evidence)
    except (AttributeError, TypeError):
        return ""


def _shown(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text or NOT_STATED


def _declaration_nodes(rows: list[list[str]]) -> list[dict[str, Any]]:
    def text(value: str) -> dict[str, Any]:
        return {"type": "text", "text": value}

    def cell(kind: str, value: str, align: str = "left") -> dict[str, Any]:
        return {"type": kind, "attrs": {"textAlign": align}, "content": [{"type": "paragraph", "content": [text(value)]}]}

    value_column = DECLARATION_COLUMNS.index("估算值")
    header = {"type": "tableRow", "content": [cell("tableHeader", name) for name in DECLARATION_COLUMNS]}
    body = [
        {"type": "tableRow", "content": [
            cell("tableCell", value, "right" if index == value_column else "left") for index, value in enumerate(row)
        ]}
        for row in rows
    ]
    return [
        {"type": "heading", "attrs": {"level": 2}, "content": [text(DECLARATION_HEADING)]},
        {"type": "paragraph", "content": [text(DECLARATION_SENTENCE)]},
        {"type": "table", "content": [header, *body]},
    ]


def _render_marked(template: str, facts: list[dict[str, Any]], fact_ids: set[str]) -> tuple[str, str] | None:
    """The template rendered by render_fact_template's rule, and the same text with _MARK after each rendered fact
    in `fact_ids` (after the prose's unit where the display leaves the unit to the prose) that the template does
    not already label itself (_AUTHOR_LABEL). The caller compares the first with the stored text, so a rendering
    that differs from the one saved places nothing."""
    from foundry.finance_explanations import FACT_TOKEN

    if _MARK in template or _SLOT in template:
        return None
    by_id = {fact["id"]: fact for fact in facts}
    units: dict[str, re.Pattern[str]] = {}
    plain: list[str] = []
    marked: list[str] = []
    cursor = 0
    for match in FACT_TOKEN.finditer(template):
        between = template[cursor:match.start()]
        plain.append(between)
        marked.append(between)
        cursor = match.end()
        fact = by_id.get(match.group(1))
        if not fact:
            plain.append(match.group(0))
            marked.append(match.group(0))
            continue
        display = fact["display_value"]
        unit = str(fact.get("unit") or "")
        # render_fact_template's rule (_unit_follows): where the prose writes the unit, the display leaves it out.
        follows = None
        if unit and display.endswith(f" {unit}"):
            if unit not in units:
                units[unit] = re.compile(rf"\s*{re.escape(unit)}(?![\w\u4e00-\u9fff])")
            follows = units[unit].match(template, cursor)
        if follows:
            display = display[: -len(unit)].rstrip()
        plain.append(display)
        marked.append(display)
        if fact["id"] in fact_ids:
            if follows:
                marked.append(follows.group(0))
                plain.append(follows.group(0))
                cursor = follows.end()
            # Where the template already labels this estimate itself, a second label would print （估算）（估算）.
            if not _AUTHOR_LABEL.match(template, cursor):
                marked.append(_MARK)
    plain.append(template[cursor:])
    marked.append(template[cursor:])
    if _MARK not in marked:
        return None
    return "".join(plain), "".join(marked)


def _body_positions(
    draft: dict[str, Any], document: dict[str, Any], plain: str, marked: str
) -> list[tuple[int, int]] | None:
    """A markdown body draft: its stored body is the rendered template, then the generated appendix. Parse the
    body with the marks in it exactly as the projection parses the stored body, and read the marks off the same
    text nodes."""
    body = draft.get("body")
    appendix = str(draft.get("evidence_appendix") or "")
    if body == plain:
        marked_body = marked
    elif appendix.strip() and body == plain.rstrip() + "\n\n" + appendix.lstrip():
        marked_body = marked.rstrip() + "\n\n" + appendix.lstrip()
    else:
        return None
    if marked_body.replace(_MARK, "") != body:
        return None
    nodes = report_nodes_from_markdown(marked_body)
    # As report_document_from_markdown_body: a leading metadata line becomes the document's metadata.
    if nodes and _parse_document_metadata_line(_paragraph_plain_text(nodes[0])):
        nodes = nodes[1:]
    positions: list[tuple[int, int]] = []
    if not _same_nodes(document["content"], nodes, positions, [0]):
        return None
    return positions if len(positions) == marked_body.count(_MARK) else None


def _same_nodes(stored: list, marked: list, positions: list[tuple[int, int]], counter: list[int]) -> bool:
    if len(stored) != len(marked):
        return False
    for node, other in zip(stored, marked):
        if not isinstance(other, dict) or node.get("type") != other.get("type"):
            return False
        if node["type"] == "text":
            text = str(other.get("text", ""))
            if text.replace(_MARK, "") != node.get("text", ""):
                return False
            offset = 0
            for piece in text.split(_MARK)[:-1]:
                offset += len(piece)
                positions.append((counter[0], offset))
            counter[0] += 1
        elif not _same_nodes(node.get("content") or [], other.get("content") or [], positions, counter):
            return False
    return True


def _document_positions(document: dict[str, Any], plain: str, marked: str) -> list[tuple[int, int]] | None:
    """A structured document draft: its body_template is the markdown of the document before rendering, and the
    stored document's markdown starts with that template rendered. Map each mark to the text node whose markdown
    holds it, through the document's markdown with every text node's text replaced by one slot character."""
    rendered = report_document_markdown(document)
    if not rendered.startswith(plain):
        return None
    slices = _text_slices(document, rendered)
    if slices is None:
        return None
    starts = [start for start, _end, _text, _literal in slices]
    escaped: list[tuple[int, int]] = []
    offset = 0
    for piece in marked.split(_MARK)[:-1]:
        offset += len(piece)
        index = bisect.bisect_left(starts, offset) - 1
        if index < 0 or not slices[index][0] < offset <= slices[index][1]:
            return None
        escaped.append((index, offset - slices[index][0]))
    wanted: dict[int, set[int]] = {}
    for index, position in escaped:
        wanted.setdefault(index, set()).add(position)
    raw = {index: _raw_offsets(slices[index][2], slices[index][3], positions) for index, positions in wanted.items()}
    if any(position not in raw[index] for index, position in escaped):
        return None
    return [(index, raw[index][position]) for index, position in escaped]


def _text_slices(document: dict[str, Any], rendered: str) -> list[tuple[int, int, str, bool]] | None:
    """(start, end) of each text node's text in `rendered`, the document's markdown, in document order, with the
    text and whether it is escaped as a link. None where that markdown is not the slots filled with the texts."""
    skeleton = {**document, "content": _copied(document["content"])}
    texts: list[tuple[str, bool]] = []
    for node in _text_nodes(skeleton["content"]):
        texts.append((node.get("text", ""), any(mark.get("type") == "link" for mark in node.get("marks", []))))
        node["text"] = _SLOT
    if any(_SLOT in text for text, _literal in texts):
        return None
    pieces = report_document_markdown(skeleton).split(_SLOT)
    if len(pieces) != len(texts) + 1:
        return None
    slices = []
    parts = []
    position = 0
    for piece, (text, literal) in zip(pieces, texts):
        escaped = _escape_markdown_literal(text) if literal else _escape_markdown_text(text)
        position += len(piece)
        slices.append((position, position + len(escaped), text, literal))
        position += len(escaped)
        parts.extend((piece, escaped))
    parts.append(pieces[-1])
    return slices if "".join(parts) == rendered else None


def _raw_offsets(text: str, literal: bool, wanted: set[int]) -> dict[int, int]:
    """For each wanted offset in the escaped markdown of `text` that falls on a character boundary of `text`, the
    offset in `text` (see _escape_markdown_text: footnote references stay as written, a link's text is escaped
    whole). An offset inside an escape is left out."""
    if not _ESCAPABLE.search(text):
        return {offset: offset for offset in wanted if offset <= len(text)}
    notes = [] if literal else [(match.start(), match.end()) for match in NOTE_REF.finditer(text)]
    found = {0: 0} if 0 in wanted else {}
    position = 0
    note = 0
    last = max(wanted)
    for index, char in enumerate(text):
        if position >= last:
            break
        while note < len(notes) and notes[note][1] <= index:
            note += 1
        in_note = note < len(notes) and notes[note][0] <= index
        position += 2 if char in _ESCAPED and not in_note else 1
        if position in wanted:
            found[position] = index + 1
    return found


def _copied(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """New node and content objects (attrs and marks shared, never changed here), so text can be replaced."""
    return [{**node, "content": _copied(node["content"])} if isinstance(node.get("content"), list) else {**node}
            for node in nodes]


def _text_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if node.get("type") == "text":
            found.append(node)
        for child in node.get("content", []) or []:
            visit(child)

    for node in nodes:
        visit(node)
    return found


def _text_length(nodes: list[dict[str, Any]]) -> int:
    return sum(len(node.get("text", "")) for node in _text_nodes(nodes))


def _node_count(nodes: list[dict[str, Any]]) -> int:
    return sum(1 + _node_count(node.get("content", []) or []) for node in nodes)


def text_node_count(nodes: list[dict[str, Any]]) -> int:
    return len(_text_nodes(nodes))
