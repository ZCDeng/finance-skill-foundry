from __future__ import annotations

import json
from functools import partial
from typing import Any, Callable

from foundry.brief import _aggregate, _table_rows
from foundry.caliber import (
    MAP_SPLITS,
    cut_fact_by_map,
    fact_schedule_lines,
    fact_split_lines,
    format_cut,
    source_table_id,
    table_key,
    as_number,
)
from foundry.catalog import quote_ident
from foundry.errors import LockRefused, QueryRefused
from foundry.locking import exclusive
from foundry.tags import CLAIMED, OUTSIDE, RECOMPUTED
from foundry.window import QUERYABLE, Window, WindowStore
from foundry.workpaper import (
    coa_names,
    load_schedules,
    next_followup_id,
    persist_schedules,
    schedule_from_cut,
    schedule_from_lines,
)


def _question_key(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _window_note(window: Window) -> str:
    """Name the window an answer came from.

    A follow-up may resolve to the brief's window or to the store's current one,
    and a re-import moves `current` to a brand-new window. Without the id in the
    answer a leader cannot tell which period they were just quoted. It closes the
    line, after the value, so a reader parses the tag and the number as before.
    """
    return f"（窗口: {window.id}）"


def _json_default(value: Any) -> Any:
    try:
        return as_number(value)
    except Exception as exc:
        raise TypeError from exc


def _facts(window: Window) -> list[dict[str, Any]]:
    path = window.root / "brief_facts.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _record_followup(
    window: Window,
    payload: dict[str, Any],
    build_schedule: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Record one follow-up as a single locked unit.

    Allocating the follow-up id, appending the audit line, adding the schedule
    item and re-rendering the workpaper are one transaction. Run unlocked, two
    simultaneous follow-ups both read the same schedule list, both derive
    ``followup-1`` and the second write drops the first item -- the audit log
    and the tickable workpaper then disagree about what was asked.
    """
    with exclusive(window.root / ".lock"):
        schedule = None
        if build_schedule is not None:
            schedule = build_schedule(item_id=next_followup_id(load_schedules(window)))
        window.followup_path.parent.mkdir(parents=True, exist_ok=True)
        with window.followup_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")
        if schedule is not None:
            persist_schedules(window, [schedule], replace=False)
        window._set_state("FollowUp")


def _same_required(fact: dict[str, Any], required_table_ids: list[str]) -> bool:
    # Both sides are spelled by hand -- one in questions.json, one on the
    # command line -- so compare the ids the catalog actually holds, not the
    # two spellings.
    recorded = {table_key(str(item)) for item in fact.get("required_table_ids") or []}
    return recorded == {table_key(table) for table in required_table_ids}


def _source_table(required_table_ids: list[str]) -> str:
    try:
        return source_table_id(required_table_ids)
    except LockRefused as exc:
        raise QueryRefused(str(exc)) from exc


def query_locked(
    window: Window,
    text: str,
    *,
    required_table_ids: list[str],
    split_by: str | None = None,
    brief_window_id: str | None = None,
    question_id: str | None = None,
) -> str:
    if not required_table_ids:
        raise QueryRefused("required_table_ids is required")
    required_table_ids = [str(table).strip() for table in required_table_ids if str(table).strip()]
    if not required_table_ids:
        raise QueryRefused("required_table_ids is required")
    citation_table_ids = list(required_table_ids)
    if split_by in MAP_SPLITS and "map" not in citation_table_ids:
        citation_table_ids.append("map")
    target = window
    if brief_window_id:
        target = WindowStore(window.store.var_root).get(brief_window_id)
    if target.state not in QUERYABLE:
        raise QueryRefused(f"query refused in state {target.state}")
    names = set(target.table_names())
    missing = [table for table in required_table_ids if table_key(table) not in names]
    if missing:
        raise QueryRefused(f"table not in this window: {missing}")
    account_names = coa_names(target)
    if split_by in MAP_SPLITS:
        if "map" not in names:
            raise QueryRefused("table not in this window: ['map']")
        fact = _source_table(required_table_ids)
        if fact not in names:
            raise QueryRefused(f"table not in this window: ['{fact}']")
        try:
            cut = cut_fact_by_map(*_table_rows(target, fact), *_table_rows(target, "map"))
        except LockRefused as exc:
            raise QueryRefused(str(exc)) from exc
        parts = format_cut(cut)
        cited = next(
            (
                fact_row
                for fact_row in _facts(target)
                if fact_row.get("cut") == "map" and fact_row.get("table") == fact
                and (
                    (question_id and fact_row.get("id") == question_id)
                    or (not question_id and _question_key(str(fact_row.get("text") or "")) == _question_key(text))
                )
                and _same_required(fact_row, citation_table_ids)
            ),
            None,
        )
        if cited:
            return f"{RECOMPUTED}: {text} → {parts}{_window_note(target)}"
        _record_followup(
            target,
            {"text": text, "tag": OUTSIDE, "cut": "map", "parts": parts},
            partial(
                schedule_from_cut,
                text=text,
                table=fact,
                cut=cut,
                names=account_names,
                origin="followup",
                tag=f"{OUTSIDE} / {RECOMPUTED}",
            ),
        )
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}{_window_note(target)}"
    table = _source_table(required_table_ids)
    if split_by:
        cols = [row[0] for row in target.query(f"DESCRIBE {quote_ident(table)}")]
        if "amount" not in cols:
            raise QueryRefused(f"{table} has no amount")
        if split_by not in cols:
            raise QueryRefused(f"{split_by} not in {table}")
        rows = target.query(
            f"SELECT {quote_ident(split_by)}, COALESCE(SUM(amount), 0) FROM {quote_ident(table)} GROUP BY 1 ORDER BY 1"
        )
        parts = ", ".join(f"{row[0]}={row[1]}" for row in rows)
        headers, fact_rows = _table_rows(target, table)
        claimed = _aggregate(target, table)
        _record_followup(
            target,
            {"text": text, "tag": OUTSIDE},
            partial(
                schedule_from_lines,
                text=text,
                table=table,
                lines=fact_split_lines(headers, fact_rows, split_by),
                names=account_names,
                origin="followup",
                tag=f"{OUTSIDE} / {RECOMPUTED}",
                claimed=None,
                recomputed=claimed,
                split_by=split_by,
            ),
        )
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}{_window_note(target)}"
    value = _aggregate(target, table)
    cited = next(
        (
            fact
            for fact in _facts(target)
            if fact.get("table") == table and fact.get("value") == as_number(value) and fact.get("cut") != "map"
            and (
                (question_id and fact.get("id") == question_id)
                or (not question_id and _question_key(str(fact.get("text") or "")) == _question_key(text))
            )
            and _same_required(fact, citation_table_ids)
        ),
        None,
    )
    if cited:
        return f"{CLAIMED}: {text} → {value}{_window_note(target)}"
    headers, fact_rows = _table_rows(target, table)
    _record_followup(
        target,
        {"text": text, "tag": OUTSIDE, "value": as_number(value)},
        partial(
            schedule_from_lines,
            text=text,
            table=table,
            lines=fact_schedule_lines(headers, fact_rows),
            names=account_names,
            origin="followup",
            tag=f"{OUTSIDE} / {RECOMPUTED}",
            claimed=None,
            recomputed=value,
        ),
    )
    return f"{OUTSIDE} / {RECOMPUTED}: {text} → {value}{_window_note(target)}"
