"""The desktop app's own suite, run from the one place that runs everything.

Node tests that only run when someone remembers to `cd app && npm test` are node
tests that stop running. The bundle suite is already wired this way in
`test_plugin.py`; this is the same wiring for the app.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
NPX = shutil.which("npx")
NODE = shutil.which("node")
APP_LOG_DIR = ROOT / "build" / "verification" / "app-tests"


def _summarize_output(text: str, *, head: int = 2000, tail: int = 6000) -> str:
    if len(text) <= head + tail:
        return text
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n... <omitted {omitted} chars; full log persisted> ...\n\n{text[-tail:]}"


def _available_parallelism() -> str:
    if NODE is None:
        return "unknown"
    result = subprocess.run(
        [NODE, "-e", "const os=require('node:os'); console.log(os.availableParallelism?.() ?? os.cpus().length)"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_logged(name: str, args: list[str], *, timeout: int = 600) -> tuple[subprocess.CompletedProcess[str], Path]:
    APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = APP_LOG_DIR / f"{name}-{time.time_ns()}.log"
    try:
        result = subprocess.run(
            args,
            cwd=APP,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr)
        returncode = -1
        stderr += f"\nTimed out after {timeout}s"
        result = subprocess.CompletedProcess(args, returncode, stdout, stderr)
    log.write_text(
        "$ " + " ".join(args) + "\n"
        + f"cwd={APP}\n"
        + f"returncode={returncode}\n"
        + f"availableParallelism={_available_parallelism()}\n"
        + "\n--- stdout ---\n" + stdout
        + "\n--- stderr ---\n" + stderr,
        encoding="utf-8",
    )
    return result, log

needs_app = pytest.mark.skipif(
    NPX is None or not (APP / "node_modules").is_dir(),
    reason="run `npm install` in app/ first",
)


@needs_app
def test_app_suite_runs() -> None:
    result, log_path = _run_logged("vitest-run", [NPX, "vitest", "run", "--maxWorkers=2"])
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"full vitest log: {log_path}\n{_summarize_output(output)}"


@needs_app
def test_app_typechecks() -> None:
    """Both projects, because they compile under different settings.

    The renderer is ESM with the DOM lib; the electron half is CommonJS without
    it. A file that passes one can fail the other, and only the electron project
    emits, so a break there is a build that ships nothing.
    """
    for project in ("tsconfig.json", "tsconfig.electron.json"):
        result, log_path = _run_logged(f"tsc-{project.replace('/', '-')}", [NPX, "tsc", "-p", project, "--noEmit"])
        output = result.stdout + result.stderr
        assert result.returncode == 0, f"{project}: full tsc log: {log_path}\n{_summarize_output(output)}"


def test_the_app_is_a_caller_not_a_mutator() -> None:
    """KTD2, asserted from this side of the language boundary too.

    The app's own suite checks its imports. This checks the claim the plan makes
    about the whole product: nothing under `app/` opens the catalog, and the
    only names it uses to reach the store are subcommands the CLI declares.
    """
    import re

    # Imports, not prose. These files talk about DuckDB and about not reading
    # `var/`, and an assertion that matched the word would forbid saying so.
    imports = re.compile(r"""^\s*(?:import[^\n]*from\s*['"]([^'"]+)['"]|const[^\n]*=\s*require\(['"]([^'"]+)['"]\))""", re.M)
    banned = {"node:fs", "node:fs/promises", "fs", "duckdb"}

    # Scoped to the files that face the store. `harness/wiring.ts` uses `fs` to
    # place a link inside the harness home, which is this app's own directory and
    # has nothing to do with the catalog -- a blanket ban there would be a rule
    # about the wrong thing.
    for name in ("foundry.ts", "reads.ts", "ipc/register.ts"):
        path = APP / "electron" / name
        for match in imports.finditer(path.read_text(encoding="utf-8")):
            module = match.group(1) or match.group(2)
            assert module not in banned, f"{path} imports {module}"

    # And the claim the ban was standing in for: nothing anywhere under
    # `electron/` builds a path into the store. The var root is a string the CLI
    # is handed, never a directory this process walks.
    store = re.compile(r"""['"][^'"]*\bvar\b[^'"]*/(?:windows|tasks|current)""")
    sources = [path for path in (APP / "electron").rglob("*.ts") if not path.name.endswith(".test.ts")]
    assert sources, "no electron sources found"
    for path in sources:
        assert not store.search(path.read_text(encoding="utf-8")), f"{path} names a path inside the store"


def test_every_command_the_app_calls_exists_on_the_cli(capsys: pytest.CaptureFixture[str]) -> None:
    """A view that names a subcommand the CLI does not have fails at runtime only.

    The app reaches the store by naming subcommands in strings, and no
    typechecker on that side can hold them to the argparse table. Read the table
    itself rather than probing by invocation: `deliverable-text` exits 2 for a
    missing `--sha` as readily as an unknown command would, so an exit code
    cannot tell the two apart.
    """
    import re

    from foundry.cli import main

    with pytest.raises(SystemExit):
        main(["--var", "/unused", "--help"])
    helped = capsys.readouterr().out
    block = helped.split("{", 1)[1].split("}", 1)[0]
    available = {name.strip() for name in block.split(",") if name.strip()}
    assert "task-show" in available, helped

    text = (APP / "electron" / "reads.ts").read_text(encoding="utf-8")
    named = set(re.findall(r"runFoundry(?:Json)?(?:<[^>]*>)?\(\s*[^,]+,\s*'([a-z-]+)'", text))
    named |= set(re.findall(r"'([a-z-]+)',?$", text.split("export const READS")[1].split("} as const")[0], re.M))
    assert named, "no subcommand names found in reads.ts"
    unknown = sorted(name for name in named if name not in available)
    assert not unknown, f"reads.ts names commands the CLI does not have: {unknown}"
