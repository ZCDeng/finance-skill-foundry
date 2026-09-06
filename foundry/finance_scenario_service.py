"""Bind scenario calculations to immutable, authorized finance snapshots."""

from foundry.errors import FoundryError
from foundry.finance_scenarios import (
    compute_receivables_aging,
    forecast_cash_13_weeks,
    validate_driver_model,
)
from foundry.finance_model import scoped_source_rows


def calculate_scenario(scenario, context, datasets):
    inputs = scenario["inputs"]
    scope = inputs.get("scope", {})
    all_rows = {}
    for alias, dataset in datasets.items():
        defaults = context.get("scopes", {}).get(alias, {})
        all_rows[alias] = scoped_source_rows(
            dataset, defaults, context.get("policies", {}).get(alias, {})
        )

    def records(key, default, optional=False):
        alias = inputs.get(key, default)
        if alias not in all_rows:
            if optional:
                return []
            raise FoundryError(f"scenario input alias {alias} is not bound")
        return all_rows[alias]

    def required(key):
        value = inputs.get(key)
        if value in (None, ""):
            raise FoundryError(f"scenario input requires {key}")
        return value

    kind = scenario["kind"]
    if kind == "receivables_aging":
        invoices = records("invoices_alias", "invoices")
        activity = records("activity_alias", "activity", True)
        result = compute_receivables_aging(
            invoices,
            activity,
            as_of=required("as_of"),
            scope=scope,
            buckets=inputs.get("buckets"),
        )
        for row in result["rows"]:
            details = [
                r
                for r in result["detail_rows"]
                if all(
                    r.get(key) == row.get(key)
                    for key in ("ledger", "organization", "currency", "unit", "bucket")
                )
            ]
            keys = {
                (
                    r["invoice_id"],
                    r["ledger"],
                    r["organization"],
                    r["currency"],
                    r["unit"],
                )
                for r in details
            }
            row["source_rows"] = [
                r["source"]
                for r in invoices
                if (
                    r.get("id"),
                    r.get("ledger"),
                    r.get("organization"),
                    r.get("currency"),
                    r.get("unit"),
                )
                in keys
            ]
            row["source_rows"] += [
                r["source"]
                for r in activity
                if (
                    r.get("invoice_id"),
                    r.get("ledger"),
                    r.get("organization"),
                    r.get("currency"),
                    r.get("unit"),
                )
                in keys
                and r.get("effective_date", "9999") <= inputs["as_of"]
            ]
            row["as_of"] = inputs["as_of"]
    elif kind == "cash_13_weeks":
        receipts = records("receipts_alias", "receipts", True)
        payments = records("payments_alias", "payments", True)
        result = forecast_cash_13_weeks(
            opening_cash=required("opening_cash"),
            start_date=required("start_date"),
            actual_cutoff=required("actual_cutoff"),
            receipts=receipts,
            payments=payments,
            scope=scope,
            scenario=inputs.get("scenario"),
            weeks=13,
        )
        refs = {("receipt", r.get("id")): r["source"] for r in receipts}
        refs.update({("payment", r.get("id")): r["source"] for r in payments})
        for row in result["rows"]:
            # Closing cash depends on opening cash and every earlier event.
            row["source_rows"] = [
                refs[(e["kind"], e["id"])]
                for e in result["evidence"]["events"]
                if (e["kind"], e["id"]) in refs and e["date"] <= row["week_end"]
            ]
            row.update(
                {
                    k: scope.get(k)
                    for k in ("ledger", "organization", "currency", "unit")
                }
            )
    elif kind == "driver_model":
        evaluated = validate_driver_model(
            inputs.get("drivers", []),
            inputs=inputs.get("values"),
            manager_assumptions=inputs.get("manager_assumptions"),
        )
        result = {
            "columns": evaluated["columns"],
            "rows": [{**row, "source_rows": []} for row in evaluated["rows"]],
            "assumptions": evaluated.get("assumptions", []),
            "driver_model": evaluated,
        }
    else:
        raise FoundryError("unsupported financial scenario kind")
    result.update(
        domain="foundry.finance.scenario_result.v1",
        scenario_id=scenario["id"],
        parent_scenario_id=scenario.get("parent_id"),
        input_hash=scenario["input_hash"],
        scenario_diff=scenario.get("diff", []),
    )
    return result
