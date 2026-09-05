from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import socket

import pytest

from foundry import runner


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    if not runner.runner_capabilities()["available"]:
        pytest.skip("Real macOS sandbox-exec is not installed on this platform")
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def test_python_computes_from_readonly_inputs_and_generates_chart(workspace: Path, monkeypatch) -> None:
    inputs = workspace / "inputs"
    inputs.mkdir()
    source = inputs / "actual.csv"
    source.write_text("amount\n0.10\n0.20\n")
    monkeypatch.setenv("OPENAI_API_KEY", "non-sensitive-provider-fixture")
    monkeypatch.setenv("PYTHONPATH", str(workspace.parent))
    result = runner.run_script(workspace, '''
import csv, os
from decimal import Decimal
from pathlib import Path
import openpyxl
assert "OPENAI_API_KEY" not in os.environ
assert "PYTHONPATH" not in os.environ
with (Path(os.environ["FOUNDRY_INPUTS"]) / "actual.csv").open() as source:
    total = sum((Decimal(row["amount"]) for row in csv.DictReader(source)), Decimal(0))
print(total)
Path("amount.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><rect width="{total * 100}" height="10"/></svg>')
''')
    assert result["status"] == "succeeded", result
    assert result["stdout"] == "0.30\n"
    assert result["inputs"][0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["outputs"][0]["path"] == "amount.svg"
    assert result["outputs"][0]["sha256"] == hashlib.sha256((Path(result["workspace"]) / "amount.svg").read_bytes()).hexdigest()
    assert result["environment"]["network"] is False
    json.dumps(result)  # Public result can be persisted as a Run without coercion.


def test_shell_builtin_writes_only_own_scratch(workspace: Path) -> None:
    result = runner.run_script(workspace, "printf '42.00' > amount.txt", language="shell")
    assert result["status"] == "succeeded", result
    assert (Path(result["workspace"]) / "amount.txt").read_text() == "42.00"


@pytest.mark.parametrize("access", ["read", "write", "metadata"])
def test_arbitrary_local_files_and_canonical_are_denied(workspace: Path, access: str) -> None:
    secret_fixture = workspace.parent / "outside.txt"
    secret_fixture.write_text("non-sensitive private fixture")
    canonical = workspace / "datasets" / "history.json"
    canonical.parent.mkdir()
    canonical.write_text("original financial history")
    action = {"read": "read_text()", "write": "write_text('changed')", "metadata": "stat()"}[access]
    code = f'''
from pathlib import Path
for target in [{str(secret_fixture)!r}, {str(canonical)!r}]:
    try:
        Path(target).{action}
    except PermissionError:
        print("denied")
    else:
        raise AssertionError("sandbox allowed forbidden access")
'''
    result = runner.run_script(workspace, code)
    assert result["status"] == "succeeded", result
    assert result["stdout"] == "denied\ndenied\n"
    assert canonical.read_text() == "original financial history"
    assert secret_fixture.read_text() == "non-sensitive private fixture"


def test_inputs_and_prior_scratch_are_immutable(workspace: Path) -> None:
    inputs = workspace / "inputs"
    inputs.mkdir()
    source = inputs / "actual.txt"
    source.write_text("10.00")
    previous = runner.run_script(workspace, "open('old.txt', 'w').write('old output')")
    prior_file = Path(previous["workspace"]) / "old.txt"
    result = runner.run_script(workspace, f'''
from pathlib import Path
for target in [{str(source)!r}, {str(prior_file)!r}]:
    try:
        Path(target).write_text("overwritten")
    except PermissionError:
        print("denied")
    else:
        raise AssertionError("history changed")
''')
    assert result["status"] == "succeeded", result
    assert result["stdout"] == "denied\ndenied\n"
    assert source.read_text() == "10.00"
    assert prior_file.read_text() == "old output"


def test_network_denied_against_real_local_listener(workspace: Path) -> None:
    # A live, harmless local endpoint distinguishes denial from absent network.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = listener.getsockname()
        result = runner.run_script(workspace, f'''
import socket
try:
    with socket.create_connection({address!r}, timeout=1):
        raise AssertionError("network escaped")
except PermissionError:
    print("network denied")
''')
        assert result["status"] == "succeeded", result
        assert result["stdout"] == "network denied\n"
        listener.settimeout(0.05)
        with pytest.raises(TimeoutError):
            listener.accept()


def test_detached_child_process_cannot_escape(workspace: Path) -> None:
    marker = workspace.parent / "escaped.txt"
    result = runner.run_script(workspace, f'''
import os, subprocess
try:
    subprocess.Popen([os.environ["FOUNDRY_PYTHON"], "-c", "open({str(marker)!r}, 'w').write('escaped')"], start_new_session=True)
except PermissionError:
    print("child denied")
else:
    raise AssertionError("detached child escaped")
''')
    assert result["status"] == "succeeded", result
    assert result["stdout"] == "child denied\n"
    assert not marker.exists()


@pytest.mark.parametrize("close_streams", [False, True])
def test_timeout_reaps_process_even_with_closed_streams(workspace: Path, close_streams: bool) -> None:
    result = runner.run_script(workspace, f'''
import os, time
open("pid.txt", "w").write(str(os.getpid()))
if {close_streams!r}:
    os.close(1)
    os.close(2)
time.sleep(10)
''', timeout=0.25)
    assert result["status"] == "timeout", result
    assert result["exit_code"] == -signal.SIGKILL
    pid = int((Path(result["workspace"]) / "pid.txt").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert result["duration_seconds"] < 3


def test_stdout_is_bounded_and_producer_is_killed(workspace: Path) -> None:
    result = runner.run_script(workspace, "import os\nwhile True: os.write(1, b'x' * 65536)")
    assert result["status"] == "output_limit", result
    assert len(result["stdout"]) == runner.MAX_STREAM_BYTES
    assert result["exit_code"] == -signal.SIGKILL


def test_artifact_file_limit_is_enforced(workspace: Path) -> None:
    result = runner.run_script(workspace, f"with open('oversized.bin', 'wb') as output:\n    output.write(b'x' * {runner.MAX_OUTPUT_BYTES + 1})")
    assert result["status"] == "failed", result
    assert "File too large" in result["stderr"]
    assert (Path(result["workspace"]) / "oversized.bin").stat().st_size <= runner.MAX_OUTPUT_BYTES


def test_symlink_cannot_redirect_script_or_manifest_reader(workspace: Path) -> None:
    outside = workspace.parent / "outside.txt"
    outside.write_text("fixture remains intact")
    result = runner.run_script(workspace, f'''
from pathlib import Path
link = Path("escape")
link.symlink_to({str(outside)!r})
try:
    link.read_text()
except PermissionError:
    print("read denied")
else:
    raise AssertionError("read escaped")
try:
    link.write_text("overwritten")
except PermissionError:
    print("write denied")
else:
    raise AssertionError("write escaped")
''')
    assert result["status"] in ("failed", "invalid_output"), result
    assert result["outputs"] == []
    assert outside.read_text() == "fixture remains intact"
    assert "Unsupported non-regular file" in result["stderr"]


def test_symlinked_input_root_is_rejected_before_execution(workspace: Path) -> None:
    (workspace / "inputs").symlink_to(workspace.parent, target_is_directory=True)
    result = runner.run_script(workspace, "print('should not run')")
    assert result["status"] == "failed"
    assert result["exit_code"] is None
    assert "symbolic link" in result["stderr"]


def test_no_unisolated_fallback_on_other_platform(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner.sys, "platform", "linux")
    marker = tmp_path / "must-not-exist"
    result = runner.run_script(tmp_path, f"open({str(marker)!r}, 'w').write('bad')")
    assert result["status"] == "unavailable"
    assert not marker.exists()


def test_installed_but_unusable_sandbox_fails_closed(workspace: Path, monkeypatch) -> None:
    primitive = workspace.parent / "unusable-sandbox"
    primitive.write_text("#!/bin/sh\nprintf 'sandbox unavailable' >&2\nexit 72\n")
    primitive.chmod(0o700)
    monkeypatch.setattr(runner, "SANDBOX_EXEC", primitive)
    result = runner.run_script(workspace, "open('must-not-exist', 'w').write('bad')")
    assert result["status"] == "unavailable"
    assert result["exit_code"] == 72
    assert result["outputs"] == []
    assert "did not initialize" in result["stderr"]


@pytest.mark.parametrize("label", ["财务分析", 'quote"with\\slash'])
def test_profile_preserves_unicode_and_quotes(workspace: Path, label: str) -> None:
    root = workspace / label
    root.mkdir()
    result = runner.run_script(root, 'print("财务计算")')
    assert result["status"] == "succeeded", result
    assert result["stdout"] == "财务计算\n"


def test_aggregate_output_limit(workspace: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "MAX_OUTPUT_BYTES", 16 * 1024)
    result = runner.run_script(workspace, """
for name in ("first.bin", "second.bin"):
    with open(name, "wb") as output:
        output.write(b"x" * 16384)
""")
    assert result["status"] == "output_limit", result
    assert result["outputs"] == []


def test_input_hardlink_is_rejected(workspace: Path) -> None:
    source = workspace.parent / "canonical-fixture"
    source.write_text("history")
    inputs = workspace / "inputs"
    inputs.mkdir()
    os.link(source, inputs / "linked")
    result = runner.run_script(workspace, "print('must not run')")
    assert result["status"] == "failed", result
    assert result["exit_code"] is None
    assert "Hard-linked" in result["stderr"]


def test_cancel_callback_reaps_sandbox_process(workspace: Path) -> None:
    import time
    started = time.monotonic()
    result = runner.run_script(
        workspace,
        "import os,time\nopen('pid.txt','w').write(str(os.getpid()))\ntime.sleep(10)",
        cancel_check=lambda: time.monotonic() - started > 0.25,
    )
    assert result["status"] == "cancelled", result
    assert result["exit_code"] == -signal.SIGKILL
    pid = int((Path(result["workspace"]) / "pid.txt").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_private_frozen_bootstrap_refuses_bare_execution(tmp_path: Path, capsys) -> None:
    from foundry.runner_entry import BOOTSTRAP_FLAG, dispatch
    marker = tmp_path / "unisolated"
    script = tmp_path / "script.py"
    script.write_text(f"open({str(marker)!r}, 'w').write('bad')")
    assert dispatch([BOOTSTRAP_FLAG, str(script)]) == 3
    assert "outside the required OS sandbox" in capsys.readouterr().err
    assert not marker.exists()
