from __future__ import annotations

import json
import os
import shutil
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


def preset_dir() -> Path:
    return dsh_plugin_dir() / "presets"


def fence_path() -> Path:
    return dsh_plugin_dir() / "period.fence.yml"


def preset_ids() -> list[str]:
    return list(load_foundry_dsh()["presets"]["ids"])


# Stands in a preset for the shipped method-skill root, filled in at install.
METHOD_SKILL_DIR_TOKEN = "__FOUNDRY_METHOD_SKILL_DIR__"


def install_presets(dsh_home: Path) -> list[Path]:
    """Copy analysis and legacy agent presets where the runtime discovers them.

    `<DSH_HOME>/.agent-presets/<id>/` is the harness-home root the preset roster
    scans last, after every configured one. Discovery is unmemoized, so a preset
    copied while the process runs is visible to the next session rather than to
    the next restart.

    Copied rather than linked, and copied on every call: a preset is read from
    its file each time a generation starts, so an edit in the checkout has to be
    carried over deliberately, and a half-updated preset in the home is worse
    than a stale one.
    """
    root = Path(dsh_home) / ".agent-presets"
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for preset_id in preset_ids():
        source = preset_dir() / preset_id
        if not (source / "agent.cordis.yml").is_file():
            raise FoundryError(f"preset {preset_id} has no agent.cordis.yml at {source}")
        target = root / preset_id
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        preset = target / "agent.cordis.yml"
        text = preset.read_text(encoding="utf-8")
        if METHOD_SKILL_DIR_TOKEN in text:
            from foundry.method_skills import method_root

            # JSON quoting is valid YAML and survives the space in "FA Foundry.app".
            text = text.replace(METHOD_SKILL_DIR_TOKEN, json.dumps(str(method_root())))
            preset.write_text(text, encoding="utf-8")
        written.append(target)
    return written


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


def office_companion() -> dict[str, Any]:
    """The Univer bundle, and the two switches it is not allowed to ship without.

    Third-party plugin code runs with the operator's full privileges, which is
    the operator's decision to make -- but our operators do not get to make the
    telemetry one for themselves, so it is made here and refused if it goes
    missing. ``DO_NOT_TRACK`` is what the plugin's own capture path checks
    first; the empty endpoint is the second belt, and it is what this published
    build already carries in ``lib/build-info.json``. A later version could bake
    one in, and this is the line that would catch it.
    """
    companion = load_foundry_dsh()["companions"]["office"]
    if companion.get("role") != "deliverable-surface":
        raise FoundryError("office companion is a deliverable surface, not a books surface")
    env = companion.get("env") or {}
    if not str(env.get("DO_NOT_TRACK") or "").strip():
        raise FoundryError("office companion must set DO_NOT_TRACK; our operators cannot")
    if env.get("UNIVER_TELEMETRY_ENDPOINT") != "":
        raise FoundryError("office companion must blank UNIVER_TELEMETRY_ENDPOINT")
    return companion


def companion_env() -> dict[str, str]:
    """Every environment variable this app sets on behalf of a companion.

    Read by the Electron side through `foundry harness`, so the values live in
    the kit's own manifest and not in two languages.
    """
    out: dict[str, str] = {}
    for companion in load_foundry_dsh()["companions"].values():
        for name, value in (companion.get("env") or {}).items():
            out[str(name)] = str(value)
    return out


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


def plugin_install_text(profile: str = "web") -> str:
    """How the period tools get in front of a model.

    One command, and deliberately not two. `dsh plugin add` writes the package
    into the profile's dependencies *and* appends it to `dsh.profile.bundles`,
    and a package carrying a `dsh.bundle.patch` block contributes its own insert
    row from there. Passing that same file again as `--patch` composes the row a
    second time, which is the double-apply the file-upload companion already
    warns about.

    Verified against a real boot on the pinned runtime: after this one command
    and nothing else, `--dump-config` shows exactly one
    `id: finance-skill-foundry` row and all ten tools reach the agent.
    """
    return "\n".join(
        [
            f"dsh plugin --profile {profile} add {dsh_plugin_dir()}",
            f"bundle\t{json.loads(plugin_package().read_text())['name']}",
            f"patch\t{dsh_plugin_dir() / 'cordis.patch.yml'} (contributed by the package; do not also pass --patch)",
            f"tools\t{','.join(load_foundry_dsh()['tools'])}",
            "",
            "# the fence. one of these, depending on whether the profile has agent presets.",
            f"presets\t{preset_dir()} -> <DSH_HOME>/.agent-presets/  ({','.join(preset_ids())})",
            f"fence\tdsh --profile {profile} --patch {fence_path()}   # only for a profile with no presets",
        ]
    )


def harness_text() -> str:
    companion = file_upload_companion()
    add = companion["add"]
    pin = companion["version"]
    omit = ",".join(companion["omitTools"])
    exts = ",".join(companion["config"]["allowedExtensions"])
    office = office_companion()
    return "\n".join(
        [
            plugin_install_text(),
            "",
            add,
            f"pin\t{pin}",
            f"role\t{companion['role']}",
            f"omit\t{omit}",
            f"allowedExtensions\t{exts}",
            f"overlay\t{overlay_path()}",
            "",
            f"# {office['package']}@{office['version']} -- {office['role']}",
            f"add\t{office['add']}",
            f"env\t{' '.join(f'{k}={v or chr(39) * 2}' for k, v in office['env'].items())}",
            f"scope\t{load_foundry_dsh()['profiles']['period']['scope']} masks {len(office['omitTools'])} tools on period",
            f"egress\t{','.join(office['egress'])} (univer_resources, denied on period)",
            f"license\texpires {office['licenseExpires']}; rendered output is watermarked after that",
        ]
    )
