from __future__ import annotations

from importlib import resources
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_dir(name: str) -> Path:
    repo_dir = _repo_root() / name
    if repo_dir.exists():
        return repo_dir
    candidate = resources.files("foundry").joinpath("resources", name)
    return Path(str(candidate))


def fixture_root(base: Path | None = None) -> Path:
    return Path(base) if base else resource_dir("fixtures") / "period-smoke"
