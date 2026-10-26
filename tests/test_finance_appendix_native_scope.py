"""Native appendix identity and qualification, using actual source-bound runs."""
from copy import deepcopy
import hashlib

import pytest

from foundry.finance_explanations import (
    _trusted_generated_appendix_regions,
    render_evidence_appendix,
)
from test_finance_runtime_ordering import task_bytes
from test_finance_statement_draft_template import statement  # noqa: F401


def _legacy_native_appendix(prepared):
    """The actual v1 rendering for this mixed opening/flow source fixture."""
    lines = ["## 计算依据"]
    for group in prepared["evidence_groups"]:
        assert group["closure"]["status"] == "unsupported"
        lines.append("\n### " + group["label"])
        for member in group["members"]:
            assert member["scope"]["period"] == "2026-11"
            lines.append(f"- {member['label']}（非可引用：未生成可核验事实）")
    return {"schema_version": 1, "body": "\n".join(lines), "fact_ids": [], "claims": []}


def _legacy_metadata(body, *, base_body=None):
    base = body if base_body is None else base_body
    return {"schema_version": 1, "render_version": 1,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "base_body_sha256": hashlib.sha256(base.encode()).hexdigest(),
            "body_chars": len(body)}


def test_native_appendix_resolves_output_period_without_qualifying_inputs(statement):  # noqa: F811
    service, _, _, _, _, prepared = statement
    before = deepcopy(prepared)
    qualified = {fact["id"] for fact in prepared["facts"]
                 if fact["evidence_eligibility"]["counts_as_amount_evidence"]}
    assert len(qualified) == 13 and len(prepared["facts"]) == 29
    assert all("period" not in fact["scope"] for fact in prepared["facts"])
    assert all(fact["metric_identity"]["period"] == "2026-11" for fact in prepared["facts"])
    appendix = render_evidence_appendix(prepared)
    assert set(appendix["fact_ids"]) == qualified
    assert {claim["fact_id"] for claim in appendix["claims"]} == qualified
    assert appendix["body"].count("；可引用金额") == 13
    assert appendix["body"].count("；不具金额引用资格") == 16
    assert "未生成可核验事实" not in appendix["body"]
    assert appendix["schema_version"] == 3
    assert prepared == before
    draft = service.save_explanation_draft(prepared["save_template_spec"])
    assert draft["quality"]["status"] == "pass", draft["quality"]["issues"]
    assert draft["completion"]["status"] == "complete"
    assert len(draft["claims"]) == 13
    assert draft["evidence_appendix_meta"]["render_version"] == 3
    assert len(_trusted_generated_appendix_regions(service.analysis, draft["body"], draft, prepared)) == 1


@pytest.mark.parametrize("mutation", ["period", "organization", "currency", "value", "fact_id", "unit", "run_id", "row",
                                      "column", "state", "display_value", "identity", "scope_conflict"])
def test_native_period_fallback_keeps_member_identity_checks(statement, mutation):  # noqa: F811
    _, _, _, _, _, prepared = statement
    changed = deepcopy(prepared)
    fact = next(f for f in changed["facts"] if f["evidence_eligibility"]["counts_as_amount_evidence"])
    group = next(g for g in changed["evidence_groups"] if fact["id"] in g["fact_ids"])
    member = next(m for m in group["members"] if m["fact_id"] == fact["id"])
    if mutation in {"period", "organization", "currency"}:
        member["scope"][mutation] = {"period": "2099-12", "organization": "Other Co", "currency": "USD"}[mutation]
    elif mutation == "run_id":
        group["run_id"] = "f" * 32
    elif mutation == "identity":
        fact["metric_identity"]["template_id"] = "untrusted-template"
    elif mutation == "scope_conflict":
        fact["scope"] = {**fact["scope"], "period": "2099-12"}
    else:
        member[mutation] = {"value": "999999", "fact_id": "f" * 64, "unit": "USD",
                            "row": 999, "column": "forged", "state": "missing",
                            "display_value": "999999 元"}[mutation]
    appendix = render_evidence_appendix(changed)
    assert fact["id"] not in appendix["fact_ids"]
    assert len(appendix["fact_ids"]) == 12
    assert "999999 元（已计算" not in appendix["body"]


def test_saved_v1_appendix_is_verified_readonly_and_tampering_is_rejected(statement, monkeypatch):  # noqa: F811
    import foundry.finance_service as service_module

    service, _, _, _, _, prepared = statement
    with monkeypatch.context() as legacy:
        legacy.setattr(service_module, "render_evidence_appendix", _legacy_native_appendix)
        legacy.setattr(service_module, "evidence_appendix_metadata", _legacy_metadata)
        draft = service.save_explanation_draft(prepared["save_template_spec"])
    assert draft["quality"]["status"] == "pass", draft["quality"]["issues"]
    assert draft["evidence_appendix_meta"]["render_version"] == 1
    assert draft["evidence_appendix"].count("未生成可核验事实") == 29
    before = task_bytes(service)
    checked = service.validate_explanation({"draft_id": draft["id"]})
    assert checked["status"] == "pass", checked["issues"]
    assert task_bytes(service) == before
    assert len(_trusted_generated_appendix_regions(service.analysis, draft["body"], draft, prepared)) == 1
    for mutation in ("body", "version", "hash"):
        forged = deepcopy(draft)
        if mutation == "body":
            forged["evidence_appendix"] += "\n- 伪造金额999999元"
            forged["body"] += "\n- 伪造金额999999元"
            forged["evidence_appendix_meta"] = _legacy_metadata(forged["evidence_appendix"])
        elif mutation == "version":
            forged["evidence_appendix_meta"]["render_version"] = 999
        else:
            forged["evidence_appendix_meta"]["body_sha256"] = "0" * 64
        assert _trusted_generated_appendix_regions(service.analysis, forged["body"], forged, prepared) == []
    assert task_bytes(service) == before
