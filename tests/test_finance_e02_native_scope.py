"""E02 native price/quantity scope, missing base price, and zero actual volume.

Ledger B engineering checks. They do not rewrite historical R3 and they do not
score an original model run.
"""
import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_requirements import (
    _price_quantity_input_gaps,
    _scope_matches,
    _unanswered_message,
    check_requirements,
    save_requirements,
)
from foundry.finance_service import FinanceStore
from foundry.finance_variance import price_quantity_bridge
from foundry.task import TaskStore
from test_finance_requirements import _claim, _run


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
                                  "volume_contribution", "mix_contribution", "price_contribution",
                                  "interaction", "residual"}]


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


BALANCED = [_row("A", "budget", "10", "10"), _row("A", "actual", "10", "11")]


def test_a_baseline_period_the_sources_do_not_hold_is_not_proven(tmp_path):
    prior = {**SCOPE, "period": "2025-09"}
    case = dual_case(tmp_path, BALANCED, requirement_scope={"actual": dict(SCOPE), "baseline": prior})
    checked = _checked(case)
    assert checked["items"][0]["status"] == "pending"
    assert checked["original_requirements_completed"] is False


def test_a_requirement_field_no_source_states_is_not_proven(tmp_path):
    case = dual_case(tmp_path, BALANCED, requirement_scope={**SCOPE, "region": "华东"})
    assert _checked(case)["items"][0]["status"] == "pending"


def test_a_requirement_field_every_source_states_is_proven(tmp_path):
    east = {**SCOPE, "region": "华东"}
    case = dual_case(tmp_path, BALANCED, public_scope=east, price_scope=east, requirement_scope=dict(east))
    assert _checked(case)["items"][0]["status"] == "answered"


def test_a_baseline_scenario_the_run_did_not_compare_is_not_proven(tmp_path):
    case = dual_case(tmp_path, BALANCED, requirement_scope={**SCOPE, "baseline_scenario": "forecast"})
    assert _checked(case)["items"][0]["status"] == "pending"


def test_the_baseline_scenario_the_run_compared_is_proven(tmp_path):
    case = dual_case(tmp_path, BALANCED, requirement_scope={**SCOPE, "baseline_scenario": "budget"})
    assert _checked(case)["items"][0]["status"] == "answered"


def _gap_run(**updates):
    return {"id": "gap", "method": "quantity_then_price", "finance_scope": {"pq": {"organization": "O"}},
            "result": {"method": "quantity_then_price", "diagnostics": [
                {"code": "price_quantity_missing", "group": {"product": "B"}, "message": "缺基价"}]}, **updates}


def test_an_unrelated_input_gap_does_not_reopen_an_answered_plain_revenue_item(tmp_path):
    analysis = AnalysisStore(TaskStore(tmp_path / "var").create(title="plain revenue"))
    requirement = save_requirements(analysis, {
        "question": "收入差异是多少", "scope": {"ledger": "L1"},
        "items": [{"id": "revenue", "metric": "revenue", "requires_drilldown": False}],
    })
    plain = _run(analysis, id_suffix="plain")
    gap = _run(analysis, id_suffix="gap", method="quantity_then_price", result={
        "method": "quantity_then_price", "columns": [], "rows": [],
        "diagnostics": [{"code": "price_quantity_missing", "group": {"product": "B"}, "message": "缺基价"}],
    })
    item = check_requirements(analysis, {
        "requirements_id": requirement["id"], "run_ids": [plain["id"], gap["id"]],
        "claims": [_claim(plain, row=0, column="contribution", value="20")],
    })["items"][0]
    assert item["status"] == "answered"
    assert "price_quantity_input_gaps" not in item


def test_a_revenue_item_answered_from_the_gapped_bridge_stays_pending(tmp_path):
    rows = [*BALANCED, _row("B", "actual", "5", "12")]
    case = dual_case(tmp_path, rows, items=[{"id": "revenue", "metric": "revenue", "requires_drilldown": False}])
    item = _checked(case)["items"][0]
    assert item["status"] == "pending"
    assert any(gap.get("product") == "B" for gap in item["price_quantity_input_gaps"])


def test_an_input_gap_stays_with_its_own_method_and_scope():
    item = {"metric": "price_quantity", "dimensions": {"method": "quantity_then_price"}}
    latest = {"scope": {"organization": "O"}}
    assert _price_quantity_input_gaps(item, {"gap": _gap_run()}, [], latest)
    assert _price_quantity_input_gaps(item, {"gap": _gap_run(finance_scope={"pq": {"period": "2026-09"}})}, [], latest)
    other_scope = _gap_run(finance_scope={"pq": {"organization": "P"}})
    assert _price_quantity_input_gaps(item, {"gap": other_scope}, [], latest) == []
    other_method = _gap_run(method="volume_mix_price", result={**_gap_run()["result"], "method": "volume_mix_price"})
    assert _price_quantity_input_gaps(item, {"gap": other_method}, [], latest) == []


def side_case(tmp_path, *, aliases, data, requirement_scope, method="quantity_then_price", run_extra=None):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="E02 sides"))
    bindings = {alias: _write_dataset(service, tmp_path, alias, data[alias])["id"] for alias in aliases}
    context = service.save_context({"bindings": bindings, "scopes": aliases})
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "question": "分解差异", "scope": requirement_scope,
        "items": [{"id": "basket", "metric": "price_quantity", "dimensions": {"method": method},
                   "requires_drilldown": False}],
    })
    run = service.explain_variance({
        "context_id": context["id"], "kind": "price_quantity", "method": method,
        "actual_scenario": "actual", "baseline_scenario": "budget", **(run_extra or {}),
    })
    assert run["execution_status"] == "succeeded", run.get("error")
    return _checked((service, context, requirement, run, service.prepare_explanation({"run_ids": [run["id"]]})))


NOTE = [{"name": "note", "value": "retained corroboration"}]
PRIOR = {**SCOPE, "period": "2025-09"}
PERIOD_FILTERS = {"actual_filters": {"period": "2026-09"}, "baseline_filters": {"period": "2025-09"}}


@pytest.mark.parametrize("field", ["ledger", "organization", "currency", "unit"])
@pytest.mark.parametrize("aliases", [("price_quantity",), ("public_facts", "price_quantity")])
def test_row_text_does_not_stand_in_for_a_scope_the_inputs_never_stated(tmp_path, field, aliases):
    rows = [{**row, field: SCOPE[field]} for row in BALANCED]
    open_scope = {key: value for key, value in SCOPE.items() if key != field}
    checked = side_case(tmp_path, aliases={alias: open_scope for alias in aliases},
                        data={"public_facts": NOTE, "price_quantity": rows}, requirement_scope=dict(SCOPE))
    assert checked["items"][0]["status"] == "pending"


@pytest.mark.parametrize("requirement_scope", [
    {"actual": {"ledger": "L"}, "baseline": {"ledger": "L"}, "organization": "WRONG"},
    {"source": {"ledger": "WRONG"}},
])
@pytest.mark.parametrize("aliases", [("price_quantity",), ("public_facts", "price_quantity")])
def test_a_source_scope_is_part_of_the_proof(tmp_path, requirement_scope, aliases):
    checked = side_case(tmp_path, aliases={alias: dict(SCOPE) for alias in aliases},
                        data={"public_facts": NOTE, "price_quantity": BALANCED}, requirement_scope=requirement_scope)
    assert checked["items"][0]["status"] == "pending"


def test_a_flat_scenario_the_run_did_not_compare_is_not_proven(tmp_path):
    case = dual_case(tmp_path, BALANCED, requirement_scope={**SCOPE, "scenario": "forecast"})
    assert _checked(case)["items"][0]["status"] == "pending"


def test_a_flat_scenario_the_run_compared_is_proven(tmp_path):
    case = dual_case(tmp_path, BALANCED, requirement_scope={**SCOPE, "scenario": "actual"})
    assert _checked(case)["items"][0]["status"] == "answered"


def test_paired_sides_on_different_periods_keep_answering_a_flat_requirement(tmp_path):
    checked = side_case(
        tmp_path, aliases={"actual": dict(SCOPE), "budget": PRIOR},
        data={"actual": [_row("A", "actual", "10", "11")], "budget": [_row("A", "budget", "10", "10")]},
        requirement_scope=dict(SCOPE), run_extra=PERIOD_FILTERS)
    assert checked["items"][0]["status"] == "answered", checked


def test_side_scopes_on_a_native_basket_keep_answering_a_flat_requirement(tmp_path):
    def basket(scenario, price):
        return [{**_row(product, scenario, "5", price), "quantity_unit": "件", "currency": "CNY", "unit": "元"}
                for product in ("A", "B")]

    checked = side_case(tmp_path, aliases={"this_year": dict(SCOPE), "last_year": PRIOR},
                        data={"this_year": basket("actual", "11"), "last_year": basket("budget", "10")},
                        requirement_scope=dict(SCOPE), method="volume_mix_price", run_extra=PERIOD_FILTERS)
    assert checked["items"][0]["status"] == "answered", checked


OPEN_PERIOD = {key: value for key, value in SCOPE.items() if key != "period"}


def _periods(gap_period):
    closed = [{**row, "period": period} for period in ("2026-08", "2026-09") for row in BALANCED]
    return [*closed, {**_row("B", "actual", "5", "12"), "period": gap_period}]


def test_an_input_gap_in_another_period_of_the_table_is_not_this_items_gap(tmp_path):
    checked = side_case(tmp_path, aliases={"price_quantity": OPEN_PERIOD},
                        data={"price_quantity": _periods("2026-08")}, requirement_scope=dict(SCOPE))
    assert checked["items"][0]["status"] == "answered", checked


def test_an_input_gap_in_the_items_own_period_still_holds_it(tmp_path):
    checked = side_case(tmp_path, aliases={"price_quantity": OPEN_PERIOD},
                        data={"price_quantity": _periods("2026-09")}, requirement_scope=dict(SCOPE))
    assert checked["items"][0]["status"] == "pending"
    assert checked["items"][0]["price_quantity_input_gaps"]


def test_a_product_in_the_requirement_scope_pins_the_gap_like_a_dimension(tmp_path):
    rows = [*BALANCED, _row("B", "actual", "5", "12")]
    checked = side_case(tmp_path, aliases={"price_quantity": dict(SCOPE)}, data={"price_quantity": rows},
                        requirement_scope={**SCOPE, "product": "A"})
    assert checked["items"][0]["status"] == "answered", checked
