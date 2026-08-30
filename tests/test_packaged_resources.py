from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "foundry" / "resources"
MIRRORED_DIRS = ("method", "dsh-plugin", "fixtures/period-smoke", "formulator-plugin")


def _files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(root))] = digest
    return result


def test_packaged_resources_mirror_canonical_inputs() -> None:
    for rel in MIRRORED_DIRS:
        canonical = ROOT / rel
        packaged = RESOURCE_ROOT / rel
        assert _files(packaged) == _files(canonical), rel
