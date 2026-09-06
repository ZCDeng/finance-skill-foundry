"""Run real skill/model analysis in isolated DSH state using an existing credential.

Requires the existing development environment (PyYAML) and staged DSH runtime.
Only synthetic finance data is sent. Credentials are copied into an ephemeral
0600 file and removed on exit; user settings and task data are never modified.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import shutil
import subprocess
import tempfile
import time

import yaml


def equal_amount(value, expected):
    try:
        return Decimal(str(value)) == Decimal(expected)
    except InvalidOperation:
        return False


# Independent financial truth, matched to named output cells rather than any
# occurrence of a coincidentally equal number elsewhere in a result.
EXPECTED_CELLS = {
    "G1": [
        ("profit_difference", "5", r"(profit|利润).*(var|diff|delta|change|impact|差异)|(var|diff|delta|change|impact|差异).*(profit|利润)"),
        ("revenue_contribution", "20", r"revenue|收入"),
        ("cost_contribution", "-10", r"cost|成本"),
        ("expense_contribution", "-5", r"expense|费用"),
    ],
    "G2": [
        ("revenue_difference", "32", r"var|diff|delta|change|差异|增量"),
        ("quantity_contribution", "20", r"quantity|qty|volume|数量|销量"),
        ("price_contribution", "12", r"price|价格|单价"),
    ],
}


def verify_financial_cells(state, case_id):
    cells = []
    for run in state["runs"]:
        if (run.get("execution_status") or run.get("status")) != "succeeded":
            continue
        for row_index, row in enumerate(run.get("result", {}).get("rows", [])):
            labels = " ".join(str(v) for v in row.values() if isinstance(v, str) and not re.fullmatch(r"-?\d+(\.\d+)?", v))
            for column, value in row.items():
                cells.append({"run_id": run["id"], "row": row_index, "column": column,
                              "value": value, "label": f"{column} {labels}"})
    matches = {}
    for metric, amount, pattern in EXPECTED_CELLS[case_id]:
        matched = []
        for cell in cells:
            label = cell["label"]
            if not re.search(pattern, label, flags=re.I) or re.search(r"pct|percent|rate|share|率|占比|%", label, re.I):
                continue
            if metric.endswith("contribution") and not re.search(
                r"contrib|effect|impact|bridge|var|diff|delta|change|贡献|影响|差异|分解", label, re.I
            ):
                continue
            if equal_amount(cell["value"], amount):
                matched.append(cell)
            elif (metric in ("cost_contribution", "expense_contribution")
                  and re.search(r"var|diff|delta|change|差异", label, re.I)
                  and not re.search(r"contribution|effect|impact|贡献|影响", label, re.I)
                  and equal_amount(cell["value"], str(-Decimal(amount)))):
                # An actual-minus-budget expense variance has the opposite
                # sign to its profit contribution. Retain the original cell
                # and this explicit accounting normalization in the evidence.
                matched.append({**cell, "raw_value": cell["value"], "value": amount,
                                "normalization": "profit_contribution = -expense_variance"})
        if not matched:
            raise AssertionError(f"{case_id}: missing named successful result for {metric}={amount}")
        matches[metric] = matched
    return matches


def verified_drafts(state, matched_cells):
    """Require one persisted draft to cite the entire closed financial bridge."""
    drafts = []
    for draft in state["drafts"]:
        cited = {}
        for metric, cells in matched_cells.items():
            for cell in cells:
                if cell["run_id"] not in draft.get("run_ids", []):
                    continue
                if any(claim.get("basis") == "calculation" and claim.get("verification_status") == "matches_run"
                       and all(claim.get(key) == cell[key] for key in ("run_id", "row", "column"))
                       and equal_amount(claim.get("value"), str(cell.get("raw_value", cell["value"])))
                       for claim in draft.get("claims", [])):
                    cited[metric] = cell
                    break
        if len(cited) != len(matched_cells):
            continue
        values = [Decimal(str(cell["value"])) for cell in cited.values()]
        if values[0] != sum(values[1:]):
            continue
        drafts.append({**draft, "verified_metric_claims": cited})
    return drafts


def stop_child(child):
    if child is not None and child.poll() is None:
        # Every verifier launch has its own group; retire its owned harness too.
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


def wait_report(child, path, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                observed = json.loads(path.read_text())
            except json.JSONDecodeError:
                observed = None
            if observed and observed["status"] != "running":
                if observed["status"] != "completed":
                    raise RuntimeError(observed.get("error", "Harness observation failed"))
                return observed
        if child.poll() is not None:
            raise RuntimeError(f"Harness exited with code {child.returncode}; see runtime.log")
        time.sleep(0.2)
    raise TimeoutError("Harness verification timed out")


def verify_loaded_resources(observed, manifest):
    expected = {item["id"]: item for item in manifest["skills"]}
    if {item["name"] for item in observed["explicit_loads"]} != set(expected):
        raise AssertionError("All four skill bodies and their references must load")
    for loaded in observed["explicit_loads"]:
        path = Path(expected[loaded["name"]]["file"])
        if Path(loaded["resourceBase"]["path"]).resolve() != path.parent.resolve():
            raise AssertionError("A personal skill shadowed the packaged method")
        source = path.read_text()
        body = source.split("---", 2)[2].strip() if source.startswith("---") else source.strip()
        if hashlib.sha256(body.encode()).hexdigest() != loaded["content_sha256"]:
            raise AssertionError(f"Loaded body differs from bundled {loaded['name']}")
        if {item["resource"] for item in loaded["resources"]} != {"FOUNDRY.md", "CONNECTORS.md"}:
            raise AssertionError("Both relative method resources must load")
        for resource in loaded["resources"]:
            original = Path(manifest["root"]) / resource["resource"]
            if original.read_text() != resource["content"] or hashlib.sha256(original.read_bytes()).hexdigest() != resource["sha256"]:
                raise AssertionError("Loaded relative resource does not match its canonical bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-root", required=True, type=Path)
    parser.add_argument("--foundry", required=True, type=Path)
    parser.add_argument("--plugin", required=True, type=Path)
    parser.add_argument("--app", type=Path, help="Launch this actual .app and test its owned harness process")
    parser.add_argument("--credentials-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--resume-observation", type=Path, help="Recheck saved cases in a copied var; launch only explicit resource/restart probes, no model rerun")
    parser.add_argument("--live", action="store_true", help="Allow requests to the existing configured model")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required: this verifier invokes the configured model")
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dsh_root, foundry, plugin = args.dsh_root.resolve(), args.foundry.resolve(), args.plugin.resolve()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for the development verifier")
    dsh = dsh_root / "node_modules/@deepseek-ai/dsh/lib/bin.js"
    fixture = json.loads((repo / "tests/fixtures/finance_baseline/cases.json").read_text())
    var = output / "var"
    resumed = None
    if args.resume_observation:
        source = args.resume_observation.resolve()
        resumed = json.loads((source / "session.json").read_text())
        if resumed.get("status") != "completed":
            raise RuntimeError("Only a completed observation can be resumed")
        shutil.copytree(source / "var", var)
        shutil.copyfile(source / "session.json", output / "source-session.json")

    def cli(command, *parts, task=None, session=None, raw=False):
        result = subprocess.run([str(foundry), "--var", str(var),
                                 *(["--task", task] if task else []),
                                 *(["--session", session] if session else []),
                                 command, *map(str, parts)],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip() if raw else json.loads(result.stdout)

    manifest = cli("method-skills", "--json")
    application = args.app.resolve() if args.app else None
    if application:
        resources = application / "Contents/Resources"
        if not all(path.is_relative_to(resources) for path in (dsh_root, foundry, plugin, Path(manifest["root"]))):
            raise RuntimeError("App verification must use only resources inside the tested app")
    config = {"dshRoot": str(dsh_root), "report": str(output / "session.json"),
              "timeoutSeconds": args.timeout_seconds, "ids": manifest["ids"], "cases": []}
    for case in [{"id": "explicit", "datasets": {}, "question": "", "explicit": True}, *(fixture["cases"][:2] if resumed is None else [])]:
        task = cli("task-new", "--title", f"技能验收 {case['id']}", raw=True)
        session = f"skill-{case['id']}-{task}"
        for name, rows in case["datasets"].items():
            source = output / f"{task}-{name}.json"
            source.write_text(json.dumps(rows, ensure_ascii=False))
            cli("dataset-add", "--path", source, "--name", name,
                "--meta", json.dumps({"currency": fixture["currency"], "unit": fixture["unit"]}), task=task)
        workspace = var / "tasks" / task / "analysis"
        workspace.mkdir(parents=True, exist_ok=True)
        config["cases"].append({**case, "sessionId": session, "taskId": task,
                               "workspace": str(workspace)})
    source_settings = yaml.safe_load((args.credentials_home / "settings.yaml").read_text()) or {}
    selection = source_settings.get("agent-default-model")
    if not selection or selection.get("provider") != "deepseek-official":
        raise RuntimeError("This verifier currently supports the configured deepseek-official route only; no model was changed")
    credentials = yaml.safe_load((args.credentials_home / ".credentials.yaml").read_text()) or {}
    reference = source_settings.get("llm-deepseek", {}).get("apiKeyEnv", "DEEPSEEK_API_KEY")
    refs = credentials.get("refs", credentials)
    if not refs.get(reference):
        raise RuntimeError("Configured provider credential is missing; no fallback credential was used")
    results = {"status": "running", "model": selection, "fixture_version": fixture["version"],
               "manifest": manifest, "cases": []}
    child = None
    with tempfile.TemporaryDirectory(prefix="foundry-live-skill-") as scratch:
        profile_root = Path(scratch) / "profile"
        home = profile_root / "harness"
        home.mkdir(parents=True)
        config["agentsHome"] = str(Path(scratch) / "agents")
        try:
            credential_path = home / ".credentials.yaml"
            selected_credentials = {"version": credentials.get("version", 1), "refs": {reference: refs[reference]}}
            descriptor = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as sink:
                yaml.safe_dump(selected_credentials, sink)
            settings = {"agent-default-model": selection, "agent-presets": {"default": "analysis"}}
            if "llm-deepseek" in source_settings:
                settings["llm-deepseek"] = source_settings["llm-deepseek"]
            (home / "settings.yaml").write_text(yaml.safe_dump(settings))
            clean_env = {key: value for key, value in os.environ.items()
                         if not key.startswith(("DSH_", "FOUNDRY_"))
                         and not any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
            clean_env.update(DSH_HOME=str(home), DSH_AGENTS_HOME=str(Path(scratch) / "agents"),
                             DSH_BUNDLED_SKILL_DIR=manifest["root"], FOUNDRY_VAR=str(var), FOUNDRY_BIN=str(foundry))
            cli("install-presets", "--dsh-home", home, raw=True)
            subprocess.run([node, str(dsh), "--profile", "web", "--dump-config"], env=clean_env,
                           cwd=scratch, capture_output=True, check=True)
            probe = Path(scratch) / "probe"
            probe.mkdir()
            shutil.copyfile(repo / "tools/verify_method_skill_session.mjs", probe / "index.mjs")
            (probe / "config.json").write_text(json.dumps(config))
            profile = home / "profiles/web"
            package_path = profile / "package.json"
            package = json.loads(package_path.read_text())
            package.setdefault("dependencies", {})["finance-skill-foundry-dsh"] = f"link:{plugin}"
            package.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", []).append("finance-skill-foundry-dsh")
            package_path.write_text(json.dumps(package))
            modules = profile / "node_modules"
            modules.mkdir(exist_ok=True)
            (modules / "finance-skill-foundry-dsh").symlink_to(plugin, target_is_directory=True)
            patch = profile / "cordis.patch.yml"
            patch.write_text(yaml.safe_dump([{"insert": [{"id": "foundry-method-session-verifier", "name": str(probe / "index.mjs")}]}]))
            launch = [node, str(dsh), "--profile", "web", "--no-open", "--port", "0"]
            if application:
                app_info = plistlib.loads((application / "Contents/Info.plist").read_bytes())
                launch = [str(application / "Contents/MacOS" / app_info["CFBundleExecutable"]),
                          f"--user-data-dir={profile_root}"]
                results["application"] = {"path": str(application), "version": app_info["CFBundleShortVersionString"]}
                clean_env = {k: v for k, v in clean_env.items()
                             if not k.startswith(("DSH_", "FOUNDRY_")) and k != "ELECTRON_RUN_AS_NODE"}
                clean_env["FOUNDRY_VAR"] = str(var)
            with (output / "runtime.log").open("w") as sink:
                child = subprocess.Popen(launch,
                                         cwd=scratch, env=clean_env, stdout=sink, stderr=subprocess.STDOUT,
                                         start_new_session=True)
                observed = wait_report(child, output / "session.json", args.timeout_seconds * 2 + 90)
            verify_loaded_resources(observed, manifest)
            if observed["model"] != selection:
                raise AssertionError("The actual session changed the configured model")
            if Path(observed["runtime"]["bundled_root"]).resolve() != Path(manifest["root"]).resolve():
                raise AssertionError("Harness did not receive the application's bundled method root")
            if application and observed["runtime"]["ppid"] != child.pid:
                raise AssertionError("The tested harness was not spawned by the tested native app")
            if resumed is not None:
                verify_loaded_resources(resumed, manifest)
                if resumed["model"] != selection:
                    raise AssertionError("Saved observation used a different model")
                observed["cases"].extend(row for row in resumed["cases"] if row["id"] != "explicit")
                results["resumed_observation"] = {
                    "path": str(args.resume_observation.resolve()),
                    "session_sha256": hashlib.sha256((output / "source-session.json").read_bytes()).hexdigest(),
                    "model_rerun": False,
                }
            for case in fixture["cases"][:2]:
                row = next(item for item in observed["cases"] if item["id"] == case["id"])
                loaded = [call for call in row["calls"] if call["name"] == "skill" and not call["isError"]
                          and call["arguments"].get("name") in case["expected_skill"]]
                used = {call["arguments"].get("name") for call in loaded}
                if not used.intersection(case["expected_skill"]):
                    raise AssertionError(f"{case['id']}: model did not load the matching skill")
                skill_index = next(i for i, c in enumerate(row["calls"]) if c in loaded)
                first_calculation = next(i for i, c in enumerate(row["calls"]) if c["name"] in ("analysis-run", "analysis-script"))
                if skill_index >= first_calculation:
                    raise AssertionError(f"{case['id']}: matching skill was not loaded before calculation")
                state = cli("analysis-state", task=row["task_id"])
                expected = Decimal(case["expected_difference"])
                matched_cells = verify_financial_cells(state, case["id"])
                difference_cells = next(iter(matched_cells.values()))
                run_ids = {cell["run_id"] for cell in difference_cells}
                drafts = verified_drafts(state, matched_cells)
                if not drafts:
                    raise AssertionError(f"{case['id']}: no draft cites every component of the closed financial bridge")
                results["cases"].append({"id": case["id"], "session_id": row["session_id"], "task_id": row["task_id"],
                                         "skills_used": sorted(used), "run_ids": sorted(run_ids),
                                         "draft_ids": [draft["id"] for draft in drafts], "expected_difference": str(expected),
                                         "verified_cells": matched_cells,
                                         "draft_metric_claims": {d["id"]: d["verified_metric_claims"] for d in drafts}})
            if application:
                stop_child(child)
                explicit = config["cases"][0]
                config["cases"] = [{**explicit, "sessionId": explicit["sessionId"] + "-restart"}]
                config["report"] = str(output / "session-restart.json")
                (probe / "config.json").write_text(json.dumps(config))
                with (output / "restart.log").open("w") as sink:
                    child = subprocess.Popen(launch, cwd=scratch, env=clean_env, stdout=sink,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                    restarted = wait_report(child, output / "session-restart.json", 90)
                verify_loaded_resources(restarted, manifest)
                if restarted["runtime"]["ppid"] != child.pid:
                    raise AssertionError("Restart probe is not owned by the restarted app")
                for case in results["cases"]:
                    state = cli("analysis-state", task=case["task_id"])
                    verify_financial_cells(state, case["id"])
                    if not set(case["draft_ids"]) <= {draft["id"] for draft in state["drafts"]}:
                        raise AssertionError("A persisted draft was lost on restart")
                results["restart"] = {"status": "passed", "runtime": restarted["runtime"],
                                      "body_hashes": {item["name"]: item["content_sha256"] for item in restarted["explicit_loads"]}}
            results["status"] = "passed"
            results["session_evidence_sha256"] = hashlib.sha256((output / "session.json").read_bytes()).hexdigest()
        except Exception as error:
            results.update(status="failed", error=str(error))
        finally:
            stop_child(child)
    (output / "verification.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": results["status"], "model": selection, "cases": results["cases"],
                      "error": results.get("error"), "evidence": str(output)}, ensure_ascii=False))
    return 0 if results["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
