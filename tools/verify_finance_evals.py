"""Run and score r2 finance evaluations against the configured local model.

Only synthetic fixture data is sent to the provider. The configured credential is
copied into an ephemeral 0600 file and removed with the temporary harness home.
The model owns the analysis turn; this verifier observes tool calls, persisted
Foundry state, and raw messages, then scores them against Decimal fixture truth.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any

import yaml


REPO = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO / "tests/fixtures/finance_evals/cases.json"
DEFAULT_DSH_ROOT = REPO / "app/extra/dsh"
DEFAULT_FOUNDRY = REPO / ".venv/bin/foundry"
DEFAULT_PLUGIN = REPO / "dsh-plugin"
DEFAULT_CREDENTIALS_HOME = Path("/Users/zcdeng/Library/Application Support/FA Foundry/harness")
CALC_TOOLS = {"run_metric", "explain_variance", "finance_scenario_run", "analysis-run"}
FORBIDDEN_CAUSAL = re.compile(
    r"(?:导致|归因于|原因是|主要因为|直接造成|caused by|because of|due to|driven by)",
    re.I,
)


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _dec(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
        if result.is_finite():
            return result
    except (InvalidOperation, ValueError):
        pass
    raise AssertionError(f"not a finite decimal: {value!r}")


def _equal(value: Any, expected: Any) -> bool:
    try:
        return _dec(value) == _dec(expected)
    except AssertionError:
        return False


def _load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in fixture["cases"]]
    if len(ids) < 30 or len(set(ids)) != len(ids):
        raise AssertionError("fixture must contain at least 30 unique cases")
    runnable = [case for case in fixture["cases"] if case.get("runnable")]
    stage5 = [case for case in fixture["cases"] if case.get("stage") == "stage5"]
    if len(runnable) < 30:
        raise AssertionError("fixture must contain at least 30 runnable cases")
    if len(stage5) < 10 or any(not case.get("runnable") for case in stage5):
        raise AssertionError("stage5 aging/cash scenario cases must now be runnable")
    categories = {case["category"] for case in runnable[:20]}
    required = {
        "profit_bridge",
        "price_quantity",
        "dimension",
        "missing",
        "zero_budget",
        "negative_budget",
        "wrong_unit",
        "duplicates",
        "manager_judgment",
        "drilldown",
    }
    missing = sorted(required - categories)
    if missing:
        raise AssertionError(f"first 20 runnable cases do not cover: {', '.join(missing)}")
    for case in fixture["cases"]:
        for dataset in case.get("datasets", []):
            if not isinstance(dataset.get("metadata"), dict) or not isinstance(dataset.get("rows"), list):
                raise AssertionError(f"{case['id']}: dataset metadata and rows are required")
            for row in dataset["rows"]:
                if "amount" in row and not isinstance(row["amount"], str):
                    raise AssertionError(f"{case['id']}: amount values must be exact strings")
    return fixture


def _clean_env(extra: dict[str, str]) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DSH_", "FOUNDRY_"))
        and not any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
    }
    env.update(extra)
    return env


def _stop(child: subprocess.Popen | None) -> None:
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


def _wait_report(child: subprocess.Popen, path: Path, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                observed = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                observed = None
            if observed and observed.get("status") != "running":
                if observed.get("status") != "completed":
                    raise RuntimeError(observed.get("error", "finance eval observation failed"))
                return observed
        if child.poll() is not None:
            raise RuntimeError(f"harness exited with code {child.returncode}; see runtime.log")
        time.sleep(0.25)
    raise TimeoutError("finance eval harness timed out")


def _call(foundry: Path, var: Path, command: str, *parts: Any, task: str | None = None, session: str | None = None, raw: bool = False) -> Any:
    result = subprocess.run(
        [
            str(foundry),
            "--var",
            str(var),
            *(["--task", task] if task else []),
            *(["--session", session] if session else []),
            command,
            *map(str, parts),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() if raw else json.loads(result.stdout)


def _seed_cases(foundry: Path, var: Path, output: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeded = []
    for case in cases:
        task = _call(foundry, var, "task-new", "--title", f"r2 finance eval {case['id']}", raw=True)
        workspace = var / "tasks" / task / "analysis"
        uploads = workspace / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        dataset_ids = {}
        for dataset in case["datasets"]:
            source = uploads / f"{dataset['name']}.json"
            source.write_text(json.dumps(dataset["rows"], ensure_ascii=False, sort_keys=True), encoding="utf-8")
            added = _call(
                foundry,
                var,
                "dataset-add",
                "--path",
                source,
                "--name",
                dataset["name"],
                "--meta",
                json.dumps(dataset["metadata"], ensure_ascii=False, sort_keys=True),
                task=task,
            )
            dataset_ids[dataset["name"]] = added["id"]
        input_record = {
            "case_id": case["id"],
            "question": case["question"],
            "datasets": case["datasets"],
            "expected": case["expected"],
        }
        input_sha = _sha(input_record)
        (output / f"{case['id']}-input.json").write_text(
            json.dumps({**input_record, "input_sha256": input_sha}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        seeded.append(
            {
                **case,
                "taskId": task,
                "sessionId": f"r2-finance-eval-{case['id']}-{task}",
                "workspace": str(workspace),
                "datasetIds": dataset_ids,
                "inputSha256": input_sha,
            }
        )
    return seeded


def _matching_rows(state: dict[str, Any], case: dict[str, Any]) -> list[tuple[dict[str, Any], int, dict[str, Any]]]:
    expected = case["expected"]
    matches = []
    for run in state.get("runs", []):
        if run.get("execution_status") != "succeeded":
            continue
        rows = run.get("result", {}).get("rows", [])
        for index, row in enumerate(rows):
            if all(row.get(key) == value for key, value in expected.get("identity", {}).items()):
                matches.append((run, index, row))
    return matches


def _find_expected_cells(state: dict[str, Any], case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected = case["expected"]
    kind = expected["type"]
    if kind == "price_quantity_missing":
        diagnostics = [
            diag
            for run in state.get("runs", [])
            for diag in run.get("result", {}).get("diagnostics", [])
        ]
        if not any(diag.get("code") == expected["diagnostic_code"] for diag in diagnostics):
            raise AssertionError("missing expected price_quantity_missing diagnostic")
        return {}
    if kind == "control_totals":
        cells = {}
        for run in state.get("runs", []):
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                currency = row.get("currency")
                if currency in expected["currencies"] and _equal(row.get("amount"), expected["currencies"][currency]):
                    cells[f"amount_{currency}"] = {"run_id": run["id"], "row": index, "column": "amount", "value": row["amount"]}
        if set(cells) != {f"amount_{key}" for key in expected["currencies"]}:
            raise AssertionError("control totals did not keep expected currency amounts")
        return cells
    if kind == "account_total":
        cells = {}
        for run, index, row in _matching_rows(state, case):
            period = row.get("period")
            if period in expected["claims"] and _equal(row.get("amount"), expected["claims"][period]):
                cells[f"amount_{period}"] = {"run_id": run["id"], "row": index, "column": "amount", "value": row["amount"]}
        if set(cells) != {f"amount_{key}" for key in expected["claims"]}:
            raise AssertionError("account total rows did not match expected period amounts")
        return cells
    if kind == "receivables_aging":
        cells = {}
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                key = f"{row.get('currency')}_{row.get('bucket')}"
                if key in expected["claims"] and _equal(row.get("open_amount"), expected["claims"][key]):
                    cells[key] = {"run_id": run["id"], "row": index, "column": "open_amount", "value": row["open_amount"]}
        if set(cells) != set(expected["claims"]):
            raise AssertionError(f"missing expected aging cells: {sorted(set(expected['claims']) - set(cells))}")
        return cells
    if kind == "cash_13_weeks":
        cells = {}
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                key = f"week_{row.get('week')}"
                if key in expected["claims"] and _equal(row.get("closing_cash"), expected["claims"][key]):
                    cells[key] = {"run_id": run["id"], "row": index, "column": "closing_cash", "value": row["closing_cash"]}
        if set(cells) != set(expected["claims"]):
            raise AssertionError(f"missing expected cash cells: {sorted(set(expected['claims']) - set(cells))}")
        return cells
    cells = {}
    for run, index, row in _matching_rows(state, case):
        if kind == "profit_bridge" and row.get("metric") in expected.get("claims", {}):
            metric = row["metric"]
            if _equal(row.get("contribution"), expected["claims"][metric]):
                cells[metric] = {"run_id": run["id"], "row": index, "column": "contribution", "value": row["contribution"]}
            if expected.get("ratio_status") and row.get("metric") in {"profit", "revenue"} and row.get("ratio_status") != expected["ratio_status"]:
                raise AssertionError("ratio_status did not match expected policy")
            if expected.get("comparison_status") and row.get("comparison_status") != expected["comparison_status"]:
                raise AssertionError("comparison_status did not match expected policy")
        elif kind == "price_quantity":
            for column, value in expected.get("claims", {}).items():
                if _equal(row.get(column), value):
                    cells[column] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
        elif kind == "ratio":
            for column, value in expected.get("claims", {}).items():
                if _equal(row.get(column), value):
                    cells[column] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
    if kind == "profit_bridge":
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                metric = row.get("metric") or row.get("line") or row.get("account") or row.get("management_account")
                if metric in expected.get("claims", {}) and metric not in cells:
                    for column in ("contribution", "profit_impact", "impact", "variance", "amount"):
                        if column in row and _equal(row.get(column), expected["claims"][metric]):
                            cells[metric] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
                            break
    elif kind == "ratio":
        aliases = {
            "numerator": ("numerator", "cost_amount", "cost", "actual_cost"),
            "denominator": ("denominator", "revenue_amount", "revenue", "actual_revenue"),
            "ratio": ("ratio", "cost_rate", "cost_rate_pct", "rate"),
        }
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                for key, columns in aliases.items():
                    if key in cells:
                        continue
                    for column in columns:
                        if column not in row:
                            continue
                        value = row[column]
                        if column.endswith("_pct"):
                            try:
                                value = _dec(value) / Decimal("100")
                            except AssertionError:
                                pass
                        if _equal(value, expected.get("claims", {}).get(key)):
                            cells[key] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
                            break
    expected_keys = set(expected.get("claims", {}))
    zero_missing = {key for key in expected_keys - set(cells) if _equal(expected["claims"][key], "0")}
    for key in zero_missing:
        cells[key] = {"run_id": "zero-not-materialized", "row": -1, "column": key, "value": "0", "synthetic_zero": True}
    if set(cells) != expected_keys:
        raise AssertionError(f"missing expected cells: {sorted(expected_keys - set(cells))}")
    if kind == "profit_bridge" and expected_keys >= {"profit", "revenue", "cost", "expense"}:
        if _dec(cells["profit"]["value"]) != sum(_dec(cells[key]["value"]) for key in ("revenue", "cost", "expense")):
            raise AssertionError("profit bridge does not close")
    return cells


def _verified_draft_cells(state: dict[str, Any], cells: dict[str, dict[str, Any]]) -> set[str]:
    verified = {name for name, cell in cells.items() if cell.get("synthetic_zero")}
    for draft in state.get("drafts", []):
        for name, cell in cells.items():
            if cell["run_id"] not in draft.get("run_ids", []):
                continue
            for claim in draft.get("claims", []):
                if (
                    claim.get("basis") == "calculation"
                    and claim.get("verification_status") == "matches_run"
                    and claim.get("run_id") == cell["run_id"]
                    and claim.get("row") == cell["row"]
                    and claim.get("column") == cell["column"]
                    and _equal(claim.get("value"), cell["value"])
                ):
                    verified.add(name)
    return verified


def _assistant_texts(messages: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") == "text":
                texts.append(str(part.get("text", "")))
    return texts


def _scan_forbidden(case: dict[str, Any], observed: dict[str, Any], state: dict[str, Any]) -> list[str]:
    if case["expected"].get("requires_judgment"):
        return []
    blobs = [draft.get("body", "") for draft in state.get("drafts", [])]
    return [text[:500] for text in blobs if FORBIDDEN_CAUSAL.search(text)]




def _verify_method_loads(observed: dict[str, Any], manifest: dict[str, Any]) -> None:
    expected = {item["id"]: item for item in manifest.get("skills", [])}
    loaded = observed.get("explicit_loads", [])
    loaded_names = {item.get("name") for item in loaded}
    if loaded_names != set(expected):
        raise AssertionError(f"method skill explicit loads incomplete: {sorted(set(expected) - loaded_names)}")
    for item in loaded:
        name = item["name"]
        source = Path(expected[name]["file"])
        if Path(item.get("resourceBase", {}).get("path", "")).resolve() != source.parent.resolve():
            raise AssertionError(f"method skill {name} loaded from unexpected resource base")
        skill_text = source.read_text(encoding="utf-8")
        body = skill_text.split("---", 2)[2].strip() if skill_text.startswith("---") else skill_text.strip()
        if hashlib.sha256(body.encode()).hexdigest() != item.get("content_sha256"):
            raise AssertionError(f"method skill {name} content hash mismatch")
        resources = item.get("resources", [])
        if {resource.get("resource") for resource in resources} != {"FOUNDRY.md", "CONNECTORS.md"}:
            raise AssertionError(f"method skill {name} did not load both method resources")
        for resource in resources:
            original = Path(manifest["root"]) / resource["resource"]
            if hashlib.sha256(original.read_bytes()).hexdigest() != resource.get("sha256"):
                raise AssertionError(f"method resource hash mismatch for {name}/{resource.get('resource')}")


def _case_tool_errors(observed: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for index, call in enumerate(observed.get("calls", [])):
        if call.get("isError"):
            errors.append({"index": index, "tool": call.get("name"), "error": call.get("error")})
    return errors


def _verify_skill_first(observed: dict[str, Any]) -> None:
    method_loaded = False
    work_tools = {
        "finance_context_save",
        "finance_map_save",
        "run_metric",
        "explain_variance",
        "drilldown_fact",
        "save_explanation_draft",
        "analysis-save",
        "analysis-run",
        "analysis-draft",
        "finance_scenario_save",
        "finance_scenario_run",
    }
    for call in observed.get("calls", []):
        name = call.get("name")
        if name == "skill" and not call.get("isError"):
            method_loaded = True
        if name in work_tools:
            if not method_loaded:
                raise AssertionError(f"case used {name} before successfully loading a method skill")
            return
    raise AssertionError("case did not reach any finance work tool after loading a method skill")

def _score_case(foundry: Path, var: Path, case: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    tool_errors = _case_tool_errors(observed)
    fatal_errors = [err for err in tool_errors if err.get("tool") in {"skill", "method-resource", "list_finance_context"}]
    if fatal_errors:
        raise AssertionError(f"method/catalog tool errors observed: {fatal_errors[:3]}")
    _verify_skill_first(observed)
    catalog_names = {item.get("name") for item in observed.get("catalog", [])}
    missing_methods = {"financial-statements", "variance-analysis"} - catalog_names
    if missing_methods:
        raise AssertionError(f"case method catalog missing required skills: {sorted(missing_methods)}")
    state = _call(foundry, var, "analysis-state", task=case["taskId"])
    cells = _find_expected_cells(state, case)
    calls = observed.get("calls", [])
    used = {call.get("name") for call in calls if not call.get("isError")}
    drilldowns = [call for call in calls if call.get("name") == "drilldown_fact" and not call.get("isError")]
    if case["expected"].get("requires_map_save") and "finance_map_save" not in used:
        raise AssertionError("case required finance_map_save but the model did not call it")
    forbidden = _scan_forbidden(case, observed, state)
    if forbidden:
        raise AssertionError("unsupported causal certainty found in raw output")
    if not used & CALC_TOOLS:
        raise AssertionError("no finance calculation tool was used")
    if case["expected"]["type"] not in {"price_quantity_missing"} and not drilldowns:
        raise AssertionError("no successful drilldown_fact call was observed")
    draft_verified = _verified_draft_cells(state, cells)
    if cells and draft_verified != set(cells):
        raise AssertionError(f"draft did not verify all expected cells: {sorted(set(cells) - draft_verified)}")
    if case["expected"].get("requires_voucher_drilldown"):
        if "true" not in json.dumps(drilldowns, ensure_ascii=False).lower():
            raise AssertionError("voucher drilldown case did not return voucher_detail_available")
    return {
        "id": case["id"],
        "task_id": case["taskId"],
        "session_id": case["sessionId"],
        "input_sha256": case["inputSha256"],
        "status": "passed",
        "tools_used": sorted(used),
        "run_ids": sorted({cell["run_id"] for cell in cells.values() if not cell.get("synthetic_zero")}),
        "verified_cells": cells,
        "draft_verified": sorted(draft_verified),
        "recoverable_tool_errors": tool_errors,
        "raw_output_sha256": _sha(observed),
    }


def score_observation(foundry: Path, var: Path, cases: list[dict[str, Any]], observed: dict[str, Any]) -> dict[str, Any]:
    by_id = {case["id"]: case for case in cases}
    results = []
    failures = []
    for row in observed.get("cases", []):
        case = by_id[row["id"]]
        try:
            results.append(_score_case(foundry, var, case, row))
        except Exception as exc:  # retain failure detail for manual review
            failures.append({"id": row["id"], "error": str(exc), "raw_output_sha256": _sha(row)})
    seen = len(observed.get("cases", []))
    completed = sum(1 for row in observed.get("cases", []) if row.get("completed"))
    passed = len(results)
    rate = Decimal(passed) / Decimal(completed or 1)
    return {
        "seen": seen,
        "completed": completed,
        "passed": passed,
        "pass_rate": format(rate, "f"),
        "status": "passed" if completed and rate >= Decimal("0.90") and not failures else "failed",
        "cases": results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--dsh-root", type=Path, default=DEFAULT_DSH_ROOT)
    parser.add_argument("--foundry", type=Path, default=DEFAULT_FOUNDRY)
    parser.add_argument("--plugin", type=Path, default=DEFAULT_PLUGIN)
    parser.add_argument("--credentials-home", type=Path, default=DEFAULT_CREDENTIALS_HOME)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[], help="run a specific fixture case; may be repeated")
    parser.add_argument("--cases-limit", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--live", action="store_true", help="invoke the configured model")
    parser.add_argument("--validate-fixture-only", action="store_true")
    args = parser.parse_args()

    fixture = _load_fixture(args.fixture)
    runnable_all = [case for case in fixture["cases"] if case.get("runnable")]
    if args.case_id:
        wanted = set(args.case_id)
        runnable = [case for case in runnable_all if case["id"] in wanted]
        missing = sorted(wanted - {case["id"] for case in runnable})
        if missing:
            raise AssertionError(f"unknown or non-runnable case id: {', '.join(missing)}")
    else:
        runnable = runnable_all[: args.cases_limit]
    pending = [case["id"] for case in fixture["cases"] if not case.get("runnable")]
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "fixture-summary.json").write_text(
        json.dumps(
            {
                "fixture_version": fixture["version"],
                "total_cases": len(fixture["cases"]),
                "runnable_cases": len(runnable_all),
                "selected_cases": [case["id"] for case in runnable],
                "pending_cases": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if args.validate_fixture_only:
        print(json.dumps({"status": "fixture-valid", "output": str(args.output)}, ensure_ascii=False))
        return 0
    if not args.live:
        parser.error("--live is required unless --validate-fixture-only is used")

    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for live DSH evals")
    dsh = args.dsh_root / "node_modules/@deepseek-ai/dsh/lib/bin.js"
    if not dsh.is_file():
        raise RuntimeError(f"DSH runtime is missing: {dsh}")
    if not args.foundry.is_file():
        raise RuntimeError(f"foundry CLI is missing: {args.foundry}")

    source_settings = yaml.safe_load((args.credentials_home / "settings.yaml").read_text(encoding="utf-8")) or {}
    selection = source_settings.get("agent-default-model")
    expected_model = fixture["model_contract"]
    if (
        not selection
        or selection.get("provider") != expected_model["provider"]
        or selection.get("model") != expected_model["model"]
        or selection.get("reasoningEffort") != expected_model["reasoning_effort"]
    ):
        raise RuntimeError("configured model does not match the r2 finance eval contract; no provider was changed")
    credentials = yaml.safe_load((args.credentials_home / ".credentials.yaml").read_text(encoding="utf-8")) or {}
    reference = source_settings.get("llm-deepseek", {}).get("apiKeyEnv", "DEEPSEEK_API_KEY")
    refs = credentials.get("refs", credentials)
    if not refs.get(reference):
        raise RuntimeError("configured provider credential is missing; no fallback credential was used")

    var = args.output / "var"
    seeded = _seed_cases(args.foundry, var, args.output, runnable)
    manifest = _call(args.foundry, var, "method-skills", "--json")
    if not manifest.get("exists") or manifest.get("missing"):
        raise RuntimeError("bundled method skills are not available for finance evals")
    config = {
        "dshRoot": str(args.dsh_root.resolve()),
        "report": str(args.output / "session.json"),
        "timeoutSeconds": args.timeout_seconds,
        "agentsHome": "",
        "ids": manifest["ids"],
        "methodRoot": manifest["root"],
        "cases": seeded,
    }
    final = {
        "status": "running",
        "fixture_version": fixture["version"],
        "model": selection,
        "method_manifest": manifest,
        "selected_cases": [case["id"] for case in seeded],
        "pending_cases": pending,
    }
    child: subprocess.Popen | None = None
    with tempfile.TemporaryDirectory(prefix="foundry-finance-evals-") as scratch_text:
        scratch = Path(scratch_text)
        home = scratch / "harness"
        home.mkdir()
        config["agentsHome"] = str(scratch / "agents")
        credential_path = home / ".credentials.yaml"
        descriptor = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as sink:
            yaml.safe_dump({"version": credentials.get("version", 1), "refs": {reference: refs[reference]}}, sink)
        settings = {"agent-default-model": selection, "agent-presets": {"default": "analysis"}}
        if "llm-deepseek" in source_settings:
            settings["llm-deepseek"] = source_settings["llm-deepseek"]
        (home / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
        env = _clean_env(
            {
                "DSH_HOME": str(home),
                "DSH_AGENTS_HOME": str(scratch / "agents"),
                "DSH_BUNDLED_SKILL_DIR": manifest["root"],
                "FOUNDRY_VAR": str(var),
                "FOUNDRY_BIN": str(args.foundry),
            }
        )
        try:
            _call(args.foundry, var, "install-presets", "--dsh-home", home, raw=True)
            subprocess.run([node, str(dsh), "--profile", "web", "--dump-config"], env=env, cwd=scratch, capture_output=True, check=True)
            probe = scratch / "probe"
            probe.mkdir()
            shutil.copyfile(REPO / "tools/verify_finance_evals.mjs", probe / "index.mjs")
            (probe / "config.json").write_text(json.dumps(config), encoding="utf-8")
            profile = home / "profiles/web"
            package_path = profile / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package.setdefault("dependencies", {})["finance-skill-foundry-dsh"] = f"link:{args.plugin.resolve()}"
            bundles = package.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
            if "finance-skill-foundry-dsh" not in bundles:
                bundles.append("finance-skill-foundry-dsh")
            package_path.write_text(json.dumps(package), encoding="utf-8")
            modules = profile / "node_modules"
            modules.mkdir(exist_ok=True)
            link = modules / "finance-skill-foundry-dsh"
            if not link.exists():
                link.symlink_to(args.plugin.resolve(), target_is_directory=True)
            (profile / "cordis.patch.yml").write_text(
                yaml.safe_dump([{"insert": [{"id": "foundry-finance-evals-verifier", "name": str(probe / "index.mjs")}]}]),
                encoding="utf-8",
            )
            with (args.output / "runtime.log").open("w", encoding="utf-8") as sink:
                child = subprocess.Popen(
                    [node, str(dsh), "--profile", "web", "--no-open", "--port", "0"],
                    cwd=scratch,
                    env=env,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                observed = _wait_report(child, args.output / "session.json", args.timeout_seconds * max(1, len(seeded)) + 120)
            if observed["model"] != selection:
                raise AssertionError("actual session changed the configured model")
            _verify_method_loads(observed, manifest)
            score = score_observation(args.foundry, var, seeded, observed)
            final.update(score)
            final["session_evidence_sha256"] = hashlib.sha256((args.output / "session.json").read_bytes()).hexdigest()
            final["raw_session_path"] = str(args.output / "session.json")
        except Exception as exc:
            final.update(status="failed", error=str(exc))
        finally:
            _stop(child)
    (args.output / "verification.json").write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": final["status"], "passed": final.get("passed"), "completed": final.get("completed"), "output": str(args.output), "error": final.get("error")}, ensure_ascii=False))
    return 0 if final["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
