"""E02 native price/quantity scope, missing base price, and zero actual volume.

Ledger B engineering checks. They do not rewrite historical R3 and they do not
score an original model run.
"""
import json

import pytest

from foundry.finance_requirements import _scope_matches, _unanswered_message, check_requirements
from foundry.finance_service import FinanceStore
from foundry.finance_variance import price_quantity_bridge
from foundry.task import TaskStore


SCOPE = {"ledger": "L", "organization": "O", "currency": "CNY", "unit": "元", "period": "2026-09"}


def _write_dataset(service, tmp_path, name, rows):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return service.analysis.add_dataset(path, name=name)


def dual_case(tmp_path, rows, *, public_scope=None, price_scope=None, method="quantity_then_price",
              items=None, requirement_scope=None):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="E02 dual alias"))
    public_scope = dict(SCOPE if public_scope is None else public_scope)
    price_scope = dict(SCOPE if price_scope is None else price_scope)
    public = _write_dataset(service, tmp_path, "public_facts", [{"name": "note", "value": "retained corroboration"}])
    prices = _write_dataset(service, tmp_path, "price_quantity", rows)
    context = service.save_context({
        "bindings": {"public_facts": public["id"], "price_quantity": prices["id"]},
        "scopes": {"public_facts": public_scope, "price_quantity": price_scope},
    })
    if items is None:
        items = [{"id": "basket", "metric": "price_quantity", "dimensions": {"method": method},
                  "requires_drilldown": False}]
    payload = {"context_id": context["id"], "question": "分解各产品差异并说明可比范围", "items": items}
    if requirement_scope is not None:
        payload["scope"] = requirement_scope
    requirement = service.analysis_requirements_save(payload)
    run = service.explain_variance({
        "context_id": context["id"], "kind": "price_quantity", "method": method,
        "actual_scenario": "actual", "baseline_scenario": "budget",
    })
    assert run["execution_status"] == "succeeded", run.get("error")
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    return service, context, requirement, run, prepared


def _claims(prepared):
    return [fact["reference_template"]["claim"] for fact in prepared["facts"]
            if fact["column"] in {"actual", "baseline", "total_variance", "quantity_contribution",
                                  "price_contribution", "interaction", "residual"}]


def _checked(case):
    service, _, requirement, run, prepared = case
    return check_requirements(service.analysis, {
        "requirements_id": requirement["id"], "run_ids": [run["id"]], "claims": _claims(prepared),
    })


def _row(product, scenario, quantity, price):
    return {"product": product, "scenario": scenario, "quantity": quantity, "price": price}


def test_generic_comparison_with_two_aliases_stays_ambiguous():
    scope = {"ledger": "L1", "organization": "O1", "unit": "万元"}
    row = {"closing_cash": "90", "ledger": "L1", "organization": "O1", "unit": "万元"}
    variance = {"finance_scope": {"pq": scope, "other": scope}, "result": {"domain": "foundry.finance.variance.v1"}}
    assert not _scope_matches(variance, row, scope)
    assert _scope_matches(
        {"finance_scope": {"pq": scope}, "result": {"domain": "foundry.finance.variance.v1"}}, row, scope)


def test_native_dual_alias_scope_counts_participating_rows_and_keeps_public_facts(tmp_path):
    rows = [_row("A", "budget", "10", "10"), _row("A", "actual", "10", "11"),
            _row("B", "budget", "4", "8"), _row("B", "actual", "5", "9")]
    case = dual_case(tmp_path, rows)
    service, context, _, run, _ = case
    checked = _checked(case)
    assert checked["items"][0]["status"] == "answered", checked
    assert checked["original_requirements_completed"] is True
    assert set(run["bindings"]) == {"public_facts", "price_quantity"}
    assert set(service._read("contexts", context["id"])["bindings"]) == {"public_facts", "price_quantity"}
    assert run["source_hashes"]["public_facts"]
    assert run["source_hashes"]["price_quantity"]


def test_corroborating_currency_conflict_names_the_field_and_keeps_the_source(tmp_path):
    """A stored context sorts alias keys, so the requirement takes the price_quantity scope.

    public_facts then disagrees on currency. That is a named corroborating conflict, not a
    second comparison side and not a reason to drop the binding.
    """
    rows = [_row("A", "budget", "10", "10"), _row("A", "actual", "10", "11")]
    case = dual_case(tmp_path, rows, price_scope={**SCOPE, "currency": "USD"})
    _, _, _, run, _ = case
    checked = _checked(case)
    item = checked["items"][0]
    assert item["status"] == "pending"
    conflicts = [conflict for location in item["locations"]
                 for conflict in location.get("evidence", {}).get("conflicts", [])]
    assert any(conflict.get("field") == "currency" and conflict.get("alias") == "public_facts"
               and conflict.get("role") == "corroborating" and conflict.get("observed") == "CNY"
               and conflict.get("participating_alias") == "price_quantity" for conflict in conflicts)
    assert any(location.get("evidence", {}).get("corroborating_aliases") == ["public_facts"]
               for location in item["locations"])
    assert "public_facts" in run["bindings"]
    assert "没有已引用的结果行" not in _unanswered_message(item)


def test_participating_currency_conflict_names_the_price_quantity_field(tmp_path):
    rows = [_row("A", "budget", "10", "10"), _row("A", "actual", "10", "11")]
    usd = {**SCOPE, "currency": "USD"}
    case = dual_case(tmp_path, rows, public_scope=usd, price_scope=usd, requirement_scope=dict(SCOPE))
    checked = _checked(case)
    item = checked["items"][0]
    assert item["status"] == "pending"
    conflicts = [conflict for location in item["locations"]
                 for conflict in location.get("evidence", {}).get("conflicts", [])]
    assert any(conflict.get("field") == "currency" and conflict.get("alias") == "price_quantity"
               and conflict.get("role") == "participating" and conflict.get("observed") == "USD"
               and conflict.get("expected") == "CNY" for conflict in conflicts)
    assert "没有已引用的结果行" not in _unanswered_message(item)


def test_missing_base_price_does_not_complete_the_basket_or_invent_zero(tmp_path):
    rows = [_row("A", "budget", "10", "10"), _row("A", "actual", "10", "11"), _row("B", "actual", "5", "12")]
    case = dual_case(tmp_path, rows, items=[
        {"id": "basket", "metric": "price_quantity", "dimensions": {"method": "quantity_then_price"},
         "requires_drilldown": False},
        {"id": "product-a", "metric": "price_quantity",
         "dimensions": {"method": "quantity_then_price", "product": "A"}, "requires_drilldown": False},
    ])
    _, _, _, run, _ = case
    products = {row.get("product") for row in run["result"]["rows"]}
    assert products == {"A"}
    assert all(row.get("baseline") != "0" for row in run["result"]["rows"])
    assert any(item.get("code") == "price_quantity_missing" and (item.get("group") or {}).get("product") == "B"
               for item in run["result"]["diagnostics"])
    checked = _checked(case)
    by_id = {item["id"]: item for item in checked["items"]}
    assert by_id["product-a"]["status"] == "answered"
    assert by_id["basket"]["status"] == "pending"
    assert any(gap.get("code") == "price_quantity_missing" and gap.get("product") == "B"
               for gap in by_id["basket"]["price_quantity_input_gaps"])
    assert checked["original_requirements_completed"] is False
    assert "price_quantity_missing" in by_id["basket"]["message"]


def test_explicit_zero_base_quantity_with_a_price_stays_calculable(tmp_path):
    rows = [_row("A", "budget", "10", "10"), _row("A", "actual", "10", "11"),
            _row("B", "budget", "0", "12"), _row("B", "actual", "5", "12")]
    case = dual_case(tmp_path, rows)
    _, _, _, run, _ = case
    product_b = next(row for row in run["result"]["rows"] if row.get("product") == "B")
    assert product_b["quantity_contribution"] == "60"
    assert product_b["price_contribution"] == "0"
    assert product_b["baseline"] == "0"
    assert not any(item.get("code") == "price_quantity_missing" for item in run["result"]["diagnostics"])
    checked = _checked(case)
    assert checked["items"][0]["status"] == "answered", checked
    assert "price_quantity_input_gaps" not in checked["items"][0]


def test_zero_actual_volume_keeps_the_money_total_and_does_not_invent_mix_price_or_a_unit():
    rows = [_row("A", "budget", "5", "10"), _row("B", "budget", "5", "20"),
            _row("A", "actual", "0", "12"), _row("B", "actual", "0", "18")]
    for row in rows:
        row.update({"ledger": "L", "organization": "O", "period": "2026-09", "currency": "CNY", "unit": "元"})
    result = price_quantity_bridge(rows, {"method": "volume_mix_price"})
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["actual"] == "0"
    assert row["baseline"] == "150"
    assert row["total_variance"] == "-150"
    assert row["actual_volume"] == "0"
    assert row["volume_contribution"] is None
    assert row["mix_contribution"] is None
    assert row["price_contribution"] is None
    assert row["residual"] is None
    assert row["quantity_unit"] is None
    assert row["applicability"] == "zero_actual_volume"
    assert row["comparison_status"] == "limited"
    assert "volume_mix_price_zero_actual_volume" in row["reason_codes"]
    assert "件" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("quantity", ["0", "-1"])
def test_a_zero_or_negative_baseline_quantity_is_not_the_zero_actual_volume_total(quantity):
    rows = [_row("A", "budget", quantity, "10"), _row("B", "budget", "5", "20"),
            _row("A", "actual", "4", "12"), _row("B", "actual", "5", "18")]
    for row in rows:
        row["quantity_unit"] = "item"
    result = price_quantity_bridge(rows, {"method": "volume_mix_price"})
    row = result["rows"][0]
    assert row["total_variance"] is None
    assert row["applicability"] == "not_comparable"
    assert "volume_mix_price_nonpositive_quantity" in row["reason_codes"]
    assert "volume_mix_price_zero_actual_volume" not in row["reason_codes"]
