"""Source-verified undefined fractions, separate from numerical requirement completion."""
from decimal import localcontext
from contextvars import ContextVar
import re

from foundry.analysis import _hash
from foundry.errors import FoundryError


PROOF_VERSION = 1
RATE_LABELS = {"collection_rate_current": "本年账单收缴率", "collection_rate_total": "综合收缴率"}
_PREPARING_UNDEFINED = ContextVar("preparing_verified_undefined_draft", default=False)


def prepare_undefined_draft(analysis, runs, *, allowed=None):
    """Offer the existing narrow limitation text after the ordinary source proof.

    This is an authoring aid, never a numerical answer or completion grant. A
    save revalidates the same proof and retains the unresolved numerical items.
    """
    from foundry.collection_metrics import collection_undefined_disclosure
    from foundry.finance_native_drafts import _current_run
    from foundry.finance_requirements import check_requirements

    if (_PREPARING_UNDEFINED.get() or len(runs) != 1
            or (runs[0].get("result") or {}).get("scenario_kind") != "collection_health"
            or (runs[0].get("result") or {}).get("rows")
            or not (runs[0].get("result") or {}).get("non_numeric_outcomes")):
        return None
    guard = _PREPARING_UNDEFINED.set(True)
    try:
        _, run, requirement, _, _, _ = _current_run(analysis, runs, allowed)
        metrics = {(item.get("dimensions") or {}).get("metric_key") for item in requirement["items"]}
        if not metrics or not metrics <= RATE_LABELS.keys():
            return None
        template = {"title": "收缴率未定义与来源限制",
                    "body": collection_undefined_disclosure(metrics)
                            + "原数值要求未完成；仍待专业复核；不作为审定或过账授权。",
                    "requirements_id": requirement["id"], "run_ids": [run["id"]],
                    "claims": [], "fact_ids": []}
        checked = check_requirements(analysis, template, _allowed=allowed)
        # This known server sentence contains no numeric claim. The same
        # source-replay proof used on saves must cover every original item.
        quality = {"checks": {"numbers": {"status": "pass"}}, "issues": checked.get("issues", [])}
        proofs = verified_undefined_outcomes(
            analysis, template, quality, requirement, checked, {run["id"]: run},
            semantic_fingerprint=analysis.fingerprint_in_view(requirement, allowed),
            stale_runs=[], allowed=allowed)
        return template if proofs else None
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        return None
    finally:
        _PREPARING_UNDEFINED.reset(guard)


def _undefined_prose_supported(body, metric_keys):
    """Accept only server-authored disclosure sentences and an enumerated safety vocabulary.

    A NONNUMERIC proof does not authorise a natural-language truth judgement.
    Whole clauses must match; no modal, negation or prohibition can consume an
    arbitrary suffix. Unknown wording retains the ordinary repair/review path.
    """
    from foundry.collection_metrics import collection_undefined_disclosure

    def clauses(text):
        return [re.sub(r"\s+", "", clause).casefold() for clause in
                re.split(r"[。.!！？?;；,，\n]+", text) if clause.strip()]

    canonical = clauses(collection_undefined_disclosure(metric_keys))
    # These are complete safety statements, not prefix patterns or truth-checking rules.
    safety_sentences = (
        "原数值要求未完成", "仍待专业复核", "不作为审定或过账授权", "输入构成已提供",
        "不能将本年账单收缴率视为零", "本年账单收缴率不应被视为零",
        "Do not report the current collection rate as zero",
        "The total collection rate must not be reported as one hundred percent",
        "所有检查尚未全部通过", "Not all checks have passed", "The draft has not been approved",
        "假设本年账单收缴率为零", "Assuming the current collection rate were zero",
    )
    allowed = {clause for sentence in safety_sentences for clause in clauses(sentence)}
    actual = clauses(body)
    if not actual or any(clause not in allowed and clause not in canonical for clause in actual):
        return False
    # Preserve the canonical factual statement's order and exactly one occurrence of each clause.
    factual = [clause for clause in actual if clause in canonical]
    return factual == canonical


def _replayed_native_result(analysis, run, allowed):
    """Re-read immutable inputs and run the registered calculator; a diagnostic alone proves nothing."""
    from foundry.finance_scenario_service import calculate_scenario
    from foundry.finance_service import FinanceStore

    if (run.get("engine") != "finance" or run.get("execution_status") != "succeeded"
            or run.get("deterministic") is not True
            or (run.get("result") or {}).get("scenario_kind") != "collection_health"
            or not run.get("bindings")
            or (allowed is not None and not set(run["bindings"].values()) <= set(allowed))):
        return None
    service = FinanceStore(analysis.task)
    scenario = service._read("scenarios", run["result"]["scenario_id"])
    context = service._read("contexts", run["finance_context_id"])
    revision = analysis.get_analysis(run["analysis_id"])
    if (scenario.get("kind") != "collection_health" or scenario.get("context_id") != context["id"]
            or context["bindings"] != run["bindings"] or context.get("scopes") != run.get("finance_scope")
            or revision.get("operation") != "scenario"
            or (revision.get("finance_spec") or {}).get("scenario_id") != scenario["id"]
            or revision.get("finance_context_id") != context["id"]
            or run.get("code_hash") != _hash({"operation": "scenario", "spec": revision["finance_spec"],
                                             "context": context})):
        return None
    datasets = {alias: analysis.read_dataset(dataset_id) for alias, dataset_id in context["bindings"].items()}
    if (run.get("source_hashes") != {alias: data["source_hash"] for alias, data in datasets.items()}
            or run.get("input_hashes") != {alias: data["data_hash"] for alias, data in datasets.items()}):
        return None
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        calculated = calculate_scenario(scenario, context, datasets)
    # The finance runner stores these type aliases and table metadata around the pure calculation.
    types = {"string": "VARCHAR", "decimal": "DECIMAL", "integer": "BIGINT", "date": "DATE"}
    columns = [dict(column) if isinstance(column, dict) else {"name": column, "type": "VARCHAR"}
               for column in calculated["columns"]]
    for column in columns:
        column["type"] = types.get(column.get("type"), column.get("type", "VARCHAR"))
    result = {**calculated, "columns": columns, "row_count": len(calculated["rows"]), "truncated": False}
    if result != run.get("result") or _hash(result) != run.get("output_hash"):
        return None
    if any(item.get("severity") == "error" and item.get("code") != "empty_result"
           for item in result.get("diagnostics", [])):
        return None
    return result


def verified_undefined_outcomes(analysis, draft, quality, requirement, requirements, runs, *,
                                semantic_fingerprint, stale_runs, allowed=None):
    """Return proofs only when every remaining numerical obligation is a proved undefined rate.

    This never changes a requirement, source qualification, numerical fact or quality result.
    Ordinary unresolved items, unverifiable claims and scope changes keep their repair path.
    """
    from foundry.finance_requirements import (
        _bindings_match, _dimensions_match, _requested_grain_matches, _requested_grains,
        _requirement_scope_matches, _row_grain,
    )
    from foundry.finance_professional import cell_evidence_eligibility

    remaining = {item["id"] for item in requirements.get("items", []) if item.get("status") != "answered"}
    if (not requirement or not semantic_fingerprint or stale_runs or not remaining
            or requirements.get("scope_changed")
            or quality.get("checks", {}).get("numbers", {}).get("status") != "pass"
            or any(issue.get("code") not in {"requirement_unanswered", "requested_source_missing"}
                   or issue.get("requirement_item_id") not in remaining for issue in quality.get("issues", []))):
        return []
    body = draft.get("body", "")
    # This first release supports an entirely undefined registered rate set. A mixed
    # numeric/undefined report needs separate per-metric prose qualification.
    registered = {item["id"] for item in (requirement or {}).get("items", [])}
    if remaining != registered:
        return []
    candidates = []
    for run in runs.values():
        # The narrow terminal outcome must not hide a source problem on an already answered sibling.
        try:
            for alias, dataset_id in (run.get("bindings") or {}).items():
                if allowed is not None and dataset_id not in allowed:
                    return []
                dataset = analysis.read_dataset(dataset_id)
                if ((run.get("source_hashes") or {}).get(alias) != dataset["source_hash"]
                        or (run.get("input_hashes") or {}).get(alias) != dataset["data_hash"]):
                    return []
        except (FoundryError, OSError, KeyError, TypeError, ValueError):
            return []
        if (run.get("requirements_id") != requirement["id"]
                or run.get("requirements_semantic_fingerprint") != semantic_fingerprint
                or run.get("seq", -1) <= requirement.get("seq", 0)
                or not _bindings_match(requirement.get("bindings"), run.get("bindings"))):
            continue
        try:
            result = _replayed_native_result(analysis, run, allowed)
            for outcome in (result or {}).get("non_numeric_outcomes", []):
                if (outcome.get("metric_key") not in RATE_LABELS or outcome.get("manual_inputs")
                        or outcome.get("kind") != "NONNUMERIC" or outcome.get("outcome") != "undefined"
                        or outcome.get("denominator") != "0" or outcome.get("value") is not None
                        or not outcome.get("component_sources")
                        or not all(outcome["component_sources"].values())
                        or not cell_evidence_eligibility(run, outcome, "value", analysis=analysis)["counts_as_amount_evidence"]):
                    continue
                candidates.append((run, outcome))
        except (FoundryError, OSError, KeyError, TypeError, ValueError):
            continue
    proofs = []
    for item in requirement.get("items", []):
        if item["id"] not in remaining:
            continue
        metric = (item.get("dimensions") or {}).get("metric_key")
        if item.get("metric") != "ratio" or metric not in RATE_LABELS or RATE_LABELS[metric] not in body:
            return []
        matches = []
        for run, outcome in candidates:
            row = {**outcome.get("source_scope", {}), **outcome}
            if (outcome["metric_key"] == metric and _dimensions_match(item, row, run)
                    and _requested_grain_matches(item, run, row)
                    and _requirement_scope_matches(run, row, item, requirement)):
                matches.append((run, outcome, row))
        grains = _requested_grains(item)
        if not matches or (grains is not None and not set(grains) <= {
                _row_grain(item, run, row) for run, _, row in matches}):
            return []
        for run, outcome, _ in matches:
            fields = {**outcome, "proof_version": PROOF_VERSION,
                      "verification_method": "native_collection_replay",
                      "requirement_item_id": item["id"], "requirements_id": requirement["id"],
                      "requirements_semantic_fingerprint": semantic_fingerprint,
                      "run_id": run["id"], "output_hash": run["output_hash"],
                      "input_hashes": run["input_hashes"], "source_hashes": run["source_hashes"],
                      "finance_scope": run.get("finance_scope", {})}
            proofs.append({**fields, "proof_hash": _hash(fields)})
    return proofs if _undefined_prose_supported(body, {proof['metric_key'] for proof in proofs}) else []


def undefined_receipt_view(analysis, receipt, allowed=None):
    """Revalidate a nonnumeric receipt on reads; preserve the historical record unchanged."""
    from foundry.finance_completion import assess_completion

    if receipt.get("stop_reason") != "verified_undefined_result":
        return receipt
    try:
        if (receipt.get("status") != "needs_review" or receipt.get("response_status") != "ended_with_limitations"
                or receipt.get("original_requirements_completed") is not False
                or receipt.get("repair_allowed") is not False):
            raise FoundryError("undefined result is not numerical completion")
        draft = analysis.get_draft(receipt["draft_id"])
        assessed = assess_completion(analysis, draft, draft["explanation_check"], allowed=allowed)
        proofs = assessed["verified_non_numeric_outcomes"]
        if (proofs and proofs == receipt.get("verified_non_numeric_outcomes")
                and assessed["run_hashes"] == receipt.get("run_hashes")
                and assessed["semantic_fingerprint"] == receipt.get("requirements_semantic_fingerprint")
                and draft.get("content_hash") == receipt.get("draft_content_hash")):
            return receipt
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        pass
    return {**{key: value for key, value in receipt.items() if key not in
               {"_integrity_hash", "verified_non_numeric_outcomes"}},
            "historical_status": receipt.get("status"), "status": "needs_review",
            "response_status": "needs_review", "original_requirements_completed": False,
            "repair_allowed": False, "stop_reason": "non_numeric_result_unverified",
            "actions": [{"code": "non_numeric_result_unverified", "message": "未定义结果的当前来源与计算证明无法核验，请复核。"}]}
