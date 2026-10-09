"""Practice tasks built from the bundled 华宸物业 example pack, so a first run never touches real books.

The pack is a set of fictitious workbooks and documents in ``foundry/resources/demo_pack`` (written by
``tests/fixtures/demo_pack/build_demo.py``; ``pack.json`` lists them and carries the pack version).
Its differences are planted on purpose: every analysis the app offers has something real to show.

``create_sample_task`` makes (or reuses) the practice task for August: the files are filed as
datasets and read exactly as a real import is, so the structure, the controls and everything after
are still the manager's to confirm. ``create_next_month_sample`` makes the September task the guide
uses to show a remembered structure applying itself. ``create_reference_task`` makes the 参考结果
task: the same August files taken through every step by the example, to compare against. Nothing here reads or writes any other task, and
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
    "reference": "示例 · 华宸物业 8 月月结（参考结果）",
    "next_month": "示例 · 华宸物业 9 月月结（跟着做）",
}
PERIODS = {"practice": "2026-08", "reference": "2026-08", "next_month": "2026-09"}


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


def create_reference_task(var: Path, *, rebuild: bool = False) -> dict:
    """The August task taken through the whole route by the example (sample_reference), computed by
    this installation. ``rebuild`` moves the current one to the trash and makes it again: the
    reference is the example's, so whatever was changed in it can always be put back."""
    return _create(Path(var), "reference", rebuild=rebuild)


def create_next_month_sample(var: Path) -> dict:
    """The September practice task, for the guide's 下个月 step."""
    return _create(Path(var), "next_month")


def _create(var: Path, kind: str, *, rebuild: bool = False) -> dict:
    manifest = pack_manifest()
    files = manifest["next_month"] if kind == "next_month" else manifest["practice"]
    tasks = TaskStore(var)
    var.mkdir(parents=True, exist_ok=True)
    # One lock per kind: the reference takes most of a minute to build and must not hold up the others,
    # and a second request for it waits the build out and then reuses what was built.
    timeout = 300 if kind == "reference" else 10
    with exclusive(var / f"sample-task-{kind}.lock", timeout=timeout):
        for task in tasks.list("active"):
            marker = read_marker(task) or {}
            if marker.get("kind") == kind and marker.get("version") == manifest["version"]:
                if marker.get("ready") and not rebuild:
                    return {"id": task.id, "created": False}
                # Left half-made by an earlier attempt, or being rebuilt: it is not reused, and it is not
                # left looking usable.
                task.set_lifecycle_status("trashed")
        task = tasks.create(title=KINDS[kind], period=PERIODS[kind])
        marker = {"sample": True, "pack": manifest["pack"], "version": manifest["version"], "kind": kind, "ready": False}
        _write_marker(task, marker)
        try:
            _file_pack(task, files)
            if kind == "reference":
                from foundry.sample_reference import build_reference

                build_reference(task)
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
    """Move every practice task on the 进行中 list into the trash: the ones the guide counted before asking.
    One the manager archived stays where they put it. Real tasks are never touched; from the trash they are
    restored or deleted for good like any other task."""
    moved = []
    for task in TaskStore(Path(var)).list("active"):
        if read_marker(task) is None:
            continue
        task.set_lifecycle_status("trashed")
        moved.append(task.id)
    return {"trashed": moved}


def add_billing(task, *, confirm: bool = False) -> dict:
    """The 海口城市公司 收费明细 (billing_sample) filed into a practice task as three detail tables.

    The export is written fresh into a temporary folder and read exactly as a manager's own export is;
    in the practice task the columns are left for the manager to confirm. ``confirm`` is the reference
    task's: it confirms them as the example does every other step. Filing twice files nothing new."""
    import tempfile

    from foundry import billing_sample
    from foundry.billing_detail import BillingDetailStore

    store = BillingDetailStore(task, actor="manager")
    names = {kind: f"{billing_sample.CITY} {label}" for kind, label in billing_sample.NAMES.items()}
    with exclusive(task.root / "sample-billing.lock", timeout=300):
        present = {row["name"]: row for row in store.list()}
        filed = {kind: present[name] for kind, name in names.items() if name in present}
        if len(filed) < len(names):
            with tempfile.TemporaryDirectory(prefix="huachen-billing-") as folder:
                billing_sample.write(Path(folder))
                for kind, name in names.items():
                    if kind not in filed:
                        paths = [Path(folder) / file_name for file_name in billing_sample.FILES[kind]]
                        filed[kind] = store.add(kind, paths, name=name)
        if confirm:
            for kind, row in filed.items():
                if not row.get("confirmation"):
                    filed[kind] = store.confirm(row["id"])
    return {kind: {"id": row["id"], "name": row["name"], "rows": row["row_count"], "confirmed": bool(row.get("confirmation"))}
            for kind, row in filed.items()}


def add_billing_to(var: Path, task_id: str) -> dict:
    """``add_billing`` for the app's button: practice tasks only, never a real one."""
    task = TaskStore(Path(var)).get(task_id)
    marker = read_marker(task)
    if marker is None or marker.get("kind") not in ("practice", "next_month"):
        raise FoundryError("the example 收费明细 goes into a practice task only")
    return {"task_id": task.id, "details": add_billing(task)}


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
    # The 收费明细 is written by its generator rather than copied: tens of megabytes the app need not carry.
    from foundry import billing_sample

    book = billing_sample.build()
    billing_sample.write(destination, book)
    names += [name for files in billing_sample.FILES.values() for name in files]
    names.append(billing_sample.write_sample_workbook(destination / billing_sample.SAMPLE_WORKBOOK, book)["name"])
    return {"folder": str(destination), "files": names}
