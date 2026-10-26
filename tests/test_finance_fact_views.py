"""Writing views partition native roles without changing amount eligibility."""
from copy import deepcopy
import hashlib

import pytest

from foundry.errors import FoundryError
from foundry.finance_driver_templates import OUTPUT_SEMANTICS, TEMPLATE_INPUTS
from foundry.finance_explanations import prepare_explanation as full_preparation
from foundry.finance_explanations import render_evidence_appendix
from foundry.finance_locators import fact_index_dir
from foundry.finance_service import FinanceStore
from test_finance_professional_protocol import _template_case


@pytest.fixture
def native(tmp_path):
    return _template_case(tmp_path)


def test_default_writing_view_is_lossless_partition_of_full_native_catalog(native):
    service, _, _, run = native
    original = full_preparation(service.analysis, [run])
    before = deepcopy(original)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    assert prepared["schema_version"] == 2
    assert prepared["fact_view"] == "writing"
    assert len(prepared["facts"]) == 13
    assert len(prepared["input_facts"]) == 16
    assert {f["semantics"]["metric"] for f in prepared["facts"]} == set(OUTPUT_SEMANTICS)
    assert {f["semantics"]["metric"] for f in prepared["input_facts"]} == set(TEMPLATE_INPUTS)
    assert not ({f["id"] for f in prepared["facts"]} & {f["id"] for f in prepared["input_facts"]})
    assert {f["id"]: f for f in prepared["facts"] + prepared["input_facts"]} == {
        f["id"]: f for f in original["facts"]}
    assert all(not f["evidence_eligibility"]["counts_as_amount_evidence"] for f in prepared["input_facts"])
    assert original == before
    for key in original.keys() - {"schema_version", "facts"}:
        assert prepared[key] == original[key]
    assert all((fact_index_dir(service) / (f["id"] + ".json")).is_file()
               for f in original["facts"])
    locator = service.open_source_locator({"fact_id": prepared["input_facts"][0]["id"]})
    assert locator["status"] != "locator_forbidden"


def test_inspection_view_explicitly_preserves_all_native_facts(native):
    service, _, _, run = native
    prepared = service.prepare_explanation({"run_ids": [run["id"]], "fact_view": "inspection"})
    assert prepared["schema_version"] == 2 and prepared["fact_view"] == "inspection"
    assert len(prepared["facts"]) == 29
    assert len(prepared["input_facts"]) == 16
    assert prepared["facts"] == full_preparation(service.analysis, [run])["facts"]


@pytest.mark.parametrize("view", [None, "all", 1, {}, []])
def test_invalid_view_is_rejected_before_fact_index_writes(native, view):
    service, _, _, run = native
    before = set(fact_index_dir(service).glob("*.json"))
    with pytest.raises(FoundryError, match="fact_view"):
        service.prepare_explanation({"run_ids": [run["id"]], "fact_view": view})
    assert set(fact_index_dir(service).glob("*.json")) == before


def test_unapproved_outputs_remain_visible_and_cannot_complete(tmp_path):
    service, _, requirement, run = _template_case(tmp_path, confirm=False, approve_boundaries=False)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    assert len(prepared["facts"]) == 13 and len(prepared["input_facts"]) == 16
    assert all(f["evidence_eligibility"]["counts_as_amount_evidence"] is False for f in prepared["facts"])
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join("{{fact:" + f["id"] + "}}" for f in prepared["facts"])})
    assert draft["quality"]["status"] != "pass"
    assert draft["completion"]["status"] != "complete"


@pytest.mark.parametrize("view", ["writing", "inspection"])
def test_restricted_reader_cannot_obtain_either_view(native, view):
    service, _, _, run = native
    restricted = FinanceStore(service.task, snapshot_ids=[], session_id="fact-view-narrow-reader")
    with pytest.raises(FoundryError):
        restricted.prepare_explanation({"run_ids": [run["id"]], "fact_view": view})


def test_all_input_claims_still_fail_while_writing_outputs_complete(native):
    service, _, requirement, run = native
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    spec = {"requirements_id": requirement["id"], "run_ids": [run["id"]]}
    body = "\n".join("{{fact:" + f["id"] + "}}" for f in prepared["facts"])
    good = service.save_explanation_draft({**spec, "body": body})
    assert good["completion"]["status"] == "complete"
    all_facts = prepared["facts"] + prepared["input_facts"]
    bad = service.save_explanation_draft({**spec, "parent_id": good["id"],
        "body": "\n".join("{{fact:" + f["id"] + "}}" for f in all_facts)})
    assert bad["completion"]["status"] != "complete"
    issues = [i for i in bad["quality"]["issues"] if i["code"] == "fact_amount_evidence_ineligible"]
    assert {i["fact_id"] for i in issues} == {f["id"] for f in prepared["input_facts"]}
    assert len(service.analysis.get_draft(bad["id"])["claims"]) == 29


def test_internal_save_explicitly_uses_inspection_view(native, monkeypatch):
    service, _, _, run = native
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    calls = []
    original = service.prepare_explanation

    def observe(spec):
        calls.append(deepcopy(spec))
        return original(spec)

    monkeypatch.setattr(service, "prepare_explanation", observe)
    saved = service.save_explanation_draft(prepared["save_template_spec"])
    assert saved["completion"]["status"] == "complete"
    assert calls and all(call["fact_view"] == "inspection" for call in calls)
    base = render_evidence_appendix(full_preparation(service.analysis, [run]))["body"]
    assert saved["evidence_appendix"].startswith(base)
    assert saved["evidence_appendix_meta"]["base_body_sha256"] == hashlib.sha256(base.encode()).hexdigest()


@pytest.mark.parametrize("mutation", ["engine", "template", "version", "source_role", "column", "row_index"])
def test_partition_does_not_trust_names_or_client_eligibility(native, mutation):
    from foundry.finance_explanation_views import explanation_fact_view

    service, _, _, native_run = native
    run = deepcopy(native_run)
    prepared = full_preparation(service.analysis, [run])
    source = next(f for f in prepared["facts"] if f["semantics"]["metric"] == "revenue")
    if mutation == "engine":
        run["engine"] = "sql"
    elif mutation == "template":
        run["result"]["template_id"] = "unregistered_template"
    elif mutation == "version":
        run["result"]["template_version"] = 999
    elif mutation == "source_role":
        run["result"]["rows"][source["row"]]["metric_key"] = "net_income"
    elif mutation == "column":
        source["column"] = "unregistered_cell"
    else:
        source["row"] = True
    result = explanation_fact_view(prepared, [run], "writing")
    assert source in result["facts"]
    assert source not in result["input_facts"]
    assert source["evidence_eligibility"]["counts_as_amount_evidence"] is False


def test_projection_does_not_mutate_or_filter_by_eligibility(native):
    from foundry.finance_explanation_views import explanation_fact_view

    service, _, _, run = native
    full = full_preparation(service.analysis, [run])
    before = deepcopy(full)
    projected = explanation_fact_view(full, [run], "writing")
    assert full == before
    # Projection must depend on native roles, not a caller-supplied flag.
    for fact in full["facts"]:
        fact["evidence_eligibility"]["counts_as_amount_evidence"] = not fact["evidence_eligibility"]["counts_as_amount_evidence"]
    inverted = explanation_fact_view(full, [run], "writing")
    assert [f["id"] for f in projected["facts"]] == [f["id"] for f in inverted["facts"]]
    assert len(inverted["facts"]) == 13 and len(inverted["input_facts"]) == 16
