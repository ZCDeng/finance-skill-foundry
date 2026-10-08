"""How a task says it is a practice task, read without importing the stores that build one.

A practice task carries ``sample-task.json`` beside its metadata. The marker, never the title,
is what makes it one: a real task that happens to share the title is a real task. Readers here
are deliberately light, because the structure template shelf asks this question on every
proposal and must not pull the sample builder (and its workbook writer) in to do so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MARKER_NAME = "sample-task.json"


def marker_path(task) -> Path:
    return task.meta_path.parent / MARKER_NAME


def read_marker(task) -> dict[str, Any] | None:
    """The task's sample marker, or None for a real task. A marker that cannot be read still
    marks the task as a sample: a damaged marker must not let a practice task pass for a real one."""
    path = marker_path(task)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sample": True}
    return value if isinstance(value, dict) else {"sample": True}


def is_sample(task) -> bool:
    return read_marker(task) is not None


def uses_sample_shelf(task) -> bool:
    """Whether the task's confirmed structures go to the practice template shelf. The 6 月 practice
    task from before the bundled pack (its marker names a dataset, not a pack) kept writing to the
    real shelf, where its templates already are; moving it now would leave those templates live and
    out of its reach, so it stays where it was until it is removed."""
    marker = read_marker(task)
    if marker is None:
        return False
    return not ("dataset" in marker and "pack" not in marker)
