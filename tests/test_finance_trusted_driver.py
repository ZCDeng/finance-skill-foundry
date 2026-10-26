from copy import deepcopy

import pytest

from foundry.errors import FoundryError
from foundry.finance_scenario_service import calculate_scenario


def source_driver():
    rows = [
        {
            "account": "revenue",
            "amount": "10",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
        },
        {
            "account": "revenue",
            "amount": "20",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
        },
        {
            "account": "expense",
            "amount": "5",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
        },
    ]
    context = {
        "bindings": {"ledger": "d1"},
        "scopes": {"ledger": {"organization": "O1", "currency": "CNY", "unit": "元"}},
    }
    binding = {
        "alias": "ledger",
        "column": "amount",
        "selector": {"account": "revenue"},
        "aggregation": "sum",
        "scope": {"organization": "O1"},
        "period": "2026-09",
        "currency": "CNY",
        "unit": "元",
    }
    inputs = {
        "drivers": [
            {"name": "revenue", "direct_assumption": True},
            {"name": "expense", "direct_assumption": True},
            {"name": "margin", "formula": "revenue - expense"},
            {"name": "twice", "formula": "margin * 2"},
        ],
        "source_bindings": {
            "revenue": binding,
            "expense": {
                **deepcopy(binding),
                "selector": {"account": "expense"},
                "aggregation": "single",
            },
        },
    }
    scenario = {
        "id": "s1",
        "kind": "driver_model",
        "input_hash": "hash",
        "inputs": inputs,
    }
    return scenario, context, {"ledger": {"id": "d1", "rows": rows}}


def run(parts):
    return calculate_scenario(*parts)


def test_source_binding_resolves_and_propagates_every_ancestor():
    result = run(source_driver())
    rows = {row["driver"]: row for row in result["rows"]}
    assert rows["twice"]["value"] == "50"
    assert {ref["row_index"] for ref in rows["twice"]["source_rows"]} == {1, 2, 3}
    assert rows["twice"]["source_binding_ids"] == ["expense", "revenue"]
    assert rows["twice"]["status"] == "source_verified"
    assert result["source_binding_status"]["all_sources_verified"] is True
    assert "metric_key" not in rows["revenue"]


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda s, c, d: s["inputs"].update(values={"revenue": "999"}), "override"),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                alias="unbound"
            ),
            "authorized",
        ),
        (lambda s, c, d: d["ledger"].update(id="wrong"), "context"),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                column="absent"
            ),
            "column",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                selector={"amount": {"gt": 0}}
            ),
            "scalar",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                selector={"imagined": "revenue"}
            ),
            "real columns",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                selector={"account": "none"}
            ),
            "matching",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                aggregation="single"
            ),
            "exactly one",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                period="2026-08"
            ),
            "period",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                currency="USD"
            ),
            "currency",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                unit="people"
            ),
            "unit",
        ),
        (lambda s, c, d: d["ledger"]["rows"][0].update(amount=None), "finite decimal"),
        (lambda s, c, d: d["ledger"]["rows"][0].update(amount="NaN"), "finite decimal"),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["revenue"].update(
                source_rows=[{"row_index": 99}]
            ),
            "unsupported",
        ),
        (
            lambda s, c, d: s["inputs"]["source_bindings"].update(
                margin=deepcopy(s["inputs"]["source_bindings"]["revenue"])
            ),
            "formula",
        ),
    ],
)
def test_invalid_source_bindings_cannot_be_promoted(change, match):
    parts = source_driver()
    change(*parts)
    with pytest.raises(FoundryError, match=match):
        run(parts)


def test_explicit_unit_conversion_preserves_original_and_target_units():
    scenario, context, datasets = source_driver()
    context["scopes"]["ledger"]["unit"] = "万元"
    for binding in scenario["inputs"]["source_bindings"].values():
        binding["unit"] = "万元"
    result = calculate_scenario(scenario, context, datasets)
    row = next(row for row in result["rows"] if row["driver"] == "twice")
    assert row["value"] == "0.0050"
    assert {ref["unit_multiplier"] for ref in row["source_rows"]} == {"0.0001"}
    assert {ref["original_unit"] for ref in row["source_rows"]} == {"元"}


def test_context_defaults_can_supply_missing_identity_but_binding_cannot():
    scenario, context, datasets = source_driver()
    for row in datasets["ledger"]["rows"]:
        row.pop("unit")
    assert calculate_scenario(scenario, context, datasets)["source_binding_status"][
        "all_sources_verified"
    ]
    context["scopes"]["ledger"].pop("unit")
    with pytest.raises(FoundryError, match="cannot label"):
        calculate_scenario(scenario, context, datasets)


def test_real_zero_is_source_verified_but_manager_label_is_not_confirmation():
    scenario, context, datasets = source_driver()
    datasets["ledger"]["rows"][2]["amount"] = "0"
    result = calculate_scenario(scenario, context, datasets)
    assert result["source_binding_status"]["bindings"]["expense"]["value"] == "0"
    del scenario["inputs"]["source_bindings"]["expense"]
    scenario["inputs"]["manager_assumptions"] = {
        "expense": {"value": "5", "label": "经理已确认", "confirmed": True}
    }
    result = calculate_scenario(scenario, context, datasets)
    row = next(row for row in result["rows"] if row["driver"] == "twice")
    assert row["value"] == "50"
    assert row["status"] == "unverified"
    assert row["unverified_inputs"] == ["expense"]
    assert result["source_binding_status"]["all_sources_verified"] is False


def test_legacy_driver_does_not_inherit_caller_metric_or_source_claims():
    scenario, context, datasets = source_driver()
    scenario["inputs"].pop("source_bindings")
    scenario["inputs"]["values"] = {"revenue": "30", "expense": "5"}
    scenario["inputs"]["drivers"][0].update(
        metric_key="net_income", source_rows=[{"dataset_id": "d1", "row_index": 1}]
    )
    result = calculate_scenario(scenario, context, datasets)
    assert all(not row["source_rows"] for row in result["rows"])
    assert all("metric_key" not in row for row in result["rows"])
    assert not result["source_binding_status"]["all_sources_verified"]


def test_generic_dag_cannot_claim_a_mixed_period_amount_is_verified():
    scenario, context, datasets = source_driver()
    datasets["ledger"]["rows"][2]["period"] = "2026-08"
    scenario["inputs"]["source_bindings"]["expense"]["period"] = "2026-08"
    result = calculate_scenario(scenario, context, datasets)
    row = next(row for row in result["rows"] if row["driver"] == "twice")
    assert row["value"] == "50"
    assert row["status"] == "unverified"
    assert any("mixed_source_identity" in reason for reason in row["unverified_inputs"])


@pytest.mark.parametrize("status", ["duplicate_pull", "deleted", "void", "voided"])
def test_inactive_rows_cannot_become_live_driver_sources(status):
    scenario, context, datasets = source_driver()
    for row in datasets["ledger"]["rows"]:
        if row["account"] == "revenue":
            row["source_status"] = status
    with pytest.raises(FoundryError, match="matching"):
        calculate_scenario(scenario, context, datasets)


def test_explicit_physical_column_and_selector_survive_canonical_field_mapping():
    scenario, context, datasets = source_driver()
    for row in datasets["ledger"]["rows"]:
        row["imported_amount"] = "999"
    context["policies"] = {"ledger": {"field_map": {"amount": "imported_amount"}}}
    scenario["inputs"]["source_bindings"]["expense"]["selector"] = {"amount": "5"}
    result = calculate_scenario(scenario, context, datasets)
    proof = result["source_binding_status"]["bindings"]["revenue"]
    assert proof["value"] == "30"
    assert all(ref["column"] == "amount" for ref in proof["source_rows"])
    assert (
        next(row for row in result["rows"] if row["driver"] == "twice")["value"] == "50"
    )


@pytest.mark.parametrize("identity", ["ledger", "scenario"])
def test_generic_dag_preserves_and_checks_undeclared_source_identity(identity):
    scenario, context, datasets = source_driver()
    for row in datasets["ledger"]["rows"]:
        row[identity] = "actual" if row["account"] == "revenue" else "forecast"
    result = calculate_scenario(scenario, context, datasets)
    assert result["source_binding_status"]["bindings"]["revenue"][identity] == "actual"
    row = next(row for row in result["rows"] if row["driver"] == "twice")
    assert row["value"] == "50"
    assert row["status"] == "unverified"
    assert "margin:mixed_source_identity" in row["unverified_inputs"]


@pytest.mark.parametrize("identity", ["ledger", "scenario"])
def test_single_binding_cannot_sum_different_books_or_scenarios(identity):
    scenario, context, datasets = source_driver()
    datasets["ledger"]["rows"][0][identity] = "actual"
    datasets["ledger"]["rows"][1][identity] = "forecast"
    with pytest.raises(FoundryError, match=f"mixes source {identity}"):
        calculate_scenario(scenario, context, datasets)
