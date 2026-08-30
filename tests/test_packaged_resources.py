from __future__ import annotations

import glob as globlib
import hashlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from foundry import resources as resources_module
from foundry.cli import REFUSED
from foundry.errors import FoundryError
from foundry.resources import resource_dir

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "foundry"
RESOURCE_ROOT = PACKAGE_ROOT / "resources"
MIRRORED_DIRS = ("method", "dsh-plugin", "fixtures/period-smoke", "formulator-plugin")


def _package_data_globs() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["tool"]["setuptools"]["package-data"]["foundry"])


def _globbed_files(package_root: Path, patterns: list[str]) -> set[str]:
    matched: set[str] = set()
    for pattern in patterns:
        for hit in globlib.glob(pattern, root_dir=package_root, recursive=True):
            if (package_root / hit).is_file():
                matched.add(Path(hit).as_posix())
    return matched


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


def test_package_data_globs_ship_every_resource_file() -> None:
    declared = _globbed_files(PACKAGE_ROOT, _package_data_globs())
    on_disk = {f"resources/{Path(rel).as_posix()}" for rel in _files(RESOURCE_ROOT)}
    assert on_disk - declared == set()


def test_package_data_globs_do_not_encode_directory_depth(tmp_path: Path) -> None:
    stage = tmp_path / "foundry"
    nested = stage / "resources" / "method" / "financial-statements" / "references" / "caliber.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("caliber notes", encoding="utf-8")

    rel = "resources/method/financial-statements/references/caliber.md"
    assert rel in _globbed_files(stage, _package_data_globs())


def test_packaged_fallback_serves_a_resource_the_repo_copy_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resources_module, "_repo_root", lambda: tmp_path / "no-checkout")
    found = resource_dir("method")
    assert found.parent.name == "resources"
    assert (found / "FOUNDRY.md").is_file()


def test_packaged_fallback_refuses_a_resource_missing_from_the_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resources_module, "_repo_root", lambda: tmp_path / "no-checkout")
    with pytest.raises(FoundryError, match="packaged resource missing"):
        resource_dir("dsh-plugin-dropped-from-the-wheel")


def test_cli_refuses_a_resource_missing_from_the_install(tmp_path: Path) -> None:
    stage = tmp_path / "site-packages"
    shutil.copytree(
        PACKAGE_ROOT, stage / "foundry", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.rmtree(stage / "foundry" / "resources" / "dsh-plugin")

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]);"
            " from foundry.cli import main; sys.exit(main(sys.argv[2:]))",
            str(stage),
            "--var",
            str(tmp_path / "var"),
            "harness",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == REFUSED, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "packaged resource missing: dsh-plugin" in proc.stderr
    assert "Traceback" not in proc.stderr
