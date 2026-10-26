"""Bind scenario calculations to immutable, authorized finance snapshots."""

from decimal import Decimal

from foundry.errors import FoundryError
from foundry.finance_scenarios import (
    compute_receivables_aging,
    forecast_cash_13_weeks,
    validate_driver_model,
    validate_aging_buckets,
    _date,
    _decimal,
    _money,
    _hash,
)
from foundry.finance_model import scoped_source_rows
from foundry.finance_driver_templates import (
    BOUNDARY_INPUTS,
    TEMPLATE_ID,
    TEMPLATE_INPUTS,
    OUTPUT_SEMANTICS,
    calculate_linked_management,
    previous_month,
)

_UNIT_FACTORS = {
    "元": Decimal(1),
    "yuan": Decimal(1),
    "万元": Decimal(10000),
    "ten_thousand_yuan": Decimal(10000),
}
_BINDING_FIELDS = {
    "alias",
    "column",
    "selector",
    "aggregation",
    "scope",
    "period",
    "unit",
    "currency",
}
_SCOPE_FIELDS = {"ledger", "organization", "period", "currency", "unit", "scenario"}


def validate_receivables_aging_configuration(inputs):
    validate_aging_buckets(inputs.get("buckets"))
    if "as_of" in inputs:
        _date(inputs["as_of"], "as_of")


def _validate_registered_template_configuration(inputs):
    if inputs.get("template_id") != TEMPLATE_ID:
        raise FoundryError("unsupported registered driver template")
    if any(key in inputs for key in (
        "drivers", "output_mapping", "metric_key", "statement_line", "manager_assumptions", "model_boundary",
    )):
        raise FoundryError("registered template formulas and model boundaries cannot be overridden")


def scenario_configuration_error(service, scenario, context):
    """Read-only intrinsic configuration checks, after source authorization and before model execution.

    Only invalid configuration may bypass the execution-obligation guard, solely
    to persist a failed diagnostic. No amount resolution or formula evaluation
    happens here, and dataset access/integrity errors are never that exception.
    """
    inputs = scenario.get("inputs") or {}
    if scenario.get("kind") == "receivables_aging":
        try:
            validate_receivables_aging_configuration(inputs)
        except FoundryError as exc:
            return exc
        return None
    if (scenario.get("kind") != "driver_model" or inputs.get("template_id") != TEMPLATE_ID
            or not inputs.get("source_bindings")):
        return None
    service._authorize(context["bindings"])
    datasets = {alias: service.analysis.read_dataset(dataset_id) for alias, dataset_id in context["bindings"].items()}
    try:
        _validate_registered_template_configuration(inputs)
        bindings = _driver_source_bindings(inputs)
        all_rows = {
            alias: scoped_source_rows(dataset,
                {key: value for key, value in context.get("scopes", {}).get(alias, {}).items() if key != "unit"},
                context.get("policies", {}).get(alias, {}))
            for alias, dataset in datasets.items()
        }
        for name, binding in bindings.items():
            _driver_binding_rows(name, binding, inputs, context, datasets, all_rows)
    except FoundryError as exc:
        return exc
    return None


def require_runtime_requirements(service, scenario, context, *, requirements_snapshot=None):
    """Require an existing obligation before an assistant runs bound management statements.

    This is an execution-order guard, not an evidence or completion assessment.
    Native manager calculations remain available for inspection and negative controls.
    """
    inputs = scenario.get("inputs") or {}
    if (service.actor == "manager" and not service.session_id) or (
        scenario.get("kind") != "driver_model"
        or inputs.get("template_id") != TEMPLATE_ID
        or not inputs.get("source_bindings")
    ):
        return

    from foundry.finance_requirements import (
        _dimensions_match,
        _requested_grain_matches,
        _requirement_scope_matches,
        latest_requirements,
    )
    from foundry.finance_professional import requirement_rule_identity

    def refuse(reason):
        raise FoundryError(
            f"management statement requirements are not current: {reason}; "
            "先 analysis_requirements_save 登记与当前来源、场景和范围一致的需求，再运行 finance_scenario_run"
        )

    # Never fall back to an older visible requirement when the task's current
    # obligation is outside the runtime's source authorization.
    current = latest_requirements(service.analysis)
    if not current:
        refuse("missing registered requirements")
    try:
        service._authorize_current(current)
    except FoundryError:
        refuse("current requirements are outside this session context")
    if (current.get("context_id") not in (None, context["id"])
            or current.get("bindings") != context.get("bindings")):
        refuse("requirements context or source bindings do not match")

    scope = inputs.get("scope") or {}
    # The shared comparison matcher deliberately ignores a flat scenario label.
    # A single management model has no actual/budget pair: its declared scenario
    # must satisfy that label explicitly, and missing identity proves nothing.
    requested_scenario = (current.get("scope") or {}).get("scenario")
    if requested_scenario is not None and requested_scenario != scope.get("scenario"):
        refuse("requirements scenario does not match the management model")
    run = {"engine": "finance", "bindings": context.get("bindings", {}),
           "finance_scope": context.get("scopes", {}), "result": {"scenario_id": scenario["id"]}}
    # Use the registered template's output semantics, never arbitrary driver
    # labels or computed numbers. One run may cover one of several requested grains.
    for item in current.get("items", []):
        metric = item.get("metric")
        if metric not in OUTPUT_SEMANTICS or (item.get("dimensions") or {}).get("template_id") != TEMPLATE_ID:
            continue
        statement, line, kind = OUTPUT_SEMANTICS[metric]
        row = {"driver": metric, "metric_key": metric, "template_id": TEMPLATE_ID,
               "statement": statement, "statement_line": line, "value_kind": kind,
               "period": inputs.get("period") or scope.get("period"),
               **{key: scope.get(key) for key in ("organization", "currency", "unit", "scenario")}}
        if (_dimensions_match(item, row, run) and _requested_grain_matches(item, run, row)
                and _requirement_scope_matches(run, row, item, current)):
            break
    else:
        refuse("no registered template output matches the requested scenario and scope")
    # Professional identity reconstruction verifies model boundaries and may
    # evaluate their source-backed scenario. Establish the obligation's identity
    # and scope first, so no unmatched request enters even that calculator path.
    fingerprint = service.analysis.fingerprint_in_view(current, service.allowed)
    if not fingerprint:
        refuse("requirements semantic fingerprint is invalid")
    identity = requirement_rule_identity(service.analysis, current, allowed=service.allowed)
    if identity != (current.get("semantic_basis") or {}).get("professional_identity"):
        refuse("requirements professional rule identity has changed")
    if requirements_snapshot is not None and (
        requirements_snapshot.get("requirements_id") != current["id"]
        or requirements_snapshot.get("requirements_semantic_fingerprint") != fingerprint
    ):
        refuse("requirements changed after execution capture")
    return {"requirements_id": current["id"], "requirements_semantic_fingerprint": fingerprint,
            **({"requirements_rule_identity": identity} if identity else {})}


def _unique_refs(refs):
    return list({_hash(ref): ref for ref in refs}.values())


def _scalar(value):
    return isinstance(value, (str, int, float, bool)) and value != ""


def _units_equal(left, right):
    return left == right or (
        left in _UNIT_FACTORS
        and right in _UNIT_FACTORS
        and _UNIT_FACTORS[left] == _UNIT_FACTORS[right]
    )


def _driver_source_bindings(inputs):
    bindings = inputs.get("source_bindings") or {}
    if not isinstance(bindings, dict):
        raise FoundryError("driver source_bindings must be an object")
    return bindings


def _driver_binding_rows(name, binding, inputs, context, datasets, all_rows):
    """Validate an authorized source reference without reading or calculating its amount."""
    if (
        not isinstance(name, str)
        or not isinstance(binding, dict)
        or set(binding) - _BINDING_FIELDS
    ):
        raise FoundryError("driver source binding contains unsupported fields")
    alias, column = binding.get("alias"), binding.get("column")
    if (
        not isinstance(alias, str)
        or alias not in context.get("bindings", {})
        or alias not in datasets
    ):
        raise FoundryError("driver source binding alias is not authorized")
    dataset = datasets[alias]
    dataset_id = dataset.get("id") or dataset.get("dataset_id")
    if dataset_id != context["bindings"][alias]:
        raise FoundryError("driver source binding dataset does not match context")
    columns = {key for row in dataset.get("rows", []) for key in row}
    if not isinstance(column, str) or column not in columns:
        raise FoundryError("driver source binding column does not exist")
    selector = binding.get("selector")
    if (
        not isinstance(selector, dict)
        or not selector
        or any(
            key not in columns or not _scalar(value)
            for key, value in selector.items()
        )
    ):
        raise FoundryError(
            "driver selector requires real columns and scalar equalities"
        )
    for value in selector.values():
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            _decimal(value, "selector")
    aggregation = binding.get("aggregation")
    if aggregation not in {"single", "sum"}:
        raise FoundryError(
            "driver source binding aggregation must be single or sum"
        )
    scope = binding.get("scope") or {}
    if (
        not isinstance(scope, dict)
        or set(scope) - _SCOPE_FIELDS
        or any(not _scalar(value) for value in scope.values())
    ):
        raise FoundryError(
            "driver source binding scope must contain scalar identity fields"
        )
    for key in ("period", "unit", "currency"):
        if not isinstance(binding.get(key), str) or not binding[key]:
            raise FoundryError(f"driver source binding requires {key}")
        if key in scope and scope[key] != binding[key]:
            raise FoundryError("driver binding identity fields conflict")
    defaults = context.get("scopes", {}).get(alias, {})
    expected = {
        **scope,
        **{key: binding[key] for key in ("period", "unit", "currency")},
    }
    source_scope = inputs.get("scope") or {}
    for key in ("organization", "ledger", "scenario", "currency", "unit"):
        declared = source_scope.get(key)
        if declared is not None:
            if not isinstance(declared, str) or not declared:
                raise FoundryError("driver scope requires scalar identities")
            if key in expected and not (
                _units_equal(expected[key], declared)
                if key == "unit"
                else expected[key] == declared
            ):
                raise FoundryError("driver binding conflicts with model scope")
            expected[key] = declared
    if (
        not isinstance(expected.get("organization"), str)
        or not expected["organization"]
    ):
        organization = defaults.get("organization")
        if not isinstance(organization, str) or not organization:
            raise FoundryError("driver binding requires one organization")
        expected["organization"] = organization
    # Canonical mappings serve scope filtering, not selection or value
    # retrieval from an explicitly named physical column. They can overwrite
    # a raw column with the same name; always dereference the original row.
    rows = []
    for row in all_rows[alias]:
        raw = dataset["rows"][row["source"]["row_index"] - 1]
        if all(
            type(raw.get(key)) is type(value) and raw.get(key) == value
            for key, value in selector.items()
        ):
            rows.append((row, raw))
    if not rows or (aggregation == "single" and len(rows) != 1):
        raise FoundryError(
            "driver binding requires matching rows and exactly one row for single"
        )
    return rows, column, defaults, expected


def _resolve_driver_bindings(inputs, context, datasets, all_rows):
    bindings = _driver_source_bindings(inputs)
    values, proofs = {}, {}
    for name, binding in bindings.items():
        rows, column, defaults, expected = _driver_binding_rows(name, binding, inputs, context, datasets, all_rows)
        total = Decimal(0)
        refs, source_units, multipliers = [], set(), set()
        for key in ("ledger", "scenario"):
            identities = {row.get(key) or defaults.get(key) for row, _ in rows}
            if len(identities) != 1:
                raise FoundryError(f"driver binding mixes source {key} identities")
            identity = next(iter(identities))
            if identity not in (None, ""):
                if not _scalar(identity):
                    raise FoundryError(f"driver binding requires one source {key}")
                if key in expected and identity != expected[key]:
                    raise FoundryError(
                        f"driver binding source {key} does not match declared identity"
                    )
                expected[key] = identity
        for row, raw in rows:
            for key, required in expected.items():
                if key == "unit":
                    continue
                actual = row.get(key)
                if actual in (None, "") and _scalar(defaults.get(key)):
                    actual = defaults[key]
                if actual != required:
                    raise FoundryError(
                        f"driver binding source {key} does not match declared identity"
                    )
            source_unit = row.get("unit") or defaults.get("unit")
            target_unit = expected["unit"]
            if not isinstance(source_unit, str) or not source_unit:
                raise FoundryError(
                    "driver binding cannot label a source with an unsupported unit"
                )
            if source_unit == target_unit:
                multiplier = Decimal(1)
            elif source_unit in _UNIT_FACTORS and target_unit in _UNIT_FACTORS:
                multiplier = _UNIT_FACTORS[source_unit] / _UNIT_FACTORS[target_unit]
            else:
                raise FoundryError("driver binding unit conversion is unsupported")
            if defaults.get("unit") and not _units_equal(defaults["unit"], target_unit):
                raise FoundryError("driver binding target unit conflicts with context")
            amount = _decimal(raw.get(column), f"source binding {name}")
            total += amount * multiplier
            refs.append(
                {
                    **row["source"],
                    "column": column,
                    "original_unit": source_unit,
                    "unit": target_unit,
                    "unit_multiplier": _money(multiplier),
                }
            )
            source_units.add(source_unit)
            multipliers.add(_money(multiplier))
        values[name] = _money(total)
        proofs[name] = {
            "status": "source_verified",
            "value": values[name],
            **expected,
            "source_rows": _unique_refs(refs),
            "source_units": sorted(source_units),
            "unit_multipliers": sorted(multipliers),
        }
    return values, proofs


def _calculate_driver(inputs, context, datasets, all_rows, verified_assumptions):
    bound_values, proofs = _resolve_driver_bindings(inputs, context, datasets, all_rows)
    supplied = inputs.get("values") or {}
    if not isinstance(supplied, dict):
        raise FoundryError("driver values must be an object")
    if set(bound_values) & set(supplied):
        raise FoundryError("driver values cannot override source bindings")
    template = inputs.get("template_id")
    if template:
        _validate_registered_template_configuration(inputs)
        if set(bound_values) - set(TEMPLATE_INPUTS) - set(BOUNDARY_INPUTS) or set(
            supplied
        ) - set(TEMPLATE_INPUTS):
            raise FoundryError("registered template contains unknown inputs")
        if not set(BOUNDARY_INPUTS) <= set(bound_values):
            raise FoundryError(
                "registered template requires all eight boundary source bindings"
            )
        if any(_decimal(bound_values[name], name) != 0 for name in BOUNDARY_INPUTS):
            raise FoundryError(
                "registered template does not support nonzero boundary effects"
            )
        period = inputs.get("period") or (inputs.get("scope") or {}).get("period")
        prior = previous_month(period)
        scope = inputs.get("scope") or {}
        if any(
            not isinstance(scope.get(key), str) or not scope[key]
            for key in ("organization", "currency", "unit")
        ):
            raise FoundryError(
                "registered template requires organization, currency and unit scope"
            )
        for name, proof in proofs.items():
            expected_period = prior if name.startswith("opening_") else period
            if proof["period"] != expected_period:
                raise FoundryError(
                    "registered template source period does not match opening or current period"
                )
        if any(
            len({proof.get(key) for proof in proofs.values()}) > 1
            for key in ("ledger", "scenario")
        ):
            raise FoundryError(
                "registered template source ledger or scenario identity is inconsistent"
            )
        values = {
            **supplied,
            **{
                key: value
                for key, value in bound_values.items()
                if key in TEMPLATE_INPUTS
            },
        }
        evaluated = calculate_linked_management(values)
    else:
        drivers = inputs.get("drivers", [])
        declared = {driver.get("name"): driver for driver in drivers}
        if set(bound_values) - set(declared):
            raise FoundryError("source binding names must be declared drivers")
        if any("formula" in declared[name] for name in bound_values):
            raise FoundryError("source bindings cannot override a formula driver")
        evaluated = validate_driver_model(
            drivers,
            inputs={**supplied, **bound_values},
            manager_assumptions=inputs.get("manager_assumptions"),
        )
    states = {}
    for row in evaluated["rows"]:
        name = row["driver"]
        dependencies = row["depends_on"]
        if dependencies:
            source_ids = sorted(
                {
                    item
                    for dep in dependencies
                    for item in states[dep]["source_binding_ids"]
                }
            )
            assumption_ids = sorted(
                {item for dep in dependencies for item in states[dep]["assumption_ids"]}
            )
            unverified = sorted(
                {
                    item
                    for dep in dependencies
                    for item in states[dep]["unverified_inputs"]
                }
            )
        else:
            source_ids = [name] if name in proofs else []
            trusted = (verified_assumptions or {}).get(name, {})
            confirmed = (
                trusted.get("status") == "confirmed"
                and trusted.get("confirmation_id")
                and _decimal(trusted.get("value"), name) == _decimal(row["value"], name)
            )
            assumption_ids = [trusted["confirmation_id"]] if confirmed else []
            unverified = [] if source_ids or confirmed else [name]
        if template and name in OUTPUT_SEMANTICS:
            source_ids = sorted(set(source_ids) | set(BOUNDARY_INPUTS))
        if not template and dependencies:
            # Generic formulas have no registered dimensional/period semantics.
            # Preserve the arithmetic but do not qualify a mixed-identity amount.
            identities = {
                (
                    proofs[key].get("organization"),
                    proofs[key].get("currency"),
                    _UNIT_FACTORS.get(proofs[key].get("unit"), proofs[key].get("unit")),
                    proofs[key].get("period"),
                    proofs[key].get("ledger"),
                    proofs[key].get("scenario"),
                )
                for key in source_ids
            }
            if len(identities) > 1:
                unverified = sorted(set(unverified) | {f"{name}:mixed_source_identity"})
        refs = _unique_refs(
            [ref for key in source_ids for ref in proofs[key]["source_rows"]]
        )
        status = (
            "unverified"
            if unverified
            else "confirmed_assumption"
            if assumption_ids
            else "source_verified"
            if refs
            else "legacy"
        )
        state = {
            "status": status,
            "source_binding_ids": source_ids,
            "assumption_ids": assumption_ids,
            "unverified_inputs": unverified,
            "source_rows": refs,
        }
        states[name] = state
        row.update(state)
        if template:
            row.update(
                period=period,
                **{key: scope[key] for key in ("organization", "currency", "unit")},
            )
            if "scenario" in scope:
                row["scenario"] = scope["scenario"]
    result = {
        "columns": evaluated["columns"],
        "rows": evaluated["rows"],
        "assumptions": evaluated.get("assumptions", []),
        "driver_model": evaluated,
        "source_binding_status": {
            "resolver": "finance.source_bindings.v1",
            "bindings": proofs,
            "drivers": states,
            "all_sources_verified": bool(states)
            and all(state["status"] == "source_verified" for state in states.values()),
        },
    }
    if template:
        refs = _unique_refs(
            [ref for proof in proofs.values() for ref in proof["source_rows"]]
        )
        for check in evaluated["model_checks"]:
            check["source_rows"] = refs
        check_status = (
            "fail"
            if any(
                check["status"] == "fail" and check["blocks_evidence"]
                for check in evaluated["model_checks"]
            )
            else "pass"
        )
        for row in result["rows"]:
            row["check_status"] = check_status
        result.update(
            template_id=template,
            template_version=1,
            model_checks=evaluated["model_checks"],
            model_scope=evaluated["model_scope"],
            supported_scope=evaluated["supported_scope"],
            model_boundary=[
                {
                    "name": name.removeprefix("boundary."),
                    "value": bound_values[name],
                    "nature": "declared_model_boundary",
                    "source_binding_id": name,
                    "source_rows": proofs[name]["source_rows"],
                }
                for name in BOUNDARY_INPUTS
            ],
        )
    return result


def calculate_scenario(scenario, context, datasets, *, verified_assumptions=None):
    inputs = scenario["inputs"]
    scope = inputs.get("scope", {})
    all_rows = {}
    for alias, dataset in datasets.items():
        if scenario["kind"] == "transaction_review":
            # Its resolver binds typed transaction/policy scalars directly;
            # money normalization must not scale months, dates or booleans.
            continue
        defaults = context.get("scopes", {}).get(alias, {})
        if scenario["kind"] == "driver_model":
            # Binding resolution performs and records explicit unit conversion.
            defaults = {key: value for key, value in defaults.items() if key != "unit"}
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
            resolve_entities(inputs, cells, units, context.get("scopes", {})),
            resolve_params(inputs.get("params")),
        )
    elif kind == "driver_model":
        result = _calculate_driver(
            inputs, context, datasets, all_rows, verified_assumptions
        )
    elif kind == "transaction_review":
        from foundry.finance_transaction_checks import review_transaction

        result = review_transaction(inputs, context, datasets)
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
