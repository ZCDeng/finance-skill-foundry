import pytest

from foundry.analysis_aggregate import execute_aggregate, validate_aggregate_plan
from foundry.errors import FoundryError


def dataset(rows, *, dataset_id="d1", source_hash="source-hash", data_hash="data-hash"):
    headers = sorted({key for row in rows for key in row})
    schema = []
    for name in headers:
        values = [row.get(name) for row in rows if row.get(name) is not None]
        if values and all(str(value).replace(".", "", 1).replace("-", "", 1).isdigit() for value in values):
            schema.append({"name": name, "type": "DECIMAL(38,2)", "nullable": len(values) != len(rows)})
        else:
            schema.append({"name": name, "type": "VARCHAR", "nullable": len(values) != len(rows)})
    return {
        "id": dataset_id,
        "name": "actual",
        "kind": "table",
        "source_hash": source_hash,
        "data_hash": data_hash,
        "source_name": "actual.csv",
        "schema": schema,
        "rows": rows,
        "row_count": len(rows),
        "metadata": {},
        "transformation": {"row_locator": "one-based JSON row index"},
    }


def base_plan(**overrides):
    plan = {
        "dataset_alias": "actual",
        "group_by": ["period", "region"],
        "filters": [{"field": "account", "op": "eq", "value": "revenue"}],
        "exclusions": [],
        "measures": [{"name": "revenue", "field": "amount", "aggregation": "sum"}],
        "result_key_columns": ["period", "region"],
        "dedupe": {"policy": "none"},
    }
    plan.update(overrides)
    return plan


def test_same_amount_different_region_traces_only_filtered_source_row():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华南", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
    ])
    result = execute_aggregate(data, base_plan(filters=[
        {"field": "account", "op": "eq", "value": "revenue"},
        {"field": "region", "op": "eq", "value": "华东"},
    ]))

    assert result["provenance"]["status"] == "verified"
    assert result["provenance"]["mode"] == "executor_verified_source_map"
    assert result["rows"] == [{
        "result_key": result["rows"][0]["result_key"],
        "period": "2026-08",
        "region": "华东",
        "currency": "CNY",
        "unit": "元",
        "revenue": "100",
        "source_rows": [{"dataset_id": "d1", "row_index": 1, "source_row": 1}],
        "excluded_source_rows": [],
        "provenance_status": "verified",
    }]
    assert result["detail_rows"][0]["source"] == {"dataset_id": "d1", "row_index": 1, "source_row": 1}
    assert result["detail_rows"][0]["measure_values"] == {"revenue": "100"}
    revenue_column = next(column for column in result["columns"] if column["name"] == "revenue")
    assert revenue_column["type"] == "DECIMAL(38,2)"
    assert revenue_column["unit"] == "元"
    assert revenue_column["currency"] == "CNY"


def test_plan_rejects_reserved_foundry_source_fields():
    data = dataset([
        {"period": "2026-08", "region": "华东", "amount": "100", "__foundry_row_index": "999"}
    ])

    with pytest.raises(FoundryError, match="reserved source field"):
        validate_aggregate_plan(base_plan(), data)


def test_explicit_exclusion_keeps_excluded_source_rows_without_included_rows():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "source_status": "voided", "amount": "100", "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(exclusions=[
        {"field": "source_status", "op": "in", "values": ["voided"], "reason": "voided_row"},
    ]))

    assert result["rows"] == [{
        "result_key": result["rows"][0]["result_key"],
        "period": "2026-08",
        "region": "华东",
        "revenue": None,
        "source_rows": [],
        "excluded_source_rows": [{"dataset_id": "d1", "row_index": 1, "source_row": 1}],
        "provenance_status": "verified",
    }]
    assert result["excluded_detail_rows"][0]["exclusion_reason"] == "voided_row"
    assert result["excluded_detail_rows"][0]["source_rows"] == [{"dataset_id": "d1", "row_index": 1, "source_row": 1}]
    assert result["provenance"]["reconciliation"][0]["before_filter"] == "100"
    assert result["provenance"]["reconciliation"][0]["included"] is None
    assert result["provenance"]["reconciliation"][0]["excluded"] == "100"


def test_dedupe_error_on_duplicate_conflicting_business_key():
    data = dataset([
        {"doc_id": "D1", "line_id": "1", "period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"doc_id": "D1", "line_id": "1", "period": "2026-08", "region": "华东", "account": "revenue", "amount": "120", "currency": "CNY", "unit": "元"},
    ])

    with pytest.raises(FoundryError, match="duplicate key"):
        execute_aggregate(data, base_plan(dedupe={"policy": "keep_first_identical_else_error", "keys": ["doc_id", "line_id"]}))


def test_identical_duplicate_is_excluded_with_reason_and_reconciliation():
    row = {"doc_id": "D1", "line_id": "1", "period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"}
    data = dataset([dict(row), dict(row)])

    result = execute_aggregate(data, base_plan(dedupe={"policy": "keep_first_identical_else_error", "keys": ["doc_id", "line_id"]}))

    assert result["rows"][0]["revenue"] == "100"
    assert result["detail_rows"][0]["source"]["row_index"] == 1
    assert result["excluded_detail_rows"][0]["source"]["row_index"] == 2
    assert result["excluded_detail_rows"][0]["exclusion_reason"] == "duplicate_identical_ignored"
    assert result["provenance"]["reconciliation"][0]["before_filter"] == "200"
    assert result["provenance"]["reconciliation"][0]["included"] == "100"
    assert result["provenance"]["reconciliation"][0]["excluded"] == "100"


@pytest.mark.parametrize("op,condition", [
    ("is_null", {"field": "region", "op": "is_null"}),
    ("not_null", {"field": "region", "op": "not_null"}),
])
def test_null_filters_do_not_treat_missing_amount_as_zero(op, condition):
    data = dataset([
        {"period": "2026-08", "region": None, "account": "revenue", "amount": None, "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "10", "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(group_by=["period"], result_key_columns=["period"], filters=[condition], measures=[{"name": "revenue", "field": "amount", "aggregation": "sum"}]))

    if op == "is_null":
        assert result["rows"][0]["revenue"] is None
        assert result["detail_rows"][0]["measure_values"] == {"revenue": None}
    else:
        assert result["rows"][0]["revenue"] == "10"


def test_between_gte_lte_and_not_in_filters():
    data = dataset([
        {"period": "2026-07", "region": "华东", "account": "revenue", "amount": "7", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "8", "currency": "CNY", "unit": "元"},
        {"period": "2026-09", "region": "华东", "account": "cost", "amount": "9", "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(group_by=["region"], result_key_columns=["region"], filters=[
        {"field": "period", "op": "between", "values": ["2026-07", "2026-08"]},
        {"field": "period", "op": "gte", "value": "2026-07"},
        {"field": "period", "op": "lte", "value": "2026-08"},
        {"field": "account", "op": "not_in", "values": ["cost"]},
    ]))

    assert result["rows"][0]["revenue"] == "15"
    assert [row["source"]["row_index"] for row in result["detail_rows"]] == [1, 2]


def test_cross_currency_requires_currency_group_or_scope_filter():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "USD", "unit": "元"},
    ])

    with pytest.raises(FoundryError, match="currency"):
        execute_aggregate(data, base_plan(group_by=["period", "region"], result_key_columns=["period", "region"]))

    grouped = execute_aggregate(data, base_plan(group_by=["period", "region", "currency"], result_key_columns=["period", "region", "currency"]))
    assert [row["currency"] for row in grouped["rows"]] == ["CNY", "USD"]


def test_result_keys_are_stable_when_input_order_changes():
    rows = [
        {"period": "2026-08", "region": "华南", "account": "revenue", "amount": "20", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "10", "currency": "CNY", "unit": "元"},
    ]
    result = execute_aggregate(dataset(rows), base_plan())
    reordered = execute_aggregate(dataset(list(reversed(rows))), base_plan())

    keys = {(row["period"], row["region"]): row["result_key"] for row in result["rows"]}
    reordered_keys = {(row["period"], row["region"]): row["result_key"] for row in reordered["rows"]}
    assert keys == reordered_keys


def test_count_distinct_min_max_do_not_claim_additive_reconciliation():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "customer": "A", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "80", "customer": "A", "currency": "CNY", "unit": "元"},
    ])
    result = execute_aggregate(data, base_plan(measures=[
        {"name": "rows", "aggregation": "count"},
        {"name": "customers", "field": "customer", "aggregation": "count_distinct"},
        {"name": "min_amount", "field": "amount", "aggregation": "min"},
        {"name": "max_amount", "field": "amount", "aggregation": "max"},
    ]))

    row = result["rows"][0]
    assert row["rows"] == "2"
    assert row["customers"] == "1"
    assert row["min_amount"] == "80"
    assert row["max_amount"] == "100"
    assert result["provenance"]["reconciliation"] == []


def test_validate_accepts_its_own_normalized_plan_kind_for_rerun():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
    ])

    normalized = validate_aggregate_plan(base_plan(), data)

    assert validate_aggregate_plan(normalized, data) == normalized
    with pytest.raises(FoundryError, match="unsupported aggregate plan kind"):
        validate_aggregate_plan({**base_plan(), "kind": "model_claimed"}, data)


def test_filter_mismatch_is_traceable_but_not_a_result_group():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华南", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(filters=[{"field": "region", "op": "eq", "value": "华东"}]))

    assert [row["region"] for row in result["rows"]] == ["华东"]
    assert [(row["region"], row["exclusion_reason"], row["source"]["row_index"]) for row in result["excluded_detail_rows"]] == [
        ("华南", "filter_mismatch", 2)
    ]
    assert result["excluded_detail_rows"][0]["source_rows"] == [{"dataset_id": "d1", "row_index": 2, "source_row": 2}]


def test_scope_is_executed_and_scope_mismatch_is_traceable():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "20", "currency": "USD", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(scope={"currency": "CNY"}))

    assert result["rows"][0]["revenue"] == "100"
    assert result["excluded_detail_rows"][0]["exclusion_reason"] == "scope_mismatch"
    assert result["excluded_detail_rows"][0]["source"]["row_index"] == 2


def test_unknown_plan_member_keys_are_rejected():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100"},
    ])

    with pytest.raises(FoundryError, match="unknown aggregate plan key"):
        validate_aggregate_plan({**base_plan(), "source_rows": []}, data)
    with pytest.raises(FoundryError, match=r"unknown filters\[0\] key"):
        validate_aggregate_plan(base_plan(filters=[{"field": "region", "op": "eq", "value": "华东", "source_rows": []}]), data)
    with pytest.raises(FoundryError, match=r"unknown measures\[0\] key"):
        validate_aggregate_plan(base_plan(measures=[{"name": "revenue", "field": "amount", "aggregation": "sum", "source_rows": []}]), data)
    with pytest.raises(FoundryError, match="unknown dedupe key"):
        validate_aggregate_plan(base_plan(dedupe={"policy": "none", "source_rows": []}), data)


def test_result_key_columns_must_cover_full_group_and_data_hash_changes_key():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
    ], data_hash="hash-a")

    with pytest.raises(FoundryError, match="exactly match group_by"):
        validate_aggregate_plan(base_plan(result_key_columns=["period"]), data)

    key_a = execute_aggregate(data, base_plan())["rows"][0]["result_key"]
    key_b = execute_aggregate(dataset(data["rows"], data_hash="hash-b"), base_plan())["rows"][0]["result_key"]
    assert key_a != key_b


def test_source_row_uses_parse_source_physical_row_locator():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
    ])
    data["transformation"] = {"row_locator": "data row index + 2 (one-based header row)"}

    result = execute_aggregate(data, base_plan())

    assert result["rows"][0]["source_rows"] == [{"dataset_id": "d1", "row_index": 1, "source_row": 2}]


def test_sum_with_missing_amount_is_not_silently_completed():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": None, "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan())

    assert result["rows"][0]["revenue"] is None
    assert result["diagnostics"] == [{
        "severity": "warning",
        "code": "aggregate_missing_measure_values",
        "measure": "revenue",
        "field": "amount",
        "aggregation": "sum",
        "group": {"period": "2026-08", "region": "华东"},
        "missing_count": 1,
    }]


def test_count_field_and_min_max_distinct_report_missing_values():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "customer": "A", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": None, "customer": None, "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(measures=[
        {"name": "amount_rows", "field": "amount", "aggregation": "count"},
        {"name": "customers", "field": "customer", "aggregation": "count_distinct"},
        {"name": "min_amount", "field": "amount", "aggregation": "min"},
        {"name": "max_amount", "field": "amount", "aggregation": "max"},
    ]))

    row = result["rows"][0]
    assert row["amount_rows"] == "1"
    assert row["customers"] == "1"
    assert row["min_amount"] == "100"
    assert row["max_amount"] == "100"
    assert [(item["measure"], item["missing_count"]) for item in result["diagnostics"]] == [
        ("customers", 1), ("min_amount", 1), ("max_amount", 1)
    ]


def test_decimal_sum_does_not_round_to_default_context_precision():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "99999999999999999999999999999999999999", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "1", "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan())

    assert result["rows"][0]["revenue"] == "100000000000000000000000000000000000000"


def test_aggregate_timeout_applies_during_validation(monkeypatch):
    ticks = iter([0, 1, 3])
    monkeypatch.setattr("foundry.analysis_aggregate.time.monotonic", lambda: next(ticks))

    with pytest.raises(FoundryError, match="execution time limit"):
        execute_aggregate(dataset([
            {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100"},
        ]), base_plan(), timeout_seconds=1)


def test_non_string_operator_aggregation_and_policy_raise_foundry_error():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100"},
    ])

    with pytest.raises(FoundryError, match="unsupported aggregate condition op"):
        validate_aggregate_plan(base_plan(filters=[{"field": "region", "op": [], "value": "华东"}]), data)
    with pytest.raises(FoundryError, match="unsupported aggregate measure aggregation"):
        validate_aggregate_plan(base_plan(measures=[{"name": "revenue", "field": "amount", "aggregation": []}]), data)
    with pytest.raises(FoundryError, match="unsupported aggregate dedupe policy"):
        validate_aggregate_plan(base_plan(dedupe={"policy": [], "keys": []}), data)


def test_range_filters_do_not_match_null_or_blank_values():
    data = dataset([
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "100", "age": None},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "10", "age": ""},
        {"period": "2026-08", "region": "华东", "account": "revenue", "amount": "5", "age": "5"},
    ])

    between = execute_aggregate(data, base_plan(filters=[{"field": "age", "op": "between", "values": ["1", "10"]}]))
    lt = execute_aggregate(data, base_plan(filters=[{"field": "age", "op": "lt", "value": "10"}]))

    assert between["rows"][0]["revenue"] == "5"
    assert lt["rows"][0]["revenue"] == "5"
    assert [row["exclusion_reason"] for row in between["excluded_detail_rows"]] == ["filter_mismatch", "filter_mismatch"]


def test_source_result_key_field_is_reserved():
    data = dataset([
        {"result_key": "model-forged", "period": "2026-08", "region": "华东", "account": "revenue", "amount": "100"},
    ])

    with pytest.raises(FoundryError, match="reserved source field"):
        validate_aggregate_plan(base_plan(group_by=["result_key"], result_key_columns=["result_key"]), data)


def test_nested_condition_scope_and_group_values_do_not_raise_type_error():
    data = dataset([
        {"period": "2026-08", "region": {"name": "华东"}, "tag": ["core"], "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "region": {"name": "华南"}, "tag": ["trial"], "account": "revenue", "amount": "20", "currency": "CNY", "unit": "元"},
    ])

    result = execute_aggregate(data, base_plan(
        scope={"tag": ["core"]},
        group_by=["region"],
        result_key_columns=["region"],
        filters=[{"field": "region", "op": "eq", "value": {"name": "华东"}}],
    ))

    assert result["rows"][0]["revenue"] == "100"
    assert result["excluded_detail_rows"][0]["exclusion_reason"] == "scope_mismatch"


def test_group_level_currency_and_unit_are_preserved_without_currency_grouping():
    data = dataset([
        {"period": "2026-08", "department": "销售", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
        {"period": "2026-08", "department": "海外", "account": "revenue", "amount": "20", "currency": "USD", "unit": "美元"},
    ])

    result = execute_aggregate(data, base_plan(group_by=["department"], result_key_columns=["department"]))

    rows = {row["department"]: row for row in result["rows"]}
    assert rows["销售"]["currency"] == "CNY"
    assert rows["销售"]["unit"] == "元"
    assert rows["海外"]["currency"] == "USD"
    assert rows["海外"]["unit"] == "美元"
    columns = {column["name"]: column for column in result["columns"]}
    assert columns["currency"]["type"] == "VARCHAR"
    assert columns["unit"]["type"] == "VARCHAR"


def test_measure_name_cannot_collide_with_scope_output_fields():
    data = dataset([
        {"period": "2026-08", "department": "销售", "account": "revenue", "amount": "100", "currency": "CNY", "unit": "元"},
    ])

    with pytest.raises(FoundryError, match="collides with output field"):
        validate_aggregate_plan(base_plan(
            group_by=["department"],
            result_key_columns=["department"],
            measures=[{"name": "currency", "field": "amount", "aggregation": "sum"}],
        ), data)
