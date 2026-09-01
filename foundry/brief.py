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
    undefined_total,
)
from foundry.catalog import quote_ident
from foundry.errors import LockRefused
from foundry.fsutil import write_text_atomic
from foundry.locking import exclusive
from foundry.questions import load_questions
from foundry.references import load_references
from foundry.task import Filed, register_window_deliverable, task_for
from foundry.tags import AGREED, CLAIMED, EXTERNAL, NOT_IN_WINDOW, OUTSIDE, RECOMPUTED
from foundry.window import Window
from foundry.workpaper import (
    coa_names,
    persist_schedules,
    schedule_from_cut,
    schedule_from_lines,
    schedule_missing,
    schedule_reference,
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


def _register_period_outputs(
    window: Window, text: str, session_id: str | None, filed: list[Filed] | None = None
) -> None:
    """File the brief and the workpaper as deliverable versions.

    Runs outside the window lock and after the writes, so a task store that
    cannot be written does not leave a Briefed window with no brief on disk.
    Registration is keyed on the bytes, so the re-entrant call below re-files a
    version that an interrupted run never got to record, and files nothing when
    it already did.
    """
    task = task_for(window.store.var_root, window.task_id)
    if task is None:
        # No timeline to hang them on, so nothing was filed. The receipt says
        # so by staying empty, which is not the same claim as "nothing was
        # produced" -- the brief is on disk either way.
        return
    written = [
        register_window_deliverable(
            task,
            window_id=window.id,
            kind="brief",
            text=text,
            cause="emit-brief",
            session_id=session_id,
        )
    ]
    if window.workpaper_path.exists():
        written.append(
            register_window_deliverable(
                task,
                window_id=window.id,
                kind="workpaper",
                text=window.workpaper_path.read_text(encoding="utf-8"),
                cause="emit-brief",
                session_id=session_id,
            )
        )
    if filed is not None:
        filed.extend(record for record in written if record is not None)


def emit_brief(
    window: Window, *, session_id: str | None = None, filed: list[Filed] | None = None
) -> str:
    """Write this window's conclusion brief, once.

    The one-shot latch is the state transition to ``Briefed``, not the presence
    of ``brief.md``. Every period output is written atomically inside the window
    lock, in dependency order -- facts, schedules, workpaper, brief, state -- so
    a window interrupted mid-emit still holds a consistent set and the next
    ``emit-brief`` recomputes it from the same locked catalog instead of
    refusing forever.

    ``filed`` is a collector, not a return value, and that is a deliberate
    shape. The text is what every one of this function's callers wants; the
    deliverable versions are what one of them wants, and turning the return
    into a pair to serve it would have rewritten ninety-odd call sites to reach
    through a tuple for the thing they already had.
    """
    if window.state in {"Briefed", "FollowUp"} and window.brief_path.exists():
        text = window.brief_path.read_text()
        _register_period_outputs(window, text, session_id, filed)
        return text
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
                    "basis": "lock",
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
                    "basis": "lock",
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
        headers, rows = _table_rows(window, source)
        # Read before summing. A table holding several measures has no
        # whole-table total, and answering with one anyway is how a brief comes
        # to carry a figure nobody can derive.
        problem = undefined_total(source, headers, rows)
        if problem:
            raise LockRefused(f"question {item['id']}: {problem}")
        total = _aggregate(window, source)
        lines.append(f"## {item['text']}")
        lines.append(f"结论: {source} 锁库汇总 {total}。{RECOMPUTED} {total}。")
        lines.append("")
        facts.append(
            {
                "id": item["id"],
                "basis": "lock",
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
    """
    What the analyst found outside the window, kept apart from what the window
    computed.

    Its own section, after the questions, so the reader never has to work out
    which half of a paragraph came from the lock. Every line carries its source
    and the date it was found, and `record_reference` has already refused any
    that tried to wear one of the lock's words.
    """
    references = load_references(window)
    if references:
        lines.append(f"## {EXTERNAL}")
        lines.append("")
        lines.append("以下不出自本窗口的锁库，是查到的外部材料，各自带出处与查到日期。")
        lines.append("")
        for entry in references:
            lines.append(f"- {entry['text']}（{entry['source']} · {entry['at']}）")
            facts.append(
                {
                    "id": entry["id"],
                    "basis": "external",
                    "tag": EXTERNAL,
                    "text": entry["text"],
                    "source": entry["source"],
                    "at": entry["at"],
                    "schedule_id": entry["id"],
                }
            )
            schedules.append(
                schedule_reference(entry["id"], entry["text"], entry["source"], entry["at"])
            )
        lines.append("")

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
    _register_period_outputs(window, text, session_id, filed)
    return text
