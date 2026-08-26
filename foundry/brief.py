from __future__ import annotations

import json
from typing import Any

from foundry.caliber import (
    MASTER_TABLES,
    as_number,
    cut_fact_by_map,
    fact_schedule_lines,
    fact_table_id,
    format_cut,
)
from foundry.catalog import quote_ident
from foundry.errors import LockRefused
from foundry.questions import load_questions
from foundry.tags import AGREED, CLAIMED, NOT_IN_WINDOW, OUTSIDE, RECOMPUTED
from foundry.window import QUERYABLE, Window
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


def _aggregate(window: Window, table: str) -> float | int:
    names = window.table_names()
    if table not in names:
        raise LockRefused(f"table {table} not in lock")
    cols = [row[0] for row in window.query(f"DESCRIBE {quote_ident(table)}")]
    if "amount" in cols:
        value = window.query(f"SELECT COALESCE(SUM(amount), 0) FROM {quote_ident(table)}")[0][0]
    else:
        value = window.query(f"SELECT COUNT(*) FROM {quote_ident(table)}")[0][0]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def emit_brief(window: Window) -> str:
    if window.state not in QUERYABLE:
        raise LockRefused(f"brief refused in state {window.state}")
    questions = load_questions(window)
    if not questions:
        raise LockRefused("empty questions refuse brief")
    names = set(window.table_names())
    account_names = coa_names(window)
    facts: list[dict[str, Any]] = []
    schedules: list[dict[str, Any]] = []
    lines = ["# 本期结论稿", ""]
    for item in questions:
        required = item["required_table_ids"]
        missing = [table for table in required if table not in names]
        if "map" in required:
            fact = fact_table_id(required)
            if fact is None or fact not in names:
                missing = missing or (["map"] if "map" not in names else [fact or "named"])
            elif "map" not in names:
                missing = ["map"]
        if missing:
            lines.append(f"## {item['text']}")
            lines.append(f"结论: {NOT_IN_WINDOW}（缺 {', '.join(missing)}）。")
            lines.append("")
            facts.append({"id": item["id"], "tag": NOT_IN_WINDOW, "missing": missing, "schedule_id": item["id"]})
            schedules.append(schedule_missing(item["id"], item["text"], missing))
            continue
        if "map" in required:
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
        source = next((table for table in required if table not in MASTER_TABLES), required[0])
        claimed = _aggregate(window, source)
        recomputed = _aggregate(window, source)
        tag = AGREED if claimed == recomputed else RECOMPUTED
        headers, rows = _table_rows(window, source)
        lines.append(f"## {item['text']}")
        lines.append(f"结论: {source} 合计 {claimed}。{CLAIMED} {claimed}；{RECOMPUTED} {recomputed}；{tag}。")
        lines.append("")
        facts.append(
            {
                "id": item["id"],
                "table": source,
                "value": claimed,
                "tag": tag,
                "text": item["text"],
                "schedule_id": item["id"],
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
                tag=tag,
                claimed=claimed,
                recomputed=recomputed,
            )
        )
    text = "\n".join(lines).rstrip() + "\n"
    if OUTSIDE in text:
        raise LockRefused("brief must not carry 稿外追问 on in-window facts")
    window.brief_path.write_text(text)
    (window.root / "brief_facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n")
    persist_schedules(window, schedules, replace=True)
    window._set_state("Briefed")
    return text
