"""Dense dictionaries preserve the complete model view before reporting overflow."""
import hashlib
import json

import pytest

from test_finance_runtime_payload import model_view, restore_table


def repeated_short_values():
    # Repeated identities are longer than reference tokens, but shorter than the
    # original dictionary threshold. No business case or monetary value is special.
    return {
        "rows": [{"source_id": f"12345678-1234-1234-1234-{i % 7:012d}",
                  "run_id": "87654321-4321-4321-4321-210987654321",
                  "ordinal": i, "value": str(i), "status": "source_verified"}
                 for i in range(600)],
        "issues": [{"code": "missing_source", "severity": "error", "value": "−0.00001"}],
        "failed_checks": [{"id": "cash_reconciliation", "status": "failed", "difference": "-60"}],
        "eligibility": {"counts_as_amount_evidence": False},
        "amount_strings": ["9007199254740993", "0.123456789012345678901", "-0", "1e-400"],
    }


@pytest.mark.parametrize("tool", ["prepare_explanation", "finance_scenario_run", "save_explanation_draft"])
def test_dense_dictionary_preserves_complete_payload_and_final_response(tool):
    data = repeated_short_values()
    if tool == "save_explanation_draft":
        data.update(id="draft-1", run_ids=["run-1"], body="Unapproved draft remains unapproved",
                    claims=[], final_response="本稿仍待修正；不得据此宣称完成。",
                    quality={"status": "needs_attention", "status_dimensions": {"numeric_citation": "failed"}},
                    completion={"status": "repair_available"})
    raw = json.dumps(data, ensure_ascii=False)
    text = model_view(tool, raw)
    packet = json.loads(text)
    assert len(text.encode()) <= 48000
    assert packet.get("_model_projection", {}).get("full_result") is True
    assert packet["_model_projection"]["lossless"] is True
    assert packet["_model_projection"]["omitted_paths"] == []
    assert packet["_model_projection"]["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    restored = restore_table(packet)
    assert restored == data
    assert all(isinstance(value, str) for value in restored["amount_strings"])
    assert restored["eligibility"]["counts_as_amount_evidence"] is False
    assert restored["failed_checks"][0]["status"] == "failed"
    if tool == "save_explanation_draft":
        assert restored["final_response"] == data["final_response"]
        assert restored["completion"]["status"] == "repair_available"


@pytest.mark.parametrize("number", ["9007199254740993", "1e400", "1e-400", "0.123456789012345678901", "-0"])
def test_dense_candidate_never_rounds_unsafe_numeric_literals(number):
    raw = json.dumps(repeated_short_values())[:-1] + ', "unsafe":' + number + '}'
    response = json.loads(model_view("prepare_explanation", raw))
    assert response["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE"
    assert response["model_view_complete"] is False
    assert "unsafe" not in response
    assert response["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()


@pytest.mark.parametrize("reserved", ["$r", "$v", "$foundry_ref", "_model_projection"])
def test_dense_candidate_rejects_reserved_keys_without_interpreting_them(reserved):
    data = repeated_short_values()
    data["source_supplied"] = {reserved: [0, []]}
    raw = json.dumps(data)
    response = json.loads(model_view("prepare_explanation", raw))
    assert response["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE"
    assert response["model_view_complete"] is False
    assert response["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()


def test_irreducible_overflow_stays_explicit_and_small_result_unchanged():
    small = '{"value":"-60","counts_as_amount_evidence":false}'
    assert model_view("prepare_explanation", small) == small
    raw = json.dumps({"detail": "a" * 60000, "value": "-60"})
    response = json.loads(model_view("prepare_explanation", raw))
    assert response["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE"
    assert response["model_view_complete"] is False
    assert response["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
