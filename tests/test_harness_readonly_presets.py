from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest

from foundry import harness, method_skills
from foundry.errors import LockRefused


def _snapshot(root: Path) -> dict[str, tuple[int, bytes | None]]:
    return {
        str(path.relative_to(root)): (
            stat.S_IMODE(path.stat().st_mode),
            path.read_bytes() if path.is_file() else None,
        )
        for path in [root, *root.rglob("*")]
    }


@pytest.fixture
def readonly_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "shipped" / "analysis"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "agent.cordis.yml").write_text(
        f"bundledSkillDir: {harness.METHOD_SKILL_DIR_TOKEN}\n", encoding="utf-8"
    )
    (nested / "data.txt").write_bytes(b"unchanged nested data\n")
    (nested / "helper.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
    (source / "agent.cordis.yml").chmod(0o400)
    (nested / "data.txt").chmod(0o444)
    (nested / "helper.sh").chmod(0o550)
    nested.chmod(0o550)
    source.chmod(0o500)
    monkeypatch.setattr(harness, "preset_ids", lambda: ["analysis"])
    monkeypatch.setattr(harness, "preset_dir", lambda: source.parent)
    monkeypatch.setattr(method_skills, "method_root", lambda: tmp_path / "FA Foundry.app" / "methods")
    yield source
    # Permit pytest to clean its own test fixture after the source invariants were checked.
    for path in [source, *source.rglob("*")]:
        path.chmod(path.stat().st_mode | stat.S_IWUSR)


def test_readonly_presets_install_with_only_destination_owner_write(
    tmp_path: Path, readonly_preset: Path
) -> None:
    before = _snapshot(readonly_preset)
    home = tmp_path / "home"
    (target,) = harness.install_presets(home)

    assert target == home / ".agent-presets" / "analysis"
    assert _snapshot(readonly_preset) == before
    expected_text = f"bundledSkillDir: {json.dumps(str(method_skills.method_root()))}\n"
    assert (target / "agent.cordis.yml").read_text(encoding="utf-8") == expected_text
    for relative, (mode, content) in before.items():
        copied = target / relative
        assert stat.S_IMODE(copied.stat().st_mode) == mode | stat.S_IWUSR
        if content is not None and relative != "agent.cordis.yml":
            assert copied.read_bytes() == content


def test_readonly_presets_reinstall_replaces_nested_content(
    tmp_path: Path, readonly_preset: Path
) -> None:
    before = _snapshot(readonly_preset)
    home = tmp_path / "home"
    (target,) = harness.install_presets(home)
    (target / "nested" / "data.txt").write_text("local edit", encoding="utf-8")
    stale = target / "nested" / "stale"
    stale.mkdir()
    (stale / "old.txt").write_text("stale", encoding="utf-8")

    assert harness.install_presets(home) == [target]
    assert not stale.exists()
    assert (target / "nested" / "data.txt").read_bytes() == b"unchanged nested data\n"
    assert harness.METHOD_SKILL_DIR_TOKEN not in (target / "agent.cordis.yml").read_text()
    assert _snapshot(readonly_preset) == before


def test_readonly_presets_without_placeholder_reinstall(
    tmp_path: Path, readonly_preset: Path
) -> None:
    preset = readonly_preset / "agent.cordis.yml"
    preset.chmod(0o600)
    preset.write_text("- id: unchanged\n", encoding="utf-8")
    preset.chmod(0o400)
    before = _snapshot(readonly_preset)
    home = tmp_path / "home"

    first = harness.install_presets(home)
    assert harness.install_presets(home) == first
    assert (first[0] / "agent.cordis.yml").read_text() == "- id: unchanged\n"
    assert _snapshot(readonly_preset) == before


def test_destination_symlink_does_not_change_its_referent(
    tmp_path: Path, readonly_preset: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"leave this alone\n")
    (outside / "sentinel").chmod(0o400)
    outside.chmod(0o500)
    before = _snapshot(outside)
    home = tmp_path / "home"
    (home / ".agent-presets").mkdir(parents=True)
    (home / ".agent-presets" / "analysis").symlink_to(outside, target_is_directory=True)

    try:
        with pytest.raises(FileExistsError):
            harness.install_presets(home)
        assert _snapshot(outside) == before
    finally:
        outside.chmod(0o700)


def test_existing_readonly_partial_install_is_replaced(
    tmp_path: Path, readonly_preset: Path
) -> None:
    before = _snapshot(readonly_preset)
    home = tmp_path / "home"
    target = home / ".agent-presets" / "analysis"
    shutil.copytree(readonly_preset, target)
    assert _snapshot(target) == before

    assert harness.install_presets(home) == [target]
    assert harness.METHOD_SKILL_DIR_TOKEN not in (target / "agent.cordis.yml").read_text()
    assert _snapshot(readonly_preset) == before


def test_existing_nested_symlink_does_not_chmod_source(
    tmp_path: Path, readonly_preset: Path
) -> None:
    before = _snapshot(readonly_preset)
    home = tmp_path / "home"
    target = home / ".agent-presets" / "analysis"
    shutil.copytree(readonly_preset, target)
    nested = target / "nested"
    nested.chmod(0o750)
    (nested / "source-link").symlink_to(readonly_preset, target_is_directory=True)
    (nested / "file-link").symlink_to(readonly_preset / "agent.cordis.yml")
    nested.chmod(0o550)

    assert harness.install_presets(home) == [target]
    assert not (target / "nested" / "source-link").exists()
    assert not (target / "nested" / "file-link").exists()
    assert _snapshot(readonly_preset) == before


def test_destination_parent_symlink_cannot_change_source(
    tmp_path: Path, readonly_preset: Path
) -> None:
    before = _snapshot(readonly_preset)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".agent-presets").symlink_to(readonly_preset.parent, target_is_directory=True)

    with pytest.raises(LockRefused, match="symlink"):
        harness.install_presets(home)
    assert _snapshot(readonly_preset) == before
