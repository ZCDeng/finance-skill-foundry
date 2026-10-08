"""Practice tasks built from the bundled 华宸物业 example pack, so a first run never touches real books.

The pack is a set of fictitious workbooks and documents in ``foundry/resources/demo_pack`` (written by
``tests/fixtures/demo_pack/build_demo.py``; ``pack.json`` lists them and carries the pack version).
Its differences are planted on purpose: every analysis the app offers has something real to show.

``create_sample_task`` makes (or reuses) the practice task for August: the files are filed as
datasets and read exactly as a real import is, so the structure, the controls and everything after
are still the manager's to confirm. ``create_next_month_sample`` makes the September task the guide
uses to show a remembered structure applying itself. Nothing here reads or writes any other task, and
a practice task's confirmed structures go to its own template shelf (see structure_templates).

Each practice task carries a marker (sample_marker) naming the pack, its version and its kind. The
marker is written before the first file is filed, so the shelf is the practice one from the start;
it says ``ready: false`` until the task is complete, and a task that never got there is moved to the
trash rather than reused.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from foundry.errors import FoundryError
from foundry.locking import exclusive
from foundry.sample_marker import marker_path, read_marker
from foundry.task import TaskStore

KINDS = {
    "practice": "示例 · 华宸物业 8 月月结（跟着做）",
    "next_month": "示例 · 华宸物业 9 月月结（跟着做）",
}
PERIODS = {"practice": "2026-08", "next_month": "2026-09"}
LOCK_NAME = "sample-task.lock"


def pack_dir() -> Path:
    from foundry.resources import resource_dir

    path = resource_dir("demo_pack")
    if not (path / "pack.json").is_file():
        raise FoundryError(f"the example pack is incomplete in this installation ({path})")
    return path


def pack_manifest() -> dict[str, Any]:
    return json.loads((pack_dir() / "pack.json").read_text(encoding="utf-8"))


def create_sample_task(var: Path) -> dict:
    """The August practice task, created once per pack version and reused after."""
    return _create(Path(var), "practice")


def create_next_month_sample(var: Path) -> dict:
    """The September practice task, for the guide's 下个月 step."""
    return _create(Path(var), "next_month")


def _create(var: Path, kind: str) -> dict:
    manifest = pack_manifest()
    files = manifest["practice"] if kind == "practice" else manifest["next_month"]
    tasks = TaskStore(var)
    var.mkdir(parents=True, exist_ok=True)
    with exclusive(var / LOCK_NAME):
        for task in tasks.list("active"):
            marker = read_marker(task) or {}
            if marker.get("kind") == kind and marker.get("version") == manifest["version"]:
                if marker.get("ready"):
                    return {"id": task.id, "created": False}
                # Left half-made by an earlier attempt: it is not reused, and it is not left looking usable.
                task.set_lifecycle_status("trashed")
        task = tasks.create(title=KINDS[kind], period=PERIODS[kind])
        marker = {"sample": True, "pack": manifest["pack"], "version": manifest["version"], "kind": kind, "ready": False}
        _write_marker(task, marker)
        try:
            _file_pack(task, files)
        except Exception:
            task.set_lifecycle_status("trashed")
            raise
        _write_marker(task, {**marker, "ready": True})
    return {"id": task.id, "created": True}


def _file_pack(task, files: list[str]) -> None:
    from foundry.analysis import AnalysisStore
    from foundry.finance_service import FinanceStore

    analysis = AnalysisStore(task)
    service = FinanceStore(task)
    source = pack_dir()
    for file_name in files:
        dataset = analysis.add_dataset(source / file_name, name=file_name)  # named as 加入分析资料 names a file
        if file_name.endswith(".xlsx"):
            # The same reading a real import gets, so the practice run asks for the structure too.
            service.structure_propose(dataset["id"], source=service.actor)


def _write_marker(task, marker: dict) -> None:
    from foundry.fsutil import write_json_atomic

    write_json_atomic(marker_path(task), marker)


def sample_status(var: Path) -> dict:
    """Which practice tasks exist, from which pack version, and whether a newer pack is installed."""
    manifest = pack_manifest()
    rows = []
    for task in TaskStore(Path(var)).list("all"):
        marker = read_marker(task)
        if marker is None:
            continue
        rows.append({
            "id": task.id,
            "title": task.meta().get("title", ""),
            "kind": marker.get("kind", "legacy"),
            "version": marker.get("version"),
            "lifecycle_status": task.lifecycle_status(),
        })
    live = [row for row in rows if row["lifecycle_status"] != "trashed"]
    return {
        "pack": manifest["pack"],
        "version": manifest["version"],
        "tasks": rows,
        # An older pack's task, or the 6 月 practice task from before the pack, still on the list.
        "outdated": any(row["version"] != manifest["version"] for row in live),
    }


def remove_samples(var: Path) -> dict:
    """Move every practice task that is not already there into the trash. Real tasks are never touched;
    from the trash they are restored or deleted for good like any other task."""
    moved = []
    for task in TaskStore(Path(var)).list("all"):
        if read_marker(task) is None or task.lifecycle_status() == "trashed":
            continue
        task.set_lifecycle_status("trashed")
        moved.append(task.id)
    return {"trashed": moved}


def export_pack(destination: Path) -> dict:
    """Copy the example files into a new folder of the manager's choosing, to open in Excel or import by hand.

    The folder must not exist yet or must be empty: an export never overwrites a file."""
    destination = Path(destination).expanduser()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise FoundryError("choose a new or empty folder for the example files")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = pack_manifest()
    names = [*manifest["practice"], *manifest["next_month"], manifest["report"], manifest["notes"]]
    for name in names:
        shutil.copy2(pack_dir() / name, destination / name)
    return {"folder": str(destination), "files": names}
