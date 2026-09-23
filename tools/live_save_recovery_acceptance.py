#!/usr/bin/env python3
"""Live app-bound acceptance for completion save recovery.

Creates a synthetic FA Foundry task and drives the real DSH web/runtime toolhost
with a deterministic local LLM adapter. The model first calls
save_explanation_draft with an invalid calculation claim, then corrects the claim
in the same user request. Evidence is written as JSON for external review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = Path("/Users/zcdeng/Documents/FA-Foundry-修复验收-20260923/save-recovery-live.json")
SESSION_ID = "save-recovery-live-runtime"


def default_foundry_bin() -> Path:
    return ROOT / ".venv" / "bin" / "foundry"


def resolve_foundry_bin(raw: str | None) -> Path:
    path = Path(raw).expanduser() if raw else default_foundry_bin()
    if not path.is_file():
        raise SystemExit(f"Foundry executable not found: {path}")
    if not os.access(path, os.X_OK):
        raise SystemExit(f"Foundry path is not executable: {path}")
    return path.resolve()


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def command_output(argv: list[str], timeout: float = 10) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": proc.stdout.strip()[:2000]}
    except Exception as exc:  # provenance only; do not hide the main acceptance result
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def package_version(package_root: Path) -> str | None:
    package_json = package_root / "package.json"
    if not package_json.is_file():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None


def runtime_provenance(foundry_bin: Path) -> dict[str, Any]:
    dsh_path = DSH_BIN.resolve()
    dsh_package_root = dsh_path.parents[1] if len(dsh_path.parents) > 1 else dsh_path.parent
    dsh_scope_root = dsh_path.parents[2] if len(dsh_path.parents) > 2 else dsh_package_root.parent
    node_path = shutil.which("node")
    return {
        "dsh": {
            "path": str(dsh_path),
            "sha256": sha256_file(dsh_path),
            "package_root": str(dsh_package_root),
            "scope_root": str(dsh_scope_root),
            "package_version": package_version(dsh_package_root),
        },
        "foundry": {
            "path": str(foundry_bin),
            "sha256": sha256_file(foundry_bin),
            "help_probe": command_output([str(foundry_bin), "--help"]),
        },
        "node": {
            "path": node_path,
            "version_probe": command_output([node_path, "--version"]) if node_path else {"ok": False, "error": "not_found"},
        },
    }


def discover_dsh_bin() -> Path:
    candidates = [
        os.environ.get("FOUNDRY_DSH_BIN"),
        "/Applications/FA Foundry.app/Contents/Resources/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js",
        str(ROOT / "app/release/mac-arm64/FA Foundry.app/Contents/Resources/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"),
        str(ROOT / "app/extra/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"),
    ]
    for raw in candidates:
        if raw and Path(raw).is_file():
            return Path(raw)
    raise SystemExit("No installed DSH bin found; set FOUNDRY_DSH_BIN")


DSH_BIN = discover_dsh_bin()
os.environ["FOUNDRY_DSH_BIN"] = str(DSH_BIN)
sys.path.insert(0, str(ROOT / "tests"))

from foundry.analysis import AnalysisStore  # noqa: E402
from foundry.finance_service import FinanceStore  # noqa: E402
from foundry.harness import install_presets  # noqa: E402
from foundry.task import TaskStore  # noqa: E402
from test_real_load import WEB_SETTLE_SECONDS, _dsh_args, _prepare, _probe_package  # noqa: E402


PROBE = r"""
export const name = 'foundry-save-recovery-live-probe';
export const inject = ['tools', 'agentPresets', 'llm', 'agents'];
export function apply(ctx) {
  (async () => {
    const { LlmAdapter, createUserMessage } = await import(process.env.FOUNDRY_LLM_MODULE);
    const report = {streams: [], toolResults: [], cancels: [], events: [], messages: []};
    let streams = 0;
    const baseSpec = () => ({
      title: '利润说明',
      body: `利润为 ${process.env.FOUNDRY_ACCEPTANCE_GOOD_VALUE} 万元。`,
      requirements_id: process.env.FOUNDRY_ACCEPTANCE_REQUIREMENT_ID,
      run_ids: [process.env.FOUNDRY_ACCEPTANCE_RUN_ID],
      claims: [{
        basis: 'calculation',
        run_id: process.env.FOUNDRY_ACCEPTANCE_RUN_ID,
        row: Number(process.env.FOUNDRY_ACCEPTANCE_ROW),
        column: process.env.FOUNDRY_ACCEPTANCE_COLUMN,
        value: process.env.FOUNDRY_ACCEPTANCE_GOOD_VALUE,
      }],
    });
    ctx.llm.registerAdapter(['foundry-save-recovery-live-fixture'], new class extends LlmAdapter {
      async *stream(options) {
        options.signal?.throwIfAborted();
        report.streams.push({
          index: streams,
          hasSaveTool: options.tools.some(tool => tool.name === 'save_explanation_draft'),
          toolCount: options.tools.length,
          messageCount: options.messages.length,
        });
        let block;
        if (streams === 0) {
          const bad = baseSpec();
          bad.claims[0].value = process.env.FOUNDRY_ACCEPTANCE_BAD_VALUE;
          bad.body = `利润为 ${process.env.FOUNDRY_ACCEPTANCE_BAD_VALUE} 万元。`;
          block = {type: 'tool-call', id: 'invalid-claim-call', name: 'save_explanation_draft', arguments: JSON.stringify({spec: bad})};
        } else if (streams === 1) {
          block = {type: 'tool-call', id: 'corrected-claim-call', name: 'save_explanation_draft', arguments: JSON.stringify({spec: baseSpec()})};
        } else {
          block = {type: 'text', text: 'SAVE_RECOVERY_ACCEPTANCE_DONE'};
        }
        streams += 1;
        yield {type: 'block-start', index: 0, blockType: block.type};
        yield {type: 'block-end', index: 0, block};
        yield {type: 'finish', reason: {kind: block.type === 'tool-call' ? 'tool-calls' : 'stop'}};
      }
    }());
    await ctx.agentPresets.standingKeyFor('analysis');
    const handle = await ctx.agents.create({
      sessionId: process.env.FOUNDRY_ACCEPTANCE_SESSION_ID,
      meta: {cwd: process.env.FOUNDRY_TEST_WORKSPACE, agentPreset: 'analysis'},
      agentOptions: {provider: 'foundry-save-recovery-live-fixture', model: 'deterministic'},
      setup: async (agentCtx) => {
        await ctx.agentPresets.mount(agentCtx, 'analysis');
        const originalCancel = agentCtx.agent.cancel.bind(agentCtx.agent);
        agentCtx.agent.cancel = (cause, options) => {
          report.cancels.push({cause, options});
          return originalCancel(cause, options);
        };
        agentCtx.on('tools/result', (exec, result) => {
          if (exec.agent.id !== process.env.FOUNDRY_ACCEPTANCE_SESSION_ID) return;
          let value = result.value;
          if (value && typeof value === 'object' && typeof value.stdout === 'string') {
            try { value = {...value, stdoutJson: JSON.parse(value.stdout)}; } catch {}
          }
          report.toolResults.push({
            name: exec.name,
            callId: exec.callId,
            isError: result.isError === true,
            value,
            error: result.error ? {name: result.error.name, message: result.error.message, status: result.error.status, refused: result.error.refused} : null,
          });
        });
      },
    });
    try {
      handle.agent.followup(createUserMessage({content: [{type: 'text', text: 'Run invalid claim then correct it in the same completion operation.'}], source: {kind: 'user'}}));
      await handle.agent.whenIdle();
      report.events = handle.agent.session.events;
      report.messages = handle.agent.session.deriveMessages();
      process.stdout.write('FOUNDRY_SAVE_RECOVERY_LIVE ' + JSON.stringify(report) + '\n');
    } finally {
      await handle.dispose();
    }
  })().catch(error => process.stdout.write('FOUNDRY_SAVE_RECOVERY_LIVE_ERROR ' + (error.stack ?? error.message) + '\n'));
}
"""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")




def foundry_json(foundry_bin: Path, var: Path, task_id: str, command: str, timeout: float = 20) -> dict[str, Any]:
    proc = subprocess.run(
        [str(foundry_bin), "--var", str(var), "--task", task_id, command],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{command} failed via {foundry_bin} with exit {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[-4000:]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{command} returned non-JSON output via {foundry_bin}: {proc.stdout[-4000:]}") from exc


def read_analysis_collection(task, kind: str) -> list[dict[str, Any]]:
    root = task.root / "analysis" / kind
    rows: list[dict[str, Any]] = []
    if root.exists():
        for path in root.glob("*.json"):
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(rows, key=lambda row: (row.get("seq", 0), row.get("created_at", ""), row.get("id", "")))


def setup_finance_task(var: Path, workspace_root: Path) -> dict[str, Any]:
    task = TaskStore(var).create(title="save recovery live synthetic QA")
    task.record_session(SESSION_ID, role="analysis")
    store = AnalysisStore(task)
    bindings: dict[str, str] = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = workspace_root / f"{scenario}.json"
        path.write_text(json.dumps([
            {"account_code": code, "management_account": account, "amount": amount}
            for code, account, amount in zip(("001", "002", "003"), ("revenue", "cost", "expense"), amounts)
        ], ensure_ascii=False), encoding="utf-8")
        bindings[scenario] = store.add_dataset(path, name=scenario)["id"]
    task.update_session_context(SESSION_ID, snapshot_ids=list(bindings.values()))
    service = FinanceStore(task)
    context = service.save_context({
        "bindings": bindings,
        "scopes": {
            alias: {
                "ledger": "L1",
                "organization": "O1",
                "period": "2026-09",
                "currency": "CNY",
                "unit": "万元",
                "scenario": alias,
            }
            for alias in bindings
        },
    })
    requirement = service.analysis_requirements_save({
        "question": "解释本期利润",
        "context_id": context["id"],
        "items": [{"id": "profit", "metric": "profit", "label": "利润"}],
    })
    run = service.run_metric({"context_id": context["id"]})
    row = 0
    column = "profit"
    good = str(run["result"]["rows"][row][column])
    bad = "999"
    return {"task": task, "context": context, "requirement": requirement, "run": run, "row": row, "column": column, "good": good, "bad": bad}


def run_dsh(home: Path, var: Path, task, setup: dict[str, Any], log: Path, foundry_bin: Path) -> dict[str, Any]:
    _prepare(home, _probe_package(home / "save-recovery-probe", PROBE), "web")
    install_presets(home)
    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env.update({
        "FOUNDRY_VAR": str(var),
        "FOUNDRY_BIN": str(foundry_bin),
        "FOUNDRY_LLM_MODULE": (DSH_BIN.resolve().parents[2] / "dsh-llm" / "lib" / "index.js").as_uri(),
        "FOUNDRY_TEST_WORKSPACE": str(task.root / "analysis"),
        "FOUNDRY_COMPLETION_MAX_REPAIRS": "1",
        "FOUNDRY_COMPLETION_TIMEOUT_SECONDS": "300",
        "FOUNDRY_ACCEPTANCE_SESSION_ID": SESSION_ID,
        "FOUNDRY_ACCEPTANCE_RUN_ID": setup["run"]["id"],
        "FOUNDRY_ACCEPTANCE_REQUIREMENT_ID": setup["requirement"]["id"],
        "FOUNDRY_ACCEPTANCE_ROW": str(setup["row"]),
        "FOUNDRY_ACCEPTANCE_COLUMN": setup["column"],
        "FOUNDRY_ACCEPTANCE_GOOD_VALUE": setup["good"],
        "FOUNDRY_ACCEPTANCE_BAD_VALUE": setup["bad"],
    })
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + max(WEB_SETTLE_SECONDS, 60)
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace")
                if "FOUNDRY_SAVE_RECOVERY_LIVE " in output or "FOUNDRY_SAVE_RECOVERY_LIVE_ERROR " in output:
                    break
                time.sleep(0.2)
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
    output = log.read_text(encoding="utf-8", errors="replace")
    if "FOUNDRY_SAVE_RECOVERY_LIVE_ERROR " in output:
        raise RuntimeError(output[-12000:])
    lines = [line for line in output.splitlines() if line.startswith("FOUNDRY_SAVE_RECOVERY_LIVE ")]
    if not lines:
        raise RuntimeError(output[-12000:])
    return json.loads(lines[-1].split(" ", 1)[1])


def collect_evidence(var: Path, task, report: dict[str, Any], setup: dict[str, Any], log: Path, foundry_bin: Path) -> dict[str, Any]:
    op_paths = sorted((task.root / "analysis" / "completion_operations").glob("*.json"))
    operations = [json.loads(path.read_text(encoding="utf-8")) for path in op_paths]
    drafts = read_analysis_collection(task, "drafts")
    completions = read_analysis_collection(task, "completions")
    recoveries_result = foundry_json(foundry_bin, var, task.id, "finance-completion-recoveries")
    recoveries = recoveries_result.get("recoveries")
    if not isinstance(recoveries, list):
        raise RuntimeError("finance-completion-recoveries returned invalid recoveries payload")
    operation = operations[0] if operations else {}
    revisions = operation.get("revisions", [])
    tool_results = [row for row in report.get("toolResults", []) if row.get("name") == "save_explanation_draft"]
    slim_tool_results = []
    for row in tool_results:
        stdout_json = ((row.get("value") or {}).get("stdoutJson") or {}) if isinstance(row.get("value"), dict) else {}
        slim_tool_results.append({
            "name": row.get("name"),
            "callId": row.get("callId"),
            "isError": row.get("isError"),
            "error": row.get("error"),
            "stdout": {
                "id": stdout_json.get("id"),
                "completion_operation_id": stdout_json.get("completion_operation_id"),
                "completion_operation_revision": stdout_json.get("completion_operation_revision"),
                "completion_status": (stdout_json.get("completion") or {}).get("status") if isinstance(stdout_json.get("completion"), dict) else None,
                "operation_status": (stdout_json.get("completion_operation") or {}).get("status") if isinstance(stdout_json.get("completion_operation"), dict) else None,
            } if stdout_json else None,
        })
    first = tool_results[0] if tool_results else {}
    second = tool_results[1] if len(tool_results) > 1 else {}
    second_stdout = ((second.get("value") or {}).get("stdoutJson") or {}) if isinstance(second.get("value"), dict) else {}
    no_orphan = {
        "one_operation": len(operations) == 1,
        "two_revisions": len(revisions) == 2,
        "first_rejected_no_draft": bool(revisions) and revisions[0].get("status") == "rejected_validation" and not revisions[0].get("draft_id") and not revisions[0].get("completion_id"),
        "second_settled": len(revisions) > 1 and revisions[1].get("status") == "settled",
        "one_draft": len(drafts) == 1,
        "one_completion": len(completions) == 1,
        "draft_linked_to_second_revision": len(revisions) > 1 and len(drafts) == 1 and revisions[1].get("draft_id") == drafts[0].get("id"),
        "completion_linked_to_second_revision": len(revisions) > 1 and len(completions) == 1 and revisions[1].get("completion_id") == completions[0].get("id"),
        "no_recoveries_after_success": recoveries == [],
    }
    accepted = all(no_orphan.values()) and bool(first.get("isError")) and second.get("isError") is False
    return {
        "accepted": accepted,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "synthetic QA; no user workbook task was opened or modified",
        "fixture_setup": {
            "created_with": "source Python modules",
            "source_root": str(ROOT),
            "note": "Synthetic task/data setup uses source modules; runtime tool execution and recovery projection use foundry_bin.",
        },
        "projection_runtime": {
            "recoveries_command": "finance-completion-recoveries",
            "recoveries_via_foundry_bin": str(foundry_bin),
        },
        "dsh_bin": str(DSH_BIN),
        "foundry_bin": str(foundry_bin),
        "node": shutil.which("node"),
        "runtime_provenance": runtime_provenance(foundry_bin),
        "var": str(var),
        "task_id": task.id,
        "task_root": str(task.root),
        "session_id": SESSION_ID,
        "run": {"id": setup["run"]["id"], "row": setup["row"], "column": setup["column"], "expected_good_value": setup["good"], "bad_value": setup["bad"]},
        "operation_id": operation.get("id"),
        "operation_status": operation.get("status"),
        "operation_stop_reason": operation.get("stop_reason"),
        "request_key": operation.get("request_key"),
        "revisions": [
            {
                "revision": row.get("revision"),
                "call_id": row.get("call_id"),
                "status": row.get("status"),
                "draft_id": row.get("draft_id"),
                "completion_id": row.get("completion_id"),
                "error": row.get("error"),
            }
            for row in revisions
        ],
        "rejected_receipt": revisions[0].get("error") if revisions else None,
        "retry": {
            "same_operation": len(revisions) > 1 and revisions[0].get("revision") == 1 and revisions[1].get("revision") == 2 and operation.get("id") == second_stdout.get("completion_operation", {}).get("id"),
            "first_call_id": revisions[0].get("call_id") if revisions else None,
            "second_call_id": revisions[1].get("call_id") if len(revisions) > 1 else None,
        },
        "newdraft": {
            "id": drafts[0].get("id") if drafts else None,
            "completion_status": (second_stdout.get("completion") or {}).get("status"),
            "verification_status": (((drafts[0].get("claims") or [{}])[0]).get("verification_status") if drafts else None),
        },
        "no_orphan": no_orphan,
        "recoveries_after_success": recoveries,
        "tool_results": slim_tool_results,
        "streams": report.get("streams", []),
        "cancels": report.get("cancels", []),
        "log": str(log),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--foundry-bin",
        help=f"Foundry executable for the DSH toolhost to call; defaults to {default_foundry_bin()}",
    )
    parser.add_argument(
        "--output",
        default=str(PUBLIC),
        help=f"Evidence JSON path; defaults to {PUBLIC}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    foundry_bin = resolve_foundry_bin(args.foundry_bin)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    root = output.parent / f"save-recovery-live-run-{time.time_ns()}"
    root.mkdir(parents=True, exist_ok=False)
    var = root / "var"
    home = root / "dsh-home"
    data = root / "data"
    data.mkdir()
    setup = setup_finance_task(var, data)
    task = setup["task"]
    log = root / "dsh-save-recovery-live.log"
    try:
        report = run_dsh(home, var, task, setup, log, foundry_bin)
        evidence = collect_evidence(var, task, report, setup, log, foundry_bin)
    except Exception as exc:
        evidence = {
            "accepted": False,
            "error": str(exc),
            "dsh_bin": str(DSH_BIN),
            "foundry_bin": str(foundry_bin),
            "runtime_provenance": runtime_provenance(foundry_bin),
            "var": str(var),
            "task_id": getattr(task, "id", None) if "task" in locals() else None,
            "log_tail": log.read_text(encoding="utf-8", errors="replace")[-12000:] if log.exists() else None,
        }
    write_json(output, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
