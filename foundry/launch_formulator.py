from __future__ import annotations

import os
import shutil
from pathlib import Path

from foundry.errors import LockRefused
from foundry.window import Window

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "formulator-plugin"


def formulator_home(window: Window) -> Path:
    return window.store.formulator_dir / window.id


def write_connectors(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "connectors.yaml"
    path.write_text("auto_connect:\n  - locked_catalog\n")
    return path


def purge_formulator_home(window: Window) -> None:
    home = formulator_home(window)
    if home.exists():
        shutil.rmtree(home)


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
    }
    argv = ["data-formulator"]
    return {"argv": argv, "env": env, "home": str(home)}


def stop_lease(window: Window) -> None:
    window.release_handle("formulator")
    purge_formulator_home(window)


def launch_formulator(window: Window) -> dict[str, str | list[str]]:
    spec = launch_spec(window)
    if os.environ.get("FOUNDRY_SKIP_FORMULATOR_EXEC") == "1":
        return spec
    import shutil
    import subprocess

    binary = shutil.which(str(spec["argv"][0]))
    if binary is None:
        return spec
    subprocess.Popen([binary], env={**os.environ, **spec["env"]}, cwd=str(spec["home"]))
    return spec
