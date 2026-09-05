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
    for (const id of ["period", "f3", "analysis", "standard"]) {
      try {
        const key = await ctx.agentPresets.standingKeyFor(id);
        const names = ctx.tools.schemas(key).map((s) => s.name).sort();
        process.stdout.write(`FOUNDRY_PRESET ${id} ${JSON.stringify(names)}\\n`);
        const { createScope } = await import(process.env.FOUNDRY_SCOPE_MODULE);
        const agent = {id: `probe-${id}`};
        const scope = createScope(ctx, agent);
        await ctx.agentPresets.mount(scope.ctx, id);
        const actual = ctx.tools.schemas(agent).map((s) => s.name).sort();
        process.stdout.write(`FOUNDRY_AGENT ${id} ${JSON.stringify(actual)}\\n`);
        await scope.dispose();
      } catch (error) {
        process.stdout.write(`FOUNDRY_PRESET ${id} ERR ${error.message}\\n`);
      }
    }
  })();
}
"""

# A deterministic local model drives the actual Agent/subagent runtime. No
# provider credentials or remote completions are needed to prove the lifecycle.
ANALYSIS_RUNTIME_PROBE = r"""
export const name = 'foundry-tool-probe';
export const inject = ['tools', 'agentPresets', 'llm', 'agents', 'subagents'];
export function apply(ctx) {
  (async () => {
    const { LlmAdapter, createUserMessage } = await import(process.env.FOUNDRY_LLM_MODULE);
    const { invokeFoundry } = await import(process.env.FOUNDRY_PLUGIN_MODULE);
    const observed = {}, calls = new Map();
    let cancelledFixture = false;
    ctx.llm.registerAdapter(['foundry-local-fixture'], new class extends LlmAdapter {
      async *stream(options) {
        options.signal?.throwIfAborted();
        const id = options.sessionId;
        const count = calls.get(id) ?? 0;
        calls.set(id, count + 1);
        observed[id] ??= {tools: options.tools.map(t => t.name), history: options.messages};
        if (id !== 'runtime-parent' && !cancelledFixture && JSON.stringify(options.messages).includes('WAIT_FOR_CANCEL')) {
          cancelledFixture = true;
          await new Promise((resolve, reject) => {
            if (options.signal.aborted) reject(options.signal.reason);
            else options.signal.addEventListener('abort', () => reject(options.signal.reason), {once: true});
          });
        }
        let block;
        if (id !== 'runtime-parent' && count === 0) {
          block = {type: 'tool-call', id: `state-${id}`, name: 'analysis-state', arguments: '{}'};
        } else {
          if (id !== 'runtime-parent') observed[id].result = options.messages;
          block = {type: 'text', text: id === 'runtime-parent' ? 'parent history acknowledged' : 'child checked bound state'};
        }
        yield {type: 'block-start', index: 0, blockType: block.type};
        yield {type: 'block-end', index: 0, block};
        yield {type: 'finish', reason: {kind: block.type === 'tool-call' ? 'tool-calls' : 'stop'}};
      }
    }());
    // standing composition awaits the same dependencies as a real web session.
    await ctx.agentPresets.standingKeyFor('analysis');
    const handle = await ctx.agents.create({
      sessionId: 'runtime-parent', meta: {cwd: process.env.FOUNDRY_TEST_WORKSPACE, agentPreset: 'analysis'},
      agentOptions: {provider: 'foundry-local-fixture', model: 'deterministic'},
      setup: async agentCtx => { await ctx.agentPresets.mount(agentCtx, 'analysis'); },
    });
    const parent = handle.agent;
    try {
      parent.followup(createUserMessage({content: [{type: 'text', text: 'UNIQUE_COMPLETED_PARENT_HISTORY'}], source: {kind: 'user'}}));
      await parent.whenIdle();
      const dispatch = async (name, args) => {
        const result = await ctx.tools.execute({callId: `probe-${name}-${Date.now()}`, name,
          arguments: args, agent: parent, signal: new AbortController().signal});
        if (result.isError) throw new Error(JSON.stringify(result.error));
        return JSON.parse(result.value.stdout);
      };
      const jobs = [];
      for (const mode of ['spawn', 'fork']) {
        let job = await dispatch('analysis-delegate', {prompt: 'Read analysis-state and summarize the bound task.', label: mode, mode});
        const deadline = Date.now() + 15000;
        while (!['completed', 'failed', 'cancelled'].includes(job.status) && Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 40));
          job = JSON.parse(await invokeFoundry(['analysis-job-show', '--job', job.id], {agent: parent}));
        }
        jobs.push(job);
      }
      const pending = await dispatch('analysis-delegate', {prompt: 'WAIT_FOR_CANCEL', label: '取消测试', mode: 'spawn'});
      const admissionDeadline = Date.now() + 5000;
      while (!observed[pending.child_session_id] && Date.now() < admissionDeadline) {
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      const cancelled = await dispatch('analysis-job-cancel', {job: pending.id});
      const drained = ctx.agents.get(pending.child_session_id) === undefined;
      let retried = await dispatch('analysis-job-retry', {job: pending.id});
      const retryDeadline = Date.now() + 15000;
      while (!['completed', 'failed', 'cancelled'].includes(retried.status) && Date.now() < retryDeadline) {
        await new Promise(resolve => setTimeout(resolve, 40));
        retried = JSON.parse(await invokeFoundry(['analysis-job-show', '--job', retried.id], {agent: parent}));
      }
      process.stdout.write('FOUNDRY_RUNTIME ' + JSON.stringify({jobs, observed, cancelled, drained, retried}) + '\n');
    } finally { await handle.dispose(); }
  })().catch(error => process.stdout.write('FOUNDRY_RUNTIME_ERROR ' + (error.stack ?? error.message) + '\n'));
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


def _package_name(source: Path) -> str:
    return json.loads((source / "package.json").read_text(encoding="utf-8"))["name"]


def _write_json_if_changed(path: Path, value: object) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _add_to_profile_manifest(home: Path, profile: str, source: Path) -> str:
    name = _package_name(source)
    manifest_path = home / "profiles" / profile / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dependencies"] = {**manifest.get("dependencies", {}), name: f"link:{source}"}
    profile_config = manifest.setdefault("dsh", {}).setdefault("profile", {})
    bundles = profile_config.setdefault("bundles", [])
    if name not in bundles:
        bundles.append(name)
    _write_json_if_changed(manifest_path, manifest)
    return name


def _resolves_to(target: Path, source: Path) -> bool:
    try:
        target.lstat()
        return target.stat().is_dir() and target.stat().st_ino == source.stat().st_ino
    except OSError:
        return False


def _ensure_profile_link(home: Path, profile: str, source: Path) -> Path:
    name = _package_name(source)
    target = home / "profiles" / profile / "node_modules" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if _resolves_to(target, source):
        return target
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)
    target.symlink_to(source, target_is_directory=True)
    return target


def _prepare(home: Path, probe: Path, profile: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    dump = _dsh(home, "--profile", profile, "--dump-config")
    assert dump.returncode == 0, dump.stderr or dump.stdout
    # Probe first: it wraps `ctx.tools.register`, so it has to be declared before
    # the bundle whose registrations it counts. This mirrors the product wiring:
    # name each package in the profile manifest and put a link where the profile
    # resolver looks, without shelling out to an external package manager.
    office = _staged_office()
    for source in (probe, PLUGIN, *( [office] if office else [] )):
        assert (source / "package.json").is_file(), source
        _add_to_profile_manifest(home, profile, source)
        _ensure_profile_link(home, profile, source)


@needs_dsh
def test_analysis_real_spawn_and_fork_inherit_bound_context_and_settle(tmp_path):
    from foundry.analysis import AnalysisStore
    from foundry.harness import install_presets
    from foundry.task import TaskStore

    home = tmp_path / "dsh-home"
    _prepare(home, _probe_package(tmp_path / "probe", ANALYSIS_RUNTIME_PROBE), "web")
    install_presets(home)
    var = tmp_path / "var"
    task = TaskStore(var).create(title="真实子任务")
    task.record_session("runtime-parent", role="analysis")
    source = tmp_path / "source.csv"
    source.write_text("revenue\n70.01\n")
    dataset = AnalysisStore(task).add_dataset(source, name="实际")
    task.update_session_context("runtime-parent", snapshot_ids=[dataset["id"]])
    workspace = task.root / "analysis"
    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env.update({
        "FOUNDRY_VAR": str(var), "FOUNDRY_BIN": str(ROOT / ".venv" / "bin" / "foundry"),
        "FOUNDRY_LLM_MODULE": (Path(DSH_BIN).resolve().parents[2] / "dsh-llm" / "lib" / "index.js").as_uri(),
        "FOUNDRY_PLUGIN_MODULE": (PLUGIN / "index.js").as_uri(),
        "FOUNDRY_TEST_WORKSPACE": str(workspace),
    })
    log = tmp_path / "runtime.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + WEB_SETTLE_SECONDS
            while time.monotonic() < deadline:
                output = log.read_text(errors="replace")
                if "FOUNDRY_RUNTIME " in output or "FOUNDRY_RUNTIME_ERROR " in output:
                    break
                time.sleep(0.2)
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
    output = log.read_text(errors="replace")
    assert "FOUNDRY_RUNTIME_ERROR " not in output, output[-12000:]
    lines = [line for line in output.splitlines() if line.startswith("FOUNDRY_RUNTIME ")]
    assert lines, output[-12000:]
    result = json.loads(lines[-1].split(" ", 1)[1])
    assert len(result["jobs"]) == 2
    assert result["cancelled"]["status"] == "cancelled"
    assert result["drained"] is True
    assert result["retried"]["status"] == "completed", result["retried"]
    assert result["retried"]["retry_of"] == result["cancelled"]["id"]
    assert result["retried"]["child_session_id"] != result["cancelled"]["child_session_id"]
    assert result["retried"]["context_hash"] == result["cancelled"]["context_hash"]
    for job in result["jobs"]:
        assert job["status"] == "completed", job
        assert job["task_id"] == task.id
        assert job["snapshot_ids"] == [dataset["id"]]
        observed = result["observed"][job["child_session_id"]]
        assert "analysis-state" in observed["tools"]
        assert not set(observed["tools"]) & {"analysis-delegate", "analysis-draft", "dataset-add", "bash", "create"}
        serialized_history = json.dumps(observed["history"])
        assert ("UNIQUE_COMPLETED_PARENT_HISTORY" in serialized_history) == (job["spec"]["mode"] == "fork")
        # The child's model requested the tool through the real agent loop. Its
        # actual return must contain this child's registered scope, not ambient.
        actual_results = [message for message in observed["result"] if message["source"]["kind"] == "tool"]
        assert actual_results
        serialized_results = json.dumps(actual_results)
        assert job["child_session_id"] in serialized_results
        assert dataset["id"] in serialized_results
        assert task.id in serialized_results


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

    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env["FOUNDRY_SCOPE_MODULE"] = (Path(DSH_BIN).resolve().parents[2] / "dsh-scope" / "lib" / "index.js").as_uri()
    log = tmp / "web.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + WEB_SETTLE_SECONDS
            while time.monotonic() < deadline:
                text = log.read_text(encoding="utf-8", errors="replace")
                if len([l for l in text.splitlines() if l.startswith("FOUNDRY_AGENT ")]) >= 4:
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
    actual = {}
    for line in text.splitlines():
        if line.startswith("FOUNDRY_AGENT "):
            _, preset_id, value = line.split(" ", 2)
            actual[preset_id] = json.loads(value)
    assert actual == reported, f"actual agent tools differ from standing presets: {actual}; standing={reported}"
    return actual


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


@needs_dsh
def test_analysis_preset_exposes_executable_analysis_without_legacy_tools(web_presets):
    profile = FOUNDRY_DSH["profiles"]["analysis"]
    offered = set(web_presets["analysis"])
    assert offered == set(profile["tools"] + profile["harnessTools"])
    assert not set(ROSTER) & offered
    assert not REACH & offered
    assert not any(name.startswith("univer_") for name in offered)
    # Mounting the new preset must not widen another session's tool scope.
    for legacy in ("period", "f3", "standard"):
        assert not set(profile["tools"]) & set(web_presets[legacy])
