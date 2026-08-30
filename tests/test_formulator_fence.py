from __future__ import annotations

import contextlib
import http.server
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Iterator

import pytest
import yaml
from openpyxl import Workbook

import importlib.util

import foundry.launch_formulator as lf
from foundry.errors import LockRefused, WindowBusy
from foundry.launch_formulator import (
    ENV_ALLOWLIST,
    launch_formulator,
    launch_spec,
    process_env,
    purge_formulator_home,
    stop_formulator,
    stop_lease,
    write_connectors,
)
from foundry.window import WindowStore

_LOADER = Path(__file__).resolve().parents[1] / "formulator-plugin" / "locked_catalog_data_loader.py"
_SPEC = importlib.util.spec_from_file_location("locked_catalog_data_loader", _LOADER)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
LockedCatalogLoader = _MOD.LockedCatalogLoader


def _xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _locked(tmp_path: Path):
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    window.lock()
    return store, window


def test_loader_lists_only_locked_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    tables = {item["name"]: item["metadata"]["row_count"] for item in loader.list_tables()}
    assert tables["gl"] == 1
    assert loader.list_tables()[0]["metadata"]["columns"][0]["name"]
    assert "notes" not in tables
    hashes = window.hashes()
    loader.fetch_table("gl")
    assert window.hashes() == hashes


def test_loader_requires_fixed_window_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _ = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.delenv("FOUNDRY_WINDOW_ID", raising=False)
    with pytest.raises(LockRefused, match="FOUNDRY_WINDOW_ID"):
        LockedCatalogLoader()


def test_loader_stays_bound_to_launch_window_after_current_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    drop = tmp_path / "drop2"
    next_window = window.reimport(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 9]])}],
        drop_dir=drop,
    )
    next_window.lock()
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    table_names = {item["name"] for item in loader.list_tables()}
    assert "gl" in table_names
    assert "ar" not in table_names


def test_loader_projection_size_and_required_columns_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    assert loader.fetch_table("gl", columns=["amount"], limit=1) == [(100.0,)]
    pytest.importorskip("pyarrow")
    arrow = loader.fetch_data_as_arrow("gl", {"columns": ["amount"], "required_columns": ["amount"], "size": 1})
    assert arrow.column_names == ["amount"]
    assert arrow.num_rows == 1
    with pytest.raises(LockRefused, match="required columns"):
        loader.fetch_data_as_arrow("gl", {"required_columns": ["missing"]})
    with pytest.raises(LockRefused, match="unsupported import options"):
        loader.fetch_data_as_arrow("gl", {"filter": {"amount": 100}})


def test_loader_refuses_before_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused):
        loader.list_tables()


def test_refresh_connector_and_starter_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused):
        loader.refresh()
    with pytest.raises(LockRefused):
        loader.load_connector("mysql")
    with pytest.raises(LockRefused):
        loader.starter_questions()


def test_over_cap_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    monkeypatch.setenv("FOUNDRY_MAX_IMPORT_ROWS", "0")
    loader = LockedCatalogLoader()
    with pytest.raises(LockRefused, match="MAX_IMPORT_ROWS"):
        loader.list_tables()


def test_launch_uses_plugin_dir_and_per_window_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    bin_dir = Path(__file__).resolve().parents[1] / ".venv" / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    spec = launch_spec(window)
    assert "--disable-database" not in spec["argv"]
    assert "--disable-data-connectors" not in spec["argv"]
    assert "--dev" not in spec["argv"]
    assert Path(spec["env"]["DATA_FORMULATOR_HOME"]) == window.store.formulator_dir / window.id
    assert spec["env"]["DF_PLUGIN_DIR"].endswith("formulator-plugin")
    assert spec["env"]["FOUNDRY_WINDOW_ID"] == window.id
    home = Path(spec["home"])
    assert not home.exists()
    connectors = yaml.safe_load(write_connectors(home).read_text())
    assert connectors["connectors"][0]["type"] == "locked_catalog"
    assert connectors["connectors"][0]["auto_connect"] is True
    before = window.hashes()
    stop_lease(window)
    purge_formulator_home(window)
    assert window.hashes() == before
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_missing_binary_fails_without_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    with pytest.raises(LockRefused, match="Data Formulator binary"):
        launch_formulator(window)
    assert not window.handles_path.exists()
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_dry_run_does_not_register_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    bin_dir = Path(__file__).resolve().parents[1] / ".venv" / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FOUNDRY_SKIP_FORMULATOR_EXEC", "1")
    launch_formulator(window)
    assert not window.handles_path.exists()


def test_stop_refuses_to_kill_unrelated_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text(str(os.getpid()))
    window.register_handle("formulator")
    with pytest.raises(LockRefused, match="does not belong"):
        stop_formulator(window)
    assert not home.exists()


def test_stop_cleans_corrupt_pid_and_handle(tmp_path: Path) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text("not-a-pid\n")
    window.register_handle("formulator")

    with pytest.raises(LockRefused, match="pid is invalid"):
        stop_formulator(window)

    assert not home.exists()
    assert "formulator" not in window.handles_path.read_text()


def test_purge_refuses_active_formulator_lease(tmp_path: Path) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text("123\n")
    window.register_handle("formulator")

    with pytest.raises(LockRefused, match="stop-formulator"):
        purge_formulator_home(window)

    assert home.exists()


# --- launch/stop guards -------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _decoy_server(port: int) -> Iterator[None]:
    """An unrelated HTTP server on the Formulator port -- e.g. another window's."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"not this window")

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _fake_formulator_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a `data_formulator` on PATH that starts but never binds the port."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "data_formulator"
    script.write_text("#!/bin/sh\nexec sleep 300\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")


def _handles(window) -> list[str]:
    if not window.handles_path.exists():
        return []
    return list(json.loads(window.handles_path.read_text()))


def test_formulator_home_is_owner_only(tmp_path: Path) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    home.chmod(0o755)
    write_connectors(home)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_credential_vault_key_can_live_outside_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "CREDENTIAL_VAULT_KEY" in ENV_ALLOWLIST
    monkeypatch.setenv("CREDENTIAL_VAULT_KEY", "vault-key-stays-in-env")
    assert process_env({})["CREDENTIAL_VAULT_KEY"] == "vault-key-stays-in-env"


def test_pid_command_separates_a_missing_ps_from_a_missing_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """None means the tool is absent; "" means the tool answered and knows nothing."""
    assert lf._pid_command(os.getpid())
    assert lf._pid_command(2**31 - 1) == ""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert lf._pid_command(os.getpid()) is None


def test_stop_without_ps_refuses_then_force_releases_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text(f"{os.getpid()}\n")
    window.register_handle("formulator")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    with pytest.raises(LockRefused, match="identity is unavailable"):
        stop_formulator(window)
    assert (home / "pid").exists()
    assert "formulator" in _handles(window)

    result = stop_formulator(window, force=True)
    assert result["forced"] == "1"
    assert result["unverified_pid"] == str(os.getpid())
    assert not home.exists()
    assert _handles(window) == []


def test_second_launch_refuses_and_leaves_the_live_owner_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    monkeypatch.setattr(lf, "_ready", lambda *args, **kwargs: False)
    home = window.store.formulator_dir / window.id
    home.mkdir(parents=True)
    (home / "pid").write_text("4242\n")
    window.register_handle("formulator")

    with pytest.raises(LockRefused, match="stop-formulator first"):
        launch_formulator(window)

    assert (home / "pid").read_text() == "4242\n"
    assert "formulator" in _handles(window)


def test_launch_refuses_while_the_formulator_handle_is_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    monkeypatch.setattr(lf, "_ready", lambda *args, **kwargs: False)
    window.register_handle("formulator")

    with pytest.raises(LockRefused, match="stop-formulator first"):
        launch_formulator(window)

    assert "formulator" in _handles(window)


def test_pid_file_is_written_before_the_readiness_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    seen: dict[str, str] = {}

    def fake_ready(url: str, proc, timeout: float = 8.0) -> bool:
        seen["child"] = str(proc.pid)
        seen["recorded"] = (window.store.formulator_dir / window.id / "pid").read_text().strip()
        return False

    monkeypatch.setattr(lf, "_ready", fake_ready)
    with pytest.raises(LockRefused, match="did not become ready"):
        launch_formulator(window)

    assert seen["recorded"] == seen["child"]
    assert not lf._pid_exists(int(seen["child"]))
    assert not (window.store.formulator_dir / window.id).exists()
    assert _handles(window) == []


def test_keyboard_interrupt_during_readiness_tears_down_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    seen: dict[str, str] = {}

    def interrupted(url: str, proc, timeout: float = 8.0) -> bool:
        seen["child"] = str(proc.pid)
        seen["recorded"] = (window.store.formulator_dir / window.id / "pid").read_text().strip()
        raise KeyboardInterrupt

    monkeypatch.setattr(lf, "_ready", interrupted)
    with pytest.raises(KeyboardInterrupt):
        launch_formulator(window)

    assert seen["recorded"] == seen["child"]
    assert not lf._pid_exists(int(seen["child"]))
    assert not (window.store.formulator_dir / window.id).exists()
    assert _handles(window) == []


def test_launch_refuses_when_the_port_already_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    port = _free_port()
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(port))
    with _decoy_server(port):
        with pytest.raises(LockRefused, match="already served by another process"):
            launch_formulator(window)

    assert _handles(window) == []
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_refuses_when_the_child_died_while_the_port_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The EADDRINUSE shape: our Formulator exits, an unrelated server answers."""
    _, window = _locked(tmp_path)
    bin_dir = tmp_path / "dead-bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "data_formulator"
    script.write_text("#!/bin/sh\nexit 3\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    port = _free_port()
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(port))
    # Bind the decoy after the pre-flight check, so readiness -- and only
    # readiness -- is what the unrelated server satisfies.
    monkeypatch.setattr(lf, "_refuse_if_port_busy", lambda url: None)

    def ready_after_the_child_is_gone(url: str, proc, timeout: float = 8.0) -> bool:
        proc.wait(timeout=5)
        return True

    monkeypatch.setattr(lf, "_ready", ready_after_the_child_is_gone)
    with _decoy_server(port):
        with pytest.raises(LockRefused, match="exited while coming up"):
            launch_formulator(window)

    assert _handles(window) == []
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_refuses_when_the_tracked_pid_is_not_this_windows_formulator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    port = _free_port()
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(port))
    monkeypatch.setattr(lf, "_refuse_if_port_busy", lambda url: None)
    monkeypatch.setattr(lf, "_pid_command", lambda pid: "python -m http.server")
    with _decoy_server(port):
        with pytest.raises(LockRefused, match="served by another process"):
            launch_formulator(window)

    assert _handles(window) == []
    assert not (window.store.formulator_dir / window.id).exists()


def test_launch_refuses_when_process_identity_cannot_be_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    port = _free_port()
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(port))
    monkeypatch.setattr(lf, "_refuse_if_port_busy", lambda url: None)
    monkeypatch.setattr(lf, "_pid_command", lambda pid: "")
    with _decoy_server(port):
        with pytest.raises(LockRefused, match="cannot confirm"):
            launch_formulator(window)

    assert _handles(window) == []
    assert not (window.store.formulator_dir / window.id).exists()


# --- Formulator base-class binding --------------------------------------


class _BlockImport:
    """A meta-path finder that makes one package look uninstalled."""

    def __init__(self, name: str) -> None:
        self.name = name

    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001
        if fullname == self.name or fullname.startswith(self.name + "."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


def _drop_formulator_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(sys.modules):
        if name == "data_formulator" or name.startswith("data_formulator."):
            monkeypatch.delitem(sys.modules, name)


def _load_loader_module():
    spec = importlib.util.spec_from_file_location("locked_catalog_data_loader_probe", _LOADER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_loader_uses_the_stub_base_only_when_formulator_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drop_formulator_modules(monkeypatch)
    monkeypatch.setattr(sys, "meta_path", [_BlockImport("data_formulator"), *sys.meta_path])
    module = _load_loader_module()
    assert module.LockedCatalogLoader.__mro__[1].__name__ == "_DFLoader"


def test_loader_fails_loud_when_the_formulator_symbol_is_renamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drop_formulator_modules(monkeypatch)
    package = types.ModuleType("data_formulator")
    package.__path__ = []  # type: ignore[attr-defined]
    sub = types.ModuleType("data_formulator.data_loader")
    sub.__path__ = []  # type: ignore[attr-defined]
    leaf = types.ModuleType("data_formulator.data_loader.external_data_loader")
    monkeypatch.setitem(sys.modules, "data_formulator", package)
    monkeypatch.setitem(sys.modules, "data_formulator.data_loader", sub)
    monkeypatch.setitem(sys.modules, "data_formulator.data_loader.external_data_loader", leaf)

    with pytest.raises(ImportError):
        _load_loader_module()


def test_loader_fails_loud_when_the_formulator_module_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drop_formulator_modules(monkeypatch)
    package = types.ModuleType("data_formulator")
    package.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "data_formulator", package)
    monkeypatch.setattr(
        sys, "meta_path", [_BlockImport("data_formulator.data_loader"), *sys.meta_path]
    )

    with pytest.raises(ModuleNotFoundError):
        _load_loader_module()


def test_loader_binds_the_real_formulator_base_class_when_installed() -> None:
    pytest.importorskip("data_formulator")
    module = _load_loader_module()
    assert module.LockedCatalogLoader.__mro__[1].__name__ == "ExternalDataLoader"


# --- #25 a launch in flight is inside the re-import fence -------------------


def _kill_launched(window) -> None:
    """Tear down a fake child this test started, without going through stop."""
    pid_path = window.formulator_pid_path
    if pid_path.exists():
        raw = pid_path.read_text().strip()
        if raw:
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(raw), signal.SIGKILL)
        pid_path.unlink(missing_ok=True)
    stop_lease(window)


def test_reimport_refuses_while_the_formulator_lease_is_held(tmp_path: Path) -> None:
    """The lease is claimed before the handle exists; the fence must read it."""
    store, window = _locked(tmp_path)
    window.formulator_pid_path.parent.mkdir(parents=True, exist_ok=True)
    window.formulator_pid_path.write_text("4242\n")

    with pytest.raises(WindowBusy, match="Formulator lease"):
        window.reimport(
            coa=_xlsx(tmp_path / "drop" / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
            named=[{"id": "gl", "path": tmp_path / "drop" / "gl.xlsx"}],
        )

    assert store.current().id == window.id
    assert [path.name for path in store.windows_dir.iterdir()] == [window.id]


def test_reimport_refuses_while_a_launch_is_still_coming_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mid-launch the lease is claimed and no handle is registered yet."""
    store, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    monkeypatch.setattr("foundry.window.LIFECYCLE_LOCK_TIMEOUT", 0.2)
    home = window.formulator_home
    # What `ps` would actually print: `_launch_locked` resolves argv[0] through
    # `shutil.which` before spawning, so the command line carries the absolute
    # path, not the bare name. The identity gate now checks the binary the launch
    # recorded, and a stub that says only `data_formulator` is less realistic
    # than the code it stands in for.
    resolved = shutil.which("data_formulator")
    monkeypatch.setattr(lf, "_pid_command", lambda pid: f"{resolved} --data-dir {home}")
    drop = tmp_path / "drop"
    outcome: list[str] = []

    def racing_ready(url: str, proc, timeout: float = 8.0) -> bool:
        assert window.formulator_pid_path.exists(), "the lease must exist mid-launch"
        assert _handles(window) == [], "the handle is only registered after readiness"

        def attempt() -> None:
            racer = WindowStore(store.var_root).get(window.id)
            try:
                racer.reimport(
                    coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
                    named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 7]])}],
                )
                outcome.append("succeeded")
            except WindowBusy as exc:
                outcome.append(f"refused: {exc}")

        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive()
        return True

    monkeypatch.setattr(lf, "_ready", racing_ready)
    try:
        launch_formulator(window)
        assert _handles(window) == ["formulator"]
    finally:
        _kill_launched(window)

    assert outcome and outcome[0].startswith("refused"), outcome
    assert store.current().id == window.id
    assert [path.name for path in store.windows_dir.iterdir()] == [window.id]


# --- a host without ps can still start a Formulator, loudly -----------------


def test_launch_without_ps_starts_and_records_that_identity_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    monkeypatch.setattr(lf, "_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(lf, "_pid_command", lambda pid: None)
    try:
        spec = launch_formulator(window)
        assert "ps" in str(spec["identity"])
        assert "not installed" in capsys.readouterr().err
        assert _handles(window) == ["formulator"]
    finally:
        _kill_launched(window)


# --- the launch must not pop the operator's browser -------------------------


def test_launch_points_the_child_at_a_no_op_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """data-formulator 0.7.0 opens a browser 1.5s in unless BROWSER swallows it."""
    _, window = _locked(tmp_path)
    _fake_formulator_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FOUNDRY_FORMULATOR_PORT", str(_free_port()))
    browser = Path(str(launch_spec(window)["env"]["BROWSER"]))
    assert browser.parent == window.formulator_home
    seen: dict[str, object] = {}

    def inspect_ready(url: str, proc, timeout: float = 8.0) -> bool:
        seen["exists"] = browser.exists()
        seen["executable"] = os.access(browser, os.X_OK)
        seen["env"] = lf.process_env(dict(launch_spec(window)["env"]))["BROWSER"]
        # webbrowser stops at the first $BROWSER entry that reports success,
        # so the no-op must exist and exit 0 before any real browser is tried.
        seen["exit"] = subprocess.run([str(browser), url], check=False).returncode
        return False

    monkeypatch.setattr(lf, "_ready", inspect_ready)
    with pytest.raises(LockRefused, match="did not become ready"):
        launch_formulator(window)

    assert seen["exists"] is True
    assert seen["executable"] is True
    assert seen["env"] == str(browser)
    assert seen["exit"] == 0


# --- #45 the loader must not accumulate read connections --------------------


def test_loader_opens_one_read_connection_across_many_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Formulator session browses for as long as it stays open."""
    import duckdb

    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    opened: list[str] = []
    real_connect = duckdb.connect

    def counting_connect(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if kwargs.get("read_only"):
            opened.append(str(args[0]))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", counting_connect)
    loader = LockedCatalogLoader()
    assert opened == []
    for _ in range(3):
        loader.list_tables()
    for _ in range(3):
        loader.fetch_table("gl")
    assert len(opened) == 1, f"the loader opened {len(opened)} read connections"
    loader.close()
    loader.list_tables()
    assert len(opened) == 2, "close must release the connection, not wedge the loader"
    loader.close()


def test_loader_still_fails_closed_when_the_window_leaves_the_locked_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binding the window once must not cache the state check with it."""
    store, window = _locked(tmp_path)
    monkeypatch.setenv("FOUNDRY_VAR", str(store.var_root))
    monkeypatch.setenv("FOUNDRY_WINDOW_ID", window.id)
    loader = LockedCatalogLoader()
    assert loader.list_tables()
    window._set_state("Open")
    with pytest.raises(LockRefused, match="read-only after lock"):
        loader.list_tables()
