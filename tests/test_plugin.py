from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

import foundry.host_profile as host_profile
from foundry.errors import FoundryError, QueryRefused
from foundry.host_profile import REQUIRED_TOOLS, STATE_TOOLS, HostProfile, host_smoke
from foundry.window import WindowStore

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "dsh-plugin"
PATCH = PLUGIN / "cordis.patch.yml"
PACKAGE = PLUGIN / "package.json"
INDEX_JS = PLUGIN / "index.js"
TEST_MJS = PLUGIN / "test.mjs"
CLI_SOURCE = ROOT / "foundry" / "cli.py"
FIXTURES = ROOT / "fixtures" / "period-smoke"

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

_STRING_RE = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", re.S)
_EXPORT_RE = re.compile(r"^export (?:const|function) ([A-Za-z_$][\w$]*)", re.M)
_SPEC_KEY_RE = re.compile(r"^  (?:\"([\w-]+)\"|([A-Za-z_$][\w$]*)): \{", re.M)


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


def _imported(tmp_path: Path):
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    profile = HostProfile.period()
    profile.execute(
        window,
        "import",
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[{"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])}],
        drop_dir=drop,
    )
    return store, window, profile, drop


# --- shared parsing helpers -------------------------------------------------


def _mask_strings(src: str) -> str:
    chars = list(src)
    for match in _STRING_RE.finditer(src):
        for index in range(match.start() + 1, match.end() - 1):
            chars[index] = "_"
    return "".join(chars)


def _block_after(src: str, masked: str, marker: str) -> str:
    start = masked.index(marker)
    open_at = masked.index("{", start)
    depth = 0
    for index in range(open_at, len(masked)):
        char = masked[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[open_at : index + 1]
    raise AssertionError(f"unbalanced block after {marker!r}")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parity_facts(path: Path) -> dict[str, object]:
    src = path.read_text()
    masked = _mask_strings(src)
    specs = _block_after(src, masked, "TOOL_SPECS")
    roster = re.search(r"const tools = (.+?);", src)
    assert roster is not None, f"{path} must read the roster from package.json, not re-declare it"
    return {
        "roster_expr": _norm(roster.group(1)),
        "spawn_options": _norm(_block_after(src, masked, "spawnSync(bin,")),
        "tool_specs": _norm(specs),
        "check_args": _norm(_block_after(src, masked, "function checkArgs")),
        "tool_names": [a or b for a, b in _SPEC_KEY_RE.findall(specs)],
        "exports": sorted(_EXPORT_RE.findall(src)),
    }


def _prelude(index_js: Path | None = None) -> str:
    """Register the bundle the way the runtime does, then expose the roster.

    Every driver below goes through `apply(ctx)` with a stand-in context rather
    than reading a return value. That is the contract: Cordis discards what a
    plugin returns, so a driver that inspected it would pass while the real
    runtime registered nothing -- which is exactly what this suite used to do.
    """
    target = INDEX_JS if index_js is None else index_js
    return (
        f'import {{ apply }} from "{target.as_uri()}";\n'
        "const registered = [];\n"
        "apply({ tools: { register: (d) => registered.push(d) } }, {});\n"
        "const tools = Object.fromEntries(registered.map((t) => [t.name, t]));\n"
        "const call = (name, input = {}, exec = {}) => tools[name].execute(input, exec);\n"
    )


def _tool_specs() -> dict[str, dict]:
    """The registered metadata, read back out of the shipped bundle."""
    if NODE is None:
        pytest.skip("node is not on PATH")
    script = _prelude() + (
        "process.stdout.write(JSON.stringify(registered.map"
        "((t) => ({ name: t.name, description: t.description, parameters: t.parameters }))));\n"
    )
    result = _run_node(script)
    return {tool["name"]: tool for tool in json.loads(result.stdout)}


def _run_node(script: str, *, env_extra: dict[str, str] | None = None, argv: list[str] | None = None):
    assert NODE is not None
    with tempfile.TemporaryDirectory() as work:
        driver = Path(work) / "driver.mjs"
        driver.write_text(script)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
        env.update(env_extra or {})
        result = subprocess.run(
            [NODE, str(driver), *(argv or [])],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
    if result.returncode != 0:
        raise AssertionError(f"node driver failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def _cli_shim(tmp_path: Path) -> Path:
    shim = tmp_path / "foundry-shim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m foundry.cli "$@"\n')
    shim.chmod(0o755)
    return shim


def _cli_flags() -> dict[str, dict[str, set[str]]]:
    """Flags each foundry subcommand accepts, parsed out of the argparse definitions."""
    src = CLI_SOURCE.read_text()
    parsers: dict[str, dict[str, set[str]]] = {}
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'add_parser\("([\w-]+)"\)', src)]
    for index, (start, name) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(src)
        segment = src[start:end]
        parsers[name] = {
            "flags": set(re.findall(r'"(--[a-z-]+)"', segment)),
            "required": set(re.findall(r'"(--[a-z-]+)",\s*required=True', segment)),
        }
    return parsers


def _flag(param: str) -> str:
    return "--" + re.sub(r"(?<!^)(?=[A-Z])", "-", param).lower()


# --- existing bundle contract ----------------------------------------------


def test_bundle_declares_cordis_patch() -> None:
    data = json.loads(PACKAGE.read_text())
    assert data["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    patch = yaml.safe_load(PATCH.read_text())
    inserted = patch[0]["insert"][0]
    assert inserted["id"] == "finance-skill-foundry"
    assert inserted["name"] == data["name"]


def test_period_profile_omits_host_writers() -> None:
    data = json.loads(PACKAGE.read_text())
    foundry = data["dsh"]["foundry"]
    assert set(foundry["tools"]) == set(REQUIRED_TOOLS)
    period = foundry["profiles"]["period"]
    assert period["sandbox"] == "read-only"
    assert period["cwd_writable"] is False
    assert set(period["omit"]) >= {"bash", "dsh-tool-fs", "str-replace-editor", "read_document"}
    assert foundry["profiles"]["f3"]["tools"] == ["query-locked"]
    assert "read_document" in foundry["profiles"]["f3"]["omit"]


def test_startup_fails_when_tool_missing() -> None:
    with pytest.raises(FoundryError, match="missing tools"):
        HostProfile("period", ["lock"])


def test_startup_fails_if_host_writers_mounted() -> None:
    with pytest.raises(FoundryError, match="host writers"):
        HostProfile("period", [*REQUIRED_TOOLS, "bash"])


def test_startup_fails_if_read_document_mounted() -> None:
    with pytest.raises(FoundryError, match="line leak"):
        HostProfile("period", [*REQUIRED_TOOLS, "read_document"])


def test_f3_cannot_execute_reimport(tmp_path: Path) -> None:
    _, window, period, drop = _imported(tmp_path)
    period.execute(window, "lock")
    f3 = HostProfile.f3()
    with pytest.raises(QueryRefused, match="re-import"):
        f3.execute(
            window,
            "re-import",
            coa=drop / "coa.xlsx",
            units=drop / "units.xlsx",
            named=[{"id": "gl", "path": drop / "gl.xlsx"}],
        )
    with pytest.raises(QueryRefused):
        f3.execute(window, "emit-brief")
    assert f3.deny_path(window.catalog_path()) is True


def test_period_state_gates_query_before_lock(tmp_path: Path) -> None:
    _, window, period, _ = _imported(tmp_path)
    with pytest.raises(QueryRefused, match="query-locked"):
        period.execute(window, "query-locked", text="GL", required_table_ids=["gl"])


# --- #15 one roster, cross-checked everywhere -------------------------------


def test_every_roster_copy_agrees_by_name() -> None:
    foundry = json.loads(PACKAGE.read_text())["dsh"]["foundry"]
    assert foundry["tools"] == list(REQUIRED_TOOLS)
    assert foundry["profiles"]["period"]["tools"] == list(REQUIRED_TOOLS)
    facts = _parity_facts(INDEX_JS)
    assert facts["roster_expr"] == "pkg?.dsh?.foundry?.tools"
    assert facts["tool_names"] == list(REQUIRED_TOOLS)
    assert "const REQUIRED = [" not in INDEX_JS.read_text()


def test_every_state_admits_create_and_leaves_the_roster_reachable() -> None:
    reachable: set[str] = set()
    for state, tools in STATE_TOOLS.items():
        assert "create" in tools, state
        assert tools <= set(REQUIRED_TOOLS), state
        reachable |= tools
    assert reachable == set(REQUIRED_TOOLS)


@needs_node
def test_bundle_registers_exactly_the_declared_roster() -> None:
    assert list(_tool_specs()) == list(REQUIRED_TOOLS)


@needs_node
def test_bundle_refuses_to_start_when_metadata_drifts(tmp_path: Path) -> None:
    """A tool added to package.json without metadata must fail startup, not register silently."""
    copy = tmp_path / "dsh-plugin"
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("node_modules"))
    data = json.loads((copy / "package.json").read_text())
    data["dsh"]["foundry"]["tools"].append("ninth-tool")
    (copy / "package.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    script = (
        f'import {{ apply }} from "{(copy / "index.js").as_uri()}";\n'
        "const ctx = { tools: { register: () => {} } };\n"
        "try { apply(ctx, {}); } catch (error) { process.stdout.write(error.message); process.exit(0); }\n"
        'throw new Error("startup accepted an undocumented tool");\n'
    )
    assert "ninth-tool" in _run_node(script).stdout


# --- #28 index.js is the single shipped module ------------------------------


def test_the_bundle_has_exactly_one_source_of_truth() -> None:
    """A second copy nothing builds drifts silently; there must not be one.

    package.json points main and exports at index.js. A src/*.ts beside it
    reads as the source but is never compiled or type-checked, so a fix landed
    there ships nothing -- and the declared `tsc` build could not run at all
    (outDir "." is tsconfig's default exclude, so the project had no inputs).
    """
    package = json.loads(PACKAGE.read_text())
    assert package["main"] == "./index.js"
    assert package["exports"]["."] == "./index.js"
    assert "build" not in package["scripts"]
    assert "devDependencies" not in package
    assert not (PLUGIN / "src").exists()
    assert not (PLUGIN / "tsconfig.json").exists()
    assert sorted(path.name for path in PLUGIN.glob("*.ts")) == []
    facts = _parity_facts(INDEX_JS)
    assert "toolDefinition" in facts["exports"]
    assert "name" in facts["exports"]
    # The two names the runtime itself reads. `inject` says which service must be
    # mounted before `apply` runs, and `apply` is where registration happens; a
    # bundle missing either loads, registers nothing, and reports no error.
    assert "inject" in facts["exports"]
    assert "apply" in facts["exports"]


# --- #4 spawnSync is bounded and reports real spawn failures ----------------


def test_spawn_is_bounded() -> None:
    facts = _parity_facts(INDEX_JS)
    options = facts["spawn_options"]
    assert "timeout:" in options
    assert "maxBuffer:" in options
    assert "killSignal:" in options
    assert "if (result.error) { throw result.error; }" in _norm(INDEX_JS.read_text())


# --- #16 every tool carries a description and an argument schema ------------


@needs_node
def test_every_tool_declares_a_description_and_schema() -> None:
    specs = _tool_specs()
    for name, tool in specs.items():
        assert tool["description"].strip(), name
        parameters = tool["parameters"]
        assert parameters["type"] == "object", name
        assert set(parameters["required"]) <= set(parameters["properties"]), name
        for param, schema in parameters["properties"].items():
            assert schema["type"] == "string", (name, param)
            assert schema["description"].strip(), (name, param)


@needs_node
def test_declared_parameters_match_the_cli_flags() -> None:
    cli = _cli_flags()
    for name, tool in _tool_specs().items():
        parameters = tool["parameters"]
        declared = {_flag(param) for param in parameters["properties"]}
        assert declared <= cli[name]["flags"], name
        assert {_flag(param) for param in parameters["required"]} == cli[name]["required"], name


@needs_node
def test_a_misnamed_argument_is_refused_instead_of_reaching_the_cli(tmp_path: Path) -> None:
    script = _prelude() + (
        "const seen = [];\n"
        'for (const input of [{ tables: "gl" }, { text: "GL", tables: "gl", table: "gl" }]) {\n'
        '  try { await call("query-locked", input); seen.push("accepted"); }\n'
        "  catch (error) { seen.push(error.message); }\n"
        "}\n"
        "process.stdout.write(JSON.stringify(seen));\n"
    )
    env = {"FOUNDRY_BIN": str(_cli_shim(tmp_path)), "FOUNDRY_VAR": str(tmp_path / "var")}
    missing, undeclared = json.loads(_run_node(script, env_extra=env).stdout)
    assert "缺少必填参数 text" in missing
    assert "未声明参数 table" in undeclared
    assert not (tmp_path / "var").exists(), "a rejected call must not reach the CLI"


# --- #3 create bootstraps the period loop, #37 workpaper reads back ---------


@needs_node
def test_bundle_bootstraps_an_empty_var_root_and_reads_its_workpaper(tmp_path: Path) -> None:
    script = _prelude() + (
        "const [named, questions] = process.argv.slice(2);\n"
        "const out = {};\n"
        "try { await call('import', { named }); out.beforeCreate = null; }\n"
        "catch (error) { out.beforeCreate = error.message; }\n"
        "out.create = (await call('create')).stdout.trim();\n"
        "await call('import', { named });\n"
        "await call('lock');\n"
        "await call('record-questions', { questions });\n"
        "await call('emit-brief');\n"
        "out.workpaper = (await call('workpaper')).stdout;\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    questions = json.dumps(
        [{"id": "q-gl", "text": "GL 合计是多少?", "required_table_ids": ["gl"]}],
        ensure_ascii=False,
    )
    env = {"FOUNDRY_BIN": str(_cli_shim(tmp_path)), "FOUNDRY_VAR": str(tmp_path / "var")}
    out = json.loads(
        _run_node(script, env_extra=env, argv=[str(FIXTURES / "named.json"), questions]).stdout
    )
    assert "no current window" in out["beforeCreate"]
    assert re.fullmatch(r"[0-9a-f]{32}", out["create"])
    assert out["workpaper"].strip(), "the agent produced a workpaper it cannot read back"


def test_period_profile_creates_and_reads_back_the_workpaper(tmp_path: Path) -> None:
    store, window, period, _ = _imported(tmp_path)
    period.execute(window, "lock")
    with pytest.raises(QueryRefused, match="workpaper refused in state Locked"):
        period.execute(window, "workpaper")
    period.execute(
        window,
        "record-questions",
        questions=[{"id": "q-gl", "text": "GL 合计是多少?", "required_table_ids": ["gl"]}],
    )
    period.execute(window, "emit-brief")
    assert period.execute(window, "workpaper").strip()
    successor = period.execute(window, "create")
    assert successor.id != window.id
    assert store.current().id == successor.id


# --- #27 one result shape for every tool ------------------------------------


@needs_node
def test_silent_commands_still_answer_the_model(tmp_path: Path) -> None:
    script = _prelude() + (
        "const [named] = process.argv.slice(2);\n"
        "await call('create');\n"
        "const results = [await call('import', { named }), await call('lock')];\n"
        "process.stdout.write(JSON.stringify(results));\n"
    )
    env = {"FOUNDRY_BIN": str(_cli_shim(tmp_path)), "FOUNDRY_VAR": str(tmp_path / "var")}
    imported, locked = json.loads(_run_node(script, env_extra=env, argv=[str(FIXTURES / "named.json")]).stdout)
    # `filed` rides on every value because the output schema declares it once
    # for every tool. A verb that files nothing carries an empty list, which is
    # the truth about it, and `render` never shows it to the model either way.
    assert imported == {"tool": "import", "stdout": "", "filed": []}
    assert locked == {"tool": "lock", "stdout": "", "filed": []}


# --- #29/#30 the node suite runs in the documented pytest loop ---------------


@needs_node
def test_node_bundle_suite_runs() -> None:
    assert NODE is not None
    result = subprocess.run(
        [NODE, str(TEST_MJS)],
        cwd=str(PLUGIN),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_invalid_named_payload_is_refused_by_the_real_cli(tmp_path: Path) -> None:
    var_root = tmp_path / "var"
    create = subprocess.run(
        [sys.executable, "-m", "foundry.cli", "--var", str(var_root), "create"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert create.returncode == 0, create.stderr
    bad = subprocess.run(
        [sys.executable, "-m", "foundry.cli", "--var", str(var_root), "import", "--named", "[{}]"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0
    assert bad.stderr.strip(), "an invalid named payload must explain itself on stderr"
    assert "Traceback" not in bad.stderr, bad.stderr


# --- #6 the smoke gate loads the shipped bundle -----------------------------


@needs_node
def test_host_smoke_drives_the_shipped_bundle(tmp_path: Path) -> None:
    assert NODE is not None
    host_profile._smoke_bundle(NODE, tmp_path / "work", tmp_path / "var", FIXTURES)
    windows = sorted((tmp_path / "var" / "windows").iterdir())
    assert len(windows) == 1
    assert (windows[0] / "workpaper.md").exists()
    assert (windows[0] / "brief.md").exists()


@needs_node
def test_host_smoke_fails_when_the_bundle_cannot_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Strip create from the shipped roster and the smoke must go red, not green."""
    copy = tmp_path / "dsh-plugin"
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("node_modules"))
    data = json.loads((copy / "package.json").read_text())
    data["dsh"]["foundry"]["tools"] = [t for t in data["dsh"]["foundry"]["tools"] if t != "create"]
    (copy / "package.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    assert NODE is not None
    original = host_profile.resource_dir
    monkeypatch.setattr(
        host_profile,
        "resource_dir",
        lambda name: copy if name == "dsh-plugin" else original(name),
    )
    with pytest.raises(FoundryError, match="host smoke bundle run failed"):
        host_profile._smoke_bundle(NODE, tmp_path / "work", tmp_path / "var", FIXTURES)


@needs_node
def test_host_smoke_invokes_probe(tmp_path: Path) -> None:
    assert host_smoke(tmp_path / "var", FIXTURES) == 0


@needs_node
def test_the_receipt_survives_the_real_cli(tmp_path: Path) -> None:
    """The two halves agree about the envelope, measured rather than asserted.

    `--receipt` is a shape the CLI writes and the bundle parses, and the two
    are edited in different languages on different days. This drives a real
    close through the real `foundry` and reads what `execute` resolved.
    """
    script = _prelude() + (
        "const [coa, named, questions] = process.argv.slice(2);\n"
        "await call('create');\n"
        "await call('import', { coa, named });\n"
        "await call('lock');\n"
        "await call('record-questions', { questions });\n"
        "const first = await call('emit-brief');\n"
        "const again = await call('emit-brief');\n"
        "process.stdout.write(JSON.stringify({ first, again }));\n"
    )
    env = {"FOUNDRY_BIN": str(_cli_shim(tmp_path)), "FOUNDRY_VAR": str(tmp_path / "var")}
    out = _run_node(
        script,
        env_extra=env,
        argv=[
            str(FIXTURES / "coa.xlsx"),
            str(FIXTURES / "named.json"),
            str(FIXTURES / "questions.json"),
        ],
    ).stdout
    first, again = (json.loads(out)[key] for key in ("first", "again"))

    # The window this driver built has no task, so there is no timeline to file
    # against. An empty receipt is the truth about that, and the brief is still
    # written either way.
    assert first["filed"] == []
    assert first["stdout"].startswith("# 本期结论稿")
    # And the text is the document, not the envelope it travelled in.
    assert not first["stdout"].lstrip().startswith("{")
    assert again["stdout"] == first["stdout"]


@needs_node
def test_a_receipt_names_the_versions_when_there_is_a_task(tmp_path: Path) -> None:
    """With a timeline, both versions come back, and a re-emit files neither."""
    var = tmp_path / "var"
    shim = _cli_shim(tmp_path)
    made = subprocess.run(
        [str(shim), "--var", str(var), "task-new", "--title", "2026-08", "--period", "2026-08"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert made.returncode == 0, made.stderr
    task_id = made.stdout.strip()

    script = _prelude() + (
        "const [coa, named, questions] = process.argv.slice(2);\n"
        "await call('create');\n"
        "await call('import', { coa, named });\n"
        "await call('lock');\n"
        "await call('record-questions', { questions });\n"
        "const first = await call('emit-brief', {}, { agent: { id: 'sess-period' } });\n"
        "const again = await call('emit-brief', {}, { agent: { id: 'sess-period' } });\n"
        "process.stdout.write(JSON.stringify({ first, again }));\n"
    )
    out = _run_node(
        script,
        env_extra={"FOUNDRY_BIN": str(shim), "FOUNDRY_VAR": str(var), "FOUNDRY_TASK": task_id},
        argv=[
            str(FIXTURES / "coa.xlsx"),
            str(FIXTURES / "named.json"),
            str(FIXTURES / "questions.json"),
        ],
    ).stdout
    first, again = (json.loads(out)[key] for key in ("first", "again"))

    assert [(row["kind"], row["appended"]) for row in first["filed"]] == [
        ("brief", True),
        ("workpaper", True),
    ]
    # The session the agent loop carried reaches the row, which is what makes a
    # version traceable to the conversation that caused it.
    assert {row["session_id"] for row in first["filed"]} == {"sess-period"}
    assert [row["appended"] for row in again["filed"]] == [False, False]
