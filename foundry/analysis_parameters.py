"""Explicit business metadata for real SQL parameters, with safe method reuse.

Labels describe caller-declared meanings. Nothing in this module derives a
business name, currency or assumption from column names or actual data values.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import duckdb

from foundry.analysis_data import json_value
from foundry.errors import FoundryError

TYPES = {"string", "decimal", "integer", "boolean", "date"}
ROLES = {"business", "formula_constant"}
FIELDS = {
    "key",
    "position",
    "label",
    "type",
    "unit",
    "description",
    "role",
    "constraints",
    "default",
}
CONSTRAINTS = {"min", "max", "choices", "nullable"}


def _text(value: Any, field: str, maximum: int, *, required=False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or required
        and not value.strip()
    ):
        raise FoundryError(
            f"parameter {field} must be {'nonempty ' if required else ''}text of at most {maximum} characters"
        )
    return value


def _typed(value: Any, kind: str, nullable: bool, label: str) -> Any:
    if value is None:
        if nullable:
            return None
        raise FoundryError(f"parameter {label} cannot be null")
    if kind == "string":
        if not isinstance(value, str):
            raise FoundryError(f"parameter {label} must be a string")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise FoundryError(f"parameter {label} must be a boolean")
        return value
    if kind == "date":
        try:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError("date format")
            return date.fromisoformat(value)
        except ValueError as exc:
            raise FoundryError(
                f"parameter {label} must be an ISO YYYY-MM-DD date"
            ) from exc
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
            raise InvalidOperation
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or kind == "integer"
            and number != number.to_integral_value()
        ):
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"parameter {label} must be a finite {kind}") from exc


def _constraints(raw: Any, kind: str) -> dict:
    if not isinstance(raw, dict) or set(raw) - CONSTRAINTS:
        raise FoundryError("parameter constraints have unsupported fields")
    out = deepcopy(raw)
    if "nullable" in out and not isinstance(out["nullable"], bool):
        raise FoundryError("parameter nullable constraint must be boolean")
    nullable = out.get("nullable", False)
    if ("min" in out or "max" in out) and kind not in {"decimal", "integer", "date"}:
        raise FoundryError("parameter min/max constraints require numeric or date type")
    bounds = {
        key: _typed(out[key], kind, False, key) for key in ("min", "max") if key in out
    }
    if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
        raise FoundryError("parameter min constraint exceeds max")
    if "choices" in out:
        if not isinstance(out["choices"], list) or not 1 <= len(out["choices"]) <= 100:
            raise FoundryError("parameter choices must contain 1–100 scalar values")
        values = [_typed(value, kind, nullable, "choice") for value in out["choices"]]
        if len(set(values)) != len(values):
            raise FoundryError("parameter choices must be unique")
    return json_value(out)


def _validate_value(value: Any, meta: dict, *, default=False) -> Any:
    constraints = meta.get("constraints", {})
    typed = _typed(value, meta["type"], constraints.get("nullable", False), meta["key"])
    if typed is None:
        return typed
    for name in ("min", "max"):
        if name in constraints:
            bound = _typed(constraints[name], meta["type"], False, name)
            if name == "min" and typed < bound or name == "max" and typed > bound:
                raise FoundryError(
                    f"parameter {meta['key']} violates {name} constraint"
                )
    if "choices" in constraints:
        choices = [
            _typed(choice, meta["type"], constraints.get("nullable", False), "choice")
            for choice in constraints["choices"]
        ]
        if typed not in choices:
            raise FoundryError(
                f"parameter {meta['key']} is outside the declared choices"
            )
    if meta["role"] == "formula_constant" and not default:
        declared = _validate_value(meta["default"], meta, default=True)
        if typed != declared:
            raise FoundryError(
                f"parameter {meta['key']} differs from its explicit formula default; revise the declaration to change the formula"
            )
    return typed


def normalize_parameter_metadata(
    sql: str, parameters: list | dict, metadata: Any
) -> list[dict]:
    if metadata is None:
        return []
    if not isinstance(metadata, list) or len(metadata) > 128:
        raise FoundryError(
            "parameter_metadata must be an array of at most 128 declarations"
        )
    if not metadata:
        return []
    try:
        with duckdb.connect(
            ":memory:",
            config={
                "enable_external_access": False,
                "autoload_known_extensions": False,
                "autoinstall_known_extensions": False,
            },
        ) as connection:
            statements = connection.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise FoundryError(
                "parameter metadata requires one parsed SELECT statement"
            )
        identifiers = set(statements[0].named_parameters)
    except duckdb.Error as exc:
        raise FoundryError(f"cannot bind parameter metadata to SQL: {exc}") from exc
    canonical = {key.casefold(): key for key in identifiers}
    if len(canonical) != len(identifiers):
        raise FoundryError("parameter identifiers differ only by case")
    if isinstance(parameters, dict):
        if any(not isinstance(key, str) for key in parameters):
            raise FoundryError("parameter dictionary keys must be strings")
        supplied = {key.casefold(): value for key, value in parameters.items()}
        if len(supplied) != len(parameters):
            raise FoundryError("duplicate parameter dictionary keys")
    else:
        supplied = {
            str(position): value for position, value in enumerate(parameters, start=1)
        }
    output = []
    seen = set()
    for raw in metadata:
        if not isinstance(raw, dict) or set(raw) - FIELDS:
            raise FoundryError("parameter metadata has unsupported fields")
        if ("key" in raw) == ("position" in raw):
            raise FoundryError(
                "parameter metadata must specify exactly one key or position"
            )
        if "position" in raw:
            position = raw["position"]
            if (
                isinstance(position, bool)
                or not isinstance(position, int)
                or position < 1
                or not isinstance(parameters, list)
            ):
                raise FoundryError(
                    "parameter position must be a one-based positional parameter"
                )
            selected = str(position)
        else:
            selected = _text(raw["key"], "key", 200, required=True)
        key = canonical.get(selected.casefold())
        if key is None:
            raise FoundryError(
                f"parameter metadata does not bind an actual SQL parameter: {selected}"
            )
        if key.casefold() in seen:
            raise FoundryError(f"duplicate parameter metadata: {key}")
        if key.casefold() not in supplied:
            raise FoundryError(f"parameter metadata has no supplied value: {key}")
        seen.add(key.casefold())
        kind = raw.get("type")
        role = raw.get("role", "business")
        if kind not in TYPES or role not in ROLES:
            raise FoundryError("parameter metadata has an unsupported type or role")
        result = {
            "key": key,
            "label": _text(raw.get("label"), "label", 200, required=True),
            "type": kind,
            "role": role,
        }
        for name, maximum in [("unit", 100), ("description", 2000)]:
            if name in raw:
                result[name] = _text(raw[name], name, maximum)
        if "constraints" in raw:
            result["constraints"] = _constraints(raw["constraints"], kind)
        if role == "formula_constant" and (
            "default" not in raw
            or kind not in {"decimal", "integer", "boolean"}
            or raw["default"] is None
        ):
            raise FoundryError(
                "parameter formula_constant requires an explicit numeric/boolean default"
            )
        if "default" in raw:
            result["default"] = json_value(raw["default"])
            _validate_value(result["default"], result, default=True)
        _validate_value(supplied[key.casefold()], result)
        output.append(result)
    return output


def shared_parameter_metadata(meta: dict, parameter: str) -> dict:
    """Share declared semantics without carrying a task's business value domain.

    Choice lists may contain customer names or private project IDs. Reusable
    methods retain numeric/date bounds and nullability, but not business choices
    or business defaults. New task values still come from explicit parameters.
    """
    result = deepcopy(meta)
    result["key"] = parameter
    if result["role"] == "business":
        result.pop("default", None)
    if "constraints" in result:
        # A domain may contain private identifiers even when the selected value
        # is a reusable formula constant. Only that declared default travels.
        result["constraints"].pop("choices", None)
        if not result["constraints"]:
            result.pop("constraints")
    return result


def method_parameters(method: dict, supplied: Any) -> Any:
    """Apply only declared constant defaults; every other value is fresh input."""
    if method.get("parameter_policy_version") != 1:
        return supplied if supplied is not None else []
    contract = method.get("parameter_contract", [])
    if supplied is None:
        values = {}
    elif isinstance(supplied, dict):
        if any(not isinstance(key, str) for key in supplied):
            raise FoundryError("method parameter keys must be strings")
        values = dict(supplied)
    elif isinstance(supplied, list):
        values = {
            str(position): value for position, value in enumerate(supplied, start=1)
        }
    else:
        raise FoundryError("method parameters must be an array or object")
    allowed = {entry["parameter"] for entry in contract}
    if set(values) - allowed:
        raise FoundryError("method parameters include an unknown parameter key")
    for entry in contract:
        key = entry["parameter"]
        if key not in values:
            if entry.get("role") == "formula_constant" and "default" in entry:
                values[key] = deepcopy(entry["default"])
            else:
                raise FoundryError(f"method parameter {key} requires a new value")
        elif entry.get("role") == "formula_constant" and "default" in entry:
            default = entry["default"]
            same = values[key] == default
            if not isinstance(default, bool) and isinstance(
                default, (int, float, str, Decimal)
            ):
                try:
                    same = not isinstance(values[key], bool) and Decimal(
                        str(values[key])
                    ) == Decimal(str(default))
                except (InvalidOperation, ValueError):
                    same = False
            if not same:
                raise FoundryError(
                    f"method parameter {key} differs from its formula default; create a revised analysis to change it"
                )
    return values
