from __future__ import annotations

import hashlib
from pathlib import Path

from foundry.errors import FoundryError
from foundry.resources import resource_dir

BUNDLED_IDS = (
    "financial-statements",
    "reconciliation",
    "variance-analysis",
    "journal-entry",
)

METHOD_RESOURCE_NAMES = ("FOUNDRY.md", "CONNECTORS.md", "NOTICE", "LICENSE")


def method_root() -> Path:
    return resource_dir("method")


def bundled_skill_dirs() -> dict[str, Path]:
    root = method_root()
    return {skill_id: root / skill_id for skill_id in BUNDLED_IDS}


def bundled_skill_files() -> dict[str, Path]:
    return {skill_id: path / "SKILL.md" for skill_id, path in bundled_skill_dirs().items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundled_skill_manifest() -> dict[str, object]:
    root = method_root()
    skills: list[dict[str, object]] = []
    missing: list[str] = []
    for skill_id, path in bundled_skill_files().items():
        item: dict[str, object] = {
            "id": skill_id,
            "dir": str(path.parent),
            "file": str(path),
            "exists": path.is_file(),
        }
        if path.is_file():
            item["sha256"] = _sha256(path)
            item["bytes"] = path.stat().st_size
        else:
            missing.append(skill_id)
        skills.append(item)
    return {
        "root": str(root),
        "ids": list(BUNDLED_IDS),
        "exists": root.is_dir() and not missing,
        "source": "repo" if root == Path(__file__).resolve().parents[1] / "method" else "package",
        "skills": skills,
        "missing": missing,
    }


def read_method_resource(skill_id: str, resource_name: str) -> dict[str, object]:
    if skill_id not in BUNDLED_IDS:
        raise FoundryError(f"unknown method skill: {skill_id}")
    if resource_name not in METHOD_RESOURCE_NAMES:
        raise FoundryError(f"method resource is not allowed: {resource_name}")
    root = method_root()
    path = root / resource_name
    resolved = path.resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise FoundryError(f"method resource escaped root: {resource_name}")
    if not path.is_file():
        raise FoundryError(f"method resource missing: {skill_id}/{resource_name}")
    return {
        "skill": skill_id,
        "resource": resource_name,
        "path": str(path),
        "sha256": _sha256(path),
        "content": path.read_text(encoding="utf-8"),
    }
