"""Durable task rule review epochs use trusted authority, never caller labels."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from openpyxl import Workbook

from foundry.errors import FoundryError
from foundry.finance_controls import applies_to, control_key
from foundry.finance_professional import artifact_rules_match, requirement_rule_identity, rule_identity
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


RULE = "variance.volume_mix_price"
OTHER = "accounting.depreciation_start"


def store(tmp_path, **kwargs):
    return FinanceStore(TaskStore(tmp_path / "var").create(title="规则复核纪元"), **kwargs)


def advance(service, expected=0, rule_id=RULE, **extra):
    return service.finance_rule_epoch_advance({"rule_id": rule_id, "expected_epoch": expected,
                                              "reason": "Synthetic engineering review event", **extra})["rule_epoch"]


def epochs(service):
    return {row["rule_id"]: row for row in service.finance_rule_epoch_list({})["rules"]}


@pytest.mark.parametrize("actor,session", [(None, None), ("assistant", None), ("manager", "runtime-session")])
def test_epoch_advance_requires_trusted_manager_without_runtime_session(tmp_path, actor, session):
    service = store(tmp_path, actor=actor, session_id=session)
    with pytest.raises(FoundryError, match="manager|session"):
        advance(service, actor="manager", changed_by="manager")
    assert epochs(service)[RULE]["epoch"] == 0


@pytest.mark.parametrize("expected", [True, False, "0", 0.0, -1, None, [], {}])
def test_expected_epoch_is_a_nonnegative_integer(tmp_path, expected):
    service = store(tmp_path, actor="manager")
    with pytest.raises(FoundryError, match="expected_epoch"):
        advance(service, expected)
    assert epochs(service)[RULE]["epoch"] == 0


@pytest.mark.parametrize("extra", [{"epoch": 0}, {"version": 2}, {"actor": "manager"}, {"bindings": {}},
                                   {"rule_id": "caller.invented"}, {"reason": ""}])
def test_epoch_spec_cannot_inject_authority_version_or_rollback(tmp_path, extra):
    service = store(tmp_path, actor="manager")
    with pytest.raises(FoundryError):
        advance(service, **extra)
    assert epochs(service)[RULE]["epoch"] == 0


def test_epochs_are_monotonic_task_local_and_history_resolves_as_of_seq(tmp_path):
    service = store(tmp_path, actor="manager")
    baseline = rule_identity(service, {}, [RULE])
    first = advance(service)
    assert (first["epoch"], first["previous_epoch"], first["implementation_version"], first["changed_by"]) == (1, 0, 1, "manager")
    assert not first.get("parent_id")
    assert rule_identity(service, {}, [RULE], max_seq=first["seq"]) == baseline
    one = rule_identity(service, {}, [RULE])
    assert one["rule_dependencies"] == [{"id": RULE, "version": 1, "epoch": 1}]
    with pytest.raises(FoundryError, match="conflict"):
        advance(service)
    second = advance(FinanceStore(service.task, actor="manager"), 1)
    assert (second["epoch"], second["previous_epoch"], second["parent_id"]) == (2, 1, first["id"])
    assert rule_identity(service, {}, [RULE], max_seq=second["seq"]) == one
    with pytest.raises(FoundryError, match="conflict"):
        advance(service, 1)
    assert len(service._list("rule_epochs")) == 2
    assert epochs(store(tmp_path / "another"))[RULE]["epoch"] == 0
    assert rule_identity(service, {}, [])["rule_dependencies"] == []
    assert not artifact_rules_match({"engine": "finance", "professional_identity": baseline}, one)
    assert artifact_rules_match({"engine": "finance", "professional_identity": one}, one)


def test_epoch_cas_serializes_concurrent_manager_changes(tmp_path):
    service = store(tmp_path, actor="manager")
    def attempt(_):
        try:
            return advance(FinanceStore(service.task, actor="manager"))["epoch"]
        except FoundryError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, range(2)))
    assert results.count(1) == 1
    assert sum("conflict" in str(value) for value in results) == 1
    assert len(service._list("rule_epochs")) == 1


@pytest.mark.parametrize("corruption", [{"bindings": {"hidden": "f" * 32}}, {"seq": True}, {"seq": 0},
                                         {"seq": "2"}, {"domain": "foundry.finance.controls.v1"}])
def test_malformed_task_epoch_fails_closed_in_full_and_restricted_views(tmp_path, corruption):
    from foundry.analysis import _hash
    service = store(tmp_path, actor="manager")
    event = advance(service)
    path = service._path("rule_epochs", event["id"])
    malformed = {key: value for key, value in event.items() if key != "_integrity_hash"}
    malformed.update(corruption)
    malformed["_integrity_hash"] = _hash(malformed)
    path.write_text(json.dumps(malformed))
    restricted = FinanceStore(service.task, snapshot_ids=[], session_id="reader")
    for reader in (service, restricted):
        with pytest.raises(FoundryError, match="invalid professional rule epoch"):
            epochs(reader)
        with pytest.raises(FoundryError, match="invalid professional rule epoch"):
            rule_identity(reader, {}, [RULE])
    with pytest.raises(FoundryError, match="invalid professional rule epoch"):
        advance(service, 1)


def test_cli_restart_reads_persisted_epoch_and_public_list_omits_private_reason(tmp_path):
    service = store(tmp_path)
    args = [sys.executable, "-m", "foundry.cli", "--var", str(tmp_path / "var"), "--task", service.task.id]
    spec = json.dumps({"rule_id": RULE, "expected_epoch": 0, "reason": "Private manager explanation"})
    refused = subprocess.run([*args, "finance-rule-epoch-advance", "--spec", spec], capture_output=True, text=True)
    assert refused.returncode != 0 and "manager" in refused.stderr
    accepted = subprocess.run([*args, "--actor", "manager", "finance-rule-epoch-advance", "--spec", spec], capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stderr
    event = json.loads(accepted.stdout)["rule_epoch"]
    listed = subprocess.run([*args, "finance-rule-epoch-list", "--spec", "{}"], capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    current = next(row for row in json.loads(listed.stdout)["rules"] if row["rule_id"] == RULE)
    assert current == {"rule_id": RULE, "implementation_version": 1, "epoch": 1, "epoch_record_id": event["id"]}
    assert "Private manager" not in listed.stdout
    restricted = FinanceStore(service.task, snapshot_ids=[], session_id="runtime-session")
    assert epochs(restricted)[RULE] == current
    with pytest.raises(FoundryError):
        restricted.finance_rule_epoch_list({"max_seq": 0})


def control_case(tmp_path):
    service = store(tmp_path, actor="manager")
    path = tmp_path / "closure.xlsx"
    book = Workbook()
    book.active.title = "Bridge"
    for row in [("Volume", 41), ("Mix", -9), ("Price", 3), ("Total", 34)]:
        book.active.append(row)
    book.save(path)
    dataset = service.analysis.add_dataset(path, name="工程闭合来源")
    def side(cell):
        return {"dataset_id": dataset["id"], "source_hash": dataset["source_hash"], "sheet": "Bridge", "range": cell}
    control = {"kind": "formula", "formula": "volume_mix_price_closure", "label": "VMP 闭合检查", "unit": "元",
               "inputs": {"volume_contribution": side("B1"), "mix_contribution": side("B2"), "price_contribution": side("B3")},
               "right": side("B4")}
    plain = {"kind": "tie_out", "label": "普通算术", "left": side("B1"), "right": side("B1")}
    return service, control, plain


def test_vmp_closure_is_recomputed_from_archived_cells_and_dependency_is_server_owned(tmp_path):
    service, control, plain = control_case(tmp_path)
    saved = service.finance_controls_save({"controls": [control, {**plain, "rule_dependencies": [RULE]}], "confirm": True})["controls"]
    assert saved[0]["professional_identity"]["rule_dependencies"] == [{"id": RULE, "version": 1}]
    assert saved[1]["professional_identity"]["rule_dependencies"] == []
    run = service.finance_controls_run({})
    result = next(row for row in run["results"] if row["control_id"] == saved[0]["id"])
    assert (result["status"], result["left"]["value"], result["right"]["value"], result["difference"]) == ("break", "35", "34", "1")
    assert result["source_hashes"]
    # Changing an actual range changes the recomputation; arbitrary labels cannot freeze a claimed result.
    changed = {**control, "inputs": {**control["inputs"], "price_contribution": control["inputs"]["mix_contribution"]}}
    preview = service.finance_controls_preview({"control": changed})["preview"]
    assert preview["left"]["value"] == "23"
    with pytest.raises(FoundryError, match="needs"):
        service.finance_controls_save({"control": {**control, "inputs": {"volume_contribution": control["right"]}}})


def test_related_epoch_stales_control_and_disposition_unrelated_preserves_them(tmp_path):
    service, control, plain = control_case(tmp_path)
    saved = service.finance_controls_save({"controls": [control, plain], "confirm": True})["controls"]
    service.finance_controls_run({})
    decision = service.finance_control_disposition_save({"control_id": saved[0]["id"], "decision": "waived",
                                                        "reason": "Synthetic review only", "decided_by_name": "Test manager"})
    paths = [path for folder in ("controls", "control_runs", "control_dispositions")
             for path in (service.analysis.root / "finance" / folder).glob("*.json")]
    originals = {path: path.read_bytes() for path in paths}
    before = service.finance_controls_list({})
    advance(service, rule_id=OTHER)
    assert service.finance_controls_list({}) == before
    advance(service)
    fresh = FinanceStore(service.task, actor="manager")
    listing = fresh.finance_controls_list({})["controls"]
    assert listing[0]["result"]["status"] == "stale" and listing[0]["issue"]["blocking"]
    assert listing[1] == before["controls"][1]
    fresh.finance_controls_run({})
    successor = next(row for row in fresh.finance_controls_list({})["controls"] if row["control"].get("formula"))
    assert successor["state"] == "proposed" and successor["parent_id"] == saved[0]["id"]
    assert control_key(successor["control"]) == control_key(saved[0]["control"])
    assert not applies_to(decision, successor["result"])
    confirmed = fresh.finance_controls_confirm({"id": successor["id"]})
    fresh.finance_controls_run({"ids": [confirmed["id"]]})
    assert fresh.finance_controls_list({})["summary"]["blocking"] == 1
    assert all(path.read_bytes() == data for path, data in originals.items())


def vmp_draft(tmp_path):
    service = store(tmp_path, actor="manager")
    scope = {"ledger": "L2", "organization": "Engineering Co", "period": "2026-08", "currency": "CNY", "unit": "元"}
    rows = [{**scope, "product": product, "scenario": scenario, "quantity": quantity, "price": price, "quantity_unit": "件"}
            for product, scenario, quantity, price in [("P", "budget", "20", "7"), ("Q", "budget", "30", "11"),
                                                       ("P", "actual", "23", "8"), ("Q", "actual", "29", "10")]]
    path = tmp_path / "basket.json"
    path.write_text(json.dumps(rows))
    dataset = service.analysis.add_dataset(path, name="工程篮子")
    context = service.save_context({"bindings": {"basket": dataset["id"]}, "scopes": {"basket": scope}})
    requirement = service.analysis_requirements_save({"context_id": context["id"], "question": "量结构价差异",
        "items": [{"id": "vmp", "metric": "price_quantity", "dimensions": {"method": "volume_mix_price"}}]})
    run = service.explain_variance({"context_id": context["id"], "kind": "price_quantity", "method": "volume_mix_price",
                                    "actual_scenario": "actual", "baseline_scenario": "budget"})
    assert run["execution_status"] == "succeeded", run.get("error")
    facts = [fact for fact in service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
             if fact["column"] in {"total_variance", "volume_contribution", "mix_contribution", "price_contribution", "residual"}]
    claims = [{"basis": "calculation", "run_id": run["id"], "row": 0, "column": fact["column"], "value": fact["value"],
               "fact_id": fact["id"]} for fact in facts]
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join(f"{fact['column']}: {{{{fact:{fact['id']}}}}}" for fact in facts), "claims": claims})
    assert draft["completion"]["status"] == "complete", draft["completion"]
    return service, context, requirement, run, draft


def test_related_epoch_invalidates_current_receipt_without_rewriting_history_or_leaking_snapshots(tmp_path):
    service, context, requirement, run, draft = vmp_draft(tmp_path)
    archived = {path: path.read_bytes() for path in service.analysis.root.rglob("*.json") if path.name != "sequence.json"}
    initial = requirement_rule_identity(service.analysis, requirement)
    advance(service, rule_id=OTHER)
    assert service._readable_receipt(draft["completion"])["status"] == "complete"
    assert requirement_rule_identity(service.analysis, requirement) == initial
    advance(service)
    fresh = FinanceStore(service.task, snapshot_ids=context["bindings"].values(), session_id="reader")
    receipt = fresh._readable_receipt(draft["completion"])
    assert receipt["status"] == "awaiting_manager" and receipt["professional_reason"] == "professional_rules_changed"
    assert fresh._readable_draft(draft)["quality"]["status"] == "needs_attention"
    current = requirement_rule_identity(service.analysis, requirement)
    assert not artifact_rules_match(run, current)
    assert requirement_rule_identity(service.analysis, requirement, historical=True) == initial
    hidden = FinanceStore(service.task, snapshot_ids=[], session_id="reader")
    assert hidden._readable_receipt(draft["completion"]) is None
    assert requirement_rule_identity(service.analysis, requirement, allowed=set())["professional_status"] == "professional_context_unavailable"
    assert all(path.read_bytes() == data for path, data in archived.items())


def test_fresh_requirement_needs_a_fresh_native_calculation_after_epoch_change(tmp_path):
    from foundry.finance_requirements import check_requirements
    service, context, requirement, run, draft = vmp_draft(tmp_path)
    advance(service)
    updated = service.analysis_requirements_save({"parent_id": requirement["id"], "context_id": context["id"],
        "question": requirement["question"], "items": requirement["items"], "change_reason": "Review new rule epoch"})
    checked = check_requirements(service.analysis, {"requirements_id": updated["id"], "run_ids": [run["id"]],
                                                   "claims": draft["claims"]})
    assert checked["items"][0]["status"] == "pending"
    assert checked["items"][0]["professional_reason"] == "run_professional_rules_differ"
    fresh = service.explain_variance({"context_id": context["id"], "kind": "price_quantity", "method": "volume_mix_price",
                                     "actual_scenario": "actual", "baseline_scenario": "budget"})
    assert fresh["id"] != run["id"]
    assert fresh["professional_identity"]["rule_dependencies"] == [{"id": RULE, "version": 1, "epoch": 1}]
    facts = [fact for fact in service.prepare_explanation({"run_ids": [fresh["id"]]})["facts"]
             if fact["column"] in {"total_variance", "volume_contribution", "mix_contribution", "price_contribution", "residual"}]
    claims = [{"basis": "calculation", "run_id": fresh["id"], "row": 0, "column": fact["column"], "value": fact["value"],
               "fact_id": fact["id"]} for fact in facts]
    revised = service.save_explanation_draft({"requirements_id": updated["id"], "run_ids": [fresh["id"]],
        "body": "\n".join(f"{fact['column']}: {{{{fact:{fact['id']}}}}}" for fact in facts), "claims": claims})
    assert revised["completion"]["status"] == "complete", revised["completion"]
    assert service._readable_receipt(draft["completion"])["status"] != "complete"
