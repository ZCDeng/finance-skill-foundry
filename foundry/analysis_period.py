"""Explicit current-month inputs. Only declared parameter/filter slots are rebound."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

import duckdb

from foundry import duckdb_offline
from foundry.errors import FoundryError

MONTH_FORMS = (
    (re.compile(r"^(\d{4})-(\d{1,2})$"), "{y}-{m:02d}"),
    (re.compile(r"^(\d{4})(\d{2})$"), "{y}{m:02d}"),
    (re.compile(r"^(\d{4})/(\d{1,2})$"), "{y}/{m:02d}"),
    (re.compile(r"^(\d{4})\.(\d{1,2})$"), "{y}.{m:02d}"),
    (re.compile(r"^(\d{4})年(\d{1,2})月$"), "{y}年{m}月"),
)


def month_of(text: Any) -> str | None:
    if isinstance(text, str):
        for pattern, _ in MONTH_FORMS:
            found = pattern.fullmatch(text.strip())
            if found and 1 <= int(found.group(2)) <= 12:
                return f"{int(found.group(1)):04d}-{int(found.group(2)):02d}"
    return None


def normalize_period_binding(value, *, engine, sql="", parameters=None, aggregate_plan=None) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("mode") != "current":
        raise FoundryError("period_binding must declare mode=current")
    field = "parameters" if engine == "sql" else "filter_fields" if engine == "structured_aggregate" else None
    if set(value) - {"mode", *([field] if field else [])}:
        raise FoundryError("period_binding has unsupported fields for this engine")
    if field is None:
        return {"mode": "current"}
    targets = value.get(field)
    if not isinstance(targets, list) or not 1 <= len(targets) <= 128:
        raise FoundryError(f"period_binding {field} needs 1–128 explicit targets")
    normalized = []
    if engine == "sql":
        try:
            with duckdb_offline.connect(":memory:") as connection:
                connection.execute("SET enable_external_access = false")
                statements = connection.extract_statements(sql)
            if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                raise FoundryError("period binding requires one SELECT")
            identifiers = {key.casefold(): key for key in statements[0].named_parameters}
        except duckdb.Error as exc:
            raise FoundryError(f"cannot bind period parameter: {exc}") from exc
        for target in targets:
            if isinstance(parameters, dict):
                if not isinstance(target, str):
                    raise FoundryError("period parameter must name a SQL parameter")
                canonical = identifiers.get(target.casefold())
                supplied = {key.casefold() for key in parameters if isinstance(key, str)}
                if canonical is None or canonical.casefold() not in supplied:
                    raise FoundryError("period parameter must bind an actual supplied SQL parameter")
                normalized.append(canonical)
            else:
                if (isinstance(target, bool) or not isinstance(target, int) or target < 1
                        or target > len(parameters or []) or str(target) not in identifiers):
                    raise FoundryError("period parameter position must bind an actual one-based SQL parameter")
                normalized.append(target)
    else:
        filters = (aggregate_plan or {}).get("filters", [])
        for target in targets:
            matches = [entry for entry in filters if entry.get("field") == target]
            if (not isinstance(target, str) or len(matches) != 1 or matches[0].get("op") != "eq"
                    or "value" not in matches[0]):
                raise FoundryError("period filter must bind exactly one existing eq filter field")
            normalized.append(target)
    if len({str(target).casefold() for target in normalized}) != len(normalized):
        raise FoundryError("duplicate period binding target")
    return {"mode": "current", field: normalized}


def dataset_months(dataset: dict) -> set[str]:
    """Read declared rows and confirmed hints; mixed periods remain visible to callers."""
    from foundry.finance_model import _field_map
    from foundry.finance_readiness import _declared_values, _snapshot_period

    months = {month_of(value) for value in _declared_values(dataset.get("rows") or [], _field_map({}), "period")}
    months.update({month_of(_snapshot_period(dataset)), month_of((dataset.get("metadata") or {}).get("period"))})
    return months - {None}


def resolve_period(analysis, datasets: dict, scope: dict, *, allowed=None, frozen: dict | None = None) -> dict:
    """Freeze the confirmed task/scope month and verify every declared source month."""
    from foundry.finance_requirements import latest_requirements

    declared = {month for dataset in datasets.values() for month in dataset_months(dataset)}
    if len(declared) > 1:
        raise FoundryError("资料包含多个期间，不能绑定单月本期参数")
    if frozen is not None:
        target = month_of(frozen.get("period"))
        if not target or declared and declared != {target}:
            raise FoundryError("冻结期间与资料期间不一致")
        return deepcopy(frozen)
    requirements = latest_requirements(analysis, allowed)
    candidates = [
        ("requirements", ((requirements or {}).get("scope") or {}).get("period")),
        ("task", analysis.task.meta().get("period")),
        ("scope", (scope or {}).get("period")),
    ]
    target, source = None, None
    for origin, value in candidates:
        if value:
            current = month_of(value)
            if current is None:
                raise FoundryError(f"period binding requires a single current month; {origin} declares {value}")
            if target is None:
                target, source = current, origin
            elif origin == "scope" and current != target:
                raise FoundryError(f"期间声明 {current} 与目标期间 {target} 不一致")
    if target is None and declared:
        target, source = next(iter(declared)), "datasets"
    if target is None:
        raise FoundryError("缺少可核验的目标期间，不能绑定本期参数")
    if declared and declared != {target}:
        raise FoundryError(f"资料期间 {next(iter(declared))} 与目标期间 {target} 不一致")
    return {"period": target, "source": source}


def bind_period(revision: dict, resolved: dict) -> dict:
    """Return an execution copy, preserving the saved definition and all undeclared slots."""
    binding = revision.get("period_binding")
    if not binding:
        return revision
    result = deepcopy(revision)
    period = resolved["period"]
    result["resolved_period"] = deepcopy(resolved)
    result["scope"] = {**result.get("scope", {}), "period": period}
    if "parameters" in binding:
        parameters = result["parameters"]
        for key in binding["parameters"]:
            if isinstance(parameters, dict):
                actual = next(name for name in parameters if name.casefold() == key.casefold())
                parameters[actual] = period
            else:
                parameters[key - 1] = period
    if "filter_fields" in binding:
        for condition in result["aggregate_plan"]["filters"]:
            if condition["field"] in binding["filter_fields"]:
                condition["value"] = period
    return result
