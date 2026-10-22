"""Local calculation runner with a real, fail-closed macOS sandbox.

The caller is a trusted broker: copy the selected input versions into
``workspace/inputs`` before calling. ``workspace/uploads`` is also readable.
Canonical task storage is never granted merely because it is under workspace.
Each invocation can write only its own ``scratch/<run_id>/output`` directory.

macOS sandbox(7) documents inherited restrictions and pre-opened descriptor
exceptions. We pass no inherited descriptors, use a fresh environment, deny
forking, and kill the process group on timeout. sandbox-exec(1) is deprecated;
when it cannot initialize, this capability is unavailable, never run bare.
"""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import sysconfig
import time
from typing import Any, Callable, Literal
import uuid

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
MAX_CODE_BYTES = 256 * 1024
MAX_STREAM_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_FILES = 256
_READY = b"\x1eFOUNDRY_RUNNER_READY\x1e\n"


def runner_capabilities() -> dict[str, Any]:
    """Report the installed primitive; each execution verifies initialization."""
    available = sys.platform == "darwin" and SANDBOX_EXEC.is_file() and os.access(SANDBOX_EXEC, os.X_OK)
    return {
        "available": available,
        "backend": "macos-seatbelt" if available else None,
        "languages": ["python", "shell"] if available else [],
        "network": False,
        "child_processes": False,
        "reason": None if available else "An OS-isolated runner is unavailable on this platform.",
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    # Never let the trusted manifest reader follow a link made by user code.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> list[tuple[Path, int]]:
    files: list[tuple[Path, int]] = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in [*dirs, *names]:
            path = Path(directory) / name
            try:
                mode = path.lstat()
            except FileNotFoundError:
                continue  # User code may replace an output while we measure it.
            if stat.S_ISLNK(mode.st_mode) or not (stat.S_ISREG(mode.st_mode) or stat.S_ISDIR(mode.st_mode)):
                raise ValueError(f"Unsupported non-regular file: {path.relative_to(root)}")
            if stat.S_ISREG(mode.st_mode):
                if mode.st_nlink != 1:
                    raise ValueError(f"Hard-linked file is not an isolated input/output: {path.relative_to(root)}")
                files.append((path, mode.st_size))
    return files


def _profile(output: Path, script: Path, input_dirs: list[Path], runtime: list[Path], executable: Path,
             context_file: Path | None = None) -> str:
    read_dirs = [output, *input_dirs, *runtime, Path("/System/Library"), Path("/usr/lib")]
    read_files = [Path("/"), script, executable, Path("/bin/bash"), Path("/dev/null"), Path("/dev/random"), Path("/dev/urandom")]
    if context_file:
        read_files.append(context_file)
    ancestors = {parent for path in [*read_dirs, *read_files] for parent in path.parents}
    quote = lambda path: json.dumps(str(path), ensure_ascii=False)
    rules = ["(version 1)", "(deny default)", "(allow sysctl-read)"]
    rules += [f"(allow file-read-metadata (literal {quote(path)}))" for path in sorted(ancestors)]
    rules += [f"(allow file-read* (subpath {quote(path)}))" for path in read_dirs]
    rules += [f"(allow file-read* (literal {quote(path)}))" for path in read_files]
    rules += [
        f"(allow file-write* (subpath {quote(output)}) (literal \"/dev/null\"))",
        f"(allow process-exec (literal {quote(executable)}) (literal \"/bin/bash\"))",
    ]
    # No process-fork, networking, arbitrary mach service, or filesystem grant.
    return "\n".join(rules)


def _kill(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _capture(process: subprocess.Popen[bytes], output: Path, timeout: float, cancel_check: Callable[[], bool] | None = None) -> tuple[bytes, bytes, str | None]:
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    stop_reason: str | None = None
    deadline = time.monotonic() + timeout
    next_output_check = time.monotonic()
    with selectors.DefaultSelector() as selector:
        assert process.stdout is not None and process.stderr is not None
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            now = time.monotonic()
            if stop_reason is None and cancel_check is not None and cancel_check():
                stop_reason = "cancelled"
                _kill(process)
            if stop_reason is None and now >= deadline:
                stop_reason = "timeout"
                _kill(process)
            if stop_reason is None and now >= next_output_check:
                try:
                    files = _files(output)
                    if len(files) > MAX_OUTPUT_FILES or sum(size for _, size in files) > MAX_OUTPUT_BYTES:
                        stop_reason = "output_limit"
                except (OSError, ValueError):
                    stop_reason = "invalid_output"
                if stop_reason:
                    _kill(process)
                next_output_check = now + 0.1
            for key, _ in selector.select(timeout=0.05):
                data = os.read(key.fileobj.fileno(), 64 * 1024)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                target = chunks[key.data]
                limit = MAX_STREAM_BYTES + (len(_READY) if key.data == "stderr" else 0)
                remaining = max(0, limit - len(target))
                target.extend(data[:remaining])
                if len(data) > remaining and stop_reason is None:
                    stop_reason = "output_limit"
                    _kill(process)
    return bytes(chunks["stdout"]), bytes(chunks["stderr"]), stop_reason


def run_script(
    workspace: Path,
    code: str,
    *,
    language: Literal["python", "shell"] = "python",
    timeout: float = 30,
    cancel_check: Callable[[], bool] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute code with read-only inputs and private scratch; return JSON data.

    Python can use installed packages but ignores user sites, environment path
    injections, and executable .pth hooks. Shell supports builtins and exec of
    /bin/bash (and the Python interpreter in development); creating subprocesses
    is denied. Frozen bundles expose Python through language="python".
    Output files have a hard per-file limit and a periodically enforced aggregate
    limit; this is not a filesystem quota. Results are candidates for broker
    archival, not canonical financial records.
    """
    started = time.monotonic()
    result: dict[str, Any] = {
        "status": "failed", "stdout": "", "stderr": "", "exit_code": None,
        "outputs": [], "inputs": [], "run_id": uuid.uuid4().hex,
        "language": language, "code": code, "code_hash": None,
        "environment": runner_capabilities(),
    }
    if not result["environment"]["available"]:
        result.update(status="unavailable", stderr=result["environment"]["reason"])
        return result
    if language not in ("python", "shell") or not isinstance(code, str):
        result["stderr"] = "language must be python or shell and code must be text."
        return result
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        result["stderr"] = "Script exceeds the 256 KiB code limit."
        return result
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        result["stderr"] = "timeout must be greater than 0 and at most 300 seconds."
        return result
    result["code_hash"] = hashlib.sha256(code.encode()).hexdigest()
    process: subprocess.Popen[bytes] | None = None
    try:
        workspace = Path(workspace).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("workspace must be an existing directory.")
        input_dirs = []
        for name in ("inputs", "uploads"):
            path = workspace / name
            if path.is_symlink():
                raise ValueError(f"{name} must not be a symbolic link.")
            if path.exists():
                if not path.is_dir():
                    raise ValueError(f"{name} must be a directory.")
                input_dirs.append(path)
                result["inputs"] += [
                    {"path": str(file.relative_to(workspace)), "size": size, "sha256": _hash_file(file)}
                    for file, size in _files(path)
                ]
        scratch = workspace / "scratch"
        if scratch.is_symlink():
            raise ValueError("scratch must not be a symbolic link.")
        scratch.mkdir(exist_ok=True, mode=0o700)
        run_root = scratch / result["run_id"]
        run_root.mkdir(mode=0o700)
        context_file = None
        if context is not None:
            context_file = run_root / "context.json"
            context_file.write_text(json.dumps(context, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            context_file.chmod(0o400)
            result["inputs"].append({"path": str(context_file.relative_to(workspace)),
                                     "size": context_file.stat().st_size, "sha256": _hash_file(context_file)})
        output = run_root / "output"
        output.mkdir(mode=0o700)
        result["workspace"] = str(output)
        executable = Path(sys.executable).resolve(strict=True)
        site_paths = sorted({str(Path(sysconfig.get_paths()[key]).resolve()) for key in ("purelib", "platlib")})
        frozen = bool(getattr(sys, "frozen", False))
        if frozen:
            runtime = [Path(sys._MEIPASS).resolve()]
            site_paths = []
        else:
            runtime = list(dict.fromkeys([Path(sys.base_prefix).resolve(), *(Path(path) for path in site_paths)]))
        # -I -S rejects inherited PYTHONPATH, user sites and package .pth hooks.
        # Hard limits are set before user code, including before shell exec.
        bootstrap = (
            "import os, sys, resource\n"
            f"resource.setrlimit(resource.RLIMIT_FSIZE, ({MAX_OUTPUT_BYTES}, {MAX_OUTPUT_BYTES}))\n"
            f"resource.setrlimit(resource.RLIMIT_CPU, ({math.ceil(timeout) + 1}, {math.ceil(timeout) + 1}))\n"
            "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
            "resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))\n"
            f"sys.path.extend({site_paths!r})\n"
            f"os.write(2, {_READY!r})\n"
        )
        if language == "python":
            bootstrap += f"exec(compile({code!r}, '<analysis-script>', 'exec'), {{'__name__': '__main__'}})\n"
        else:
            bootstrap += f"os.execv('/bin/bash', ['/bin/bash', '--noprofile', '--norc', '--posix', '-c', {code!r}])\n"
        script = run_root / "script.py"
        script.write_text(bootstrap, encoding="utf-8")
        script.chmod(0o400)
        profile = _profile(output, script, input_dirs, runtime, executable, context_file)
        env = {
            "PATH": f"{executable.parent}:/usr/bin:/bin", "HOME": str(output),
            "TMPDIR": str(output), "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
            "FOUNDRY_INPUTS": str(workspace / "inputs"), "FOUNDRY_UPLOADS": str(workspace / "uploads"),
            "FOUNDRY_OUTPUTS": str(output),
        }
        if context is not None:
            env["FOUNDRY_CONTEXT"] = str(context_file)
        if not frozen:
            env["FOUNDRY_PYTHON"] = str(executable)
        result["environment"].update(
            python=sys.version.split()[0], executable=str(executable),
            platform=sys.platform, frozen=frozen, environment_keys=sorted(env),
            packages={distribution.metadata["Name"]: distribution.version
                      for distribution in metadata.distributions(path=site_paths or [str(runtime[0])])
                      if distribution.metadata.get("Name")},
            sandbox_profile_hash=hashlib.sha256(profile.encode()).hexdigest(),
            limits={"timeout_seconds": timeout, "stream_bytes": MAX_STREAM_BYTES,
                    "output_bytes": MAX_OUTPUT_BYTES, "output_files": MAX_OUTPUT_FILES},
        )
        interpreter_args = ["--_foundry-runner-bootstrap", str(script)] if frozen else ["-I", "-S", "-B", str(script)]
        process = subprocess.Popen(
            [str(SANDBOX_EXEC), "-p", profile, str(executable), *interpreter_args],
            cwd=output, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True, start_new_session=True,
        )
        stdout, stderr, stop_reason = _capture(process, output, timeout, cancel_check)
        ready = stderr.startswith(_READY)
        if ready:
            stderr = stderr[len(_READY):]
        result.update(stdout=stdout.decode("utf-8", errors="replace"), stderr=stderr.decode("utf-8", errors="replace"), exit_code=process.returncode)
        result["status"] = stop_reason or ("succeeded" if process.returncode == 0 else "failed")
        if not ready:
            result["status"] = stop_reason or "unavailable"
            result["stderr"] = "OS-isolated runner did not initialize. " + result["stderr"]
        files = _files(output)
        if len(files) > MAX_OUTPUT_FILES or sum(size for _, size in files) > MAX_OUTPUT_BYTES:
            result.update(status="output_limit", stderr=result["stderr"] + "\nOutput files exceed runner limits.")
        elif ready:
            result["outputs"] = [
                {"path": str(file.relative_to(output)), "size": size, "sha256": _hash_file(file)}
                for file, size in sorted(files)
            ]
    except (OSError, ValueError) as exc:
        if process is not None and process.poll() is None:
            _kill(process)
            process.wait()
        result.update(status="failed", stderr=f"{result['stderr']}\n{exc}".strip())
    finally:
        if process is not None:
            if process.poll() is None:
                _kill(process)
                process.wait()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result
