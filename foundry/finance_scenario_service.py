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
            status_filter=inputs.get("status_filter"),
        )

        def identity_key(detail):
            return (
                detail["invoice_id"],
                detail["ledger"],
                detail["organization"],
                detail["currency"],
                detail["unit"],
            )

        def detail_keys(key, row):
            details = [
                detail
                for detail in result[key]
                if all(
                    detail.get(field) == row.get(field)
                    for field in (
                        "ledger",
                        "organization",
                        "currency",
                        "unit",
                        "bucket",
                    )
                )
            ]
            return {identity_key(detail) for detail in details}

        def source_rows(keys):
            refs = [
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
            refs += [
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
            return refs

        for detail in result["detail_rows"]:
            detail["source_rows"] = source_rows({identity_key(detail)})
        for detail in result["excluded_detail_rows"]:
            detail["source_rows"] = source_rows({identity_key(detail)})

        for row in result["rows"]:
            row["source_rows"] = source_rows(detail_keys("detail_rows", row))
            row["excluded_source_rows"] = source_rows(
                detail_keys("excluded_detail_rows", row)
            )
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
    elif kind == "collection_health":
        from foundry.collection_metrics import (
            evaluate_collection_health,
            resolve_entities,
            resolve_params,
        )

        # Cells are addressed one by one, so the scope does not filter rows: a KPI
        # sheet keeps rates and amounts in one table, each row with its own unit.
        cells = {
            alias: scoped_source_rows(
                dataset, {}, context.get("policies", {}).get(alias, {})
            )
            for alias, dataset in datasets.items()
        }
        units = {
            alias: (context.get("scopes", {}).get(alias) or {}).get("unit")
            for alias in cells
        }
        result = evaluate_collection_health(
            resolve_entities(inputs, cells, units),
            resolve_params(inputs.get("params")),
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
