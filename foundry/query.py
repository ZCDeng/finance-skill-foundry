from __future__ import annotations

import json
from functools import partial
from typing import Any, Callable

from foundry.brief import _aggregate, _table_rows
from foundry.caliber import (
    undefined_total,
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
from foundry.task import Filed, register_window_deliverable, task_for
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
    """The figures on this window's brief that the locked catalog produced.

    ``brief_facts.json`` now holds two kinds of record, and this is where that
    stops being true: everything past this line is a figure this window derived.
    Both lookups below decide whether a follow-up is quoting the brief (报表声称)
    or going outside it (稿外追问), and a reference can answer neither -- it was
    never derived here, so it can neither be quoted as this window's arithmetic
    nor be the thing a recomputation matches.

    Today both lookups would also miss a reference by structure, since neither a
    ``required_table_ids`` match nor a map-cut match can succeed against a
    record that carries no tables. That is an accident of what a reference
    happens not to have, not a rule, and it is not what the next lookup written
    against this list will be able to rely on. The rule is here.

    Facts written before this field existed have no ``basis`` and are treated as
    what they were: lock figures.
    """
    path = window.root / "brief_facts.json"
    if not path.exists():
        return []
    loaded = json.loads(path.read_text())
    return [fact for fact in loaded if fact.get("basis", "lock") == "lock"]


def _record_followup(
    window: Window,
    payload: dict[str, Any],
    build_schedule: Callable[..., dict[str, Any]] | None = None,
    *,
    session_id: str | None = None,
    brief_sha: str | None = None,
    filed: list[Filed] | None = None,
) -> None:
    """Record one follow-up as a single locked unit.

    Allocating the follow-up id, appending the audit line, adding the schedule
    item and re-rendering the workpaper are one transaction. Run unlocked, two
    simultaneous follow-ups both read the same schedule list, both derive
    ``followup-1`` and the second write drops the first item -- the audit log
    and the tickable workpaper then disagree about what was asked.
    """
    task = task_for(window.store.var_root, window.task_id)
    # `brief_sha` is the deliverable version the leader was actually holding when
    # they asked. The window id alone does not say that: a window has one brief
    # but several exports of it, and an answer has to be traceable to the sheet
    # of paper the question was asked against.
    #
    # There is no separate pointer to the leader's own wording. `session_id` is
    # that pointer -- the verbatim lives once on the task's session row, and a
    # second copy per follow-up would be a second thing to keep true.
    payload = {
        **payload,
        "task_id": None if task is None else task.id,
        "session_id": session_id,
        "brief_sha": brief_sha,
    }
    workpaper = None
    schedule_id = None
    with exclusive(window.root / ".lock"):
        schedule = None
        if build_schedule is not None:
            schedule = build_schedule(item_id=next_followup_id(load_schedules(window)))
            schedule_id = schedule.get("id")
        window.followup_path.parent.mkdir(parents=True, exist_ok=True)
        with window.followup_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")
        if schedule is not None:
            workpaper = persist_schedules(window, [schedule], replace=False)
        window._set_state("FollowUp")
    if workpaper is not None:
        # The cause names the schedule this answer added, so a workpaper version
        # traces back to the one follow-up that grew it. Without it the timeline
        # says the file changed and never says what changed it.
        record = register_window_deliverable(
            task,
            window_id=window.id,
            kind="workpaper",
            text=workpaper,
            cause=f"query-locked:{schedule_id}" if schedule_id else "query-locked",
            session_id=session_id,
        )
        if filed is not None and record is not None:
            filed.append(record)


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
    session_id: str | None = None,
    brief_sha: str | None = None,
    filed: list[Filed] | None = None,
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
            session_id=session_id,
            filed=filed,
            brief_sha=brief_sha,
        )
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}{_window_note(target)}"
    table = _source_table(required_table_ids)
    if split_by:
        cols = [row[0] for row in target.query(f"DESCRIBE {quote_ident(table)}")]
        if "amount" not in cols:
            raise QueryRefused(f"{table} has no amount")
        if split_by not in cols:
            raise QueryRefused(f"{split_by} not in {table}")
        headers, fact_rows = _table_rows(target, table)
        # A cut by something other than the account still adds unlike measures
        # inside each part. `undefined_total` lets `account_code` through,
        # because that cut is what separates them.
        problem = undefined_total(table, headers, fact_rows, split_by=split_by)
        if problem:
            raise QueryRefused(problem)
        rows = target.query(
            f"SELECT {quote_ident(split_by)}, COALESCE(SUM(amount), 0) FROM {quote_ident(table)} GROUP BY 1 ORDER BY 1"
        )
        parts = ", ".join(f"{row[0]}={row[1]}" for row in rows)
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
            session_id=session_id,
            filed=filed,
            brief_sha=brief_sha,
        )
        return f"{OUTSIDE} / {RECOMPUTED}: {text} → {parts}{_window_note(target)}"
    headers, fact_rows = _table_rows(target, table)
    problem = undefined_total(table, headers, fact_rows)
    if problem:
        raise QueryRefused(problem)
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
        session_id=session_id,
        filed=filed,
        brief_sha=brief_sha,
    )
    return f"{OUTSIDE} / {RECOMPUTED}: {text} → {value}{_window_note(target)}"
