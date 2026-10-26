#!/usr/bin/env python3
"""Independent, append-only transaction review verification through the public CLI.

Synthetic engineering decisions only. This suite grants no original release-slot
credit, professional credential, monetary evidence eligibility or posting authority.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "tools/verify_finance_mutation_pipeline.py"
CONTRACT = ROOT / "tests/fixtures/finance_supplements/review_v1/contract.json"
ORIGINAL_SHA256 = "7868708a037dce6fabd89a0b41915ded1dc31913e55bf216960e48f1e4a8c7bf"
CONTRACT_SHA256 = "6f9a39464cd6adac5eb5832c992e1806421d9911ce9a4b18c346b716cf9de38e"
PREPARE = "finance-transaction-review-prepare"
SAVE = "finance-transaction-review-save"
REVOKE = "finance-transaction-review-revoke"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_inputs():
    if sha(ORIGINAL) != ORIGINAL_SHA256 or sha(CONTRACT) != CONTRACT_SHA256:
        raise ValueError("frozen original driver or independent review contract identity mismatch")
    contract = json.loads(CONTRACT.read_text())
    if contract["original_driver_sha256"] != ORIGINAL_SHA256:
        raise ValueError("contract original driver mismatch")
    specification = importlib.util.spec_from_file_location("original_finance_mutation_driver", ORIGINAL)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module, contract


def history_hashes(task_root):
    """Include all prior bytes, even XLSX; exclude only documented live counters/locks."""
    task_root = Path(task_root)
    return {p.relative_to(task_root).as_posix(): sha(p) for p in sorted(task_root.rglob("*"))
            if p.is_file() and p.name not in {".lock", "completion.lock"}
            and p.relative_to(task_root).as_posix() != "analysis/sequence.json"}


def changed_history(before, after):
    return sorted(name for name, digest in before.items() if after.get(name) != digest)


def existing_sequence(directory):
    seen = set()
    for path in sorted((Path(directory) / "calls").glob("*.json")):
        record = json.loads(path.read_text())
        sequence = record["sequence"]
        if type(sequence) is not int or sequence < 1 or sequence in seen:
            raise ValueError("invalid or duplicate existing CLI sequence")
        if int(path.name.split("-", 1)[0]) != sequence:
            raise ValueError("CLI sequence filename mismatch")
        seen.add(sequence)
    return max(seen, default=0)


def restore_cli(module, foundry, directory, task_id):
    class ContinuingCLI(module.CLI):
        def call(self, command, *parts, **kwargs):
            # The original recorder writes normally; guard every next sequence before
            # invoking it so a recovered secondary task cannot overwrite prior calls.
            if any((self.directory / "calls").glob(f"{self.sequence + 1:03d}-*.json")):
                raise FileExistsError("next CLI sequence already exists")
            return super().call(command, *parts, **kwargs)
    cli = ContinuingCLI(foundry, Path(directory))
    cli.task = task_id
    cli.sequence = existing_sequence(directory)
    return cli


def refusal_matches(record, text):
    return bool(isinstance(record, dict) and type(record.get("returncode")) is int
                and record["returncode"] != 0 and text.casefold() in record.get("stderr", "").casefold())


def refused_history_problems(before, after):
    return ["refused operation changed or appended task records"] if before != after else []


def scope_problems(prepared):
    eligibility = (prepared or {}).get("eligibility") or {}
    return ["review scope or privileges changed"] if (
        eligibility.get("scope") != "transaction_review_only"
        or eligibility.get("counts_as_amount_evidence") is not False
        or eligibility.get("posting_authorized") is not False) else []


def completion_problems(observation):
    """Require actual independent surfaces, never a caller-provided 'pass' label."""
    problems = []
    draft_id = observation.get("draft_id")
    validation = observation.get("validation") or {}
    checked = validation.get("value") or {}
    requirements = checked.get("requirements") or {}
    refresh = observation.get("refresh") or {}
    refreshed = refresh.get("value") or {}
    draft = observation.get("current_draft") or {}
    receipt = observation.get("current_completion") or {}
    prepared = observation.get("prepared") or {}
    if not draft_id or draft.get("id") != draft_id or refreshed.get("id") != draft_id:
        problems.append("same original draft not proven")
    if validation.get("returncode") != 0 or checked.get("status") != "pass":
        problems.append("fresh validation did not pass")
    if draft.get("quality", {}).get("status") != "pass":
        problems.append("current draft quality did not pass")
    if (requirements.get("requirements_id") != observation.get("requirements_id")
            or not observation.get("requirements_id")
            or requirements.get("coverage", {}).get("status") != "pass"
            or requirements.get("original_requirements_completed") is not True
            or not requirements.get("items")
            or any(item.get("status") != "answered" or item.get("counts_as_amount_evidence") is not False
                   for item in requirements.get("items", []))):
        problems.append("full original transaction requirements not satisfied")
    if (refresh.get("returncode") != 0 or not receipt.get("id") or receipt.get("status") != "complete"
            or receipt.get("draft_id") != draft_id
            or (refreshed.get("completion") or {}).get("id") != receipt.get("id")):
        problems.append("actual current same-draft complete receipt missing")
    if (prepared.get("draft_id") != draft_id or prepared.get("current_status") != "approved"
            or (prepared.get("eligibility") or {}).get("eligible") is not True):
        problems.append("current matching approval missing")
    problems.extend(scope_problems(prepared))
    return problems


def incomplete_problems(observation):
    receipt = observation.get("current_completion") or {}
    if not receipt.get("id") or receipt.get("draft_id") != observation.get("draft_id"):
        return ["actual incomplete receipt missing"]
    if receipt.get("status") == "complete" or any(
            row.get("draft_id") == observation.get("draft_id") and row.get("status") == "complete"
            for row in observation.get("state", {}).get("completions", [])):
        return ["unexpected complete receipt"]
    return []


def epoch_problems(rule_id, before, event, after):
    old = {row["rule_id"]: row for row in before.get("rules", [])}
    new = {row["rule_id"]: row for row in after.get("rules", [])}
    record = event.get("rule_epoch") or {}
    if rule_id not in old or rule_id not in new:
        return ["dependent rule missing from actual epoch list"]
    if (set(old) != set(new) or old[rule_id].get("epoch") != 0 or new[rule_id].get("epoch") != 1
            or record.get("rule_id") != rule_id or record.get("previous_epoch") != 0 or record.get("epoch") != 1
            or not record.get("id") or new[rule_id].get("epoch_record_id") != record["id"]
            or old[rule_id].get("epoch_record_id") is not None or record.get("parent_id") is not None
            or not old[rule_id].get("implementation_version")
            or record.get("implementation_version") != old[rule_id]["implementation_version"]
            or new[rule_id].get("implementation_version") != old[rule_id]["implementation_version"]
            or record.get("changed_by") != "manager" or record.get("session_id") is not None
            or any(old[key] != new[key] for key in old if key != rule_id)):
        return ["actual durable epoch transition and authority not proven"]
    return []


def decision_problems(record, draft_id, decision):
    value = record.get("value") or {}
    review = value.get("review") or {}
    if (record.get("returncode") != 0 or not review.get("id") or review.get("draft_id") != draft_id
            or review.get("decision") != decision or review.get("saved_by") != "manager"
            or review.get("session_id") is not None or value.get("current_status") != decision):
        return ["actual manager decision not proven"]
    return []


class StageFailure(AssertionError):
    pass


class Audit:
    def __init__(self, cli, output, contract):
        self.cli, self.output, self.contract = cli, Path(output), contract
        self.task_root = cli.var / "tasks" / cli.task
        if not self.task_root.is_dir():
            raise ValueError("actual task directory missing")
        self.stages = []

    def stage(self, name, action, check, *, refuse_side_effects=False):
        before_hashes = history_hashes(self.task_root)
        before = self.cli.state()
        start = self.cli.sequence
        evidence, problems = None, []
        try:
            evidence = action()
            problems.extend(check(evidence))
        except Exception as exc:
            problems.append(f"{type(exc).__name__}: {exc}")
        after = self.cli.state()
        after_hashes = history_hashes(self.task_root)
        modified = changed_history(before_hashes, after_hashes)
        if modified:
            problems.append("historical bytes changed: " + ", ".join(modified))
        if refuse_side_effects:
            problems.extend(refused_history_problems(before_hashes, after_hashes))
        result = {"stage": name, "task_id": self.cli.task, "status": "fail" if problems else "pass",
                  "problems": problems, "evidence": evidence, "before": before, "after": after,
                  "first_action_sequence": start + 1, "last_sequence": self.cli.sequence,
                  "historical_files_before": before_hashes, "historical_files_after": after_hashes,
                  "modified_historical_files": modified,
                  "history_exclusions": ["analysis/sequence.json", ".lock", "completion.lock"]}
        write_new(self.output / f"{len(self.stages) + 1:02d}-{name}.json", result)
        self.stages.append({"stage": name, "status": result["status"], "problems": problems})
        if problems:
            raise StageFailure("; ".join(problems))
        return evidence

    def prepare(self, draft_id):
        return self.cli.call(PREPARE, spec={"draft_id": draft_id})

    def observe(self, draft_id, requirements_id):
        refresh = self.cli.call("save-explanation-draft", spec={"draft_id": draft_id}, required=False)
        validation = self.cli.call("validate-explanation", spec={"draft_id": draft_id}, required=False)
        prepared = self.prepare(draft_id)
        state = self.cli.state()
        receipt_id = ((refresh.get("value") or {}).get("completion") or {}).get("id")
        return {"draft_id": draft_id, "requirements_id": requirements_id, "refresh": refresh,
                "validation": validation, "prepared": prepared,
                "current_draft": next((d for d in state.get("drafts", []) if d.get("id") == draft_id), None),
                "current_completion": next((r for r in state.get("completions", []) if r.get("id") == receipt_id), None),
                "state": state}

    def decision(self, draft_id, prepared, decision="approved", **changes):
        spec = {"draft_id": draft_id, "basis_fingerprint": prepared["basis_fingerprint"],
                "decision": decision, "reviewer": "Synthetic engineering reviewer",
                "reason": "Engineering workflow verification; no real professional signoff or posting authority",
                "checklist": dict.fromkeys(self.contract["required_checklist"], True)}
        spec.update(changes)
        return spec

    def refuse(self, name, spec, text, actor="manager"):
        return self.stage(name, lambda: self.cli.call(SAVE, spec=spec, actor=actor, required=False),
                          lambda value: [] if refusal_matches(value, text) else ["expected refusal not proven"],
                          refuse_side_effects=True)


def verify_control(audit, observation, expected, *, epoch=False):
    draft_id = observation["current_draft"]["id"]
    requirements_id = observation["request"]["requirements_id"]
    result = {"draft_id": draft_id, "task_id": audit.cli.task, "expected": expected,
              "approval_scope": "transaction_check_only", "human_signoff": False,
              "counts_as_amount_evidence": False, "posting_authorized": False, "status": "fail"}
    try:
        run = observation["checked_run"]
        actual = {row["item"]: row["actual"] for row in run["result"]["rows"]}
        module, _ = load_inputs()
        module.assert_amounts(actual, expected)
        if (run["result"].get("status") != "pass"
                or run["result"].get("source_binding_status", {}).get("all_sources_verified") is not True
                or not run["result"].get("source_rows")):
            raise StageFailure("source-bound passing transaction check missing")
        result["source_records"] = {"input_hashes": run.get("input_hashes"), "source_hashes": run.get("source_hashes"),
                                    "output_hash": run.get("output_hash"), "source_rows": run["result"]["source_rows"]}
        initial = audit.stage("unreviewed_incomplete", lambda: audit.observe(draft_id, requirements_id),
            lambda value: incomplete_problems(value) + scope_problems(value["prepared"]) + (
                [] if value["prepared"].get("current_status") == "pending"
                and value["prepared"]["eligibility"].get("eligible") is True
                and value["prepared"].get("required_checklist") == audit.contract["required_checklist"]
                else ["eligible pending review with exact checklist missing"]))
        prepared = initial["prepared"]
        spec = audit.decision(draft_id, prepared)
        audit.refuse("assistant_refused", spec, "manager", actor="assistant")
        audit.refuse("stale_basis_refused", {**spec, "basis_fingerprint": "0" * 64}, "basis")
        audit.refuse("incomplete_checklist_refused", {**spec, "checklist": {}}, "checklist")

        def approve(preparation):
            decision = audit.cli.call(SAVE, spec=audit.decision(draft_id, preparation), actor="manager", required=False)
            problems = decision_problems(decision, draft_id, "approved")
            if problems:
                raise StageFailure("; ".join(problems))
            observed = audit.observe(draft_id, requirements_id)
            return {**observed, "decision": decision}

        approved = audit.stage("approved_same_draft_complete", lambda: approve(prepared), completion_problems)
        review_id = approved["decision"]["value"]["review"]["id"]
        approved_receipt = approved["current_completion"]["id"]

        def revoke():
            revoked = audit.cli.call(REVOKE, spec={"review_id": review_id, "reason": "Synthetic withdrawal"},
                                     actor="manager", required=False)
            problems = decision_problems(revoked, draft_id, "revoked")
            if problems:
                raise StageFailure("; ".join(problems))
            return {**audit.observe(draft_id, requirements_id), "revocation": revoked}

        def revoked_problems(value):
            prior = next((r for r in value["state"].get("completions", []) if r.get("id") == approved_receipt), None)
            return incomplete_problems(value) + ([] if value["prepared"].get("current_status") == "revoked"
                and prior and prior.get("status") != "complete" else ["revoked current view retained approval"])

        audit.stage("revoked_incomplete", revoke, revoked_problems)
        audit.refuse("old_basis_replay_refused", spec, "basis")
        fresh = audit.prepare(draft_id)
        if fresh["basis_fingerprint"] == prepared["basis_fingerprint"]:
            raise StageFailure("revocation did not change basis")
        audit.stage("fresh_approval_complete", lambda: approve(fresh), completion_problems)

        def clone():
            clone_spec = deepcopy(observation["request"])
            clone_spec.update(parent_id=draft_id, body=clone_spec["body"] + "\nIndependent new-body clone; requires a separate review.")
            saved = audit.cli.call("save-explanation-draft", spec=clone_spec)
            if saved["id"] == draft_id:
                raise StageFailure("clone reused original draft")
            return audit.observe(saved["id"], requirements_id)

        audit.stage("clone_not_inherited", clone, lambda value: incomplete_problems(value) + (
            [] if value["prepared"].get("current_status") == "pending" else ["clone inherited review"]))
        if epoch:
            def advance():
                rule_id = "accounting.transaction_recognition"
                before = audit.cli.call("finance-rule-epoch-list", spec={})
                old = next(r for r in before["rules"] if r["rule_id"] == rule_id)
                if old["epoch"] != 0:
                    raise StageFailure("new task rule epoch must begin at zero")
                event = audit.cli.call("finance-rule-epoch-advance", actor="manager", spec={
                    "rule_id": rule_id, "expected_epoch": 0, "reason": "Synthetic dependent-rule invalidation"})
                after = audit.cli.call("finance-rule-epoch-list", spec={})
                problems = epoch_problems(rule_id, before, event, after)
                if problems:
                    raise StageFailure("; ".join(problems))
                return {**audit.observe(draft_id, requirements_id), "epoch_before": before, "epoch_event": event, "epoch_after": after}
            audit.stage("dependent_rule_epoch_invalidates", advance, lambda value: incomplete_problems(value) + (
                [] if value["prepared"].get("current_status") == "stale" else ["rule epoch did not invalidate review"]))
        audit.stage("historical_files_preserved", lambda: {"all_previous_stages_preserved_bytes": True}, lambda _: [])
        result["status"] = "pass"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["stages"] = audit.stages
    write_new(audit.output / "result.json", result)
    return result


def verify_mutant(audit, observation):
    draft_id = observation["current_draft"]["id"]
    result = {"draft_id": draft_id, "task_id": audit.cli.task, "status": "fail"}
    try:
        prepared = audit.prepare(draft_id)
        if prepared["eligibility"].get("eligible") is not False:
            raise StageFailure("original erroneous mutant incorrectly eligible")
        audit.refuse("mutant_approval_refused", audit.decision(draft_id, prepared), "not eligible")
        def reject():
            saved = audit.cli.call(SAVE, spec=audit.decision(draft_id, prepared, "rejected"), actor="manager", required=False)
            problems = decision_problems(saved, draft_id, "rejected")
            if problems:
                raise StageFailure("; ".join(problems))
            return {**audit.observe(draft_id, observation["request"]["requirements_id"]), "rejection": saved}
        audit.stage("mutant_rejection_auditable", reject, lambda value: incomplete_problems(value) + (
            [] if value["prepared"].get("current_status") == "rejected" else ["rejection not current"]))
        result["status"] = "pass"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["stages"] = audit.stages
    write_new(audit.output / "result.json", result)
    return result


def suite_status(families, contract, selected):
    expected = {case["id"]: len(case["controls"]) for case in contract["cases"] if case["id"] in selected}
    control_stages = set(contract["required_stages"]) - {"mutant_approval_refused"}
    if len(families) != len(expected) or {f["id"] for f in families} != set(expected):
        return "fail"
    for family in families:
        if (family.get("status") != "pass" or family.get("mutant", {}).get("status") != "pass"
                or len(family.get("controls", [])) != expected[family["id"]]
                or any(control.get("status") != "pass" for control in family["controls"])):
            return "fail"
        if not {"mutant_approval_refused", "mutant_rejection_auditable"} <= {
                stage["stage"] for stage in family["mutant"].get("stages", []) if stage.get("status") == "pass"}:
            return "fail"
        if any(not control_stages <= {stage["stage"] for stage in control.get("stages", [])
                                      if stage.get("status") == "pass"} for control in family["controls"]):
            return "fail"
    return "pass" if len(families) == contract["required_counts"]["families"] else "partial_pass"


def identity(module, foundry, manifest):
    original_standard = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    return {"driver_sha256": sha(__file__), "original_driver_sha256": sha(ORIGINAL),
            "contract_sha256": sha(CONTRACT), "original_standard_sha256": sha(original_standard),
            "public_inputs": module.tree_hashes(module.FIXTURES),
            "candidate": module.candidate_identity(foundry, manifest)}


def run_suite(foundry, candidate_manifest, output, selected):
    module, contract = load_inputs()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = identity(module, foundry, candidate_manifest)
    if before["original_standard_sha256"] != contract["original_standard_sha256"]:
        raise ValueError("original standard identity mismatch")
    write_new(output / "identity-before.json", before)
    families = []
    for case in contract["cases"]:
        if case["id"] not in selected:
            continue
        case_id = case["id"]
        directory = output / case_id / "original"
        family = {"id": case_id, "status": "fail", "controls": []}
        try:
            original = module.execute_case(foundry, directory, case_id)
            original_hash = sha(directory / "result.json")
            original_calls = {str(p.relative_to(directory)): sha(p) for p in directory.rglob("calls/*.json")}
            family.update(original_result=str(directory / "result.json"), original_sha256=original_hash,
                          original_classification=original["status"], original_calls=original_calls)
            if original["status"] != "detected":
                raise StageFailure("original mutation was not independently detected")
            cli = restore_cli(module, foundry, directory, original["task_id"])
            family["mutant"] = verify_mutant(Audit(cli, output / case_id / "mutant", contract), original["mutant"])
            controls = [(directory, original["task_id"], original["control"])]
            if case_id in {"M08", "M09"}:
                key, folder = ("capitalization_control", "capitalization-control") if case_id == "M08" else ("new_sale_control", "new-sale-control")
                secondary = original["setup"][key]["observation"]
                controls.append((directory / folder, secondary["current_draft"]["task_id"], secondary))
            for index, ((control_dir, task_id, observation), expected) in enumerate(zip(controls, case["controls"], strict=True)):
                cli = restore_cli(module, foundry, control_dir, task_id)
                item = verify_control(Audit(cli, output / case_id / expected["kind"], contract), observation,
                                      expected["expected"], epoch=case_id == "M07" and index == 0)
                item["kind"] = expected["kind"]
                family["controls"].append(item)
            changed = [p for p, digest in original_calls.items() if sha(directory / p) != digest]
            if sha(directory / "result.json") != original_hash or changed:
                raise StageFailure("original result or raw calls overwritten")
            family["status"] = "pass" if family["mutant"]["status"] == "pass" and all(
                c["status"] == "pass" for c in family["controls"]) else "fail"
        except Exception as exc:
            family["error"] = f"{type(exc).__name__}: {exc}"
        write_new(output / case_id / "review-result.json", family)
        families.append(family)
    after = identity(module, foundry, candidate_manifest)
    write_new(output / "identity-after.json", after)
    status = suite_status(families, contract, selected) if before == after else "fail"
    summary = {"suite_id": contract["suite_id"], "created_at": datetime.now(timezone.utc).isoformat(),
               "status": status, "selected_cases": selected, "families": families,
               "identity_unchanged": before == after, "contract_sha256": CONTRACT_SHA256,
               "provider_calls": 0, "original_slots_credit": 0, "approved_scope": contract["approved_scope"],
               "human_signoff": False, "counts_as_amount_evidence": False, "posting_authorized": False,
               "counts": {"families": len(families), "legitimate_controls": sum(len(f["controls"]) for f in families),
                          "primary_mutants": sum("mutant" in f for f in families)}, "limits": contract["limits"]}
    write_new(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory; never reused")
    parser.add_argument("--cases", nargs="+", choices=["M07", "M08", "M09"], default=["M07", "M08", "M09"])
    args = parser.parse_args()
    if len(set(args.cases)) != len(args.cases):
        parser.error("duplicate cases are not allowed")
    result = run_suite(args.foundry, args.candidate_manifest, args.output, args.cases)
    print(json.dumps({key: result[key] for key in ("status", "counts", "identity_unchanged", "provider_calls", "original_slots_credit")}))
    return 0 if result["status"] in {"pass", "partial_pass"} else 1


if __name__ == "__main__":
    sys.exit(main())
