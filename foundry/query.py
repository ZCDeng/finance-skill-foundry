from __future__ import annotations

import json
from typing import Any

from foundry.brief import _aggregate, _table_rows
from foundry.caliber import (
    MAP_SPLITS,
    cut_fact_by_map,
    fact_schedule_lines,
    fact_split_lines,
    fact_table_id,
    format_cut,
)
from foundry.catalog import quote_ident
from foundry.errors import LockRefused, QueryRefused
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


def _facts(window: Window) -> list[dict[str, Any]]:
    path = window.root / "brief_facts.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _append_followup(window: Window, payload: dict[str, Any], schedule: dict[str, Any] | None = None) -> None:
    window.followup_path.parent.mkdir(parents=True, exist_ok=True)
    with window.followup_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    if schedule is not None:
        persist_schedules(window, [schedule], replace=False)
    window._set_state("FollowUp")


def query_locked(
    window: Window,
    text: str,
    *,
    required_table_ids: list[str],
    split_by: str | None = None,
    brief_window_id: str | None = None,
) -> str:
    target = window
    if brief_window_id:
        target = WindowStore(window.store.var_root).get(brief_window_id)
    if target.state not in QUERYABLE:
        raise QueryRefused(f"query refused in state {target.state}")
    names = set(target.table_names())
    missing = [table for table in required_table_ids if table not in names]
    if missing:
        raise QueryRefused(f"table not in this window: {missing}")
    account_names = coa_names(target)
    if split_by in MAP_SPLITS:
        if "map" not in names:
            raise QueryRefused("table not in this window: ['map']")
        fact = fact_table_id(required_table_ids) or required_table_ids[0]
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
            ),
            None,
        )
        if cited:
            return f"{RECOMPUTED}: {text} → {parts}"
        schedule = schedule_from_cut(
            item_id=next_followup_id(load_schedules(target)),
            text=text,
            table=fact,
            cut=cut,
            names=account_names,
            origin="followup",
            tag=f"{OUTSIDE} / {RECOMPUTED}",
        )
        _append_followup(target, {"text": text, "tag": OUTSIDE, "cut": "map", "parts": parts}, schedule)
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}"
    table = required_table_ids[0]
    if split_by:
        cols = [row[0] for row in target.query(f"DESCRIBE {quote_ident(table)}")]
        if split_by not in cols:
            raise QueryRefused(f"{split_by} not in {table}")
        rows = target.query(
            f"SELECT {quote_ident(split_by)}, COALESCE(SUM(amount), 0) FROM {quote_ident(table)} GROUP BY 1 ORDER BY 1"
        )
        parts = ", ".join(f"{row[0]}={row[1]}" for row in rows)
        headers, fact_rows = _table_rows(target, table)
        claimed = _aggregate(target, table)
        schedule = schedule_from_lines(
            item_id=next_followup_id(load_schedules(target)),
            text=text,
            table=table,
            lines=fact_split_lines(headers, fact_rows, split_by),
            names=account_names,
            origin="followup",
            tag=f"{OUTSIDE} / {RECOMPUTED}",
            claimed=claimed,
            split_by=split_by,
        )
        _append_followup(target, {"text": text, "tag": OUTSIDE}, schedule)
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}"
    value = _aggregate(target, table)
    cited = next(
        (
            fact
            for fact in _facts(target)
            if fact.get("table") == table and fact.get("value") == value and fact.get("cut") != "map"
        ),
        None,
    )
    if cited:
        return f"{CLAIMED}: {text} → {value}"
    headers, fact_rows = _table_rows(target, table)
    schedule = schedule_from_lines(
        item_id=next_followup_id(load_schedules(target)),
        text=text,
        table=table,
        lines=fact_schedule_lines(headers, fact_rows),
        names=account_names,
        origin="followup",
        tag=f"{OUTSIDE} / {RECOMPUTED}",
        claimed=value,
    )
    _append_followup(target, {"text": text, "tag": OUTSIDE, "value": value}, schedule)
    return f"{OUTSIDE} / {RECOMPUTED}: {text} → {value}"
