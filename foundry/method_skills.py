from __future__ import annotations

from pathlib import Path

BUNDLED_IDS = (
    "financial-statements",
    "reconciliation",
    "variance-analysis",
    "journal-entry",
)


def method_root() -> Path:
    return Path(__file__).resolve().parents[1] / "method"


def bundled_skill_dirs() -> dict[str, Path]:
    root = method_root()
    return {skill_id: root / skill_id for skill_id in BUNDLED_IDS}


def bundled_skill_files() -> dict[str, Path]:
    return {skill_id: path / "SKILL.md" for skill_id, path in bundled_skill_dirs().items()}
