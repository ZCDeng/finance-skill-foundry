"""Server-owned professional evidence and scoped rule identities.

Calculation outputs remain readable even when they cannot answer an amount.
Never interpret caller labels or a finance engine name as source evidence.
"""
from __future__ import annotations

from foundry.errors import FoundryError
from datetime import date
from decimal import Decimal, InvalidOperation
import re

BASE_FIELDS = frozenset({"purpose", "effective_period.start", "effective_period.end", "functional_currency",
                         "presentation_currency", "presentation_unit", "entity_scope"})
STANDARD_FIELDS = frozenset({"basis", "basis_version", "fiscal_year_start", "early_adoption"})
POLICIES = {"depreciation_start": {"in_service_month", "following_month"},
            "cash_flow_presentation": {"direct", "indirect"}}
RULES = {
    "accounting.transaction_recognition": (1, frozenset()),
    "variance.volume_mix_price": (1, frozenset()),
    "driver.source_binding": (1, BASE_FIELDS | STANDARD_FIELDS),
    "statements.linked_management": (1, BASE_FIELDS | STANDARD_FIELDS),
    "cash.collection_screen": (1, frozenset()),
    "cash.functional_currency_balance": (1, BASE_FIELDS | STANDARD_FIELDS),
    "accounting.depreciation_start": (1, BASE_FIELDS | STANDARD_FIELDS | {"policies.depreciation_start"}),
    "accounting.cash_flow_presentation": (1, BASE_FIELDS | STANDARD_FIELDS | {"policies.cash_flow_presentation"}),
}
TEMPLATE_ID = "linked_three_statement_management_v1"
TEMPLATE_METRICS = frozenset({"net_income", "cash_flow_operating", "cash_flow_investing", "cash_flow_financing",
                            "closing_cash", "closing_receivables", "closing_ppe", "closing_payables", "closing_debt",
                            "closing_equity", "total_assets", "total_liabilities_equity", "available_cash"})


def _hash(value):
    from foundry.analysis import _hash as canonical_hash
    return canonical_hash(value)


def _rule_epoch_heads(service, *, max_seq=None):
    """Task-owned review events, independent of implementation versions and source visibility."""
    root = service.analysis._inside(service.analysis.root / service._folder("rule_epochs"))
    records = [service.analysis._read(path) for path in root.glob("*.json")]
    # These events govern the whole task. Snapshot filtering must never hide an invalid
    # bound event and silently restore an older rule identity for a narrower reader.
    for record in records:
        if (record.get("domain") != "foundry.finance.rule_epochs.v1" or record.get("bindings", {}) != {}
                or type(record.get("seq")) is not int or record["seq"] <= 0):
            raise FoundryError("invalid professional rule epoch record")
    heads = {}
    for record in sorted(records, key=lambda row: row["seq"]):
        if max_seq is not None and record["seq"] >= max_seq:
            continue
        key = record.get("rule_id")
        if not isinstance(key, str) or key not in RULES:
            raise FoundryError("invalid professional rule epoch rule_id")
        previous = heads.get(key)
        epoch = previous["epoch"] if previous else 0
        if (record.get("changed_by") != "manager" or record.get("session_id")
                or type(record.get("epoch")) is not int or record["epoch"] != epoch + 1
                or type(record.get("previous_epoch")) is not int or record["previous_epoch"] != epoch
                or record.get("parent_id") != (previous["id"] if previous else None)):
            raise FoundryError("invalid professional rule epoch history")
        heads[key] = record
    return heads


def advance_rule_epoch(service, spec):
    """A trusted operator requests review invalidation, not approval or a code-version change."""
    service._manager_only("advance a professional rule epoch")
    if service.session_id:
        raise FoundryError("runtime sessions cannot advance a professional rule epoch")
    if not isinstance(spec, dict) or set(spec) != {"rule_id", "expected_epoch", "reason"}:
        raise FoundryError("rule epoch advance requires only rule_id, expected_epoch and reason")
    key = spec["rule_id"]
    if not isinstance(key, str) or key not in RULES:
        raise FoundryError("rule_id must name a registered professional rule")
    expected = spec["expected_epoch"]
    if type(expected) is not int or expected < 0:
        raise FoundryError("expected_epoch must be a nonnegative integer")
    reason = spec["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise FoundryError("rule epoch reason must be nonempty text, at most 2000 characters")
    from foundry.locking import exclusive
    from foundry.analysis import _new
    with exclusive(service.task.lock_path):
        previous = _rule_epoch_heads(service).get(key)
        current = previous["epoch"] if previous else 0
        if expected != current:
            raise FoundryError(f"rule epoch conflict: expected {expected}, current {current}")
        record = _new(service.task, domain="foundry.finance.rule_epochs.v1", rule_id=key,
                      epoch=current + 1, previous_epoch=current, implementation_version=RULES[key][0],
                      changed_by=service.actor, session_id=None, reason=reason.strip(),
                      **({"parent_id": previous["id"]} if previous else {}))
        record = service.analysis._write_locked(service._path("rule_epochs", record["id"]), record)
    return {"schema_version": 1, "rule_epoch": record}


def list_rule_epochs(service, spec):
    if not isinstance(spec, dict) or spec:
        raise FoundryError("rule epoch list requires an empty object")
    heads = _rule_epoch_heads(service)
    # Runtime readers need the current identity, not private manager explanations.
    return {"schema_version": 1, "rules": [
        {"rule_id": key, "implementation_version": RULES[key][0], "epoch": heads.get(key, {}).get("epoch", 0),
         "epoch_record_id": heads.get(key, {}).get("id")} for key in sorted(RULES)]}


def profile_fields(profile):
    result = {}
    for key, value in profile.items():
        if isinstance(value, dict):
            result.update({f"{key}.{child}": item for child, item in value.items()})
        else:
            result[key] = value
    return result


def clean_reporting_profile(value):
    if not isinstance(value, dict):
        raise FoundryError("reporting_profile must be an object")
    allowed = {field for field in BASE_FIELDS if "." not in field} | STANDARD_FIELDS | {"schema_version", "effective_period", "policies"}
    if set(value) - allowed:
        raise FoundryError("reporting_profile contains unsupported fields")
    if value.get("schema_version", 1) != 1:
        raise FoundryError("unsupported reporting profile version")
    if value.get("basis") not in {"CAS", "IFRS", "US_GAAP", "management"}:
        raise FoundryError("unsupported reporting basis")
    if value.get("purpose") not in {"management", "forecast", "statutory"}:
        raise FoundryError("unsupported reporting purpose")
    profile = {**value, "schema_version": 1}
    for key in ("basis_version", "functional_currency", "presentation_currency", "presentation_unit", "entity_scope"):
        if not isinstance(profile.get(key), str) or not profile[key].strip() or len(profile[key]) > 160:
            raise FoundryError(f"reporting profile requires {key}")
    period = profile.get("effective_period")
    if not isinstance(period, dict) or set(period) != {"start", "end"}:
        raise FoundryError("reporting profile requires effective_period start and end")
    for month in period.values():
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise FoundryError("profile effective period must be YYYY-MM")
    if period["start"] > period["end"]:
        raise FoundryError("profile effective period is reversed")
    try:
        date.fromisoformat(profile["fiscal_year_start"])
    except (KeyError, TypeError, ValueError):
        raise FoundryError("profile fiscal_year_start must be an ISO date") from None
    if not (isinstance(profile.get("early_adoption"), bool) or profile.get("early_adoption") == "unknown"):
        raise FoundryError("early_adoption must be true, false or unknown")
    policies = profile.get("policies", {})
    if not isinstance(policies, dict) or set(policies) - set(POLICIES):
        raise FoundryError("unsupported professional policy")
    if any(value not in POLICIES[key] for key, value in policies.items()):
        raise FoundryError("unsupported professional policy value")
    profile["policies"] = dict(policies)
    return profile


def _is_zero(value):
    try:
        number = Decimal(str(value))
        return number.is_finite() and number == 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def confirmation_basis(context):
    return {key: context.get(key) for key in ("task_id", "bindings", "source_hashes", "scopes")}


def profile_gap(service, context, required, *, max_seq=None):
    """Show the manager what this basis has approved, what the rule still needs, and the current values.

    Existence of a profile value is not approval. A seven-field event stays readable and does not
    cover an eleven-field rule. Revocation drops current approval without rewriting the old event.
    Partial approvals from a different confirmation basis are not merged in.
    """
    required = frozenset(required or ())
    fields = profile_fields(context.get("reporting_profile") or {})
    basis = confirmation_basis(context)
    records = [record for record in service._list("profile_confirmations")
               if (max_seq is None or record.get("seq", 0) < max_seq)
               and record.get("confirmation_basis") == basis
               and not record.get("confirmed_model_boundaries")]
    current = max(records, key=lambda record: record.get("seq", 0)) if records else None
    confirmed = set()
    stored = {}
    if current and current.get("status") == "confirmed" and current.get("confirmed_by") == "manager":
        confirmed = set(current.get("confirmed_fields") or [])
        stored = current.get("field_values") or {}
    approved = sorted(key for key in required if key in confirmed and stored.get(key) == fields.get(key))
    stale = sorted(key for key in required if key in confirmed and stored.get(key) != fields.get(key))
    return {
        "approved_fields": approved,
        "required_fields": sorted(required),
        "missing_fields": sorted(required - set(approved)),
        "stale_fields": stale,
        "current_values": {key: fields.get(key) for key in sorted(required)},
        "approval_basis": current.get("confirmation_basis") if current else None,
        "confirmation_id": current.get("id") if current else None,
        "confirmation_status": current.get("status") if current else None,
    }


def profile_confirmation(service, context, required, *, max_seq=None):
    fields = profile_fields(context.get("reporting_profile") or {})
    records = [record for record in service._list("profile_confirmations")
               if max_seq is None or record.get("seq", 0) < max_seq]
    candidates = [record for record in records if record.get("confirmation_basis") == confirmation_basis(context)]
    named = context.get("profile_confirmation_id")
    for record in reversed(candidates):
        # The newest event of this confirmation lineage decides revocation.
        root = record.get("confirmation_root") or record["id"]
        latest = next((item for item in reversed(records) if (item.get("confirmation_root") or item["id"]) == root), record)
        confirmed = set(latest.get("confirmed_fields") or [])
        if required <= confirmed and all(latest.get("field_values", {}).get(key) == fields.get(key) for key in required):
            if named and named not in {latest["id"], root}:
                return None  # A pinned older reference cannot bypass the newest decision for this basis.
            return latest if latest.get("status") == "confirmed" and latest.get("confirmed_by") == "manager" else None
    return None


def profile_route(profile, *, confirmed_fields=()):
    if not profile:
        return {"status": "legacy", "standard": None}
    standard = profile["basis"]
    if standard == "IFRS":
        annual = profile["fiscal_year_start"]
        early = profile["early_adoption"]
        if annual < "2027-01-01":
            if early == "unknown" or "early_adoption" not in confirmed_fields:
                return {"status": "awaiting_profile_confirmation", "standard": None}
            standard = "IFRS18" if early is True else "IAS1"
        else:
            standard = "IFRS18"
        if profile["basis_version"] not in {standard, f"{standard}-2026", f"{standard}-2027"}:
            return {"status": "unsupported_professional_route", "standard": standard}
    # This release supports management/forecast templates, not statutory preparation.
    return {"status": "unsupported_professional_route" if profile["purpose"] == "statutory" else "supported",
            "standard": standard}


def rule_ids_for(*, operation=None, spec=None, scenario=None, items=None, control=None):
    spec = spec or {}
    ids = set()
    if spec.get("method") == "volume_mix_price" or any(
            (item.get("dimensions") or {}).get("method") == "volume_mix_price" for item in items or []):
        ids.add("variance.volume_mix_price")
    if scenario and scenario.get("kind") == "driver_model":
        inputs = scenario.get("inputs") or {}
        if inputs.get("source_bindings"):
            ids.add("driver.source_binding")
        if inputs.get("template_id") == TEMPLATE_ID:
            ids.update({"driver.source_binding", "statements.linked_management"})
    if any((item.get("dimensions") or {}).get("template_id") == TEMPLATE_ID for item in items or []):
        ids.update({"driver.source_binding", "statements.linked_management"})
    if (scenario or {}).get("kind") == "transaction_review" or any(
            item.get("metric") == "transaction_review" for item in items or []):
        ids.add("accounting.transaction_recognition")
    formula = (control or {}).get("formula")
    if formula in {"dso", "implied_collection"}:
        ids.add("cash.collection_screen")
    if formula == "volume_mix_price_closure":
        ids.add("variance.volume_mix_price")
    return sorted(ids)


def rule_identity(service, context, rule_ids, *, max_seq=None, scenario_ids=()):
    heads = _rule_epoch_heads(service, max_seq=max_seq) if rule_ids else {}
    # Epoch zero keeps existing identities byte-compatible; only an explicit review event changes one.
    dependencies = [{"id": key, "version": RULES[key][0], **({"epoch": heads[key]["epoch"]} if key in heads else {})}
                    for key in sorted(set(rule_ids))]
    required = frozenset().union(*(RULES[item["id"]][1] for item in dependencies))
    profile = context.get("reporting_profile") or {}
    fields = profile_fields(profile)
    confirmation = profile_confirmation(service, context, required, max_seq=max_seq) if required else None
    basis = {"fields": {key: fields.get(key) for key in sorted(required)}} if required else {}
    if required:
        basis["confirmation_id"] = confirmation["id"] if confirmation else None
    route = profile_route(profile, confirmed_fields=(confirmation or {}).get("confirmed_fields", [])) if required else {"status": "supported"}
    status = ("awaiting_profile_confirmation" if required and not confirmation else route["status"])
    if "statements.linked_management" in rule_ids:
        approvals = {}
        for scenario_id in sorted(set(scenario_ids)):
            try:
                proof = boundary_basis(service, context, scenario_id)
                approval = boundary_confirmation(service, proof, max_seq=max_seq)
                approvals[scenario_id] = {"basis_hash": _hash(proof), "confirmation_id": approval["id"] if approval else None}
            except (FoundryError, KeyError, TypeError, ValueError, OSError):
                approvals[scenario_id] = {"basis_hash": None, "confirmation_id": None}
        basis["model_boundaries"] = approvals
        if status == "supported" and (not approvals or any(not item["confirmation_id"] for item in approvals.values())):
            status = "awaiting_model_boundary_confirmation"
    return {"rule_dependencies": dependencies, "rule_basis": basis,
            "rule_fingerprint": _hash({"version": 1, "dependencies": dependencies, "basis": basis}),
            "professional_status": status, "required_profile_fields": sorted(required), "professional_route": route}


def requirement_rule_identity(analysis, record, *, allowed=None, historical=False):
    from foundry.finance_service import FinanceStore
    ids = rule_ids_for(items=record.get("items"))
    if not ids:
        return None
    service = FinanceStore(analysis.task, snapshot_ids=allowed)
    try:
        context = _requirement_context(service, record)
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return {"rule_dependencies": [{"id": key, "version": RULES[key][0]} for key in ids],
                "rule_fingerprint": None, "professional_status": "professional_context_unavailable"}
    scenario_ids = [(item.get("dimensions") or {}).get("scenario_id") for item in record.get("items", [])
                    if (item.get("dimensions") or {}).get("template_id") == TEMPLATE_ID]
    return rule_identity(service, context, ids, max_seq=record.get("seq") if historical else None,
                         scenario_ids=[key for key in scenario_ids if isinstance(key, str)])


def _requirement_context(service, record):
    """Read the actual authorized context; never replace the obligation's sources."""
    if not record.get("context_id"):
        raise FoundryError(
            "professional_context_required: professional requirements need a real context_id before registration; "
            "create/select finance_context with required_bindings equal to all original bindings, then resubmit "
            "the complete requirements using its returned id. Do not delete sources or requirements."
        )
    context = service._read("contexts", record["context_id"])
    service._authorize(record.get("bindings", {}))
    if not context.get("bindings") or context.get("id") != record["context_id"]:
        raise FoundryError("professional context identity is unavailable; restore its real required_bindings")
    if context.get("bindings") != record.get("bindings"):
        raise FoundryError("professional requirement bindings must exactly match the context bindings; "
                           "retain all required_bindings and create/select a matching context before registration")
    for alias, dataset_id in context["bindings"].items():
        dataset = service.analysis.read_dataset(dataset_id)
        if context.get("source_hashes", {}).get(alias) != dataset["source_hash"]:
            raise FoundryError("professional context source identity is unavailable; restore verified required_bindings")
    return context


def valid_rule_identity(identity):
    """Structural identity is required even when genuine professional approval is pending."""
    if not isinstance(identity, dict) or not isinstance(identity.get("rule_basis"), dict):
        return False
    dependencies = identity.get("rule_dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        return False
    seen = set()
    for dependency in dependencies:
        if (not isinstance(dependency, dict) or not isinstance(dependency.get("id"), str)
                or dependency["id"] not in RULES
                or dependency["id"] in seen or type(dependency.get("version")) is not int
                or dependency["version"] < 1 or type(dependency.get("epoch", 0)) is not int
                or dependency.get("epoch", 0) < 0):
            return False
        seen.add(dependency["id"])
    return identity.get("rule_fingerprint") == _hash({
        "version": 1, "dependencies": dependencies, "basis": identity["rule_basis"]})


def validate_requirement_identity(analysis, record, *, allowed=None):
    """Fail before authoring; absent approval remains a valid, explicitly blocked identity."""
    if not rule_ids_for(items=record.get("items")):
        return None
    from foundry.finance_service import FinanceStore
    _requirement_context(FinanceStore(analysis.task, snapshot_ids=allowed), record)
    identity = requirement_rule_identity(analysis, record, allowed=allowed)
    if not valid_rule_identity(identity):
        raise FoundryError("professional_identity_invalid: restore the real context and complete required_bindings, "
                           "then register the original requirements before calculating")
    return identity


def boundary_basis(service, context, scenario_id):
    """Resolve exactly the immutable scenario's eight declared boundaries from archived bytes."""
    from foundry.finance_driver_templates import BOUNDARY_INPUTS
    from foundry.finance_scenario_service import calculate_scenario
    scenario = service._read("scenarios", scenario_id)
    if scenario.get("context_id") != context.get("id") or (scenario.get("inputs") or {}).get("template_id") != TEMPLATE_ID:
        raise FoundryError("model boundary scenario does not belong to this template context")
    datasets = {alias: service.analysis.read_dataset(dataset_id) for alias, dataset_id in context["bindings"].items()}
    result = calculate_scenario(scenario, context, datasets)
    proofs = result["source_binding_status"]["bindings"]
    if any(proofs.get(key, {}).get("status") != "source_verified" or not _is_zero(proofs.get(key, {}).get("value")) for key in BOUNDARY_INPUTS):
        raise FoundryError("all eight model boundaries require verified zero sources")
    return {"scenario_id": scenario_id, "scenario_input_hash": scenario["input_hash"],
            "confirmation_basis": confirmation_basis(context), "period": scenario["inputs"].get("period") or scenario["inputs"].get("scope", {}).get("period"),
            "scope": scenario["inputs"]["scope"],
            "source_hashes": {alias: dataset["source_hash"] for alias, dataset in datasets.items()},
            "input_hashes": {alias: dataset["data_hash"] for alias, dataset in datasets.items()},
            "boundaries": {key: proofs[key] for key in BOUNDARY_INPUTS}}


def boundary_confirmation(service, basis, *, max_seq=None):
    records = [row for row in service._list("profile_confirmations") if max_seq is None or row["seq"] < max_seq]
    for record in reversed(records):
        if record.get("boundary_basis") != basis or record.get("confirmed_by") != "manager":
            continue
        root = record.get("confirmation_root") or record["id"]
        latest = next(row for row in reversed(records) if (row.get("confirmation_root") or row["id"]) == root)
        return latest if latest.get("status") == "confirmed" else None
    return None


def artifact_rules_match(run, expected):
    """A basket and a model may answer one question without sharing irrelevant rules."""
    captured = run.get("professional_identity") if run.get("engine") == "finance" else run.get("requirements_rule_identity")
    captured = captured or {}
    dependencies = captured.get("rule_dependencies") or []
    if not dependencies:
        return True
    versions = {item["id"]: (item["version"], item.get("epoch", 0)) for item in expected.get("rule_dependencies", [])}
    if any(versions.get(item["id"]) != (item["version"], item.get("epoch", 0)) for item in dependencies):
        return False
    basis, wanted = captured.get("rule_basis") or {}, expected.get("rule_basis") or {}
    if any(wanted.get("fields", {}).get(key) != value for key, value in basis.get("fields", {}).items()):
        return False
    if "confirmation_id" in basis and basis["confirmation_id"] != wanted.get("confirmation_id"):
        return False
    return all(wanted.get("model_boundaries", {}).get(key) == value for key, value in basis.get("model_boundaries", {}).items())


def saved_professional_problem(analysis, draft, allowed=None, *, cache=None):
    """Stored success remains historical; current views recheck its scoped approvals."""
    from foundry.finance_adjustments import current_reference_issues

    adjustment_issues = current_reference_issues(analysis, draft, allowed=allowed)
    if adjustment_issues:
        return adjustment_issues[0]["code"]
    from foundry.finance_transaction_reviews import current_problem
    try:
        transaction_problem = current_problem(analysis, draft, allowed, cache=cache)
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        transaction_problem = "professional_context_unavailable"
    if transaction_problem:
        return transaction_problem
    requirement_id = draft.get("requirements_id") or ((draft.get("explanation_check") or {}).get("requirements") or {}).get("requirements_id")
    if not requirement_id:
        return None
    try:
        record = analysis._get("requirements", requirement_id)
        from foundry.finance_requirements import requirements_readable
        if not requirements_readable(record, allowed):
            return "professional_context_unavailable"
        if not (record.get("semantic_basis") or {}).get("professional_identity"):
            return None
        current = requirement_rule_identity(analysis, record, allowed=allowed)
        if current["professional_status"] != "supported":
            return current["professional_status"]
        if not valid_rule_identity(record["semantic_basis"]["professional_identity"]):
            return "professional_identity_invalid"
        if current["rule_fingerprint"] != record["semantic_basis"]["professional_identity"]["rule_fingerprint"]:
            return "professional_rules_changed"
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return "professional_context_unavailable"
    return None


def _current_claim_issues(analysis, draft, allowed):
    from foundry.finance_explanations import saved_claim_semantic_issues
    try:
        return saved_claim_semantic_issues(analysis, draft, allowed)
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return [{"code": "claim_semantic_context_unavailable", "severity": "error",
                 "message": "当前无法读取正文语义核验所需证据，请恢复来源后重新验证。"}]


def draft_professional_view(analysis, draft, allowed=None, *, cache=None):
    from foundry.finance_transaction_reviews import has_transaction, _service
    try:
        transaction = has_transaction(analysis, draft, allowed=allowed, cache=cache)
    except FoundryError:
        # Keep the archived draft for the existing evidence-view fallback. An
        # unreadable run cannot validate a current receipt (checked separately).
        return draft
    if transaction:
        try:
            quality = _service(analysis, allowed).validate_explanation({"draft_id": draft["id"]})
            return {**draft, "quality": quality, "explanation_check": quality}
        except (FoundryError, OSError, KeyError, TypeError, ValueError):
            pass
    problem = saved_professional_problem(analysis, draft, allowed, cache=cache)
    semantic_issues = _current_claim_issues(analysis, draft, allowed)
    if not problem and not semantic_issues:
        return draft
    problem = problem or ("claim_semantic_context_unavailable" if any(
        issue.get("code") == "claim_semantic_context_unavailable" for issue in semantic_issues) else "claim_semantics_changed")
    result = {**draft, "professional_reason": problem}
    for key in ("quality", "explanation_check"):
        check = draft.get(key)
        if isinstance(check, dict):
            result[key] = {**check, "status": "needs_attention", "professional_reason": problem,
                           "issues": [*(check.get("issues") or []), *semantic_issues],
                           "requirements": {**(check.get("requirements") or {}),
                                            "coverage": {"status": "needs_attention"}, "original_requirements_completed": False}}
    return result


def receipt_professional_view(analysis, receipt, allowed=None, *, cache=None):
    if not receipt or not receipt.get("draft_id"):
        return receipt
    try:
        draft = analysis.get_draft(receipt["draft_id"])
        problem = saved_professional_problem(analysis, draft, allowed, cache=cache)
        semantic_issues = _current_claim_issues(analysis, draft, allowed)
    except FoundryError:
        problem = "claim_semantic_context_unavailable"
        semantic_issues = [{"code": problem}]
    if not problem and not semantic_issues:
        from foundry.finance_completion import receipt_fingerprint_view
        return receipt_fingerprint_view(analysis, receipt, allowed)
    problem = problem or ("claim_semantic_context_unavailable" if any(
        issue.get("code") == "claim_semantic_context_unavailable" for issue in semantic_issues) else "claim_semantics_changed")
    professional_message = {
        "adjustment_approval_superseded": "引用的调整后金额已被同范围的新批准替代；请按当前批准重新计算，历史结果保留。",
        "adjustment_dependency_unavailable": "引用的调整后金额所依赖的批准无法核验；请恢复获授权的依赖后重新验证。",
        "professional_context_unavailable": "需求绑定的财务 context 或来源身份不可核验；请恢复获授权的完整来源，"
                                            "以真实 context 重新登记完整要求并重算。此记录不证明专业批准发生变化。",
        "professional_identity_invalid": "需求的专业规则身份不完整；请以真实 context 及全部原始来源修订需求后重算，"
                                         "不能复用失效身份或改写历史回执。",
    }.get(problem, "专业口径或模型边界批准需复核，请按当前要求确认后重新运行。")
    needs_review = bool(semantic_issues) or problem in {"adjustment_approval_superseded", "adjustment_dependency_unavailable"}
    return {**{key: value for key, value in receipt.items() if key != "_integrity_hash"},
            "historical_status": receipt.get("status"),
            "status": "needs_review" if needs_review else "awaiting_manager", "professional_reason": problem,
            "response_status": "needs_review" if needs_review else "ended_with_limitations",
            "original_requirements_completed": False, "repair_allowed": False, "stop_reason": problem,
            "actions": [{"code": problem, "message": semantic_issues[0].get("message", "当前核验证据不可用，请复核。") if semantic_issues
                         else professional_message}]}


def cell_evidence_eligibility(run, row, column, *, analysis=None):
    refs = (row.get("evidence") or {}).get(column, row.get("source_rows", []))
    # A zero aging bucket is proved by the complete source-backed population,
    # not by pretending that zero has an originating invoice in that bucket.
    if not refs and analysis is not None and column == "open_amount" and row.get(column) == "0":
        try:
            from foundry.finance_service import FinanceStore
            result = run.get("result") or {}
            scenario = FinanceStore(analysis.task)._read("scenarios", result["scenario_id"])
            if scenario["kind"] == "receivables_aging":
                population = [detail for detail in result.get("detail_rows", [])
                              if all(detail.get(key) == row.get(key) for key in
                                     ("ledger", "organization", "currency", "unit"))]
                if population and not any(detail.get("bucket") == row.get("bucket") for detail in population):
                    refs = [ref for detail in population for ref in detail.get("source_rows", [])]
        except (FoundryError, OSError, KeyError, TypeError, ValueError):
            pass
    reasons = []
    if analysis is None:
        reasons.append("source_verification_required")
    if run.get("engine") != "finance":
        reasons.append("not_finance_engine")
    if not isinstance(refs, list) or not refs:
        reasons.append("amount_sources_missing")
        refs = []
    datasets = {}
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("dataset_id") not in (run.get("bindings") or {}).values():
            reasons.append("amount_source_outside_bindings")
            continue
        index = ref.get("row_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            reasons.append("amount_source_row_invalid")
            continue
        if analysis is not None:
            try:
                dataset_id = ref["dataset_id"]
                if dataset_id not in datasets:
                    datasets[dataset_id] = analysis.read_dataset(dataset_id)
                dataset = datasets[dataset_id]
                if index > len(dataset.get("rows") or []):
                    reasons.append("amount_source_row_invalid")
                for alias, bound in (run.get("bindings") or {}).items():
                    if bound == dataset_id and ((run.get("source_hashes") or {}).get(alias) != dataset["source_hash"]
                            or (run.get("input_hashes") or {}).get(alias) != dataset["data_hash"]):
                        reasons.append("amount_source_hash_mismatch")
            except (FoundryError, OSError, KeyError, TypeError, ValueError):
                reasons.append("amount_source_unavailable")
    if analysis is not None and (run.get("result") or {}).get("source_binding_status"):
        reasons.extend(_driver_evidence_reasons(analysis, run, row))
    if analysis is not None:
        from foundry.finance_adjustments import current_cell_problem

        adjustment_problem = current_cell_problem(analysis, run, row, column)
        if adjustment_problem:
            reasons.append(adjustment_problem)
    reasons = sorted(set(reasons))
    return {"status": "unverified" if reasons else "model_verified" if row.get("template_id") == TEMPLATE_ID else "source_verified",
            "counts_as_amount_evidence": not reasons, "reason_codes": reasons,
            "source_rows": refs}


def _driver_evidence_reasons(analysis, run, row):
    """Verify registered financial meaning as well as archived input provenance."""
    from foundry.finance_driver_templates import BOUNDARY_INPUTS, OUTPUT_SEMANTICS, TEMPLATE_INPUTS
    from foundry.finance_service import FinanceStore
    result = run.get("result") or {}
    status = result.get("source_binding_status") or {}
    service = FinanceStore(analysis.task)
    try:
        scenario = service._read("scenarios", result["scenario_id"])
        context = service._read("contexts", run["finance_context_id"])
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return ["driver_definition_unavailable"]
    if scenario.get("kind") != "driver_model" or (scenario.get("inputs") or {}).get("template_id") != TEMPLATE_ID:
        return ["unregistered_financial_semantics"]
    metric = row.get("metric_key")
    if row.get("template_id") != TEMPLATE_ID or row.get("template_version") != 1 or metric not in OUTPUT_SEMANTICS:
        return ["unregistered_financial_semantics"]
    statement, line, value_kind = OUTPUT_SEMANTICS[metric]
    reasons = []
    if context.get("bindings") != run.get("bindings") or scenario.get("context_id") != context.get("id"):
        reasons.append("template_context_mismatch")
    if (row.get("statement"), row.get("statement_line"), row.get("value_kind")) != (statement, line, value_kind):
        reasons.append("template_semantics_mismatch")
    bindings = status.get("bindings") or {}
    expected = set(TEMPLATE_INPUTS) | set(BOUNDARY_INPUTS)
    if status.get("resolver") != "finance.source_bindings.v1" or not expected <= set(bindings):
        reasons.append("template_sources_incomplete")
    if row.get("unverified_inputs") or row.get("assumption_ids") or any(
            bindings.get(key, {}).get("status") != "source_verified" for key in expected):
        reasons.append("template_inputs_unverified")
    boundary_ids = set(BOUNDARY_INPUTS)
    if not boundary_ids <= set(row.get("source_binding_ids") or []) or any(
            not _is_zero(bindings.get(key, {}).get("value")) for key in boundary_ids):
        reasons.append("model_boundary_unverified")
    checks = result.get("model_checks") or []
    if not checks or any(check.get("blocks_evidence") and check.get("status") != "pass" for check in checks):
        reasons.append("model_checks_failed")
    identity = rule_identity(service, context, rule_ids_for(scenario=scenario), scenario_ids=[scenario["id"]])
    if identity["professional_status"] != "supported":
        reasons.append(identity["professional_status"])
    if (run.get("professional_identity") or {}).get("rule_fingerprint") != identity["rule_fingerprint"]:
        reasons.append("professional_rules_changed")
    profile = context.get("reporting_profile") or {}
    period = profile.get("effective_period") or {}
    if (profile.get("purpose") not in {"forecast", "management"}
            or row.get("organization") != profile.get("entity_scope")
            or row.get("currency") != profile.get("presentation_currency")
            or row.get("currency") != profile.get("functional_currency")
            or row.get("unit") != profile.get("presentation_unit")
            or not period.get("start", "~") <= row.get("period", "") <= period.get("end", "")):
        reasons.append("template_profile_scope_mismatch")
    return reasons
