from __future__ import annotations

import os
import shutil
from pathlib import Path

from foundry.errors import LockRefused
from foundry.window import Window

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "formulator-plugin"
FORMULATOR_BINS = ("data_formulator", "data-formulator")


def formulator_home(window: Window) -> Path:
    return window.store.formulator_dir / window.id


def write_connectors(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "connectors.yaml"
    path.write_text(
        "connectors:\n"
        "  - id: locked_catalog\n"
        "    type: locked_catalog\n"
        "    name: Locked catalog\n"
        "    auto_connect: true\n"
    )
    return path


def purge_formulator_home(window: Window) -> None:
    home = formulator_home(window)
    if home.exists():
        shutil.rmtree(home)


def formulator_bin() -> str:
    for name in FORMULATOR_BINS:
        found = shutil.which(name)
        if found:
            return found
    return FORMULATOR_BINS[0]


def launch_spec(window: Window) -> dict[str, str | list[str]]:
    if window.state not in {"Locked", "Briefed", "FollowUp"}:
        raise LockRefused("Formulator launches only after lock")
    home = formulator_home(window)
    write_connectors(home)
    window.register_handle("formulator")
    env = {
        "DF_PLUGIN_DIR": str(PLUGIN_DIR),
        "DATA_FORMULATOR_HOME": str(home),
        "FOUNDRY_VAR": str(window.store.var_root),
        "WORKSPACE_BACKEND": "local",
    }
    argv = [
        formulator_bin(),
        "--data-dir",
        str(home),
        "--dev",
        "--host",
        "127.0.0.1",
        "--port",
        os.environ.get("FOUNDRY_FORMULATOR_PORT", "5567"),
    ]
    return {"argv": argv, "env": env, "home": str(home)}


def stop_lease(window: Window) -> None:
    window.release_handle("formulator")
    purge_formulator_home(window)


def launch_formulator(window: Window) -> dict[str, str | list[str]]:
    spec = launch_spec(window)
    if os.environ.get("FOUNDRY_SKIP_FORMULATOR_EXEC") == "1":
        return spec
    import subprocess

    argv = list(spec["argv"])
    resolved = shutil.which(str(argv[0]))
    if resolved is None:
        return spec
    argv[0] = resolved
    log = Path(spec["home"]) / "formulator.log"
    handle = log.open("ab")
    subprocess.Popen(
        argv,
        env={**os.environ, **spec["env"]},
        cwd=str(spec["home"]),
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )
    handle.close()
    return spec
