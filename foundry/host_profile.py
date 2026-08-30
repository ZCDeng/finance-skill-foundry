from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from foundry.brief import emit_brief
from foundry.caliber import table_key
from foundry.errors import FoundryError, QueryRefused
from foundry.harness import LINE_LEAKS
from foundry.launch_formulator import formulator_bin, launch_formulator, stop_formulator
from foundry.probe import run_probe
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.resources import resource_dir
from foundry.tags import OUTSIDE
from foundry.window import Window, WindowStore

REQUIRED_TOOLS = (
    "create",
    "import",
    "lock",
    "record-questions",
    "emit-brief",
    "workpaper",
    "launch-formulator",
    "stop-formulator",
    "query-locked",
    "re-import",
)
HOST_WRITERS = frozenset({"bash", "dsh-tool-fs", "str-replace-editor"})
F3_TOOLS = frozenset({"query-locked"})
STATE_TOOLS = {
    "Open": frozenset({"create", "import", "lock"}),
    "Imported": frozenset({"create", "import", "lock"}),
    "Locked": frozenset(
        {"create", "record-questions", "emit-brief", "launch-formulator", "stop-formulator", "re-import"}
    ),
    "Briefed": frozenset(
        {"create", "query-locked", "workpaper", "launch-formulator", "stop-formulator", "re-import"}
    ),
    "FollowUp": frozenset(
        {"create", "query-locked", "workpaper", "launch-formulator", "stop-formulator", "re-import"}
    ),
}


class HostProfile:
    def __init__(self, name: str, tools: list[str] | tuple[str, ...]) -> None:
        self.name = name
        self.tools = set(tools)
        writers = self.tools & HOST_WRITERS
        if writers:
            raise FoundryError(f"period profile must omit host writers: {sorted(writers)}")
        leaks = self.tools & LINE_LEAKS
        if leaks:
            raise FoundryError(f"period profile must omit line leaks: {sorted(leaks)}")
        if name == "period":
            missing = [tool for tool in REQUIRED_TOOLS if tool not in self.tools]
            if missing:
                raise FoundryError(f"foundry plugin startup failed; missing tools: {','.join(missing)}")
        if name == "f3" and self.tools != F3_TOOLS:
            raise FoundryError("F3 allowlist is query-locked only")

    @classmethod
    def period(cls) -> HostProfile:
        return cls("period", REQUIRED_TOOLS)

    @classmethod
    def f3(cls) -> HostProfile:
        return cls("f3", tuple(F3_TOOLS))

    def deny_path(self, path: Path) -> bool:
        if self.name != "f3":
            return False
        text = str(path)
        return (
            "catalog.duckdb" in text
            or "/formulator/" in text
            or text.endswith("/formulator")
            or ".dsh-uploads" in text
        )

    def execute(self, window: Window, tool: str, **payload: Any) -> Any:
        if tool not in self.tools:
            raise QueryRefused(f"{self.name} cannot execute {tool}")
        if self.name == "f3" and tool != "query-locked":
            raise QueryRefused(f"F3 cannot execute {tool}")
        allowed = STATE_TOOLS.get(window.state, frozenset())
        if self.name == "period" and tool not in allowed:
            raise QueryRefused(f"{tool} refused in state {window.state}")
        if tool == "create":
            return window.store.create()
        if tool == "import":
            return window.import_tables(
                coa=Path(payload["coa"]) if payload.get("coa") else None,
                named=payload["named"] if "named" in payload else None,
                aux=Path(payload["aux"]) if payload.get("aux") else None,
                map=Path(payload["map"]) if payload.get("map") else None,
                units=Path(payload["units"]) if payload.get("units") else None,
                drop_dir=Path(payload["drop_dir"]) if payload.get("drop_dir") else None,
            )
        if tool == "lock":
            return window.lock()
        if tool == "record-questions":
            record_questions(window, payload["questions"])
            return None
        if tool == "emit-brief":
            return emit_brief(window)
        if tool == "workpaper":
            if not window.workpaper_path.exists():
                raise FoundryError("workpaper not written")
            return window.workpaper_path.read_text()
        if tool == "launch-formulator":
            return launch_formulator(window)
        if tool == "stop-formulator":
            return stop_formulator(window)
        if tool == "query-locked":
            return query_locked(
                window,
                payload["text"],
                required_table_ids=payload["required_table_ids"],
                split_by=payload.get("split_by"),
                brief_window_id=payload.get("brief_window_id"),
                question_id=payload.get("question_id"),
            )
        if tool == "re-import":
            return window.reimport(
                coa=Path(payload["coa"]) if payload.get("coa") else None,
                named=payload["named"] if "named" in payload else None,
                aux=Path(payload["aux"]) if payload.get("aux") else None,
                map=Path(payload["map"]) if payload.get("map") else None,
                units=Path(payload["units"]) if payload.get("units") else None,
                drop_dir=Path(payload["drop_dir"]) if payload.get("drop_dir") else None,
            )
        raise FoundryError(f"unknown tool {tool}")


SMOKE_SEQUENCE = (
    "create",
    "import",
    "lock",
    "record-questions",
    "emit-brief",
    "workpaper",
    "query-locked",
    "launch-formulator",
    "stop-formulator",
)

_BUNDLE_DRIVER = """
import { apply, definitions } from "%(bundle)s";

const steps = JSON.parse(process.argv[2]);

// Enumerate through `definitions`, not through `apply`. `apply` registers on
// the context the runtime hands it and returns nothing, so a driver that read
// its return value would be reading a value the runtime itself discards -- the
// exact confusion this smoke used to encode. Registering onto a stand-in
// context here still proves `apply` reaches `ctx.tools.register` for every tool.
const registered = [];
apply({ tools: { register: (definition) => registered.push(definition) } }, { profile: "period" });
const enumerated = definitions("period");
if (registered.length !== enumerated.length) {
  throw new Error(
    `host-smoke: apply registered ${registered.length} tools, definitions listed ${enumerated.length}`,
  );
}
const tools = Object.fromEntries(registered.map((tool) => [tool.name, tool]));
for (const step of steps) {
  const tool = tools[step.tool];
  if (!tool) {
    throw new Error(`host-smoke: bundle did not register ${step.tool}`);
  }
  if (!tool.description || !tool.parameters || !tool.output) {
    throw new Error(`host-smoke: ${step.tool} registered without description/parameters/output`);
  }
  const value = await tool.execute(step.input, {});
  if (value?.tool !== step.tool || typeof value.stdout !== "string") {
    throw new Error(`host-smoke: ${step.tool} returned an unnormalised result`);
  }
  process.stdout.write(JSON.stringify(value) + "\\n");
}
"""


def _smoke_steps(fixtures: Path, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    named = fixtures / "named.json"
    return [
        {"tool": "create", "input": {}},
        {"tool": "import", "input": {"named": str(named)}},
        {"tool": "lock", "input": {}},
        {"tool": "record-questions", "input": {"questions": json.dumps(questions, ensure_ascii=False)}},
        {"tool": "emit-brief", "input": {}},
        {"tool": "workpaper", "input": {}},
        {"tool": "query-locked", "input": {"text": "host-smoke 重算", "tables": "gl", "splitBy": "unit_id"}},
        {"tool": "launch-formulator", "input": {}},
        {"tool": "stop-formulator", "input": {}},
    ]


def _in_window_questions(fixtures: Path) -> list[dict[str, Any]]:
    named = json.loads((fixtures / "named.json").read_text())
    # Compare catalog ids, not spellings: a fixture named ar-2024-08.xlsx is the
    # table ar_2024_08, and a raw comparison would drop its questions silently.
    available = {table_key(str(item["id"])) for item in named.get("tables", [])}
    available |= {key for key in ("coa", "aux", "map", "units") if named.get(key)}
    questions = [
        question
        for question in json.loads((fixtures / "questions.json").read_text())
        if {table_key(table) for table in question.get("required_table_ids") or []} <= available
    ]
    if not questions:
        raise FoundryError("host smoke fixture has no in-window questions")
    return questions


def _cli_shim(work: Path) -> Path:
    shim = work / "foundry-shim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m foundry.cli "$@"\n')
    shim.chmod(0o755)
    return shim


def _smoke_env(work: Path, var_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["FOUNDRY_BIN"] = str(_cli_shim(work))
    env["FOUNDRY_VAR"] = str(var_root)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parents[1]), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    # One resolver. Re-scanning PATH here would skip the real launch on exactly
    # the machines that carry a frozen Formulator instead of an installed one.
    if not Path(formulator_bin()).exists():
        env["FOUNDRY_SKIP_FORMULATOR_EXEC"] = "1"
        print(
            "host-smoke: Data Formulator 未安装, launch/stop 只走 spec 分支, 未起真实进程",
            file=sys.stderr,
        )
    return env


def _check_bundle_output(stdout: str) -> None:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != len(SMOKE_SEQUENCE):
        raise FoundryError(f"host smoke ran {len(lines)} of {len(SMOKE_SEQUENCE)} tools through the bundle")
    results = {}
    for tool, line in zip(SMOKE_SEQUENCE, lines):
        payload = json.loads(line)
        if payload.get("tool") != tool:
            raise FoundryError(f"host smoke expected {tool}, bundle answered {payload.get('tool')}")
        results[tool] = payload.get("stdout", "")
    if len(results["create"].strip()) != 32:
        raise FoundryError("host smoke create did not return a window id")
    if "本期结论稿" not in results["emit-brief"]:
        raise FoundryError("host smoke emit-brief did not return the brief")
    if not results["workpaper"].strip():
        raise FoundryError("host smoke workpaper came back empty")
    if not results["query-locked"].startswith(OUTSIDE):
        raise FoundryError("host smoke expected a tagged recompute")
    if "url" not in json.loads(results["launch-formulator"]):
        raise FoundryError("host smoke launch-formulator did not return a launch spec")
    if json.loads(results["stop-formulator"]).get("stopped") != "formulator":
        raise FoundryError("host smoke stop-formulator did not release the lease")


def _smoke_bundle(node: str, work: Path, var_root: Path, fixtures: Path) -> None:
    bundle = resource_dir("dsh-plugin") / "index.js"
    if not bundle.is_file():
        raise FoundryError(f"host bundle is missing: {bundle}")
    work.mkdir(parents=True, exist_ok=True)
    driver = work / "driver.mjs"
    driver.write_text(_BUNDLE_DRIVER % {"bundle": bundle.as_uri()})
    steps = json.dumps(_smoke_steps(fixtures, _in_window_questions(fixtures)), ensure_ascii=False)
    result = subprocess.run(
        [node, str(driver), steps],
        capture_output=True,
        text=True,
        env=_smoke_env(work, var_root),
        timeout=300,
    )
    if result.returncode != 0:
        raise FoundryError(f"host smoke bundle run failed: {result.stderr.strip() or result.stdout.strip()}")
    _check_bundle_output(result.stdout)


def host_smoke(var_root: Path, fixtures: Path) -> int:
    profile = HostProfile.period()
    unknown = [step for step in SMOKE_SEQUENCE if step not in profile.tools]
    if unknown:
        raise FoundryError(f"host smoke sequence is not in the period roster: {','.join(unknown)}")
    if run_probe(var_root / "probe", fixtures) != 0:
        raise FoundryError("host smoke fixture probe failed")
    node = shutil.which("node")
    if node is None:
        raise FoundryError("host smoke needs node on PATH to load the shipped dsh bundle")
    _smoke_bundle(node, var_root / "smoke-work", var_root / "smoke", fixtures)
    return 0
