"""A stopped save needs an exact reply, never a bookkeeping tool after the save."""
from copy import deepcopy
import hashlib
import json

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from test_finance_runtime_payload import ROOT, model_view, restore_table


def terminal_save():
    evidence = [{"fact_id": f"fact-{i}", "source": f"archived-{i}",
                 "note": f"Evidence {i}: " + "source detail " * 24} for i in range(38)]
    quality = {
        "status": "needs_attention", "claim_semantics_version": CLAIM_SEMANTICS_VERSION,
        "issues": [{"code": "requirement_unanswered", "severity": "warning", "text": "数量与价格待补",
                    "position": 7, "details": {"counts_as_amount_evidence": False}}],
        "readability": {"issues": []}, "status_dimensions": {"coverage": "needs_attention"},
        "recognition_basis_version": 1,
        "recognition_basis": {
            "version": 1, "status": "insufficient",
            "missing_fields": ["service_direction", "economic_nature"],
            "sources": [{"dataset_id": "source-1", "source_hash": "source-hash",
                         "source_rows": [1], "facts": {"service_completed": "yes"},
                         "missing_fields": ["service_direction", "economic_nature"]}],
            "counts_as_amount_evidence": False, "posting_authorized": False,
            "qualification": "qualitative_service_basis_only",
        },
        "requirements": {"status": "needs_attention", "items": [{"id": "pq", "status": "pending",
                                                                       "requires_drilldown": True, "drilldown_status": "missing"}],
                         "support": {"supported_metrics": evidence, "blocked_evidence": [
                             {"code": "price_quantity_missing", "binding": "source"}]}},
        "facts": evidence, "evidence_groups": evidence, "evidence_labels": evidence,
        "evidence_posture": {"publication_authorized": False},
        "dataset_freshness": {"status": "current"},
    }
    return {
        "id": "draft-1", "task_id": "task-1", "requirements_id": "req-1", "run_ids": ["run-1"],
        "content_hash": "content-1", "body": "需要数量和单价资料。", "body_template": "需要数量和单价资料。",
        "claims": [], "fact_ids": ["fact-1"], "quality": quality, "explanation_check": deepcopy(quality),
        "completion_operation_id": "operation-1", "completion_operation_revision": 2,
        "completion": {"id": "receipt-1", "draft_id": "draft-1", "task_id": "task-1",
                       "draft_content_hash": "content-1", "requirements_id": "req-1",
                       "status": "awaiting_input", "repair_allowed": False,
                       "stop_reason": "verified_input_gap", "original_requirements_completed": False,
                       "actions": [{"code": "missing_input", "message": "请补充数量与单价"}]},
        "completion_operation": {"id": "operation-1", "task_id": "task-1", "session_id": "session-1",
                                 "current_revision": 2, "status": "awaiting_input",
                                 "deadline_at": "2026-10-26T12:00:00Z", "policy": {"max_repairs": 2},
                                 "revisions": [{"status": "needs_review", "payload": evidence}]},
        "final_response": "草稿已保存；数量与单价资料待补，原量价要求仍未完成。",
        "delivery_contract": {"draft_id": "draft-1", "receipt_id": "receipt-1",
                              "completion_status": "awaiting_input"},
        "unknown_qualification": {"status": "unverified", "amount": "9007199254740993"},
    }


def residual(data, omitted):
    expected = deepcopy(data)
    for pointer in omitted:
        target = expected
        parts = pointer[1:].split("/")
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        del target[parts[-1]]
    return expected


def test_terminal_save_projects_exact_reply_and_keeps_every_current_diagnostic():
    saved = terminal_save()
    raw = json.dumps(saved, ensure_ascii=False)
    packet = json.loads(model_view("save_explanation_draft", raw))
    meta = packet["_model_projection"]
    assert meta["schema"] == "foundry.model-result.v2"
    assert meta["lossless"] is False and meta["full_result"] is False
    assert meta["next_action"]["kind"] == "final_response_only"
    assert meta["next_action"]["text"] == saved["final_response"]
    assert "todo_write" in meta["next_action"]["instruction"]
    assert meta["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    decoded = restore_table(packet)
    assert decoded == residual(saved, meta["omitted_paths"])
    for key in ("issues", "requirements", "status_dimensions", "readability", "evidence_posture",
                "dataset_freshness", "recognition_basis_version", "recognition_basis"):
        expected = residual(saved, meta["omitted_paths"])["quality"][key]
        assert decoded["quality"][key] == expected
    assert decoded["completion"] == saved["completion"]
    assert decoded["completion"]["original_requirements_completed"] is False
    assert decoded["quality"]["requirements"]["items"][0]["drilldown_status"] == "missing"
    assert decoded["quality"]["recognition_basis"]["missing_fields"] == ["service_direction", "economic_nature"]
    assert decoded["quality"]["recognition_basis"]["posting_authorized"] is False
    assert decoded["completion_operation"]["deadline_at"] == saved["completion_operation"]["deadline_at"]
    assert decoded["completion_operation"]["policy"] == {"max_repairs": 2}
    assert decoded["unknown_qualification"] == saved["unknown_qualification"]
    assert packet["receipt"]["final_response"] == saved["final_response"]
    assert len(json.dumps(packet, ensure_ascii=False).encode()) < len(raw.encode()) * .40


@pytest.mark.parametrize("mutation", ["repair_allowed", "repair_available", "wrong_operation", "wrong_revision",
                                      "wrong_draft", "wrong_status", "wrong_content", "no_final_response"])
def test_repair_or_conflicting_save_does_not_receive_terminal_direction(mutation):
    saved = terminal_save()
    if mutation == "repair_allowed":
        saved["completion"]["repair_allowed"] = True
    elif mutation == "repair_available":
        saved["completion"]["status"] = "repair_available"
    elif mutation == "wrong_operation":
        saved["completion_operation"]["id"] = "old-operation"
    elif mutation == "wrong_revision":
        saved["completion_operation"]["current_revision"] = 1
    elif mutation == "wrong_draft":
        saved["completion"]["draft_id"] = "old-draft"
    elif mutation == "wrong_status":
        saved["delivery_contract"]["completion_status"] = "complete"
    elif mutation == "wrong_content":
        saved["completion"]["draft_content_hash"] = "old-content"
    else:
        saved.pop("final_response")
    packet = json.loads(model_view("save_explanation_draft", json.dumps(saved, ensure_ascii=False)))
    assert "next_action" not in packet.get("_model_projection", {})


def test_terminal_reply_guidance_preserves_repair_path_and_bookkeeping_order():
    prompt = (ROOT / "dsh-plugin/presets/analysis/agent.cordis.yml").read_text()
    assert "如使用 todo_write" in prompt and "最终保存前" in prompt
    assert "不是 response_status" in prompt
    assert "原样回复 final_response" in prompt
    assert "终态之后禁止 todo_write" in prompt
    assert "completion.repair_allowed 为真" in prompt
    mirror = ROOT / "foundry/resources/dsh-plugin/presets/analysis/agent.cordis.yml"
    assert mirror.read_text() == prompt
