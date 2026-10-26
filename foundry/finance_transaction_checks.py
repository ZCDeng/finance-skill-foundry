"""Source-bound checks for a closed set of transaction recognition policies.

The service must load datasets through AnalysisStore.read_dataset, which verifies
the archived bytes and data hashes. This pure module does not certify accounting
policy, approve a manager decision, or post a journal. Proposed entries are the
artifact being checked; they are never accepted as original transaction facts.
"""

from datetime import date
from decimal import Decimal, localcontext
import re

from foundry.errors import FoundryError
from foundry.finance_model import scoped_source_rows
from foundry.finance_scenarios import _decimal, _hash, _money


RULE_VERSION = "transaction_recognition_v1"
POLICIES = {
    "uniform_service_advance": "uniform_monthly_service_v1",
    "ordinary_service_consumed": "expense_consumed_service_v1",
    "capitalizable_acquisition": "capitalize_qualifying_acquisition_v1",
    "old_ar_collection": "settle_existing_receivable_v1",
    "new_earned_cash_sale": "recognize_fulfilled_cash_sale_v1",
    "restricted_cash_release": "release_effective_restriction_v1",
}
BASE_FIELDS = {"transaction_id", "transaction_type", "recognition_date"}
POLICY_FIELDS = {
    "policy_id", "policy_reference", "policy_effective_from",
    "policy_effective_to", "policy_transaction_type",
}
RELEASE_FIELDS = {
    "release_id", "release_reference", "release_restriction_id", "release_amount",
    "release_effective_date", "release_status",
}
FACT_FIELDS = {
    "uniform_service_advance": {
        "cash_received", "service_months", "earned_months",
        "performance_pattern", "fulfilment_basis",
    },
    "ordinary_service_consumed": {
        "amount", "service_consumed_in_period", "future_economic_benefit",
    },
    "capitalizable_acquisition": {
        "amount", "future_economic_benefit", "asset_controlled",
        "reliable_measurement", "useful_life_months",
    },
    "old_ar_collection": {"amount", "opening_receivable", "receivable_origin_period"},
    "new_earned_cash_sale": {
        "amount", "performance_obligation_satisfied", "associated_expense", "tax_expense",
    },
    "restricted_cash_release": {
        "cash_balance", "restricted_cash", "restriction_id", "as_of_date", "obligations_due",
        *RELEASE_FIELDS,
    },
}
_BINDING_FIELDS = {
    "alias", "column", "selector", "aggregation", "scope", "period", "unit", "currency",
}
_IDENTITY_FIELDS = {"organization", "period", "currency", "unit", "ledger", "scenario"}


def _require(condition, message):
    if not condition:
        raise FoundryError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _period(value):
    _require(_text(value) and re.fullmatch(r"\d{4}-\d{2}", value), "period must be YYYY-MM")
    try:
        date.fromisoformat(value + "-01")
    except ValueError:
        raise FoundryError("period must be YYYY-MM") from None
    return value


def _date(value, name):
    _require(_text(value), f"{name} requires an ISO date source")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise FoundryError(f"{name} requires an ISO date source") from None
    _require(result.isoformat() == value, f"{name} requires an ISO date source")
    return result


def _resolve(bindings, context, datasets, scope):
    """Resolve typed scalars from physical cells, never canonical numeric aliases."""
    values, refs, records, identities = {}, {}, {}, set()
    for name, binding in bindings.items():
        _require(isinstance(name, str) and isinstance(binding, dict), "invalid source binding")
        _require(not set(binding) - _BINDING_FIELDS, f"{name}: unsupported binding fields")
        alias = binding.get("alias")
        _require(isinstance(alias, str) and alias in context.get("bindings", {}) and alias in datasets,
                 f"{name}: source alias is not authorized")
        dataset = datasets[alias]
        dataset_id = dataset.get("id") or dataset.get("dataset_id")
        _require(dataset_id == context["bindings"][alias], f"{name}: dataset does not match context")
        for hash_name in ("source_hash", "data_hash"):
            digest = dataset.get(hash_name)
            _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
                     f"{name}: verified dataset {hash_name} is required")
        _require(binding.get("aggregation") == "single", f"{name}: only a single original observation is supported")
        selector, column = binding.get("selector"), binding.get("column")
        _require(isinstance(selector, dict) and bool(selector) and _text(column),
                 f"{name}: explicit physical column and selector required")
        _require(all(isinstance(key, str) and isinstance(value, (str, int, float, bool))
                     and value != "" for key, value in selector.items()),
                 f"{name}: selector requires scalar equalities")
        declared = binding.get("scope", {})
        _require(isinstance(declared, dict) and not set(declared) - _IDENTITY_FIELDS,
                 f"{name}: unsupported binding scope")
        for key, value in declared.items():
            _require(key in scope and value == scope[key], f"{name}: binding scope conflicts with review")
        for key in ("period", "currency", "unit"):
            _require(binding.get(key) == scope[key], f"{name}: binding {key} conflicts with review")
        # Scope defaults are declarations in the saved context. Binding labels
        # alone cannot manufacture organization, currency, or source units.
        defaults = context.get("scopes", {}).get(alias, {})
        selected = []
        for canonical in scoped_source_rows(dataset, defaults, context.get("policies", {}).get(alias, {})):
            source = canonical["source"]
            raw = dataset["rows"][source["row_index"] - 1]
            if all(key in raw and type(raw[key]) is type(value) and raw[key] == value
                   for key, value in selector.items()):
                selected.append((canonical, raw))
        _require(len(selected) == 1, f"{name}: selector must match exactly one active original row")
        canonical, raw = selected[0]
        _require(column in raw and raw[column] is not None and raw[column] != "",
                 f"{name}: original source cell is missing")
        value = raw[column]
        _require(isinstance(value, (str, int, float, bool)), f"{name}: source must be a scalar")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _decimal(value, name)
        identity = {}
        for key in _IDENTITY_FIELDS:
            actual = canonical.get(key)
            if actual in (None, ""):
                actual = defaults.get(key)
            if key in scope:
                _require(actual == scope[key], f"{name}: source {key} does not match review")
            if actual not in (None, ""):
                _require(_text(actual), f"{name}: source {key} must be a scalar identity")
            identity[key] = actual or None
        # Even omitted optional scope fields cannot silently mix books/scenarios.
        identities.add(tuple(identity[key] for key in sorted(_IDENTITY_FIELDS)))
        values[name], records[name] = value, raw
        refs[name] = {
            **canonical["source"], "column": column,
            "source_hash": dataset["source_hash"], "data_hash": dataset["data_hash"],
            "unit": scope["unit"], "currency": scope["currency"], "period": scope["period"],
        }
    _require(len(identities) == 1, "source bindings mix organization, book, scenario, period, currency or units")
    return values, refs, records


def _expected(values, period):
    kind = values["transaction_type"]

    def number(name, *, positive=False):
        value = _decimal(values[name], name)
        _require(value > 0 if positive else value >= 0, f"{name} must be {'positive' if positive else 'nonnegative'}")
        return value

    def boolean(name, expected):
        # AnalysisData normalizes original JSON booleans to these exact text
        # forms. Do not apply truthiness or accept arbitrary affirmative text.
        value = values[name]
        if type(value) is str and value in {"True", "False"}:
            value = value == "True"
        _require(type(value) is bool and value is expected,
                 f"{name} must have an explicit {expected} source for this policy")

    zero = Decimal(0)
    if kind == "uniform_service_advance":
        _require(values["performance_pattern"] == "uniform_monthly", "uniform monthly performance evidence is required")
        _require(values["fulfilment_basis"] == "cumulative_since_contract_start",
                 "earned_months must be explicitly cumulative since contract start")
        cash, term, earned = number("cash_received"), number("service_months", positive=True), number("earned_months")
        _require(term == term.to_integral_value() and earned <= term,
                 "contract months must be whole and earned months cannot exceed the contract")
        revenue = cash * earned / term
        return {"recognized_revenue": revenue, "contract_liability": cash - revenue}, "contract_cumulative_allocation"
    if kind == "ordinary_service_consumed":
        boolean("service_consumed_in_period", True)
        boolean("future_economic_benefit", False)
        return {"expense": number("amount"), "capitalized_asset": zero}, "transaction_recognition"
    if kind == "capitalizable_acquisition":
        for field in ("future_economic_benefit", "asset_controlled", "reliable_measurement"):
            boolean(field, True)
        life = number("useful_life_months", positive=True)
        _require(life == life.to_integral_value(), "useful_life_months must be whole")
        return {"expense": zero, "capitalized_asset": number("amount")}, "initial_asset_recognition_before_depreciation"
    if kind == "restricted_cash_release":
        cash, restricted, release = number("cash_balance"), number("restricted_cash"), number("release_amount")
        _require(restricted <= cash and release <= restricted,
                 "restriction/release amounts exceed the sourced cash/restriction balance")
        _require(_text(values["restriction_id"]) and values["release_restriction_id"] == values["restriction_id"],
                 "release evidence must identify the original restriction")
        _require(_text(values["release_id"]) and _text(values["release_reference"]),
                 "release document identity and reference are required")
        _require(values["release_status"] in {"effective", "ineffective"}, "explicit release status is required")
        as_of = _date(values["as_of_date"], "as_of_date")
        _require(values["as_of_date"] == values["recognition_date"], "release review date must equal recognition date")
        effective_date = _date(values["release_effective_date"], "release_effective_date")
        applied = release if values["release_status"] == "effective" and effective_date <= as_of else zero
        remaining = restricted - applied
        available = cash - remaining
        return {"available_cash": available, "remaining_restricted_cash": remaining,
                "cash_shortfall": max(zero, number("obligations_due") - available)}, "cash_availability_at_review_date"
    amount = number("amount")
    if kind == "old_ar_collection":
        _require(_period(values["receivable_origin_period"]) < period,
                 "opening receivable must originate before the review period")
        _require(number("opening_receivable") >= amount, "collection exceeds sourced opening receivable")
        return {"cash_delta": amount, "receivables_delta": -amount,
                "revenue_delta": zero, "profit_delta": zero}, "transaction_movement"
    boolean("performance_obligation_satisfied", True)
    profit = amount - number("associated_expense") - number("tax_expense")
    return {"cash_delta": amount, "receivables_delta": zero,
            "revenue_delta": amount, "profit_delta": profit}, "transaction_movement"


def review_transaction(inputs, context, datasets):
    """Return itemized expected/actual differences or explicit blocking gaps.

    This deliberately supports one transaction and a closed registered policy.
    All factual bindings must share one original transaction row; all policy
    bindings must share one policy row linked by the transaction's policy_id.
    It supports no currency/unit conversion, arbitrary formulas or approvals.
    """
    report = {
        "rule_version": RULE_VERSION, "columns": ["item", "expected", "actual", "difference", "status"],
        "rows": [], "checks": [], "diagnostics": [], "input_gaps": [],
        "expected_entries": {}, "evidence_eligible": False,
        "qualification": "source_bound_transaction_check_requires_professional_review",
        "source_binding_status": {"status": "input_gap", "all_sources_verified": False},
    }
    refs = {}
    try:
        _require(isinstance(inputs, dict), "transaction review inputs must be an object")
        _require(not set(inputs) - {"scope", "source_bindings", "proposed_entries"}, "unsupported transaction review inputs")
        scope = inputs.get("scope")
        _require(isinstance(scope, dict) and not set(scope) - _IDENTITY_FIELDS,
                 "review scope requires explicit identity fields")
        for key in ("organization", "period", "currency", "unit"):
            _require(_text(scope.get(key)), f"review scope requires {key}")
        for key, value in scope.items():
            _require(_text(value), f"review scope {key} must be text")
        period = _period(scope["period"])
        bindings = inputs.get("source_bindings")
        _require(isinstance(bindings, dict) and BASE_FIELDS | POLICY_FIELDS <= set(bindings),
                 "original transaction identity, nature, recognition date and effective policy bindings are required")
        values, refs, records = _resolve(bindings, context, datasets, scope)
        kind = values["transaction_type"]
        _require(isinstance(kind, str) and kind in POLICIES, "unsupported source transaction_type")
        required = BASE_FIELDS | POLICY_FIELDS | FACT_FIELDS[kind]
        _require(set(bindings) == required, "source bindings must contain exactly the registered transaction facts and policy fields")
        _require(_text(values["transaction_id"]), "original transaction_id is required")
        fact_fields = BASE_FIELDS | FACT_FIELDS[kind]
        groups = [(fact_fields, "transaction"), (POLICY_FIELDS, "policy")]
        if kind == "restricted_cash_release":
            groups = [(fact_fields - RELEASE_FIELDS, "transaction"), (POLICY_FIELDS, "policy"),
                      (RELEASE_FIELDS, "release")]
        for group, label in groups:
            locations = {(refs[name]["dataset_id"], refs[name]["row_index"]) for name in group}
            _require(len(locations) == 1, f"{label} facts must come from one original record")
        transaction = records["transaction_id"]
        _require(transaction.get("transaction_id") == values["transaction_id"], "transaction identity must match its original record")
        if kind == "restricted_cash_release":
            _require((refs["release_id"]["dataset_id"], refs["release_id"]["row_index"]) !=
                     (refs["transaction_id"]["dataset_id"], refs["transaction_id"]["row_index"]),
                     "release requires a separate original evidence record")
        _require(transaction.get("policy_id") == values["policy_id"], "transaction must explicitly link the sourced policy_id")
        _require(values["policy_id"] == POLICIES[kind], "source policy does not match registered transaction policy")
        _require(values["policy_transaction_type"] == kind and _text(values["policy_reference"]),
                 "explicit policy reference and applicable transaction nature are required")
        recognition = _date(values["recognition_date"], "recognition_date")
        _require(recognition.strftime("%Y-%m") == period, "recognition date is outside review period")
        _require(_date(values["policy_effective_from"], "policy_effective_from") <= recognition <=
                 _date(values["policy_effective_to"], "policy_effective_to"), "policy is not effective on recognition date")
        # No global Decimal context changes; independent of caller precision.
        with localcontext() as decimal_context:
            decimal_context.prec = max(80, sum(len(str(value)) for value in values.values()) + 20)
            expected, measurement_basis = _expected(values, period)
            proposed = inputs.get("proposed_entries")
            _require(isinstance(proposed, dict) and set(proposed) == set(expected),
                     "proposed_entries must contain exactly the registered result items")
            actual = {name: _decimal(value, f"proposed_entries.{name}") for name, value in proposed.items()}
            source_rows = list({_hash(ref): ref for ref in refs.values()}.values())
            basis = {
                "rule_version": RULE_VERSION, "transaction_id": values["transaction_id"],
                "transaction_type": kind, "policy_id": values["policy_id"],
                "policy_reference": values["policy_reference"], "measurement_basis": measurement_basis,
                "recognition_date": values["recognition_date"], "actual_basis": "proposed_entries",
            }
            for name, expected_value in expected.items():
                difference = actual[name] - expected_value
                row = {"item": name, "expected": _money(expected_value), "actual": _money(actual[name]),
                       "difference": _money(difference), "status": "pass" if difference == 0 else "fail",
                       "severity": "error", "blocks_evidence": True, "amount": None,
                       "source_rows": source_rows, "basis": basis,
                       "fact_eligibility": {"status": "transaction_check", "counts_as_evidence": False}}
                report["rows"].append(row)
                report["checks"].append({"id": f"transaction.{name}", **row})
                if difference:
                    report["diagnostics"].append({"code": "transaction_recognition_mismatch", "severity": "error",
                                                  "message": f"{name} differs from source-derived recognition", "item": name})
            report.update(expected_entries={name: _money(value) for name, value in expected.items()},
                          basis=basis, source_rows=source_rows, source_bindings=refs,
                          source_binding_status={"status": "source_bound", "all_sources_verified": True},
                          status="fail" if report["diagnostics"] else "pass")
    except (FoundryError, KeyError, TypeError) as exc:
        message = str(exc)
        report.update(status="input_gap", source_rows=list(refs.values()))
        report["input_gaps"].append({"code": "transaction_input_gap", "message": message})
        report["diagnostics"].append({"code": "transaction_input_gap", "severity": "error", "message": message})
    return report
