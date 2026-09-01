"""What the bundle does inside a real FA Foundry harness, not inside our own driver.

Every other plugin test calls `apply` with a stand-in context. That proves the
bundle's own convention and nothing about the runtime's, which is how the
previous shape -- an `apply` that *returned* a tool list Cordis discards --
passed a full suite while registering nothing.

Opt in by pointing `FOUNDRY_DSH_BIN` at an installed harness entry, e.g.

    FOUNDRY_DSH_BIN=/path/to/node_modules/@deepseek-ai/dsh/lib/bin.js \\
      .venv/bin/python -m pytest tests/test_real_load.py

Skipped otherwise, because a 282MB runtime is not a test dependency. The version
it runs against is whatever that install is; the pin this repo declares is in the
README, and these tests do not check the two agree.

Two profiles, two fences, and the difference is most of why this file is long.
`headless` has no agent presets: its tool rows ARE the tool set, and a profile
patch takes them away. `web` composes `agent-presets`, and there a profile row
cannot take away a tool the preset mounts -- the preset decides. Getting that
backwards is how the fence was believed to exist while it did not.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "dsh-plugin"
FOUNDRY_DSH = json.loads((PLUGIN / "package.json").read_text())["dsh"]["foundry"]
ROSTER = FOUNDRY_DSH["tools"]
F3_ROSTER = FOUNDRY_DSH["profiles"]["f3"]["tools"]
FENCE = PLUGIN / "period.fence.yml"

DSH_BIN = os.environ.get("FOUNDRY_DSH_BIN")
NODE = shutil.which("node")

needs_dsh = pytest.mark.skipif(
    not DSH_BIN or not Path(DSH_BIN).is_file() or NODE is None,
    reason="set FOUNDRY_DSH_BIN to an installed @deepseek-ai/dsh lib/bin.js",
)

BOOT_TIMEOUT = 600
WEB_SETTLE_SECONDS = 40

# Anything that can reach a file, a shell, or another agent. A locked window the
# model can read around is not locked.
#
# `web_search` is deliberately not in here. It was, and KTD11 took it out: the
# test is whether a row is a path to the archived books, and a search result is
# not one. What it returns reaches a document only through `record-reference`,
# which demands a source and a date. Both fences agree on this -- the preset and
# `period.fence.yml` -- which is why one set can check both.
REACH = {
    "bash",
    "read",
    "write",
    "edit",
    "str_replace_editor",
    "glob",
    "grep",
    "job_list",
    "job_output",
    "job_kill",
    "subagent",
    "subagent_fork",
    "workflow",
    "ralph",
}

REGISTER_PROBE = """\
export const name = "foundry-tool-probe";
export const inject = ["tools"];
export function apply(ctx) {
  // Record at the moment of registration rather than reading the registry back
  // afterwards. `ctx.tools.schemas()` is empty during any plugin's own apply --
  // tools arrive later -- and a timer set to read after that races the boot's
  // own teardown: with no provider credential the context is already inactive
  // when it fires.
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

PRESET_PROBE = """\
export const name = "foundry-tool-probe";
export const inject = ["tools", "agentPresets"];
export function apply(ctx) {
  // `standingKeyFor` composes a preset without starting an agent, a session or a
  // turn, which is the only way to measure one from outside a browser. The scope
  // key it hands back is what `schemas` resolves the preset's own layer through,
  // so this is the tool list an agent on that preset would actually be offered.
  (async () => {
    for (const id of ["period", "f3", "standard"]) {
      try {
        const key = await ctx.agentPresets.standingKeyFor(id);
        const names = ctx.tools.schemas(key).map((s) => s.name).sort();
        process.stdout.write(`FOUNDRY_PRESET ${id} ${JSON.stringify(names)}\\n`);
      } catch (error) {
        process.stdout.write(`FOUNDRY_PRESET ${id} ERR ${error.message}\\n`);
      }
    }
  })();
}
"""

PROBE_PATCH = """\
- insert:
    - id: foundry-tool-probe
      name: foundry-tool-probe
"""


def _dsh_args(home: Path, *args: str) -> tuple[list[str], dict[str, str], str]:
    assert DSH_BIN is not None and NODE is not None
    env = {**os.environ, "DSH_HOME": str(home)}
    # The package root that owns `node_modules`, not `node_modules` itself:
    # `<root>/node_modules/@deepseek-ai/dsh/lib/bin.js` is four levels down.
    cwd = str(Path(DSH_BIN).resolve().parents[4])
    return [NODE, DSH_BIN, *args], env, cwd


def _dsh(home: Path, *args: str, env_extra: dict[str, str] | None = None):
    argv, env, cwd = _dsh_args(home, *args)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env={**env, **(env_extra or {})},
        cwd=cwd,
        timeout=BOOT_TIMEOUT,
    )


def _probe_package(where: Path, body: str) -> Path:
    """A second plugin whose only job is to say what a model would be offered.

    It declares its own `dsh.bundle.patch`. Without one the runtime installs it
    as a plain dependency and warns that it is not a profile layer -- it loads
    nothing and reports nothing, which looks exactly like a registry that came
    back empty.
    """
    where.mkdir(parents=True, exist_ok=True)
    (where / "index.js").write_text(body, encoding="utf-8")
    (where / "cordis.patch.yml").write_text(PROBE_PATCH, encoding="utf-8")
    (where / "package.json").write_text(
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
    return where


def _staged_office() -> Path | None:
    """The Univer bundle, if this checkout has staged it.

    Measured from the staged tree rather than installed here: it is 150MB with
    native bindings, and a test that fetched it would be a test that needed the
    network. Absent, the office assertions skip and the rest still runs.
    """
    from foundry.harness import office_companion

    if not DSH_BIN:
        return None
    root = Path(DSH_BIN).parents[3]
    staged = root / office_companion()["package"]
    return staged if (staged / "package.json").is_file() else None


def _prepare(home: Path, probe: Path, profile: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    assert _dsh(home, "--profile", profile, "--dump-config").returncode == 0
    # Probe first: it wraps `ctx.tools.register`, so it has to be applied before
    # the bundle whose registrations it counts.
    office = _staged_office()
    for source in (probe, PLUGIN, *( [office] if office else [] )):
        added = _dsh(home, "plugin", "--profile", profile, "add", str(source))
        assert added.returncode == 0, added.stderr


# --- headless: the tool rows are the tool set ------------------------------


@pytest.fixture(scope="module")
def headless(tmp_path_factory) -> dict[str, object]:
    if not DSH_BIN or not Path(DSH_BIN).is_file() or NODE is None:
        pytest.skip("no harness")
    tmp = tmp_path_factory.mktemp("headless")
    home = tmp / "dsh-home"
    _prepare(home, _probe_package(tmp / "probe", REGISTER_PROBE), "headless")

    def boot(*extra: str) -> list[str]:
        # No provider credential. The boot gets far enough to mount every tool
        # and then stops for want of a key, which is all this measures.
        run = _dsh(
            home,
            "--profile",
            "headless",
            *extra,
            "hi",
            env_extra={
                "FOUNDRY_VAR": str(tmp / "var"),
                "FOUNDRY_BIN": str(ROOT / ".venv" / "bin" / "foundry"),
            },
        )
        lines = [line for line in run.stdout.splitlines() if line.startswith("FOUNDRY_PROBE ")]
        assert lines, f"probe never reported; stdout={run.stdout[-2000:]} stderr={run.stderr[-2000:]}"
        return json.loads(lines[-1].split(" ", 1)[1])

    dump = _dsh(home, "--profile", "headless", "--dump-config")
    return {"dump": dump.stdout, "open": boot(), "fenced": boot("--patch", str(FENCE))}


@needs_dsh
def test_installing_the_package_composes_exactly_one_row(headless) -> None:
    """`dsh plugin add` is the whole wiring, and passing --patch as well is the trap.

    The package carries its own `dsh.bundle.patch`, and `add` appends the package
    to the profile's `dsh.profile.bundles`, so the insert row arrives from there.
    Handing the same file to `--patch` composes it a second time.
    """
    rows = [
        line for line in headless["dump"].splitlines() if line.strip() == "- id: finance-skill-foundry"
    ]
    assert len(rows) == 1, headless["dump"]


@needs_dsh
def test_every_declared_tool_reaches_the_model(headless) -> None:
    """The first thing that ever measured this."""
    offered = set(headless["open"])
    missing = [tool for tool in ROSTER if tool not in offered]
    assert not missing, f"declared but never registered: {missing}; offered={sorted(offered)}"


@needs_dsh
def test_an_unfenced_profile_hands_the_model_a_shell(headless) -> None:
    """Why `period.fence.yml` exists, kept as the contrast the next test is against."""
    assert REACH & set(headless["open"]), "the stock headless profile used to leak; it no longer does"


@needs_dsh
def test_the_fence_patch_closes_a_profile_that_has_no_presets(headless) -> None:
    fenced = set(headless["fenced"])
    assert not (REACH & fenced), f"still reachable: {sorted(REACH & fenced)}"
    assert set(ROSTER) <= fenced, f"the fence took foundry's own tools: {sorted(set(ROSTER) - fenced)}"


# --- web: the preset is the tool set ---------------------------------------


@pytest.fixture(scope="module")
def web_presets(tmp_path_factory) -> dict[str, list[str]]:
    """Boot the web profile long enough for the probe to compose each preset.

    The web app serves and never exits, so this one is spawned and stopped rather
    than waited on, and the probe prints as it goes instead of on exit.
    """
    if not DSH_BIN or not Path(DSH_BIN).is_file() or NODE is None:
        pytest.skip("no harness")
    tmp = tmp_path_factory.mktemp("web")
    home = tmp / "dsh-home"
    _prepare(home, _probe_package(tmp / "probe", PRESET_PROBE), "web")

    from foundry.harness import install_presets

    install_presets(home)

    argv, env, cwd = _dsh_args(home, "--profile", "web")
    log = tmp / "web.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + WEB_SETTLE_SECONDS
            while time.monotonic() < deadline:
                text = log.read_text(encoding="utf-8", errors="replace")
                if len([l for l in text.splitlines() if l.startswith("FOUNDRY_PRESET ")]) >= 3:
                    break
                time.sleep(0.5)
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:  # pragma: no cover - only on a wedged child
                child.kill()

    text = log.read_text(encoding="utf-8", errors="replace")
    reported: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("FOUNDRY_PRESET "):
            continue
        _, preset_id, rest = line.split(" ", 2)
        assert not rest.startswith("ERR"), f"{preset_id}: {rest}"
        reported[preset_id] = json.loads(rest)
    assert reported, f"no preset was measured; log tail={text[-2000:]}"
    return reported


@needs_dsh
def test_the_period_preset_offers_the_roster_and_no_reach(web_presets) -> None:
    period = set(web_presets["period"])
    assert set(ROSTER) <= period, f"missing from period: {sorted(set(ROSTER) - period)}"
    assert not (REACH & period), f"still reachable: {sorted(REACH & period)}"
    # Everything that survives the deletion, and the row it comes from. Written
    # out rather than bounded, because the interesting failure is a tool that
    # appears without anyone deciding it should.
    #
    #   skill                                   the close methods ship as skills
    #   todo_write                              a period has steps
    #   ask_user_question                       and choices
    #   create_goal / update_goal / get_goal    the model stating what it is doing
    #   exit_plan_mode                          thinking before acting
    #   web_search                              KTD11; what it returns reaches a
    #                                           document only via record-reference
    assert period - set(ROSTER) == {
        "skill",
        "todo_write",
        "ask_user_question",
        "create_goal",
        "update_goal",
        "get_goal",
        "exit_plan_mode",
        "web_search",
    }


@needs_dsh
def test_the_f3_preset_offers_exactly_the_follow_up_tool(web_presets) -> None:
    """KTD7: a leader's follow-up agent can recompute and do nothing else.

    Foundry registers its ten globally from the profile row, so the preset cannot
    register a smaller roster of its own -- the names are taken. `f3-scope` masks
    them for this preset's agents instead.
    """
    assert sorted(web_presets["f3"]) == sorted(F3_ROSTER) == ["query-locked"]


@needs_dsh
def test_the_office_tools_reach_the_authoring_seat_and_not_the_close_seat(web_presets) -> None:
    """The thing a preset row could not do on its own.

    `dsh-univer-office` registers thirteen tools globally, at profile level. The
    period preset is built by deleting upstream rows, and deleting a row cannot
    take away a tool the preset never mounted -- so before `period-scope` existed
    these stood next to a locked window. Two of them are reach in the plain
    sense: `univer_execute` runs arbitrary Facade JavaScript against an absolute
    path, and `univer_import` reads an xlsx off disk into a unit.

    The other eleven fail a different test. A figure typed into a cell and
    exported is a figure with no basis -- not 我重算, because no catalog produced
    it, and not 外部引用, because nobody published it.

    `standard` is the contrast and the point: an authoring session keeps all
    thirteen. This is a fence around the close, not a ban on the plugin.
    """
    from foundry.harness import office_companion

    if _staged_office() is None:
        pytest.skip("office companion is not staged; run `npm run harness` in app/")

    declared = set(office_companion()["omitTools"])
    standard = set(web_presets["standard"])
    assert declared <= standard, f"the bundle did not register: {sorted(declared - standard)}"

    for seat in ("period", "f3"):
        offered = set(web_presets[seat])
        assert not (declared & offered), f"{seat} still sees: {sorted(declared & offered)}"


@needs_dsh
def test_the_stock_preset_is_still_the_wide_one(web_presets) -> None:
    """The contrast, and the reason a foundry-owned preset had to exist.

    Nothing here asks upstream to change: `standard` is a coding agent and a
    coding agent should have a shell. What was wrong was pointing a locked period
    at it.
    """
    standard = set(web_presets["standard"])
    assert REACH & standard, "the stock preset narrowed; re-derive ours from it"
    assert set(ROSTER) <= standard, "foundry's global registration stopped reaching a preset agent"
