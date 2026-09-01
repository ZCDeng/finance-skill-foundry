from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from foundry.caliber import CutLine, MapCut, as_number, format_aux
from foundry.fsutil import write_text_atomic
from foundry.tags import AGREED, CLAIMED, EXTERNAL, NOT_IN_WINDOW, OUTSIDE, RECOMPUTED
from foundry.window import Window


def _display_number(value: Decimal | float | int | str) -> int | str:
    if isinstance(value, str):
        return as_number(Decimal(value))
    return as_number(value)


def coa_names(window: Window) -> dict[str, str]:
    if "coa" not in window.table_names():
        return {}
    rows = window.query("SELECT account_code, account_name FROM coa")
    return {str(code).strip(): str(name or "").strip() for code, name in rows}


def line_dict(line: CutLine, names: dict[str, str]) -> dict[str, Any]:
    return {
        "node_id": line.node_id,
        "node_name": line.node_name,
        "account": line.account,
        "account_name": names.get(line.account, ""),
        "dims": [list(pair) for pair in line.dims],
        "aux": format_aux(line.dims),
        "amount": as_number(line.amount),
        "match": line.match,
        "conflict_nodes": list(line.conflict_nodes),
    }


def _item(
    *,
    item_id: str,
    text: str,
    tag: str,
    origin: str,
    table: str | None = None,
    cut: str | None = None,
    split_by: str | None = None,
    claimed: Decimal | float | int | str | None = None,
    recomputed: Decimal | float | int | str | None = None,
    unmapped: Decimal | float | int | str = 0,
    conflict: Decimal | float | int | str = 0,
    nodes: list[dict[str, Any]] | None = None,
    lines: list[dict[str, Any]] | None = None,
    missing: list[str] | None = None,
    reference: dict[str, str] | None = None,
) -> dict[str, Any]:
    tie = AGREED if claimed is not None and recomputed is not None and claimed == recomputed else None
    return {
        "id": item_id,
        "schedule_id": item_id,
        **({"reference": reference} if reference else {}),
        "text": text,
        "tag": tag,
        "origin": origin,
        "table": table,
        "cut": cut,
        "split_by": split_by,
        "claimed": _display_number(claimed) if claimed is not None else None,
        "recomputed": _display_number(recomputed) if recomputed is not None else None,
        "unmapped": _display_number(unmapped) if unmapped else 0,
        "conflict": _display_number(conflict) if conflict else 0,
        "tie": tie,
        "nodes": nodes or [],
        "lines": lines or [],
        "missing": missing or [],
    }


def schedule_missing(item_id: str, text: str, missing: list[str]) -> dict[str, Any]:
    return _item(item_id=item_id, text=text, tag=NOT_IN_WINDOW, origin="brief", missing=missing)


LATE_REFERENCE = "late-reference"


def schedule_reference(
    item_id: str, text: str, source: str, at: str, *, origin: str = "brief"
) -> dict[str, Any]:
    """A reference on the workpaper, carrying the two things that place it.

    It has no lines, because there is no arithmetic to show. What it has is a
    source and a date, and those are exactly what a figure copied out of a
    spreadsheet was missing.

    ``origin`` separates the two moments it can arrive. Filed before the brief
    it is part of the brief; filed after, it is not, and a workpaper that said
    ``来源: brief`` about it would be claiming the leader read it when they did
    not. It is still not a follow-up -- nothing was recomputed -- so it takes
    neither label.
    """
    return _item(
        item_id=item_id,
        text=text,
        tag=EXTERNAL,
        origin=origin,
        reference={"source": source, "at": at},
    )


def schedule_from_cut(
    *,
    item_id: str,
    text: str,
    table: str,
    cut: MapCut,
    names: dict[str, str],
    origin: str,
    tag: str,
) -> dict[str, Any]:
    return _item(
        item_id=item_id,
        text=text,
        tag=tag,
        origin=origin,
        table=table,
        cut="map",
        claimed=as_number(cut.claimed),
        recomputed=as_number(cut.recomputed),
        unmapped=cut.unmapped,
        conflict=cut.conflict,
        nodes=[{"id": node, "name": name, "amount": as_number(amount)} for node, name, amount in cut.nodes],
        lines=[line_dict(line, names) for line in cut.lines],
    )


def schedule_from_lines(
    *,
    item_id: str,
    text: str,
    table: str,
    lines: list[CutLine],
    names: dict[str, str],
    origin: str,
    tag: str,
    claimed: Decimal | float | int | str | None,
    recomputed: Decimal | float | int | str | None = None,
    split_by: str | None = None,
) -> dict[str, Any]:
    recomputed = claimed if recomputed is None else recomputed
    return _item(
        item_id=item_id,
        text=text,
        tag=tag,
        origin=origin,
        table=table,
        split_by=split_by,
        claimed=claimed,
        recomputed=recomputed,
        lines=[line_dict(line, names) for line in lines],
    )


def load_schedules(window: Window) -> dict[str, Any]:
    path = window.schedules_path
    if not path.exists():
        return {"window_id": window.id, "hashes": window.hashes(), "items": []}
    return json.loads(path.read_text())


def next_followup_id(payload: dict[str, Any]) -> str:
    count = sum(1 for item in payload.get("items", []) if item.get("origin") == "followup")
    return f"followup-{count + 1}"


def persist_schedules(window: Window, items: list[dict[str, Any]], *, replace: bool) -> str:
    """Write schedules.json and re-render workpaper.md from it.

    The caller must already hold ``exclusive(window.root / ".lock")``: a
    read-modify-write of the item list is not safe on its own, and the follow-up
    id this appends under was allocated from the same read. ``schedules.json``
    is the dependency and goes first, so an interrupted pair leaves a workpaper
    that is behind rather than a workpaper claiming an item the schedule list
    never recorded.
    """
    if replace:
        payload = {"window_id": window.id, "hashes": window.hashes(), "items": items}
    else:
        payload = load_schedules(window)
        payload["window_id"] = window.id
        payload["hashes"] = payload.get("hashes") or window.hashes()
        payload["items"] = list(payload.get("items") or []) + items
    write_text_atomic(window.schedules_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    rendered = render_workpaper(payload)
    write_text_atomic(window.workpaper_path, rendered)
    # Returned so the caller can register this exact text as a deliverable
    # version without re-reading the file it just wrote.
    return rendered


def _aux_part(hashes: dict[str, Any]) -> str | None:
    """Render the aux digest, saying so when aux was derived from units.

    A units-derived aux has no aux file behind it, so the only digest available
    is the loaded table's. Printing that as plain ``aux=`` sends an auditor
    looking for a file that does not exist and reads exactly like the aux-file
    case. Two markers can say so: ``aux_derived_from``, which only a manifest
    written after that fix carries, and ``aux_kind``, which ``Window.hashes()``
    derives from the absence of a source digest and so is right for a window
    locked by an older build too. Read both, and fall back to the plain label
    only when neither is there.
    """
    value: Any = hashes.get("aux")
    derived: Any = hashes.get("aux_derived_from") or hashes.get("aux_kind") == "derived"
    if isinstance(value, dict):
        derived = value.get("derived_from") or (not value.get("source_hash")) or derived
        value = value.get("source_hash") or value.get("loaded_hash") or value.get("hash")
    if not value:
        value = hashes.get("aux_loaded")
        if value:
            derived = derived or "units"
    if not value:
        return None
    return f"aux(derived)={value}" if derived else f"aux={value}"


def _hash_line(hashes: dict[str, Any]) -> str:
    named = hashes.get("named") or {}
    parts = [f"coa={hashes.get('coa') or '—'}", f"map={hashes.get('map') or '—'}"]
    if hashes.get("units"):
        parts.append(f"units={hashes['units']}")
    aux_part = _aux_part(hashes)
    if aux_part:
        parts.append(aux_part)
    for table, digest in named.items():
        parts.append(f"{table}={digest or '—'}")
    return " ".join(parts)


def _account_cell(line: dict[str, Any]) -> str:
    code = str(line.get("account") or "")
    name = str(line.get("account_name") or "")
    if code and name:
        return f"{code} {name}"
    return code or "—"


def _match_cell(line: dict[str, Any]) -> str:
    match = str(line.get("match") or "")
    conflicts = line.get("conflict_nodes") or []
    if conflicts:
        return f"{match} ({', '.join(str(item) for item in conflicts)})"
    return match or "—"


def render_workpaper(payload: dict[str, Any]) -> str:
    lines = [
        "# 本期计算底稿",
        "",
        f"窗口: {payload.get('window_id') or '—'}",
        f"锁哈希: {_hash_line(payload.get('hashes') or {})}",
        "本文件由锁库算出，不是模型起草。归档 Excel 不是底稿。",
        "",
    ]
    for item in payload.get("items") or []:
        lines.append(f"## {item.get('id')} · {item.get('text')}")
        lines.append("")
        origin = {"followup": OUTSIDE, LATE_REFERENCE: "稿外补录"}.get(
            str(item.get("origin")), "brief"
        )
        lines.append(f"来源: {origin}")
        tag = item.get("tag") or ""
        if item.get("origin") == "followup" and OUTSIDE not in tag:
            tag = f"{OUTSIDE} / {tag}" if tag else OUTSIDE
        lines.append(f"标签: {tag}")
        if item.get("reference"):
            # No arithmetic to show, so the source and the date are the whole
            # of what makes this line checkable.
            lines.append(f"来源出处: {item['reference'].get('source') or '—'}")
            lines.append(f"查到于: {item['reference'].get('at') or '—'}")
            lines.append(f"{EXTERNAL}，不出自本窗口的锁库，无附表行。")
            lines.append("")
            continue
        if item.get("missing"):
            lines.append(f"缺: {', '.join(item['missing'])}")
            lines.append("无附表行。")
            lines.append("")
            continue
        if item.get("table"):
            lines.append(f"表: {item['table']}")
        if item.get("claimed") is not None:
            lines.append(f"{CLAIMED}: {item['claimed']}")
        if item.get("recomputed") is not None:
            lines.append(f"{RECOMPUTED}: {item['recomputed']}")
        if item.get("unmapped"):
            lines.append(f"未对照: {item['unmapped']}")
        if item.get("conflict"):
            lines.append(f"冲突: {item['conflict']}")
        if item.get("tie"):
            lines.append(f"勾稽: {item['tie']}")
        rows = item.get("lines") or []
        if not rows:
            lines.append("无附表行。")
            lines.append("")
            continue
        show_node = any(row.get("node_id") for row in rows)
        header = "| 分析节点 | 科目 | 辅助 | 金额 | 对照 |" if show_node else "| 科目 | 辅助 | 金额 | 对照 |"
        rule = "| --- | --- | --- | --- | --- |" if show_node else "| --- | --- | --- | --- |"
        lines.append("")
        lines.append(header)
        lines.append(rule)
        for row in rows:
            account = _account_cell(row)
            aux = row.get("aux") or "—"
            amount = row.get("amount")
            match = _match_cell(row)
            if show_node:
                node = row.get("node_id") or "—"
                if node == "__unmapped__":
                    node = "未对照"
                elif node == "__conflict__":
                    node = "冲突"
                lines.append(f"| {node} | {account} | {aux} | {amount} | {match} |")
            else:
                lines.append(f"| {account} | {aux} | {amount} | {match} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
