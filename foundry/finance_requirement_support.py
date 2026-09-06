"""Server-derived requirement support and snapshot-bound input gaps."""
from __future__ import annotations

from foundry.errors import FoundryError

ALIASES = {
    "variance_ratio": "ratio",
    "revenue=price×quantity": "revenue",
    "revenue=price*quantity": "revenue",
}
NATIVE_METRICS = {
    "management_pnl": "run_metric",
    "profit": "run_metric / explain_variance",
    "revenue": "run_metric / explain_variance",
    "cost": "run_metric / explain_variance",
    "expense": "run_metric / explain_variance",
    "ratio": "run_metric / explain_variance",
    "account_total": "run_metric",
    "control_totals": "run_metric",
    "price_quantity": "explain_variance",
    "amount_change": "explain_variance",
    "total_variance": "explain_variance",
    "quantity_contribution": "explain_variance",
    "price_contribution": "explain_variance",
    "interaction": "explain_variance",
    "residual": "explain_variance",
    "open_amount": "finance_scenario_run (receivables_aging)",
    "closing_cash": "finance_scenario_run (cash_13_weeks)",
}


def canonical_metric(metric):
    return ALIASES.get(metric, metric)


def metric_catalog():
    return [{"metric": key, "tool": tool} for key, tool in NATIVE_METRICS.items()]


def assess_requirement_support(analysis, spec):
    """Describe supported paths without accepting client-authored absence claims.

    A missing native field means the current binding needs data or a field map,
    not that quantities cannot exist elsewhere or be computed with SQL/Python.
    This report never declares an unexecuted financial requirement answered.
    """
    sources = []
    accounts = set()
    failures = []
    for alias, dataset_id in (spec.get("bindings") or {}).items():
        try:
            dataset = analysis.read_dataset(dataset_id)
            columns = [c["name"] for c in dataset.get("schema", [])]
            sources.append({"alias": alias, "dataset_id": dataset_id,
                            "source_hash": dataset["source_hash"],
                            "data_hash": dataset["data_hash"], "columns": columns})
            accounts.update(str(row["management_account"]) for row in dataset.get("rows", [])
                            if isinstance(row, dict) and row.get("management_account") is not None)
        except (FoundryError, OSError, ValueError, KeyError, TypeError):
            failures.append({"alias": alias, "dataset_id": dataset_id,
                             "reason": "snapshot_unverified"})
    reports = []
    source_columns = {column for source in sources for column in source["columns"]}
    for item in spec.get("items", []):
        metric = canonical_metric(item.get("metric"))
        report = {"requirement_item_id": item.get("id"), "canonical_metric": metric,
                  "status": "requires_execution", "sources": sources}
        if metric not in NATIVE_METRICS:
            if metric in accounts:
                report["tool"] = "run_metric (single account_total)"
            elif metric in source_columns:
                report["tool"] = "analysis-save / analysis-run (explicit result column)"
            else:
                report.update(status="unrecognized", next_action="选择已支持指标，或用SQL/Python计算并声明明确的结果列；保留原问题。")
        else:
            report["tool"] = NATIVE_METRICS[metric]
        if failures:
            report.update(status="unverified", failures=failures,
                          next_action="先恢复并核验绑定快照，不能将读取失败当成数据不存在。")
        elif metric == "price_quantity" or (
            metric in {"revenue", "amount"}
            and item.get("dimensions", {}).get("method") in {
                "quantity_then_price", "base_weights_with_interaction"
            }
        ):
            report.update(tool="explain_variance", status="requires_execution")
            if not sources:
                report.update(status="unverified", next_action="先绑定已授权资料，再检查量价字段。")
            else:
                missing = [{"dataset_id": source["dataset_id"], "alias": source["alias"],
                            "columns": [key for key in ("quantity", "price") if key not in source["columns"]]}
                           for source in sources]
                missing = [item for item in missing if item["columns"]]
                if missing:
                    report.update(status="requires_input", gap_code="native_price_quantity_fields_unavailable",
                                  missing_inputs=missing, input_basis="native_default_field_names",
                                  next_action="当前绑定缺少原生quantity/price字段；补充数量与单价资料，或明确字段映射后重新计算。可继续使用SQL/Python探索。")
        reports.append(report)
    return {"version": 1, "supported_metrics": metric_catalog(), "items": reports}


def with_input_gaps(analysis, requirements):
    """Attach independently verified gaps without turning coverage green."""
    requirement_id = requirements.get("requirements_id")
    if not requirement_id:
        return requirements
    record = analysis._get("requirements", requirement_id)
    support = assess_requirement_support(analysis, record)
    gaps = {item["requirement_item_id"]: item for item in support["items"]
            if item["status"] == "requires_input"}
    items = []
    for item in requirements.get("items", []):
        gap = gaps.get(item["id"])
        if gap and item["status"] != "answered":
            item = {**item, "status": "missing_data", "input_gap": gap}
        items.append(item)
    return {**requirements, "items": items, "support": support}


def input_gap_appendix(requirements):
    gaps = [item for item in requirements.get("items", []) if item.get("input_gap")]
    if not gaps:
        return ""
    return "\n\n## 待补资料\n\n" + "\n".join(dict.fromkeys(
        "- 量价分解待补齐：" + item["input_gap"]["next_action"] for item in gaps
    ))
