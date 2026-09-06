from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests/fixtures/finance_evals/cases.json"
SPEC = importlib.util.spec_from_file_location("verify_finance_evals", REPO / "tools/verify_finance_evals.py")
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verifier)


def test_fixture_contract_has_30_cases_and_first_20_cover_required_categories() -> None:
    fixture = verifier._load_fixture(FIXTURE)
    cases = fixture["cases"]
    assert len(cases) >= 30
    assert sum(1 for case in cases if case["stage"] == "stage5" and case["runnable"]) >= 10
    first_20 = [case for case in cases if case["runnable"]][:20]
    categories = {case["category"] for case in first_20}
    assert {
        "profit_bridge",
        "price_quantity",
        "dimension",
        "missing",
        "zero_budget",
        "negative_budget",
        "wrong_unit",
        "duplicates",
        "manager_judgment",
        "drilldown",
    } <= categories


def test_fixture_uses_exact_string_amounts_and_stable_hashes() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    hashes = []
    for case in fixture["cases"]:
        hashes.append(verifier._sha({"case_id": case["id"], "question": case["question"], "datasets": case["datasets"], "expected": case["expected"]}))
        for dataset in case["datasets"]:
            assert isinstance(dataset["metadata"], dict)
            for row in dataset["rows"]:
                if "amount" in row:
                    assert isinstance(row["amount"], str)
    assert len(set(hashes)) == len(hashes)


def test_profit_bridge_scoring_requires_closed_verified_draft_claims() -> None:
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][0]
    case = {**case, "taskId": "task", "sessionId": "session", "inputSha256": "abc"}
    run = {
        "id": "run1",
        "execution_status": "succeeded",
        "bindings": {"actual": "a", "budget": "b"},
        "result": {
            "rows": [
                {**case["expected"]["identity"], "metric": "profit", "contribution": "5", "ratio_status": "absolute_baseline", "comparison_status": "complete"},
                {**case["expected"]["identity"], "metric": "revenue", "contribution": "20", "ratio_status": "absolute_baseline", "comparison_status": "complete"},
                {**case["expected"]["identity"], "metric": "cost", "contribution": "-10", "ratio_status": "absolute_baseline", "comparison_status": "complete"},
                {**case["expected"]["identity"], "metric": "expense", "contribution": "-5", "ratio_status": "absolute_baseline", "comparison_status": "complete"},
            ]
        },
    }
    state = {"runs": [run], "drafts": []}
    cells = verifier._find_expected_cells(state, case)
    assert set(cells) == {"profit", "revenue", "cost", "expense"}
    assert verifier._verified_draft_cells(state, cells) == set()
    state["drafts"] = [
        {
            "id": "draft1",
            "run_ids": ["run1"],
            "claims": [
                {"basis": "calculation", "verification_status": "matches_run", "run_id": "run1", "row": row, "column": "contribution", "value": value}
                for row, value in enumerate(["5", "20", "-10", "-5"])
            ],
        }
    ]
    assert verifier._verified_draft_cells(state, cells) == set(cells)


def test_forbidden_causal_certainty_is_external_and_can_be_allowed_by_judgment() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = fixture["cases"][0]
    assert verifier._scan_forbidden(case, {"messages": []}, {"drafts": [{"body": "收入增长导致利润改善"}]})
    judgment_case = next(item for item in fixture["cases"] if item["expected"].get("requires_judgment"))
    assert verifier._scan_forbidden(judgment_case, {"messages": [{"content": "费用超支主要因为临时活动"}]}, {"drafts": []}) == []


def test_price_quantity_missing_accepts_diagnostic_without_invented_outputs() -> None:
    case = next(item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"] if item["id"] == "F12_price_quantity_missing_inputs")
    state = {
        "runs": [
            {
                "id": "run1",
                "execution_status": "succeeded",
                "result": {"rows": [], "diagnostics": [{"severity": "warning", "code": "price_quantity_missing"}]},
            }
        ],
        "drafts": [],
    }
    assert verifier._find_expected_cells(state, case) == {}
    bad = {"runs": [{"id": "run1", "execution_status": "succeeded", "result": {"rows": [{"total_variance": "32"}], "diagnostics": []}}], "drafts": []}
    with pytest.raises(AssertionError):
        verifier._find_expected_cells(bad, case)


def test_score_observation_reports_seen_separately_from_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        {"id": "done", "taskId": "task-done", "sessionId": "session-done", "inputSha256": "sha-done"},
        {"id": "timed", "taskId": "task-timed", "sessionId": "session-timed", "inputSha256": "sha-timed"},
    ]

    def fake_score(_foundry: Path, _var: Path, case: dict[str, object], _row: dict[str, object]) -> dict[str, object]:
        if case["id"] == "timed":
            raise AssertionError("timeout retained for review")
        return {"id": case["id"], "status": "passed"}

    monkeypatch.setattr(verifier, "_score_case", fake_score)
    result = verifier.score_observation(
        REPO / ".venv/bin/foundry",
        REPO / "build/verification/nonexistent-var",
        cases,
        {"cases": [{"id": "done", "completed": True}, {"id": "timed"}]},
    )

    assert result["seen"] == 2
    assert result["completed"] == 1
    assert result["passed"] == 1
    assert result["status"] == "failed"
