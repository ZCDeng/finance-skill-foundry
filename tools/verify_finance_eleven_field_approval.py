#!/usr/bin/env python3
"""Ledger B: an eleven-field manager approval, then the real M02/M06 checks.

The original mutation tool still confirms only the seven BASE_FIELDS and is not
modified. This runner records that original result as ledger A and does not
treat it as a pass. No provider is called. Human review stays pending.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FULL_FIELDS = [
    "basis", "basis_version", "early_adoption", "effective_period.end", "effective_period.start",
    "entity_scope", "fiscal_year_start", "functional_currency", "presentation_currency",
    "presentation_unit", "purpose",
]


def pipeline():
    path = Path(__file__).resolve().parent / "verify_finance_mutation_pipeline.py"
    spec = importlib.util.spec_from_file_location("verify_finance_mutation_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def eleven_setup(pipe, cli):
    """Same public template fixture as the seven-field tool, with a new eleven-field event."""
    bindings, source_bindings, boundary_names = {}, {}, []
    for alias, key in (("template_inputs", "input_name"), ("model_boundary", "boundary_name")):
        source = pipe.FIXTURES / "E18--base--closed-template" / f"{alias}.json"
        rows = pipe.deepcopy(json.loads(source.read_text())["rows"])
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
    inputs = {"template_id": pipe.TEMPLATE, "period": "2026-09",
              "scope": {"organization": "Synthetic Fixture Co", "currency": "CNY", "unit": "元"},
              "source_bindings": source_bindings}
    scenario = cli.call("finance-scenario-save", spec={"context_id": context["id"], "kind": "driver_model",
                                                        "label": "eleven field approval fixture", "inputs": inputs})
    assistant = cli.call("finance-profile-confirm", actor="assistant", required=False, spec={
        "context_id": context["id"], "confirmed_fields": FULL_FIELDS, "confirmed_by": "manager", "status": "confirmed"})
    seven = cli.call("finance-profile-confirm", actor="manager", spec={
        "context_id": context["id"], "confirmed_fields": pipe.BASE_FIELDS})
    seven_status = cli.call("finance-profile-status", spec={"context_id": context["id"], "scenario_id": scenario["id"]})
    seven_call = next(call for call in reversed(cli.calls) if call["command"] == "finance-profile-confirm" and call["actor"] == "manager")
    # The confirmation file is inside the task var. Re-read it after the eleven-field event.
    confirmation_dir = cli.var / "tasks" / cli.task / "analysis" / "finance" / "profile_confirmations"
    seven_path = next(confirmation_dir.glob("*.json"))
    seven_bytes = seven_path.read_bytes()
    eleven = cli.call("finance-profile-confirm", actor="manager", spec={
        "context_id": context["id"], "confirmed_fields": FULL_FIELDS})
    eleven_status = cli.call("finance-profile-status", spec={"context_id": context["id"], "scenario_id": scenario["id"]})
    unchanged = seven_path.read_bytes() == seven_bytes
    cli.call("finance-profile-confirm", actor="manager", spec={
        "context_id": context["id"], "scenario_id": scenario["id"], "confirmed_model_boundaries": boundary_names})
    requirement = cli.call("analysis-requirements-save", spec={"context_id": context["id"],
        "question": "管理预测三表及现金可用性", "items": [{"id": "cash", "metric": "closing_cash",
        "dimensions": {"template_id": pipe.TEMPLATE, "scenario_id": scenario["id"]}}]})
    run = cli.call("finance-scenario-run", spec={"scenario_id": scenario["id"]})
    if run.get("execution_status") != "succeeded":
        raise RuntimeError(f"eleven-field template did not run: {run.get('error')}")
    pipe.assert_amounts({row["metric_key"]: row["value"] for row in run["result"]["rows"] if row.get("metric_key")}, {
        "net_income": "50", "cash_flow_operating": "50", "cash_flow_investing": "-40",
        "cash_flow_financing": "-20", "closing_cash": "90", "closing_receivables": "70",
        "closing_ppe": "230", "closing_payables": "60", "closing_debt": "80",
        "closing_equity": "250", "total_assets": "390", "total_liabilities_equity": "390", "available_cash": "90"})
    return {"context": context, "scenario": scenario, "inputs": inputs, "requirement": requirement,
            "run": run, "boundary_names": boundary_names, "seven_id": seven["id"], "eleven_id": eleven["id"],
            "assistant_rejected": assistant["returncode"] != 0,
            "seven_gap": seven_status.get("profile_gap"), "eleven_gap": eleven_status.get("profile_gap"),
            "seven_status": seven_status.get("professional_status"),
            "eleven_before_boundary": eleven_status.get("professional_status"),
            "seven_bytes_unchanged": unchanged, "seven_call_kept": seven_call["returncode"] == 0}


def eleven_case(pipe, foundry, directory, mutation):
    cli = pipe.CLI(foundry, directory)
    cli.start(f"eleven field {mutation}")
    setup = eleven_setup(pipe, cli)
    base, _, _ = pipe.draft_spec(cli, setup)
    control = pipe.outcome(cli, base)
    if mutation == "M02":
        inputs = pipe.deepcopy(setup["inputs"])
        inputs["source_bindings"]["revenue"]["selector"] = {"input_name": "missing_reference"}
        mutant = pipe.run_failure(cli, setup, inputs)
    elif mutation == "M06":
        bad = pipe.deepcopy(base)
        bad.update(run_ids=[], claims=[], body="全部分析已完成，无待办事项。",
                   completion={"status": "complete"}, completion_status="complete")
        mutant = pipe.outcome(cli, bad)
    else:
        raise ValueError(mutation)
    status = pipe.classify(control, mutant, mutation)
    return {"mutation": mutation, "ledger": "B", "status": status,
            "control_accepted": bool(control.get("accepted")),
            "control_completion": (control.get("current_completion") or {}).get("status"),
            "mutant_accepted": bool(mutant.get("accepted")),
            "matched_rejections": pipe.matching_rejections(mutation, mutant),
            "assistant_rejected": setup["assistant_rejected"],
            "seven_bytes_unchanged": setup["seven_bytes_unchanged"],
            "seven_id": setup["seven_id"], "eleven_id": setup["eleven_id"],
            "seven_status": setup["seven_status"], "seven_gap": setup["seven_gap"],
            "eleven_before_boundary": setup["eleven_before_boundary"], "eleven_gap": setup["eleven_gap"],
            "provider_calls": 0}


def compact_rejection(reasons):
    kept = []
    for reason in reasons or []:
        if not isinstance(reason, dict):
            continue
        kept.append({key: reason.get(key) for key in ("stage", "code", "status", "message") if key in reason})
    return kept[:8]


def original_seven_field(pipe, foundry, directory, mutation):
    result = pipe.execute_case(foundry, directory, mutation)
    return {"mutation": mutation, "ledger": "A", "status": result["status"],
            "control_accepted": bool(result["control"].get("accepted")),
            "control_completion": (result["control"].get("current_completion") or {}).get("status"),
            "provider_calls": result["provider_calls"],
            "rejection_sample": compact_rejection(result["control"].get("rejection_reasons"))}


def run_report(foundry, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    pipe = pipeline()
    foundry = str(Path(foundry).resolve())
    report = {"ledger_b_eleven_field": {}, "ledger_a_original_seven_field": {},
              "original_model_credit": 0, "human_review": "human_review_pending", "provider_calls": 0,
              "scorer_changed": False, "timeout_seconds": 420}
    for mutation in ("M02", "M06"):
        report["ledger_a_original_seven_field"][mutation] = original_seven_field(
            pipe, foundry, output / "ledger-a" / mutation, mutation)
        report["ledger_b_eleven_field"][mutation] = eleven_case(
            pipe, foundry, output / "ledger-b" / mutation, mutation)
    report["status"] = "passed" if (
        all(item["status"] == "control_not_accepted" for item in report["ledger_a_original_seven_field"].values())
        and all(item["status"] == "detected" and item["control_accepted"] and item["assistant_rejected"]
                and item["seven_bytes_unchanged"] and item["eleven_id"] != item["seven_id"]
                and set(item["seven_gap"]["missing_fields"]) == {"basis", "basis_version", "fiscal_year_start", "early_adoption"}
                and item["eleven_gap"]["missing_fields"] == []
                for item in report["ledger_b_eleven_field"].values())
    ) else "failed"
    pipe.write_json(output / "report.json", report)
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = run_report(args.foundry, args.output)
    print(json.dumps({"status": report["status"],
                      "ledger_a": {key: value["status"] for key, value in report["ledger_a_original_seven_field"].items()},
                      "ledger_b": {key: value["status"] for key, value in report["ledger_b_eleven_field"].items()}},
                     ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
