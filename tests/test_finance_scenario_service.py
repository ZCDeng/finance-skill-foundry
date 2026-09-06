import json

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


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
