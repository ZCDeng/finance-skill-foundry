"""A label change cannot qualify referenced native-template input amounts."""
import pytest

from test_finance_statement_draft_template import statement  # noqa: F401


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("metric,label", [
    ("opening_receivables", "期初应收"),
    ("customer_receipts", "客户收款合计"),
    ("revenue", "本期确认收入"),
    ("closing_restricted_cash", "期末受限"),
])
def test_optional_input_reference_cannot_bypass_qualification_by_wording(statement, short, metric, label):  # noqa: F811
    service, _, _, _, run, prepared = statement
    source = next(f for f in prepared["facts"] if f["semantics"]["metric"] == metric)
    assert source["evidence_eligibility"]["counts_as_amount_evidence"] is False
    extra = label + " {{fact:" + source["id"] + "}}。"
    spec = dict(prepared["save_template_spec"] if short else prepared["draft_template"])
    if short:
        spec["qualitative_note"] = extra
    else:
        spec["body"] += "\n\n" + extra
    saved = service.save_explanation_draft(spec)
    issue, = [i for i in saved["quality"]["issues"]
              if i["code"] == "fact_amount_evidence_ineligible" and i["fact_id"] == source["id"]]
    assert issue["expected_metric"] == metric
    assert issue["reason_codes"] == ["unregistered_financial_semantics"]
    assert saved["quality"]["status"] == "needs_attention"
    assert saved["completion"]["status"] != "complete"
    assert all(i["status"] == "answered" for i in saved["quality"]["requirements"]["items"])
    current = service.prepare_explanation({"run_ids": [run["id"]], "fact_view": "inspection"})
    assert next(f for f in current["facts"] if f["id"] == source["id"])["evidence_eligibility"] == source["evidence_eligibility"]
    fixed = service.save_explanation_draft({**current["save_template_spec"], "parent_id": saved["id"]})
    assert fixed["quality"]["status"] == "pass"
    assert fixed["completion"]["status"] == "complete"


@pytest.mark.parametrize("basis", ["source_fact", "user_assumption", "professional_judgment"])
@pytest.mark.parametrize("with_fact_id", [False, True])
@pytest.mark.parametrize("wrong_value", [False, True])
def test_native_cell_cannot_change_qualification_by_renaming_its_claim_basis(statement, basis, with_fact_id, wrong_value):  # noqa: F811
    from copy import deepcopy
    from foundry.finance_explanations import saved_claim_semantic_issues

    service, _, _, _, _, prepared = statement
    source = next(f for f in prepared["facts"] if f["semantics"]["metric"] == "revenue")
    claim = {key: source[key] for key in ("run_id", "row", "column", "value")}
    claim.update(basis=basis, reason="caller category label")
    if with_fact_id:
        claim["fact_id"] = source["id"]
    if wrong_value:
        claim["value"] = "999999"
    # No token and no explicit fact_ids for this additional cell: only its
    # claimed basis changed. The server still resolves the native cell identity.
    spec = {**prepared["draft_template"], "claims": [claim]}
    spec["body"] += "\n\n输入金额 " + source["value"] + "。"
    saved = service.save_explanation_draft(spec)
    assert any(i["code"] == "fact_amount_evidence_ineligible" and i["fact_id"] == source["id"]
               for i in saved["quality"]["issues"])
    assert saved["completion"]["status"] != "complete"
    if wrong_value:
        assert any(i["code"] == "fact_claim_mismatch" and i["fact_id"] == source["id"]
                   for i in saved["quality"]["issues"])
    historical = deepcopy(saved)
    historical["explanation_check"] = {"claim_semantics_version": 7}
    historical["fact_ids"] = [key for key in historical["fact_ids"] if key != source["id"]]
    before = deepcopy(historical)
    issues = saved_claim_semantic_issues(service.analysis, historical)
    assert any(i["code"] == "fact_amount_evidence_ineligible" and i["fact_id"] == source["id"] for i in issues)
    assert historical == before
