"""Eleven-field approval gap. Ledger B. The original seven-field mutation contract stays elsewhere."""
import pytest

from foundry.errors import FoundryError
from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS, rule_identity
from foundry.finance_service import FinanceStore
from test_finance_professional_protocol import _profile_case


FULL = sorted(BASE_FIELDS | STANDARD_FIELDS)


def test_status_shows_the_seven_field_gap_and_a_new_eleven_field_event_keeps_the_old_bytes(tmp_path):
    service, context = _profile_case(tmp_path)
    old = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS)})
    path = service._path("profile_confirmations", old["id"])
    before = path.read_bytes()
    status = service.finance_profile_status({"context_id": context["id"]})
    gap = status["profile_gap"]
    assert status["professional_status"] == "awaiting_profile_confirmation"
    assert set(gap["approved_fields"]) == BASE_FIELDS
    assert set(gap["missing_fields"]) == STANDARD_FIELDS
    assert gap["stale_fields"] == []
    assert gap["current_values"]["basis"] == "management"
    assert gap["current_values"]["basis_version"] == "management-v1"
    assert gap["approval_basis"]["task_id"] == service.task.id
    assert gap["approval_basis"]["bindings"] == context["bindings"]
    assert gap["confirmation_id"] == old["id"]
    assert "profile_gap" not in rule_identity(service, context, ["driver.source_binding"])

    fresh = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": FULL})
    assert fresh["id"] != old["id"]
    assert path.read_bytes() == before
    current = service.finance_profile_status({"context_id": context["id"]})
    assert current["professional_status"] == "supported"
    assert current["profile_gap"]["missing_fields"] == []
    assert set(current["profile_gap"]["approved_fields"]) == set(FULL)
    assert current["profile_gap"]["confirmation_id"] == fresh["id"]


def test_value_change_scope_expansion_and_revocation_drop_current_approval_only(tmp_path):
    service, context = _profile_case(tmp_path)
    approval = service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": FULL})
    path = service._path("profile_confirmations", approval["id"])
    before = path.read_bytes()
    changed = service.save_context({
        "parent_id": context["id"], "bindings": context["bindings"], "scopes": context["scopes"],
        "reporting_profile": {**context["reporting_profile"], "entity_scope": "O1 and O2"},
    })
    gap = service.finance_profile_status({"context_id": changed["id"]})["profile_gap"]
    assert "entity_scope" in gap["stale_fields"]
    assert "entity_scope" in gap["missing_fields"]
    assert gap["current_values"]["entity_scope"] == "O1 and O2"
    assert rule_identity(service, changed, ["variance.volume_mix_price"])["professional_status"] == "supported"

    service.finance_profile_revoke({"id": approval["id"], "reason": "范围扩大后原批准失效"})
    revoked = service.finance_profile_status({"context_id": context["id"]})
    assert revoked["professional_status"] == "awaiting_profile_confirmation"
    assert revoked["profile_gap"]["approved_fields"] == []
    assert revoked["profile_gap"]["confirmation_status"] == "revoked"
    assert path.read_bytes() == before
    assert rule_identity(service, context, ["cash.collection_screen"])["professional_status"] == "supported"


def test_assistant_cannot_fill_confirmed_fields(tmp_path):
    service, context = _profile_case(tmp_path)
    assistant = FinanceStore(service.task)
    with pytest.raises(FoundryError, match="manager"):
        assistant.finance_profile_confirm({
            "context_id": context["id"], "confirmed_fields": FULL, "confirmed_by": "manager", "status": "confirmed",
        })
    assert service._list("profile_confirmations") == []
