from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundry.errors import FoundryError, LockRefused
from foundry.resources import resource_dir

LINE_LEAKS = frozenset({"read_document"})
DROP_EXTS = frozenset({".xlsx", ".csv", ".json"})
RESERVED_STEMS = {
    "coa": "coa",
    "aux": "aux",
    "map": "map",
    "units": "units",
}
SKIP_STEMS = frozenset(
    {
        "named",
        "questions",
        "brief",
        "lock",
        "workpaper",
        "schedules",
        "readme",
        "skill",
        "notice",
        "license",
    }
)


@dataclass
class DropMap:
    coa: Path | None = None
    aux: Path | None = None
    map: Path | None = None
    units: Path | None = None
    named: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def dsh_plugin_dir() -> Path:
    """Resolved on call, not on import, so a missing resource reaches the cli handler."""
    return resource_dir("dsh-plugin")


def plugin_package() -> Path:
    return dsh_plugin_dir() / "package.json"


def overlay_path() -> Path:
    return dsh_plugin_dir() / "file-upload.overlay.yml"


def load_foundry_dsh() -> dict[str, Any]:
    return json.loads(plugin_package().read_text())["dsh"]["foundry"]


def file_upload_companion() -> dict[str, Any]:
    companion = load_foundry_dsh()["companions"]["file-upload"]
    if companion.get("role") != "input-drop":
        raise FoundryError("file-upload companion must be an input drop, not a books surface")
    omit = set(companion.get("omitTools") or [])
    if not LINE_LEAKS <= omit:
        raise FoundryError(f"file-upload companion must omit line leaks: {sorted(LINE_LEAKS)}")
    return companion


def assert_no_escaping_symlink(path: Path, label: str) -> None:
    """Refuse a path reached through a symlink that leaves its own directory.

    Resolving a path first and anchoring containment to the result lets a
    symlinked directory move the envelope: every sibling in the target then
    passes the containment check. Both import entry points -- the drop dir and
    the named descriptor -- run this, so they agree on where the boundary is.

    An in-place symlink is left alone. ``/tmp -> /private/tmp`` and the macOS
    ``/var`` are the everyday shape and they do not move anything: the test is
    whether the target escapes the directory the link itself lives in.
    """
    parent = path.parent
    prefix = Path(parent.anchor) if parent.anchor else Path()
    for part in parent.parts[len(prefix.parts) :]:
        prefix = prefix / part
        if not prefix.is_symlink():
            continue
        target = Path(os.path.realpath(prefix))
        home = Path(os.path.realpath(prefix.parent))
        try:
            target.relative_to(home)
        except ValueError as exc:
            raise LockRefused(
                f"{label} is reached through a symlink that leaves its directory: "
                f"{prefix} -> {target}"
            ) from exc


def map_drop(drop_dir: Path) -> DropMap:
    assert_no_escaping_symlink(drop_dir, "drop-dir")
    if drop_dir.is_symlink():
        raise LockRefused(f"drop-dir symlink is refused: {drop_dir}")
    if not drop_dir.is_dir():
        raise LockRefused(f"drop-dir is not a directory: {drop_dir}")
    root = drop_dir.resolve()
    by_stem: dict[str, Path] = {}
    result = DropMap()
    for path in sorted(drop_dir.rglob("*")):
        if path.is_symlink():
            raise LockRefused(f"drop-dir symlink is refused: {path.relative_to(drop_dir)}")
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise LockRefused(f"drop-dir path escapes root: {path}") from exc
        rel = str(path.relative_to(drop_dir))
        if path.suffix.lower() not in DROP_EXTS:
            result.skipped.append(rel)
            continue
        stem = path.stem.strip().lower()
        if stem in by_stem:
            raise LockRefused(f"drop-dir has two files for {stem}")
        by_stem[stem] = path
    for stem, path in by_stem.items():
        field_name = RESERVED_STEMS.get(stem)
        if field_name is not None:
            setattr(result, field_name, path)
            continue
        if stem in SKIP_STEMS:
            result.skipped.append(str(path.relative_to(drop_dir)))
            continue
        result.named.append({"id": stem, "path": path})
    return result


def merge_import_sources(
    *,
    coa: Path | None,
    named: list[dict[str, Any]] | None,
    aux: Path | None,
    map: Path | None,
    units: Path | None,
    drop_dir: Path | None,
) -> DropMap:
    mapped = map_drop(drop_dir) if drop_dir is not None else DropMap()
    return DropMap(
        coa=Path(coa) if coa else mapped.coa,
        aux=Path(aux) if aux else mapped.aux,
        map=Path(map) if map else mapped.map,
        units=Path(units) if units else mapped.units,
        named=list(named) if named is not None else mapped.named,
        skipped=mapped.skipped,
    )


def harness_text() -> str:
    companion = file_upload_companion()
    add = companion["add"]
    pin = companion["version"]
    omit = ",".join(companion["omitTools"])
    exts = ",".join(companion["config"]["allowedExtensions"])
    return "\n".join(
        [
            add,
            f"pin\t{pin}",
            f"role\t{companion['role']}",
            f"omit\t{omit}",
            f"allowedExtensions\t{exts}",
            f"overlay\t{overlay_path()}",
        ]
    )
