"""Independent supplementary provider slots; no credit to the original release suite."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import finance_professional_eval as base  # noqa: E402

SUITE = "professional_supplement_v2"
SEED_FIELDS = {"id", "slot", "attempt", "taskId", "sessionId", "workspace", "question", "inputSha256", "datasetIds", "precondition"}
EMPTY_COLLECTIONS = ("requirements", "runs", "drafts", "completions")


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def runtime_seed(seed):
    if set(seed) - SEED_FIELDS:
        raise ValueError("unexpected private or control fields in runtime seed")
    return {key: value for key, value in seed.items() if key != "precondition"}


def assert_unsolved(state):
    if any(state.get(key) for key in EMPTY_COLLECTIONS):
        raise ValueError("model seed must be unsolved: no requirements, runs, drafts or completions")


def assert_unsolved_files(analysis_root):
    counts = {key: sum(path.is_file() for path in (analysis_root / key).rglob("*")) for key in EMPTY_COLLECTIONS}
    if any(counts.values()):
        raise ValueError("model seed must be unsolved on disk, including hidden records")
    return counts


def observation_identity_problems(row, seed):
    pairs = {"id": "id", "slot": "slot", "attempt": "attempt", "task_id": "taskId",
             "session_id": "sessionId", "input_sha256": "inputSha256"}
    return ["observation_identity_mismatch:" + field for field, target in pairs.items()
            if field not in row or row[field] != seed.get(target)]


def supplement_problems(state, row, contract, seed=None):
    """Extra closed-template guards, in addition to the unchanged original scorer."""
    problems = []
    metrics = set(contract["required_metrics"])
    checks = set(contract["required_model_checks"])
    limits = contract["limits"]
    elapsed = row.get("duration_ms")
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0 or elapsed > limits["timeout_seconds"] * 1000:
        problems.append("runtime_duration_outside_contract")
    if not isinstance(row.get("calls"), list) or len(row["calls"]) > limits["max_tool_turns"]:
        problems.append("runtime_tool_limit_or_evidence_missing")
    current = (state.get("requirements") or [{}])[-1]
    asked = [item.get("metric") for item in current.get("items", [])]
    if len(asked) != len(metrics) or set(asked) != metrics:
        problems.append("all_thirteen_requirements_not_registered")
    draft = row.get("final_draft") or {}
    answered = draft.get("explanation_check", {}).get("requirements", {}).get("items", [])
    if (len(answered) != len(metrics) or {item.get("metric") for item in answered} != metrics
            or any(item.get("status") != "answered" for item in answered)):
        problems.append("all_thirteen_requirements_not_answered")
    by_id = {item.get("id"): item for item in state.get("runs", [])}
    qualifying = 0
    for key in draft.get("run_ids", []):
        run = by_id.get(key) or {}
        result = run.get("result") or {}
        if run.get("engine") != "finance" or result.get("template_id") != contract["template_id"]:
            continue
        failures = []
        scenario = (seed or {}).get("precondition", {}).get("setup", {}).get("scenario") or next(
            (item for item in state.get("scenarios", []) if item.get("id") == result.get("scenario_id")), {})
        inputs = scenario.get("inputs") or {}
        if (scenario.get("id") != result.get("scenario_id") or scenario.get("input_hash") != result.get("input_hash")
                or inputs.get("period") != contract["scope"]["period"]
                or any(inputs.get("scope", {}).get(field) != contract["scope"][field]
                       for field in ("organization", "ledger", "scenario", "currency", "unit"))):
            failures.append("native_scenario_scope_differs_from_frozen_contract")
        if run.get("execution_status") != "succeeded" or run.get("output_hash") != base.canonical_hash(result):
            failures.append("native_output_identity_invalid")
        actual_checks = result.get("model_checks", [])
        if (len(actual_checks) != len(checks) or {item.get("id") for item in actual_checks} != checks
                or any(item.get("status") != "pass" or not item.get("source_rows") for item in actual_checks)):
            failures.append("twelve_distinct_native_checks_not_passed")
        sources = result.get("source_binding_status") or {}
        bindings = sources.get("bindings") or {}
        if (sources.get("all_sources_verified") is not True or len(bindings) != 24
                or any(not item.get("source_rows") for item in bindings.values())):
            failures.append("twenty_four_source_bindings_not_verified")
        if any(any(proof.get(field) != contract["scope"][field] for field in ("ledger", "scenario"))
               for proof in bindings.values()):
            failures.append("native_source_scope_differs_from_frozen_contract")
        boundaries = result.get("model_boundary") or []
        boundary_names = {item.get("name") for item in boundaries}
        if (len(boundaries) != 8 or len(boundary_names) != 8
                or any(not base.exact_decimal(item.get("value"), "0") for item in boundaries)):
            failures.append("eight_explicit_zero_boundaries_missing")
        boundary_ids = {f"boundary.{name}" for name in boundary_names}
        if not boundary_ids <= set(bindings):
            failures.append("boundary_source_identity_missing")
        frozen_boundaries = contract.get("preconditions", {}).get("boundary_names")
        if frozen_boundaries and boundary_ids != set(frozen_boundaries):
            failures.append("boundary_names_differ_from_frozen_contract")
        if seed:
            public_ids = seed["datasetIds"]
            for name, proof in bindings.items():
                alias = "model_boundary" if name.startswith("boundary.") else "template_inputs"
                expected_id = public_ids.get(alias)
                if not expected_id or any(ref.get("dataset_id") != expected_id for ref in proof.get("source_rows", [])):
                    failures.append("native_source_not_from_frozen_public_seed")
                    break
        values = [item for item in result.get("rows", []) if item.get("metric_key") in metrics]
        if len(values) != len(metrics) or {item.get("metric_key") for item in values} != metrics:
            failures.append("native_metric_identity_incomplete")
        for item in values:
            if (any(item.get(field) != contract["scope"][field] for field in ("organization", "period", "currency", "unit"))
                    or not item.get("source_rows") or not boundary_ids <= set(item.get("source_binding_ids", []))):
                failures.append("native_row_scope_or_provenance_invalid")
                break
        cited = set()
        for claim in draft.get("claims", []):
            if claim.get("basis") != "calculation" or claim.get("run_id") != key or claim.get("column") != "value":
                continue
            index = claim.get("row")
            if type(index) is int and 0 <= index < len(result.get("rows", [])):
                item = result["rows"][index]
                if item.get("metric_key") in metrics and base.exact_decimal(claim.get("value"), item.get("value")):
                    cited.add(item["metric_key"])
        if cited != metrics:
            failures.append("all_thirteen_native_metrics_not_cited")
        problems.extend(failures)
        if not failures:
            qualifying += 1
    if not qualifying:
        problems.append("no_complete_cited_native_template_run")
    return sorted(set(problems))


def rollup(planned, attempts):
    expected = {base.slot_key(slot) for slot in planned}
    seen = Counter(base.slot_key(item["slot"]) for item in attempts)
    problems = []
    if len(expected) != len(planned) or set(seen) != expected or any(n != 1 for n in seen.values()):
        problems.append("missing_duplicate_or_foreign_slots")
    for field in ("task_id", "session_id"):
        values = [item.get(field) for item in attempts]
        if not all(values) or len(set(values)) != len(values):
            problems.append("non_independent_" + field)
    if any(item.get("score", {}).get("status") != "passed" for item in attempts):
        problems.append("failed_slot")
    return {"suite_id": SUITE, "status": "failed" if problems else "passed", "errors": problems,
            "planned": len(planned), "attempts": len(attempts),
            "passed": sum(item.get("score", {}).get("status") == "passed" for item in attempts),
            "original_slots_credit": 0, "original_release_accepted": False, "human_signoff": False}


def candidate_identity(path, foundry, plugin):
    value = json.loads(path.read_text())
    root = path.parent.resolve()
    for relative, digest in value["files"].items():
        file = (root / relative).resolve()
        if not file.is_relative_to(root) or base.file_hash(file) != digest:
            raise ValueError("candidate hash mismatch: " + relative)
    if foundry.resolve() != root / "foundry-cli" or plugin.resolve() != root / "dsh-plugin" or ROOT.resolve() != root:
        raise ValueError("run the frozen controller, Foundry and plugin from the same candidate")
    return base.file_hash(path)


def main():
    from tools import finance_supplement_cases as shared
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--foundry", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests/fixtures/finance_supplements/three_statement_v1")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--repeat-index", type=int, choices=(1, 2, 3))
    parser.add_argument("--mode", choices=("prepare", "live"), default="prepare")
    parser.add_argument("--dsh-root", type=Path, default=base.legacy.DEFAULT_DSH_ROOT)
    parser.add_argument("--credentials-home", type=Path, default=base.legacy.DEFAULT_CREDENTIALS_HOME)
    args = parser.parse_args()
    for field in ("candidate_source", "foundry", "plugin", "output", "fixtures", "dsh_root", "credentials_home"):
        setattr(args, field, getattr(args, field).resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    identity = candidate_identity(args.candidate_source, args.foundry, args.plugin)
    if args.fixtures != ROOT / "tests/fixtures/finance_supplements/three_statement_v1":
        raise ValueError("use supplementary fixtures from the same frozen candidate")
    suite = shared.load_suite(args.fixtures)
    contract = suite["contract"]
    args.timeout_seconds, args.max_tool_turns = contract["limits"]["timeout_seconds"], contract["limits"]["max_tool_turns"]
    if (args.timeout_seconds, args.max_tool_turns) != (420, 80):
        raise ValueError("supplement runtime limits changed")
    all_slots = [{"candidate": identity, "suite": SUITE, "family": item["case_id"].split("-")[1],
                  "case": item["case_id"], "variant": "independent_closed_template", "repeat": item["repeat_index"]}
                 for item in contract["planned_slots"]]
    slots = [slot for slot in all_slots if (not args.case_id or slot["case"] in args.case_id)
             and (args.repeat_index is None or slot["repeat"] == args.repeat_index)]
    if not slots or set(args.case_id) - {slot["case"] for slot in slots}:
        raise ValueError("empty or invalid supplementary slot selection")
    args.batch_timeout_seconds = args.timeout_seconds * len(slots) + 240
    cases = {case["case_id"]: case for case in suite["cases"]}
    selections = [{"slot": slot, "public": shared.case_public(cases[slot["case"]]),
                   "oracle": cases[slot["case"]]["oracle"], "fixture_sha256": cases[slot["case"]]["fixture_sha256"]} for slot in slots]
    methods = base.legacy._call(args.foundry, args.output / "var", "method-skills", "--json")
    for selected in selections:
        selected["required_resources"] = base.required_resources(selected, Path(methods["root"]))
    original = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    model = base.model_selection(json.loads(original.read_text())["actual_model_contract"])
    dependencies = base.freeze_dependencies(args.output)
    supplementary_dependencies = {}
    for filename in ("finance_supplement_eval.py", "finance_supplement_cases.py"):
        destination = args.output / "supplementary-dependencies" / filename
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "tools" / filename, destination)
        supplementary_dependencies[str(destination.relative_to(args.output))] = base.file_hash(destination)
    identities = {key: item["sha256"] for key, item in dependencies.items()}
    identities.update(candidate_source_manifest=identity, foundry_entry=base.file_hash(args.foundry),
                      plugin=base.tree_hash(args.plugin, suffixes={".js", ".json", ".yml"}),
                      methods=base.tree_hash(Path(methods["root"])), frozen_manifest=base.file_hash(original),
                      supplementary_manifest=base.file_hash(args.fixtures / "manifest.json"),
                      dsh_pin=base.file_hash(args.dsh_root / "PIN"), dsh_lock=base.file_hash(args.dsh_root / "package-lock.json"))
    if args.mode == "live":
        isolated = base.isolation_probe(args.foundry, args.plugin, args.output)
        if isolated["status"] != "passed":
            raise ValueError("runtime isolation failed")
    seeds = base.seed_public_cases(args.foundry, args.output / "var", args.output, selections)
    for seed, selected in zip(seeds, selections):
        folder = args.output / "state-preconditions" / seed["id"]
        proof = shared.prepare_preconditions(args.foundry, args.output / "var", seed["taskId"], folder,
                                             selected["public"], seed["datasetIds"])
        initial = base.legacy._call(args.foundry, args.output / "var", "analysis-state", task=seed["taskId"])
        assert_unsolved(initial)
        physical_counts = assert_unsolved_files(args.output / "var/tasks" / seed["taskId"] / "analysis")
        initial_path = folder / "controller-initial-state.json"
        write_new(initial_path, initial)
        proof["files"]["controller-initial-state.json"] = base.file_hash(initial_path)
        proof["files"] = {str(folder.relative_to(args.output) / name): digest for name, digest in proof["files"].items()}
        proof["initial_empty_counts"] = {key: len(initial.get(key, [])) for key in EMPTY_COLLECTIONS}
        proof["initial_empty_physical_counts"] = physical_counts
        seed["precondition"] = proof
        seed["question"] += ("\n合成管理端已为此补充测试预建 context " + proof["context_id"] + " 和 scenario " + proof["scenario_id"]
                             + "，并确认该合成档案与八项明示边界。请先核对来源及确认状态，使用该场景完成全部十三项需求登记、原生计算、引用和文稿保存。"
                             + "此授权仅用于公开合成管理预测，不代表真实业务审批。尚无需求、计算运行、草稿或完成回执。")
        runtime_seed(seed)
    write_new(args.output / "initial-seeds.json", seeds)
    manifest = {"suite_id": SUITE, "mode": args.mode, "created_at": datetime.now(timezone.utc).isoformat(),
                "candidate": identity, "planned_slots": all_slots, "selected_slots": slots, "identities": identities,
                "model": model, "limits": contract["limits"], "controller_attempt_retries": 0,
                "evaluator_dependencies": dependencies, "supplementary_dependencies": supplementary_dependencies,
                "seed_sha256": [base.canonical_hash(seed) for seed in seeds],
                "initial_seeds_sha256": base.file_hash(args.output / "initial-seeds.json"),
                "original_slots_credit": 0, "human_signoff": False}
    write_new(args.output / "run-manifest.json", manifest)
    if not all(base.verify_runtime_evidence(args.output, manifest, seed) for seed in seeds):
        raise ValueError("initial state proof mismatch")
    if args.mode == "prepare":
        print(json.dumps({"status": "prepared", "selected": len(slots), "provider_calls": 0, "original_slots_credit": 0}))
        return 0
    result = base.launch_runtime(args, selections, model, methods, seeded=seeds)
    observed = result["observation"]
    observed_by_id = {row["id"]: row for row in observed.get("cases", [])}
    observation_set_valid = (len(observed.get("cases", [])) == len(seeds)
                             and set(observed_by_id) == {seed["id"] for seed in seeds})
    attempts = []
    for seed, selected in zip(seeds, selections):
        row = observed_by_id.get(seed["id"], {})
        try:
            state = base.read_snapshot(args.output, row)
            private = selected["oracle"]
            oracle = {"case_id": selected["slot"]["case"], "numeric_checks": [
                {"metric": metric, "expected": value} for metric, value in private["expected_values"].items()]}
            score = base.score_professional_artifact(state, oracle, row)
            score["supplement_errors"] = supplement_problems(state, row, contract, seed) + observation_identity_problems(row, seed)
            if not observation_set_valid:
                score["supplement_errors"].append("missing_duplicate_or_foreign_observations")
            score["skill_first"] = base.skill_first(row.get("tool_events", []), session=seed["sessionId"],
                                                    resources=selected["required_resources"])
            if score["supplement_errors"] or score["skill_first"]["status"] != "passed":
                score["status"] = "failed"
        except (ValueError, KeyError, TypeError, OSError) as exc:
            score = {"status": "failed", "errors": ["invalid_observation:" + str(exc)]}
        attempt = {"slot": selected["slot"], "attempt": 1, "score": score, "task_id": seed["taskId"],
                   "session_id": seed["sessionId"], "fixture_sha256": selected["fixture_sha256"],
                   "public_sha256": seed["inputSha256"], "seed_sha256": base.canonical_hash(seed),
                   "state_snapshot_sha256": (row.get("state_snapshot") or {}).get("sha256"),
                   "evidence_sha256": base.canonical_hash(row), "duration_ms": row.get("duration_ms"),
                   "tool_calls": len(row.get("calls", [])), "provider_retries": row.get("provider_retries", []),
                   "usage": row.get("usage"), "run_manifest_sha256": base.file_hash(args.output / "run-manifest.json"),
                   "identities": identities, "original_slots_credit": 0, "human_signoff": False}
        base.append_attempt(args.output / "attempts.jsonl", attempt)
        attempts.append(attempt)
    after = candidate_identity(args.candidate_source, args.foundry, args.plugin)
    if after != identity or base.file_hash(args.fixtures / "manifest.json") != identities["supplementary_manifest"]:
        raise ValueError("candidate or suite changed during model execution")
    if not all(base.verify_runtime_evidence(args.output, manifest, seed) for seed in seeds):
        raise ValueError("immutable runtime evidence changed")
    if any(base.file_hash(args.output / name) != digest for name, digest in supplementary_dependencies.items()):
        raise ValueError("supplementary evaluator dependency changed")
    if (base.file_hash(args.dsh_root / "PIN") != identities["dsh_pin"]
            or base.file_hash(args.dsh_root / "package-lock.json") != identities["dsh_lock"]
            or base.tree_hash(Path(methods["root"])) != identities["methods"]):
        raise ValueError("runtime or method resource identity changed")
    summary = rollup(slots, attempts)
    summary.update(selected_subset=len(slots) != len(all_slots), frozen_suite_slots=len(all_slots),
                   candidate_identity_unchanged=True, professional_acceptance="not_real_business_or_human_signoff")
    write_new(args.output / "verification.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
