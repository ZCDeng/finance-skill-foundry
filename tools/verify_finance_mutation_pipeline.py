#!/usr/bin/env python3
"""Exercise financial mutations through the actual Foundry CLI, without a provider.

All records are created by public CLI calls in a new isolated var directory. The
observer reads actual validation/current completion; it never patches stored runs
or submits a prelabelled result to a scorer. A green control is mandatory for a
mutation to count as detected. This is deterministic pipeline verification, not
model evaluation or human professional approval.
"""

from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/finance_evals/professional_runtime_v1/public"
TEMPLATE = "linked_three_statement_management_v1"
BASE_FIELDS = ["purpose", "effective_period.start", "effective_period.end",
               "functional_currency", "presentation_currency", "presentation_unit", "entity_scope"]
MUTATIONS = {
    "M01": "wrong_formula", "M02": "broken_reference", "M03": "fabricated_source",
    "M04": "unauthorized_state", "M05": "omitted_check", "M06": "false_completion",
    "M07": "advance_recognized_as_revenue", "M08": "current_expense_capitalized",
    "M09": "old_receivable_recognized_as_revenue", "M10": "restricted_cash_available",
    "M11": "disputed_receivable_deleted",
}
FROZEN_COVERAGE = {
    "M01": {"status": "covered", "scope": "Registered formula override submitted to the actual computation API."},
    "M02": {"status": "covered", "scope": "A source binding references no archived row."},
    "M03": {"status": "covered", "scope": "A syntactically valid, nonexistent fact hash is cited."},
    "M04": {"status": "covered", "scope": "Assistant attempts manager confirmation; caller labels carry no authority."},
    "M05": {"status": "covered", "scope": "A genuine zero residual check is omitted from the cited result."},
    "M06": {"status": "covered", "scope": "A draft missing required run/claims submits a false complete status."},
    "M07": {"status": "covered", "scope": "Original 120/12/1 is allocated by the registered source-bound policy to revenue 10/liability 110; balanced candidate journal 120/0 is rejected. Legal check still requires professional review."},
    "M08": {"status": "covered", "scope": "Consumed service expense 100 versus actual proposed asset 100; independent source-policy-backed qualifying acquisition control. Legal checks still require professional review."},
    "M09": {"status": "covered", "scope": "Actual balanced candidate three-statement rows derived from a native E18 baseline and old-AR movement; wrong revenue/AR treatment rejected; separate fulfilled cash-sale control. Legal transaction checks still require professional review."},
    "M10": {"status": "covered", "scope": "Native cash 100/restricted 30/available 70 plus source-bound obligation 80/shortfall 10; independent effective, future and ineffective release documents. Release checks still require professional review."},
    "M11": {"status": "covered", "scope": "Native source-backed full 115, active subset 95 and disputed subset 20 are reconciled in the legal control; the mutant misstates 95 as full population."},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(path):
    return {str(p.relative_to(path)): file_hash(p) for p in sorted(Path(path).rglob("*")) if p.is_file()}


def assert_amounts(observed, expected):
    """Expected constants come from the frozen examples, never product output."""
    for key, value in expected.items():
        if key not in observed or Decimal(str(observed[key])) != Decimal(str(value)):
            raise AssertionError(f"independent oracle mismatch: {key}: {observed.get(key)} != {value}")
    return {"expected": expected, "observed": {key: observed[key] for key in expected}, "status": "pass"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidate_identity(foundry, candidate_manifest=None):
    binary = Path(foundry).resolve()
    if candidate_manifest:
        manifest_path = Path(candidate_manifest).resolve()
        manifest = json.loads(manifest_path.read_text())
        package = manifest_path.parent
        observed, errors = {}, []
        for relative, expected in manifest["files"].items():
            path = (package / relative).resolve()
            if not path.is_relative_to(package) or not path.is_file():
                errors.append(f"missing or outside candidate: {relative}")
                continue
            observed[relative] = file_hash(path)
            if observed[relative] != expected:
                errors.append(f"hash mismatch: {relative}")
        if not binary.is_relative_to(package):
            errors.append("CLI is outside the manifest candidate directory")
        # The frozen source launcher must import the manifest's package root,
        # rather than the mutable checkout or whichever editable install wins.
        if binary.read_bytes().startswith(b"#!"):
            tree = ast.parse(binary.read_text())
            roots = [node.args[1].value for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and ast.unparse(node.func) == "sys.path.insert"
                     and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                     and isinstance(node.args[1].value, str)]
            if str(package) not in roots:
                errors.append("source launcher does not explicitly bind the manifest package root")
        if not observed or not any(name.startswith("foundry/") for name in observed):
            errors.append("manifest does not cover the runtime package")
        for directory in ("foundry", "method", "dsh-plugin"):
            for path in (package / directory).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    relative = str(path.relative_to(package))
                    if relative not in observed:
                        errors.append(f"runtime file omitted from manifest: {relative}")
        if errors:
            raise ValueError("invalid candidate identity: " + "; ".join(errors))
        return {"path": str(binary), "sha256": file_hash(binary), "execution_kind": "manifest_bound_candidate",
                "manifest_path": str(manifest_path), "manifest_sha256": file_hash(manifest_path),
                "manifest_base_commit": manifest.get("base_commit"), "package_root": str(package),
                "verified_files": observed, "verified_file_count": len(observed), "manifest_verified": True}
    # A console script hashes only its launcher; retain the source tree manifest
    # too. For a frozen CLI the binary and sibling bundle files are authoritative.
    source_files = {str(p.relative_to(ROOT)): file_hash(p)
                    for p in sorted((ROOT / "foundry").rglob("*"))
                    if p.is_file() and "__pycache__" not in p.parts}
    frozen_files = {}
    if binary.parent.name == "foundry" and (binary.parent / "_internal").is_dir():
        frozen_files = {str(p.relative_to(binary.parent)): file_hash(p)
                        for p in sorted((binary.parent / "_internal").rglob("*")) if p.is_file()}
    return {"path": str(binary), "sha256": file_hash(binary),
            "source_tree_sha256": digest(source_files), "source_files": source_files,
            "frozen_bundle_sha256": digest(frozen_files) if frozen_files else None,
            "frozen_bundle_files": frozen_files,
            "execution_kind": "frozen_cli" if frozen_files else "development_cli_launcher",
            "identity_limitation": None if frozen_files else "Checkout hash is a development observation; use --candidate-manifest to bind a frozen source launcher."}


class CLI:
    def __init__(self, foundry, directory):
        self.foundry = str(Path(foundry).resolve())
        self.directory = directory
        self.var = directory / "var"
        self.task = None
        self.sequence = 0
        self.calls = []
        self.env = {k: v for k, v in os.environ.items()
                    if k not in {"FOUNDRY_VAR", "FOUNDRY_TASK", "FOUNDRY_SESSION",
                                 "FOUNDRY_BIN", "FOUNDRY_DSH_INSTALL", "FOUNDRY_FORMULATOR_BIN"}
                    and not k.endswith(("API_KEY", "API_TOKEN"))}

    def call(self, command, *parts, spec=None, actor="assistant", required=True, raw=False):
        self.sequence += 1
        argv = [self.foundry, "--var", str(self.var), "--actor", actor]
        if self.task:
            argv += ["--task", self.task]
        argv += [command, *map(str, parts)]
        if spec is not None:
            argv += ["--spec", json.dumps(spec, ensure_ascii=False)]
        result = subprocess.run(argv, capture_output=True, text=True, env=self.env, timeout=120)
        record = {"sequence": self.sequence, "command": command, "actor": actor,
                  "argv": argv, "request_sha256": digest({"command": command, "spec": spec,
                                                         "parts": list(map(str, parts)), "actor": actor}),
                  "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        try:
            value = json.loads(result.stdout) if result.stdout.strip() and not raw else result.stdout.strip()
        except json.JSONDecodeError:
            value = None
        record["value"] = value
        self.calls.append(record)
        write_json(self.directory / "calls" / f"{self.sequence:03d}-{command}.json", record)
        if required and result.returncode:
            raise RuntimeError(f"{command} failed: {result.stderr.strip()}")
        return value if required else record

    def start(self, name):
        self.task = self.call("task-new", "--title", name, "--period", "2026-09", raw=True)

    def dataset(self, alias, rows):
        path = self.directory / "sources" / f"{alias}.json"
        write_json(path, rows)
        return self.call("dataset-add", "--path", path, "--name", alias)["id"]

    def state(self):
        return self.call("analysis-state")


def outcome(cli, spec, *, actor="assistant"):
    """Save, validate the actual saved draft, and read public current state."""
    before = cli.state()
    saved = cli.call("save-explanation-draft", spec=spec, actor=actor, required=False)
    result = {"request": spec, "request_sha256": digest(spec), "before": before,
              "save": saved, "validation": None,
              "current_draft": None, "current_completion": None}
    if saved["returncode"] == 0 and isinstance(saved["value"], dict):
        draft = saved["value"]
        validation = cli.call("validate-explanation", spec={"draft_id": draft["id"]}, required=False)
        result["validation"] = validation
    after = cli.state()
    result["after"] = after
    if saved["returncode"] == 0 and isinstance(saved["value"], dict):
        draft = saved["value"]
        result["current_draft"] = next((d for d in after.get("drafts", []) if d["id"] == draft["id"]), None)
        receipt_id = (draft.get("completion") or {}).get("id")
        result["current_completion"] = next((c for c in after.get("completions", [])
                                             if c.get("id") == receipt_id), None)
    result["accepted"] = bool(
        result["validation"] and result["validation"]["returncode"] == 0
        and (result["validation"]["value"] or {}).get("status") == "pass"
        and (result["current_draft"] or {}).get("quality", {}).get("status") == "pass"
        and (result["current_completion"] or {}).get("status") == "complete")
    result["rejection_reasons"] = rejection_reasons(result)
    return result


def rejection_reasons(result):
    reasons = []
    for key in ("save", "validation", "operation"):
        record = result.get(key)
        if isinstance(record, dict) and record.get("returncode"):
            reasons.append({"stage": key, "message": record.get("stderr"), "returncode": record["returncode"]})
    validation = ((result.get("validation") or {}).get("value") or {})
    reasons += [{"stage": "validation", **issue} for issue in validation.get("issues", [])]
    draft = result.get("current_draft") or {}
    reasons += [{"stage": "draft_quality", **issue} for issue in draft.get("quality", {}).get("issues", [])]
    completion = result.get("current_completion") or {}
    if completion and completion.get("status") != "complete":
        reasons.append({"stage": "current_completion", "status": completion.get("status"),
                        "actions": completion.get("actions", [])})
    return reasons


EXPECTED_CODES = {
    "M03": {"unknown_fact", "fact_claim_mismatch"},
    "M05": {"missing_required_fact"},
    "M06": {"requirement_unanswered"},
    "M07": {"fact_metric_semantics_mismatch", "transaction_recognition_mismatch"},
    "M08": {"fact_metric_semantics_mismatch", "transaction_recognition_mismatch"},
    "M09": {"fact_metric_semantics_mismatch", "transaction_recognition_mismatch"},
    "M10": {"fact_metric_semantics_mismatch", "transaction_recognition_mismatch"},
    "M11": {"fact_population_scope_mismatch"},
}
EXPECTED_MESSAGES = {
    "M01": ("scenario_run", "registered template formulas and model boundaries cannot be overridden"),
    "M02": ("scenario_run", "driver binding requires matching rows and exactly one row for single"),
    "M03": ("save", "unknown explanation fact"),
    "M04": ("operation", "only the manager can confirm a reporting profile"),
}


def matching_rejections(mutation, mutant):
    matches = []
    for reason in mutant.get("rejection_reasons", []):
        if not isinstance(reason, dict) or "Traceback" in str(reason.get("message", "")):
            continue
        if reason.get("code") in EXPECTED_CODES.get(mutation, set()):
            matches.append(reason)
        stage, message = EXPECTED_MESSAGES.get(mutation, (None, None))
        if stage and reason.get("stage") == stage and message in str(reason.get("message", "")):
            matches.append(reason)
    return matches


def classify(control, mutant, mutation=None):
    if not (control.get("accepted") or control.get("qualified_review_control")):
        return "control_not_accepted"
    if mutant.get("accepted"):
        return "escaped"
    # A validation error must invalidate the user-visible saved result as well.
    # A stale complete receipt is an escape even if validate now rejects it.
    saved = mutant.get("current_draft")
    receipt = mutant.get("current_completion")
    save_record = mutant.get("save") or {}
    save_value = save_record.get("value") or {}
    saved_successfully = save_record.get("returncode") == 0 and isinstance(save_value, dict) and save_value.get("id")
    if saved_successfully or saved or receipt or mutant.get("historical_draft_id"):
        if (receipt or {}).get("status") == "complete" or (saved or {}).get("quality", {}).get("status") == "pass":
            return "escaped_current_receipt"
        if not saved or not receipt:
            return "unresolved"
    if not mutation or not matching_rejections(mutation, mutant):
        return "unresolved"
    return "detected"


def template_setup(cli, *, variant="E18--base--closed-template", edits=None, confirm=True):
    bindings, source_bindings, boundary_names = {}, {}, []
    sources = {}
    for alias, key in (("template_inputs", "input_name"), ("model_boundary", "boundary_name")):
        source = FIXTURES / variant / f"{alias}.json"
        rows = deepcopy(json.loads(source.read_text())["rows"])
        for row in rows:
            if alias == "template_inputs" and row[key] in (edits or {}):
                row["amount"] = edits[row[key]]
        sources[alias] = {"fixture": str(source.relative_to(ROOT)), "fixture_sha256": file_hash(source),
                          "runtime_rows_sha256": digest(rows), "runtime_edits": edits or {}}
        bindings[alias] = cli.dataset(alias, rows)
        for row in rows:
            name = row[key] if alias == "template_inputs" else "boundary." + row[key]
            if alias == "model_boundary":
                boundary_names.append(name)
            source_bindings[name] = {"alias": alias, "column": "amount", "selector": {key: row[key]},
                                     "aggregation": "single", "period": row["period"],
                                     "scope": {"organization": row["organization"]},
                                     "currency": row["currency"], "unit": row["unit"]}
    profile = {"schema_version": 1, "basis": "management", "basis_version": "management-v1",
               "purpose": "forecast", "fiscal_year_start": "2026-01-01", "early_adoption": False,
               "effective_period": {"start": "2026-09", "end": "2026-09"},
               "functional_currency": "CNY", "presentation_currency": "CNY", "presentation_unit": "元",
               "entity_scope": "Synthetic Fixture Co", "policies": {}}
    context = cli.call("finance-context-save", spec={"bindings": bindings, "reporting_profile": profile})
    inputs = {"template_id": TEMPLATE, "period": "2026-09",
              "scope": {"organization": "Synthetic Fixture Co", "currency": "CNY", "unit": "元"},
              "source_bindings": source_bindings}
    scenario = cli.call("finance-scenario-save", spec={"context_id": context["id"], "kind": "driver_model",
                                                        "label": "deterministic mutation fixture", "inputs": inputs})
    if confirm:
        cli.call("finance-profile-confirm", actor="manager",
                 spec={"context_id": context["id"], "confirmed_fields": BASE_FIELDS})
        cli.call("finance-profile-confirm", actor="manager",
                 spec={"context_id": context["id"], "scenario_id": scenario["id"],
                       "confirmed_model_boundaries": boundary_names})
    requirement = cli.call("analysis-requirements-save", spec={"context_id": context["id"],
        "question": "管理预测三表及现金可用性", "items": [{"id": "cash", "metric": "closing_cash",
        "dimensions": {"template_id": TEMPLATE, "scenario_id": scenario["id"]}}]})
    run = cli.call("finance-scenario-run", spec={"scenario_id": scenario["id"]})
    if run.get("execution_status") != "succeeded":
        raise RuntimeError(f"legal template did not run: {run.get('error')}")
    expected = {"net_income": "50", "cash_flow_operating": "50", "cash_flow_investing": "-40",
                "cash_flow_financing": "-20", "closing_cash": "90", "closing_receivables": "70",
                "closing_ppe": "230", "closing_payables": "60", "closing_debt": "80",
                "closing_equity": "250", "total_assets": "390", "total_liabilities_equity": "390", "available_cash": "90"}
    if variant == "E19--old_ar_collected--closed-template" or edits == {"customer_receipts": "110", "closing_restricted_cash": "30"}:
        expected.update(cash_flow_operating="60", closing_cash="100", closing_receivables="60", available_cash="100")
    if edits == {"customer_receipts": "110", "closing_restricted_cash": "30"}:
        expected["available_cash"] = "70"
    oracle = assert_amounts({r["metric_key"]: r["value"] for r in run["result"]["rows"] if r.get("metric_key")}, expected)
    return {"context": context, "scenario": scenario, "inputs": inputs, "requirement": requirement,
            "run": run, "sources": sources, "boundary_names": boundary_names, "independent_oracle": oracle}


def draft_spec(cli, setup, lead=""):
    run = setup["run"]
    prepared = cli.call("prepare-explanation", spec={"run_ids": [run["id"]]})
    facts = [f for f in prepared["facts"] if f["column"] == "value"]
    if not facts:
        facts = prepared["facts"]
    claims = [{"basis": "calculation", "run_id": f["run_id"], "row": f["row"],
               "column": f["column"], "value": f["value"], "fact_id": f["id"]} for f in facts]
    by_metric = {(run["result"]["rows"][f["row"]].get("metric_key") or f["column"]): f for f in facts}
    lines = ["{{fact:" + f["id"] + "}}" for f in facts]
    spec = {"requirements_id": setup["requirement"]["id"], "run_ids": [run["id"]],
            "body": lead + "\n" + "\n".join(lines), "claims": claims}
    return spec, facts, by_metric


def run_failure(cli, setup, inputs):
    before = cli.state()
    scenario = cli.call("finance-scenario-save", spec={"context_id": setup["context"]["id"],
        "kind": "driver_model", "label": "candidate mutation", "inputs": inputs})
    run = cli.call("finance-scenario-run", spec={"scenario_id": scenario["id"]})
    spec = {"requirements_id": setup["requirement"]["id"], "run_ids": [run["id"]],
            "body": "候选结果要求后端验证。", "claims": []}
    result = outcome(cli, spec)
    result.update(before=before, candidate_scenario=scenario, candidate_run=run)
    if run.get("execution_status") == "failed":
        result["rejection_reasons"].insert(0, {"stage": "scenario_run", "message": run.get("error")})
    return result


def template_case(cli, mutation):
    setup = template_setup(cli, edits={"customer_receipts": "110", "closing_restricted_cash": "30"}
                           if mutation == "M10" else None, confirm=mutation != "M04")
    base, facts, metrics = draft_spec(cli, setup)
    if mutation == "M04":
        before = cli.state()
        forbidden = cli.call("finance-profile-confirm", required=False, spec={
            "context_id": setup["context"]["id"], "confirmed_fields": BASE_FIELDS, "actor": "manager",
            "confirmed_by": "manager", "status": "confirmed"})
        mutant = outcome(cli, base)
        mutant.update(before=before, operation=forbidden)
        mutant["rejection_reasons"] = rejection_reasons(mutant)
        cli.call("finance-profile-confirm", actor="manager", spec={"context_id": setup["context"]["id"],
                                                                    "confirmed_fields": BASE_FIELDS})
        cli.call("finance-profile-confirm", actor="manager", spec={"context_id": setup["context"]["id"],
            "scenario_id": setup["scenario"]["id"], "confirmed_model_boundaries": setup["boundary_names"]})
        # Requirements capture the new approved basis before a fresh run.
        setup["requirement"] = cli.call("analysis-requirements-save", spec={"parent_id": setup["requirement"]["id"], "context_id": setup["context"]["id"],
            "question": "管理预测三表及现金可用性", "items": [{"id": "cash", "metric": "closing_cash",
            "dimensions": {"template_id": TEMPLATE, "scenario_id": setup["scenario"]["id"]}}]})
        setup["run"] = cli.call("finance-scenario-run", spec={"scenario_id": setup["scenario"]["id"]})
        base, _, _ = draft_spec(cli, setup)
        return outcome(cli, base), mutant, setup
    if mutation == "M10":
        base["body"] = "本期可用资金为{{fact:" + metrics["available_cash"]["id"] + "}}。\n" + base["body"]
    control = outcome(cli, base)
    bad = deepcopy(base)
    if mutation in {"M01", "M02"}:
        inputs = deepcopy(setup["inputs"])
        if mutation == "M01":
            inputs["drivers"] = [{"name": "net_income", "formula": "revenue + operating_expense + depreciation"}]
        else:
            inputs["source_bindings"]["revenue"]["selector"] = {"input_name": "missing_reference"}
        return control, run_failure(cli, setup, inputs), setup
    if mutation == "M03":
        fake = "0" * 64
        bad["body"] = "{{fact:" + fake + "}}\n" + base["body"]
        bad["claims"].append({**base["claims"][0], "fact_id": fake})
    elif mutation == "M06":
        # The artifact really lacks the required run/evidence. Merely attaching a
        # fake status to an already-valid draft would not test false completion.
        bad.update(run_ids=[], claims=[], body="全部分析已完成，无待办事项。",
                   completion={"status": "complete"}, completion_status="complete")
    elif mutation == "M10":
        bad["body"] = base["body"].replace("本期可用资金为{{fact:" + metrics["available_cash"]["id"],
                                           "本期可用资金为{{fact:" + metrics["closing_cash"]["id"], 1)
    return control, outcome(cli, bad), setup


def semantic_sql_case(cli, mutation):
    # These are explicitly synthetic source transactions. No oracle answer is
    # inserted into an archived source cell. M07 checks advance classification;
    # it does not claim to implement E05's 120 / 12 performance allocation.
    from openpyxl import Workbook

    metric = "prepayment_received" if mutation == "M07" else "ordinary_operating_expense"
    classification = "unperformed_customer_advance" if mutation == "M07" else "current_period_consumed_service"
    amount = 120 if mutation == "M07" else 100
    book = Workbook()
    sheet = book.active
    sheet.title = "Transactions"
    sheet.append(["metric_key", "classification", "amount", "period", "organization", "unit", "currency",
                  "future_economic_benefits", "performance_status"])
    sheet.append([metric, classification, amount, "2026-09", "Synthetic Fixture Co", "元", "CNY", False,
                  "not_performed" if mutation == "M07" else "fully_consumed_current_period"])
    source = cli.directory / "sources" / "transactions.xlsx"
    source.parent.mkdir(parents=True, exist_ok=True)
    book.save(source)
    dataset = cli.call("dataset-add", "--path", source, "--name", "synthetic original transactions",
                       "--meta", json.dumps({"mode": "table", "sheet": "Transactions"}))
    context = cli.call("finance-context-save", spec={"bindings": {"transactions": dataset["id"]}})
    requirement = cli.call("analysis-requirements-save", spec={"context_id": context["id"],
        "question": "说明已归档交易金额及其来源分类，不擅自变更会计性质",
        "items": [{"id": "amount", "metric": metric, "requires_drilldown": False}]})
    definition = cli.call("analysis-save", spec={"question": "读取原始交易金额及明确分类",
        "bindings": {"transactions": dataset["id"]},
        "sql": "SELECT metric_key, classification, CAST(amount AS DECIMAL(38,2)) AS value, period, organization, unit, currency FROM transactions"})
    run = cli.call("analysis-run", "--analysis", definition["id"])
    if run.get("execution_status") != "succeeded":
        raise RuntimeError(f"legal SQL did not run: {run.get('error')}")
    setup = {"context": context, "requirement": requirement, "run": run,
             "sources": {"transactions": dataset}, "source_file_sha256": file_hash(source),
             "coverage_boundary": "Synthetic transaction classification and fact-use consistency; not full performance allocation, capitalization policy evaluation, or journal-entry recognition."}
    base, _, metrics = draft_spec(cli, setup)
    base["evidence_recipes"] = [{"id": "source-transaction", "kind": "direct", "dataset_id": dataset["id"],
        "source_hash": dataset["source_hash"], "sheet": "Transactions", "range": "C2", "unit": "元",
        "claim": {"run_id": run["id"], "row": 0, "column": "value"}}]
    token = "{{fact:" + metrics[metric]["id"] + "}}"
    good = deepcopy(base)
    bad = deepcopy(base)
    if mutation == "M07":
        good["body"] = f"预收款为{token}，这是尚未履约的收款及合同负债，不全额等同本期新增收入。\n" + base["body"]
        bad["body"] = f"预收款为{token}，全额确认为本期新增收入{token}。\n" + base["body"]
    else:
        good["body"] = f"已消耗且无未来经济利益的普通服务计入本期费用{token}。\n" + base["body"]
        bad["body"] = f"已消耗且无未来经济利益的普通服务计入资本化资产{token}。\n" + base["body"]
    return outcome(cli, good), outcome(cli, bad), setup


def vmp_case(cli):
    rows = [{"product": p, "scenario": scenario, "quantity": q, "price": price,
             "quantity_unit": "件", "ledger": "L1", "organization": "O1", "period": "2026-09",
             "currency": "CNY", "unit": "元"}
            for p, scenario, q, price in [("A", "budget", "50", "10"), ("B", "budget", "50", "20"),
                                          ("A", "actual", "72", "12"), ("B", "actual", "48", "18")]]
    source = cli.dataset("basket", rows)
    context = cli.call("finance-context-save", spec={"bindings": {"basket": source}, "scopes": {"basket": {
        "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}}})
    requirement = cli.call("analysis-requirements-save", spec={"context_id": context["id"], "question": "量结构价差异及闭合检查",
        "items": [{"id": "vmp", "metric": "price_quantity", "dimensions": {"method": "volume_mix_price"}}]})
    run = cli.call("explain-variance", spec={"context_id": context["id"], "kind": "price_quantity", "method": "volume_mix_price",
                                            "actual_scenario": "actual", "baseline_scenario": "budget"})
    oracle = assert_amounts(run["result"]["rows"][0], {"actual": "1728", "baseline": "1500", "total_variance": "228",
        "volume_contribution": "300", "mix_contribution": "-120", "price_contribution": "48", "residual": "0"})
    prepared = cli.call("prepare-explanation", spec={"run_ids": [run["id"]]})
    facts = [f for f in prepared["facts"] if f["column"] in {"total_variance", "volume_contribution", "mix_contribution", "price_contribution", "residual"}]
    claims = [{"basis": "calculation", "run_id": f["run_id"], "row": f["row"], "column": f["column"], "value": f["value"], "fact_id": f["id"]} for f in facts]
    good = {"requirements_id": requirement["id"], "run_ids": [run["id"]], "claims": claims,
            "body": "\n".join(f["column"] + ": {{fact:" + f["id"] + "}}" for f in facts)}
    bad = deepcopy(good)
    bad["claims"] = [c for c in claims if c["column"] != "residual"]
    bad["body"] = "\n".join(line for line in good["body"].splitlines() if not line.startswith("residual:"))
    return outcome(cli, good), outcome(cli, bad), {"context": context, "requirement": requirement, "run": run,
        "sources": {"runtime_rows_sha256": digest(rows)}, "independent_oracle": oracle, "omitted_check": "zero residual closure fact"}


def aging_case(cli):
    rows = [{"id": name, "customer": name, "amount": value, "invoice_status": status,
             "issue_date": "2026-08-01", "due_date": "2026-08-01", "ledger": "L1",
             "organization": "O1", "currency": "CNY", "unit": "元"}
            for name, value, status in (("normal", "95", "正常"), ("disputed", "20", "争议"))]
    source = cli.dataset("invoices", rows)
    scope = {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "元"}
    context = cli.call("finance-context-save", spec={"bindings": {"invoices": source}, "scopes": {"invoices": scope}})
    requirement = cli.call("analysis-requirements-save", spec={"context_id": context["id"],
        "question": "报告完整应收毛额，不得遗漏未结争议应收",
        "items": [{"id": "ar", "metric": "open_amount", "requires_drilldown": False}]})
    runs, full_control, bad = [], None, None
    for population, expected in ((None, "115"), ("active", "95"), ("disputed", "20")):
        inputs = {"as_of": "2026-09-05", "scope": scope}
        if population:
            inputs["status_filter"] = {"field": "invoice_status", "include": [population],
                                       "mapping": {"active": ["正常"], "disputed": ["争议"]}}
        scenario = cli.call("finance-scenario-save", spec={"context_id": context["id"], "kind": "receivables_aging",
                                                            "label": population or "full", "inputs": inputs})
        run = cli.call("finance-scenario-run", spec={"scenario_id": scenario["id"]})
        if run.get("execution_status") != "succeeded":
            raise RuntimeError(f"aging did not run: {run.get('error')}")
        runs.append(run)
        base, facts, _ = draft_spec(cli, {"run": run, "requirement": requirement})
        total = next(f for f in facts if f["column"] == "open_amount" and float(f["value"]) > 0)
        if str(total["value"]) != expected:
            raise AssertionError(f"independent aging oracle mismatch: {population}: {total['value']} != {expected}")
        base["body"] = "完整应收毛额为{{fact:" + total["id"] + "}}。\n" + base["body"]
        if population is None:
            full_control = outcome(cli, base)
        elif population == "active":
            bad = base
    prepared = cli.call("prepare-explanation", spec={"run_ids": [r["id"] for r in runs]})
    facts = prepared["facts"]
    totals = {f["run_id"]: f for f in facts if f["column"] == "open_amount" and float(f["value"]) > 0}
    tokens = ["{{fact:" + totals[r["id"]]["id"] + "}}" for r in runs]
    reconciliation = {"requirements_id": requirement["id"], "run_ids": [r["id"] for r in runs],
        "claims": [{"basis": "calculation", "run_id": f["run_id"], "row": f["row"], "column": f["column"],
                    "value": f["value"], "fact_id": f["id"]} for f in facts],
        "body": f"完整应收毛额为{tokens[0]}，其中正常应收子集{tokens[1]}，排除的争议应收{tokens[2]}仍须保留在总体。"
                f"调节关系：{tokens[1]} + {tokens[2]} = {tokens[0]}。\n"
                + "\n".join("{{fact:" + f["id"] + "}}" for f in facts)}
    control = outcome(cli, reconciliation)
    control["additional_unfiltered_control"] = full_control
    control["accepted"] = control["accepted"] and full_control["accepted"]
    return control, outcome(cli, bad), {"context": context, "requirement": requirement, "runs": runs,
                       "sources": {"runtime_rows_sha256": digest(rows)},
                       "independent_expected": {"full": "115", "active": "95", "disputed": "20"},
                       "fixture_basis": "E06--base frozen closing gross 115 includes disputed 20; no source rows deleted"}


def old_receivable_case(cli):
    setup = template_setup(cli, variant="E19--old_ar_collected--closed-template")
    transactions = cli.dataset("transactions", [{"additional_old_ar_collection": "10",
        "transaction": "收回期初已确认应收", "period": "2026-09", "organization": "Synthetic Fixture Co",
        "currency": "CNY", "unit": "元"}])
    definition = cli.call("analysis-save", spec={"question": "读取旧应收回款交易", "bindings": {"transactions": transactions},
        "sql": "SELECT CAST(additional_old_ar_collection AS DECIMAL(38,2)) AS old_ar_collection FROM transactions"})
    transaction_run = cli.call("analysis-run", "--analysis", definition["id"])
    run_ids = [setup["run"]["id"], transaction_run["id"]]
    prepared = cli.call("prepare-explanation", spec={"run_ids": run_ids})
    facts = prepared["facts"]
    old = next(f for f in facts if f["column"] == "old_ar_collection")
    token = "{{fact:" + old["id"] + "}}"
    claims = [{"basis": "calculation", "run_id": f["run_id"], "row": f["row"], "column": f["column"],
               "value": f["value"], "fact_id": f["id"]} for f in facts]
    base = {"requirements_id": setup["requirement"]["id"], "run_ids": run_ids, "claims": claims,
            "body": "\n".join("{{fact:" + f["id"] + "}}" for f in facts)}
    good = {**base, "body": f"本期收回期初已确认的旧应收款{token}，不再次确认收入。\n" + base["body"]}
    bad = {**base, "body": f"本期收回期初已确认的旧应收款{token}，全额确认为本期新增收入{token}。\n" + base["body"]}
    setup.update(transaction_run=transaction_run,
                 coverage_boundary="Source-backed old AR collection mislabelled as revenue in the draft; does not simulate a fully posted erroneous balanced journal entry.")
    return outcome(cli, good), outcome(cli, bad), setup


TRANSACTION_POLICIES = {
    "uniform_service_advance": "uniform_monthly_service_v1",
    "ordinary_service_consumed": "expense_consumed_service_v1",
    "capitalizable_acquisition": "capitalize_qualifying_acquisition_v1",
    "old_ar_collection": "settle_existing_receivable_v1",
    "new_earned_cash_sale": "recognize_fulfilled_cash_sale_v1",
    "restricted_cash_release": "release_effective_restriction_v1",
}


def transaction_pair(cli, kind, facts, correct, incorrect, *, release=None, statement_base=None):
    """Submit actual candidate entries to a source-bound native policy check."""
    scope = {"organization": "Synthetic Fixture Co", "period": "2026-09", "unit": "元", "currency": "CNY"}
    policy_id = TRANSACTION_POLICIES[kind]
    transaction = {**scope, "transaction_id": "T1", "transaction_type": kind,
                   "recognition_date": "2026-09-30", "policy_id": policy_id, **facts}
    policy = {**scope, "policy_id": policy_id, "policy_transaction_type": kind,
              "policy_reference": "Synthetic documented policy for this closed engineering case",
              "policy_effective_from": "2026-01-01", "policy_effective_to": "2026-12-31"}
    records = {"transactions": transaction, "policies": policy}
    selectors = {"transactions": {"transaction_id": "T1"}, "policies": {"policy_id": policy_id}}
    fields = {"transactions": {"transaction_id", "transaction_type", "recognition_date", *facts},
              "policies": {"policy_id", "policy_transaction_type", "policy_reference", "policy_effective_from", "policy_effective_to"}}
    if release is not None:
        records["releases"] = {**scope, **release}
        selectors["releases"] = {"release_id": release["release_id"]}
        fields["releases"] = set(release)
    bindings, source_bindings = {}, {}
    for alias, record in records.items():
        bindings[alias] = cli.dataset(alias, [record])
        for name in sorted(fields[alias]):
            source_bindings[name] = {"alias": alias, "column": name, "selector": selectors[alias], "aggregation": "single",
                "scope": {"organization": scope["organization"]}, "period": scope["period"], "unit": scope["unit"], "currency": scope["currency"]}
    context = cli.call("finance-context-save", spec={"bindings": bindings})
    requirement = cli.call("analysis-requirements-save", spec={"context_id": context["id"],
        "question": "核查来源约束下的交易候选分录，保留专业审核资格边界",
        "items": [{"id": "transaction", "metric": "transaction_review", "requires_drilldown": False}]})
    outcomes, runs, oracles = [], [], []
    for entries in (correct, incorrect):
        scenario = cli.call("finance-scenario-save", spec={"context_id": context["id"], "kind": "transaction_review",
            "label": "source-bound transaction review", "inputs": {"scope": scope, "source_bindings": source_bindings,
                                                                    "proposed_entries": entries}})
        run = cli.call("finance-scenario-run", spec={"scenario_id": scenario["id"]})
        if run.get("execution_status") != "succeeded":
            raise RuntimeError(f"transaction review did not execute: {run.get('error')}")
        result = run["result"]
        if result.get("input_gaps"):
            raise RuntimeError(f"transaction source contract rejected: {result['input_gaps']}")
        oracle = {"expected": assert_amounts(result.get("expected_entries", {}), correct),
                  "actual": assert_amounts({row["item"]: row["actual"] for row in result["rows"]}, entries)}
        base, _, _ = draft_spec(cli, {"run": run, "requirement": requirement})
        artifact = None
        if kind == "uniform_service_advance":
            artifact = {"debit_cash": facts["cash_received"], "credit_revenue": entries["recognized_revenue"],
                        "credit_contract_liability": entries["contract_liability"]}
            assert Decimal(artifact["debit_cash"]) == Decimal(artifact["credit_revenue"]) + Decimal(artifact["credit_contract_liability"])
        elif statement_base is not None:
            artifact = statement_artifact(statement_base, entries)
        observed = outcome(cli, base)
        observed["checked_run"] = run
        observed["candidate_accounting_artifact"] = artifact
        outcomes.append(observed)
        runs.append(run)
        oracles.append(oracle)
    control, mutant = outcomes
    result = runs[0]["result"]
    reasons = control["rejection_reasons"]
    codes = {reason.get("code") for reason in reasons}
    control["qualified_review_control"] = bool(
        control.get("save", {}).get("returncode") == 0
        and control.get("validation", {}).get("returncode") == 0
        and result.get("status") == "pass" and result.get("source_binding_status", {}).get("all_sources_verified")
        and result.get("source_rows") and all(row["status"] == "pass" for row in result["rows"])
        and "transaction_review_requires_professional_review" in codes
        and codes <= {None, "transaction_review_requires_professional_review"}
        and control.get("current_draft") and control.get("current_completion")
        and control["current_completion"].get("status") != "complete")
    control["acceptance_basis"] = "Source-bound check is correct and explicitly awaits professional review; this is not amount-evidence completion."
    return control, mutant, {"context": context, "requirement": requirement, "runs": runs,
        "source_records": records, "source_records_sha256": digest(records), "independent_oracles": oracles}


def statement_artifact(baseline, entries):
    """Build the submitted statement artifact, independently of the checker.

    Baseline is the native E18 result. Entries are the proposed transaction,
    including the deliberately wrong one, not accepted source observations.
    """
    values = {key: Decimal(value) for key, value in baseline.items()}
    delta = {key: Decimal(value) for key, value in entries.items()}
    values["closing_cash"] += delta["cash_delta"]
    values["cash_flow_operating"] += delta["cash_delta"]
    values["closing_receivables"] += delta["receivables_delta"]
    values["net_income"] += delta["profit_delta"]
    values["closing_equity"] += delta["profit_delta"]
    values["total_assets"] = values["closing_cash"] + values["closing_receivables"] + values["closing_ppe"]
    values["total_liabilities_equity"] = values["closing_payables"] + values["closing_debt"] + values["closing_equity"]
    assert values["total_assets"] == values["total_liabilities_equity"]
    return {"income_statement": {"net_income": str(values["net_income"])},
            "cash_flow_statement": {key: str(values[key]) for key in ("cash_flow_operating", "cash_flow_investing", "cash_flow_financing")},
            "balance_sheet": {key: str(values[key]) for key in ("closing_cash", "closing_receivables", "closing_ppe", "closing_payables", "closing_debt", "closing_equity", "total_assets", "total_liabilities_equity")}}


def transaction_case(cli, mutation):
    if mutation == "M07":
        return transaction_pair(cli, "uniform_service_advance", {
            "cash_received": "120", "service_months": "12", "earned_months": "1",
            "performance_pattern": "uniform_monthly", "fulfilment_basis": "cumulative_since_contract_start"},
            {"recognized_revenue": "10", "contract_liability": "110"},
            {"recognized_revenue": "120", "contract_liability": "0"})
    if mutation == "M08":
        control, mutant, setup = transaction_pair(cli, "ordinary_service_consumed", {
            "amount": "100", "service_consumed_in_period": True, "future_economic_benefit": False},
            {"expense": "100", "capitalized_asset": "0"}, {"expense": "0", "capitalized_asset": "100"})
        additional = CLI(cli.foundry, cli.directory / "capitalization-control")
        additional.start("legal source-policy-backed capitalization")
        cap_control, _, cap_setup = transaction_pair(additional, "capitalizable_acquisition", {
            "amount": "100", "future_economic_benefit": True, "asset_controlled": True,
            "reliable_measurement": True, "useful_life_months": "36"},
            {"expense": "0", "capitalized_asset": "100"}, {"expense": "100", "capitalized_asset": "0"})
        setup["capitalization_control"] = {"observation": cap_control, "setup": cap_setup}
        control["qualified_review_control"] &= cap_control["qualified_review_control"]
        return control, mutant, setup
    if mutation == "M09":
        baseline_cli = CLI(cli.foundry, cli.directory / "native-baseline")
        baseline_cli.start("native source-bound three-statement baseline")
        baseline_setup = template_setup(baseline_cli)
        baseline_spec, _, _ = draft_spec(baseline_cli, baseline_setup)
        baseline_control = outcome(baseline_cli, baseline_spec)
        assert baseline_control["accepted"], "native baseline did not complete"
        baseline = {row["metric_key"]: row["value"] for row in baseline_setup["run"]["result"]["rows"] if row.get("metric_key")}
        control, mutant, setup = transaction_pair(cli, "old_ar_collection", {
            "amount": "10", "opening_receivable": "70", "receivable_origin_period": "2026-08"},
            {"cash_delta": "10", "receivables_delta": "-10", "revenue_delta": "0", "profit_delta": "0"},
            {"cash_delta": "10", "receivables_delta": "0", "revenue_delta": "10", "profit_delta": "10"}, statement_base=baseline)
        setup["native_baseline"] = {"setup": baseline_setup, "control": baseline_control}
        additional = CLI(cli.foundry, cli.directory / "new-sale-control")
        additional.start("legal new fulfilled cash sale")
        sale_control, _, sale_setup = transaction_pair(additional, "new_earned_cash_sale", {
            "amount": "10", "performance_obligation_satisfied": True, "associated_expense": "0", "tax_expense": "0"},
            {"cash_delta": "10", "receivables_delta": "0", "revenue_delta": "10", "profit_delta": "10"},
            {"cash_delta": "10", "receivables_delta": "-10", "revenue_delta": "0", "profit_delta": "0"}, statement_base=baseline)
        setup["new_sale_control"] = {"observation": sale_control, "setup": sale_setup}
        control["qualified_review_control"] &= sale_control["qualified_review_control"]
        return control, mutant, setup
    raise ValueError(mutation)


def restricted_cash_case(cli):
    control, mutant, setup = template_case(cli, "M10")
    release_cases = []
    for name, effective_date, status in (("future", "2026-10-01", "effective"),
                                         ("ineffective", "2026-09-01", "ineffective"),
                                         ("effective", "2026-09-01", "effective")):
        additional = CLI(cli.foundry, cli.directory / ("release-" + name))
        additional.start("source-dated restricted cash release")
        released = name == "effective"
        correct = {"available_cash": "100" if released else "70", "remaining_restricted_cash": "0" if released else "30", "cash_shortfall": "0" if released else "10"}
        wrong = {"available_cash": "70" if released else "100", "remaining_restricted_cash": "30" if released else "0", "cash_shortfall": "10" if released else "0"}
        legal, bad, details = transaction_pair(additional, "restricted_cash_release", {
            "cash_balance": "100", "restricted_cash": "30", "restriction_id": "R1", "as_of_date": "2026-09-30", "obligations_due": "80"}, correct, wrong,
            release={"release_id": "REL1", "release_reference": "Synthetic independent bank release document",
                     "release_restriction_id": "R1", "release_amount": "30", "release_effective_date": effective_date, "release_status": status})
        assert legal["qualified_review_control"], "correct release check did not retain its review qualification"
        assert classify(legal, bad, "M10") == "detected", "incorrect release treatment escaped"
        release_cases.append({"name": name, "control": legal, "mutant": bad, "setup": details})
    setup["release_cases"] = release_cases
    return control, mutant, setup


def execute_case(foundry, directory, mutation):
    cli = CLI(foundry, directory)
    cli.start(f"deterministic {mutation} {MUTATIONS[mutation]}")
    if mutation in {"M07", "M08", "M09"}:
        control, mutant, setup = transaction_case(cli, mutation)
    elif mutation == "M05":
        control, mutant, setup = vmp_case(cli)
    elif mutation == "M11":
        control, mutant, setup = aging_case(cli)
    elif mutation == "M10":
        control, mutant, setup = restricted_cash_case(cli)
    else:
        control, mutant, setup = template_case(cli, mutation)
    result = {"id": mutation, "name": MUTATIONS[mutation], "task_id": cli.task, "setup": setup,
              "frozen_case_coverage": FROZEN_COVERAGE[mutation],
              "control": control, "mutant": mutant, "status": classify(control, mutant, mutation),
              "matched_rejections": matching_rejections(mutation, mutant),
              "calls": len(cli.calls), "deterministic_pipeline": True, "provider_calls": 0}
    write_json(directory / "result.json", result)
    return result


def observe_saved(cli, previous):
    """Read an existing immutable draft through the new candidate's public view."""
    draft_id = (previous.get("current_draft") or {}).get("id")
    if not draft_id:
        raise ValueError("historical recheck requires an actually saved draft")
    before = cli.state()
    validation = cli.call("validate-explanation", spec={"draft_id": draft_id}, required=False)
    after = cli.state()
    current = next((d for d in after.get("drafts", []) if d["id"] == draft_id), None)
    receipt_id = (previous.get("current_completion") or {}).get("id")
    receipt = next((c for c in after.get("completions", []) if c["id"] == receipt_id), None)
    result = {"historical_draft_id": draft_id, "before": before, "validation": validation,
              "after": after, "current_draft": current, "current_completion": receipt}
    result["accepted"] = bool(validation["returncode"] == 0 and isinstance(validation["value"], dict)
                              and validation["value"].get("status") == "pass"
                              and (current or {}).get("quality", {}).get("status") == "pass"
                              and (receipt or {}).get("status") == "complete")
    result["rejection_reasons"] = rejection_reasons(result)
    return result


def recheck_case(foundry, directory, previous_path, mutation):
    previous_path = Path(previous_path).resolve()
    previous = json.loads(previous_path.read_text())
    cli = CLI(foundry, directory)
    cli.var = previous_path.parent / "var"
    cli.task = previous["task_id"]
    historical_before = tree_hashes(cli.var)
    control = observe_saved(cli, previous["control"])
    mutant = observe_saved(cli, previous["mutant"])
    historical_after = tree_hashes(cli.var)
    write_json(directory / "historical-files-before.json", historical_before)
    write_json(directory / "historical-files-after.json", historical_after)
    modified = historical_before != historical_after
    result = {"id": mutation, "name": MUTATIONS[mutation], "task_id": cli.task,
              "historical_evidence": str(previous_path), "historical_evidence_sha256": file_hash(previous_path),
              "historical_var": str(cli.var), "historical_records_modified": modified,
              "historical_files_before_sha256": digest(historical_before),
              "historical_files_after_sha256": digest(historical_after),
              "control": control, "mutant": mutant,
              "status": "historical_records_modified" if modified else classify(control, mutant, mutation),
              "matched_rejections": matching_rejections(mutation, mutant), "calls": len(cli.calls),
              "frozen_case_coverage": previous.get("frozen_case_coverage", {"status": "partial", "scope": "Historical diagnostic predates explicit full-case coverage; no new controls were created during read-only recheck."}),
              "deterministic_pipeline": True, "provider_calls": 0}
    write_json(directory / "result.json", result)
    return result


def run_suite(foundry, output, selected=None, candidate_manifest=None, recheck=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = candidate_identity(foundry, candidate_manifest)
    driver_path = Path(__file__).resolve()
    driver_before = {"path": str(driver_path), "sha256": file_hash(driver_path)}
    if candidate_manifest:
        expected = json.loads(Path(candidate_manifest).read_text())["files"].get("tools/verify_finance_mutation_pipeline.py")
        if expected and expected != driver_before["sha256"]:
            raise ValueError("actual mutation driver differs from the frozen candidate manifest")
    report = {"schema_version": 1, "evaluation_kind": "deterministic_real_cli_mutation_pipeline",
              "model_evaluation": False, "professional_review": False, "provider_calls": 0, "historical_recheck": recheck,
              "started_at": datetime.now(timezone.utc).isoformat(), "candidate_before": before,
              "driver_before": driver_before, "cases": []}
    report["selected_cases"] = list(selected or MUTATIONS)
    report["full_suite_selected"] = set(report["selected_cases"]) == set(MUTATIONS)
    write_json(output / "candidate-before.json", before)
    for mutation in selected or MUTATIONS:
        try:
            result = (recheck_case(foundry, output / mutation, Path(recheck) / mutation / "result.json", mutation)
                      if recheck else execute_case(foundry, output / mutation, mutation))
            summary = {"id": mutation, "status": result["status"], "control_accepted": result["control"]["accepted"],
                       "control_review_qualified": result["control"].get("qualified_review_control", False),
                       "mutant_accepted": result["mutant"]["accepted"], "calls": result["calls"],
                       "frozen_case_coverage": result["frozen_case_coverage"],
                       "evidence": str((output / mutation / "result.json").relative_to(output))}
        except Exception as error:
            summary = {"id": mutation, "status": "harness_error", "error": str(error)}
            write_json(output / mutation / "error.json", summary)
        report["cases"].append(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        write_json(output / "report.json", report)
    after = candidate_identity(foundry, candidate_manifest)
    report["candidate_after"] = after
    report["candidate_stable"] = before == after
    report["driver_after"] = {"path": str(driver_path), "sha256": file_hash(driver_path)}
    report["driver_stable"] = report["driver_after"] == driver_before
    report["diagnostics_passed"] = all(c["status"] == "detected" for c in report["cases"])
    report["legitimate_controls_completed"] = all(c.get("control_accepted") is True for c in report["cases"])
    report["frozen_coverage_complete"] = report["full_suite_selected"] and all(c.get("frozen_case_coverage", {}).get("status") == "covered" for c in report["cases"])
    report["status"] = "passed" if (report["candidate_stable"] and report["driver_stable"] and report["diagnostics_passed"]
                                    and report["frozen_coverage_complete"] and report["legitimate_controls_completed"]) else "failed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["counts"] = {status: sum(c["status"] == status for c in report["cases"])
                        for status in ("detected", "escaped", "escaped_current_receipt", "control_not_accepted", "unresolved", "historical_records_modified", "harness_error")}
    write_json(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry", required=True, help="Actual candidate CLI executable; no provider is invoked")
    parser.add_argument("--output", required=True, help="New directory; existing evidence is never overwritten")
    parser.add_argument("--cases", nargs="+", choices=list(MUTATIONS))
    parser.add_argument("--candidate-manifest", help="Frozen candidate-source.json next to the actual bound source launcher")
    parser.add_argument("--recheck", help="Prior run directory: only validate/read its existing drafts; write observations to a new --output")
    args = parser.parse_args(argv)
    report = run_suite(args.foundry, args.output, args.cases, args.candidate_manifest, args.recheck)
    print(json.dumps({"status": report["status"], "counts": report["counts"], "output": str(Path(args.output).resolve())}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
