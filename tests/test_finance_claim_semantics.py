from copy import deepcopy

import pytest

from foundry.finance_claim_semantics import check_claim_semantics


def fact(metric, value, *, row=0, run_id="run"):
    return {"id": f"{run_id}-{metric}", "run_id": run_id, "row": row, "column": "value", "value": str(value),
            "display_value": f"{value} 元", "semantics": {"metric": metric}, "unit": "元",
            "evidence_eligibility": {"counts_as_amount_evidence": True, "status": "source_verified"}}


CASH = [fact("closing_cash", 100), fact("available_cash", 70, row=1), fact("closing_restricted_cash", 30, row=2)]


@pytest.mark.parametrize("sign", ["-", "−", "－"])
@pytest.mark.parametrize("template", [None, "可用资金为{{fact:run-closing_cash}}。"])
def test_negative_cash_sign_cannot_hide_wrong_metric_identity(sign, template):
    issues = check_claim_semantics(f"可用资金为{sign}60元。", [fact("closing_cash", -60)],
                                   body_template=template)
    assert any(item["code"] == "fact_metric_semantics_mismatch" for item in issues)


@pytest.mark.parametrize("sign", ["-", "−", "－"])
@pytest.mark.parametrize("eligible", [False, True])
def test_negative_cash_sign_preserves_amount_qualification(sign, eligible):
    source = fact("available_cash", -60)
    source["evidence_eligibility"]["counts_as_amount_evidence"] = eligible
    before = deepcopy(source)
    issues = check_claim_semantics(f"可用资金为{sign}60元。", [source],
                                   body_template="可用资金为{{fact:run-available_cash}}。")
    if eligible:
        assert issues == []
    else:
        assert [item["code"] for item in issues] == ["fact_amount_evidence_ineligible"]
    assert source == before


@pytest.mark.parametrize("body", [
    "本期可用资金为100元。完整模型结果：现金余额100元，可用资金70元。",
    "可动用资金：100", "available cash is 100", "unrestricted cash: 100", "可用资金 | 100",
    "将现金余额100元作为可用资金。", "期末现金为70元。", "受限资金为100元。",
])
def test_affirmative_cash_amount_must_have_the_corresponding_fact_type(body):
    issues = check_claim_semantics(body, CASH)
    assert any(issue["code"] == "fact_metric_semantics_mismatch" and issue["severity"] == "error" for issue in issues)


@pytest.mark.parametrize("body", [
    "期末现金余额100元，受限资金30元，可用资金70元。",
    "可用资金为70元，比现金余额100元少30元。",
    "不能将现金余额100元作为可用资金。", "可用资金不是100元，而是70元。",
    "可用资金不足100元。", "可用资金为100元的说法不正确，可用资金为70元。",
    "“可用资金为100元”这一说法错误。", "若忽略限制，可用资金将为100元。",
    "现金余额100元并不代表可用资金100元。", "本次只展示现金余额100元。",
])
def test_cash_labels_do_not_reject_valid_contrasts_negations_or_balance_reporting(body):
    assert check_claim_semantics(body, CASH) == []


def test_equal_number_does_not_grant_an_unrelated_fact_cash_meaning():
    facts = [fact("closing_cash", 100), fact("net_income", 100)]
    assert check_claim_semantics("可用资金100元", facts)
    assert check_claim_semantics("可用资金100元", [*facts, fact("available_cash", 100)]) == []
    forged_label = {**facts[0], "label": "available_cash"}
    assert check_claim_semantics("可用资金100元", [forged_label])


def test_explicit_template_reference_keeps_identity_when_another_fact_has_the_same_value():
    facts = [fact("closing_cash", 100), fact("available_cash", 100)]
    template = "可用资金为{{fact:run-closing_cash}}。"
    issues = check_claim_semantics("可用资金为100元。", facts, body_template=template)
    assert issues and issues[0]["fact_id"] == "run-closing_cash"
    assert check_claim_semantics("可用资金为100元。", facts,
                                 body_template="可用资金为{{fact:run-available_cash}}。") == []


@pytest.mark.parametrize("body", [
    "不能忽略受限资金但可用资金为100元。", "不能忽略受限资金，但是可用资金为100元。",
    "不应遗漏受限资金而可用资金为100元。", "不能误判实际可用资金为100元。",
    "非受限现金100元。", "非受限资金为100元。",
])
def test_negation_does_not_hide_an_affirmative_claim_after_a_contrast(body):
    assert check_claim_semantics(body, CASH)


def test_unqualified_sql_alias_and_another_run_cannot_launder_a_cash_reference():
    sql_alias = fact("available_cash", 100, run_id="sql")
    sql_alias["evidence_eligibility"] = {"counts_as_amount_evidence": False, "status": "unverified"}
    assert check_claim_semantics("可用资金为100元", [*CASH, sql_alias])
    assert check_claim_semantics("可用资金为100元", [*CASH, sql_alias],
                                 body_template="可用资金为{{fact:sql-available_cash}}")
    other = fact("available_cash", 100, run_id="other-period")
    assert check_claim_semantics("可用资金为100元", [*CASH, other])
    assert check_claim_semantics("可用资金为100元", [*CASH, other],
                                 body_template="可用资金为{{fact:run-closing_cash}}")
    assert check_claim_semantics("可用资金为100元", [*CASH, other],
                                 body_template="可用资金为{{fact:other-period-available_cash}}") == []


def test_old_template_cannot_replace_an_edited_body_amount():
    assert check_claim_semantics("可用资金为100元", CASH,
                                 body_template="可用资金为{{fact:run-available_cash}}")


def test_cash_equal_values_in_different_scopes_require_the_exact_reference():
    balance = {**fact("closing_cash", 100), "scope": {"organization": "A", "period": "2026-09"}}
    available = {**fact("available_cash", 100), "scope": {"organization": "B", "period": "2026-09"}}
    assert check_claim_semantics("可用资金100元", [balance, available])
    assert check_claim_semantics("可用资金100元", [balance, available],
                                 body_template="可用资金{{fact:run-available_cash}}元") == []


def test_only_the_server_parameter_can_supply_recipe_semantic_proof():
    source = fact("available_cash", 70)
    source["evidence_eligibility"] = {"counts_as_amount_evidence": False, "status": "unverified"}
    source["trusted_fact_ids"] = [source["id"]]
    source["semantic_verified"] = True
    template = "可用资金{{fact:run-available_cash}}元"
    assert check_claim_semantics("可用资金70元", [source], body_template=template)
    assert check_claim_semantics("可用资金70元", [source], body_template=template,
                                 trusted_fact_ids=[source["id"]]) == []
    assert check_claim_semantics("可用资金100元", CASH, body_template="可用资金{{fact:run-closing_cash}}元",
                                 trusted_fact_ids=["run-closing_cash"])


@pytest.mark.parametrize("metric,label", [
    ("closing_cash", "期末现金余额"),
    ("available_cash", "可用资金"),
    ("closing_restricted_cash", "受限资金"),
])
def test_matching_cash_metric_without_amount_qualification_has_a_specific_diagnosis(metric, label):
    source = fact(metric, "37.25")
    source["evidence_eligibility"] = {
        "counts_as_amount_evidence": False, "status": "unverified",
        "reason_codes": ["unregistered_financial_semantics"],
    }
    before = deepcopy(source)
    issues = check_claim_semantics(f"{label}为37.25元。", [source],
                                   body_template=f"{label}为{{{{fact:{source['id']}}}}}。")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["code"] == "fact_amount_evidence_ineligible"
    assert issue["severity"] == "error"
    assert issue["fact_id"] == source["id"] and issue["run_id"] == source["run_id"]
    assert issue["row"] == source["row"] and issue["column"] == source["column"]
    assert issue["expected_metric"] == metric
    assert issue["reason_codes"] == ["unregistered_financial_semantics"]
    assert issue["counts_as_amount_evidence"] is False
    assert issue["recovery"]["required_metric"] == metric
    assert issue["recovery"]["requires_amount_eligible_fact"] is True
    assert "unregistered_financial_semantics" in issue["message"]
    assert source == before  # A diagnosis never upgrades the input evidence.


@pytest.mark.parametrize("eligibility,reason_codes", [
    ({}, ["amount_evidence_not_qualified"]),
    ({"counts_as_amount_evidence": False, "reason_codes": []}, ["amount_evidence_not_qualified"]),
    ({"counts_as_amount_evidence": "true"}, ["amount_evidence_not_qualified"]),
    ({"counts_as_amount_evidence": False, "reason_codes": ["amount_source_hash_mismatch", "model_checks_failed"]},
     ["amount_source_hash_mismatch", "model_checks_failed"]),
])
def test_ineligible_diagnosis_preserves_server_reasons_and_fails_closed_without_them(eligibility, reason_codes):
    source = fact("available_cash", 23)
    source["evidence_eligibility"] = eligibility
    issue, = check_claim_semantics("可用资金23元", [source])
    assert issue["code"] == "fact_amount_evidence_ineligible"
    assert issue["reason_codes"] == reason_codes


def test_ineligible_exact_token_does_not_borrow_an_equal_qualified_fact():
    source = fact("closing_restricted_cash", 13, run_id="input")
    source["evidence_eligibility"] = {
        "counts_as_amount_evidence": False, "reason_codes": ["unregistered_financial_semantics"]}
    qualified = fact("closing_restricted_cash", 13, run_id="registered")
    facts = [qualified, source]
    issue, = check_claim_semantics("受限资金13元", facts,
                                   body_template="受限资金{{fact:input-closing_restricted_cash}}元")
    assert issue["code"] == "fact_amount_evidence_ineligible"
    assert issue["fact_id"] == source["id"]
    assert issue["matched_fact_ids"] == [source["id"]]
    assert check_claim_semantics("受限资金13元", facts,
           body_template="受限资金{{fact:registered-closing_restricted_cash}}元") == []


@pytest.mark.parametrize("qualified", [True, False])
def test_wrong_metric_token_remains_a_semantic_mismatch_even_when_equal_input_matches(qualified):
    wrong = fact("closing_cash", 41)
    wrong["evidence_eligibility"]["counts_as_amount_evidence"] = qualified
    matching = fact("closing_restricted_cash", 41)
    matching["evidence_eligibility"]["counts_as_amount_evidence"] = False
    issue, = check_claim_semantics("受限资金41元", [matching, wrong],
                                   body_template="受限资金{{fact:run-closing_cash}}元")
    assert issue["code"] == "fact_metric_semantics_mismatch"
    assert issue["fact_id"] == wrong["id"]


def test_native_restricted_cash_input_is_diagnosed_but_never_upgraded(tmp_path):
    from test_finance_professional_protocol import _template_case
    service, _, requirement, run = _template_case(tmp_path)
    prepared = service.prepare_explanation({"run_ids": [run["id"]], "fact_view": "inspection"})
    source = next(item for item in prepared["facts"]
                  if item["semantics"]["metric"] == "closing_restricted_cash" and item["column"] == "value")
    assert source["evidence_eligibility"]["counts_as_amount_evidence"] is False
    assert source["evidence_eligibility"]["reason_codes"] == ["unregistered_financial_semantics"]
    template = "受限资金为{{fact:%s}}。\n" % source["id"]
    template += "\n".join("{{fact:%s}}" % item["id"] for item in prepared["facts"])
    saved = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]], "body": template})
    issue, = [issue for issue in saved["quality"]["issues"]
              if issue.get("fact_id") == source["id"] and issue["code"].startswith("fact_")]
    assert issue["code"] == "fact_amount_evidence_ineligible"
    assert issue["reason_codes"] == ["unregistered_financial_semantics"]
    assert saved["quality"]["status"] == "needs_attention"
    assert saved["completion"]["status"] != "complete"
    reread = service.prepare_explanation({"run_ids": [run["id"]], "fact_view": "inspection"})
    assert next(item for item in reread["facts"] if item["id"] == source["id"])["evidence_eligibility"] == source["evidence_eligibility"]


@pytest.mark.parametrize("metric, bad, good", [
    ("prepayment_received", "本期新增收入为120元", "本期预收120元，不能全额确认为本期收入120元"),
    ("ordinary_operating_expense", "本期资本化资产为120元", "本期服务费用120元，不应作为资本化资产120元"),
    ("old_ar_collection", "全额确认为本期新增收入120元", "本期收回旧应收120元，不再次确认收入"),
])
def test_explicit_transaction_identity_cannot_be_relabelled(metric, bad, good):
    source = fact(metric, 120)
    source["evidence_eligibility"] = {"counts_as_amount_evidence": False, "status": "unverified"}
    assert check_claim_semantics(bad, [source])
    assert check_claim_semantics(good, [source]) == []


def test_exact_old_ar_reference_does_not_inherit_same_valued_revenue():
    facts = [fact("old_ar_collection", 10), fact("revenue", 10)]
    body = "本期收回旧应收10元，全额确认为本期新增收入10元。"
    template = "本期收回旧应收{{fact:run-old_ar_collection}}，全额确认为本期新增收入{{fact:run-old_ar_collection}}。"
    assert check_claim_semantics(body, facts, body_template=template)
    assert check_claim_semantics(body, facts, body_template=template.replace("收入{{fact:run-old_ar_collection}}", "收入{{fact:run-revenue}}")) == []
    assert check_claim_semantics("旧应收10元，不再次确认收入10元。", facts) == []


def test_complete_number_and_decimal_matching():
    facts = [fact("closing_cash", "1100.25"), fact("available_cash", "100.25")]
    assert check_claim_semantics("可用资金为1,100.25元", facts)
    assert check_claim_semantics("可用资金100.25元", facts) == []
    assert check_claim_semantics("可用资金1100元", facts) == []  # Numeric validator handles uncited values.


def filtered_ar():
    scope = {"ledger": "L", "organization": "O", "currency": "CNY", "unit": "元"}
    ar = {**fact("open_amount", 95), "column": "open_amount"}
    run = {"id": "run", "engine": "finance", "result": {"rows": [{**scope, "open_amount": "95"}],
           "evidence": {"status_filter": {
               "included_open_amount_by_scope": [{**scope, "open_amount": "95"}],
               "excluded_open_amount_by_scope": [{**scope, "open_amount": "20"}],
               "total_scope_open_amount_by_scope": [{**scope, "open_amount": "115"}],
           }}}}
    return ar, run


def test_filtered_receivables_are_not_the_full_population():
    ar, run = filtered_ar()
    issues = check_claim_semantics("完整应收毛额为95元", [ar], runs=[run])
    assert issues[0]["code"] == "fact_population_scope_mismatch"
    assert issues[0]["population"]["excluded"] == "20"
    assert issues[0]["population"]["total"] == "115"


@pytest.mark.parametrize("body", [
    "非争议应收95元，另有争议应收20元，完整应收毛额115元。",
    "非争议应收95元。", "不应将95元作为完整应收毛额。",
    "非争议应收账款毛额95元。", "筛选后的应收毛额95元。",
    "完整应收毛额不是95元，而是115元。",
])
def test_filtered_subset_and_explicit_reconciliation_are_allowed(body):
    ar, run = filtered_ar()
    assert check_claim_semantics(body, [ar], runs=[run]) == []


def test_no_exclusion_or_unrelated_scope_does_not_create_a_population_obligation():
    ar, run = filtered_ar()
    unchanged = deepcopy(run)
    filtered = unchanged["result"]["evidence"]["status_filter"]
    filtered["excluded_open_amount_by_scope"][0]["open_amount"] = "0"
    filtered["total_scope_open_amount_by_scope"][0]["open_amount"] = "95"
    assert check_claim_semantics("完整应收毛额95元", [ar], runs=[unchanged]) == []
    run["result"]["rows"][0]["organization"] = "Other"
    assert check_claim_semantics("完整应收毛额95元", [ar], runs=[run]) == []


def test_m11_uses_real_aging_sources_and_current_filter_reconciliation(tmp_path):
    import json
    from foundry.finance_service import FinanceStore
    from foundry.task import TaskStore
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="M11 完整应收"))
    scope = {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "元"}
    path = tmp_path / "invoices.json"
    path.write_text(json.dumps([{**scope, "invoice_id": key, "amount": value, "invoice_status": status,
                                 "issue_date": "2026-08-01", "due_date": "2026-08-01"}
                                for key, value, status in [("active", "95", "正常"), ("disputed", "20", "争议")]]))
    dataset = service.analysis.add_dataset(path, name="应收")
    context = service.save_context({"bindings": {"invoices": dataset["id"]}, "scopes": {"invoices": scope}})
    scenario = service.save_scenario({"context_id": context["id"], "kind": "receivables_aging", "label": "非争议",
        "inputs": {"invoices_alias": "invoices", "as_of": "2026-09-05", "scope": scope,
                   "status_filter": {"field": "invoice_status", "include": ["active"],
                                     "mapping": {"active": ["正常"], "disputed": ["争议"]}}}})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    assert any(fact["value"] == "95" and fact["column"] == "open_amount" for fact in facts)
    issues = check_claim_semantics("完整应收毛额为95元。", facts, runs=[run])
    assert issues and issues[0]["population"]["total"] == "115"
    assert check_claim_semantics("非争议应收95元，排除争议应收20元，调节后完整应收毛额115元。", facts, runs=[run]) == []


def test_m10_uses_real_source_bound_template_facts(tmp_path, monkeypatch):
    import test_finance_three_statement as template_tests
    from test_finance_professional_protocol import _template_case
    original = template_tests.template_parts

    def restricted_parts():
        scenario, context, datasets = original()
        for row in datasets["template_inputs"]["rows"]:
            if row["input_name"] in {"customer_receipts", "closing_restricted_cash"}:
                row["amount"] = {"customer_receipts": "110", "closing_restricted_cash": "30"}[row["input_name"]]
        return scenario, context, datasets

    monkeypatch.setattr(template_tests, "template_parts", restricted_parts)
    service, context, requirement, run = _template_case(tmp_path)
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    by_metric = {fact["semantics"]["metric"]: fact for fact in facts if fact["column"] == "value"}
    assert by_metric["closing_cash"]["value"] == "100"
    assert by_metric["available_cash"]["value"] == "70"
    assert check_claim_semantics("本期可用资金为100元。完整模型：可用资金70元。", facts, runs=[run])
    assert check_claim_semantics("本期可用资金为70元，期末现金余额100元。", facts, runs=[run]) == []


def test_unreadable_historical_semantic_evidence_does_not_keep_a_current_success(tmp_path, monkeypatch):
    from foundry import finance_explanations
    from foundry.errors import FoundryError
    from test_finance_professional_protocol import _template_case
    service, _, requirement, run = _template_case(tmp_path)
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    saved = service.save_explanation_draft({
        "body": "\n".join("{{fact:%s}}" % fact["id"] for fact in facts
                          if fact["evidence_eligibility"]["counts_as_amount_evidence"]),
        "run_ids": [run["id"]], "requirements_id": requirement["id"],
    })
    assert saved["completion"]["status"] == "complete"
    paths = [service.analysis._object_path("drafts", saved["id"]),
             service.analysis._object_path("completions", saved["completion"]["id"])]
    before = [path.read_bytes() for path in paths]

    def unavailable(*args, **kwargs):
        raise FoundryError("archived semantic evidence is unavailable")

    monkeypatch.setattr(finance_explanations, "saved_claim_semantic_issues", unavailable)
    draft = service.analysis.draft_in_view(service.analysis.get_draft(saved["id"]), None)
    receipt = service.analysis.completion_in_view(saved["completion"], None)
    assert draft["quality"]["status"] == "needs_attention"
    assert any(issue["code"] == "claim_semantic_context_unavailable" for issue in draft["quality"]["issues"])
    assert receipt["status"] == receipt["response_status"] == "needs_review"
    assert receipt["professional_reason"] == "claim_semantic_context_unavailable"
    assert receipt["historical_status"] == "complete"
    assert receipt["repair_attempts"] == saved["completion"]["repair_attempts"]
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("source_metric", ["available_cash", "closing_cash"])
@pytest.mark.parametrize("source_scenario,result_scenario", [(None, None), ("actual", "actual"), ("actual", "budget")])
def test_source_typed_cash_sql_with_verified_direct_recipe_remains_valid(tmp_path, source_metric, source_scenario, result_scenario):
    from openpyxl import Workbook
    from foundry.finance_service import FinanceStore
    from foundry.task import TaskStore
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="来源可用现金"))
    book = Workbook()
    sheet = book.active
    sheet.title = "Cash"
    sheet.append(["metric_key", "amount", "unit", "currency", "period", "organization", "scenario"])
    sheet.append([source_metric, 70, "元", "CNY", "2026-09", "Synthetic Fixture Co", source_scenario])
    path = tmp_path / "cash.xlsx"
    book.save(path)
    dataset = service.analysis.add_dataset(path, name="现金", metadata={"mode": "table", "sheet": "Cash"})
    context = service.save_context({"bindings": {"cash": dataset["id"]}})
    requirement = service.analysis_requirements_save({"context_id": context["id"], "question": "报告来源可用现金",
        "items": [{"id": "available", "metric": "available_cash", "requires_drilldown": False}]})
    metric_sql = "metric_key" if source_metric == "available_cash" else "'available_cash' AS metric_key"
    scenario_sql = f", '{result_scenario}' AS scenario" if result_scenario else ""
    definition = service.analysis.save_analysis({"question": "来源现金", "bindings": context["bindings"],
        "sql": f"SELECT {metric_sql}, CAST(amount AS DECIMAL(38,2)) AS value, unit, currency, period, organization{scenario_sql} FROM cash"})
    run = service.analysis.run_analysis(definition["id"])
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    amount = next(fact for fact in facts if fact["column"] == "value")
    assert amount["semantics"]["metric"] == "available_cash"
    assert not amount["evidence_eligibility"]["counts_as_amount_evidence"]
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "可用资金为{{fact:%s}}。" % amount["id"],
        "evidence_recipes": [{"id": "source-cash", "kind": "direct", "dataset_id": dataset["id"],
            "source_hash": dataset["source_hash"], "sheet": "Cash", "range": "B2", "unit": "元",
            "claim": {"run_id": run["id"], "row": 0, "column": "value"}}]})
    if source_metric == "available_cash" and source_scenario == result_scenario:
        assert draft["explanation_check"]["status"] == "pass", draft["explanation_check"]["issues"]
        assert draft["completion"]["status"] == "complete"
    else:
        # The SQL output's alias matches the prose, but its source meaning or
        # scenario did not earn the trusted-recipe qualification.
        issue, = [issue for issue in draft["explanation_check"]["issues"]
                  if issue["code"] == "fact_amount_evidence_ineligible"]
        assert issue["fact_id"] == amount["id"]
        assert issue["reason_codes"] == amount["evidence_eligibility"]["reason_codes"]
        assert draft["explanation_check"]["status"] == "needs_attention"
        assert draft["completion"]["status"] != "complete"
