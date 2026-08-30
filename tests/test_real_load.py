"""What the bundle does inside a real DeepSeek Harness, not inside our own driver.

Every other plugin test calls `apply` with a stand-in context. That proves the
bundle's own convention and nothing about the runtime's, which is how the
previous shape -- an `apply` that *returned* a tool list Cordis discards --
passed a full suite while registering nothing.

Opt in by pointing `FOUNDRY_DSH_BIN` at an installed harness entry, e.g.

    FOUNDRY_DSH_BIN=/path/to/node_modules/@deepseek-ai/dsh/lib/bin.js \\
      .venv/bin/python -m pytest tests/test_real_load.py

Skipped otherwise, because a 282MB runtime is not a test dependency. The
version it runs against is whatever that install is; the pin this repo declares
is in the README, and these tests do not check the two agree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "dsh-plugin"
ROSTER = json.loads((PLUGIN / "package.json").read_text())["dsh"]["foundry"]["tools"]

DSH_BIN = os.environ.get("FOUNDRY_DSH_BIN")
NODE = shutil.which("node")

needs_dsh = pytest.mark.skipif(
    not DSH_BIN or not Path(DSH_BIN).is_file() or NODE is None,
    reason="set FOUNDRY_DSH_BIN to an installed @deepseek-ai/dsh lib/bin.js",
)

# The boot pulls a profile together and links two packages into it.
BOOT_TIMEOUT = 600

PROBE_INDEX = """\
export const name = "foundry-tool-probe";
export const inject = ["tools"];
export function apply(ctx) {
  // Record at the moment of registration rather than reading the registry back
  // afterwards. `ctx.tools.schemas()` is empty during any plugin's own apply --
  // tools arrive later, as the agent's preset mounts them -- and a timer set to
  // read after that races the boot's own teardown: with no provider credential
  // the context is already inactive when it fires, and the read returns
  // "cannot get required service" instead of a roster.
  //
  // Wrapping `register` needs this plugin to load BEFORE the one under test,
  // which is why the profile installs it first.
  const seen = [];
  const runtime = ctx.tools;
  const original = runtime.register.bind(runtime);
  runtime.register = (definition) => {
    seen.push(definition?.name);
    return original(definition);
  };
  process.on("exit", () => {
    process.stdout.write("FOUNDRY_PROBE " + JSON.stringify(seen.sort()) + "\\n");
  });
}
"""

PROBE_PATCH = """\
- insert:
    - id: foundry-tool-probe
      name: foundry-tool-probe
"""


def _dsh(home: Path, *args: str, env_extra: dict[str, str] | None = None):
    assert DSH_BIN is not None and NODE is not None
    env = {**os.environ, "DSH_HOME": str(home), **(env_extra or {})}
    return subprocess.run(
        [NODE, DSH_BIN, *args],
        capture_output=True,
        text=True,
        env=env,
        # The package root that owns `node_modules`, not `node_modules` itself:
        # `<root>/node_modules/@deepseek-ai/dsh/lib/bin.js` is four levels down.
        cwd=str(Path(DSH_BIN).resolve().parents[4]),
        timeout=BOOT_TIMEOUT,
    )


def _probe_package(tmp_path: Path) -> Path:
    """A second plugin whose only job is to say what the model would be offered.

    It declares its own `dsh.bundle.patch`. Without one the runtime installs it
    as a plain dependency and warns that it is not a profile layer -- it loads
    nothing and reports nothing, which looks exactly like a registry that came
    back empty.
    """
    probe = tmp_path / "probe"
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "index.js").write_text(PROBE_INDEX, encoding="utf-8")
    (probe / "cordis.patch.yml").write_text(PROBE_PATCH, encoding="utf-8")
    (probe / "package.json").write_text(
        json.dumps(
            {
                "name": "foundry-tool-probe",
                "version": "0.0.0",
                "private": True,
                "type": "module",
                "main": "./index.js",
                "exports": {".": "./index.js"},
                "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return probe


@pytest.fixture(scope="module")
def booted(tmp_path_factory) -> dict[str, object]:
    """One boot, shared: materialise a profile, install both plugins, read the roster."""
    if not DSH_BIN or not Path(DSH_BIN).is_file() or NODE is None:
        pytest.skip("no harness")
    tmp_path = tmp_path_factory.mktemp("realload")
    home = tmp_path / "dsh-home"
    home.mkdir(parents=True, exist_ok=True)
    materialise = _dsh(home, "--profile", "headless", "--dump-config")
    assert materialise.returncode == 0, materialise.stderr

    # Probe first: it wraps `ctx.tools.register`, so it has to be applied before
    # the bundle whose registrations it counts.
    for source in (_probe_package(tmp_path), PLUGIN):
        added = _dsh(home, "plugin", "--profile", "headless", "add", str(source))
        assert added.returncode == 0, added.stderr

    dump = _dsh(home, "--profile", "headless", "--dump-config")
    assert dump.returncode == 0, dump.stderr

    boot = _dsh(
        home,
        "--profile",
        "headless",
        "hi",
        env_extra={
            # No provider credential. The boot gets far enough to mount every
            # tool and then stops for want of a key, which is all this measures.
            "FOUNDRY_VAR": str(tmp_path / "var"),
            "FOUNDRY_BIN": str(ROOT / ".venv" / "bin" / "foundry"),
        },
    )
    lines = [line for line in boot.stdout.splitlines() if line.startswith("FOUNDRY_PROBE ")]
    assert lines, f"probe never reported; stdout={boot.stdout[-2000:]} stderr={boot.stderr[-2000:]}"
    return {"dump": dump.stdout, "offered": json.loads(lines[-1].split(" ", 1)[1])}


@needs_dsh
def test_installing_the_package_composes_exactly_one_row(booted) -> None:
    """`dsh plugin add` is the whole wiring, and passing --patch as well is the trap.

    The package carries its own `dsh.bundle.patch`, and `add` appends the package
    to the profile's `dsh.profile.bundles`, so the insert row arrives from there.
    Handing the same file to `--patch` composes it a second time.
    """
    rows = [line for line in booted["dump"].splitlines() if line.strip() == "- id: finance-skill-foundry"]
    assert len(rows) == 1, booted["dump"]


@needs_dsh
def test_every_declared_tool_reaches_the_model(booted) -> None:
    """The unit's done condition, and the first thing that ever measured it."""
    offered = set(booted["offered"])
    missing = [tool for tool in ROSTER if tool not in offered]
    assert not missing, f"declared but never registered: {missing}; offered={sorted(offered)}"


@needs_dsh
def test_the_stock_preset_still_mounts_host_writers(booted) -> None:
    """A finding, written down as a fact rather than as prose.

    The period profile is supposed to omit `bash`, the filesystem tools and
    `str_replace_editor`, and the bundle refuses to start if any of them are in
    the roster it is handed. That check only ever sees the bundle's own list.
    The agent's tool set is decided by its PRESET, which a profile row cannot
    reach into, so on the stock preset the model is offered foundry's ten tools
    and a shell next to them.

    Locked books the model can read around are not locked. Closing this needs a
    foundry-owned agent preset, which is its own unit; until then this test
    holds the gap still so it cannot be forgotten, and it is meant to fail --
    loudly, here -- on the day the preset lands.
    """
    offered = set(booted["offered"])
    leaked = sorted({"bash", "write", "edit", "str_replace_editor", "read"} & offered)
    assert leaked, "the preset appears to have been fenced; update this test and the plan"
