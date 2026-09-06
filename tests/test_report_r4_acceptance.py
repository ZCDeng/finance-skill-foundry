from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("report_r4_acceptance", REPO / "tools/report_r4_acceptance.py")
reporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(reporter)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_analysis(
    root: Path,
    task_id: str,
    *,
    completion_status: str | None,
    repair_attempts: int | None = 0,
    draft_hash: str | None = None,
    completion_hash: str | None = None,
    chain_key: str = "chain-a",
    prior_chain: bool = False,
    prior_chain_count: int = 1,
    scope_changed: bool = False,
    hard_quality: bool = False,
) -> None:
    analysis = root / "var" / "tasks" / task_id / "analysis"
    content_hash = draft_hash or f"hash-{task_id}"
    draft = {
        "id": f"draft-{task_id}",
        "seq": 10,
        "content_hash": content_hash,
        "explanation_check": {
            "checks": {"numbers": {"status": "needs_attention" if hard_quality else "pass"}},
            "requirements": {
                "coverage": {"status": "pass"},
                "provenance": {"status": "pass"},
                "scope_changed": scope_changed,
            },
        },
    }
    _write_json(analysis / "drafts" / f"draft-{task_id}.json", draft)
    _write_json(analysis / "runs" / f"run-{task_id}.json", {"id": f"run-{task_id}", "seq": 5, "execution_status": "succeeded"})
    _write_json(analysis / "requirements" / f"req-{task_id}.json", {"id": f"req-{task_id}", "seq": 4})
    if prior_chain:
        for index in range(prior_chain_count):
            _write_json(analysis / "completions" / f"completion-prior-{index}-{task_id}.json", {
                "id": f"completion-prior-{index}-{task_id}",
                "seq": 8 + index,
                "draft_id": f"old-draft-{index}",
                "draft_content_hash": f"old-hash-{index}",
                "status": "repair_available",
                "repair_attempts": index,
                "chain_key": f"older-chain-{index}",
                "checks": {"numbers": {"status": "needs_attention"}, "coverage": {"status": "needs_attention"}, "provenance": {"status": "pass"}},
            })
    if completion_status is None:
        return
    completion = {
        "id": f"completion-{task_id}",
        "seq": 11,
        "draft_id": draft["id"],
        "draft_content_hash": completion_hash if completion_hash is not None else content_hash,
        "status": completion_status,
        "repair_attempts": repair_attempts,
        "chain_key": chain_key,
        "requirements_semantic_fingerprint": "fp-a",
        "requirements_id": f"req-{task_id}",
        "response_status": "final" if completion_status == "complete" else "ended_with_limitations",
        "stop_reason": None if completion_status == "complete" else "verified_input_gap",
        "original_requirements_completed": completion_status == "complete",
        "checks": {
            "numbers": {"status": "pass"},
            "coverage": {"status": "pass" if completion_status == "complete" else "needs_attention"},
            "provenance": {"status": "pass"},
        },
    }
    _write_json(analysis / "completions" / f"completion-{task_id}.json", completion)


def test_report_r4_acceptance_uses_fixture_denominator_and_receipt_metrics(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "fixture-summary.json", {"selected_cases": ["F01", "F02", "F03", "F04"]})
    _write_json(root / "session.json", {
        "status": "completed",
        "model": {"provider": "deepseek-official", "model": "deepseek-v4-flash", "reasoningEffort": "max"},
        "cases": [
            {
                "id": "F01",
                "task_id": "task-first",
                "session_id": "session-first",
                "completed": True,
                "duration_ms": 100,
                "provider_retries": 1,
                "calls": [{"name": "skill", "isError": False}, {"name": "run_metric", "isError": False}],
            },
            {
                "id": "F02",
                "task_id": "task-repair2",
                "session_id": "session-repair2",
                "completed": True,
                "duration_ms": 300,
                "calls": [{"name": "skill", "isError": False}, {"name": "save_explanation_draft", "isError": False}],
            },
            {
                "id": "F03",
                "task_id": "task-no-receipt",
                "session_id": "session-no-receipt",
                "completed": True,
                "duration_ms": 200,
                "calls": [{"name": "run_metric", "isError": True, "error": "boom"}],
            },
        ],
    })
    _write_json(root / "verification.json", {
        "status": "failed",
        "scoring_contract": "r4-requirements-evidence-completion-v3",
        "cases": [{"id": "F01", "status": "passed"}],
        "failures": [{"id": "F03", "status": "failed", "error": "no receipt"}],
    })
    _write_analysis(root, "task-first", completion_status="complete", repair_attempts=0)
    _write_analysis(root, "task-repair2", completion_status="complete", repair_attempts=2)
    _write_analysis(root, "task-no-receipt", completion_status=None)

    report = reporter.build_report(root)

    assert report["schema_version"] == 2
    assert report["case_count"] == 4
    assert report["seen_count"] == 3
    assert report["unobserved_count"] == 1
    assert report["provisional"] is True
    assert report["metrics"]["receipt_reported_first_attempt_completion"]["completed"] == 1
    assert report["metrics"]["receipt_reported_first_attempt_completion"]["denominator"] == 4
    assert report["metrics"]["receipt_reported_first_attempt_completion"]["case_ids"] == ["F01"]
    assert report["metrics"]["receipt_reported_within_two_repairs_completion"]["completed"] == 2
    assert report["metrics"]["receipt_reported_within_two_repairs_completion"]["case_ids"] == ["F01", "F02"]
    assert report["metrics"]["independent_scorer_verified_completion"]["case_ids"] == ["F01"]
    assert report["metrics"]["latency_ms"]["p50_ms"] == 200
    assert report["metrics"]["tool_errors"]["by_tool"] == {"run_metric": 1}
    assert report["metrics"]["model_retries"]["total"] == 1
    assert report["metrics"]["independent_status_counts"]["numbers"] == {"missing": 1, "pass": 3}
    assert report["metrics"]["independent_status_counts"]["receipt_numbers"] == {"missing": 2, "pass": 2}
    assert report["metrics"]["manual_calibration"]["status"] == "not_evaluated"
    no_receipt = next(case for case in report["cases"] if case["id"] == "F03")
    assert no_receipt["observed_completed"] is True
    assert no_receipt["receipt_reported_first_attempt_complete"] is False
    assert no_receipt["latest_completion_status"] is None
    assert no_receipt["scoring_error"] == "no receipt"
    unobserved = next(case for case in report["cases"] if case["id"] == "F04")
    assert unobserved["observed"] is False
    assert unobserved["receipt_reported_within_two_repairs_complete"] is False


def test_report_r4_acceptance_requires_draft_bound_content_hash(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "session.json", {"status": "completed", "cases": [{"id": "F01", "task_id": "task-stale", "completed": True}]})
    _write_analysis(root, "task-stale", completion_status="complete", repair_attempts=0, completion_hash="old-hash")

    report = reporter.build_report(root)

    case = report["cases"][0]
    assert case["latest_completion_status"] is None
    assert case["content_hash_mismatch_count"] == 1
    assert case["receipt_reported_first_attempt_complete"] is False
    assert report["metrics"]["receipt_reported_first_attempt_completion"]["completed"] == 0


def test_report_r4_acceptance_does_not_count_new_chain_reset_as_first_attempt_or_within_two(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "session.json", {"status": "completed", "cases": [{"id": "F01", "task_id": "task-chain", "completed": True}]})
    _write_analysis(
        root,
        "task-chain",
        completion_status="complete",
        repair_attempts=0,
        chain_key="new-chain",
        prior_chain=True,
        prior_chain_count=4,
        scope_changed=True,
    )

    report = reporter.build_report(root)

    case = report["cases"][0]
    assert case["receipt_attempt_count"] == 5
    assert case["prior_chain_receipt_count"] == 4
    assert case["completion_chain_strategy"] == "chain_key"
    assert case["scope_changed"] is True
    assert case["receipt_reported_first_attempt_complete"] is False
    assert case["receipt_reported_within_two_repairs_complete"] is False


def test_report_r4_acceptance_excludes_hard_error_from_flow_success(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "session.json", {
        "status": "completed",
        "cases": [{"id": "F01", "task_id": "task-hard", "completed": True, "error": "case exceeded 420s"}],
    })
    _write_analysis(root, "task-hard", completion_status="complete", repair_attempts=0)

    report = reporter.build_report(root)

    assert report["cases"][0]["observed_completed"] is False
    assert report["metrics"]["receipt_reported_first_attempt_completion"]["completed"] == 0
    assert report["metrics"]["model_hard_errors"]["case_ids"] == ["F01"]
    assert report["metrics"]["hard_errors"]["case_ids"] == ["F01"]


def test_report_r4_acceptance_records_corrupt_analysis_json(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "session.json", {"status": "completed", "cases": [{"id": "F01", "task_id": "task-bad", "completed": True}]})
    _write_analysis(root, "task-bad", completion_status="complete", repair_attempts=0)
    bad = root / "var" / "tasks" / "task-bad" / "analysis" / "runs" / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")

    report = reporter.build_report(root)

    assert report["metrics"]["data_errors"]["case_ids"] == ["F01"]
    assert report["metrics"]["data_errors"]["total"] == 1
    assert report["cases"][0]["receipt_metrics_uncertain"] is True
    assert report["cases"][0]["receipt_reported_first_attempt_complete"] is False
    assert report["cases"][0]["receipt_reported_within_two_repairs_complete"] is False
    assert "bad.json" in report["cases"][0]["data_errors"][0]["path"]


def test_report_r4_acceptance_separates_observation_state_error_from_model_hard_error(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "session.json", {
        "status": "completed",
        "cases": [{
            "id": "F01",
            "task_id": "task-state-error",
            "completed": True,
            "state_error": "spawnSync foundry ENOBUFS",
        }],
    })
    _write_analysis(root, "task-state-error", completion_status="complete", repair_attempts=0)

    report = reporter.build_report(root)

    assert report["metrics"]["observation_errors"]["case_ids"] == ["F01"]
    assert report["metrics"]["model_hard_errors"]["case_ids"] == []
    assert report["cases"][0]["observed_completed"] is True
    assert report["metrics"]["receipt_reported_first_attempt_completion"]["case_ids"] == ["F01"]


def test_report_r4_acceptance_counts_awaiting_input_as_receipt_terminal(tmp_path: Path) -> None:
    root = tmp_path / "r4-run"
    _write_json(root / "session.json", {
        "status": "completed",
        "cases": [{"id": "F12", "task_id": "task-gap", "completed": True, "events": [{"type": "llm/retry"}]}],
    })
    _write_analysis(root, "task-gap", completion_status="awaiting_input", repair_attempts=0)

    report = reporter.build_report(root)

    assert report["metrics"]["receipt_reported_first_attempt_completion"]["case_ids"] == ["F12"]
    assert report["metrics"]["receipt_reported_within_two_repairs_completion"]["case_ids"] == ["F12"]
    assert report["metrics"]["model_retries"] == {"case_count": 1, "total": 1, "case_ids": ["F12"]}
    assert report["metrics"]["independent_status_counts"]["completion_status"] == {"awaiting_input": 1}
