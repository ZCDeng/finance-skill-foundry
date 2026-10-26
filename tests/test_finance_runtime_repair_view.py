"""Repair guidance is a bound view of a failed save, never a new completion grant."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from test_finance_runtime_payload import ROOT, model_view, restore_table
from test_finance_terminal_delivery import residual, terminal_save


def repair_save():
    saved = terminal_save()
    saved["completion"].update(status="repair_available", repair_allowed=True,
                               repair_attempts=0, max_repairs=2, stop_reason=None)
    saved["completion_operation"].update(status="repair_available")
    saved["delivery_contract"]["completion_status"] = "repair_available"
    requirements = saved["quality"]["requirements"]
    requirements["requirements_id"] = "req-current"
    requirements["support"].update(
        preflight={"requirements_before_execution": True,
                   "required_bindings": {"ledger": "snap-ledger", "public_facts": "snap-context"},
                   "finance_context_status": "missing",
                   "context_binding_diagnostic": {"missing_aliases": ["public_facts"]}},
        items=[{"id": "actual-account", "metric": "其他应收款",
                "execution_specs": [{"tool": "run_metric", "spec": {"metric": {
                    "kind": "account_total", "accounts": ["其他应收款"]}},
                    "requires_context_id": True,
                    "required_bindings": {"ledger": "snap-ledger", "public_facts": "snap-context"},
                    "status": "blocked", "blockers": ["finance_context_missing"],
                    "after": ["cite_all_amount_rows", "drilldown_fact_each"]}],
                "metric_identity_diagnostic": {"status": "actual_ledger_account"}}])
    saved["completion"]["actions"] = [{"code": "requirements_run_outdated", "run_ids": ["run-old"],
                                      "fixups": [{"code": "repin_requirements",
                                                  "requirements_id": "req-current"}]}]
    saved["explanation_check"] = deepcopy(saved["quality"])
    return saved


def test_repair_view_keeps_current_diagnostics_and_executable_server_specs():
    saved = repair_save()
    raw = json.dumps(saved, ensure_ascii=False)
    text = model_view("save_explanation_draft", raw)
    packet = json.loads(text)
    meta = packet["_model_projection"]
    step = meta["next_action"]
    assert step["kind"] == "repair_current_draft"
    assert step["saved_requirements_id"] == "req-1"
    assert step["requirements_id"] == "req-current"
    assert step["parent_id"] == "draft-1" and step["receipt_id"] == "receipt-1"
    assert step["saved_run_ids"] == ["run-1"]
    assert step["repair_budget"] == {"used": 0, "limit": 2, "remaining": 2}
    assert step["deadline_at"] == saved["completion_operation"]["deadline_at"]
    assert "same" in step["instruction"] and "prepare_explanation" in step["instruction"]
    assert "execution_specs" in step["instruction"]
    assert "public_facts" in text and "req-current" in text
    assert meta["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    decoded = restore_table(packet)
    expected = residual(saved, meta["omitted_paths"])
    assert decoded == expected
    for key in ("requirements", "recognition_basis", "recognition_basis_version"):
        assert decoded["quality"][key] == expected["quality"][key]
    assert decoded["unknown_qualification"] == saved["unknown_qualification"]
    assert decoded["completion"]["original_requirements_completed"] is False
    assert packet["receipt"]["completion"]["actions"] == saved["completion"]["actions"]
    assert len(text.encode()) < len(raw.encode()) * .55


def test_real_native_save_repair_keeps_original_requirements_until_new_save(tmp_path):
    from foundry.finance_completion_operations import CompletionOperationStore
    from foundry.finance_service import FinanceStore
    from test_finance_performance_semantics import performance_case

    service, _, requirement, run = performance_case(tmp_path)
    service.task.record_session("runtime-repair-native", role="analysis")
    service = FinanceStore(service.task, session_id="runtime-repair-native")
    operation = CompletionOperationStore(service.task, service.session_id).begin("runtime-repair-request")
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    bad = service.save_completion_draft(operation["id"], "repair-save-1",
                                      {**prepared["save_template_spec"], "qualitative_note": "边界值为0。"})
    assert bad["completion"]["status"] == "repair_available"
    raw = json.dumps(bad, ensure_ascii=False)
    (tmp_path / "actual-bad-save.json").write_text(raw)
    packet = json.loads(model_view("save_explanation_draft", raw))
    step = packet["_model_projection"]["next_action"]
    assert step["requirements_id"] == requirement["id"]
    assert step["saved_run_ids"] == [run["id"]]
    assert step["repair_budget"] == {"used": 0, "limit": 2, "remaining": 2}
    assert step["deadline_at"] == bad["completion_operation"]["deadline_at"]
    assert any(issue["code"] == "uncited_number" for issue in packet["receipt"]["quality"]["issues"])
    requirements = restore_table(packet)["quality"]["requirements"]
    assert requirements["support"]["preflight"]["required_bindings"]
    assert requirements["support"] == residual(bad, packet["_model_projection"]["omitted_paths"])["quality"]["requirements"]["support"]
    prepared_again = service.prepare_explanation({"run_ids": [run["id"]]})
    good = service.save_completion_draft(operation["id"], "repair-save-2",
                                       {**prepared_again["save_template_spec"], "parent_id": bad["id"]})
    assert good["requirements_id"] == requirement["id"] and good["run_ids"] == [run["id"]]
    assert good["completion"]["status"] == "complete"
    assert good["completion"]["repair_attempts"] == 1
    stopped = json.loads(model_view("save_explanation_draft", json.dumps(good, ensure_ascii=False)))
    assert stopped["_model_projection"]["next_action"]["kind"] == "final_response_only"
    assert stopped["_model_projection"]["next_action"]["text"] == good["final_response"]


def test_ordinary_manager_save_has_no_runtime_repair_direction():
    saved = repair_save()
    saved.pop("completion_operation")
    saved.pop("completion_operation_id")
    saved.pop("completion_operation_revision")
    packet = json.loads(model_view("save_explanation_draft", json.dumps(saved, ensure_ascii=False)))
    assert "next_action" not in packet.get("_model_projection", {})


def test_small_valid_repair_still_returns_a_bounded_recovery_direction():
    saved = repair_save()
    saved["quality"] = {"status": "needs_attention", "status_dimensions": {"coverage": "needs_attention"},
                        "issues": [], "readability": {"issues": []},
                        "claim_semantics_version": saved["quality"]["claim_semantics_version"],
                        "requirements": {"requirements_id": "req-current"}}
    for key in ("explanation_check", "body", "body_template", "claims", "unknown_qualification"):
        saved.pop(key)
    saved["completion_operation"]["revisions"] = []
    raw = json.dumps(saved, ensure_ascii=False)
    packet = json.loads(model_view("save_explanation_draft", raw))
    assert packet["_model_projection"]["next_action"]["kind"] == "repair_current_draft"
    assert len(json.dumps(packet, ensure_ascii=False).encode()) <= 48000


@pytest.mark.parametrize("mutation", ["task", "operation", "revision", "hash", "contract", "deadline",
                                      "exhausted", "policy", "missing_current", "not_repair", "completed"])
def test_conflicting_or_exhausted_snapshot_has_no_repair_direction(mutation):
    saved = repair_save()
    if mutation == "task":
        saved["completion"]["task_id"] = "other-task"
    elif mutation == "operation":
        saved["completion_operation"]["id"] = "old-operation"
    elif mutation == "revision":
        saved["completion_operation"]["current_revision"] = 0
    elif mutation == "hash":
        saved["completion"]["draft_content_hash"] = "old-hash"
    elif mutation == "contract":
        saved["delivery_contract"]["completion_status"] = "complete"
    elif mutation == "deadline":
        saved["completion_operation"]["deadline_at"] = "unknown"
    elif mutation == "exhausted":
        saved["completion"]["repair_attempts"] = 2
    elif mutation == "policy":
        saved["completion_operation"]["policy"]["max_repairs"] = 3
    elif mutation == "missing_current":
        saved["quality"]["requirements"].pop("requirements_id")
    elif mutation == "not_repair":
        saved["completion"]["repair_allowed"] = False
    else:
        saved["completion"]["original_requirements_completed"] = True
    packet = json.loads(model_view("save_explanation_draft", json.dumps(saved, ensure_ascii=False)))
    assert "next_action" not in packet.get("_model_projection", {})


def test_actual_tool_render_preserves_full_persisted_result():
    raw = json.dumps(repair_save(), ensure_ascii=False)
    script = r'''
import fs from 'node:fs';
import {definitions} from './dsh-plugin/analysis.js';
const raw=fs.readFileSync(0,'utf8');
const tool=definitions(undefined,async()=>raw).find(t=>t.name==='save_explanation_draft');
const value=await tool.execute({spec:{body:'draft',run_ids:['run-1']}},{agent:{id:'session-1'}});
process.stdout.write(JSON.stringify({value,content:tool.output.render({},value)}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            input=raw, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["value"]["stdout"] == raw
    packet = json.loads(report["content"][0]["text"])
    assert packet["_model_projection"]["next_action"]["requirements_id"] == "req-current"


def test_guidance_frontloads_registration_context_and_supported_native_paths():
    script = "import {definitions} from './dsh-plugin/analysis.js';process.stdout.write(JSON.stringify(Object.fromEntries(definitions().map(t=>[t.name,t.description]))));"
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    descriptions = json.loads(result.stdout)
    registration = descriptions["analysis_requirements_save"]
    assert "诊断" in registration and "scope.purpose" in registration and "question" in registration
    assert "preflight" in registration and "execution_specs" in registration
    assert "public_facts" in descriptions["finance_context_save"]
    assert "accounts" in descriptions["run_metric"] and "control_totals" in descriptions["run_metric"]
    assert "相同 run_ids" in descriptions["save_explanation_draft"]
    prompt = (ROOT / "dsh-plugin/presets/analysis/agent.cordis.yml").read_text()
    assert "诊断之前" in prompt and "scope.purpose" in prompt
    assert "public_facts" in prompt and "execution_specs" in prompt
    assert "result_key_columns" in prompt and "group_by" in prompt and ":period" in prompt


@pytest.mark.parametrize("path", ["finance-tools.js", "model-result.js", "final-delivery-runtime.js",
                                  "presets/analysis/agent.cordis.yml"])
def test_plugin_resource_mirrors_are_exact(path):
    assert (ROOT / "dsh-plugin" / path).read_bytes() == (ROOT / "foundry/resources/dsh-plugin" / path).read_bytes()
