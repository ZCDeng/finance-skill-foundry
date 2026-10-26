"""Aggregate professional release evidence without changing the legacy R4 verdict.

This is a separate gate: a workflow pass is not professional acceptance. Missing
reviews, unopened blind custody, incomplete deterministic checks, or missing
slots block acceptance even when every observed model answer looks correct.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import math
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("finance_professional_eval", Path(__file__).with_name("finance_professional_eval.py"))
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def review_check(record: dict, *, output_sha256: str, critical: list[str]) -> bool:
    scores = record.get("scores", {})
    if record.get("reviewer_type") != "human" or not record.get("reviewer_id") or not record.get("reviewed_at"):
        return False
    if record.get("output_sha256") != output_sha256 or set(scores) != set(evaluation.DIMENSIONS):
        return False
    if any(type(value) is not int or value not in {0, 1, 2} for value in scores.values()):
        return False
    return (all(scores[d] == 2 for d in critical) and min(scores.values()) >= 1
            and sum(v == 2 for v in scores.values()) / len(scores) >= 0.75)


def aggregate(manifest: dict, attempts: list[dict], *, reviews: list[dict] | None = None,
              calibration: dict | None = None, deterministic: dict | None = None, unseen: dict | None = None,
              run_manifests: list[dict] | None = None, manifest_sha256: str | None = None,
              verified_evidence: set[str] | None = None) -> dict:
    planned = [evaluation.normalized_slot(row) for row in manifest["planned_slots"]]
    fixture_hashes = {evaluation.slot_key(evaluation.normalized_slot(row)): row.get("fixture_sha256") for row in manifest["planned_slots"]}
    covered = evaluation.coverage(planned, attempts, fixture_hashes=fixture_hashes)
    blockers = []
    if covered["status"] != "passed":
        blockers.append("planned_slot_coverage_or_attempt_identity")
    # A successful retry never erases its preceding attempt from this denominator.
    completed = sum(a.get("legal_workflow_completed") is True for a in attempts)
    completion_rate = completed / len(attempts) if attempts else None
    if completion_rate is None or completion_rate < 0.95:
        blockers.append("all_attempt_completion_below_95_percent")
    runs = {evaluation.canonical_hash(r): r for r in run_manifests or []}
    identity_errors = []
    for attempt in attempts:
        run = runs.get(attempt.get("run_manifest_sha256"))
        identities = attempt.get("identities", {})
        required = {"foundry_entry", "plugin", "dsh_lock", "dsh_pin", "methods", "frozen_manifest", *evaluation.DEPENDENCY_FILES}
        if (not run or run.get("candidate") != attempt["slot"]["candidate"]
                or run.get("candidate") != manifest.get("candidate_id")
                or run.get("model") != evaluation.model_selection(manifest.get("actual_model_contract", {}))
                or run.get("identities") != identities or not all(identities.get(k) for k in required)
                or not manifest_sha256 or identities.get("frozen_manifest") != manifest_sha256
                or not (identities.get("candidate_source_manifest") or identities.get("foundry_source"))
                or attempt["slot"] not in run.get("selected_slots", [])
                or set(run.get("evaluator_dependencies", {})) != set(evaluation.DEPENDENCY_FILES)
                or any(identities.get(k) != v.get("sha256") for k, v in run.get("evaluator_dependencies", {}).items())
                or not attempt.get("seed_sha256") or attempt["seed_sha256"] not in run.get("seed_sha256", [])
                or not run.get("initial_seeds_sha256")
                or not attempt.get("state_snapshot_sha256") or not attempt.get("evidence_sha256")):
            identity_errors.append(attempt["slot"])
    if identity_errors or not attempts:
        blockers.append("candidate_runtime_scorer_snapshot_identity_unverified")
    if len({evaluation.canonical_hash(a.get("identities", {})) for a in attempts}) > 1:
        blockers.append("mixed_candidate_runtime_or_scorer_identity")
    if any(evaluation.canonical_hash(a) not in (verified_evidence or set()) for a in attempts):
        blockers.append("raw_observation_and_state_files_unverified")
    if any(a.get("critical_error_count") is None for a in attempts):
        blockers.append("critical_error_audit_incomplete")
    critical_errors = sum(a.get("critical_error_count") or 0 for a in attempts)
    if critical_errors:
        blockers.append("critical_errors")
    final = {}
    for attempt in attempts:
        final[evaluation.slot_key(attempt["slot"])] = attempt
    passed = Counter()
    variants = defaultdict(list)
    for key, attempt in final.items():
        success = attempt.get("score", {}).get("status") == "passed"
        if success:
            passed[attempt["slot"]["suite"]] += 1
        variants[(attempt["slot"]["suite"], attempt["slot"]["family"], attempt["slot"]["case"], attempt["slot"]["variant"])].append(success)
    thresholds = {"main": 27, "holdout": 8, "historical_blind": 18}
    for suite, minimum in thresholds.items():
        if passed[suite] < minimum:
            blockers.append("suite_threshold:" + suite)
    professional_count = sum(s["suite"] == "professional_development" for s in planned)
    if passed["professional_development"] < math.ceil(0.90 * professional_count):
        blockers.append("professional_quality_below_90_percent")
    high_risk = {"E01", "E03", "E08", "E10", "E12", "E18", "E19", "E22", "E23", "E26", "E27", "E31"}
    for key in {(s["suite"], s["family"], s["case"], s["variant"]) for s in planned if s["suite"] == "professional_development"}:
        minimum = 3 if key[1] in high_risk else 2
        if sum(variants[key]) < minimum:
            blockers.append("variant_repeat_threshold:" + key[2])
    if not deterministic or deterministic.get("status") != "passed" or deterministic.get("failed") != 0 or not deterministic.get("executed") or not deterministic.get("evidence_sha256"):
        blockers.append("deterministic_checks_not_verified")
    elif set(deterministic.get("mutants_rejected", [])) != {f"M{i:02d}" for i in range(1, 12)} or deterministic.get("legitimate_controls_passed") is not True:
        blockers.append("scorer_mutants_or_legitimate_controls_incomplete")
    elif deterministic.get("mutant_scope") != "live_artifact_pipeline":
        blockers.append("standalone_scorer_mutants_do_not_prove_live_pipeline")
    calibrated = (calibration and calibration.get("status") == "passed" and calibration.get("output_count", 0) >= 10
                  and calibration.get("reviewer_type") == "human" and calibration.get("evidence_sha256"))
    if not calibrated:
        blockers.append("human_calibration_absent")
    review_rows = reviews or []
    review_missing = []
    critical_dimensions = ["numeric_basis", "recognition_basis", "scope_period", "authority_completion"]
    for key, attempt in final.items():
        minimum = 2 if attempt["slot"]["family"] in high_risk else 1
        matching = [r for r in review_rows if r.get("slot") == attempt["slot"] and r.get("attempt") == attempt.get("attempt")]
        valid = [r for r in matching if review_check(r, output_sha256=attempt.get("evidence_sha256", ""), critical=critical_dimensions)]
        if len({r["reviewer_id"] for r in valid}) < minimum:
            review_missing.append(attempt["slot"])
    if review_missing or not attempts:
        blockers.append("human_reviews_missing_or_below_anchors")
    unseen_ready = (unseen and unseen.get("independent_custodian") and unseen.get("knowledge_status") == "unseen_before_run"
                    and unseen.get("planned") == 20 and unseen.get("observed") == 20 and unseen.get("passed", 0) >= 18
                    and unseen.get("critical_errors") == 0 and unseen.get("double_reviewed") == 20
                    and unseen.get("evidence_sha256"))
    if not unseen_ready:
        blockers.append("independent_unseen20_not_accepted")
    return {"contract": "finance-professional-release-v1", "status": "accepted" if not blockers else "not_accepted",
            "legacy_r4_status_unchanged": True, "coverage": covered, "attempt_count": len(attempts),
            "completed_attempts": completed, "all_attempt_completion_rate": completion_rate,
            "passed_by_suite": dict(passed), "professional_required_passes": math.ceil(0.90 * professional_count),
            "critical_error_count": critical_errors, "human_review_missing_slots": review_missing,
            "identity_error_slots": identity_errors,
            "blockers": blockers, "unknown_usage_is_zero": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempts", action="append", type=Path, default=[])
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--deterministic", type=Path)
    parser.add_argument("--unseen", type=Path)
    parser.add_argument("--run-manifest", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def read(path):
        return json.loads(path.read_text()) if path else None
    attempts, verified_evidence = [], set()
    for path in args.attempts:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        attempts.extend(rows)
        try:
            session = read(path.parent / "session.json")
            run_manifest = read(path.parent / "run-manifest.json")
            seeds = read(path.parent / "initial-seeds.json")
            if evaluation.file_hash(path.parent / "initial-seeds.json") != run_manifest.get("initial_seeds_sha256"):
                raise ValueError("initial seed file hash mismatch")
            for attempt in rows:
                observed = next(r for r in session.get("cases", []) if r.get("slot") == attempt["slot"] and r.get("attempt", 1) == attempt["attempt"])
                seed = next(r for r in seeds if r.get("slot") == attempt["slot"] and r.get("attempt") == attempt["attempt"])
                evaluation.read_snapshot(path.parent, observed)
                if (evaluation.canonical_hash(observed) == attempt.get("evidence_sha256")
                        and evaluation.canonical_hash(seed) == attempt.get("seed_sha256")
                        and (evaluation.canonical_hash(seed["precondition"]) if seed.get("precondition") else None) == attempt.get("precondition_sha256")
                        and evaluation.verify_runtime_evidence(path.parent, run_manifest, seed)
                        and observed["state_snapshot"]["sha256"] == attempt.get("state_snapshot_sha256")
                        and evaluation.canonical_hash(run_manifest) == attempt.get("run_manifest_sha256")):
                    verified_evidence.add(evaluation.canonical_hash(attempt))
        except (OSError, ValueError, KeyError, StopIteration):
            pass  # Explicit unverified evidence blocker below; never silently accepted.
    result = aggregate(read(args.manifest), attempts, reviews=read(args.reviews), calibration=read(args.calibration),
                       deterministic=read(args.deterministic), unseen=read(args.unseen), run_manifests=[read(p) for p in args.run_manifest],
                       manifest_sha256=evaluation.file_hash(args.manifest), verified_evidence=verified_evidence)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": result["status"], "planned": result["coverage"]["planned"], "attempts": len(attempts), "blockers": len(result["blockers"])}, ensure_ascii=False))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
