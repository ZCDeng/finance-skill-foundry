from __future__ import annotations

import json
from typing import Any

from foundry.catalog import quote_ident
from foundry.errors import LockRefused
from foundry.questions import load_questions
from foundry.tags import AGREED, CLAIMED, NOT_IN_WINDOW, OUTSIDE, RECOMPUTED
from foundry.window import QUERYABLE, Window


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
    facts: list[dict[str, Any]] = []
    lines = ["# 本期结论稿", ""]
    for item in questions:
        required = item["required_table_ids"]
        missing = [table for table in required if table not in names]
        if missing:
            lines.append(f"## {item['text']}")
            lines.append(f"结论: {NOT_IN_WINDOW}（缺 {', '.join(missing)}）。")
            lines.append("")
            facts.append({"id": item["id"], "tag": NOT_IN_WINDOW, "missing": missing})
            continue
        claimed = _aggregate(window, required[0])
        recomputed = _aggregate(window, required[0])
        tag = AGREED if claimed == recomputed else RECOMPUTED
        lines.append(f"## {item['text']}")
        lines.append(f"结论: {required[0]} 合计 {claimed}。{CLAIMED} {claimed}；{RECOMPUTED} {recomputed}；{tag}。")
        lines.append("")
        facts.append(
            {
                "id": item["id"],
                "table": required[0],
                "value": claimed,
                "tag": tag,
                "text": item["text"],
            }
        )
    text = "\n".join(lines).rstrip() + "\n"
    if OUTSIDE in text:
        raise LockRefused("brief must not carry 稿外追问 on in-window facts")
    window.brief_path.write_text(text)
    (window.root / "brief_facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n")
    window._set_state("Briefed")
    return text
