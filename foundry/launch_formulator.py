from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from foundry.errors import LockRefused
from foundry.fsutil import write_text_atomic
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
    # Lets the operator point data-formulator's credential vault outside the
    # window instead of leaving credentials.db + .vault_key in the home.
    "CREDENTIAL_VAULT_KEY",
)

FORCE_STOP_ENV = "FOUNDRY_FORMULATOR_FORCE_STOP"


def formulator_home(window: Window) -> Path:
    return window.formulator_home


def no_browser_path(home: Path) -> Path:
    return home / "no-browser"


def write_no_browser(home: Path) -> Path:
    """A no-op "browser" the child opens instead of the operator's real one.

    data-formulator 0.7.0 arms ``webbrowser.open`` 1.5s after start unless
    ``--dev`` is passed, and ``--dev`` also turns on the Flask debugger, which
    this kit refuses to expose. Python's ``webbrowser`` tries ``$BROWSER``
    first and stops as soon as one entry reports success, so a script that
    exits 0 swallows the popup. Without it a launch that is still 8s away from
    being refused has already opened a tab on a server that may not even be
    this window's.
    """
    ensure_formulator_home(home)
    path = no_browser_path(home)
    write_text_atomic(path, "#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    return path


def ensure_formulator_home(home: Path) -> Path:
    """Create the per-window Formulator home so only its owner can read it.

    data-formulator keeps its credential vault here: ``credentials.db`` next to
    a cleartext ``.vault_key``. chmod also tightens a home created under an
    older umask, so ciphertext and key are never readable by another account.
    """
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    return home


def write_connectors(home: Path) -> Path:
    ensure_formulator_home(home)
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
    if "formulator" in handles or window.formulator_pid_path.exists():
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
        "BROWSER": str(no_browser_path(home)),
    }
    argv = [
        formulator_bin(),
        "--data-dir",
        str(home),
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
    return window.formulator_pid_path


def stop_formulator(window: Window, *, force: bool = False) -> dict[str, str]:
    """Stop this window's Formulator and release its lease.

    ``force`` (or ``FOUNDRY_FORMULATOR_FORCE_STOP=1``) releases the lease when
    the pid's identity cannot be confirmed -- a host without ``ps`` -- so a
    window is never permanently un-reimportable. It never kills an unverified
    pid; the payload says the process was left running.

    Held under the same lifecycle lock as launch and re-import: all three move
    the lease, and a re-import that read the lease while a stop was half done
    would cross the fence on a Formulator that is still serving.
    """
    with window.lifecycle_lock():
        return _stop_locked(window, force=force)


def _stop_locked(window: Window, *, force: bool) -> dict[str, str]:
    forced = force or os.environ.get(FORCE_STOP_ENV) == "1"
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
                    if not forced:
                        reason = (
                            "ps is not installed on this host"
                            if command is None
                            else "ps does not report this pid"
                        )
                        raise LockRefused(
                            f"Formulator process identity is unavailable ({reason}); "
                            f"install ps, or release the lease with {FORCE_STOP_ENV}=1 "
                            "and stop the process yourself"
                        )
                    pid_path.unlink(missing_ok=True)
                    stop_lease(window)
                    return {
                        "released": "formulator",
                        "window_id": window.id,
                        "forced": "1",
                        "unverified_pid": str(pid),
                        "warning": "lease released without stopping the process; kill it yourself",
                    }
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


def _pid_command(pid: int) -> str | None:
    """The pid's command line.

    ``None`` means ``ps`` itself is unavailable -- a distroless or
    python:slim host, where the exec raises OSError rather than exiting
    non-zero. ``""`` means ``ps`` ran and knows nothing about this pid. The two
    call for opposite answers: a missing tool must not be read as a missing
    process, and a missing process must not be read as a missing tool.
    """
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
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


def _registered_handles(window: Window) -> list[str]:
    if not window.handles_path.exists():
        return []
    return json.loads(window.handles_path.read_text())


def _refuse_second_launch(window: Window) -> None:
    """Refuse a launch this window already has an owner for.

    Runs before anything is created, so a refusal never touches the live
    instance's pid file, handle, or home.
    """
    pid_path = _pid_path(window)
    if pid_path.exists():
        raise LockRefused(
            f"a Formulator already owns this window (pid file {pid_path}); "
            "run stop-formulator first"
        )
    if "formulator" in _registered_handles(window):
        raise LockRefused(
            "the formulator handle is still registered for this window; "
            "run stop-formulator first"
        )


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _refuse_if_port_busy(url: str) -> None:
    """Refuse when someone already listens on the Formulator port.

    The port is one fixed default shared by every window, so an earlier
    Formulator serving a different period would answer the readiness probe and
    the leader would open another period's locked catalog.
    """
    parts = urllib.parse.urlsplit(url)
    port = parts.port
    if port is None:
        raise LockRefused(f"Formulator url has no port: {url}")
    if _port_in_use(port, parts.hostname or "127.0.0.1"):
        raise LockRefused(
            f"port {port} is already served by another process; stop it or set "
            "FOUNDRY_FORMULATOR_PORT to a free port"
        )


def _claim_pid_file(window: Window) -> Path:
    """Atomically claim this window's single-instance Formulator lease.

    ``O_CREAT | O_EXCL`` is the test-and-set: two launches racing on one window
    cannot both win it, so the loser refuses instead of orphaning the winner's
    process. The pid lands in the file as soon as Popen returns.
    """
    ensure_formulator_home(formulator_home(window))
    pid_path = _pid_path(window)
    try:
        fd = os.open(str(pid_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise LockRefused(
            "a Formulator already owns this window; run stop-formulator first"
        ) from exc
    os.close(fd)
    return pid_path


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
    """Start this window's Formulator under the window's lifecycle lock.

    The lease is claimed before the spawn but the ``formulator`` handle is only
    registered once the server answered, so between them a re-import would see
    an empty handle list and cross the fence while a Formulator was coming up.
    Holding the same lock ``reimport`` holds makes the whole startup one step.
    """
    spec = launch_spec(window)
    if os.environ.get("FOUNDRY_SKIP_FORMULATOR_EXEC") == "1":
        return spec
    with window.lifecycle_lock():
        return _launch_locked(window, spec)


def _launch_locked(window: Window, spec: dict[str, str | list[str]]) -> dict[str, str | list[str]]:
    argv = list(spec["argv"])
    resolved = shutil.which(str(argv[0]))
    if resolved is None:
        raise LockRefused("Data Formulator binary is not installed")
    argv[0] = resolved
    home = Path(spec["home"])
    url = str(spec["url"])
    _refuse_second_launch(window)
    _refuse_if_port_busy(url)
    # From here the window is ours: the claim is atomic, so every cleanup below
    # tears down our own process and never a live owner's.
    pid_path = _claim_pid_file(window)
    proc: subprocess.Popen[bytes] | None = None
    handle = None
    try:
        write_connectors(home)
        write_no_browser(home)
        handle = (home / "formulator.log").open("ab")
        proc = subprocess.Popen(
            argv,
            env=process_env(dict(spec["env"])),
            cwd=str(spec["home"]),
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )
        # Record ownership before the readiness wait, not after it. A CLI killed
        # during those 8s leaves a detached child (start_new_session=True); the
        # pid file is the only thing that lets stop-formulator find it.
        write_text_atomic(pid_path, str(proc.pid) + "\n")
        if not _ready(url, proc):
            raise LockRefused("Data Formulator did not become ready")
        if proc.poll() is not None:
            raise LockRefused("Data Formulator exited while coming up")
        command = _pid_command(proc.pid)
        if command is None:
            # No ps on this host (distroless, python:slim). Refusing here would
            # make the Formulator unstartable there, so fall back to what this
            # process can prove on its own -- the port was free before the
            # spawn and our own child is the one still running -- and say on
            # the record that the identity was not confirmed.
            spec = {**spec, "identity": "unconfirmed: ps is not installed on this host"}
            print(
                "launch-formulator: ps is not installed; the served process could not be "
                "confirmed as this window's Data Formulator",
                file=sys.stderr,
            )
        elif not command:
            raise LockRefused(
                f"ps does not report pid {proc.pid}; cannot confirm the Data "
                "Formulator process identity"
            )
        elif not _command_matches_window(command, home):
            raise LockRefused(f"{url} is served by another process, not this window's Data Formulator")
        window.register_handle("formulator")
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt during the readiness
        # wait must still tear the child down and release the lease.
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        pid_path.unlink(missing_ok=True)
        stop_lease(window)
        raise
    finally:
        if handle is not None:
            handle.close()
    return spec
