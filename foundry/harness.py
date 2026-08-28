from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundry.errors import FoundryError, LockRefused

PLUGIN_PACKAGE = Path(__file__).resolve().parents[1] / "dsh-plugin" / "package.json"
OVERLAY = Path(__file__).resolve().parents[1] / "dsh-plugin" / "file-upload.overlay.yml"

LINE_LEAKS = frozenset({"read_document"})
DROP_EXTS = frozenset({".xlsx", ".csv"})
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


def load_foundry_dsh() -> dict[str, Any]:
    return json.loads(PLUGIN_PACKAGE.read_text())["dsh"]["foundry"]


def file_upload_companion() -> dict[str, Any]:
    companion = load_foundry_dsh()["companions"]["file-upload"]
    if companion.get("role") != "input-drop":
        raise FoundryError("file-upload companion must be an input drop, not a books surface")
    omit = set(companion.get("omitTools") or [])
    if not LINE_LEAKS <= omit:
        raise FoundryError(f"file-upload companion must omit line leaks: {sorted(LINE_LEAKS)}")
    return companion


def map_drop(drop_dir: Path) -> DropMap:
    if not drop_dir.is_dir():
        raise LockRefused(f"drop-dir is not a directory: {drop_dir}")
    by_stem: dict[str, Path] = {}
    result = DropMap()
    for path in sorted(p for p in drop_dir.rglob("*") if p.is_file()):
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
            f"overlay\t{OVERLAY}",
        ]
    )
