"""SQL over explicit in-memory snapshots, never a window or host connection.

Boundary settings follow DuckDB's securing_duckdb/overview documentation:
external access/extension autoload disabled; no spill directory; locked settings.
This is a fixed SQL interface, not an operating-system sandbox for scripts.
"""

from __future__ import annotations

import json
import math
import tempfile
import threading
from collections import Counter
from decimal import Decimal
from typing import Any

import duckdb

from foundry.analysis_parameters import shared_parameter_metadata
from foundry.errors import FoundryError


CONFIG = {
    "enable_external_access": False,
    "autoload_known_extensions": False,
    "autoinstall_known_extensions": False,
    "allow_community_extensions": False,
    "allow_unsigned_extensions": False,
    "memory_limit": "256MB",
    "threads": 1,
    "max_temp_directory_size": "0B",
    "temp_directory": "",
}
STAGING_CONFIG = {**CONFIG, "enable_external_access": True}
RELATIONSHIP_CARDINALITIES = {
    "one-to-one",
    "one-to-many",
    "many-to-one",
    "many-to-many",
}
SAFE_TABLE_FUNCTIONS = {"range", "generate_series", "unnest"}
FORBIDDEN_FUNCTIONS = {
    "query",
    "query_table",
    "getenv",
    "read_blob",
    "read_text",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_parquet",
    "parquet_scan",
    "csv_scan",
    "json_scan",
    "glob",
    "nextval",
    "setval",
    "currval",
    "setseed",
    "write_log",
    "checkpoint",
    "force_checkpoint",
}
VOLATILE_FUNCTIONS = {
    "random",
    "uuid",
    "uuidv4",
    "uuidv7",
    "now",
    "current_timestamp",
    "current_date",
    "today",
    "get_current_timestamp",
    "transaction_timestamp",
}


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def validate_sql(connection, sql: str, aliases: set[str]) -> dict:
    statements = connection.extract_statements(sql)
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise FoundryError("exactly one parsed SELECT/CTE statement is allowed")
    # PRAGMA may be rewritten by extract_statements; serialize the original,
    # which only accepts SELECT, so that a rewrite does not broaden this API.
    tree = json.loads(
        connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
    )
    if tree.get("error") or len(tree.get("statements", [])) != 1:
        raise FoundryError("SQL must parse as one SELECT/CTE query")
    nodes = list(_walk(tree))
    ctes = {
        str(entry["key"]).casefold()
        for node in nodes
        for entry in node.get("cte_map", {}).get("map", [])
    }
    allowed = {name.casefold() for name in aliases} | ctes
    tables, volatile = set(), []
    for node in nodes:
        if node.get("type") == "BASE_TABLE":
            table = str(node.get("table_name", "")).casefold()
            if (
                table not in allowed
                or node.get("schema_name")
                or node.get("catalog_name")
            ):
                raise FoundryError(
                    f"SQL table is not an explicitly bound snapshot: {table}"
                )
            if table in {name.casefold() for name in aliases}:
                tables.add(table)
        if node.get("type") == "TABLE_FUNCTION":
            name = str(node.get("function", {}).get("function_name", "")).lower()
            if name not in SAFE_TABLE_FUNCTIONS:
                raise FoundryError(
                    f"table function is outside the SQL capability: {name}"
                )
        name = str(node.get("function_name", "")).lower()
        if name in FORBIDDEN_FUNCTIONS or name.startswith(
            (
                "read_",
                "duckdb_",
                "pragma_",
                "sqlite_",
                "postgres_",
                "http_",
                "json_execute_",
            )
        ):
            raise FoundryError(f"function is outside the SQL capability: {name}")
        if name in VOLATILE_FUNCTIONS or node.get("sample"):
            volatile.append(name or "sampling")
    return {
        "tables": sorted(tables),
        "has_join": any(n.get("type") == "JOIN" for n in nodes),
        "volatile": sorted(set(volatile)),
        "tree": tree,
    }


def _validate_join_keys(
    parsed: dict, relationships: list[dict], datasets: dict
) -> None:
    """A declared relationship must describe the actual parsed JOIN predicate.

    Fail closed for computed/cast/OR keys; normalize such keys in a snapshot or
    CTE before declaring the relation. Ordinary conjunctive filters are allowed.
    """
    nodes = list(_walk(parsed["tree"]))
    cte_sources = {}
    for node in nodes:
        for entry in node.get("cte_map", {}).get("map", []):
            cte_sources[entry["key"].casefold()] = {
                n["table_name"].casefold()
                for n in _walk(entry["value"])
                if n.get("type") == "BASE_TABLE"
            }

    def sources(name, seen=None):
        if name in {a.casefold() for a in datasets}:
            return {name}
        seen = set(seen or ())
        if name in seen:
            return set()
        seen.add(name)
        return set().union(*(sources(n, seen) for n in cte_sources.get(name, set())))

    def side(ref):
        if ref.get("type") == "BASE_TABLE":
            name = ref["table_name"].casefold()
            if name not in {alias.casefold() for alias in datasets}:
                raise FoundryError(
                    "JOIN derived relations require a materialized snapshot with its own grain contract"
                )
            return {str(ref.get("alias") or name).casefold(): sources(name)}
        if ref.get("type") == "SUBQUERY":
            raise FoundryError(
                "JOIN derived relations require a materialized snapshot with its own grain contract"
            )
        if ref.get("type") == "JOIN":
            return {**side(ref["left"]), **side(ref["right"])}
        return {}

    def equalities(condition):
        if not condition:
            return []
        if condition.get("type") == "CONJUNCTION_AND":
            return [
                pair
                for child in condition.get("children", [])
                for pair in equalities(child)
            ]
        if condition.get("type") == "COMPARE_EQUAL":
            left, right = condition.get("left", {}), condition.get("right", {})
            if left.get("type") == right.get("type") == "COLUMN_REF":
                return [(left["column_names"], right["column_names"])]
        return []

    for join in (n for n in nodes if n.get("type") == "JOIN"):
        left, right = side(join["left"]), side(join["right"])
        lnames, rnames = (
            set().union(*left.values()) if left else set(),
            set().union(*right.values()) if right else set(),
        )
        if not lnames and not rnames:
            continue
        if not lnames or not rnames:
            raise FoundryError(
                "JOIN involving a snapshot and generated rows requires an explicit materialized input"
            )
        candidates = [
            r
            for r in relationships
            if r.get("left", "").casefold() in lnames
            and r.get("right", "").casefold() in rnames
        ]
        pairs = equalities(join.get("condition"))
        valid = False
        for relation in candidates:
            lk = relation.get("left_keys") or relation.get("keys") or []
            rk = relation.get("right_keys") or relation.get("keys") or []
            using = join.get("using_columns", [])
            if using and lk == rk and set(lk).issubset(using):
                valid = True
                break
            aliases = {**left, **right}
            mapped = set()
            for a, b in pairs:
                if len(a) == 2 and len(b) == 2:
                    for ta in aliases.get(str(a[0]).casefold(), set()):
                        for tb in aliases.get(str(b[0]).casefold(), set()):
                            mapped.add(
                                (ta, str(a[1]).casefold(), tb, str(b[1]).casefold())
                            )
                            mapped.add(
                                (tb, str(b[1]).casefold(), ta, str(a[1]).casefold())
                            )
            if (
                lk
                and len(lk) == len(rk)
                and all(
                    (
                        relation["left"].casefold(),
                        a.casefold(),
                        relation["right"].casefold(),
                        b.casefold(),
                    )
                    in mapped
                    for a, b in zip(lk, rk)
                )
            ):
                valid = True
                break
        if not valid:
            raise FoundryError(
                "actual SQL JOIN keys do not match a declared relationship; use explicit equality keys"
            )


def validate_relationship_contract(
    relationships: Any, aliases: set[str] | None = None
) -> list[dict]:
    if not isinstance(relationships, list):
        raise FoundryError("relationships must be an array")
    checked = []
    for index, relationship in enumerate(relationships, start=1):
        label = f"relationship #{index}"
        if not isinstance(relationship, dict):
            raise FoundryError(
                f"{label} must be an object with left, right, left_keys, right_keys and cardinality"
            )
        left, right = relationship.get("left"), relationship.get("right")
        if (
            not isinstance(left, str)
            or not left
            or not isinstance(right, str)
            or not right
        ):
            raise FoundryError(f"{label} must name left and right bound aliases")
        if aliases is not None and (left not in aliases or right not in aliases):
            raise FoundryError(f"{label} left and right must name bound snapshots")
        left_keys = relationship.get("left_keys")
        right_keys = relationship.get("right_keys")
        if left_keys is None and right_keys is None and "keys" in relationship:
            left_keys = right_keys = relationship.get("keys")
        if (
            not isinstance(left_keys, list)
            or not left_keys
            or not isinstance(right_keys, list)
            or not right_keys
            or len(left_keys) != len(right_keys)
            or any(
                not isinstance(key, str) or not key
                for key in [*left_keys, *right_keys]
            )
        ):
            raise FoundryError(
                f"{label} requires equally sized nonempty string arrays: left_keys and right_keys"
            )
        cardinality = relationship.get("cardinality")
        if cardinality not in RELATIONSHIP_CARDINALITIES:
            raise FoundryError(
                f"{label} cardinality must be one of {', '.join(sorted(RELATIONSHIP_CARDINALITIES))}"
            )
        if cardinality == "many-to-many":
            if relationship.get("allow_many_to_many") is not True:
                raise FoundryError(
                    f"{label} many-to-many requires allow_many_to_many=true"
                )
            rationale = relationship.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise FoundryError(
                    f"{label} many-to-many requires an allocation rationale"
                )
        checked.append(relationship)
    return checked


def _raise_if_expired(expired: threading.Event | None) -> None:
    if expired is not None and expired.is_set():
        raise FoundryError("SQL exceeded its execution time limit")


def relationship_checks(
    datasets: dict[str, dict],
    spec: dict,
    parsed: dict,
    expired: threading.Event | None = None,
) -> list[dict]:
    relationships = spec.get("relationships") or []
    if parsed["has_join"] and len(parsed["tables"]) > 1 and not relationships:
        raise FoundryError(
            "multi-table JOIN requires explicit relationships and cardinality"
        )
    validate_relationship_contract(relationships, set(datasets))
    _validate_join_keys(parsed, relationships, datasets)
    checks = []
    for relationship in relationships:
        left, right = relationship.get("left"), relationship.get("right")
        left_keys = relationship.get("left_keys") or relationship.get("keys")
        right_keys = relationship.get("right_keys") or relationship.get("keys")
        cardinality = relationship.get("cardinality")
        left_types = {c["name"]: c["type"] for c in datasets[left]["schema"]}
        right_types = {c["name"]: c["type"] for c in datasets[right]["schema"]}
        if any(
            left_types.get(a, "").startswith("DECIMAL")
            != right_types.get(b, "").startswith("DECIMAL")
            for a, b in zip(left_keys, right_keys)
        ):
            raise FoundryError(
                "relationship key types differ; normalize keys explicitly before JOIN"
            )
        counters = []
        nulls = []
        for alias, keys in [(left, left_keys), (right, right_keys)]:
            table = datasets[alias]
            if table["kind"] != "table" or any(
                key not in {col["name"] for col in table["schema"]} for key in keys
            ):
                raise FoundryError(f"relationship keys not in {alias}")
            types = {column["name"]: column["type"] for column in table["schema"]}
            values = []
            for index, row in enumerate(table["rows"], start=1):
                if index % 8192 == 0:
                    _raise_if_expired(expired)
                values.append(
                    tuple(
                        Decimal(row[key])
                        if row[key] is not None and types[key].startswith("DECIMAL")
                        else row[key]
                        for key in keys
                    )
                )
            _raise_if_expired(expired)
            nulls.append(sum(any(v is None for v in value) for value in values))
            counters.append(
                Counter(value for value in values if all(v is not None for v in value))
            )
        lc, rc = counters
        lduplicates, rduplicates = (
            sum(v - 1 for v in lc.values()),
            sum(v - 1 for v in rc.values()),
        )
        if cardinality.startswith("one-") and lduplicates:
            raise FoundryError(
                f"duplicate keys on left side of {cardinality} relationship: {left}"
            )
        if cardinality.endswith("-one") and rduplicates:
            raise FoundryError(
                f"duplicate keys on right side of {cardinality} relationship: {right}"
            )
        checks.append(
            {
                "left": left,
                "right": right,
                "cardinality": cardinality,
                "left_keys": left_keys,
                "right_keys": right_keys,
                "left_duplicate_rows": lduplicates,
                "right_duplicate_rows": rduplicates,
                "left_unmatched_rows": sum(v for k, v in lc.items() if k not in rc)
                + nulls[0],
                "right_unmatched_rows": sum(v for k, v in rc.items() if k not in lc)
                + nulls[1],
                "matched_join_rows": sum(v * rc.get(k, 0) for k, v in lc.items()),
                "left_rows": datasets[left]["row_count"],
                "right_rows": datasets[right]["row_count"],
            }
        )
    currencies = {
        str(data.get("metadata", {}).get("currency"))
        for data in datasets.values()
        if data.get("metadata", {}).get("currency")
    }
    units = {
        str(data.get("metadata", {}).get("unit"))
        for data in datasets.values()
        if data.get("metadata", {}).get("unit")
    }
    if (len(currencies) > 1 or len(units) > 1) and not spec.get("conversion_rules"):
        raise FoundryError(
            "mixed currencies or units require explicit conversion_rules"
        )
    return checks


def _value(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (Decimal, float, int)):
        if (
            isinstance(value, float)
            and not math.isfinite(value)
            or isinstance(value, Decimal)
            and not value.is_finite()
        ):
            raise FoundryError(
                "non-finite financial result; define denominator-zero/null handling"
            )
        return format(value, "f") if isinstance(value, Decimal) else str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _value(v) for k, v in value.items()}
    raise FoundryError(f"unsupported result value: {type(value).__name__}")


def _stage_table(connection, alias: str, dataset: dict, expired: threading.Event) -> None:
    fields = dataset["schema"]
    quoted_alias = quote_identifier(alias)
    connection.execute(
        f"CREATE TABLE {quoted_alias} ("
        + ",".join(quote_identifier(f["name"]) + " " + f["type"] for f in fields)
        + ")"
    )
    if not dataset["rows"]:
        return
    columns = "{" + ",".join(
        quote_literal(field["name"]) + ": 'VARCHAR'" for field in fields
    ) + "}"
    projection = ",".join(
        f"{quote_identifier(field['name'])}::{field['type']}" for field in fields
    )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".ndjson", delete=True
    ) as handle:
        for index, row in enumerate(dataset["rows"], start=1):
            if expired.is_set():
                raise FoundryError("SQL exceeded its execution time limit")
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            if index % 8192 == 0:
                handle.flush()
        handle.flush()
        connection.execute(
            f"INSERT INTO {quoted_alias} SELECT {projection} "
            "FROM read_json(?, records=true, columns="
            + columns
            + ")",
            [handle.name],
        )


def execute_sql(datasets: dict[str, dict], spec: dict) -> dict:
    connection = None
    timer = None
    expired = threading.Event()
    try:
        def interrupt():
            expired.set()
            if connection is not None:
                connection.interrupt()

        timer = threading.Timer(spec.get("timeout_seconds", 15), interrupt)
        timer.daemon = True
        timer.start()

        with duckdb.connect(":memory:", config=CONFIG) as validation_connection:
            parsed = validate_sql(validation_connection, spec["sql"], set(datasets))
        if expired.is_set():
            raise FoundryError("SQL exceeded its execution time limit")
        checks = relationship_checks(datasets, spec, parsed, expired)
        if expired.is_set():
            raise FoundryError("SQL exceeded its execution time limit")
        connection = duckdb.connect(":memory:", config=STAGING_CONFIG)
        for alias, dataset in datasets.items():
            if dataset["kind"] != "table":
                continue
            _stage_table(connection, alias, dataset, expired)
            if expired.is_set():
                raise FoundryError("SQL exceeded its execution time limit")
        connection.execute("SET enable_external_access=false")
        connection.execute("SET lock_configuration=true")
        cursor = connection.execute(spec["sql"], spec.get("parameters") or [])
        columns = [{"name": c[0], "type": str(c[1])} for c in cursor.description]
        if len({c["name"] for c in columns}) != len(columns):
            raise FoundryError("duplicate result column names; use explicit aliases")
        max_rows = spec.get("max_rows", 1000)
        values = cursor.fetchmany(max_rows + 1)
        if expired.is_set():
            raise FoundryError("query timed out")
        rows = [
            {c["name"]: _value(v) for c, v in zip(columns, row)}
            for row in values[:max_rows]
        ]
        warnings = []
        if any(c["type"] in {"FLOAT", "DOUBLE"} for c in columns):
            warnings.append(
                "Floating-point output (including DuckDB decimal division): no exact-money claim; display/rounding must follow the analysis metric definition."
            )
        if parsed["volatile"]:
            warnings.append(
                "Non-deterministic SQL functions: " + ", ".join(parsed["volatile"])
            )
        return {
            "result": {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(values) > max_rows,
            },
            "relationship_checks": checks,
            "deterministic": not parsed["volatile"],
            "warnings": warnings,
        }
    except Exception as exc:
        if expired.is_set():
            return {
                "error": "SQL exceeded its execution time limit",
                "error_code": "timeout",
            }
        return {
            "error": str(exc),
            "error_code": "query_refused"
            if isinstance(exc, FoundryError)
            else "sql_error",
        }
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if connection is not None:
            connection.close()


def _formula_defaults(tree: dict) -> dict[int, dict]:
    """Recognize only the documented zero guards and percentage scale literals.

    A hundred in a filter, limit, sum/addend or amount is not a default. No
    string literal or arbitrary financial amount is retained by this policy.
    """
    result = {}

    def numeric(node):
        if node.get("class") != "CONSTANT" or node["value"].get("is_null"):
            return None
        value = node["value"]
        sql_type = value["type"]
        if sql_type["id"] not in {
            "TINYINT",
            "SMALLINT",
            "INTEGER",
            "BIGINT",
            "FLOAT",
            "DOUBLE",
            "DECIMAL",
        }:
            return None
        try:
            number = Decimal(str(value["value"]))
            if sql_type["id"] == "DECIMAL":
                number = number.scaleb(-sql_type["type_info"]["scale"])
            return number
        except (ValueError, ArithmeticError):
            return None

    for parent in _walk(tree):
        candidates = []
        if parent.get("class") == "CASE":
            candidates.append(
                (parent.get("else_expr", {}), Decimal(0), "case_else_zero")
            )
        if parent.get("class") == "FUNCTION":
            name = parent.get("function_name", "").lower()
            children = parent.get("children", [])
            if name == "nullif" and len(children) == 2:
                candidates.append((children[1], Decimal(0), "nullif_zero_guard"))
            if name in {"*", "/"} and len(children) == 2:
                candidates.extend(
                    (child, Decimal(100), "percentage_scale_100") for child in children
                )
        for child, expected, strategy in candidates:
            if numeric(child) == expected:
                result[id(child)] = {
                    "default": str(expected),
                    "default_strategy": strategy,
                }
    return result


def method_template(
    sql: str, parameter_metadata: list[dict] | None = None
) -> tuple[str, list[dict]]:
    """Preserve explicit semantics while stripping task values from reusable SQL.

    AST serialization discards comments. Ordinary literals become parameters
    requiring new values; only the narrowly documented structural constant rules
    or explicitly declared numeric/boolean defaults may carry a reusable value.
    """
    declarations = {
        entry["key"].casefold(): entry for entry in parameter_metadata or []
    }
    with duckdb.connect(":memory:", config=CONFIG) as connection:
        tree = json.loads(
            connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
        )
        if tree.get("error") or len(tree.get("statements", [])) != 1:
            raise FoundryError("only a parsed SELECT analysis can be saved as a method")
        defaults = _formula_defaults(tree)
        contract = []
        existing = {}
        for node in list(_walk(tree)):
            if node.get("class") == "PARAMETER":
                original = node["identifier"]
                lookup = original.casefold()
                if lookup not in existing:
                    identifier = str(len(contract) + 1)
                    existing[lookup] = identifier
                    entry = {
                        "parameter": identifier,
                        "type": "caller_supplied",
                        "source": "parameter",
                        "source_parameter": original,
                        "role": "unclassified",
                    }
                    if lookup in declarations:
                        meta = shared_parameter_metadata(
                            declarations[lookup], identifier
                        )
                        entry.update(metadata=meta, role=meta["role"])
                        if meta["role"] == "formula_constant":
                            entry.update(
                                default=meta["default"],
                                default_strategy="explicit_declaration",
                            )
                    contract.append(entry)
                node["identifier"] = existing[lookup]
            elif node.get("class") == "CONSTANT" and not node["value"].get("is_null"):
                identifier = str(len(contract) + 1)
                sql_type = node["value"]["type"]
                entry = {
                    "parameter": identifier,
                    "type": sql_type["id"],
                    "source": "literal",
                    "source_parameter": None,
                    "role": "unclassified",
                }
                if id(node) in defaults:
                    entry.update(defaults[id(node)], role="formula_constant")
                    entry["metadata"] = {
                        "key": identifier,
                        "label": "公式常数",
                        "type": "decimal"
                        if sql_type["id"] in {"DECIMAL", "FLOAT", "DOUBLE"}
                        else "integer",
                        "role": "formula_constant",
                        "default": entry["default"],
                        "description": "SQL structure: " + entry["default_strategy"],
                    }
                contract.append(entry)
                alias = node.get("alias", "")
                parameter = {
                    "class": "PARAMETER",
                    "type": "VALUE_PARAMETER",
                    "alias": "",
                    "query_location": 18446744073709551615,
                    "identifier": identifier,
                }
                node.clear()
                node.update(
                    {
                        "class": "CAST",
                        "type": "OPERATOR_CAST",
                        "alias": alias,
                        "query_location": 18446744073709551615,
                        "child": parameter,
                        "cast_type": sql_type,
                        "try_cast": False,
                    }
                )
        for statement in tree["statements"]:
            statement["named_param_map"] = [
                {"key": entry["parameter"], "value": int(entry["parameter"])}
                for entry in contract
            ]
        normalized = connection.execute(
            "SELECT json_deserialize_sql(?)", [json.dumps(tree)]
        ).fetchone()[0]
    return normalized, contract
