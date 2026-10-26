"""Independent recognition controls; expected values are frozen hand calculations."""

from copy import deepcopy
from decimal import localcontext
import hashlib

import pytest

from foundry.finance_transaction_checks import review_transaction


SCOPE = {"organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}


def case(kind="uniform_service_advance"):
    policy, facts, proposed = {
        "uniform_service_advance": (
            "uniform_monthly_service_v1",
            {"cash_received": "120", "service_months": "12", "earned_months": "1",
             "performance_pattern": "uniform_monthly", "fulfilment_basis": "cumulative_since_contract_start"},
            {"recognized_revenue": "10", "contract_liability": "110"},
        ),
        "ordinary_service_consumed": (
            "expense_consumed_service_v1",
            {"amount": "100", "service_consumed_in_period": True, "future_economic_benefit": False},
            {"expense": "100", "capitalized_asset": "0"},
        ),
        "capitalizable_acquisition": (
            "capitalize_qualifying_acquisition_v1",
            {"amount": "100", "future_economic_benefit": True, "asset_controlled": True,
             "reliable_measurement": True, "useful_life_months": "36"},
            {"expense": "0", "capitalized_asset": "100"},
        ),
        "old_ar_collection": (
            "settle_existing_receivable_v1",
            {"amount": "10", "opening_receivable": "30", "receivable_origin_period": "2026-08"},
            {"cash_delta": "10", "receivables_delta": "-10", "revenue_delta": "0", "profit_delta": "0"},
        ),
        "new_earned_cash_sale": (
            "recognize_fulfilled_cash_sale_v1",
            {"amount": "10", "performance_obligation_satisfied": True,
             "associated_expense": "0", "tax_expense": "0"},
            {"cash_delta": "10", "receivables_delta": "0", "revenue_delta": "10", "profit_delta": "10"},
        ),
    }[kind]
    raw = {**SCOPE, "transaction_id": "T1", "transaction_type": kind, "recognition_date": "2026-09-30",
           "policy_id": policy, "policy_reference": "approved-policy-document:v1:section-2",
           "policy_effective_from": "2026-01-01", "policy_effective_to": "2026-12-31",
           "policy_transaction_type": kind, **facts}
    fields = set(raw) - set(SCOPE)
    bindings = {name: {"alias": "transactions", "column": name, "selector": {"transaction_id": "T1"},
                       "aggregation": "single", "scope": {"organization": "O1"},
                       "period": "2026-09", "currency": "CNY", "unit": "元"} for name in fields}
    inputs = {"scope": dict(SCOPE), "source_bindings": bindings, "proposed_entries": proposed}
    context = {"bindings": {"transactions": "d1"}, "scopes": {"transactions": dict(SCOPE)}}
    # The pure API receives archive hashes already verified by the service.
    datasets = {"transactions": {"id": "d1", "rows": [raw],
                                 "source_hash": hashlib.sha256(b"original source bytes").hexdigest(),
                                 "data_hash": hashlib.sha256(b"original data bytes").hexdigest()}}
    return inputs, context, datasets


def original(parts):
    return parts[2]["transactions"]["rows"][0]


@pytest.mark.parametrize("kind", ["uniform_service_advance", "ordinary_service_consumed", "capitalizable_acquisition",
                                 "old_ar_collection", "new_earned_cash_sale"])
def test_legitimate_controls_pass_without_becoming_certified_amount_facts(kind):
    parts = case(kind)
    before = deepcopy(parts)
    result = review_transaction(*parts)
    assert result["status"] == "pass", result
    assert result["expected_entries"] == parts[0]["proposed_entries"]
    assert not result["diagnostics"]
    assert result["evidence_eligible"] is False
    assert all(row["amount"] is None and row["fact_eligibility"]["counts_as_evidence"] is False for row in result["rows"])
    assert parts == before


@pytest.mark.parametrize("kind,wrong,failed", [
    ("uniform_service_advance", {"recognized_revenue": "120", "contract_liability": "0"},
     {"recognized_revenue": "110", "contract_liability": "-110"}),
    ("ordinary_service_consumed", {"expense": "0", "capitalized_asset": "100"},
     {"expense": "-100", "capitalized_asset": "100"}),
    ("old_ar_collection", {"cash_delta": "10", "receivables_delta": "0", "revenue_delta": "10", "profit_delta": "10"},
     {"receivables_delta": "10", "revenue_delta": "10", "profit_delta": "10"}),
])
def test_balanced_but_wrong_recognition_is_blocked(kind, wrong, failed):
    parts = case(kind)
    parts[0]["proposed_entries"] = wrong
    result = review_transaction(*parts)
    assert result["status"] == "fail"
    assert {r["item"]: r["difference"] for r in result["rows"] if r["status"] == "fail"} == failed
    assert all(item["severity"] == "error" for item in result["diagnostics"])
    assert all(row["blocks_evidence"] for row in result["checks"])


def test_prepaid_revenue_is_computed_from_120_12_1_not_supplied_as_source_10():
    result = review_transaction(*case())
    assert result["expected_entries"] == {"recognized_revenue": "10", "contract_liability": "110"}
    assert result["basis"]["measurement_basis"] == "contract_cumulative_allocation"
    assert "recognized_revenue" not in result["source_bindings"]
    assert {r["column"] for r in result["rows"][0]["source_rows"]} >= {"cash_received", "service_months", "earned_months", "policy_reference"}
    assert all(len(r["source_hash"]) == 64 and len(r["data_hash"]) == 64 for r in result["source_rows"])


@pytest.mark.parametrize("field", ["transaction_type", "policy_reference", "policy_effective_from", "cash_received", "earned_months"])
def test_missing_original_fact_or_policy_is_an_input_gap(field):
    parts = case()
    del original(parts)[field]
    result = review_transaction(*parts)
    assert result["status"] == "input_gap"
    assert result["expected_entries"] == {}
    assert result["diagnostics"][0]["severity"] == "error"


@pytest.mark.parametrize("field,value", [
    ("policy_id", "arbitrary-policy"), ("policy_transaction_type", "old_ar_collection"),
    ("policy_effective_from", "2026-10-01"), ("policy_effective_to", "2026-08-31"),
    ("recognition_date", "2026-08-31"), ("performance_pattern", "milestone"),
    ("fulfilment_basis", "undocumented"), ("service_months", "0"),
    ("service_months", "1.5"), ("earned_months", "13"), ("cash_received", "NaN"),
])
def test_policy_and_allocation_boundaries_are_explicit(field, value):
    parts = case()
    original(parts)[field] = value
    assert review_transaction(*parts)["status"] == "input_gap"


@pytest.mark.parametrize("field,value", [("future_economic_benefit", False), ("asset_controlled", False),
                                         ("reliable_measurement", "true"), ("useful_life_months", "0")])
def test_capitalization_requires_positive_policy_criteria_not_a_title(field, value):
    parts = case("capitalizable_acquisition")
    original(parts)[field] = value
    original(parts)["title"] = "legally capitalizable asset approved"
    assert review_transaction(*parts)["status"] == "input_gap"


def test_new_cash_sale_profit_uses_explicit_cost_and_tax_and_old_ar_does_not_create_profit():
    parts = case("new_earned_cash_sale")
    original(parts).update(associated_expense="3", tax_expense="1")
    parts[0]["proposed_entries"]["profit_delta"] = "6"
    assert review_transaction(*parts)["expected_entries"]["profit_delta"] == "6"
    del original(parts)["tax_expense"]
    assert review_transaction(*parts)["status"] == "input_gap"
    old = case("old_ar_collection")
    original(old)["opening_receivable"] = "9"
    assert review_transaction(*old)["status"] == "input_gap"
    original(old).update(opening_receivable="30", receivable_origin_period="2026-09")
    assert review_transaction(*old)["status"] == "input_gap"


@pytest.mark.parametrize("kind", ["ordinary_service_consumed", "capitalizable_acquisition", "new_earned_cash_sale"])
def test_archived_canonical_boolean_text_is_supported(kind):
    parts = case(kind)
    for name, value in original(parts).items():
        if type(value) is bool:
            original(parts)[name] = str(value)
    assert review_transaction(*parts)["status"] == "pass"


@pytest.mark.parametrize("value", ["true", "yes", "1", 1, " True "])
def test_noncanonical_truthy_text_is_not_a_policy_criterion(value):
    parts = case("capitalizable_acquisition")
    original(parts)["asset_controlled"] = value
    assert review_transaction(*parts)["status"] == "input_gap"


@pytest.mark.parametrize("field,value", [("organization", "O2"), ("currency", "USD"), ("period", "2026-08"), ("unit", "万元")])
def test_cross_identity_and_unit_relabeling_cannot_qualify(field, value):
    parts = case()
    original(parts)[field] = value
    assert review_transaction(*parts)["status"] == "input_gap"


def test_physical_amount_binding_survives_canonical_mapping():
    parts = case("ordinary_service_consumed")
    original(parts)["imported_amount"] = "999"
    parts[1]["policies"] = {"transactions": {"field_map": {"amount": "imported_amount"}}}
    result = review_transaction(*parts)
    assert result["status"] == "pass", result
    assert result["expected_entries"]["expense"] == "100"
    assert result["source_bindings"]["amount"]["column"] == "amount"


@pytest.mark.parametrize("mutation", [
    lambda p: p[2]["transactions"].pop("source_hash"),
    lambda p: p[2]["transactions"].update(data_hash="forged"),
    lambda p: p[2]["transactions"].update(id="unauthorized"),
    lambda p: p[0]["source_bindings"]["cash_received"].update(alias="other"),
    lambda p: p[0]["source_bindings"]["cash_received"].update(aggregation="sum"),
    lambda p: p[0]["source_bindings"]["cash_received"].update(selector={"invented": "T1"}),
    lambda p: original(p).update(source_status="voided"),
    lambda p: p[2]["transactions"]["rows"].append(deepcopy(original(p))),
])
def test_untrusted_or_ambiguous_sources_are_rejected(mutation):
    parts = case()
    mutation(parts)
    assert review_transaction(*parts)["status"] == "input_gap"


def test_fact_and_policy_records_cannot_be_mixed_between_transactions_or_books():
    parts = case()
    other = {**deepcopy(original(parts)), "transaction_id": "T2"}
    parts[2]["transactions"]["rows"].append(other)
    parts[0]["source_bindings"]["earned_months"]["selector"] = {"transaction_id": "T2"}
    assert review_transaction(*parts)["status"] == "input_gap"
    parts = case()
    policy = {**deepcopy(original(parts)), "transaction_id": "POLICY", "ledger": "L2"}
    original(parts)["ledger"] = "L1"
    parts[2]["transactions"]["rows"].append(policy)
    for name, binding in parts[0]["source_bindings"].items():
        if name.startswith("policy_"):
            binding["selector"] = {"transaction_id": "POLICY"}
    assert review_transaction(*parts)["status"] == "input_gap"


def test_separate_explicitly_linked_policy_record_is_supported():
    parts = case()
    policy = {**SCOPE, "record_id": "POLICY1"}
    for field in list(original(parts)):
        if field.startswith("policy_"):
            policy[field] = original(parts)[field]
            parts[0]["source_bindings"][field]["selector"] = {"record_id": "POLICY1"}
            if field != "policy_id":
                del original(parts)[field]
    parts[2]["transactions"]["rows"].append(policy)
    assert review_transaction(*parts)["status"] == "pass"
    original(parts)["policy_id"] = "unrelated"
    assert review_transaction(*parts)["status"] == "input_gap"


def test_output_contract_rejects_omitted_added_nonfinite_or_boolean_actuals():
    for replacement in ({"recognized_revenue": "10"}, {"recognized_revenue": "10", "contract_liability": "110", "cash": "120"},
                        {"recognized_revenue": "NaN", "contract_liability": "110"},
                        {"recognized_revenue": True, "contract_liability": "110"}):
        parts = case()
        parts[0]["proposed_entries"] = replacement
        assert review_transaction(*parts)["status"] == "input_gap"


def test_decimal_precision_is_local_and_no_float_rounding_hides_difference():
    parts = case()
    original(parts).update(cash_received="0.3", service_months="3", earned_months="1")
    parts[0]["proposed_entries"] = {"recognized_revenue": "0.1", "contract_liability": "0.2"}
    with localcontext() as context:
        context.prec = 3
        assert review_transaction(*parts)["status"] == "pass"
        assert context.prec == 3
    parts[0]["proposed_entries"]["recognized_revenue"] = "0.1000000000000000000001"
    assert review_transaction(*parts)["status"] == "fail"


def restriction_case():
    parts = case()
    transaction = original(parts)
    keep = {"transaction_id", "recognition_date", *SCOPE}
    for key in list(transaction):
        if key not in keep and not key.startswith("policy_"):
            transaction.pop(key)
    transaction.update(transaction_type="restricted_cash_release", policy_transaction_type="restricted_cash_release",
                       policy_id="release_effective_restriction_v1", cash_balance="100", restricted_cash="30",
                       restriction_id="R1", as_of_date="2026-09-30", obligations_due="80")
    release = {**SCOPE, "release_id": "REL1", "release_reference": "bank-release-letter:123",
               "release_restriction_id": "R1", "release_amount": "30",
               "release_effective_date": "2026-09-29", "release_status": "effective"}
    parts[2]["transactions"]["rows"].append(release)
    template = deepcopy(parts[0]["source_bindings"]["transaction_id"])
    bindings = {}
    for raw, selector in ((transaction, {"transaction_id": "T1"}), (release, {"release_id": "REL1"})):
        for name in set(raw) - set(SCOPE):
            bindings[name] = {**deepcopy(template), "column": name, "selector": selector}
    parts[0].update(source_bindings=bindings,
                    proposed_entries={"available_cash": "100", "remaining_restricted_cash": "0", "cash_shortfall": "0"})
    return parts


def test_effective_release_has_separate_source_and_releases_only_its_amount():
    parts = restriction_case()
    result = review_transaction(*parts)
    assert result["status"] == "pass", result
    assert result["expected_entries"] == {"available_cash": "100", "remaining_restricted_cash": "0", "cash_shortfall": "0"}
    assert result["source_bindings"]["release_amount"]["row_index"] == 2
    assert result["source_bindings"]["restricted_cash"]["row_index"] == 1
    parts[2]["transactions"]["rows"][1]["release_amount"] = "5"
    parts[0]["proposed_entries"] = {"available_cash": "75", "remaining_restricted_cash": "25", "cash_shortfall": "5"}
    assert review_transaction(*parts)["status"] == "pass"


@pytest.mark.parametrize("field,value", [("release_effective_date", "2026-10-01"), ("release_status", "ineffective")])
def test_future_or_ineffective_release_cannot_make_100_available(field, value):
    parts = restriction_case()
    parts[2]["transactions"]["rows"][1][field] = value
    result = review_transaction(*parts)
    assert result["status"] == "fail"
    assert result["expected_entries"] == {"available_cash": "70", "remaining_restricted_cash": "30", "cash_shortfall": "10"}
    parts[0]["proposed_entries"] = {"available_cash": "70", "remaining_restricted_cash": "30", "cash_shortfall": "10"}
    assert review_transaction(*parts)["status"] == "pass"


@pytest.mark.parametrize("field,value", [("release_restriction_id", "R2"), ("release_amount", "31"),
                                         ("release_effective_date", "tomorrow"), ("release_status", "approved"),
                                         ("release_reference", "")])
def test_release_requires_valid_link_amount_effective_date_and_status(field, value):
    parts = restriction_case()
    parts[2]["transactions"]["rows"][1][field] = value
    assert review_transaction(*parts)["status"] == "input_gap"


def test_no_release_source_or_unseparated_model_claim_cannot_release_restriction():
    parts = restriction_case()
    release = parts[2]["transactions"]["rows"].pop()
    assert review_transaction(*parts)["status"] == "input_gap"
    original(parts).update(release)
    for binding in parts[0]["source_bindings"].values():
        binding["selector"] = {"transaction_id": "T1"}
    assert review_transaction(*parts)["status"] == "input_gap"


def test_cash_shortfall_is_derived_from_independent_obligations_not_balance_error():
    parts = restriction_case()
    parts[2]["transactions"]["rows"][1]["release_status"] = "ineffective"
    parts[0]["proposed_entries"] = {"available_cash": "70", "remaining_restricted_cash": "30", "cash_shortfall": "10"}
    result = review_transaction(*parts)
    assert result["status"] == "pass"
    assert result["diagnostics"] == []  # A correctly disclosed shortfall is not an arithmetic defect.
    del original(parts)["obligations_due"]
    assert review_transaction(*parts)["status"] == "input_gap"
