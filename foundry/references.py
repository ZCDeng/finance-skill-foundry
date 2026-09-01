from __future__ import annotations

import json
from typing import Any

from foundry.errors import LockRefused
from foundry.fsutil import write_text_atomic
from foundry.locking import exclusive
from foundry.tags import RESERVED_WORDS
from foundry.task import Filed, register_window_deliverable, task_for
from foundry.window import QUERYABLE, Window
from foundry.workpaper import LATE_REFERENCE, persist_schedules, schedule_reference

"""
What the analyst found outside the window.

A period runs against a locked catalog, and the fence around it says a figure
on the brief must be derivable from that catalog. It never said the brief may
contain nothing else. This month's analysis carried thirteen industry
benchmarks -- 82% collection, 106 days' turnover, a 17.4% provision rate --
copied out of a spreadsheet with no source and no date on any of them, because
the session had no way to look one up and no place to put it if it had.

So a reference is a first-class thing on the window, kept beside the questions
and rendered in its own section of the brief. What makes it safe is not that it
is scarce, it is that it is *marked*: every one carries where it came from and
when it was found, and none of them may ever wear one of the lock's words.

The difference the operator has to be able to see at a glance:

    我重算 32,195      this window's catalog produced this number
    外部引用 106 天     someone published this, here is who and when

Both belong in an analysis. Only one of them is this period's arithmetic.
"""

REQUIRED = ("id", "text", "source", "at")


def _field(entry: dict[str, Any], name: str) -> str:
    return str(entry.get(name) or "").strip()


def record_reference(
    window: Window,
    entries: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    filed: list[Filed] | None = None,
) -> None:
    """File one or more external references against this window.

    Appends rather than replacing, and refuses a duplicate id: an analyst finds
    references one at a time, over a conversation, and a call that replaced the
    file would lose the one found ten minutes ago.

    Allowed for as long as a question is: from the lock through the follow-up.
    Restricting it to ``Locked`` was the obvious first rule and the wrong one --
    the moment a leader actually asks how a figure compares to the industry is
    while they are reading the brief, not before it exists. A reference filed
    then still has to land somewhere, so it lands where every other post-brief
    answer does, on the workpaper, and the window moves to ``FollowUp``.
    """
    if window.state not in QUERYABLE:
        raise LockRefused(f"references refused in state {window.state}")
    if not isinstance(entries, list) or not entries:
        raise LockRefused("references must be a non-empty list")

    kept = load_references(window)
    seen = {item["id"] for item in kept}
    for entry in entries:
        if not isinstance(entry, dict):
            raise LockRefused("reference must be an object")
        missing = [name for name in REQUIRED if not _field(entry, name)]
        if missing:
            raise LockRefused(
                f"reference {_field(entry, 'id') or '<missing>'} needs {', '.join(missing)}; "
                "a reference without a source and a date is a number with no way back to it"
            )
        entry_id = _field(entry, "id")
        if entry_id in seen:
            raise LockRefused(f"duplicate reference id: {entry_id}")
        text = _field(entry, "text")
        # The whole point of the mark is that these two vocabularies stay apart.
        # Checked here rather than at emit time so the analyst is told which
        # reference is at fault, while it is still the one they are writing.
        borrowed = sorted(word for word in RESERVED_WORDS if word in text)
        if borrowed:
            raise LockRefused(
                f"reference {entry_id} uses {', '.join(borrowed)}, which is the brief's own "
                "mark and may not appear in cited text"
            )
        seen.add(entry_id)
        kept.append(
            {
                "id": entry_id,
                "text": text,
                "source": _field(entry, "source"),
                "at": _field(entry, "at"),
                **({"note": _field(entry, "note")} if _field(entry, "note") else {}),
            }
        )
    # Renamed off `filed`, which is now the caller's collector.
    kept_now = [entry for entry in kept if entry["id"] in {_field(item, "id") for item in entries}]
    if window.state == "Locked":
        # The brief has not been written yet, so `emit_brief` will pick these up
        # and render them itself. Nothing else to do.
        write_text_atomic(
            window.references_path, json.dumps(kept, ensure_ascii=False, indent=2) + "\n"
        )
        return

    # Past the brief, this is the only place the reference will ever be
    # rendered, and the file list and the workpaper have to move together --
    # exactly as `query.py` does for a follow-up, and for the same reason.
    task = task_for(window.store.var_root, window.task_id)
    with exclusive(window.root / ".lock"):
        write_text_atomic(
            window.references_path, json.dumps(kept, ensure_ascii=False, indent=2) + "\n"
        )
        workpaper = persist_schedules(
            window,
            [
                schedule_reference(
                    entry["id"],
                    entry["text"],
                    entry["source"],
                    entry["at"],
                    origin=LATE_REFERENCE,
                )
                for entry in kept_now
            ],
            replace=False,
        )
        window._set_state("FollowUp")
    record = register_window_deliverable(
        task,
        window_id=window.id,
        kind="workpaper",
        text=workpaper,
        cause=f"record-reference:{','.join(entry['id'] for entry in kept_now)}",
        session_id=session_id,
    )
    if filed is not None and record is not None:
        filed.append(record)


def load_references(window: Window) -> list[dict[str, Any]]:
    if not window.references_path.exists():
        return []
    loaded = json.loads(window.references_path.read_text())
    return loaded if isinstance(loaded, list) else []
