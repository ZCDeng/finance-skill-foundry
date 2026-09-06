#!/usr/bin/env python3
"""Summarize r4 acceptance metrics from persisted verification output.

This is a postprocess-only reader. It does not rescore cases, invoke the model,
or mutate the live verification directory. Metrics are derived from observed
session records plus persisted analysis drafts/completion receipts/runs.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RECEIPT_TERMINAL_STATUSES = {"complete", "awaiting_input"}
INDEPENDENT_STATUS_PATHS = {
    "numbers": ("checks", "numbers", "status"),
    "requirements_coverage": ("requirements", "coverage", "status"),
    "requirements_provenance": ("requirements", "provenance", "status"),
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_json_dir(path: Path, data_errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for item in sorted(path.glob("*.json")):
        try:
            value = _load_json(item)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            data_errors.append({"path": str(item), "error": str(exc)})
            continue
        rows.append(value)
    return sorted(rows, key=lambda row: (row.get("seq") if isinstance(row.get("seq"), int) else -1, row.get("created_at") or ""))


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[-1] if rows else None


def _dig(value: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    current: Any = value or {}
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _completion_content_matches_draft(completion: dict[str, Any], draft: dict[str, Any]) -> bool:
    return completion.get("draft_id") == draft.get("id") and completion.get("draft_content_hash") == draft.get("content_hash")


def _completion_chain_key(completion: dict[str, Any]) -> tuple[str, str] | None:
    chain_key = completion.get("chain_key")
    if isinstance(chain_key, str) and chain_key:
        return ("chain_key", chain_key)
    fingerprint = completion.get("requirements_semantic_fingerprint")
    requirement_id = completion.get("requirements_id")
    if isinstance(fingerprint, str) and fingerprint and isinstance(requirement_id, str) and requirement_id:
        return ("requirements_semantic_fingerprint", f"{requirement_id}:{fingerprint}")
    return None


def _dedupe_receipts(completions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for row in completions:
        key = row.get("id") or row.get("completion_request_key") or (row.get("draft_id"), row.get("draft_content_hash"), row.get("seq"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _completion_bindings(completions: list[dict[str, Any]], draft: dict[str, Any] | None) -> dict[str, Any]:
    deduped = _dedupe_receipts(completions)
    if not draft:
        return {
            "latest": None,
            "first_in_current_chain": None,
            "chain_strategy": "no_draft",
            "current_chain_receipt_count": 0,
            "prior_chain_receipt_count": 0,
            "receipt_attempt_count": len(deduped),
            "content_hash_mismatch_count": 0,
        }
    draft_bound = [row for row in completions if row.get("draft_id") == draft.get("id")]
    content_matched = [row for row in draft_bound if _completion_content_matches_draft(row, draft)]
    latest = _latest(content_matched)
    if not latest:
        return {
            "latest": None,
            "first_in_current_chain": None,
            "chain_strategy": "draft_bound_content_hash_required",
            "current_chain_receipt_count": 0,
            "prior_chain_receipt_count": len(deduped),
            "receipt_attempt_count": len(deduped),
            "content_hash_mismatch_count": len(draft_bound),
        }
    chain_key = _completion_chain_key(latest)
    if chain_key:
        same_chain = [row for row in completions if _completion_chain_key(row) == chain_key]
        strategy = chain_key[0]
    else:
        same_chain = content_matched
        strategy = "draft_bound_content_hash_required"
    same_chain = sorted(same_chain, key=lambda row: (row.get("seq") if isinstance(row.get("seq"), int) else -1, row.get("created_at") or ""))
    same_ids = {id(row) for row in same_chain}
    prior_chain = [row for row in deduped if id(row) not in same_ids]
    return {
        "latest": latest,
        "first_in_current_chain": same_chain[0] if same_chain else latest,
        "chain_strategy": strategy,
        "current_chain_receipt_count": len(same_chain),
        "prior_chain_receipt_count": len(prior_chain),
        "receipt_attempt_count": len(deduped),
        "content_hash_mismatch_count": len(draft_bound) - len(content_matched),
    }


def _duration_ms(case: dict[str, Any]) -> int | None:
    duration = case.get("duration_ms")
    if isinstance(duration, bool):
        return None
    if isinstance(duration, (int, float)) and duration >= 0:
        return int(duration)
    started = case.get("started_at")
    completed = case.get("completed_at")
    if not isinstance(started, str) or not isinstance(completed, str):
        return None
    try:
        start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    except ValueError:
        return None
    millis = int((end_dt - start_dt).total_seconds() * 1000)
    return millis if millis >= 0 else None


def _latency_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"observed_count": 0}
    ordered = sorted(values)

    def percentile(p: float) -> int:
        if len(ordered) == 1:
            return ordered[0]
        index = round((len(ordered) - 1) * p)
        return ordered[index]

    return {
        "observed_count": len(ordered),
        "min_ms": ordered[0],
        "p50_ms": int(statistics.median(ordered)),
        "p90_ms": percentile(0.9),
        "max_ms": ordered[-1],
        "mean_ms": int(statistics.mean(ordered)),
    }


def _provider_retry_count(case: dict[str, Any]) -> int:
    retries = case.get("provider_retries")
    if isinstance(retries, int) and not isinstance(retries, bool):
        return retries
    events = case.get("events")
    if isinstance(events, list):
        return sum(1 for event in events if isinstance(event, dict) and event.get("type") == "llm/retry")
    return 0


def _tool_errors(case: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for index, call in enumerate(case.get("calls", []) or []):
        if isinstance(call, dict) and call.get("isError"):
            errors.append({"index": index, "tool": call.get("name"), "error": call.get("error")})
    return errors


def _model_hard_errors(case: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    if case.get("error"):
        errors.append({"source": "case", "error": case.get("error")})
    turn_errors = case.get("turn_errors")
    if isinstance(turn_errors, list):
        errors.extend({"source": "turn", "error": err} for err in turn_errors)
    return errors


def _observation_errors(case: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    if case.get("state_error"):
        errors.append({"source": "analysis-state", "error": case.get("state_error")})
    return errors


def _analysis_records(root: Path, task_id: str | None, data_errors: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    if not task_id:
        return {"drafts": [], "completions": [], "runs": [], "requirements": []}
    analysis = root / "var" / "tasks" / task_id / "analysis"
    return {
        "drafts": _load_json_dir(analysis / "drafts", data_errors),
        "completions": _load_json_dir(analysis / "completions", data_errors),
        "runs": _load_json_dir(analysis / "runs", data_errors),
        "requirements": _load_json_dir(analysis / "requirements", data_errors),
    }


def _placeholder_case(case_id: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "task_id": None,
        "session_id": None,
        "observed": False,
        "observed_completed": False,
        "duration_ms": None,
        "tool_call_count": 0,
        "tool_error_count": 0,
        "tool_errors": [],
        "model_hard_errors": [],
        "hard_errors": [],
        "observation_errors": [],
        "provider_retry_count": 0,
        "run_count": 0,
        "draft_count": 0,
        "completion_count": 0,
        "requirement_count": 0,
        "latest_draft_id": None,
        "latest_completion_id": None,
        "latest_completion_status": None,
        "repair_attempts": None,
        "completion_chain_strategy": "unobserved",
        "current_chain_receipt_count": 0,
        "prior_chain_receipt_count": 0,
        "receipt_attempt_count": 0,
        "content_hash_mismatch_count": 0,
        "scope_changed": False,
        "receipt_metrics_uncertain": False,
        "receipt_reported_first_attempt_complete": False,
        "receipt_reported_within_two_repairs_complete": False,
        "independent_statuses": {},
        "independent_scorer_verified": False,
        "scoring_status": None,
        "scoring_error": None,
        "data_errors": [],
    }


def _case_report(root: Path, case: dict[str, Any], scoring_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = str(case.get("id") or "")
    task_id = case.get("task_id") or case.get("taskId")
    task_id = task_id if isinstance(task_id, str) else None
    data_errors: list[dict[str, str]] = []
    records = _analysis_records(root, task_id, data_errors)
    draft = _latest(records["drafts"])
    completion_info = _completion_bindings(records["completions"], draft)
    completion = completion_info["latest"]
    first_completion = completion_info["first_in_current_chain"]
    quality = draft.get("explanation_check", draft.get("quality")) if isinstance(draft, dict) else None
    if not isinstance(quality, dict):
        quality = None
    completion_checks = completion.get("checks") if isinstance(completion, dict) else None
    if not isinstance(completion_checks, dict):
        completion_checks = None

    completion_status = completion.get("status") if isinstance(completion, dict) else None
    repair_attempts = completion.get("repair_attempts") if isinstance(completion, dict) else None
    first_repair_attempts = first_completion.get("repair_attempts") if isinstance(first_completion, dict) else None
    if isinstance(repair_attempts, bool) or not isinstance(repair_attempts, int):
        repair_attempts = None
    if isinstance(first_repair_attempts, bool) or not isinstance(first_repair_attempts, int):
        first_repair_attempts = None
    model_hard_errors = _model_hard_errors(case)
    observation_errors = _observation_errors(case)
    observed_completed = bool(case.get("completed")) and not model_hard_errors
    receipt_terminal = completion_status in RECEIPT_TERMINAL_STATUSES
    first_status = first_completion.get("status") if isinstance(first_completion, dict) else None
    receipt_attempt_count = completion_info["receipt_attempt_count"]
    first_is_current_attempt = completion_info["prior_chain_receipt_count"] == 0 and receipt_attempt_count == 1
    receipt_metrics_uncertain = bool(data_errors)
    first_attempt = (
        not receipt_metrics_uncertain
        and observed_completed
        and first_is_current_attempt
        and first_status in RECEIPT_TERMINAL_STATUSES
        and first_repair_attempts == 0
    )
    within_two_repairs = (
        not receipt_metrics_uncertain
        and observed_completed
        and receipt_terminal
        and isinstance(repair_attempts, int)
        and repair_attempts <= 2
        and receipt_attempt_count <= 3
    )
    scope_changed = any(bool(_dig(d, ("explanation_check", "requirements", "scope_changed")) or _dig(d, ("quality", "requirements", "scope_changed"))) for d in records["drafts"])
    status_details = {
        name: _dig(quality, path)
        for name, path in INDEPENDENT_STATUS_PATHS.items()
    }
    status_details["completion_status"] = completion_status
    status_details["completion_response_status"] = completion.get("response_status") if isinstance(completion, dict) else None
    status_details["completion_stop_reason"] = completion.get("stop_reason") if isinstance(completion, dict) else None
    status_details["completion_original_requirements_completed"] = completion.get("original_requirements_completed") if isinstance(completion, dict) else None
    if completion_checks:
        status_details["receipt_numbers"] = _dig(completion, ("checks", "numbers", "status"))
        status_details["receipt_coverage"] = _dig(completion, ("checks", "coverage", "status"))
        status_details["receipt_provenance"] = _dig(completion, ("checks", "provenance", "status"))

    scoring = scoring_by_id.get(case_id) or {}
    scoring_status = scoring.get("status")
    return {
        "id": case_id,
        "task_id": task_id,
        "session_id": case.get("session_id") or case.get("sessionId"),
        "observed": True,
        "observed_completed": observed_completed,
        "duration_ms": _duration_ms(case),
        "tool_call_count": len(case.get("calls", []) or []),
        "tool_error_count": len(_tool_errors(case)),
        "tool_errors": _tool_errors(case),
        "model_hard_errors": model_hard_errors,
        "hard_errors": model_hard_errors,
        "observation_errors": observation_errors,
        "provider_retry_count": _provider_retry_count(case),
        "run_count": len(records["runs"]),
        "draft_count": len(records["drafts"]),
        "completion_count": len(records["completions"]),
        "requirement_count": len(records["requirements"]),
        "latest_draft_id": draft.get("id") if isinstance(draft, dict) else None,
        "latest_completion_id": completion.get("id") if isinstance(completion, dict) else None,
        "latest_completion_status": completion_status,
        "repair_attempts": repair_attempts,
        "completion_chain_strategy": completion_info["chain_strategy"],
        "current_chain_receipt_count": completion_info["current_chain_receipt_count"],
        "prior_chain_receipt_count": completion_info["prior_chain_receipt_count"],
        "receipt_attempt_count": receipt_attempt_count,
        "content_hash_mismatch_count": completion_info["content_hash_mismatch_count"],
        "scope_changed": scope_changed,
        "receipt_metrics_uncertain": receipt_metrics_uncertain,
        "receipt_reported_first_attempt_complete": first_attempt,
        "receipt_reported_within_two_repairs_complete": within_two_repairs,
        "independent_statuses": status_details,
        "independent_scorer_verified": scoring_status == "passed",
        "scoring_status": scoring_status,
        "scoring_error": scoring.get("error"),
        "data_errors": data_errors,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _status_counts(cases: list[dict[str, Any]], status_key: str) -> dict[str, int]:
    counter = Counter()
    for case in cases:
        status = case.get("independent_statuses", {}).get(status_key)
        counter[str(status) if status is not None else "missing"] += 1
    return dict(sorted(counter.items()))


def _selected_case_ids(root: Path, session_cases: list[dict[str, Any]]) -> list[str]:
    summary_path = root / "fixture-summary.json"
    if summary_path.exists():
        summary = _load_json(summary_path)
        selected = summary.get("selected_cases")
        if isinstance(selected, list) and all(isinstance(item, str) and item for item in selected):
            return selected
    return [str(case.get("id") or "") for case in session_cases if isinstance(case, dict) and case.get("id")]


def build_report(root: Path) -> dict[str, Any]:
    session_path = root / "session.json"
    if not session_path.exists():
        raise FileNotFoundError(f"missing session.json: {session_path}")
    session = _load_json(session_path)
    verification = _load_json(root / "verification.json") if (root / "verification.json").exists() else {}
    scored = {row.get("id"): row for row in verification.get("cases", []) or [] if isinstance(row, dict)}
    scored.update({row.get("id"): row for row in verification.get("failures", []) or [] if isinstance(row, dict)})
    session_cases = [case for case in session.get("cases", []) or [] if isinstance(case, dict)]
    selected_ids = _selected_case_ids(root, session_cases)
    observed_by_id = {str(case.get("id") or ""): case for case in session_cases if case.get("id")}
    cases = []
    for case_id in selected_ids:
        observed = observed_by_id.get(case_id)
        cases.append(_case_report(root, observed, scored) if observed else _placeholder_case(case_id))
    for case_id, observed in observed_by_id.items():
        if case_id not in selected_ids:
            cases.append(_case_report(root, observed, scored))
    denominator = len(selected_ids) if selected_ids else len(cases)
    seen_count = sum(1 for case in cases if case["observed"])
    provisional = session.get("status") != "completed" or seen_count < denominator
    first_attempt_ids = [case["id"] for case in cases if case["receipt_reported_first_attempt_complete"]]
    within_two_ids = [case["id"] for case in cases if case["receipt_reported_within_two_repairs_complete"]]
    scorer_verified_ids = [case["id"] for case in cases if case["independent_scorer_verified"]]
    tool_error_cases = [case for case in cases if case["tool_error_count"]]
    hard_error_cases = [case for case in cases if case["model_hard_errors"]]
    observation_error_cases = [case for case in cases if case["observation_errors"]]
    provider_retry_cases = [case for case in cases if case["provider_retry_count"]]
    data_error_cases = [case for case in cases if case["data_errors"]]
    durations = [case["duration_ms"] for case in cases if isinstance(case.get("duration_ms"), int)]
    return {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_dir": str(root),
        "session_status": session.get("status"),
        "provisional": provisional,
        "model": session.get("model"),
        "verification_status": verification.get("status"),
        "scoring_contract": verification.get("scoring_contract") or verification.get("current_scoring_contract"),
        "case_count": denominator,
        "seen_count": seen_count,
        "unobserved_count": max(denominator - seen_count, 0),
        "metrics": {
            "receipt_reported_first_attempt_completion": {
                "completed": len(first_attempt_ids),
                "denominator": denominator,
                "rate": _rate(len(first_attempt_ids), denominator),
                "case_ids": first_attempt_ids,
                "basis": "first completion receipt in the current semantic chain, requiring no prior completion chain, observed completion, and no hard error",
            },
            "receipt_reported_within_two_repairs_completion": {
                "completed": len(within_two_ids),
                "denominator": denominator,
                "rate": _rate(len(within_two_ids), denominator),
                "case_ids": within_two_ids,
                "basis": "latest draft-bound receipt in the current semantic chain, requiring observed completion and no hard error",
            },
            "independent_scorer_verified_completion": {
                "completed": len(scorer_verified_ids),
                "denominator": denominator,
                "rate": _rate(len(scorer_verified_ids), denominator),
                "case_ids": scorer_verified_ids,
                "basis": "existing verification.json case status passed; no rescoring is performed here",
            },
            "latency_ms": _latency_summary(durations),
            "tool_errors": {
                "case_count": len(tool_error_cases),
                "total": sum(case["tool_error_count"] for case in cases),
                "by_tool": dict(sorted(Counter(error["tool"] for case in tool_error_cases for error in case["tool_errors"]).items())),
                "case_ids": [case["id"] for case in tool_error_cases],
            },
            "model_hard_errors": {
                "case_count": len(hard_error_cases),
                "case_ids": [case["id"] for case in hard_error_cases],
            },
            "hard_errors": {
                "case_count": len(hard_error_cases),
                "case_ids": [case["id"] for case in hard_error_cases],
                "note": "Backward-compatible alias for model_hard_errors; observation sampling errors are reported separately.",
            },
            "observation_errors": {
                "case_count": len(observation_error_cases),
                "case_ids": [case["id"] for case in observation_error_cases],
            },
            "model_retries": {
                "case_count": len(provider_retry_cases),
                "total": sum(case["provider_retry_count"] for case in cases),
                "case_ids": [case["id"] for case in provider_retry_cases],
            },
            "data_errors": {
                "case_count": len(data_error_cases),
                "total": sum(len(case["data_errors"]) for case in cases),
                "case_ids": [case["id"] for case in data_error_cases],
            },
            "independent_status_counts": {
                "numbers": _status_counts(cases, "numbers"),
                "requirements_coverage": _status_counts(cases, "requirements_coverage"),
                "requirements_provenance": _status_counts(cases, "requirements_provenance"),
                "completion_status": _status_counts(cases, "completion_status"),
                "receipt_numbers": _status_counts(cases, "receipt_numbers"),
                "receipt_coverage": _status_counts(cases, "receipt_coverage"),
                "receipt_provenance": _status_counts(cases, "receipt_provenance"),
            },
            "manual_calibration": {
                "status": "not_evaluated",
                "case_count": 0,
                "note": "Human financial-manager calibration is intentionally separate from receipt-reported and scorer-verified r4 acceptance metrics.",
            },
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate postprocess r4 acceptance metrics from verification output.")
    parser.add_argument("verification_dir", type=Path, help="Directory containing session.json and optional verification.json")
    parser.add_argument("--output", type=Path, help="Optional JSON output path. Stdout is always emitted when omitted.")
    args = parser.parse_args()
    report = build_report(args.verification_dir)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
