"""The desktop app's own suite, run from the one place that runs everything.

Node tests that only run when someone remembers to `cd app && npm test` are node
tests that stop running. The bundle suite is already wired this way in
`test_plugin.py`; this is the same wiring for the app.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
NPX = shutil.which("npx")

needs_app = pytest.mark.skipif(
    NPX is None or not (APP / "node_modules").is_dir(),
    reason="run `npm install` in app/ first",
)


@needs_app
def test_app_suite_runs() -> None:
    result = subprocess.run(
        [NPX, "vitest", "run"],
        cwd=APP,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]


@needs_app
def test_app_typechecks() -> None:
    """Both projects, because they compile under different settings.

    The renderer is ESM with the DOM lib; the electron half is CommonJS without
    it. A file that passes one can fail the other, and only the electron project
    emits, so a break there is a build that ships nothing.
    """
    for project in ("tsconfig.json", "tsconfig.electron.json"):
        result = subprocess.run(
            [NPX, "tsc", "-p", project, "--noEmit"],
            cwd=APP,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert result.returncode == 0, f"{project}: {result.stdout[-4000:]}"


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
