"""New drafts use the frozen ten-field content hash; historical eleven-field drafts stay put.

The scorer in tools/finance_professional_eval.py is not modified. These tests
bind the production writer to that scorer's field list and the 420 second default.
"""
import json
from pathlib import Path

import pytest

from foundry.analysis import _hash
from foundry.errors import FoundryError
from foundry.finance_completion import COMPLETION_POLICY_VERSION, completion_input_key
from foundry.fsutil import write_json_atomic
from test_finance_m05_completion_closure import authoring_spec, source_bound_case


# Same ten fields legal_workflow hashes. Do not add authorship here.
FROZEN_CONTENT_FIELDS = (
    "title", "requirements_id", "materiality", "body", "body_template", "document",
    "run_ids", "fact_ids", "claims", "limitations",
)
SCORER = Path(__file__).resolve().parents[1] / "tools" / "finance_professional_eval.py"


def frozen_content_hash(draft):
    return _hash({key: draft.get(key) for key in FROZEN_CONTENT_FIELDS})


def historical_eleven_field_hash(draft):
    payload = {key: draft.get(key) for key in FROZEN_CONTENT_FIELDS}
    authorship = draft.get("required_check_authorship")
    if authorship is not None:
        payload["required_check_authorship"] = authorship
    return _hash(payload)


def calculation_request(requirement, run, facts):
    return {
        "requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join(fact["column"] + ": {{fact:" + fact["id"] + "}}" for fact in facts),
        "claims": [{key: value for key, value in fact["reference_template"]["claim"].items()}
                   for fact in facts],
    }


def assert_frozen_binding(draft):
    assert draft.get("required_check_authorship"), "managed draft must keep service-owned authorship"
    assert draft["content_hash"] == frozen_content_hash(draft)
    assert draft["content_hash"] != historical_eleven_field_hash(draft)
    assert draft["check_policy_version"] == COMPLETION_POLICY_VERSION == 16
    assert draft["completion"]["draft_id"] == draft["id"]
    assert draft["completion"]["draft_content_hash"] == draft["content_hash"]
    assert draft["completion"]["status"] == "complete"


def test_managed_save_binds_frozen_ten_field_content_hash(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    saved = service.save_explanation_draft(calculation_request(requirement, run, facts))
    assert_frozen_binding(saved)


def test_prepared_template_save_binds_frozen_ten_field_content_hash(tmp_path):
    service, _, run, _, _ = source_bound_case(tmp_path)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    saved = service.save_explanation_draft(prepared["save_template_spec"])
    assert_frozen_binding(saved)


def test_managed_revision_binds_frozen_ten_field_content_hash(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    first = service.save_explanation_draft(calculation_request(requirement, run, facts))
    revised = service.save_explanation_draft({"parent_id": first["id"], "title": "显式新修订"})
    assert revised["id"] != first["id"]
    assert revised["parent_id"] == first["id"]
    assert_frozen_binding(revised)
    original = service.analysis._object_path("drafts", first["id"]).read_bytes()
    assert service.analysis.get_draft(first["id"])["content_hash"] == first["content_hash"]
    assert service.analysis._object_path("drafts", first["id"]).read_bytes() == original


def test_direct_legacy_save_omits_authorship_and_matches_ten_fields(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    draft = service.analysis.save_draft(authoring_spec(requirement, run, facts))
    assert "required_check_authorship" not in draft
    assert draft["content_hash"] == frozen_content_hash(draft)
    path = service.analysis._object_path("drafts", draft["id"])
    before = path.read_bytes()
    checked = service.validate_explanation({"draft_id": draft["id"]})
    delivered = service.save_explanation_draft({"draft_id": draft["id"]})
    assert checked["status"] == "pass"
    assert delivered["completion"]["status"] == "complete"
    assert delivered["completion"]["draft_content_hash"] == draft["content_hash"]
    assert path.read_bytes() == before


def test_same_content_distinct_drafts_keep_separate_receipts(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    spec = authoring_spec(requirement, run, facts)
    first = service.analysis.save_draft(spec)
    second = service.analysis.save_draft(spec)
    assert first["id"] != second["id"]
    assert first["content_hash"] == second["content_hash"] == frozen_content_hash(first)
    left = service.save_explanation_draft({"draft_id": first["id"]})
    right = service.save_explanation_draft({"draft_id": second["id"]})
    assert left["completion"]["id"] != right["completion"]["id"]
    assert left["completion"]["draft_id"] == first["id"]
    assert right["completion"]["draft_id"] == second["id"]
    assert left["completion"]["draft_content_hash"] == right["completion"]["draft_content_hash"] == first["content_hash"]
    completions = service.analysis._list("completions")
    assert [row["id"] for row in completions if row["draft_id"] == first["id"]] == [left["completion"]["id"]]
    assert [row["id"] for row in completions if row["draft_id"] == second["id"]] == [right["completion"]["id"]]


def _rebind_historical(path, mutate):
    record = json.loads(path.read_text())
    record.pop("_integrity_hash", None)
    mutate(record)
    record["_integrity_hash"] = _hash(record)
    write_json_atomic(path, record)
    return record


def test_historical_eleven_field_draft_is_not_migrated(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    request = calculation_request(requirement, run, facts)
    saved = service.save_explanation_draft(request)
    draft_path = service.analysis._object_path("drafts", saved["id"])
    receipt_path = service.analysis._object_path("completions", saved["completion"]["id"])
    historical = historical_eleven_field_hash(saved)
    assert historical != saved["content_hash"]

    def stamp_draft(record):
        record["content_hash"] = historical

    draft = _rebind_historical(draft_path, stamp_draft)

    def stamp_receipt(record):
        record["draft_content_hash"] = historical
        record["input_key"] = completion_input_key(
            record["chain_key"], draft, draft["explanation_check"], COMPLETION_POLICY_VERSION)

    _rebind_historical(receipt_path, stamp_receipt)
    draft_bytes = draft_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    export_root = service.analysis.root / "exports"
    export_before = sorted(path.relative_to(export_root).as_posix() for path in export_root.rglob("*") if path.is_file()) if export_root.exists() else []

    loaded = service.analysis.get_draft(saved["id"])
    assert loaded["content_hash"] == historical
    assert loaded["required_check_authorship"] == saved["required_check_authorship"]
    replay = service.save_explanation_draft(request)
    assert replay["id"] == saved["id"]
    assert replay["replayed"] is True
    assert replay["completion"]["id"] == saved["completion"]["id"]
    assert replay["completion"]["draft_content_hash"] == historical
    refreshed = service.save_explanation_draft({"draft_id": saved["id"]})
    assert refreshed["id"] == saved["id"]
    assert refreshed["content_hash"] == historical
    exported = service.analysis.export_draft(saved["id"], "md")
    assert exported["content_hash"] == historical
    again = service.analysis.export_draft(saved["id"], "md")
    assert again["sha256"] == exported["sha256"]
    assert draft_path.read_bytes() == draft_bytes
    assert receipt_path.read_bytes() == receipt_bytes
    assert json.loads(draft_bytes)["content_hash"] == historical
    assert export_before == []


def test_authorship_disk_rewrite_is_rejected_by_reader_or_semantics(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    saved = service.save_explanation_draft(calculation_request(requirement, run, facts))
    path = service.analysis._object_path("drafts", saved["id"])
    raw = json.loads(path.read_text())
    raw["required_check_authorship"]["authored_fact_ids"] = []
    path.write_text(json.dumps(raw))
    with pytest.raises(FoundryError, match="integrity"):
        service.analysis.get_draft(saved["id"])

    def empty_required(record):
        record["required_check_authorship"]["required_fact_ids"] = []

    _rebind_historical(path, empty_required)
    with pytest.raises(FoundryError, match="authorship"):
        service.validate_explanation({"draft_id": saved["id"]})


def test_receipt_cannot_be_rebound_to_another_draft(tmp_path):
    service, requirement, run, facts, _ = source_bound_case(tmp_path)
    spec = authoring_spec(requirement, run, facts)
    first = service.analysis.save_draft(spec)
    second = service.analysis.save_draft(spec)
    left = service.save_explanation_draft({"draft_id": first["id"]})
    path = service.analysis._object_path("completions", left["completion"]["id"])
    raw = json.loads(path.read_text())
    raw["draft_id"] = second["id"]
    path.write_text(json.dumps(raw))
    with pytest.raises(FoundryError, match="integrity"):
        service.analysis._get("completions", left["completion"]["id"])


def test_frozen_scorer_keeps_ten_fields_and_420_second_limit():
    source = SCORER.read_text()
    assert 'for k in ("title", "requirements_id", "materiality", "body", "body_template", "document", "run_ids", "fact_ids", "claims", "limitations")' in source
    assert 'parser.add_argument("--timeout-seconds", type=int, default=420)' in source
    assert "required_check_authorship" not in source.split("def legal_workflow", 1)[1].split("def verify_professional_v2", 1)[0]
