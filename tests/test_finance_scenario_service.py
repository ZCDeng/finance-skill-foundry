import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.mark.parametrize("kind,policy,source_values,proposed,expected_status,expected", [
    ("uniform_service_advance", "uniform_monthly_service_v1",
     {"cash_received": "120", "service_months": "12", "earned_months": "1",
      "performance_pattern": "uniform_monthly", "fulfilment_basis": "cumulative_since_contract_start"},
     {"recognized_revenue": "10", "contract_liability": "110"}, "pass",
     {"recognized_revenue": "10", "contract_liability": "110"}),
    ("uniform_service_advance", "uniform_monthly_service_v1",
     {"cash_received": "120", "service_months": "12", "earned_months": "1",
      "performance_pattern": "uniform_monthly", "fulfilment_basis": "cumulative_since_contract_start"},
     {"recognized_revenue": "120", "contract_liability": "0"}, "fail",
     {"recognized_revenue": "10", "contract_liability": "110"}),
    ("ordinary_service_consumed", "expense_consumed_service_v1",
     {"amount": "100", "service_consumed_in_period": True, "future_economic_benefit": False},
     {"expense": "0", "capitalized_asset": "100"}, "fail", {"expense": "100", "capitalized_asset": "0"}),
    ("capitalizable_acquisition", "capitalize_qualifying_acquisition_v1",
     {"amount": "100", "future_economic_benefit": True, "asset_controlled": True, "reliable_measurement": True,
      "useful_life_months": "60"},
     {"expense": "0", "capitalized_asset": "100"}, "pass", {"expense": "0", "capitalized_asset": "100"}),
    ("old_ar_collection", "settle_existing_receivable_v1",
     {"amount": "10", "opening_receivable": "100", "receivable_origin_period": "2026-08"},
     {"cash_delta": "10", "receivables_delta": "0", "revenue_delta": "10", "profit_delta": "10"}, "fail",
     {"cash_delta": "10", "receivables_delta": "-10", "revenue_delta": "0", "profit_delta": "0"}),
])
def test_transaction_review_uses_archived_typed_sources_without_granting_amount_authority(
    tmp_path, kind, policy, source_values, proposed, expected_status, expected,
):
    from foundry.errors import FoundryError

    service = FinanceStore(TaskStore(tmp_path / "var").create(title="交易会计处理复核"))
    scope = {"organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元"}
    records = {
        "transactions": {**scope, "transaction_id": "T1", "transaction_type": kind,
                         "recognition_date": "2026-09-30", "policy_id": policy, **source_values},
        "policies": {**scope, "policy_id": policy, "policy_reference": "fixture-policy-approved-scope",
                     "policy_effective_from": "2026-01-01", "policy_effective_to": "2026-12-31",
                     "policy_transaction_type": kind},
    }
    bindings = {}
    for alias, row in records.items():
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps([row]))
        bindings[alias] = service.analysis.add_dataset(path, name=alias)["id"]
    context = service.save_context({"bindings": bindings, "scopes": {alias: scope for alias in bindings}})
    requirement = service.analysis_requirements_save({"context_id": context["id"],
        "question": "核查候选交易处理，保留专业复核边界",
        "items": [{"id": "transaction", "metric": "transaction_review", "requires_drilldown": False}]})
    source_bindings = {}
    for name in ["transaction_id", "transaction_type", "recognition_date", *source_values,
                 "policy_id", "policy_reference", "policy_effective_from", "policy_effective_to", "policy_transaction_type"]:
        alias = "policies" if name.startswith("policy_") else "transactions"
        source_bindings[name] = {"alias": alias, "column": name, "aggregation": "single", "scope": scope,
            "period": scope["period"], "currency": scope["currency"], "unit": scope["unit"],
            "selector": {"policy_id": policy} if alias == "policies" else {"transaction_id": "T1"}}
    scenario = service.save_scenario({"context_id": context["id"], "kind": "transaction_review",
        "label": "候选分录检查", "inputs": {"scope": scope, "source_bindings": source_bindings,
                                         "proposed_entries": proposed}})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded", run.get("error")
    assert run["result"]["status"] == expected_status, run["result"]["input_gaps"]
    assert run["result"]["expected_entries"] == expected
    assert run["result"]["evidence_eligible"] is False
    assert run["result"]["scenario_id"] == scenario["id"]
    facts = service.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    assert not any(fact["evidence_eligibility"]["counts_as_amount_evidence"] for fact in facts)
    draft = service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "\n".join("{{fact:" + fact["id"] + "}}" for fact in facts)})
    assert draft["completion"]["status"] != "complete"
    checked = service.validate_explanation({"draft_id": draft["id"]})
    assert checked["status"] == "needs_attention"
    checked_requirement = checked["requirements"]["items"][0]
    if expected_status == "pass":
        assert checked_requirement["status"] == "pending"
        assert checked_requirement["awaiting_manager"] == ["transaction_review_required"]
        assert draft["completion"]["status"] == "awaiting_manager"
        assert checked_requirement["counts_as_amount_evidence"] is False
        assert {issue["code"] for issue in checked["issues"]} == {"transaction_review_requires_professional_review"}
        assert not checked["requirements"]["original_requirements_completed"]
        incomplete = service.validate_explanation({"draft_id": draft["id"], "claims": []})
        assert incomplete["requirements"]["items"][0]["status"] != "answered"
    else:
        assert checked_requirement["status"] != "answered"
    if expected_status == "fail":
        assert any(item["severity"] == "error" for item in run["result"]["diagnostics"])
        checked = service.validate_explanation({"run_ids": [run["id"]], "body": "核查候选处理。"})
        assert checked["status"] == "needs_attention"
    denied = FinanceStore(service.task, snapshot_ids=[])
    with pytest.raises(FoundryError, match="outside"):
        denied.run_scenario({"scenario_id": scenario["id"]})


def test_cash_child_is_persistent_reproducible_and_drillable(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="现金预测")
    service = FinanceStore(task)
    scope = {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "万元"}
    bindings = {}
    for alias, rows in {
        "receipts": [{"id": "R1", "date": "2026-09-25", "amount": "100"}],
        "payments": [{"id": "P1", "date": "2026-09-28", "amount": "60"}],
    }.items():
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps(rows))
        bindings[alias] = AnalysisStore(task).add_dataset(path, name=alias)["id"]
    context = service.save_context(
        {"bindings": bindings, "scopes": {alias: scope for alias in bindings}}
    )
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "cash_13_weeks",
            "inputs": {
                "opening_cash": "50",
                "start_date": "2026-09-24",
                "actual_cutoff": "2026-09-23",
                "scope": scope,
            },
            "label": "基准",
        }
    )
    before = service.run_scenario({"scenario_id": scenario["id"]})
    assert before["result"]["rows"][0]["closing_cash"] == "90"
    child = service.save_scenario(
        {
            "parent_id": scenario["id"],
            "changes": {"scenario": {"delay_receipts_days": 14, "label": "延迟两周"}},
            "label": "延迟两周",
        }
    )
    after = service.run_scenario({"scenario_id": child["id"]})
    assert after["result"]["rows"][0]["closing_cash"] == "-10"
    assert (
        service._read("scenarios", scenario["id"])["input_hash"]
        == scenario["input_hash"]
    )
    assert after["result"]["parent_scenario_id"] == scenario["id"]
    assert (
        service.analysis.run_analysis(before["analysis_id"])["output_hash"]
        == before["output_hash"]
    )
    assert service.drilldown_fact({"run_id": before["id"], "row": 0})["total"] == 2


def test_driver_run_preserves_manager_assumptions_and_formula_provenance(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="驱动模型")
    path = tmp_path / "assumptions.json"
    path.write_text('[{"amount":"10"}]')
    service = FinanceStore(task)
    dataset = service.analysis.add_dataset(path, name="经理口径")
    context = service.save_context(
        {
            "bindings": {"inputs": dataset["id"]},
            "scopes": {"inputs": {"currency": "CNY", "unit": "万元"}},
        }
    )
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "driver_model",
            "label": "人数预算",
            "inputs": {
                "drivers": [
                    {"name": "headcount", "direct_assumption": True},
                    {
                        "name": "expense",
                        "formula": "headcount * 3",
                        "depends_on": ["headcount"],
                    },
                ],
                "manager_assumptions": {
                    "headcount": {"value": "10", "label": "经理编制计划"}
                },
            },
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    rows = {row["driver"]: row for row in run["result"]["rows"]}
    assert rows["headcount"]["source"] == "manager_direct"
    assert rows["expense"]["source"] == "derived"
    assert rows["expense"]["value"] == "30"
    assert rows["expense"]["formula"] == "headcount * 3"
    assert run["assumptions"][0]["label"] == "经理编制计划"
    assert service.drilldown_fact({"run_id": run["id"], "row": 0})["total"] == 0


def test_receivables_aging_service_links_scope_totals_and_source_rows(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="账龄")
    service = FinanceStore(task)
    invoice_path = tmp_path / "invoices.json"
    invoice_path.write_text(
        json.dumps(
            [
                {
                    "id": "I1",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "issue_date": "2026-08-01",
                    "due_date": "2026-08-01",
                    "amount": "80",
                },
                {
                    "id": "I2",
                    "ledger": "L2",
                    "organization": "O2",
                    "currency": "CNY",
                    "unit": "元",
                    "issue_date": "2026-08-01",
                    "due_date": "2026-08-01",
                    "amount": "40",
                },
            ],
            ensure_ascii=False,
        )
    )
    invoices = service.analysis.add_dataset(invoice_path, name="invoices")
    context = service.save_context(
        {
            "bindings": {"invoices": invoices["id"]},
            "scopes": {
                "invoices": {"currency": "CNY", "unit": "元"},
            },
        }
    )
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "receivables_aging",
            "label": "账龄",
            "inputs": {
                "as_of": "2026-09-05",
                "scope": {
                    "ledger": ["L1", "L2"],
                    "organization": ["O1", "O2"],
                    "currency": "CNY",
                    "unit": "元",
                },
            },
        }
    )

    run = service.run_scenario({"scenario_id": scenario["id"]})

    assert run["execution_status"] == "succeeded"
    assert run["result"]["evidence"]["total_open_amount_by_scope"] == [
        {
            "ledger": "L1",
            "organization": "O1",
            "currency": "CNY",
            "unit": "元",
            "open_amount": "80",
        },
        {
            "ledger": "L2",
            "organization": "O2",
            "currency": "CNY",
            "unit": "元",
            "open_amount": "40",
        },
    ]
    row = next(
        row
        for row in run["result"]["rows"]
        if row["ledger"] == "L1"
        and row["organization"] == "O1"
        and row["bucket"] == "31-60"
    )
    assert row["open_amount"] == "80"
    assert row["source_rows"] == [
        {"dataset_id": invoices["id"], "row_index": 1, "source_row": 1}
    ]


def test_receivables_aging_service_applies_status_filter_and_exclusion_sources(
    tmp_path,
):
    task = TaskStore(tmp_path / "var").create(title="争议账龄")
    service = FinanceStore(task)
    invoice_path = tmp_path / "invoices.json"
    invoice_path.write_text(
        json.dumps(
            [
                {
                    "id": "I-disputed",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "issue_date": "2026-08-01",
                    "due_date": "2026-08-01",
                    "amount": "100",
                    "invoice_status": "争议",
                },
                {
                    "id": "I-active",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "issue_date": "2026-08-01",
                    "due_date": "2026-08-01",
                    "amount": "30",
                    "invoice_status": "正常",
                },
            ],
            ensure_ascii=False,
        )
    )
    activity_path = tmp_path / "activity.json"
    activity_path.write_text(
        json.dumps(
            [
                {
                    "id": "P-disputed",
                    "invoice_id": "I-disputed",
                    "kind": "payment",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "effective_date": "2026-08-20",
                    "amount": "40",
                },
                {
                    "id": "P-active",
                    "invoice_id": "I-active",
                    "kind": "payment",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "effective_date": "2026-08-20",
                    "amount": "5",
                },
            ],
            ensure_ascii=False,
        )
    )
    invoices = service.analysis.add_dataset(invoice_path, name="invoices")
    activity = service.analysis.add_dataset(activity_path, name="activity")
    context = service.save_context(
        {
            "bindings": {"invoices": invoices["id"], "activity": activity["id"]},
            "scopes": {
                "invoices": {"currency": "CNY", "unit": "元"},
                "activity": {"currency": "CNY", "unit": "元"},
            },
        }
    )
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "receivables_aging",
            "label": "争议账龄",
            "inputs": {
                "as_of": "2026-09-05",
                "scope": {
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                },
                "status_filter": {
                    "field": "invoice_status",
                    "include": ["disputed"],
                    "mapping": {"disputed": ["争议"], "active": ["正常"]},
                },
            },
        }
    )

    run = service.run_scenario({"scenario_id": scenario["id"]})

    row = next(
        row for row in run["result"]["rows"] if row["bucket"] == "31-60"
    )
    assert row["open_amount"] == "60"
    assert row["source_rows"] == [
        {"dataset_id": invoices["id"], "row_index": 1, "source_row": 1},
        {"dataset_id": activity["id"], "row_index": 1, "source_row": 1},
    ]
    assert row["excluded_source_rows"] == [
        {"dataset_id": invoices["id"], "row_index": 2, "source_row": 2},
        {"dataset_id": activity["id"], "row_index": 2, "source_row": 2},
    ]
    excluded = run["result"]["evidence"]["status_filter"]["excluded"][0]
    assert {
        key: excluded[key]
        for key in (
            "invoice_id",
            "ledger",
            "organization",
            "currency",
            "unit",
            "bucket",
            "raw_status",
            "status",
            "exclusion_reason",
            "open_amount",
        )
    } == {
        "invoice_id": "I-active",
        "ledger": "L1",
        "organization": "O1",
        "currency": "CNY",
        "unit": "元",
        "bucket": "31-60",
        "raw_status": "正常",
        "status": "active",
        "exclusion_reason": "status_not_included",
        "open_amount": "25",
    }


def test_receivables_aging_service_keeps_excluded_sources_when_all_filtered_out(
    tmp_path,
):
    task = TaskStore(tmp_path / "var").create(title="全部剔除账龄")
    service = FinanceStore(task)
    invoice_path = tmp_path / "invoices.json"
    invoice_path.write_text(
        json.dumps(
            [
                {
                    "id": "I-same",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "issue_date": "2026-08-01",
                    "due_date": "2026-08-06",
                    "amount": "100",
                    "invoice_status": "正常",
                },
                {
                    "id": "I-same",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "USD",
                    "unit": "元",
                    "issue_date": "2026-08-01",
                    "due_date": "2026-08-05",
                    "amount": "50",
                    "invoice_status": "正常",
                },
            ],
            ensure_ascii=False,
        )
    )
    activity_path = tmp_path / "activity.json"
    activity_path.write_text(
        json.dumps(
            [
                {
                    "id": "P-cny",
                    "invoice_id": "I-same",
                    "kind": "payment",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "effective_date": "2026-09-05",
                    "amount": "10",
                },
                {
                    "id": "P-usd",
                    "invoice_id": "I-same",
                    "kind": "payment",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "USD",
                    "unit": "元",
                    "effective_date": "2026-09-05",
                    "amount": "5",
                },
                {
                    "id": "P-cny-after",
                    "invoice_id": "I-same",
                    "kind": "payment",
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "effective_date": "2026-09-06",
                    "amount": "7",
                },
            ],
            ensure_ascii=False,
        )
    )
    invoices = service.analysis.add_dataset(invoice_path, name="invoices")
    activity = service.analysis.add_dataset(activity_path, name="activity")
    context = service.save_context(
        {
            "bindings": {"invoices": invoices["id"], "activity": activity["id"]},
            "scopes": {
                "invoices": {"currency": ["CNY", "USD"], "unit": "元"},
                "activity": {"currency": ["CNY", "USD"], "unit": "元"},
            },
        }
    )
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "receivables_aging",
            "label": "全部剔除账龄",
            "inputs": {
                "as_of": "2026-09-05",
                "scope": {
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": ["CNY", "USD"],
                    "unit": "元",
                },
                "status_filter": {
                    "field": "invoice_status",
                    "include": ["disputed"],
                    "mapping": {"active": ["正常"], "disputed": ["争议"]},
                },
            },
        }
    )

    run = service.run_scenario({"scenario_id": scenario["id"]})

    assert all(row["open_amount"] == "0" for row in run["result"]["rows"])
    cny_bucket = next(
        row
        for row in run["result"]["rows"]
        if row["currency"] == "CNY" and row["bucket"] == "0-30"
    )
    usd_bucket = next(
        row
        for row in run["result"]["rows"]
        if row["currency"] == "USD" and row["bucket"] == "31-60"
    )
    assert cny_bucket["as_of"] == "2026-09-05"
    assert usd_bucket["as_of"] == "2026-09-05"
    assert cny_bucket["source_rows"] == []
    assert usd_bucket["source_rows"] == []
    assert cny_bucket["excluded_source_rows"] == [
        {"dataset_id": invoices["id"], "row_index": 1, "source_row": 1},
        {"dataset_id": activity["id"], "row_index": 1, "source_row": 1},
    ]
    assert usd_bucket["excluded_source_rows"] == [
        {"dataset_id": invoices["id"], "row_index": 2, "source_row": 2},
        {"dataset_id": activity["id"], "row_index": 2, "source_row": 2},
    ]
    excluded_by_currency = {
        row["currency"]: row for row in run["result"]["excluded_detail_rows"]
    }
    assert excluded_by_currency["CNY"]["source_rows"] == cny_bucket[
        "excluded_source_rows"
    ]
    assert excluded_by_currency["USD"]["source_rows"] == usd_bucket[
        "excluded_source_rows"
    ]
    assert run["result"]["evidence"]["status_filter"][
        "total_scope_open_amount_by_scope"
    ] == [
        {
            "ledger": "L1",
            "organization": "O1",
            "currency": "CNY",
            "unit": "元",
            "open_amount": "90",
        },
        {
            "ledger": "L1",
            "organization": "O1",
            "currency": "USD",
            "unit": "元",
            "open_amount": "45",
        },
    ]
