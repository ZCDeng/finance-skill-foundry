from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from foundry.caliber import (
    as_number,
    cut_fact_by_map,
    fact_schedule_lines,
    fact_table_id,
    format_cut,
    source_table_id,
    table_key,
)
from foundry.catalog import quote_ident
from foundry.errors import LockRefused
from foundry.fsutil import write_text_atomic
from foundry.locking import exclusive
from foundry.questions import load_questions
from foundry.tags import AGREED, CLAIMED, NOT_IN_WINDOW, OUTSIDE, RECOMPUTED
from foundry.window import Window
from foundry.workpaper import (
    coa_names,
    persist_schedules,
    schedule_from_cut,
    schedule_from_lines,
    schedule_missing,
)


def _table_rows(window: Window, table: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    headers = [row[0] for row in window.query(f"DESCRIBE {quote_ident(table)}")]
    rows = window.query(f"SELECT * FROM {quote_ident(table)}")
    return [str(h) for h in headers], rows


def _aggregate(window: Window, table: str) -> Decimal | int:
    names = window.table_names()
    if table not in names:
        raise LockRefused(f"table {table} not in lock")
    cols = [row[0] for row in window.query(f"DESCRIBE {quote_ident(table)}")]
    if "amount" in cols:
        value = window.query(f"SELECT COALESCE(SUM(amount), 0) FROM {quote_ident(table)}")[0][0]
    else:
        value = window.query(f"SELECT COUNT(*) FROM {quote_ident(table)}")[0][0]
    return value


def emit_brief(window: Window) -> str:
    """Write this window's conclusion brief, once.

    The one-shot latch is the state transition to ``Briefed``, not the presence
    of ``brief.md``. Every period output is written atomically inside the window
    lock, in dependency order -- facts, schedules, workpaper, brief, state -- so
    a window interrupted mid-emit still holds a consistent set and the next
    ``emit-brief`` recomputes it from the same locked catalog instead of
    refusing forever.
    """
    if window.state in {"Briefed", "FollowUp"} and window.brief_path.exists():
        return window.brief_path.read_text()
    if window.state != "Locked":
        raise LockRefused(f"brief refused in state {window.state}")
    questions = load_questions(window)
    if not questions:
        raise LockRefused("empty questions refuse brief")
    names = set(window.table_names())
    account_names = coa_names(window)
    facts: list[dict[str, Any]] = []
    schedules: list[dict[str, Any]] = []
    lines = ["# 本期结论稿", "", f"窗口: {window.id}", ""]
    for item in questions:
        required = item["required_table_ids"]
        # Report the operator's spelling, but decide on the catalog's id: a
        # hyphenated file name lands in DuckDB normalized, and comparing the
        # two raw would declare a table absent that is right there.
        keys = {table_key(table) for table in required}
        missing = [table for table in required if table_key(table) not in names]
        if "map" in keys:
            fact = fact_table_id(required)
            if fact is None or fact not in names:
                missing = missing or (["map"] if "map" not in names else [fact or "named"])
            elif "map" not in names:
                missing = ["map"]
        if missing:
            lines.append(f"## {item['text']}")
            lines.append(f"结论: {NOT_IN_WINDOW}（缺 {', '.join(missing)}）。")
            lines.append("")
            facts.append(
                {
                    "id": item["id"],
                    "tag": NOT_IN_WINDOW,
                    "missing": missing,
                    "schedule_id": item["id"],
                    "required_table_ids": required,
                    "text": item["text"],
                }
            )
            schedules.append(schedule_missing(item["id"], item["text"], missing))
            continue
        if "map" in keys:
            fact = fact_table_id(required)
            assert fact is not None
            fact_headers, fact_rows = _table_rows(window, fact)
            map_headers, map_rows = _table_rows(window, "map")
            cut = cut_fact_by_map(fact_headers, fact_rows, map_headers, map_rows)
            claimed = as_number(cut.claimed)
            recomputed = as_number(cut.recomputed)
            total_tag = AGREED if cut.claimed == cut.recomputed else RECOMPUTED
            lines.append(f"## {item['text']}")
            lines.append(
                f"结论: 按分析节点 {format_cut(cut)}。{RECOMPUTED}。{CLAIMED} {fact} 合计 {claimed}；{total_tag}。"
            )
            lines.append("")
            facts.append(
                {
                    "id": item["id"],
                    "table": fact,
                    "value": recomputed,
                    "claimed": claimed,
                    "cut": "map",
                    "nodes": [{"id": node, "name": name, "amount": as_number(amount)} for node, name, amount in cut.nodes],
                    "unmapped": as_number(cut.unmapped),
                    "conflict": as_number(cut.conflict),
                    "tag": RECOMPUTED,
                    "text": item["text"],
                    "schedule_id": item["id"],
                    "required_table_ids": required,
                }
            )
            schedules.append(
                schedule_from_cut(
                    item_id=item["id"],
                    text=item["text"],
                    table=fact,
                    cut=cut,
                    names=account_names,
                    origin="brief",
                    tag=RECOMPUTED,
                )
            )
            continue
        source = source_table_id(required)
        total = _aggregate(window, source)
        headers, rows = _table_rows(window, source)
        lines.append(f"## {item['text']}")
        lines.append(f"结论: {source} 锁库汇总 {total}。{RECOMPUTED} {total}。")
        lines.append("")
        facts.append(
            {
                "id": item["id"],
                "table": source,
                "value": as_number(total),
                "tag": RECOMPUTED,
                "text": item["text"],
                "schedule_id": item["id"],
                "required_table_ids": required,
            }
        )
        schedules.append(
            schedule_from_lines(
                item_id=item["id"],
                text=item["text"],
                table=source,
                lines=fact_schedule_lines(headers, rows),
                names=account_names,
                origin="brief",
                tag=RECOMPUTED,
                claimed=None,
                recomputed=total,
            )
        )
    text = "\n".join(lines).rstrip() + "\n"
    if OUTSIDE in text:
        raise LockRefused(f"brief must not carry {OUTSIDE} on in-window facts")
    with exclusive(window.root / ".lock"):
        if window.state != "Locked":
            raise LockRefused(f"brief refused in state {window.state}")
        write_text_atomic(
            window.root / "brief_facts.json",
            json.dumps(facts, ensure_ascii=False, indent=2) + "\n",
        )
        persist_schedules(window, schedules, replace=True)
        write_text_atomic(window.brief_path, text)
        window._set_state("Briefed")
    return text
