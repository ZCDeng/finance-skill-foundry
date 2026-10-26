"""Closed, versioned management templates; callers cannot supply their formulas."""

from copy import deepcopy
from datetime import date

from foundry.errors import FoundryError
from foundry.finance_scenarios import _decimal, _money, validate_driver_model

TEMPLATE_ID = "linked_three_statement_management_v1"
TEMPLATE_VERSION = 1
TEMPLATE_INPUTS = (
    "opening_cash",
    "opening_receivables",
    "opening_ppe",
    "opening_payables",
    "opening_debt",
    "opening_equity",
    "revenue",
    "customer_receipts",
    "operating_expense",
    "supplier_payments",
    "depreciation",
    "capex",
    "debt_drawdowns",
    "debt_principal_repayments",
    "dividends_paid",
    "closing_restricted_cash",
)
BOUNDARY_NAMES = (
    "inventory_movement",
    "tax_effect",
    "interest_effect",
    "vat_effect",
    "fx_effect",
    "oci_effect",
    "noncash_investing_financing",
    "other_balance_sheet_movements",
)
BOUNDARY_INPUTS = tuple(f"boundary.{name}" for name in BOUNDARY_NAMES)
FORMULAS = {
    "net_income": "revenue - operating_expense - depreciation",
    "cash_flow_operating": "customer_receipts - supplier_payments",
    "cash_flow_investing": "-capex",
    "cash_flow_financing": "debt_drawdowns - debt_principal_repayments - dividends_paid",
    "closing_cash": "opening_cash + cash_flow_operating + cash_flow_investing + cash_flow_financing",
    "closing_receivables": "opening_receivables + revenue - customer_receipts",
    "closing_ppe": "opening_ppe + capex - depreciation",
    "closing_payables": "opening_payables + operating_expense - supplier_payments",
    "closing_debt": "opening_debt + debt_drawdowns - debt_principal_repayments",
    "closing_equity": "opening_equity + net_income - dividends_paid",
    "total_assets": "closing_cash + closing_receivables + closing_ppe",
    "total_liabilities_equity": "closing_payables + closing_debt + closing_equity",
    "available_cash": "closing_cash - closing_restricted_cash",
}
OUTPUT_SEMANTICS = {
    "net_income": ("income_statement", "net_income", "flow"),
    "cash_flow_operating": ("cash_flow", "operating_cash_flow", "flow"),
    "cash_flow_investing": ("cash_flow", "investing_cash_flow", "flow"),
    "cash_flow_financing": ("cash_flow", "financing_cash_flow", "flow"),
    "closing_cash": ("balance_sheet", "cash", "stock"),
    "closing_receivables": ("balance_sheet", "accounts_receivable", "stock"),
    "closing_ppe": ("balance_sheet", "property_plant_equipment_net", "stock"),
    "closing_payables": ("balance_sheet", "accounts_payable", "stock"),
    "closing_debt": ("balance_sheet", "debt_principal", "stock"),
    "closing_equity": ("balance_sheet", "equity", "stock"),
    "total_assets": ("balance_sheet", "total_assets", "stock"),
    "total_liabilities_equity": ("balance_sheet", "total_liabilities_equity", "stock"),
    "available_cash": ("liquidity", "available_cash", "stock"),
}


def previous_month(period):
    try:
        current = date.fromisoformat(f"{period}-01")
        if current.strftime("%Y-%m") != period:
            raise ValueError
    except (TypeError, ValueError):
        raise FoundryError("template period must be YYYY-MM") from None
    return (
        f"{current.year - 1}-12"
        if current.month == 1
        else f"{current.year}-{current.month - 1:02d}"
    )


def template_drivers(template_id):
    if template_id != TEMPLATE_ID:
        raise FoundryError("unsupported registered driver template")
    return [{"name": name, "direct_assumption": True} for name in TEMPLATE_INPUTS] + [
        {"name": name, "formula": formula} for name, formula in FORMULAS.items()
    ]


def calculate_linked_management(values):
    """Compute only the registered arithmetic; source qualification is separate."""
    if set(values) != set(TEMPLATE_INPUTS):
        raise FoundryError(
            "registered template requires exactly its complete input names"
        )
    numbers = {name: _decimal(value, name) for name, value in values.items()}
    if any(value < 0 for value in numbers.values()):
        raise FoundryError("registered management template input must be nonnegative")
    evaluated = validate_driver_model(template_drivers(TEMPLATE_ID), inputs=numbers)
    numbers.update(
        {
            row["driver"]: _decimal(row["value"], row["driver"])
            for row in evaluated["rows"]
        }
    )
    checks = []

    def check(name, actual, expected, *, alert=False, lower_bound=False):
        difference = actual - expected
        passed = difference >= 0 if lower_bound else difference == 0
        checks.append(
            {
                "id": name,
                "status": "pass" if passed else "fail",
                "severity": "alert" if alert else "error",
                "blocks_evidence": not alert,
                "actual": _money(actual),
                "expected": _money(expected),
                "difference": _money(difference),
                "source_rows": [],
            }
        )

    n = numbers
    check(
        "opening_balance_sheet",
        n["opening_cash"] + n["opening_receivables"] + n["opening_ppe"],
        n["opening_payables"] + n["opening_debt"] + n["opening_equity"],
    )
    for check_id, output, components in (
        (
            "revenue_receivables_cash",
            "closing_receivables",
            ("opening_receivables", "revenue", "customer_receipts"),
        ),
        ("ppe_rollforward", "closing_ppe", ("opening_ppe", "capex", "depreciation")),
        (
            "payables_rollforward",
            "closing_payables",
            ("opening_payables", "operating_expense", "supplier_payments"),
        ),
        (
            "debt_financing",
            "closing_debt",
            ("opening_debt", "debt_drawdowns", "debt_principal_repayments"),
        ),
        (
            "equity_rollforward",
            "closing_equity",
            ("opening_equity", "net_income", "dividends_paid"),
        ),
    ):
        check(
            check_id, n[components[0]] + n[components[1]] - n[components[2]], n[output]
        )
    check(
        "cash_reconciliation",
        n["opening_cash"]
        + n["cash_flow_operating"]
        + n["cash_flow_investing"]
        + n["cash_flow_financing"],
        n["closing_cash"],
    )
    check(
        "cash_flow_indirect_bridge",
        n["net_income"]
        + n["depreciation"]
        - (n["closing_receivables"] - n["opening_receivables"])
        + (n["closing_payables"] - n["opening_payables"]),
        n["cash_flow_operating"],
    )
    check("closing_balance_sheet", n["total_assets"], n["total_liabilities_equity"])
    check(
        "nonnegative_operating_balances",
        min(
            n[key]
            for key in (
                "closing_receivables",
                "closing_ppe",
                "closing_payables",
                "closing_debt",
            )
        ),
        _decimal(0, "zero"),
        lower_bound=True,
    )
    check(
        "restricted_cash_bounds",
        max(n["closing_cash"], _decimal(0, "zero")) - n["closing_restricted_cash"],
        _decimal(0, "zero"),
        lower_bound=True,
    )
    check(
        "cash_sufficiency",
        n["available_cash"],
        _decimal(0, "zero"),
        alert=True,
        lower_bound=True,
    )
    for row in evaluated["rows"]:
        if row["driver"] in OUTPUT_SEMANTICS:
            statement, line, kind = OUTPUT_SEMANTICS[row["driver"]]
            row.update(
                metric_key=row["driver"],
                statement=statement,
                statement_line=line,
                value_kind=kind,
                template_id=TEMPLATE_ID,
                template_version=TEMPLATE_VERSION,
            )
    evaluated.update(
        template_id=TEMPLATE_ID,
        template_version=TEMPLATE_VERSION,
        model_checks=checks,
        model_scope="single_entity_management_forecast",
        supported_scope={
            "entity_count": 1,
            "source_ledger_policy": "single_identity",
            "source_scenario_policy": "single_identity",
            "supports_actual_forecast_bridge": False,
            "supports_statutory_statements": False,
            "excluded_effects": list(BOUNDARY_NAMES),
        },
    )
    return deepcopy(evaluated)
