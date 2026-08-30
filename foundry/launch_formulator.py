from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from foundry.errors import LockRefused
from foundry.resources import resource_dir
from foundry.window import Window

PLUGIN_DIR = resource_dir("formulator-plugin")
FORMULATOR_BINS = ("data_formulator", "data-formulator")
ENV_ALLOWLIST = (
    "PATH",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)


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
    handles = json.loads(window.handles_path.read_text()) if window.handles_path.exists() else []
    if "formulator" in handles or (home / "pid").exists():
        raise LockRefused("stop-formulator before purging an active Formulator home")
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
    port = os.environ.get("FOUNDRY_FORMULATOR_PORT", "5567")
    env = {
        "DF_PLUGIN_DIR": str(PLUGIN_DIR),
        "DATA_FORMULATOR_HOME": str(home),
        "FOUNDRY_VAR": str(window.store.var_root),
        "FOUNDRY_WINDOW_ID": window.id,
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
        port,
    ]
    return {"argv": argv, "env": env, "home": str(home), "url": f"http://127.0.0.1:{port}"}


def process_env(extra: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in ENV_ALLOWLIST}
    env.update(extra)
    return env


def stop_lease(window: Window) -> None:
    window.release_handle("formulator")
    purge_formulator_home(window)


def _pid_path(window: Window) -> Path:
    return formulator_home(window) / "pid"


def stop_formulator(window: Window) -> dict[str, str]:
    pid_path = _pid_path(window)
    if pid_path.exists():
        raw = pid_path.read_text().strip()
        if raw:
            try:
                pid = int(raw)
            except ValueError as exc:
                pid_path.unlink(missing_ok=True)
                stop_lease(window)
                raise LockRefused("Formulator pid is invalid") from exc
            if pid <= 0:
                pid_path.unlink(missing_ok=True)
                stop_lease(window)
                raise LockRefused("Formulator pid is invalid")
            command = _pid_command(pid)
            if not command:
                if _pid_exists(pid):
                    raise LockRefused("Formulator process identity is unavailable")
            elif not _command_matches_window(command, formulator_home(window)):
                pid_path.unlink(missing_ok=True)
                stop_lease(window)
                raise LockRefused("Formulator pid does not belong to this window")
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            else:
                if not _wait_for_pid_exit(pid):
                    os.kill(pid, signal.SIGKILL)
                    if not _wait_for_pid_exit(pid):
                        raise LockRefused("Data Formulator did not stop")
        pid_path.unlink(missing_ok=True)
    stop_lease(window)
    return {"stopped": "formulator", "window_id": window.id}


def _pid_command(pid: int) -> str:
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid_exit(pid: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            waited, _status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                return True
        except ChildProcessError:
            pass
        if not _pid_exists(pid):
            return True
        time.sleep(0.05)
    return not _pid_exists(pid)


def _command_matches_window(command: str, home: Path) -> bool:
    return bool(command) and any(name in command for name in FORMULATOR_BINS) and str(home) in command


def _ready(url: str, proc: subprocess.Popen[bytes], timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                return response.status < 500
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    return False


def launch_formulator(window: Window) -> dict[str, str | list[str]]:
    spec = launch_spec(window)
    if os.environ.get("FOUNDRY_SKIP_FORMULATOR_EXEC") == "1":
        return spec

    argv = list(spec["argv"])
    resolved = shutil.which(str(argv[0]))
    if resolved is None:
        raise LockRefused("Data Formulator binary is not installed")
    argv[0] = resolved
    home = Path(spec["home"])
    proc: subprocess.Popen[bytes] | None = None
    handle = None
    try:
        write_connectors(home)
        handle = (home / "formulator.log").open("ab")
        proc = subprocess.Popen(
            argv,
            env=process_env(dict(spec["env"])),
            cwd=str(spec["home"]),
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )
        if not _ready(str(spec["url"]), proc):
            if proc.poll() is None:
                proc.terminate()
            raise LockRefused("Data Formulator did not become ready")
        _pid_path(window).write_text(str(proc.pid) + "\n")
        window.register_handle("formulator")
    except Exception:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        stop_lease(window)
        raise
    finally:
        if handle is not None:
            handle.close()
    return spec
