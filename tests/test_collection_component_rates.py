"""Component collection rates, using engineering examples independent of eval fixtures."""

import json
import random
from decimal import Decimal

import pytest

from foundry.analysis import AnalysisStore
from foundry.collection_metrics import evaluate_collection_health, resolve_entities, resolve_params
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


COMPONENTS = ("current_due", "current_collection", "opening_ar", "arrears_collection")
BASE = dict(zip(COMPONENTS, ("1200", "900", "600", "180")))


def _result(values, tables=None, units=None, scopes=None, **entity_options):
    inputs = {"entities": [{"name": "工程服务部", "values": values, **entity_options}]}
    entities = (resolve_entities(inputs, tables or {}, units) if scopes is None
                else resolve_entities(inputs, tables or {}, units, scopes))
    result = evaluate_collection_health(entities, resolve_params({}))
    return {(r["metric_key"], r["scenario"]): r for r in result["rows"]}, result


def _bound(values, units=None):
    rows = [
        {"item": key, "amount": value, "unit": (units or {}).get(key, "万元"),
         "source": {"dataset_id": "engineering-ledger", "source_row": i + 1}}
        for i, (key, value) in enumerate(values.items())
    ]
    refs = {key: {"alias": "ledger", "match": {"item": key}, "column": "amount"} for key in values}
    return refs, {"ledger": rows}


@pytest.mark.parametrize(("arrears", "total"), [("180", "60"), ("540", "80"), ("450", "75")])
def test_total_can_be_lower_higher_or_equal_to_current(arrears, total):
    refs, tables = _bound({**BASE, "arrears_collection": arrears})
    rows, _ = _result(refs, tables)
    for key, expected, inputs in [
        ("collection_rate_current", "75", set(COMPONENTS[:2])),
        ("collection_rate_total", total, set(COMPONENTS)),
    ]:
        row = rows[key, "本期"]
        assert Decimal(row["value"]) == Decimal(expected) / 100
        assert row["unit"] == "ratio" and row["display_value"] == f"{expected}.00%"
        assert row["estimate"] is False
        assert set(row["inputs"]) == inputs
        assert len(row["source_rows"]) == len(inputs)
        assert {s["dataset_id"] for s in row["source_rows"]} == {"engineering-ledger"}
        assert {s["column"] for s in row["source_rows"]} == {"amount"}
        assert "手填" not in row["note"]


def test_decimal_components_generalize_beyond_whole_number_examples():
    rng = random.Random(42917)
    for _ in range(12):
        amounts = [Decimal(rng.randint(1, 50000)) / 100 for _ in COMPONENTS]
        rows, _ = _result(dict(zip(COMPONENTS, map(str, amounts))))
        due, collected, opening, arrears = amounts
        assert Decimal(rows["collection_rate_current", "本期"]["value"]) == collected / due
        assert Decimal(rows["collection_rate_total", "本期"]["value"]) == (collected + arrears) / (due + opening)


@pytest.mark.parametrize("missing", COMPONENTS)
def test_missing_components_are_skipped_and_never_assumed_zero(missing):
    values = {key: value for key, value in BASE.items() if key != missing}
    rows, result = _result(values)
    assert ("collection_rate_total", "本期") not in rows
    assert (("collection_rate_current", "本期") in rows) == (missing not in COMPONENTS[:2])
    skipped = {item["metric_key"]: item for d in result["diagnostics"] for item in d.get("skipped", [])}
    assert "collection_rate_total" in skipped
    assert missing in " ".join(skipped["collection_rate_total"]["needs"])


@pytest.mark.parametrize(("due", "opening", "current_exists", "total_exists"), [
    ("0", "600", False, True), ("1200", "-1200", True, False), ("0", "0", False, False),
])
def test_zero_denominators_skip_only_the_undefined_rates(due, opening, current_exists, total_exists):
    rows, result = _result({**BASE, "current_due": due, "opening_ar": opening})
    assert (("collection_rate_current", "本期") in rows) is current_exists
    assert (("collection_rate_total", "本期") in rows) is total_exists
    skipped = {item["metric_key"]: item for d in result["diagnostics"] for item in d.get("skipped", [])}
    for key, exists in [("collection_rate_current", current_exists), ("collection_rate_total", total_exists)]:
        if not exists:
            assert skipped[key]["reason"] == "zero_denominator"
            assert "分母为零" in skipped[key]["message"]


def test_known_zero_arrears_is_not_missing():
    rows, _ = _result({**BASE, "opening_ar": "0", "arrears_collection": "0"})
    assert rows["collection_rate_current", "本期"]["value"] == rows["collection_rate_total", "本期"]["value"]


def test_known_zero_collections_produce_zero_rates():
    rows, _ = _result({**BASE, "current_collection": "0", "arrears_collection": "0"})
    assert Decimal(rows["collection_rate_current", "本期"]["value"]) == 0
    assert Decimal(rows["collection_rate_total", "本期"]["value"]) == 0


def test_manual_components_are_marked_for_current_and_prior_rows():
    prior = dict(zip(COMPONENTS, ("1000", "800", "500", "400")))
    rows, _ = _result({**BASE, **{f"{k}_py": v for k, v in prior.items()}})
    for key, current, previous in [("collection_rate_current", "75", "80"), ("collection_rate_total", "60", "80")]:
        for scenario, expected in [("本期", current), ("上年同期", previous)]:
            row = rows[key, scenario]
            assert Decimal(row["value"]) == Decimal(expected) / 100
            assert "含手填数" in row["note"] and row["source_rows"] == []
        change = rows[key, "变动"]
        assert Decimal(change["value"]) == Decimal(current) - Decimal(previous)
        assert change["unit"] == "百分点"


def test_reported_rates_remain_available_without_components():
    rows, _ = _result({"collection_rate_current": "72.5%", "collection_rate_total": "0.68"})
    assert Decimal(rows["collection_rate_current", "本期"]["value"]) == Decimal("0.725")
    assert Decimal(rows["collection_rate_total", "本期"]["value"]) == Decimal("0.68")
    for row in rows.values():
        if row["metric_key"].startswith("collection_rate_"):
            assert "套表报数" in row["formula"] and "含手填数" in row["note"]


def test_components_take_precedence_without_falling_back_on_partial_or_zero_inputs():
    reported = {"collection_rate_current": "99%", "collection_rate_total": "98%"}
    rows, _ = _result({**reported, **BASE})
    assert Decimal(rows["collection_rate_current", "本期"]["value"]) == Decimal("0.75")
    assert Decimal(rows["collection_rate_total", "本期"]["value"]) == Decimal("0.60")
    rows, _ = _result({**reported, "current_due": "1200"})
    assert ("collection_rate_current", "本期") not in rows
    assert ("collection_rate_total", "本期") not in rows
    rows, _ = _result({**reported, **BASE, "current_due": "0", "opening_ar": "0"})
    assert ("collection_rate_current", "本期") not in rows
    assert ("collection_rate_total", "本期") not in rows


def test_derived_rates_feed_existing_metrics_with_component_sources():
    refs, tables = _bound({**BASE, "revenue": "1500", "cost": "900", "period_expense": "150",
                           "ar_begin": "50", "ar_end": "80", "impairment": "0"})
    rows, result = _result(refs, tables, sensitivity=True)
    assert Decimal(rows["collection_gap", "本期"]["value"]) == 5
    assert Decimal(rows["collection_gap_total", "本期"]["value"]) == -10
    implied = Decimal(rows["implied_collection", "本期"]["value"])
    assert Decimal(rows["implied_vs_reported", "本期"]["value"]) == implied - 60
    for key in ("collection_gap_total", "implied_vs_reported"):
        row = rows[key, "本期"]
        assert set(COMPONENTS) <= set(row["inputs"])
        assert "collection_rate_total" not in row["inputs"]
    assert result["sensitivity"][0]["current"]["collection_rate"] == "0.75"


def test_risk_signal_uses_derived_year_on_year_rate_and_keeps_sources():
    refs, tables = _bound({**BASE, "current_due_py": "1000", "current_collection_py": "800",
                           "operating_profit": "10"})
    rows, _ = _result(refs, tables)
    risk = rows["risk_score", "本期"]
    assert "收缴率同比下降（1分）" in risk["note"]
    assert {"current_due", "current_collection", "current_due_py", "current_collection_py"} <= set(risk["inputs"])
    assert len(risk["source_rows"]) == 5


def _sum_bound():
    rows = [
        {"project": "a", **dict(zip(COMPONENTS, ("700", "490", "100", "70"))), "unit": "万元",
         "source": {"dataset_id": "engineering-projects", "source_row": 1}},
        {"project": "b", **dict(zip(COMPONENTS, ("300", "210", "400", "280"))), "unit": "万元",
         "source": {"dataset_id": "engineering-projects", "source_row": 2}},
        {"project": "excluded", **dict(zip(COMPONENTS, ("999", "123", "456", "321"))), "unit": "元",
         "source": {"dataset_id": "engineering-projects", "source_row": 3}},
    ]
    refs = {key: {"alias": "projects", "column": key, "sum_where": {"project": ["a", "b"]}} for key in COMPONENTS}
    return refs, {"projects": rows}


def test_component_sums_preserve_every_used_source_cell():
    refs, tables = _sum_bound()
    rows, _ = _result(refs, tables)
    for key, count in [("collection_rate_current", 4), ("collection_rate_total", 8)]:
        row = rows[key, "本期"]
        assert Decimal(row["value"]) == Decimal("0.70")
        assert len(row["source_rows"]) == count
        assert {r["source_row"] for r in row["source_rows"]} == {1, 2}


@pytest.mark.parametrize("blank", [None, "", "—"])
def test_component_sums_refuse_incomplete_selected_rows(blank):
    refs, tables = _sum_bound()
    tables["projects"][1]["arrears_collection"] = blank
    with pytest.raises(FoundryError, match="empty|blank|missing"):
        _result(refs, tables)


@pytest.mark.parametrize("override", [False, True])
def test_component_cell_units_cannot_be_laundered_with_a_reference_override(override):
    refs, tables = _bound(BASE, {"arrears_collection": "元"})
    if override:
        refs["arrears_collection"]["unit"] = "万元"
    with pytest.raises(FoundryError, match="unit"):
        _result(refs, tables)


def test_component_source_scope_and_row_unit_conflicts_are_rejected():
    refs, tables = _bound(BASE)
    with pytest.raises(FoundryError, match="unit"):
        _result(refs, tables, {"ledger": "亿元"})


def test_missing_component_units_require_a_consistent_declared_unit():
    refs, tables = _bound(BASE, {"arrears_collection": None})
    with pytest.raises(FoundryError, match="unit"):
        _result(refs, tables)
    rows, _ = _result(refs, tables, {"ledger": "万"})
    assert Decimal(rows["collection_rate_total", "本期"]["value"]) == Decimal("0.60")
    refs, tables = _sum_bound()
    tables["projects"][1]["unit"] = None
    with pytest.raises(FoundryError, match="unit"):
        _result(refs, tables)
    rows, _ = _result(refs, tables, {"projects": "万元"})
    assert Decimal(rows["collection_rate_total", "本期"]["value"]) == Decimal("0.70")


@pytest.mark.parametrize("override", [False, True])
def test_component_sums_reject_mixed_units_even_with_an_override(override):
    refs, tables = _sum_bound()
    tables["projects"][1]["unit"] = "元"
    if override:
        for ref in refs.values():
            ref["unit"] = "万元"
    with pytest.raises(FoundryError, match="unit"):
        _result(refs, tables)


@pytest.mark.parametrize("mode", ["text", "scale", "unit"])
def test_component_inputs_must_be_amounts_not_percentages(mode):
    refs, tables = _bound(BASE)
    if mode == "text":
        tables["ledger"][0]["amount"] = "1200%"
    elif mode == "scale":
        refs["current_due"]["scale"] = "percent"
    else:
        for row in tables["ledger"]:
            row["unit"] = "%"
    with pytest.raises(FoundryError, match="amount|unit"):
        _result(refs, tables)


@pytest.mark.parametrize("source_unit", ["pct", "PCT", "percent", "百分比", "百分率", "fraction", "比率", "ratio"])
def test_component_amounts_reject_rate_unit_aliases(source_unit):
    refs, tables = _bound(BASE, dict.fromkeys(COMPONENTS, source_unit))
    with pytest.raises(FoundryError, match="amount unit"):
        _result(refs, tables)


@pytest.mark.parametrize("manual_names", [(), ("arrears_collection",), COMPONENTS])
def test_bound_components_run_through_finance_service_and_drilldown(tmp_path, manual_names):
    task = TaskStore(tmp_path / "var").create(title="组件收缴率工程回归")
    service = FinanceStore(task)
    path = tmp_path / "engineering-collections.json"
    path.write_text(json.dumps([{"项目": "测试项目", **BASE}], ensure_ascii=False))
    dataset = AnalysisStore(task).add_dataset(path, name="engineering-collections")
    context = service.save_context({"bindings": {"ledger": dataset["id"]},
                                    "scopes": {"ledger": {"currency": "CNY", "unit": "万元"}}})
    scenario = service.save_scenario({"context_id": context["id"], "kind": "collection_health",
                                     "inputs": {"entities": [{"name": "测试项目", "values": {
                                         key: BASE[key] if key in manual_names else {
                                             "alias": "ledger", "match": {"项目": "测试项目"}, "column": key}
                                         for key in COMPONENTS}}]}})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    for index, row in enumerate(run["result"]["rows"]):
        if row["metric_key"] == "collection_rate_total" and row["scenario"] == "本期":
            assert Decimal(row["value"]) == Decimal("0.60")
            assert ("手填" in row["note"]) is bool(manual_names)
            assert row["manual_inputs"] == sorted(manual_names)
            assert {ref["column"] for ref in row["source_rows"]} == set(COMPONENTS) - set(manual_names)
            assert len(row["source_rows"]) == 4 - len(manual_names)
            # Drilldown deduplicates the source table row; four column refs remain on the result.
            evidence = service.drilldown_fact({"run_id": run["id"], "row": index})
            assert evidence["total"] == (0 if len(manual_names) == 4 else 1)
            expected = "missing" if len(manual_names) == 4 else "unverified" if manual_names else "verified"
            assert evidence["provenance_status"] == expected
            break
    else:
        pytest.fail("component-derived collection_rate_total row missing")


def test_manual_inputs_are_derived_per_row_and_not_inherited_from_other_periods():
    values = {**BASE, **{f"{k}_py": v for k, v in BASE.items()}, "revenue": "1500", "cost": "900",
              "period_expense": "150", "operating_profit": "10", "ar_begin": "50", "ar_end": "80",
              "revenue_py_full": "2000", "revenue_ttm": "1700"}
    refs, tables = _bound(values)
    manual = {"current_collection", "opening_ar_py", "cost", "ar_begin"}
    for key in manual:
        refs[key] = values[key]
    rows, _ = _result(refs, tables, manual_inputs=[])
    assert ("risk_score", "本期") in rows and ("dso", "年初") in rows
    for row in rows.values():
        assert row["manual_inputs"] == sorted(set(row["inputs"]) & manual)
    assert rows["collection_rate_current", "上年同期"]["manual_inputs"] == []
    assert rows["collection_rate_total", "变动"]["manual_inputs"] == sorted(manual & {
        "current_collection", "opening_ar_py"})


@pytest.mark.parametrize(("field", "expected", "wrong"), [
    ("currency", "CNY", "USD"), ("period", "2032-04", "2031-04"), ("organization", "园区甲", "园区乙"),
    ("ledger", "ledger-a", "ledger-b"),
])
def test_component_source_scope_cannot_be_relabelled_by_alias_scope(field, expected, wrong):
    refs, tables = _bound(BASE)
    for row in tables["ledger"]:
        row[field] = expected
    tables["ledger"][-1][field] = wrong
    with pytest.raises(FoundryError, match=field):
        _result(refs, tables, scopes={"ledger": {field: expected}})


@pytest.mark.parametrize("field", ["currency", "period", "organization", "ledger"])
@pytest.mark.parametrize("summed", [False, True])
def test_components_cannot_mix_real_scope_dimensions_without_alias_restrictions(field, summed):
    refs, tables = _sum_bound() if summed else _bound(BASE)
    data = next(iter(tables.values()))
    for row in data:
        row[field] = "same"
    data[1][field] = "different"
    with pytest.raises(FoundryError, match=field):
        _result(refs, tables)


def test_component_current_and_prior_scope_consistency_are_separate_and_do_not_filter_selected_rows():
    refs, tables = _bound(BASE)
    prior_refs, prior_tables = _bound(BASE)
    tables["prior"] = prior_tables["ledger"]
    for row in tables["ledger"]:
        row.update(period="2032-04", organization="园区甲", currency="CNY")
    for row in tables["prior"]:
        row.update(period="2031-04", organization="园区甲", currency="CNY")
    refs.update({f"{key}_py": {**ref, "alias": "prior"} for key, ref in prior_refs.items()})
    rows, _ = _result(refs, tables, scopes={"ledger": {"period": "2032-04"}, "prior": {"period": "2031-04"}})
    assert Decimal(rows["collection_rate_total", "上年同期"]["value"]) == Decimal("0.60")
    refs, tables = _sum_bound()
    tables["projects"][0]["currency"] = "CNY"
    tables["projects"][1]["currency"] = "USD"
    with pytest.raises(FoundryError, match="currency"):
        _result(refs, tables, scopes={"projects": {"currency": "CNY"}})
    tables["projects"][1]["currency"] = "CNY"
    tables["projects"][2]["currency"] = "USD"  # outside sum_where, so irrelevant
    rows, _ = _result(refs, tables, scopes={"projects": {"currency": "CNY"}})
    assert Decimal(rows["collection_rate_total", "本期"]["value"]) == Decimal("0.70")


@pytest.mark.parametrize(("source_unit", "raw", "expected"), [
    ("%", "0.75", "0.0075"), ("pct", "0.75", "0.0075"), ("百分比", "0.75", "0.0075"),
    ("%", "75%", "0.75"), ("ratio", "0.75", "0.75"), ("比率", "0.75", "0.75"),
])
def test_reported_rate_respects_explicit_source_unit(source_unit, raw, expected):
    refs, tables = _bound({"collection_rate_current": raw}, {"collection_rate_current": source_unit})
    rows, _ = _result(refs, tables)
    assert Decimal(rows["collection_rate_current", "本期"]["value"]) == Decimal(expected)


@pytest.mark.parametrize(("source_unit", "override"), [
    ("%", {"scale": "fraction"}), ("ratio", {"scale": "percent"}),
    ("%", {"unit": "ratio"}), ("ratio", {"unit": "%"}),
])
def test_reported_rate_rejects_reference_overrides_that_conflict_with_source_unit(source_unit, override):
    refs, tables = _bound({"collection_rate_current": "0.75"}, {"collection_rate_current": source_unit})
    refs["collection_rate_current"].update(override)
    with pytest.raises(FoundryError, match="unit|scale"):
        _result(refs, tables)


@pytest.mark.parametrize("name", ["collection_rate_current", "collection_rate_total",
                                  "collection_rate_current_py", "collection_rate_total_py"])
@pytest.mark.parametrize("field", ["ledger", "organization", "currency", "period"])
def test_reported_collection_rates_validate_actual_source_scope(name, field):
    refs, tables = _bound({name: "0.75"}, {name: "ratio"})
    tables["ledger"][0][field] = "wrong"
    with pytest.raises(FoundryError, match=field):
        _result(refs, tables, scopes={"ledger": {field: "expected"}})


@pytest.mark.parametrize("field", ["ledger", "organization", "currency", "period"])
def test_reported_collection_rates_cannot_mix_source_scopes(field):
    values = {"collection_rate_current": "0.75", "collection_rate_total": "0.60"}
    refs, tables = _bound(values, dict.fromkeys(values, "ratio"))
    tables["ledger"][0][field] = "one"
    tables["ledger"][1][field] = "another"
    with pytest.raises(FoundryError, match=field):
        _result(refs, tables)


def test_component_scope_guard_does_not_change_legacy_gross_margin_path():
    refs, tables = _bound({"gross_margin": "0.30"}, {"gross_margin": "ratio"})
    tables["ledger"][0]["currency"] = "USD"
    rows, _ = _result(refs, tables, scopes={"ledger": {"currency": "CNY"}})
    assert Decimal(rows["gross_margin", "本期"]["value"]) == 30


def test_component_missing_input_diagnostic_is_explicit():
    rows, result = _result({"current_due": "1200"})
    assert not rows
    skipped = {item["metric_key"]: item for d in result["diagnostics"] for item in d.get("skipped", [])}
    assert skipped["collection_rate_current"]["reason"] == "missing_inputs"
    assert "current_collection" in skipped["collection_rate_current"]["message"]
