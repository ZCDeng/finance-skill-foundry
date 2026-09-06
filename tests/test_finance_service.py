import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.fixture
def finance(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="管理利润")
    store = AnalysisStore(task)
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{scenario}.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "account_code": code,
                        "management_account": account,
                        "amount": amount,
                    }
                    for code, account, amount in zip(
                        ("001", "002", "003"), ("revenue", "cost", "expense"), amounts
                    )
                ]
            )
        )
        bindings[scenario] = store.add_dataset(path, name=scenario)["id"]
    service = FinanceStore(task)
    context = service.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": alias,
                }
                for alias in bindings
            },
        }
    )
    return service, context


def test_shared_run_draft_drilldown_and_immutable_mapping(finance):
    service, context = finance
    run = service.explain_variance({"context_id": context["id"]})
    rows = run["result"]["rows"]
    index = next(i for i, row in enumerate(rows) if row["metric"] == "profit")
    assert rows[index]["contribution"] == "5"
    evidence = service.drilldown_fact({"run_id": run["id"], "row": index})
    assert len(evidence["rows"]) == 6
    assert not any(r["voucher_detail_available"] for r in evidence["rows"])
    assert evidence["rows"][0]["data"]["account_code"].startswith("00")
    draft = service.save_explanation_draft(
        {
            "title": "利润说明",
            "body": "利润超预算 5 万元。",
            "run_ids": [run["id"]],
            "claims": [
                {
                    "basis": "calculation",
                    "run_id": run["id"],
                    "row": index,
                    "column": "contribution",
                    "value": "5",
                }
            ],
        }
    )
    assert draft["claims"][0]["verification_status"] == "matches_run"
    assert draft["claims"][0]["finance_scope"]["actual"]["unit"] == "万元"
    updated = service.save_explanation_draft(
        {
            "parent_id": draft["id"],
            "body": "预计来自促销，待核实。",
            "claims": [{"basis": "professional_judgment", "reason": "经理判断"}],
        }
    )
    assert updated["claims"][0]["verification_status"] == "unverified"
    assert service.analysis.get_draft(draft["id"])["body"] == "利润超预算 5 万元。"
    rerun = service.analysis.run_analysis(run["analysis_id"])
    assert rerun["output_hash"] == run["output_hash"]
    assert rerun["reproducibility_status"] == "reproducible"
    assert service.analysis.state()["runs"][-1]["id"] == rerun["id"]


def test_changed_calculated_value_cannot_keep_verification(finance):
    service, context = finance
    run = service.run_metric({"context_id": context["id"]})
    with pytest.raises(FoundryError, match="differs"):
        service.save_explanation_draft(
            {
                "run_ids": [run["id"]],
                "claims": [
                    {
                        "basis": "calculation",
                        "run_id": run["id"],
                        "row": 0,
                        "column": "profit",
                        "value": "999",
                    }
                ],
            }
        )


def test_session_ceiling_applies_to_context_runs_and_drilldown(finance):
    service, context = finance
    run = service.run_metric({"context_id": context["id"]})
    child = FinanceStore(service.task, snapshot_ids=[context["bindings"]["actual"]])
    assert child.list_finance_context()["contexts"] == []
    with pytest.raises(FoundryError, match="outside"):
        child.run_metric({"context_id": context["id"]})
    with pytest.raises(FoundryError, match="outside"):
        child.drilldown_fact({"run_id": run["id"], "row": 0})
    with pytest.raises(FoundryError, match="outside"):
        child.save_explanation_draft({"run_ids": [run["id"]], "body": "不可越权"})


def test_mapping_version_is_bound_to_context(finance):
    service, context = finance
    first = service.save_account_map(
        {"rows": [{"account_code": "001", "management_account": "revenue"}]}
    )
    newer = service.save_account_map(
        {
            "parent_id": first["id"],
            "rows": [{"account_code": "001", "management_account": "other"}],
        }
    )
    bound = service.save_context(
        {
            "bindings": context["bindings"],
            "scopes": context["scopes"],
            "account_map_id": first["id"],
        }
    )
    assert service._read("contexts", bound["id"])["account_map_id"] == first["id"]
    assert newer["parent_id"] == first["id"]
    assert (
        service._read("account_maps", first["id"])["rows"][0]["management_account"]
        == "revenue"
    )


def test_finance_calculation_failure_is_persisted_as_failed_run(finance):
    service, context = finance

    run = service.explain_variance(
        {"context_id": context["id"], "actual_filters": ["not", "an", "object"]}
    )

    assert run["execution_status"] == "failed"
    assert run["reproducibility_status"] == "unverified"
    assert run["output_hash"] is None
    assert run["error_code"] == "finance_calculation_failed"
    assert "comparison filters must be objects" in run["error"]
    assert service.analysis.get_run(run["id"])["execution_status"] == "failed"


def test_finance_rerun_output_mismatch_is_non_reproducible(finance, monkeypatch):
    service, context = finance
    values = iter(["1", "2"])

    def changing_metric(_normalized, _spec):
        return {
            "columns": [{"name": "value", "type": "decimal"}],
            "rows": [{"value": next(values)}],
            "diagnostics": [],
        }

    monkeypatch.setattr("foundry.finance_service.evaluate_metric", changing_metric)

    first = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    second = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )

    assert first["execution_status"] == "succeeded"
    assert second["execution_status"] == "succeeded"
    assert second["reproducibility_status"] == "non_reproducible"


def test_price_quantity_run_uses_account_alias_and_explicit_period_filters(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="量价桥")
    service = FinanceStore(task)
    bindings = {}
    for alias, scenario, quantity, price in (
        ("actual", "actual", "12", "11"),
        ("budget", "budget", "10", "10"),
    ):
        path = tmp_path / f"{alias}.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "ledger_id": "L1",
                        "organization_id": "O1",
                        "period": "2026-09",
                        "currency": "CNY",
                        "unit": "元",
                        "scenario": scenario,
                        "科目编码": "6001",
                        "qty": quantity,
                        "unit_price": price,
                        "product": "A",
                    },
                    {
                        "ledger_id": "L1",
                        "organization_id": "O1",
                        "period": "2026-08",
                        "currency": "CNY",
                        "unit": "元",
                        "scenario": scenario,
                        "科目编码": "6001",
                        "qty": "99",
                        "unit_price": "99",
                        "product": "A",
                    },
                    {
                        "ledger_id": "L1",
                        "organization_id": "O1",
                        "period": "2026-09",
                        "currency": "CNY",
                        "unit": "元",
                        "scenario": scenario,
                        "科目编码": "6401",
                        "qty": "99",
                        "unit_price": "99",
                        "product": "A",
                    },
                ],
                ensure_ascii=False,
            )
        )
        bindings[alias] = service.analysis.add_dataset(path, name=alias)["id"]
    context = service.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "scenario": scenario,
                }
                for alias, scenario in (("actual", "actual"), ("budget", "budget"))
            },
            "policies": {
                alias: {"field_map": {"quantity": "qty", "price": "unit_price"}}
                for alias in bindings
            },
        }
    )

    run = service.explain_variance(
        {
            "context_id": context["id"],
            "kind": "price_quantity",
            "dimensions": ["product"],
            "actual_filters": {"period": "2026-09", "account_code": "6001"},
            "baseline_filters": {"period": "2026-09", "account_code": "6001"},
        }
    )

    assert run["execution_status"] == "succeeded"
    assert run["result"]["rows"][0]["total_variance"] == "32"
    assert run["result"]["rows"][0]["quantity_contribution"] == "20"
    assert len(run["result"]["rows"][0]["source_rows"]) == 2
