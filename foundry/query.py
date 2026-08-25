from __future__ import annotations

import json
from typing import Any

from foundry.brief import _aggregate
from foundry.catalog import quote_ident
from foundry.errors import QueryRefused
from foundry.tags import CLAIMED, OUTSIDE, RECOMPUTED
from foundry.window import QUERYABLE, Window, WindowStore


def _facts(window: Window) -> list[dict[str, Any]]:
    path = window.root / "brief_facts.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


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
    table = required_table_ids[0]
    if split_by:
        cols = [row[0] for row in target.query(f"DESCRIBE {quote_ident(table)}")]
        if split_by not in cols:
            raise QueryRefused(f"{split_by} not in {table}")
        rows = target.query(
            f"SELECT {quote_ident(split_by)}, COALESCE(SUM(amount), 0) FROM {quote_ident(table)} GROUP BY 1 ORDER BY 1"
        )
        parts = ", ".join(f"{row[0]}={row[1]}" for row in rows)
        target.followup_path.parent.mkdir(parents=True, exist_ok=True)
        with target.followup_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"text": text, "tag": OUTSIDE}, ensure_ascii=False) + "\n")
        target._set_state("FollowUp")
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}"
    value = _aggregate(target, table)
    cited = next((fact for fact in _facts(target) if fact.get("table") == table and fact.get("value") == value), None)
    if cited and not split_by:
        return f"{CLAIMED}: {text} → {value}"
    with target.followup_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"text": text, "tag": OUTSIDE, "value": value}, ensure_ascii=False) + "\n")
    target._set_state("FollowUp")
    return f"{OUTSIDE} / {RECOMPUTED}: {text} → {value}"
