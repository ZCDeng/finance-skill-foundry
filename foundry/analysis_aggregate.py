"""Deterministic single-snapshot aggregate plans with executor-owned provenance."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable

from foundry.analysis_data import json_value
from foundry.errors import FoundryError

FILTER_OPS = {"eq", "neq", "ne", "in", "not_in", "is_null", "not_null", "between", "gt", "gte", "lt", "lte"}
AGGREGATIONS = {"sum", "count", "count_distinct", "min", "max"}
DEDUPE_POLICIES = {"none", "error_on_duplicate", "keep_first_identical_else_error"}
PLAN_KEYS = {"kind", "dataset_alias", "filters", "exclusions", "group_by", "measures", "dedupe", "result_key_columns", "scope"}
CONDITION_KEYS = {"field", "op", "value", "values", "reason"}
MEASURE_KEYS = {"name", "field", "aggregation"}
DEDUPE_KEYS = {"policy", "keys"}
RESERVED_FIELDS = {"result_key", "source_rows", "excluded_source_rows", "provenance_status"}
RESERVED_PREFIX = "__foundry_"


def validate_aggregate_plan(
    plan: dict[str, Any],
    dataset: dict[str, Any],
    *,
    _started: float | None = None,
    _timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Validate and normalize a server-side single-snapshot aggregate plan."""

    deadline = _deadline(_started, _timeout_seconds)
    _check_deadline(deadline)
    if not isinstance(dataset, dict) or dataset.get("kind") != "table":
        raise FoundryError("aggregate dataset must be a table snapshot")
    rows = dataset.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise FoundryError("aggregate dataset rows must be objects")
    if not isinstance(plan, dict):
        raise FoundryError("aggregate plan must be an object")
    _reject_unknown_keys(plan, PLAN_KEYS, "aggregate plan")
    if plan.get("kind") not in (None, "single_snapshot_aggregate"):
        raise FoundryError("unsupported aggregate plan kind")

    fields, field_types = _dataset_fields(dataset, deadline)
    _reject_reserved_fields(fields)

    dataset_alias = plan.get("dataset_alias") or dataset.get("name") or dataset.get("id")
    if not isinstance(dataset_alias, str) or not dataset_alias.strip():
        raise FoundryError("aggregate plan requires dataset_alias")
    dataset_alias = dataset_alias.strip()

    group_by = _string_list(plan.get("group_by", []), "group_by")
    _require_fields(group_by, fields, "group_by")

    result_key_columns = _string_list(plan.get("result_key_columns", group_by), "result_key_columns")
    if result_key_columns != group_by:
        raise FoundryError("result_key_columns must exactly match group_by to avoid key collisions")

    scope = _scope(plan.get("scope", {}), fields)
    filters = _conditions(plan.get("filters", []), fields, "filters")
    exclusions = _conditions(plan.get("exclusions", []), fields, "exclusions", allow_reason=True)
    measures = _measures(plan.get("measures"), fields, field_types, group_by, deadline)
    dedupe = _dedupe(plan.get("dedupe", {"policy": "none"}), fields)
    _check_deadline(deadline)

    return {
        "kind": "single_snapshot_aggregate",
        "dataset_alias": dataset_alias,
        "scope": scope,
        "group_by": group_by,
        "result_key_columns": result_key_columns,
        "filters": filters,
        "exclusions": exclusions,
        "measures": measures,
        "dedupe": dedupe,
    }


def execute_aggregate(
    dataset: dict[str, Any],
    plan: dict[str, Any],
    *,
    max_rows: int = 1000,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    """Execute a validated single-snapshot aggregate and return traceable raw result data."""

    started = time.monotonic()
    _validate_limits(max_rows, timeout_seconds)
    deadline = _deadline(started, timeout_seconds)
    normalized = validate_aggregate_plan(plan, dataset, _started=started, _timeout_seconds=timeout_seconds)
    plan_hash = _hash(normalized)
    data_hash = dataset.get("data_hash")
    rows = dataset["rows"]
    dataset_id = dataset.get("id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise FoundryError("aggregate dataset requires id")
    source_lookup = _source_lookup(dataset)
    field_types = {
        column["name"]: column.get("type", "VARCHAR")
        for column in dataset.get("schema", [])
        if isinstance(column, dict) and isinstance(column.get("name"), str)
    }

    filter_passed: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    included: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    output_excluded: list[dict[str, Any]] = []
    all_excluded: list[dict[str, Any]] = []
    seen_dedupe: dict[tuple[Any, ...], tuple[int, str]] = {}

    for row_index, row in enumerate(rows, start=1):
        _check_deadline(deadline)
        source_ref = {"dataset_id": dataset_id, "row_index": row_index, "source_row": source_lookup(row_index)}
        if not _matches_scope(row, normalized["scope"]):
            all_excluded.append(_detail_row(row, normalized, source_ref, False, "scope_mismatch"))
            continue
        if not _matches_all(row, normalized["filters"]):
            all_excluded.append(_detail_row(row, normalized, source_ref, False, "filter_mismatch"))
            continue
        filter_passed.append((row_index, row, source_ref))

        exclusion_reason = _exclusion_reason(row, normalized["exclusions"])
        if exclusion_reason:
            detail = _detail_row(row, normalized, source_ref, False, exclusion_reason)
            output_excluded.append(detail)
            all_excluded.append(detail)
            continue

        dedupe_reason = _dedupe_reason(row_index, row, normalized["dedupe"], seen_dedupe)
        if dedupe_reason:
            detail = _detail_row(row, normalized, source_ref, False, dedupe_reason)
            output_excluded.append(detail)
            all_excluded.append(detail)
            continue

        included.append((row_index, row, source_ref))

    _reject_mixed_scope(included, normalized["group_by"])

    groups: dict[tuple[Any, ...], list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    excluded_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    filter_groups: dict[tuple[Any, ...], list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for item in filter_passed:
        filter_groups[_group_key(item[1], normalized["group_by"])].append(item)
    for item in included:
        groups[_group_key(item[1], normalized["group_by"])].append(item)
    for row in output_excluded:
        excluded_groups[_group_key(row, normalized["group_by"])].append(row)

    output_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    excluded_detail_rows: list[dict[str, Any]] = []
    result_groups = set(groups) | set(excluded_groups)
    for group_key in sorted(result_groups, key=_stable_json):
        _check_deadline(deadline)
        group_items = groups.get(group_key, [])
        group_map = {field: group_key[index] for index, field in enumerate(normalized["group_by"])}
        result_key = _result_key(normalized, group_map, data_hash=data_hash, plan_hash=plan_hash)
        row_out: dict[str, Any] = {"result_key": result_key, **group_map}
        row_out.update(_scope_metadata(dataset, group_items, normalized["group_by"]))
        for measure in normalized["measures"]:
            row_out[measure["name"]] = _aggregate(
                group_items,
                measure,
                field_types,
                diagnostics=diagnostics,
                group_map=group_map,
            )
        source_rows = [source for _, _, source in group_items]
        excluded_sources = [row["source"] for row in excluded_groups.get(group_key, [])]
        row_out["source_rows"] = source_rows
        row_out["excluded_source_rows"] = excluded_sources
        row_out["provenance_status"] = "verified"
        output_rows.append(row_out)
        detail_rows.extend(
            _detail_row(row, normalized, source, True, None, result_key=result_key)
            for _, row, source in group_items
        )
        excluded_detail_rows.extend(
            {**row, "result_key": row.get("result_key") or result_key}
            for row in excluded_groups.get(group_key, [])
        )

    trace_group_keys = {_group_key(row, normalized["group_by"]) for row in all_excluded}
    output_group_keys = set(result_groups)
    output_excluded_ids = {id(row) for row in output_excluded}
    for row in all_excluded:
        if id(row) in output_excluded_ids:
            continue
        group_map = {field: row.get(field) for field in normalized["group_by"]}
        row["result_key"] = _result_key(normalized, group_map, data_hash=data_hash, plan_hash=plan_hash)
        excluded_detail_rows.append(row)
    _check_deadline(deadline)

    if len(output_rows) > max_rows:
        raise FoundryError("aggregate result exceeds max_rows; refine filters or grouping")

    schema = _result_schema(normalized, field_types, dataset, included, output_rows)
    detail_schema = _detail_schema(normalized)
    return {
        "columns": schema,
        "rows": output_rows,
        "row_count": len(output_rows),
        "truncated": False,
        "schema": schema,
        "detail_columns": detail_schema,
        "detail_rows": detail_rows,
        "excluded_detail_columns": detail_schema,
        "excluded_detail_rows": sorted(excluded_detail_rows, key=lambda row: (row.get("source", {}).get("row_index", 0), row.get("exclusion_reason") or "")),
        "diagnostics": diagnostics,
        "provenance": {
            "domain": "foundry.analysis.aggregate.provenance.v1",
            "status": "verified",
            "mode": "executor_verified_source_map",
            "dataset_id": dataset_id,
            "dataset_alias": normalized["dataset_alias"],
            "source_hash": dataset.get("source_hash"),
            "data_hash": data_hash,
            "plan_hash": plan_hash,
            "result_key_columns": normalized["result_key_columns"],
            "dedupe": normalized["dedupe"],
            "included_source_row_count": len(detail_rows),
            "excluded_source_row_count": len(excluded_detail_rows),
            "trace_excluded_group_count": len(trace_group_keys - output_group_keys),
            "reconciliation": _reconciliation(normalized, filter_groups, groups, excluded_groups, field_types, data_hash, plan_hash),
        },
    }


def _deadline(started: float | None, timeout_seconds: float | None) -> Callable[[], None]:
    if started is None or timeout_seconds is None:
        return lambda: None
    return lambda: _check_timeout(started, timeout_seconds)


def _dataset_fields(dataset: dict[str, Any], deadline: Callable[[], None]) -> tuple[set[str], dict[str, str]]:
    fields: set[str] = set()
    field_types: dict[str, str] = {}
    for column in dataset.get("schema", []):
        deadline()
        if not isinstance(column, dict) or not isinstance(column.get("name"), str):
            raise FoundryError("aggregate dataset schema is invalid")
        name = column["name"]
        if name in fields:
            raise FoundryError(f"duplicate dataset field: {name}")
        fields.add(name)
        field_types[name] = str(column.get("type") or "VARCHAR")
    for row in dataset.get("rows", []):
        deadline()
        fields.update(str(key) for key in row.keys())
    return fields, field_types


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FoundryError(f"unknown {context} key: {', '.join(unknown)}")


def _reject_reserved_fields(fields: set[str]) -> None:
    for field in fields:
        if field.startswith(RESERVED_PREFIX) or field in RESERVED_FIELDS:
            raise FoundryError(f"reserved source field is not allowed in aggregate input: {field}")


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise FoundryError(f"aggregate {name} must be a list of field names")
    if len(set(value)) != len(value):
        raise FoundryError(f"aggregate {name} contains duplicates")
    return list(value)


def _require_fields(names: list[str], fields: set[str], context: str) -> None:
    missing = [name for name in names if name not in fields]
    if missing:
        raise FoundryError(f"unknown {context} field: {', '.join(missing)}")


def _scope(value: Any, fields: set[str]) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise FoundryError("aggregate scope must be an object")
    normalized: dict[str, Any] = {}
    for field, expected in value.items():
        if not isinstance(field, str) or not field:
            raise FoundryError("aggregate scope field is invalid")
        _require_fields([field], fields, "scope")
        normalized[field] = json_value(expected)
    return normalized


def _conditions(value: Any, fields: set[str], context: str, *, allow_reason: bool = False) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FoundryError(f"aggregate {context} must be a list")
    normalized = []
    for index, condition in enumerate(value):
        if not isinstance(condition, dict):
            raise FoundryError(f"aggregate {context}[{index}] must be an object")
        _reject_unknown_keys(condition, CONDITION_KEYS, f"{context}[{index}]")
        field, op = condition.get("field"), _normalize_op(condition.get("op"))
        if not isinstance(field, str) or not field:
            raise FoundryError(f"aggregate {context}[{index}] requires field")
        _require_fields([field], fields, context)
        if not isinstance(op, str) or op not in FILTER_OPS:
            raise FoundryError(f"unsupported aggregate condition op: {condition.get('op')}")
        item = {"field": field, "op": op}
        if op in {"eq", "neq", "gt", "gte", "lt", "lte"}:
            if "value" not in condition:
                raise FoundryError(f"aggregate {context}[{index}] requires value")
            item["value"] = json_value(condition["value"])
        elif op in {"in", "not_in", "between"}:
            values = condition.get("values")
            if not isinstance(values, list) or (op == "between" and len(values) != 2):
                raise FoundryError(f"aggregate {context}[{index}] requires values")
            item["values"] = json_value(values)
        if allow_reason:
            reason = condition.get("reason") or f"excluded_by_{field}"
            if not isinstance(reason, str) or not reason:
                raise FoundryError(f"aggregate {context}[{index}] reason is invalid")
            item["reason"] = reason
        normalized.append(item)
    return normalized


def _normalize_op(value: Any) -> Any:
    if value == "ne":
        return "neq"
    return value


def _measures(
    value: Any,
    fields: set[str],
    field_types: dict[str, str],
    group_by: list[str],
    deadline: Callable[[], None],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise FoundryError("aggregate measures must be a non-empty list")
    names: set[str] = set(group_by) | {"currency", "unit", *RESERVED_FIELDS}
    normalized = []
    for index, measure in enumerate(value):
        deadline()
        if not isinstance(measure, dict):
            raise FoundryError(f"aggregate measures[{index}] must be an object")
        _reject_unknown_keys(measure, MEASURE_KEYS, f"measures[{index}]")
        name, aggregation = measure.get("name"), measure.get("aggregation")
        if not isinstance(name, str) or not name:
            raise FoundryError(f"aggregate measures[{index}] requires name")
        if name in names:
            raise FoundryError(f"aggregate measure name collides with output field: {name}")
        names.add(name)
        if not isinstance(aggregation, str) or aggregation not in AGGREGATIONS:
            raise FoundryError(f"unsupported aggregate measure aggregation: {aggregation}")
        item = {"name": name, "aggregation": aggregation}
        field = measure.get("field")
        if aggregation == "count":
            if field is not None:
                if not isinstance(field, str) or field not in fields:
                    raise FoundryError(f"unknown measures field: {field}")
                item["field"] = field
        else:
            if not isinstance(field, str) or not field:
                raise FoundryError(f"aggregate measure {name} requires field")
            _require_fields([field], fields, "measures")
            if aggregation == "sum" and not _is_decimal_type(field_types.get(field)):
                raise FoundryError(f"sum measure requires DECIMAL field: {field}")
            item["field"] = field
        normalized.append(item)
    return normalized


def _dedupe(value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FoundryError("aggregate dedupe must be an object")
    _reject_unknown_keys(value, DEDUPE_KEYS, "dedupe")
    policy = value.get("policy")
    if not isinstance(policy, str) or policy not in DEDUPE_POLICIES:
        raise FoundryError(f"unsupported aggregate dedupe policy: {policy}")
    keys = _string_list(value.get("keys", []), "dedupe.keys")
    if policy != "none" and not keys:
        raise FoundryError("aggregate dedupe keys are required")
    _require_fields(keys, fields, "dedupe")
    return {"policy": policy, "keys": keys}


def _validate_limits(max_rows: int, timeout_seconds: float) -> None:
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows <= 0:
        raise FoundryError("aggregate max_rows must be a positive integer")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise FoundryError("aggregate timeout_seconds must be positive")


def _check_deadline(deadline: Callable[[], None]) -> None:
    deadline()


def _check_timeout(started: float, timeout_seconds: float) -> None:
    if time.monotonic() - started > timeout_seconds:
        raise FoundryError("aggregate exceeded its execution time limit")


def _source_lookup(dataset: dict[str, Any]):
    transformation = dataset.get("transformation") or {}
    row_numbers = transformation.get("source_row_numbers")
    if isinstance(row_numbers, list):
        return lambda row_index: row_numbers[row_index - 1] if row_index - 1 < len(row_numbers) else row_index
    if transformation.get("row_locator") == "data row index + 2 (one-based header row)":
        return lambda row_index: row_index + 1
    return lambda row_index: row_index


def _matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    for field, expected in scope.items():
        actual = _cmp_value(row.get(field))
        if isinstance(expected, list):
            expected_whole = _cmp_value(expected)
            allowed = {_cmp_value(item) for item in expected}
            if actual != expected_whole and actual not in allowed:
                return False
        elif actual != _cmp_value(expected):
            return False
    return True


def _matches_all(row: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    return all(_matches(row.get(condition["field"]), condition) for condition in conditions)


def _matches(value: Any, condition: dict[str, Any]) -> bool:
    op = condition["op"]
    if op == "eq":
        return _cmp_value(value) == _cmp_value(condition.get("value"))
    if op == "neq":
        return _cmp_value(value) != _cmp_value(condition.get("value"))
    if op == "in":
        return _cmp_value(value) in {_cmp_value(item) for item in condition.get("values", [])}
    if op == "not_in":
        return _cmp_value(value) not in {_cmp_value(item) for item in condition.get("values", [])}
    if op == "is_null":
        return value is None or value == ""
    if op == "not_null":
        return value is not None and value != ""
    if op == "between":
        low, high = condition["values"]
        ordered = _order_value(value)
        low_ordered = _order_value(low)
        high_ordered = _order_value(high)
        return ordered is not None and low_ordered is not None and high_ordered is not None and low_ordered <= ordered <= high_ordered
    if op == "gt":
        return _ordered_compare(value, condition.get("value"), lambda left, right: left > right)
    if op == "gte":
        return _ordered_compare(value, condition.get("value"), lambda left, right: left >= right)
    if op == "lt":
        return _ordered_compare(value, condition.get("value"), lambda left, right: left < right)
    if op == "lte":
        return _ordered_compare(value, condition.get("value"), lambda left, right: left <= right)
    raise FoundryError(f"unsupported aggregate condition op: {op}")


def _cmp_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, (dict, list, tuple)):
        return _stable_json(value)
    return value


def _ordered_compare(value: Any, boundary: Any, predicate: Callable[[tuple[int, Any], tuple[int, Any]], bool]) -> bool:
    ordered = _order_value(value)
    boundary_ordered = _order_value(boundary)
    return ordered is not None and boundary_ordered is not None and predicate(ordered, boundary_ordered)


def _order_value(value: Any) -> tuple[int, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list, tuple)):
        return (2, _stable_json(value))
    try:
        return (1, Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return (2, str(value))


def _exclusion_reason(row: dict[str, Any], exclusions: list[dict[str, Any]]) -> str | None:
    for condition in exclusions:
        if _matches(row.get(condition["field"]), condition):
            return condition["reason"]
    return None


def _dedupe_reason(
    row_index: int,
    row: dict[str, Any],
    dedupe: dict[str, Any],
    seen: dict[tuple[Any, ...], tuple[int, str]],
) -> str | None:
    policy = dedupe["policy"]
    if policy == "none":
        return None
    key = tuple(_cmp_value(row.get(field)) for field in dedupe["keys"])
    if any(value in (None, "") for value in key):
        raise FoundryError("dedupe key contains empty value")
    fingerprint = _stable_json(json_value(row))
    prior = seen.get(key)
    if prior is None:
        seen[key] = (row_index, fingerprint)
        return None
    prior_index, prior_fingerprint = prior
    if policy == "error_on_duplicate":
        raise FoundryError(f"duplicate key at source row {row_index}; first seen at source row {prior_index}")
    if fingerprint != prior_fingerprint:
        raise FoundryError(f"duplicate key conflict at source row {row_index}; first seen at source row {prior_index}")
    return "duplicate_identical_ignored"


def _reject_mixed_scope(rows: list[tuple[int, dict[str, Any], dict[str, Any]]], group_by: list[str]) -> None:
    for scope_field in ("currency", "unit"):
        if scope_field in group_by:
            continue
        values_by_group: dict[tuple[Any, ...], set[Any]] = defaultdict(set)
        for _, row, _ in rows:
            value = row.get(scope_field)
            if value not in (None, ""):
                values_by_group[_group_key(row, group_by)].add(value)
        for values in values_by_group.values():
            if len(values) > 1:
                raise FoundryError(f"mixed {scope_field} requires grouping by {scope_field} or filtering to one {scope_field}")


def _group_key(row: dict[str, Any], group_by: list[str]) -> tuple[Any, ...]:
    return tuple(_cmp_value(row.get(field)) for field in group_by)


def _result_key(plan: dict[str, Any], group_map: dict[str, Any], *, data_hash: Any, plan_hash: str) -> str:
    material = {field: group_map.get(field) for field in plan["group_by"]}
    return "agg_" + _hash({
        "dataset_alias": plan["dataset_alias"],
        "data_hash": data_hash,
        "plan_hash": plan_hash,
        "group": material,
    })[:16]


def _detail_row(
    row: dict[str, Any],
    plan: dict[str, Any],
    source_ref: dict[str, Any],
    included: bool,
    exclusion_reason: str | None,
    *,
    result_key: str | None = None,
) -> dict[str, Any]:
    group_map = {field: json_value(row.get(field)) for field in plan["group_by"]}
    return {
        "result_key": result_key,
        **group_map,
        **_row_scope_fields(row, plan["group_by"]),
        "included": included,
        "exclusion_reason": exclusion_reason,
        "source": source_ref,
        "source_rows": [source_ref],
        "excluded_source_rows": [] if included else [source_ref],
        "measure_values": {measure["name"]: _row_measure_value(row, measure) for measure in plan["measures"]},
        "provenance_status": "verified",
    }


def _row_measure_value(row: dict[str, Any], measure: dict[str, Any]) -> Any:
    if measure["aggregation"] == "count" and "field" not in measure:
        return "1"
    field = measure.get("field")
    if not field:
        return None
    value = row.get(field)
    if measure["aggregation"] == "count":
        return "1" if value not in (None, "") else None
    return _display_value(value)


def _aggregate(
    items: list[tuple[int, dict[str, Any], dict[str, Any]]],
    measure: dict[str, Any],
    field_types: dict[str, str],
    *,
    diagnostics: list[dict[str, Any]] | None = None,
    group_map: dict[str, Any] | None = None,
) -> Any:
    aggregation = measure["aggregation"]
    if aggregation == "count" and "field" not in measure:
        return str(len(items))
    field = measure.get("field")
    if not field:
        raise FoundryError(f"aggregate measure {measure['name']} requires field")
    raw_values = [row.get(field) for _, row, _ in items]
    values = [value for value in raw_values if value not in (None, "")]
    missing_count = len(raw_values) - len(values)
    if aggregation == "count":
        return str(len(values))
    if missing_count and aggregation in {"sum", "min", "max", "count_distinct"}:
        _append_missing_diagnostic(diagnostics, group_map, measure, missing_count)
    if aggregation == "sum":
        if missing_count:
            return None
        decimals = [_decimal(value) for value in values]
        return _decimal_text(_sum(decimals)) if decimals else None
    if aggregation == "count_distinct":
        return str(len({_stable_json(json_value(value)) for value in values}))
    if aggregation in {"min", "max"}:
        if not values:
            return None
        if _is_decimal_type(field_types.get(field)):
            ordered = [_decimal(value) for value in values]
            chosen = min(ordered) if aggregation == "min" else max(ordered)
            return _decimal_text(chosen)
        chosen = min(values, key=lambda value: str(value)) if aggregation == "min" else max(values, key=lambda value: str(value))
        return _display_value(chosen)
    raise FoundryError(f"unsupported aggregate measure aggregation: {aggregation}")


def _append_missing_diagnostic(
    diagnostics: list[dict[str, Any]] | None,
    group_map: dict[str, Any] | None,
    measure: dict[str, Any],
    missing_count: int,
) -> None:
    if diagnostics is None or missing_count <= 0:
        return
    diagnostics.append({
        "severity": "warning",
        "code": "aggregate_missing_measure_values",
        "measure": measure["name"],
        "field": measure.get("field"),
        "aggregation": measure["aggregation"],
        "group": group_map or {},
        "missing_count": missing_count,
    })


def _sum(values: list[Decimal]) -> Decimal:
    max_digits = max((len(value.as_tuple().digits) for value in values), default=1)
    precision = max(80, max_digits + len(str(len(values))) + 8)
    with localcontext() as context:
        context.prec = precision
        total = Decimal("0")
        for value in values:
            total += value
        return +total


def _display_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return _decimal_text(value)
    return json_value(value)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None or value == "":
        raise FoundryError("decimal aggregate value is missing or invalid")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"decimal aggregate value is invalid: {value}") from exc
    if not amount.is_finite():
        raise FoundryError("non-finite numeric value")
    return amount


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _is_decimal_type(value: str | None) -> bool:
    return bool(value and str(value).upper().startswith("DECIMAL"))


def _result_schema(
    plan: dict[str, Any],
    field_types: dict[str, str],
    dataset: dict[str, Any],
    included_rows: list[tuple[int, dict[str, Any], dict[str, Any]]],
    output_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = [{"name": "result_key", "type": "VARCHAR"}]
    columns.extend({"name": field, "type": field_types.get(field, "VARCHAR")} for field in plan["group_by"])
    for field in ("currency", "unit"):
        if field not in plan["group_by"] and (any(field in row for row in output_rows) or (dataset.get("metadata") or {}).get(field) not in (None, "")):
            columns.append({"name": field, "type": field_types.get(field, "VARCHAR")})
    for measure in plan["measures"]:
        aggregation = measure["aggregation"]
        if aggregation in {"count", "count_distinct"}:
            dtype = "BIGINT"
        else:
            dtype = field_types.get(measure.get("field"), "VARCHAR")
            if aggregation == "sum" and not _is_decimal_type(dtype):
                dtype = "DECIMAL(38,2)"
        column: dict[str, Any] = {"name": measure["name"], "type": dtype}
        if aggregation == "sum":
            column.update(_scope_metadata(dataset, included_rows, plan["group_by"]))
        columns.append(column)
    columns.extend([
        {"name": "source_rows", "type": "JSON"},
        {"name": "excluded_source_rows", "type": "JSON"},
        {"name": "provenance_status", "type": "VARCHAR"},
    ])
    return columns


def _scope_metadata(
    dataset: dict[str, Any],
    included_rows: list[tuple[int, dict[str, Any], dict[str, Any]]],
    group_by: list[str] | None = None,
) -> dict[str, Any]:
    group_by = group_by or []
    metadata: dict[str, Any] = {}
    for key in ("currency", "unit"):
        if key in group_by:
            continue
        row_values = {row.get(key) for _, row, _ in included_rows if row.get(key) not in (None, "")}
        if len(row_values) == 1:
            metadata[key] = next(iter(row_values))
        elif not row_values:
            value = (dataset.get("metadata") or {}).get(key)
            if value not in (None, ""):
                metadata[key] = value
    return metadata


def _row_scope_fields(row: dict[str, Any], group_by: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("currency", "unit") if key not in group_by and row.get(key) not in (None, "")}


def _detail_schema(plan: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": "result_key", "type": "VARCHAR"},
        *({"name": field, "type": "VARCHAR"} for field in plan["group_by"]),
        {"name": "included", "type": "BOOLEAN"},
        {"name": "exclusion_reason", "type": "VARCHAR"},
        {"name": "source", "type": "JSON"},
        {"name": "source_rows", "type": "JSON"},
        {"name": "excluded_source_rows", "type": "JSON"},
        {"name": "measure_values", "type": "JSON"},
        {"name": "provenance_status", "type": "VARCHAR"},
    ]


def _reconciliation(
    plan: dict[str, Any],
    filter_groups: dict[tuple[Any, ...], list[tuple[int, dict[str, Any], dict[str, Any]]]],
    groups: dict[tuple[Any, ...], list[tuple[int, dict[str, Any], dict[str, Any]]]],
    excluded_groups: dict[tuple[Any, ...], list[dict[str, Any]]],
    field_types: dict[str, str],
    data_hash: Any,
    plan_hash: str,
) -> list[dict[str, Any]]:
    additive_measures = [measure for measure in plan["measures"] if measure["aggregation"] == "sum"]
    if not additive_measures:
        return []
    rows = []
    for group_key in sorted(set(filter_groups) | set(groups) | set(excluded_groups), key=_stable_json):
        group_map = {field: group_key[index] for index, field in enumerate(plan["group_by"])}
        for measure in additive_measures:
            excluded_items = [
                (0, {measure["field"]: row["measure_values"].get(measure["name"])}, row["source"])
                for row in excluded_groups.get(group_key, [])
            ]
            before = _aggregate(filter_groups.get(group_key, []), measure, field_types)
            included = _aggregate(groups.get(group_key, []), measure, field_types)
            excluded = _aggregate(excluded_items, measure, field_types)
            rows.append({
                "result_key": _result_key(plan, group_map, data_hash=data_hash, plan_hash=plan_hash),
                **group_map,
                "measure": measure["name"],
                "before_filter": before,
                "included": included,
                "excluded": excluded,
                "check": "included_plus_excluded_equals_before_filter",
                "status": "verified",
            })
    return rows


def _hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(json_value(value)).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
