"""Append-only manager decisions for transaction-check obligations, never posting authority."""
from __future__ import annotations

from foundry.analysis import _hash, _new
from foundry.errors import FoundryError
from foundry.locking import exclusive

RULE_ID = "accounting.transaction_recognition"
DOMAIN = "foundry.finance.transaction_reviews.v1"
CHECKLIST = ("source_evidence", "policy_applicability", "recognition_cutoff", "classification_measurement", "boundaries")
REVIEW_CODE = "transaction_review_requires_professional_review"
QUALIFICATION = "source_bound_transaction_check_requires_professional_review"
PAYLOAD_FIELDS = ("body", "claims", "fact_ids", "run_ids", "requirements_id", "document", "body_template",
                  "materiality", "evidence_recipes", "consistency_rules", "consistency_sources", "source_read_failures")


def _service(analysis, allowed=None):
    from foundry.finance_service import FinanceStore
    return FinanceStore(analysis.task, snapshot_ids=allowed)


def _records(service):
    root = service.analysis._inside(service.analysis.root / service._folder("transaction_reviews"))
    rows = [service.analysis._read(path) for path in root.glob("*.json")]
    for row in rows:
        proof = row.get("proof") or {}
        checklist = row.get("checklist")
        if (row.get("domain") != DOMAIN or type(row.get("seq")) is not int or row["seq"] <= 0
                or row.get("saved_by") != "manager" or row.get("session_id") is not None
                or row.get("decision") not in {"approved", "rejected", "revoked"}
                or not isinstance(checklist, dict) or set(checklist) != set(CHECKLIST)
                or any(type(value) is not bool for value in checklist.values())
                or row.get("decision") == "approved" and (not all(checklist.values()) or proof.get("blocking_reasons"))
                or proof.get("task_id") != service.task.id or proof.get("draft_id") != row.get("draft_id")
                or row.get("proof_hash") != _hash(proof)
                or row.get("bindings") != {f"source{i}": key for i, key in enumerate(proof.get("snapshot_ids", []))}):
            raise FoundryError("invalid transaction review history")
        _text(row.get("reviewer"), "reviewer")
        _text(row.get("reason"), "reason")
    if len({row["seq"] for row in rows}) != len(rows):
        raise FoundryError("invalid transaction review sequence")
    heads = {}
    for row in sorted(rows, key=lambda item: item["seq"]):
        previous = heads.get(row["draft_id"])
        if (row.get("parent_id") != (previous or {}).get("id")
                or row.get("basis_fingerprint") != _hash({"proof_hash": row["proof_hash"], "head_id": (previous or {}).get("id")})
                or row["decision"] == "revoked" and (not previous or previous["decision"] != "approved"
                                                      or previous["proof_hash"] != row["proof_hash"])):
            raise FoundryError("invalid transaction review decision chain")
        heads[row["draft_id"]] = row
    return heads


def _draft(service, draft_id):
    draft = service.analysis.get_draft(draft_id)
    if not service.analysis.draft_readable(draft, service.allowed):
        raise FoundryError("transaction review draft is outside this session context")
    service._authorize_draft(draft)
    return draft


def obligation_ids(analysis, spec):
    from foundry.finance_requirements import latest_requirements
    requirement = latest_requirements(analysis) or {}
    return [item["id"] for item in requirement.get("items", [])
            if item.get("metric") == "transaction_review" and not item.get("dimensions")
            and not any(item.get(key) for key in ("organizations", "periods", "scenarios"))]


def has_transaction(analysis, spec, *, allowed=None, cache=None):
    # Reuse only integrity-verified immutable runs within this reader's request.
    # Review decisions are deliberately not cached with those runs.
    cache = {} if cache is None else cache
    runs = [analysis.verified_run(key, allowed, cache) for key in spec.get("run_ids", [])]
    for run in runs:
        if run.get("task_id") != analysis.task.id:
            raise FoundryError("transaction review run belongs to another task")
        if allowed is not None and not set((run.get("bindings") or {}).values()) <= set(allowed):
            raise FoundryError("transaction review run is outside this session context")
    return any((run.get("result") or {}).get("qualification") == QUALIFICATION for run in runs)


def _proof(service, draft, spec=None):
    """Only immutable inputs and current source/rule state; no quality/receipt reads or decision-head recursion."""
    from foundry.finance_controls import superseded_snapshots
    from foundry.finance_professional import rule_identity, artifact_rules_match
    from foundry.finance_requirements import latest_requirements, _same_number
    from foundry.finance_scenario_service import calculate_scenario
    analysis = service.analysis
    merged = {**draft, **(spec or {})}
    reasons = []
    payload = {key: merged.get(key) for key in PAYLOAD_FIELDS}
    proof = {"schema_version": 1, "task_id": service.task.id, "draft_id": draft["id"],
             "draft_content_hash": draft["content_hash"], "payload": payload,
             "snapshot_ids": sorted(analysis.draft_snapshots(draft)), "runs": []}
    if payload != {key: draft.get(key) for key in PAYLOAD_FIELDS}:
        reasons.append("draft_changed")
    requirement = latest_requirements(analysis)
    if not requirement or requirement["id"] != draft.get("requirements_id"):
        reasons.append("requirements_changed")
    if not obligation_ids(analysis, merged):
        reasons.append("explicit_transaction_review_required")
    if requirement:
        service._authorize(requirement.get("bindings", {}))
        fingerprint = analysis.fingerprint_in_view(requirement, service.allowed)
        proof["requirements"] = {"id": requirement["id"], "fingerprint": fingerprint}
        if not fingerprint:
            reasons.append("requirements_fingerprint_unverified")
    current_rules = rule_identity(service, {}, [RULE_ID])
    proof["professional_identity"] = current_rules
    replaced = superseded_snapshots(service.task, analysis.published_datasets(), allowed=None)
    if set(proof["snapshot_ids"]) & replaced:
        reasons.append("source_superseded")
    task_service = _service(analysis)
    contexts, scenarios = task_service._list("contexts"), task_service._list("scenarios")
    transactions = 0
    for run_id in dict.fromkeys(draft.get("run_ids", [])):
        run = analysis.get_run(run_id)
        service._authorize(run.get("bindings", {}))
        result = run.get("result") or {}
        item = {"id": run_id, "output_hash": run.get("output_hash"), "bindings": run.get("bindings")}
        proof["runs"].append(item)
        if result.get("qualification") != QUALIFICATION:
            continue
        transactions += 1
        if (run.get("engine") != "finance" or run.get("execution_status") != "succeeded"
                or run.get("output_hash") != _hash(result) or not artifact_rules_match(run, current_rules)
                or not (run.get("professional_identity") or {}).get("rule_dependencies")):
            reasons.append("transaction_run_invalid")
        scenario = service._read("scenarios", result.get("scenario_id"))
        context = service._read("contexts", scenario["context_id"])
        if (scenario.get("kind") != "transaction_review" or scenario.get("input_hash") != _hash(scenario.get("inputs"))
                or run.get("finance_context_id") != context["id"] or result.get("input_hash") != scenario["input_hash"]):
            reasons.append("scenario_mismatch")
        if any(row.get("parent_id") == scenario["id"] and row.get("input_hash") != scenario["input_hash"] for row in scenarios):
            reasons.append("scenario_superseded")
        if any(row.get("parent_id") == context["id"] for row in contexts):
            reasons.append("context_superseded")
        datasets = {alias: analysis.read_dataset(key) for alias, key in context["bindings"].items()}
        item.update(context=context, scenario=scenario,
                    sources={alias: {"id": data["id"], "source_hash": data["source_hash"], "data_hash": data["data_hash"]}
                             for alias, data in datasets.items()})
        for alias, data in datasets.items():
            if (run.get("source_hashes", {}).get(alias) != data["source_hash"]
                    or run.get("input_hashes", {}).get(alias) != data["data_hash"]
                    or context.get("source_hashes", {}).get(alias) != data["source_hash"]):
                reasons.append("source_hash_mismatch")
        fresh = calculate_scenario(scenario, context, datasets)
        item["recomputed"] = {key: value for key, value in fresh.items() if key != "columns"}
        if any(result.get(key) != value for key, value in item["recomputed"].items()):
            reasons.append("transaction_recomputation_mismatch")
        if (fresh.get("status") != "pass" or fresh.get("diagnostics") or fresh.get("input_gaps")
                or not fresh.get("source_rows") or not fresh.get("source_binding_status", {}).get("all_sources_verified")):
            reasons.append("transaction_check_not_passed")
        for index, row in enumerate(fresh.get("rows", [])):
            if not any(claim.get("basis") == "calculation" and claim.get("run_id") == run_id
                       and type(claim.get("row")) is int and claim["row"] == index and claim.get("column") == "actual"
                       and _same_number(claim.get("value"), row.get("actual")) for claim in merged.get("claims", []) if isinstance(claim, dict)):
                reasons.append("transaction_claim_missing")
    if not transactions:
        reasons.append("transaction_run_required")
    proof["blocking_reasons"] = sorted(set(reasons))
    return proof


def decision_for_spec(analysis, spec, allowed=None):
    service = _service(analysis, allowed)
    ids = obligation_ids(analysis, spec)
    key = spec.get("draft_id") or spec.get("id")
    state = {"current_status": "pending", "approved": False, "obligation_ids": ids, "decision": None}
    if not key:
        return state
    draft = _draft(service, key)
    head = _records(service).get(key)
    try:
        proof = _proof(service, draft, spec)
    except (FoundryError, KeyError, TypeError, ValueError, OSError) as exc:
        proof = {"task_id": service.task.id, "draft_id": key, "snapshot_ids": sorted(analysis.draft_snapshots(draft)),
                 "draft_content_hash": draft["content_hash"], "blocking_reasons": ["review_basis_unavailable"],
                 "unavailable_type": type(exc).__name__}
    proof_hash = _hash(proof)
    status = ("stale" if head and head["proof_hash"] != proof_hash else head["decision"] if head else
              "ineligible" if proof["blocking_reasons"] else "pending")
    return {**state, "current_status": status, "approved": status == "approved" and not proof["blocking_reasons"],
            "decision": {"review_id": head["id"], "decision": head["decision"]} if head else None,
            "proof": proof, "proof_hash": proof_hash, "head": head,
            "basis_fingerprint": _hash({"proof_hash": proof_hash, "head_id": (head or {}).get("id")})}


def prepare_review(service, spec):
    if not isinstance(spec, dict) or set(spec) != {"draft_id"}:
        raise FoundryError("transaction review prepare requires only draft_id")
    draft = _draft(service, spec["draft_id"])
    state = decision_for_spec(service.analysis, {**draft, "draft_id": draft["id"]}, service.allowed)
    checked = service.validate_explanation({"draft_id": draft["id"]})
    reasons = list(state["proof"]["blocking_reasons"])
    if any(issue.get("code") != REVIEW_CODE for issue in checked.get("issues", [])):
        reasons.append("draft_validation_failed")
    if any(item.get("status") != "answered" and not item.get("awaiting_manager") == ["transaction_review_required"]
           for item in checked.get("requirements", {}).get("items", [])):
        reasons.append("requirements_incomplete")
    return {"schema_version": 1, "draft_id": draft["id"], "basis_fingerprint": state["basis_fingerprint"],
            "eligibility": {"eligible": not reasons, "reasons": sorted(set(reasons)), "scope": "transaction_review_only",
                            "counts_as_amount_evidence": False, "posting_authorized": False},
            "required_checklist": list(CHECKLIST), "current_status": state["current_status"], "decision": state["decision"]}


def _authority(service):
    service._manager_only("decide a transaction review")
    if service.session_id:
        raise FoundryError("runtime sessions cannot decide a transaction review")


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise FoundryError(f"{name} requires nonempty text, at most 2000 characters")
    return value.strip()


def _append(service, draft_id, state, decision, reviewer, reason, checklist):
    proof = state["proof"]
    record = _new(service.task, domain=DOMAIN, draft_id=draft_id, decision=decision, reviewer=reviewer, reason=reason,
                  checklist=checklist, saved_by=service.actor, session_id=None, proof=proof, proof_hash=state["proof_hash"],
                  basis_fingerprint=state["basis_fingerprint"], parent_id=(state.get("head") or {}).get("id"),
                  bindings={f"source{i}": key for i, key in enumerate(proof["snapshot_ids"])})
    return service.analysis._write_locked(service._path("transaction_reviews", record["id"]), record)


def save_review(service, spec):
    _authority(service)
    fields = {"draft_id", "basis_fingerprint", "decision", "reviewer", "reason", "checklist"}
    if not isinstance(spec, dict) or set(spec) != fields or spec["decision"] not in {"approved", "rejected"}:
        raise FoundryError("transaction review save requires exact decision fields")
    checklist = spec["checklist"]
    if (not isinstance(checklist, dict) or set(checklist) != set(CHECKLIST)
            or any(type(value) is not bool for value in checklist.values())
            or spec["decision"] == "approved" and not all(checklist.values())):
        raise FoundryError("approval requires every registered checklist field to be true")
    reviewer, reason = _text(spec["reviewer"], "reviewer"), _text(spec["reason"], "reason")
    with exclusive(service.task.lock_path):
        prepared = prepare_review(service, {"draft_id": spec["draft_id"]})
        if spec["basis_fingerprint"] != prepared["basis_fingerprint"]:
            raise FoundryError("transaction review basis conflict; prepare the current draft again")
        if spec["decision"] == "approved" and not prepared["eligibility"]["eligible"]:
            raise FoundryError("transaction review is not eligible for approval")
        state = decision_for_spec(service.analysis, {"draft_id": spec["draft_id"]}, service.allowed)
        record = _append(service, spec["draft_id"], state, spec["decision"], reviewer, reason, checklist)
    refreshed = refresh_draft(service, {"draft_id": spec["draft_id"]})
    return {"schema_version": 1, "review": record, "current_status": spec["decision"], "completion": refreshed["completion"]}


def revoke_review(service, spec):
    _authority(service)
    if not isinstance(spec, dict) or set(spec) != {"review_id", "reason"}:
        raise FoundryError("transaction review revoke requires only review_id and reason")
    reason = _text(spec["reason"], "reason")
    with exclusive(service.task.lock_path):
        record = service._read("transaction_reviews", spec["review_id"])
        draft = _draft(service, record["draft_id"])
        head = _records(service).get(draft["id"])
        if not head or head["id"] != record["id"] or head["decision"] != "approved":
            raise FoundryError("only the latest approved transaction review can be revoked")
        state = {"proof": head["proof"], "proof_hash": head["proof_hash"], "head": head,
                 "basis_fingerprint": _hash({"proof_hash": head["proof_hash"], "head_id": head["id"]})}
        record = _append(service, draft["id"], state, "revoked", head["reviewer"], reason, head["checklist"])
    refreshed = refresh_draft(service, {"draft_id": draft["id"]})
    return {"schema_version": 1, "review": record, "current_status": "revoked", "completion": refreshed["completion"]}


def refresh_draft(service, spec):
    if not isinstance(spec, dict) or set(spec) != {"draft_id"}:
        raise FoundryError("transaction draft refresh requires only draft_id")
    draft = _draft(service, spec["draft_id"])
    if not has_transaction(service.analysis, draft):
        raise FoundryError("draft refresh requires a transaction review draft")
    from foundry.finance_completion import record_completion
    with exclusive(service.analysis._inside(service.analysis.root / "completion.lock")):
        quality = service.validate_explanation({"draft_id": draft["id"]})
        receipt = record_completion(service.analysis, draft, quality, allowed=service.allowed)
    return {**draft, "quality": quality, "explanation_check": quality,
            "completion": service._readable_receipt(receipt), "validation_basis": "current_transaction_review"}


def current_problem(analysis, draft, allowed=None, *, cache=None):
    if not has_transaction(analysis, draft, allowed=allowed, cache=cache):
        return None
    state = decision_for_spec(analysis, draft, allowed)
    return None if state["approved"] else REVIEW_CODE
