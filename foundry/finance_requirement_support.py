"""Server-derived requirement support and snapshot-bound input gaps."""
from __future__ import annotations

from foundry.errors import FoundryError

ALIASES = {
    "variance_ratio": "ratio",
    "revenue=price×quantity": "revenue",
    "revenue=price*quantity": "revenue",
}
METHOD_ALIASES = {
    "profit_bridge": "revenue_minus_cost_minus_expense",
    "profit_variance_bridge": "revenue_minus_cost_minus_expense",
    "利润桥": "revenue_minus_cost_minus_expense",
    "利润变动桥": "revenue_minus_cost_minus_expense",
    "收入-成本-费用": "revenue_minus_cost_minus_expense",
    "收入减成本减费用": "revenue_minus_cost_minus_expense",
}
# Evidence that can answer each native metric, not a tool to try. Every metric but a ratio, count or
# quantity is an amount: script values never answer it. run_metric management_pnl rows never close for
# revenue/profit/cost/expense, so those are answered by a cited cell with a passing direct/sum/diff
# evidence recipe, or by explain_variance engine closure (items without scenarios); price_quantity by the
# engine's price-quantity bridge or a recipe; the other amounts the engine states itself (engine_output), a
# server-side structured_aggregate states (aggregate_output), or a recipe proves.
NATIVE_METRICS = {
    "management_pnl": "evidence_recipe",
    "profit": "evidence_recipe / engine_closure (explain_variance)",
    "revenue": "evidence_recipe / engine_closure (explain_variance)",
    "cost": "evidence_recipe / engine_closure (explain_variance)",
    "expense": "evidence_recipe / engine_closure (explain_variance)",
    "ratio": "cited_result_row",
    "account_total": "run_metric_result_set (run_metric)",
    "control_totals": "run_metric_result_set (run_metric)",
    "price_quantity": "price_quantity_bridge (explain_variance) / evidence_recipe",
    "amount_change": "engine_output (explain_variance) / evidence_recipe",
    "total_variance": "price_quantity_bridge (explain_variance) / engine_output (explain_variance) / evidence_recipe",
    "quantity_contribution": "price_quantity_bridge (explain_variance) / engine_output (explain_variance) / evidence_recipe",
    "price_contribution": "price_quantity_bridge (explain_variance) / engine_output (explain_variance) / evidence_recipe",
    "interaction": "price_quantity_bridge (explain_variance) / engine_output (explain_variance) / evidence_recipe",
    "residual": "price_quantity_bridge (explain_variance) / engine_output (explain_variance) / evidence_recipe",
    "open_amount": "engine_output (finance_scenario_run receivables_aging) / evidence_recipe",
    "closing_cash": "engine_output (finance_scenario_run cash_13_weeks) / evidence_recipe",
}


def canonical_metric(metric):
    return ALIASES.get(metric, metric)


def canonical_method(method):
    if not isinstance(method, str):
        return method
    return METHOD_ALIASES.get(method, method)


def canonical_dimensions(dimensions):
    if not isinstance(dimensions, dict):
        return {}
    normalized = dict(dimensions)
    if normalized.get("method") is not None:
        normalized["method"] = canonical_method(normalized["method"])
    return normalized


def metric_catalog():
    return [{"metric": key, "evidence": evidence} for key, evidence in NATIVE_METRICS.items()]


ENGINE_TOOLS = {"explain_variance", "run_metric", "finance_scenario_run"}


def _offers(paths, name):
    return any(path["path"] == name for path in [*paths["accepted"], *paths["blocked"]])


def _offered_evidence(text, paths):
    """The catalog text narrowed to the paths the checker offers this item, accepted or blocked.

    Engine closure rows carry no scenario, so an amount item with scenarios is never pointed there.
    """
    if not paths:
        return text
    parts = [part for part in text.split(" / ") if _offers(paths, part.split(" (")[0])]
    return " / ".join(parts) or text


def _paths_evidence(paths):
    return " / ".join(dict.fromkeys(
        f"{path['path']} ({path['tool']})" if path.get("tool") in ENGINE_TOOLS else path["path"]
        for path in [*paths["accepted"], *paths["blocked"]]))


def _amount_next_action(item, paths):
    from foundry.finance_requirements import BLOCKER_TEXT, _path_text

    keys = f"metric_key（{item['metric']}） 和 value"
    accepted = "；或".join(_path_text(path, keys) for path in paths["accepted"])
    blocked = "；".join(f"{path['path']}（{'、'.join(BLOCKER_TEXT.get(b, b) for b in path['blockers'])}）"
                        for path in paths["blocked"])
    return ("按金额类要求作答（比率、数量、人数等以外的指标都按金额核验）" + (f"：{accepted}" if accepted else "") + "。"
            + (f"当前走不通的路径：{blocked}。" if blocked else "")
            + "只有脚本或 SQL 输出的数不计为已回答；保留原问题。")


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
    from foundry.finance_requirements import (
        _closed_metric_key, _evidence_environment, _evidence_paths, _native_account_item, _pnl_class,
    )

    try:
        environment = _evidence_environment(analysis, spec)
    except (FoundryError, OSError, ValueError, KeyError, TypeError):
        environment = {"workbook_sources": [], "finance_context": None, "structure_pending": []}
    for item in spec.get("items", []):
        metric = canonical_metric(item.get("metric"))
        report = {"requirement_item_id": item.get("id"), "canonical_metric": metric,
                  "status": "requires_execution", "sources": sources}
        # What can answer this item right now, and what is blocked and why (never a bare tool name).
        paths = (_evidence_paths(item, environment)
                 if isinstance(item, dict) and isinstance(item.get("metric"), str) else None)
        if metric not in NATIVE_METRICS:
            if paths and _closed_metric_key(item) and _offers(paths, "evidence_recipe"):
                # Every name but a ratio, count or quantity is gated as an amount (利润总额, NetProfit, a name
                # nothing recognises …), so free SQL/Python result columns alone never answer it.
                report.update(evidence=_paths_evidence(paths), next_action=_amount_next_action(item, paths))
                if _pnl_class(item.get("metric")) is None and metric not in accounts and metric not in source_columns:
                    report.update(status="unrecognized", next_action=(
                        "未识别的指标按金额核验：可选择已支持指标，或用SQL/Python计算并声明明确的结果列，再按下述依据作答。"
                        + report["next_action"]))
            elif metric in accounts and _native_account_item(item):
                report["evidence"] = "run_metric_result_set (single account_total)"
            elif paths and (paths["accepted"] or paths["blocked"]) and _pnl_class(item.get("metric")) is not None:
                # A P&L line named by its alias (营业收入) that is also a ledger account: not an account item, and
                # not unrecognized either; the paths the checker offers it (a method run) are its evidence.
                report["evidence"] = _paths_evidence(paths)
            elif metric in source_columns:
                report["evidence"] = "cited_result_row (explicit result column)"
            else:
                report.update(status="unrecognized", next_action="选择已支持指标，或用SQL/Python计算并声明明确的结果列；保留原问题。")
        else:
            report["evidence"] = _offered_evidence(NATIVE_METRICS[metric], paths)
        if paths is not None:
            report["accepted_evidence"] = [path["path"] for path in paths["accepted"]]
            if paths["blocked"]:
                report["blocked_evidence"] = paths["blocked"]
        if failures:
            report.update(status="unverified", failures=failures,
                          next_action="先恢复并核验绑定快照，不能将读取失败当成数据不存在。")
        elif metric == "price_quantity" or (
            metric in {"revenue", "amount"}
            and canonical_method(item.get("dimensions", {}).get("method")) in {
                "quantity_then_price", "base_weights_with_interaction"
            }
        ):
            report.update(evidence=_offered_evidence(NATIVE_METRICS["price_quantity"], paths), status="requires_execution")
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


EVIDENCE_BASIS_LABELS = {
    "source_value": "来源原值（单元格选择待复核）",
    "source_calculation": "来源计算（单元格选择待复核）",
    "estimate": "估算（经理确认前不计为已回答）",
}


def evidence_basis_appendix(requirements):
    """Recipe-backed cells grouped by server-derived evidence_basis; estimates show their formula.

    Only item ids, metric keys and sheet!range references are written, never a value. A sheet name can
    still hold digits (2026预算!B5), so validation exempts exactly these references inside the trusted
    appendix (see evidence_basis_references); the same text in the writer's prose is still checked.
    """
    lines = []
    for heading, groups in _evidence_basis_groups(requirements):
        lines.append(f"- {heading}")
        for basis, label in EVIDENCE_BASIS_LABELS.items():
            if basis in groups:
                lines.append(f"  - {label}：" + "；".join(groups[basis]))
    if not lines:
        return ""
    return "\n\n## 来源复算依据\n\n" + "\n".join(lines)


def evidence_basis_references(requirements):
    """The texts the 来源复算依据 appendix writes that name requirement items and archived cells (item
    headings and sheet!range formulas); they state no business number."""
    references = []
    for heading, groups in _evidence_basis_groups(requirements):
        references.append(heading)
        references.extend(formula for formulas in groups.values() for formula in formulas)
    return list(dict.fromkeys(references))


def _evidence_basis_groups(requirements):
    for item in requirements.get("items", []):
        groups = {}
        for location in item.get("locations", []):
            evidence = location.get("evidence") or {}
            basis = evidence.get("evidence_basis")
            if basis not in EVIDENCE_BASIS_LABELS or location.get("status") not in {"answered", "estimated"}:
                continue
            groups.setdefault(basis, []).append(_basis_formula(evidence))
        if groups:
            yield f"{item['id']}（{item.get('metric')}）", {
                basis: list(dict.fromkeys(formulas)) for basis, formulas in groups.items()}


def _basis_formula(evidence):
    text = _range_text(evidence.get("recipe_location"), evidence.get("recipe_kind"))
    if evidence.get("recipe_scale") not in (None, "1"):
        text += "（单位换算）"
    factor = (evidence.get("factor") or {}).get("location")
    return f"{text} × （{_range_text(factor, 'ratio')}）" if factor else text


def _range_text(location, kind=None):
    if not isinstance(location, dict):
        return ""
    if isinstance(location.get("left"), dict) and isinstance(location.get("right"), dict):
        operator = "÷" if kind == "ratio" else "−"
        return f"{_range_text(location['left'])} {operator} {_range_text(location['right'])}"
    return f"{location.get('sheet')}!{location.get('range')}"
