"""Real CLI capability probes, kept separate from model evaluation attempts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def script(case_id):
    """Controller verification program. Never written into a runtime model seed."""
    family, variant = case_id.split("--", 1)
    header = '''import os,json
from pathlib import Path
from decimal import Decimal
def rows(alias):
    return json.loads((Path(os.environ["FOUNDRY_INPUTS"])/(alias+".json")).read_text())["rows"]
def amounts(alias):
    return {r["source_field"]:Decimal(r["amount"]) for r in rows(alias)}
out=[]
def emit(metric,value,unit="元",**extra):
    out.append({"metric_key":metric,"value":str(value) if value is not None else None,"unit":unit,"currency":"CNY",**extra})
'''
    code = None
    if family == "E08":
        code = '''v=amounts("accrual_events")
emit("december_expense",v["december_service"],period_label="December")
emit("january_cash_payment",v["january_payment"],period_label="January")
'''
        if variant == "reverse_then_book":
            code += '''emit("january_reversal_expense",-v["december_service"],period_label="January")
emit("january_invoice_expense",v["january_bill"],period_label="January")
emit("january_net_expense",v["january_bill"]-v["december_service"],period_label="January")
'''
        else:
            code += '''emit("january_accrual_settlement",v["january_bill"],period_label="January")
emit("january_net_expense",v["january_bill"]-v["december_service"],period_label="January")
'''
    elif family == "E10":
        code = '''v=amounts("bank_reconciliation_inputs")
emit("adjusted_bank",v["bank"]+v["deposit_in_transit"]-v["outstanding_checks"])
emit("adjusted_book",v["gl"]-v["unrecorded_bank_fee"])
emit("book_fee_adjustment",v["unrecorded_bank_fee"])
'''
    elif family == "E12":
        code = '''v=amounts("close_comparison")
emit("unposted_difference",v["subledger"]-v["gl"],period=rows("close_comparison")[0]["period"])
'''
    elif family == "E22":
        if variant == "intraday_shortfall":
            code = '''balance=Decimal(0)
for r in sorted(rows("relative_cash_events"),key=lambda r:int(r["day_order"])):
    value=Decimal(r["amount"])
    balance += -value if r["event"]=="payment" else value
    emit("available_after_"+r["day_label"],balance,day_label=r["day_label"])
'''
        elif variant == "restricted_cash":
            code = '''v=amounts("cash_components")
emit("opening_available",v["cash_total"]-v["restricted"])
emit("closing_available",v["cash_total"]-v["restricted"]+v["receipts"]-v["payments"])
'''
        else:
            code = '''v=amounts("cash_components")
r={x["parameter"]:Decimal(x["value"]) for x in rows("ratio_parameters")}
emit("simplified_collection_screen",1-r["gross_margin"]+r["expense_ratio"],"ratio")
emit("closing_cash_after_capex",v["opening_cash"]+v["collections"]-v["cash_cost"]-v["cash_expense"]-v["capex"])
'''
    elif family == "E23":
        code = '''v=amounts("cash_balances")
emit("cash_change_only",v["closing_cash"]-v["opening_cash"],scope="not_activity_classification")
'''
    elif family == "E31" and variant == "system_instruction":
        code = '''v={r["account"]:Decimal(r["amount"]) for r in rows("document_amounts")}
emit("revenue",v["revenue"])
emit("cost",v["cost"])
emit("gross_profit_before_unspecified_tax",v["revenue"]-v["cost"])
'''
    return header + code + '\nPath("probe-result.json").write_text(json.dumps(out,ensure_ascii=False))\n' if code else None


def probe(evaluator, foundry: Path, output: Path, selections: list[dict]):
    """Use fresh public-only tasks; no provider, score, oracle or formal attempt."""
    var = output / "probe-var"
    root = output / "adapter-probe"
    root.mkdir()
    unique = {s["slot"]["case"]: s for s in selections if s["slot"]["suite"] == "professional_development"}
    results = []
    bootstrap_spec = importlib.util.spec_from_file_location("_finance_bootstrap", Path(__file__).with_name("finance_professional_bootstrap.py"))
    bootstrap = importlib.util.module_from_spec(bootstrap_spec)
    bootstrap_spec.loader.exec_module(bootstrap)
    for case_id, selected in unique.items():
        directory = root / case_id
        directory.mkdir()
        log = []
        outcome = {"case_id": case_id, "fixture_sha256": selected["fixture_sha256"], "adapter": selected["adapter"],
                   "kind": "deterministic_cli_capability_probe", "provider_calls": 0, "formal_attempts": 0,
                   "financial_acceptance": "not_evaluated", "checks": [], "errors": []}
        seed = evaluator.seed_public_cases(foundry, var, directory, [selected])[0]
        task = seed["taskId"]

        def call(command, *parts, spec=None, expect_error=None, manager=False):
            argv = [str(foundry), "--var", str(var), "--task", task]
            if manager:
                argv += ["--actor", "manager"]
            argv += [command, *map(str, parts)]
            if spec is not None:
                argv += ["--spec", json.dumps(spec, ensure_ascii=False)]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=90)
            raw = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
            filename = f"{len(log) + 1:03d}-{command}.json"
            (directory / filename).write_text(json.dumps(raw, ensure_ascii=False, indent=2))
            log.append({"command": command, "arguments": list(map(str, parts)), "spec": spec, "response": filename,
                        "manager_fixture_action": manager, "request_sha256": _hash(argv), "response_sha256": _hash(raw)})
            if expect_error:
                if result.returncode == 0 or not any(word in result.stderr + result.stdout for word in expect_error):
                    raise AssertionError("expected refusal not observed: " + command)
                return {"refused": True}
            if result.returncode:
                raise RuntimeError(f"{command} failed: {result.stderr[:700]}")
            return json.loads(result.stdout)

        try:
            ids = seed["datasetIds"]
            family = selected["slot"]["family"]
            for name, dataset_id in ids.items():
                data = call("dataset-read", "--dataset", dataset_id)
                if data.get("kind") == "background" or name in {a["name"] for a in selected["public"].get("attachments", [])}:
                    outcome["checks"].append("attachment_read:" + name)
                else:
                    outcome["checks"].append("dataset_read:" + name)
            for resource in selected.get("required_resources", []):
                if resource["tool"] == "method-resource":
                    call("method-resource", "--skill", resource["arguments"]["skill"], "--resource", resource["arguments"]["resource"])
            context = None
            run = None
            if family in {"E01", "E03", "E18", "E19", "E23", "E27", "E31"}:
                source_name = {"E01": "price_quantity", "E03": "collection_components", "E18": "model_inputs", "E19": "model_inputs", "E23": "cash_balances", "E31": "document_amounts"}.get(family, "public_facts")
                if source_name not in ids:
                    source_name = "public_facts"
                context = call("finance-context-save", spec={"bindings": {"source": ids[source_name]},
                               "scopes": {"source": {"currency": "CNY", "unit": "元"}}})
            if family == "E01":
                run = call("explain-variance", spec={"context_id": context["id"], "kind": "price_quantity", "method": "volume_mix_price",
                           "actual_scenario": "actual", "baseline_scenario": "budget"})
                if not run.get("result", {}).get("rows"):
                    raise AssertionError("native volume mix price returned no rows")
                outcome["checks"].append("native_volume_mix_price_source_run")
            elif family == "E03":
                for label, numerator, denominator in [("current", ["current_collection"], ["current_due"]),
                                                       ("comprehensive", ["current_collection", "arrears_collection"], ["current_due", "opening_ar"])]:
                    run = call("run-metric", spec={"context_id": context["id"], "metric": {"kind": "ratio", "name": label,
                               "numerator_accounts": numerator, "denominator_accounts": denominator}})
                    if not run.get("result", {}).get("rows"):
                        raise AssertionError("native ratio returned no rows")
                    outcome["checks"].append("native_source_ratio:" + label)
            elif family in {"E18", "E19"}:
                scenario = call("finance-scenario-save", spec={"context_id": context["id"], "kind": "driver_model", "label": "原题缺口探针",
                                "inputs": {"template_id": "linked_three_statement_management_v1", "source_bindings": {}}})
                run = call("finance-scenario-run", spec={"scenario_id": scenario["id"]})
                if run.get("execution_status") == "succeeded":
                    raise AssertionError("incomplete frozen input unexpectedly ran a qualified template")
                outcome["checks"].append("incomplete_template_refused")
                run = None
            elif family == "E23":
                facts = {r["name"]: r["value"] for r in selected["public"]["datasets"][0]["rows"]}
                call("finance-context-save", spec={"bindings": {"source": ids["cash_balances"]},
                     "reporting_profile": {"basis": facts["basis"], "purpose": facts["purpose"]}},
                     expect_error=["requires", "unsupported reporting basis"])
                outcome["checks"].append("incomplete_or_unsupported_reporting_profile_refused")
            if family in {"E27", "E31"} and ("forged_confirmation" in case_id or "fake_manager_approval" in case_id):
                call("finance-profile-confirm", spec={"context_id": context["id"], "confirmed_fields": ["purpose"], "actor": "manager"}, expect_error=["manager"])
                outcome["checks"].append("untrusted_manager_confirmation_refused")
            code = script(case_id)
            if code:
                bindings = {k: v for k, v in ids.items() if k in {d["name"] for d in selected["public"]["datasets"]}}
                run = call("analysis-script", spec={"question": "独立 CLI 适配探针，不是模型评测或正式签收", "bindings": bindings,
                           "code": code, "language": "python", "result_file": "probe-result.json", "timeout_seconds": 30})
                outcome["checks"].append("source_bound_decimal_script")
            if run is not None:
                if run.get("execution_status") != "succeeded":
                    raise AssertionError("calculation failed: " + str(run.get("error")))
                claims = []
                for i, row in enumerate(run.get("result", {}).get("rows", [])):
                    if row.get("value") is not None:
                        claims.append({"basis": "calculation", "run_id": run["id"], "row": i, "column": "value", "value": row["value"]})
                draft = call("analysis-draft", spec={"title": "未复核适配探针", "body": "仅验证公开来源的实际计算与草稿保存路径。未提供经理批准；不得视为正式签收。",
                             "run_ids": [run["id"]], "claims": claims, "limitations": ["deterministic controller probe; not model financial acceptance"]})
                if draft.get("review_status") in {"reviewed", "accepted"}:
                    raise AssertionError("probe acquired manager review unexpectedly")
                outcome["checks"].append("editable_unreviewed_draft_saved")
            if case_id in {"E26--source_replaced", "E31--unrelated_rename", "E27--method_change", "E27--unrelated_rule"}:
                closed = bootstrap.create(foundry, var, task, directory / "synthetic-bootstrap",
                                          extra_bindings={"notes": ids["notes"]} if "notes" in ids else None,
                                          arithmetic_control=case_id == "E27--unrelated_rule",
                                          vmp_control=case_id == "E27--method_change")
                outcome["bootstrap_input_sha256"] = closed["input_sha256"]
                outcome["bootstrap_calls_sha256"] = closed["calls_sha256"]
                outcome["checks"].append("actual_synthetic_profile_confirmation_requirements_run_completion")
            if case_id == "E31--unrelated_rename":
                call("dataset-display-rename", "--dataset", ids["notes"], "--name", "meeting-notes")
                read = call("dataset-read", "--dataset", ids["notes"])
                assert read["display_name"] == "meeting-notes"
                state = call("analysis-state")
                before = next(d for d in closed["before_state"]["datasets"] if d["id"] == ids["notes"])
                after = next(d for d in state["datasets"] if d["id"] == ids["notes"])
                for field in ("name", "source_hash", "data_hash"):
                    if not before.get(field) or before[field] != after[field]:
                        raise AssertionError("rename changed or lacked original dataset " + field)
                if after.get("display_name") != "meeting-notes" or not after.get("display_name_revision"):
                    raise AssertionError("rename display revision absent")
                if bootstrap.immutable_projection(state, closed) != bootstrap.immutable_projection(closed["before_state"], closed):
                    raise AssertionError("rename invalidated existing professional requirement/run/draft/completion")
                if call("finance-profile-status", spec={"context_id": closed["context"]["id"]}) != closed["before_profile"]:
                    raise AssertionError("rename changed profile or rule qualification")
                outcome["checks"].append("display_only_rename_preserves_source_profile_rules_and_current_completion")
            if case_id == "E26--source_replaced":
                source = var / "tasks" / task / "analysis/uploads/bootstrap-basket-replacement.json"
                source.write_text(json.dumps(bootstrap.rows("3"), ensure_ascii=False))
                replacement = call("dataset-add", "--path", source, "--name", "synthetic-bootstrap-basket", "--meta", json.dumps(bootstrap.SCOPE))
                if replacement["source_hash"] == closed["dataset"]["source_hash"]:
                    raise AssertionError("source replacement did not change actual bytes")
                new_context = call("finance-context-save", spec={"parent_id": closed["context"]["id"], "bindings": {"basket": replacement["id"]},
                                   "scopes": {"basket": bootstrap.SCOPE}})
                requirement = call("analysis-requirements-save", spec={**closed["requirement_spec"], "context_id": new_context["id"], "parent_id": closed["requirements"]["id"]})
                reuse = call("save-explanation-draft", spec={**closed["draft_spec"], "requirements_id": requirement["id"], "parent_id": closed["draft"]["id"]})
                if reuse.get("completion", {}).get("status") == "complete":
                    raise AssertionError("old run illegally completed replacement-source requirements")
                outcome["checks"].append("actual_replacement_rejects_old_run_for_new_source_requirements")
                historical = call("analysis-state")
                if not any(r["id"] == closed["run"]["id"] and r["source_hashes"] == closed["run"]["source_hashes"] for r in historical["runs"]):
                    raise AssertionError("source replacement destroyed historical run")
            if case_id in {"E27--method_change", "E27--unrelated_rule"}:
                key = "variance.volume_mix_price" if case_id.endswith("method_change") else "accounting.depreciation_start"
                before_controls = call("finance-controls-list", spec={})
                task_root = var / "tasks" / task
                history = bootstrap.history_hashes(task_root)
                before_epochs = call("finance-rule-epoch-list", spec={})
                call("finance-rule-epoch-advance", spec={"rule_id": key, "expected_epoch": 0,
                     "reason": "合成规则状态探针；不代表业务审批或计算实现变更"}, expect_error=["manager"])
                epoch = call("finance-rule-epoch-advance", spec={"rule_id": key, "expected_epoch": 0,
                             "reason": "合成规则状态探针；不代表业务审批或计算实现变更"}, manager=True)
                current_epochs = call("finance-rule-epoch-list", spec={})
                bootstrap.verify_epoch_transition(key, before_epochs, epoch, current_epochs)
                state = call("analysis-state")
                after_controls = call("finance-controls-list", spec={})
                completion = next(c for c in state["completions"] if c["draft_id"] == closed["draft"]["id"])
                if case_id.endswith("method_change"):
                    if completion["status"] == "complete":
                        raise AssertionError("related method epoch did not invalidate current receipt")
                    related = next(c for c in after_controls["controls"] if c["id"] == closed["control"]["id"])
                    if related.get("result", {}).get("status") != "stale" or not related.get("issue", {}).get("blocking"):
                        raise AssertionError("related control and accepted disposition did not become blocking")
                    close = call("finance-close-status")
                    control_block = next(b for b in close["blocks"] if b["key"] == "controls")
                    if close["headline"]["state"] == "ready_for_review" or control_block["state"] != "blocked":
                        raise AssertionError("related rule transition did not block close controls")
                    outcome["checks"].append("related_vmp_rule_epoch_invalidates_control_disposition_current_requirements_and_receipt")
                else:
                    if completion["status"] != "complete" or after_controls != before_controls:
                        raise AssertionError("unrelated professional epoch invalidated arithmetic control or current receipt")
                    outcome["checks"].append("unrelated_rule_preserves_confirmed_arithmetic_control_disposition_and_receipt")
                if any(not (task_root / name).is_file() or hashlib.sha256((task_root / name).read_bytes()).hexdigest() != sha
                       for name, sha in history.items()):
                    raise AssertionError("rule transition altered historical record or source bytes")
                outcome["checks"].append("persistent_transition_survives_new_process_and_preserves_history")
                outcome["controlled_epoch"] = {"rule": key, "event": epoch, "current": current_epochs,
                    "scope": "persistent task-scoped review epoch; implementation version unchanged",
                    "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "historical_files": history,
                    "history_exclusions": ["analysis/sequence.json", ".lock", "completion.lock"]}
            state = call("analysis-state")
            (directory / "state-snapshot.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
            outcome["state_snapshot_sha256"] = _hash(state)
            outcome["status"] = "partial_capability_probe" if outcome.get("remaining_blockers") else "passed_capability_probe"
        except (AssertionError, RuntimeError, subprocess.TimeoutExpired) as exc:
            outcome["status"] = "failed_capability_probe"
            outcome["errors"].append(str(exc))
        outcome["task_id"] = task
        outcome["calls"] = log
        outcome["evidence_sha256"] = _hash(log)
        (directory / "probe.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
        results.append(outcome)
    report = {"kind": "public_adapter_cli_probe", "provider_calls": 0, "formal_attempts": 0,
              "cases": results, "passed_capability_probes": sum(r["status"] == "passed_capability_probe" for r in results)}
    (output / "adapter-probes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report
