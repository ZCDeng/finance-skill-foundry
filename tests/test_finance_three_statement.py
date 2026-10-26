import json
from pathlib import Path

import pytest

from foundry.errors import FoundryError
from foundry.finance_driver_templates import (
    BOUNDARY_INPUTS,
    TEMPLATE_ID,
    calculate_linked_management,
)
from foundry.finance_scenario_service import calculate_scenario
from foundry.finance_scenarios import validate_driver_model
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

FIXTURES = (
    Path(__file__).parent / "fixtures/finance_evals/professional_runtime_v1/public"
)
BASE_VALUES = {
    "opening_cash": "100",
    "opening_receivables": "50",
    "opening_ppe": "200",
    "opening_payables": "50",
    "opening_debt": "100",
    "opening_equity": "200",
    "revenue": "120",
    "customer_receipts": "100",
    "operating_expense": "60",
    "supplier_payments": "50",
    "depreciation": "10",
    "capex": "40",
    "debt_drawdowns": "0",
    "debt_principal_repayments": "20",
    "dividends_paid": "0",
    "closing_restricted_cash": "0",
}


def template_parts(variant="E18--base--closed-template"):
    context = {
        "bindings": {"template_inputs": "d1", "model_boundary": "d2"},
        "scopes": {},
    }
    datasets, bindings = {}, {}
    for alias, key in (
        ("template_inputs", "input_name"),
        ("model_boundary", "boundary_name"),
    ):
        rows = json.loads((FIXTURES / variant / f"{alias}.json").read_text())["rows"]
        datasets[alias] = {"id": context["bindings"][alias], "rows": rows}
        for row in rows:
            name = row[key] if alias == "template_inputs" else f"boundary.{row[key]}"
            bindings[name] = {
                "alias": alias,
                "column": "amount",
                "selector": {key: row[key]},
                "aggregation": "single",
                "period": row["period"],
                "scope": {"organization": row["organization"]},
                "currency": row["currency"],
                "unit": row["unit"],
            }
    inputs = {
        "template_id": TEMPLATE_ID,
        "period": "2026-09",
        "scope": {
            "organization": "Synthetic Fixture Co",
            "currency": "CNY",
            "unit": "元",
        },
        "source_bindings": bindings,
    }
    return (
        {"id": "s1", "kind": "driver_model", "input_hash": "hash", "inputs": inputs},
        context,
        datasets,
    )


def output(result):
    return {
        row["driver"]: row["value"] for row in result["rows"] if "metric_key" in row
    }


def test_e18_independent_three_statement_oracle():
    result = calculate_linked_management(BASE_VALUES)
    assert output(result) == {
        "net_income": "50",
        "cash_flow_operating": "50",
        "cash_flow_investing": "-40",
        "cash_flow_financing": "-20",
        "closing_cash": "90",
        "closing_receivables": "70",
        "closing_ppe": "230",
        "closing_payables": "60",
        "closing_debt": "80",
        "closing_equity": "250",
        "total_assets": "390",
        "total_liabilities_equity": "390",
        "available_cash": "90",
    }
    assert all(check["status"] == "pass" for check in result["model_checks"])


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("E18--base--closed-template", ("90", "70", "50", "250", "390")),
        ("E19--old_ar_collected--closed-template", ("100", "60", "50", "250", "390")),
        ("E19--new_cash_sale--closed-template", ("100", "70", "60", "260", "400")),
    ],
)
def test_e18_e19_resolve_actual_source_rows_and_keep_business_perturbations_distinct(
    variant, expected
):
    result = calculate_scenario(*template_parts(variant))
    values = output(result)
    assert (
        tuple(
            values[key]
            for key in (
                "closing_cash",
                "closing_receivables",
                "net_income",
                "closing_equity",
                "total_assets",
            )
        )
        == expected
    )
    assert result["source_binding_status"]["all_sources_verified"]
    assert len(result["model_boundary"]) == 8
    for row in result["rows"]:
        if "metric_key" in row:
            assert set(BOUNDARY_INPUTS) <= set(row["source_binding_ids"])
            assert row["source_rows"]
            assert row["period"] == "2026-09"


@pytest.mark.parametrize(
    "change,match",
    [
        (
            lambda s, c, d: s["inputs"]["source_bindings"].pop("boundary.fx_effect"),
            "eight boundary",
        ),
        (
            lambda s, c, d: d["model_boundary"]["rows"][0].update(amount="1"),
            "nonzero boundary",
        ),
        (lambda s, c, d: s["inputs"].update(drivers=[]), "overridden"),
        (
            lambda s, c, d: s["inputs"].update(model_boundary={"fx_effect": 0}),
            "overridden",
        ),
        (lambda s, c, d: s["inputs"].update(metric_key="net_income"), "overridden"),
        (lambda s, c, d: s["inputs"].update(period="2026-10"), "source period"),
        (
            lambda s, c, d: s["inputs"]["source_bindings"]["opening_cash"].update(
                unit="万元"
            ),
            "model scope",
        ),
    ],
)
def test_template_refuses_missing_or_forged_boundaries_and_scope(change, match):
    parts = template_parts()
    change(*parts)
    with pytest.raises(FoundryError, match=match):
        calculate_scenario(*parts)


def test_no_equity_plug_and_negative_operating_balances_are_blocking():
    result = calculate_linked_management({**BASE_VALUES, "opening_equity": "199"})
    assert output(result)["closing_equity"] == "249"
    checks = {check["id"]: check for check in result["model_checks"]}
    for key in ("opening_balance_sheet", "closing_balance_sheet"):
        assert checks[key]["difference"] == "1"
        assert checks[key]["status"] == "fail" and checks[key]["blocks_evidence"]
    result = calculate_linked_management({**BASE_VALUES, "customer_receipts": "171"})
    assert output(result)["closing_receivables"] == "-1"
    assert (
        next(
            check
            for check in result["model_checks"]
            if check["id"] == "nonnegative_operating_balances"
        )["status"]
        == "fail"
    )


def test_correct_cash_shortfall_is_an_alert_and_does_not_destroy_evidence():
    scenario, context, datasets = template_parts()
    next(
        row
        for row in datasets["template_inputs"]["rows"]
        if row["input_name"] == "capex"
    )["amount"] = "140"
    result = calculate_scenario(scenario, context, datasets)
    assert output(result)["closing_cash"] == "-10"
    checks = {check["id"]: check for check in result["model_checks"]}
    assert checks["cash_sufficiency"]["status"] == "fail"
    assert checks["cash_sufficiency"]["severity"] == "alert"
    assert checks["cash_sufficiency"]["blocks_evidence"] is False
    assert all(
        check["status"] == "pass"
        for check in checks.values()
        if check["blocks_evidence"]
    )
    assert all(row["check_status"] == "pass" for row in result["rows"])
    assert result["source_binding_status"]["all_sources_verified"]


def test_persisted_template_has_real_archived_sources_and_no_unbound_metric(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="三表来源验证")
    # Native manager archive probe; assistant ordering is covered separately.
    service = FinanceStore(task, actor="manager")
    scenario, context, datasets = template_parts()
    for alias, dataset in datasets.items():
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps(dataset["rows"], ensure_ascii=False))
        context["bindings"][alias] = service.analysis.add_dataset(path, name=alias)[
            "id"
        ]
    saved_context = service.save_context(context)
    saved = service.save_scenario(
        {
            "context_id": saved_context["id"],
            "kind": "driver_model",
            "label": "来源三表",
            "inputs": scenario["inputs"],
        }
    )
    run = service.run_scenario({"scenario_id": saved["id"]})
    assert output(run["result"])["closing_cash"] == "90"
    cash_index = next(
        index
        for index, row in enumerate(run["result"]["rows"])
        if row["driver"] == "closing_cash"
    )
    assert (
        service.drilldown_fact({"run_id": run["id"], "row": cash_index})["total"] >= 8
    )
    assert run["input_hashes"]


@pytest.mark.parametrize(
    "values,formula,expected",
    [
        (
            {"cost": "120", "residual": "0", "months": "12", "elapsed": "6"},
            "(cost - residual) / months * elapsed",
            "60",
        ),
        (
            {"cost": "120", "residual": "0", "months": "12", "elapsed": "5"},
            "(cost - residual) / months * elapsed",
            "50",
        ),
        (
            {"payroll": "50000", "paid_fte": "10", "forecast_fte": "12"},
            "payroll / paid_fte * forecast_fte",
            "60000",
        ),
        (
            {"opening_cash": "100", "cfo": "20", "cfi": "-5", "cff": "10", "fx": "3"},
            "opening_cash + cfo + cfi + cff + fx",
            "128",
        ),
        (
            {
                "opening_re": "80",
                "income": "20",
                "dividend": "5",
                "approved_adjustment": "2",
                "oci": "3",
            },
            "opening_re + income - dividend + approved_adjustment",
            "97",
        ),
        (
            {
                "opening_debt": "100",
                "draws": "30",
                "principal_paid": "20",
                "fx": "2",
                "interest": "5",
            },
            "opening_debt + draws - principal_paid + fx",
            "112",
        ),
        (
            {
                "total_cash": "100",
                "restricted_cash": "30",
                "receipts": "20",
                "payments": "100",
            },
            "total_cash - restricted_cash + receipts - payments",
            "-10",
        ),
    ],
)
def test_explicit_separate_schedules_preserve_e15_e22_boundaries(
    values, formula, expected
):
    # These are transparent, separately declared calculations, not extra registered
    # statement semantics or automatic policy/manager confirmation.
    drivers = [{"name": name, "direct_assumption": True} for name in values]
    drivers.append({"name": "schedule_result", "formula": formula})
    result = validate_driver_model(drivers, inputs=values)
    row = next(row for row in result["rows"] if row["driver"] == "schedule_result")
    assert row["value"] == expected
    assert "metric_key" not in row
    if "oci" in values:
        assert "oci" not in row["depends_on"]
    if "interest" in values:
        assert "interest" not in row["depends_on"]


def test_zero_fte_and_nonzero_unsupported_fx_cannot_silently_succeed():
    with pytest.raises(FoundryError, match="divides by zero"):
        validate_driver_model(
            [
                {"name": "payroll", "direct_assumption": True},
                {"name": "fte", "direct_assumption": True},
                {"name": "rate", "formula": "payroll / fte"},
            ],
            inputs={"payroll": "50000", "fte": "0"},
        )
    scenario, context, datasets = template_parts()
    next(
        row
        for row in datasets["model_boundary"]["rows"]
        if row["boundary_name"] == "fx_effect"
    )["amount"] = "3"
    with pytest.raises(FoundryError, match="nonzero boundary"):
        calculate_scenario(scenario, context, datasets)
