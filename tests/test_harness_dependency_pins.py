"""Keep the pinned harness on the Cordis APIs its boot code actually uses."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORDIS_PINS = {
    "@deepseek-ai/cordis": "4.0.2",
    "@deepseek-ai/cordis-plugin-group": "1.0.2",
    "@deepseek-ai/cordis-plugin-hmr": "1.0.17",
    "@deepseek-ai/cordis-plugin-include": "1.0.7",
    "@deepseek-ai/cordis-plugin-loader": "1.0.3",
    "@deepseek-ai/cordis-plugin-timer": "1.1.4",
    "@deepseek-ai/cosmokit": "1.8.3",
    "@deepseek-ai/schemastery": "3.18.2",
}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def staged_harness(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "app" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "app" / "scripts" / "fetch-harness.mjs", scripts)
    # Client presentation is independent of dependency compatibility. This
    # fixture exercises the real staging/check CLI without its large assets.
    (scripts / "adapt-harness-client.mjs").write_text(
        "export function adaptClient() {}\n", encoding="utf-8"
    )
    kit = {
        "name": "finance-skill-foundry-dsh",
        "dsh": {"foundry": {"harness": {
            "package": "@deepseek-ai/dsh",
            "version": "0.1.1-rc.2",
            "entry": "node_modules/@deepseek-ai/dsh/lib/bin.js",
            "overrides": CORDIS_PINS,
        }}},
    }
    _write_json(tmp_path / "dsh-plugin" / "package.json", kit)
    stage = tmp_path / "app" / "extra" / "dsh"
    entry = stage / kit["dsh"]["foundry"]["harness"]["entry"]
    entry.parent.mkdir(parents=True)
    entry.write_text("// fixture runtime entry\n", encoding="utf-8")
    (stage / "PIN").write_text("pin: @deepseek-ai/dsh@0.1.1-rc.2\n", encoding="utf-8")
    _write_json(stage / "node_modules" / kit["name"] / "package.json", kit)
    for package, version in CORDIS_PINS.items():
        _write_json(stage / "node_modules" / package / "package.json", {"version": version})
    return scripts / "fetch-harness.mjs", stage


def _run(script: Path, flag: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node is not None, "the app's staging regression requires Node"
    return subprocess.run([node, str(script), flag], capture_output=True, text=True, timeout=30)


def test_harness_declares_the_compatible_cordis_family_in_both_bundles() -> None:
    for package in (
        ROOT / "dsh-plugin" / "package.json",
        ROOT / "foundry" / "resources" / "dsh-plugin" / "package.json",
    ):
        harness = json.loads(package.read_text(encoding="utf-8"))["dsh"]["foundry"]["harness"]
        assert harness.get("overrides") == CORDIS_PINS, package


def test_harness_check_accepts_the_compatible_tree(staged_harness: tuple[Path, Path]) -> None:
    script, _ = staged_harness
    result = _run(script, "--check")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("package", CORDIS_PINS)
def test_harness_check_rejects_transitive_drift(
    staged_harness: tuple[Path, Path], package: str
) -> None:
    script, stage = staged_harness
    _write_json(stage / "node_modules" / package / "package.json", {"version": "99.0.0"})
    result = _run(script, "--check")
    assert result.returncode != 0, "a matching top-level dsh pin must not admit incompatible Cordis"
    assert package in result.stderr
    assert "99.0.0" in result.stderr
    assert CORDIS_PINS[package] in result.stderr


def test_harness_refresh_local_keeps_dependency_overrides(staged_harness: tuple[Path, Path]) -> None:
    script, stage = staged_harness
    result = _run(script, "--refresh-local")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((stage / "package.json").read_text(encoding="utf-8"))["overrides"] == CORDIS_PINS


def test_harness_refresh_local_refuses_an_incompatible_cache(staged_harness: tuple[Path, Path]) -> None:
    script, stage = staged_harness
    _write_json(stage / "node_modules/@deepseek-ai/cordis-plugin-hmr/package.json", {"version": "1.1.0"})
    result = _run(script, "--refresh-local")
    assert result.returncode != 0, "refresh-local must not bless a drifted cached runtime"
    assert "cordis-plugin-hmr" in result.stderr
    assert "1.1.0" in result.stderr


@pytest.mark.parametrize("consumer", ("@deepseek-ai/dsh", "@deepseek-ai/dsh-app-boot"))
@pytest.mark.parametrize("flag", ("--check", "--refresh-local"))
def test_harness_refuses_a_nested_incompatible_copy(
    staged_harness: tuple[Path, Path], consumer: str, flag: str
) -> None:
    script, stage = staged_harness
    # Node resolves this copy before the compatible one at the staging root.
    nested = stage / "node_modules" / consumer / "node_modules/@deepseek-ai/cordis-plugin-hmr"
    _write_json(nested / "package.json", {"name": "@deepseek-ai/cordis-plugin-hmr", "version": "1.1.0"})
    result = _run(script, flag)
    assert result.returncode != 0, "a compatible root copy must not hide the consumer's incompatible HMR"
    assert str(nested.relative_to(stage)) in result.stderr
    assert "1.1.0" in result.stderr
    assert "1.0.17" in result.stderr
