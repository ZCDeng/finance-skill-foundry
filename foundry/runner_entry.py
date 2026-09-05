"""Early frozen-interpreter entry, before importing the ordinary storage CLI.

This is not an alternate unsandboxed script command. The private bootstrap
refuses unless macOS reports active kernel restrictions. Its caller still
installs the complete deny-default profile in runner.py; this check also catches
accidental direct launches of the private entry during packaging/integration.
"""
from __future__ import annotations

import ctypes
import csv  # Bundle the supported financial script standard library.
import decimal
import json
import os
from pathlib import Path
import random
import resource
import socket
import statistics
import sys


BOOTSTRAP_FLAG = "--_foundry-runner-bootstrap"
SELF_TEST_FLAG = "--_foundry-runner-self-test"


def _sandbox_active() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        library = ctypes.CDLL("/usr/lib/libsandbox.dylib")
        check = library.sandbox_check
        check.restype = ctypes.c_int
        return all(check(os.getpid(), operation, 0) == 1 for operation in (b"process-fork", b"network-outbound"))
    except (AttributeError, OSError):
        return False


def _self_test(workspace: Path) -> int:
    from foundry.runner import run_script

    workspace.mkdir(parents=True, exist_ok=True)
    outside = workspace.parent / "runner-forbidden-fixture.txt"
    outside.write_text("non-sensitive packaging fixture")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    address = listener.getsockname()
    code = f'''
import csv, decimal, statistics, socket, os
import openpyxl
from pathlib import Path
assert decimal.Decimal("0.1") + decimal.Decimal("0.2") == decimal.Decimal("0.3")
assert statistics.mean([1, 2, 3]) == 2
try:
    Path({str(outside)!r}).read_text()
except PermissionError:
    pass
else:
    raise AssertionError("frozen runner escaped its filesystem scope")
try:
    socket.create_connection({address!r}, timeout=1)
except PermissionError:
    pass
else:
    raise AssertionError("frozen runner can connect to the network")
try:
    child = os.fork()
except PermissionError:
    pass
else:
    if child == 0:
        os._exit(1)
    os.waitpid(child, 0)
    raise AssertionError("frozen runner can fork")
Path("chart.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="30" height="10"/></svg>')
print("frozen runner verified")
'''
    try:
        result = run_script(workspace, code)
    finally:
        listener.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "succeeded" and result["stdout"] == "frozen runner verified\n" else 1


def dispatch(argv: list[str]) -> int | None:
    """Return None for ordinary CLI arguments; no canonical imports on bootstrap."""
    if not argv or argv[0] not in (BOOTSTRAP_FLAG, SELF_TEST_FLAG):
        return None
    if len(argv) != 2:
        print("Runner internal entry requires exactly one path.", file=sys.stderr)
        return 2
    if argv[0] == SELF_TEST_FLAG:
        return _self_test(Path(argv[1]).resolve())
    if not _sandbox_active():
        print("Refusing runner bootstrap outside the required OS sandbox.", file=sys.stderr)
        return 3
    # Frozen import paths are supplied by the bundle; parent runner passes only
    # its task environment. No normal CLI imports or task-store constructors run.
    script = Path(argv[1])
    exec(compile(script.read_bytes(), str(script), "exec"), {"__name__": "__main__"})
    return 0
