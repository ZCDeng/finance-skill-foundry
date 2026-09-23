"""Stable run comparison helpers for explanation draft revisions."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any


NUMERIC_COLUMNS = {
    "actual",
    "budget",
    "baseline",
    "variance",
    "amount",
    "revenue",
    "cost",
    "expense",
    "profit",
    "contribution",
    "attainment",
    "ratio",
}


def compare_draft_runs(analysis, parent: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """Compare parent and revised draft runs using stable business identity.

    The comparison is intentionally conservative. It reports exact same-basis
    numeric changes, discloses changed source/scope basis, and refuses ambiguous
    duplicate keys instead of pairing rows by index.
    """

    if not parent:
        return {"schema_version": 1, "issues": [], "summary": {"status": "no_parent"}}
    parent_runs = _visible_runs(analysis, parent.get("run_ids", []))
    draft_runs = _visible_runs(analysis, draft.get("run_ids", []))
    if not parent_runs or not draft_runs:
        return {"schema_version": 1, "issues": [], "summary": {"status": "no_comparable_runs"}}

    old_index = _index_rows(parent_runs)
    new_index = _index_rows(draft_runs)
    issues: list[dict[str, Any]] = []
    comparable_keys = set(old_index) & set(new_index)
    if not comparable_keys:
        return {
            "schema_version": 1,
            "issues": [],
            "summary": {
                "status": "no_comparable_runs",
                "compared_business_keys": 0,
                "issue_count": 0,
            },
        }
    for key in sorted(comparable_keys, key=str):
        old_rows = old_index[key]
        new_rows = new_index[key]
        if len(old_rows) != 1 or len(new_rows) != 1:
            issues.append({
                "code": "revision_comparison_ambiguous",
                "business_key": key,
                "old_count": len(old_rows),
                "new_count": len(new_rows),
                "severity": "warning",
                "message": "同一业务指标存在重复行，未按行序任意比较。",
            })
            continue
        old = old_rows[0]
        new = new_rows[0]
        if old["basis"] != new["basis"]:
            issue = {
                "code": "revision_basis_changed",
                "business_key": key,
                "old_run_id": old["run_id"],
                "new_run_id": new["run_id"],
                "severity": "info",
                "old_basis": old["basis"],
                "new_basis": new["basis"],
                "message": "指标来源或口径发生变化，未作为同源数值回归处理。",
            }
            changed_columns = _changed_numeric_columns(old["values"], new["values"])
            if changed_columns:
                issue["changed_columns"] = changed_columns
                issue["severity"] = "warning"
                issue["message"] = "指标来源或口径及数值均发生变化，需核对并说明原因。"
            changed_hash_aliases = _changed_hash_aliases(old["basis"], new["basis"])
            if changed_hash_aliases:
                issue["changed_hash_aliases"] = changed_hash_aliases
            issues.append(issue)
            continue
        for column in sorted(set(old["values"]) & set(new["values"])):
            old_value = old["values"][column]
            new_value = new["values"][column]
            if old_value == new_value:
                continue
            issues.append({
                "code": "revision_numeric_regression",
                "business_key": key,
                "column": column,
                "old_value": str(old_value),
                "new_value": str(new_value),
                "old_run_id": old["run_id"],
                "new_run_id": new["run_id"],
                "severity": "error",
                "message": "同一来源和口径下的关键数值发生变化，需要解释或修正。",
            })
    status = "needs_attention" if issues else "pass"
    return {
        "schema_version": 1,
        "issues": issues,
        "summary": {
            "status": status,
            "compared_business_keys": len(comparable_keys),
            "issue_count": len(issues),
        },
    }


def _visible_runs(analysis, run_ids: Any) -> list[dict[str, Any]]:
    if not isinstance(run_ids, list):
        return []
    runs = []
    for run_id in dict.fromkeys(run_ids):
        try:
            run = analysis.get_run(run_id)
        except Exception:
            continue
        if run.get("execution_status") == "succeeded":
            runs.append(run)
    return runs


def _index_rows(runs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order, run in enumerate(runs):
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        for row_number, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            key = _business_key(run, row)
            if key is None:
                continue
            values = _numeric_values(row)
            if values:
                grouped[key].append({
                    "run_id": run["id"],
                    "run_seq": run.get("seq", order),
                    "row": row_number,
                    "basis": _basis(run, row),
                    "values": values,
                })
    index: dict[str, list[dict[str, Any]]] = {}
    for key, rows in grouped.items():
        latest = max(_sortable_seq(row.get("run_seq")) for row in rows)
        index[key] = [row for row in rows if _sortable_seq(row.get("run_seq")) == latest]
    return index


def _sortable_seq(value: Any) -> tuple[int, str]:
    if isinstance(value, bool):
        return (0, str(value))
    if isinstance(value, int):
        return (value, "")
    return (0, str(value))


def _business_key(run: dict[str, Any], row: dict[str, Any]) -> str | None:
    metric = row.get("metric_key") or row.get("metric") or row.get("label") or row.get("name")
    if not isinstance(metric, str) or not metric.strip():
        return None
    scope = row.get("scope") if isinstance(row.get("scope"), dict) else run.get("finance_scope", {})
    period = row.get("period") or row.get("period_key") or _scope_value(scope, "period") or ""
    organization = row.get("organization") or row.get("org") or row.get("region") or _scope_value(scope, "organization") or ""
    scenario = row.get("scenario") or row.get("baseline_scenario") or _scope_value(scope, "scenario") or ""
    aggregation = row.get("aggregation") or row.get("aggregation_definition") or row.get("basis") or row.get("value_kind") or ""
    unit = row.get("unit") or _scope_value(scope, "unit") or ""
    currency = row.get("currency") or _scope_value(scope, "currency") or ""
    return repr({
        "metric": metric.strip().casefold(),
        "period": period,
        "organization": organization,
        "scenario": scenario,
        "aggregation": aggregation,
        "unit": unit,
        "currency": currency,
    })


def _basis(run: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_hashes": run.get("input_hashes", {}),
        "source_hashes": run.get("source_hashes", {}),
        "scope": row.get("scope") if isinstance(row.get("scope"), dict) else run.get("finance_scope", {}),
        "assumption_id": row.get("assumption_id"),
    }


def _numeric_values(row: dict[str, Any]) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for key, value in row.items():
        if key not in NUMERIC_COLUMNS and not key.endswith(("_actual", "_budget", "_variance")):
            if key != "value" or not _is_declared_financial_value_row(row):
                continue
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if not decimal.is_finite():
            continue
        values[key] = decimal
    return values


def _is_declared_financial_value_row(row: dict[str, Any]) -> bool:
    return any(
        isinstance(row.get(key), str) and row.get(key).strip()
        for key in ("metric_key", "value_kind")
    )


def _changed_numeric_columns(old_values: dict[str, Decimal], new_values: dict[str, Decimal]) -> list[dict[str, str]]:
    changes = []
    for column in sorted(set(old_values) & set(new_values)):
        old_value = old_values[column]
        new_value = new_values[column]
        if old_value == new_value:
            continue
        changes.append({"column": column, "old_value": str(old_value), "new_value": str(new_value)})
    return changes


def _changed_hash_aliases(old_basis: dict[str, Any], new_basis: dict[str, Any]) -> list[dict[str, str]]:
    aliases = []
    for map_name in ("input_hashes", "source_hashes"):
        old_hashes = old_basis.get(map_name) if isinstance(old_basis.get(map_name), dict) else {}
        new_hashes = new_basis.get(map_name) if isinstance(new_basis.get(map_name), dict) else {}
        for alias in sorted(set(old_hashes) | set(new_hashes)):
            old_value = old_hashes.get(alias)
            new_value = new_hashes.get(alias)
            if old_value == new_value:
                continue
            aliases.append({
                "kind": map_name,
                "alias": str(alias),
                "old_value": str(old_value),
                "new_value": str(new_value),
            })
    return aliases


def _scope_value(scope: Any, key: str) -> Any:
    if not isinstance(scope, dict):
        return None
    values = [item.get(key) for item in scope.values() if isinstance(item, dict) and item.get(key)]
    return values[0] if values and all(value == values[0] for value in values) else None
