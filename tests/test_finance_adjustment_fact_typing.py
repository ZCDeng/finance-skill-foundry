import json
from decimal import Decimal

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.fixture
def adjustment_store(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="调整金额事实类型")
    source = tmp_path / "ledger.json"
    source.write_text(json.dumps([
        {"account_code": code, "management_account": account, "amount": amount}
        for code, account, amount in (
            ("6001", "revenue", "200"),
            ("6401", "cost", "60"),
            ("6601", "expense", "10"),
        )
    ]), encoding="utf-8")
    dataset = AnalysisStore(task).add_dataset(source, name="ledger")
    store = FinanceStore(task)
    context = store.save_context({
        "bindings": {"actual": dataset["id"]},
        "scopes": {"actual": {
            "ledger": "adjustment-ledger", "organization": "O1",
            "period": "2026-08", "scenario": "actual",
            "currency": "CNY", "unit": "元",
        }},
    })
    return store, context


def _save_adjustment(store, context, impact, *, parent_id=None, confirm=True):
    spec = {
        "context_id": context["id"], "label": "管理利润调整",
        "amount": impact, "profit_impact": impact,
        "accounts": ["management-adjustment"], "effective_period": "2026-08",
        "basis": "professional_judgment", "bindings": context["bindings"],
    }
    if parent_id is not None:
        spec["parent_id"] = parent_id
    saved = store.finance_adjustment_save(spec)
    return store.finance_adjustment_confirm({"id": saved["id"]}) if confirm else saved


def _run(store, context, adjustment):
    run = store.run_metric({
        "context_id": context["id"], "metric": {"kind": "management_pnl"},
        "adjustment_ids": [adjustment["id"]],
    })
    assert run["execution_status"] == "succeeded", run.get("error")
    return run


def _facts(store, run):
    return {
        fact["column"]: fact
        for fact in store.prepare_explanation({
            "run_ids": [run["id"]], "fact_view": "inspection",
        })["facts"]
        if fact["row"] == 0
    }


@pytest.mark.parametrize("impact,expected", [
    ("100", "230"),
    ("0", "130"),
    ("-130", "0"),
    ("-140.125", "-10.125"),
    ("0.000000000000000001", "130.000000000000000001"),
])
def test_adjusted_totals_are_decimal_facts_bound_to_the_actual_run(
    adjustment_store, impact, expected,
):
    store, context = adjustment_store
    adjustment = _save_adjustment(store, context, impact)
    run = _run(store, context, adjustment)
    row = run["result"]["rows"][0]
    assert row["profit"] == row["source_total"] == "130"
    assert Decimal(row["adjusted_total"]) == Decimal(expected)
    assert row["applied_adjustment_ids"] == [adjustment["id"]]
    types = {column["name"]: column["type"] for column in run["result"]["columns"]}
    assert types["source_total"] == types["adjusted_total"] == "DECIMAL"
    assert types["period"] == types["organization"] == "VARCHAR"

    facts = _facts(store, run)
    for column, value in (("source_total", "130"), ("adjusted_total", expected)):
        fact = facts[column]
        assert Decimal(fact["value"]) == Decimal(value)
        assert fact["unit"] == row["unit"] == "元"
        assert fact["semantics"]["role"] == "amount"
        assert fact["display_value"] == f"{Decimal(value):,f} 元"
        assert fact["run_id"] == run["id"]
        assert fact["column"] == column
        assert fact["source_trace"]["output_hash"] == run["output_hash"]
        assert fact["source_trace"]["input_hashes"] == run["input_hashes"]
        assert fact["source_trace"]["source_hashes"] == run["source_hashes"]
        assert fact["source_trace"]["source_rows"] == row["source_rows"]
        assert fact["source_trace"]["source_row_count"] == 3
        assert fact["evidence_eligibility"]["counts_as_amount_evidence"] is True

    fact = facts["adjusted_total"]
    draft = store.save_explanation_draft({
        "run_ids": [run["id"]], "fact_ids": [fact["id"]],
        "body": "调整后管理利润为 {{fact:" + fact["id"] + "}}。",
    })
    claim = next(claim for claim in draft["claims"] if claim.get("fact_id") == fact["id"])
    assert claim["verification_status"] == "matches_run"
    assert Decimal(claim["value"]) == Decimal(expected)
    assert not any(issue["code"] == "unknown_fact" for issue in draft["explanation_check"]["issues"])


def test_replaced_adjustment_gets_new_fact_without_rewriting_old_run_or_draft(adjustment_store):
    store, context = adjustment_store
    old_adjustment = _save_adjustment(store, context, "100")
    old_run = _run(store, context, old_adjustment)
    old_fact = _facts(store, old_run)["adjusted_total"]
    old_draft = store.save_explanation_draft({
        "run_ids": [old_run["id"]], "fact_ids": [old_fact["id"]],
        "body": "调整后管理利润为 {{fact:" + old_fact["id"] + "}}。",
    })
    archives = [
        store.analysis.root / "runs" / (old_run["id"] + ".json"),
        store.analysis.root / "drafts" / (old_draft["id"] + ".json"),
        store.analysis.root / "completions" / (old_draft["completion"]["id"] + ".json"),
    ]
    before = {path: path.read_bytes() for path in archives}

    replacement = _save_adjustment(store, context, "120", parent_id=old_adjustment["id"])
    new_run = _run(store, context, replacement)
    new_fact = _facts(store, new_run)["adjusted_total"]
    assert old_fact["value"] == "230"
    assert new_fact["value"] == "250"
    assert new_fact["id"] != old_fact["id"]
    assert new_fact["run_id"] == new_run["id"] != old_run["id"]
    assert new_fact["source_trace"]["output_hash"] == new_run["output_hash"] != old_run["output_hash"]
    assert new_run["result"]["applied_adjustment_ids"] == [replacement["id"]]
    assert {path: path.read_bytes() for path in archives} == before


def test_unconfirmed_adjustment_does_not_create_adjusted_facts(adjustment_store):
    store, context = adjustment_store
    pending = _save_adjustment(store, context, "100", confirm=False)
    run = _run(store, context, pending)
    assert run["result"]["rows"][0]["profit"] == "130"
    assert run["result"]["ignored_adjustments"] == [{"id": pending["id"], "reason": "not_confirmed"}]
    facts = _facts(store, run)
    assert "source_total" not in facts
    assert "adjusted_total" not in facts
