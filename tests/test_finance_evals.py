from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore, _new
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests/fixtures/finance_evals/cases.json"
HOLDOUT = REPO / "tests/fixtures/finance_evals/holdout_cases.json"
SPEC = importlib.util.spec_from_file_location("verify_finance_evals", REPO / "tools/verify_finance_evals.py")
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verifier)


def _semantic_basis(item_id: str = 'item-1') -> dict[str, object]:
    return {
        'version': 1,
        'question': '解释利润变动。',
        'context_id': 'ctx-main',
        'scope': {'ledger': 'L1', 'period': '2026-08'},
        'sources': {'actual': {'dataset_id': 'dataset-a', 'source_hash': 'source-hash', 'data_hash': 'data-hash'}},
        'removed_item_ids': [],
        'items': [
            {
                'id': item_id,
                'metric': 'profit',
                'dimensions': {},
                'periods': ['2026-08'],
                'requires_drilldown': False,
            }
        ],
    }


def _semantic_fingerprint() -> str:
    return verifier._sha(_semantic_basis())


def _semantic_requirement(requirement_id: str, seq: int, fingerprint: str | None = None) -> dict[str, object]:
    basis = _semantic_basis()
    return {
        'id': requirement_id,
        'seq': seq,
        'question': basis['question'],
        'context_id': basis['context_id'],
        'scope': basis['scope'],
        'bindings': {'actual': 'dataset-a'},
        'items': [
            {
                'id': 'item-1',
                'metric': 'profit',
                'dimensions': {},
                'periods': ['2026-08'],
                'requires_drilldown': False,
            },
        ],
        'removed_item_ids': [],
        'semantic_version': 1,
        'semantic_fingerprint': fingerprint or verifier._sha(basis),
        'semantic_basis': basis,
    }


def _dataset_state() -> dict[str, object]:
    return {
        'id': 'dataset-a',
        'source_hash': 'source-hash',
        'data_hash': 'data-hash',
        'row_count': 2,
        'schema': [
            {'name': 'ledger', 'type': 'VARCHAR'},
            {'name': 'organization', 'type': 'VARCHAR'},
            {'name': 'period', 'type': 'VARCHAR'},
            {'name': 'amount', 'type': 'DECIMAL'},
        ],
    }


def _bound_run(run_id: str = 'run1', seq: int = 20, requirement_id: str = 'req2') -> dict[str, object]:
    return {
        'id': run_id,
        'seq': seq,
        'execution_status': 'succeeded',
        'requirements_id': requirement_id,
        'requirements_semantic_fingerprint': _semantic_fingerprint(),
        'bindings': {'actual': 'dataset-a'},
        'input_hashes': {'actual': 'data-hash'},
        'source_hashes': {'actual': 'source-hash'},
    }


def _r4_management_service(tmp_path: Path, dirname: str = 'r4-real') -> tuple[FinanceStore, dict[str, object]]:
    service = FinanceStore(TaskStore(tmp_path / dirname).create(title='r4 verifier real backend'))
    bindings = {}
    rows_by_alias = {
        'actual': [
            {'account_code': '001', 'management_account': 'revenue', 'amount': '120', 'scenario': 'actual'},
            {'account_code': '002', 'management_account': 'cost', 'amount': '70', 'scenario': 'actual'},
        ],
        'budget': [
            {'account_code': '001', 'management_account': 'revenue', 'amount': '100', 'scenario': 'budget'},
            {'account_code': '002', 'management_account': 'cost', 'amount': '60', 'scenario': 'budget'},
        ],
    }
    for alias, rows in rows_by_alias.items():
        path = tmp_path / f'{dirname}-{alias}.json'
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        bindings[alias] = service.analysis.add_dataset(path, name=alias)['id']
    context = service.save_context({
        'bindings': bindings,
        'scopes': {
            alias: {
                'ledger': 'L1',
                'organization': 'O1',
                'period': '2026-09',
                'currency': 'CNY',
                'unit': '万元',
                'scenario': alias,
            }
            for alias in bindings
        },
    })
    return service, context


def _r4_contract_draft(service: FinanceStore, requirement: dict[str, object], run: dict[str, object], quality: dict[str, object]) -> dict[str, object]:
    body = '成本率已按当前要求完成。'
    draft = _new(
        service.task,
        requirements_id=requirement['id'],
        body=body,
        run_ids=[run['id']],
        fact_ids=[],
        claims=[],
        explanation_check=quality,
        quality=quality,
        limitations=[],
        content_hash=verifier._sha({'body': body, 'run_ids': [run['id']], 'quality': quality}),
    )
    return service.analysis._write(service.analysis._object_path('drafts', draft['id']), draft)


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


def test_holdout_fixture_has_distinct_runnable_cases() -> None:
    fixture = verifier._load_fixture(HOLDOUT)
    cases = fixture["cases"]
    assert fixture["suite"] == "holdout"
    assert len(cases) >= 8
    assert all(case["runnable"] for case in cases)
    assert {case["expected"]["type"] for case in cases} >= {
        "profit_bridge",
        "price_quantity",
        "ratio",
        "control_totals",
        "receivables_aging",
        "cash_13_weeks",
    }


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


def test_only_latest_draft_can_verify_expected_cells() -> None:
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][0]
    case = {**case, "taskId": "task", "sessionId": "session", "inputSha256": "abc"}
    run = {
        "id": "run1",
        "execution_status": "succeeded",
        "result": {
            "rows": [
                {**case["expected"]["identity"], "metric": "profit", "contribution": "5"},
                {**case["expected"]["identity"], "metric": "revenue", "contribution": "20"},
                {**case["expected"]["identity"], "metric": "cost", "contribution": "-10"},
                {**case["expected"]["identity"], "metric": "expense", "contribution": "-5"},
            ]
        },
    }
    state = {
        "runs": [run],
        "drafts": [
            {
                "id": "old-complete",
                "run_ids": ["run1"],
                "body": "旧稿完整，不能替最终稿评分。",
                "claims": [
                    {"basis": "calculation", "verification_status": "matches_run", "run_id": "run1", "row": row, "column": "contribution", "value": value}
                    for row, value in enumerate(["5", "20", "-10", "-5"])
                ],
            },
            {
                "id": "latest-incomplete",
                "run_ids": ["run1"],
                "body": "最终稿只引用利润。",
                "claims": [
                    {"basis": "calculation", "verification_status": "matches_run", "run_id": "run1", "row": 0, "column": "contribution", "value": "5"}
                ],
            },
        ],
    }
    cells = verifier._find_expected_cells(state, case)
    assert verifier._verified_draft_cells(state, cells) == {"profit"}


def test_expected_zero_must_be_materialized_by_a_real_run_cell() -> None:
    case = next(item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"] if item["id"] == "F19_prior_period_comparison")
    state = {
        "runs": [
            {
                "id": "run1",
                "execution_status": "succeeded",
                "result": {
                    "rows": [
                        {**case["expected"]["identity"], "metric": "profit", "contribution": "1"},
                        {**case["expected"]["identity"], "metric": "revenue", "contribution": "5"},
                        {**case["expected"]["identity"], "metric": "cost", "contribution": "-4"},
                    ]
                },
            }
        ],
        "drafts": [],
    }
    with pytest.raises(AssertionError, match="expense"):
        verifier._find_expected_cells(state, case)


def test_final_text_requires_precise_ratio_and_rejects_contradictory_amounts() -> None:
    case = next(item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"] if item["id"] == "F14_ratio_cost_rate")
    cells = {
        "numerator": {"run_id": "run1", "row": 0, "column": "numerator", "value": "70"},
        "denominator": {"run_id": "run1", "row": 0, "column": "denominator", "value": "120"},
        "ratio": {"run_id": "run1", "row": 0, "column": "ratio", "value": "0.5833333333333333333333333333"},
    }
    verifier._verify_final_text_numbers(case, "成本70万元，收入120万元，成本率58.33%。", cells)
    with pytest.raises(AssertionError, match="unbacked"):
        verifier._verify_final_text_numbers(case, "成本70万元，收入120万元，成本率58%。", cells)
    with pytest.raises(AssertionError, match="missing expected"):
        verifier._verify_final_text_numbers(case, "计算过程详见引用。", cells)

    bridge_case = next(item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"] if item["id"] == "F19_prior_period_comparison")
    bridge_cells = {
        "profit": {"run_id": "run1", "row": 0, "column": "contribution", "value": "1"},
        "revenue": {"run_id": "run1", "row": 1, "column": "contribution", "value": "5"},
        "cost": {"run_id": "run1", "row": 2, "column": "contribution", "value": "-4"},
        "expense": {"run_id": "run1", "row": 3, "column": "contribution", "value": "0"},
    }
    verifier._verify_final_text_numbers(bridge_case, "收入增加5万元，成本增加4万元，利润影响-4万元，费用影响0万元，利润增加1万元。", bridge_cells)
    verifier._verify_final_text_numbers(bridge_case, "收入增加5万元，成本超预算4万元，利润增加1万元，费用影响0万元。", bridge_cells)
    verifier._verify_final_text_numbers(bridge_case, "收入增加5万元，成本高于预算4万元，利润增加1万元，费用影响0万元。", bridge_cells)
    with pytest.raises(AssertionError, match="unbacked"):
        verifier._verify_final_text_numbers(bridge_case, "成本下降4万元，利润增加4万元。", bridge_cells)


def test_final_answer_cannot_complete_missing_draft_text() -> None:
    cells = {
        "profit": {"run_id": "run1", "row": 0, "column": "contribution", "value": "5"},
        "revenue": {"run_id": "run1", "row": 1, "column": "contribution", "value": "20"},
    }
    state = {"drafts": [{"body": "正文只写利润增加5万元。"}]}
    observed = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "收入增加20万元。"}]}]}
    with pytest.raises(AssertionError, match="missing expected"):
        verifier._verify_canonical_final_text({"expected": {"type": "profit_bridge"}}, observed, state, cells)


def test_forbidden_causal_scan_includes_final_answer_and_requires_judgment_label() -> None:
    case = {"expected": {"type": "profit_bridge", "requires_judgment": True}}
    observed = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "收入增长导致利润改善。"}]}]}
    assert verifier._scan_forbidden(case, observed, {"drafts": []})
    labeled = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "经理判断：收入增长主要因为临时活动。"}]}]}
    assert verifier._scan_forbidden(case, labeled, {"drafts": []}) == []


def test_drilldown_must_point_to_referenced_cells_and_requested_object() -> None:
    cells = {
        "profit": {"run_id": "run1", "row": 0, "column": "contribution", "value": "5"},
        "revenue": {"run_id": "run1", "row": 1, "column": "contribution", "value": "20"},
    }
    good = {"calls": [{"name": "drilldown_fact", "isError": False, "arguments": {"spec": {"run_id": "run1", "row": 1, "column": "contribution"}}}]}
    verifier._verify_drilldowns_reference_cells({"question": "保存说明并下钻任一来源行。", "expected": {}}, good, cells)
    bad = {"calls": [{"name": "drilldown_fact", "isError": False, "arguments": {"spec": {"run_id": "run2", "row": 0, "column": "contribution"}}}]}
    with pytest.raises(AssertionError, match="referenced expected cells"):
        verifier._verify_drilldowns_reference_cells({"question": "保存说明并下钻任一来源行。", "expected": {}}, bad, cells)
    with pytest.raises(AssertionError, match="requested drilldown target"):
        verifier._verify_drilldowns_reference_cells({"question": "保存说明并下钻利润行。", "expected": {}}, good, cells)


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

    def fake_score(_foundry: Path, _var: Path, case: dict[str, object], _row: dict[str, object], *, r4: bool = False) -> dict[str, object]:
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
    assert result["attempted"] == 2
    assert result["completed"] == 1
    assert result["passed"] == 1
    assert result["workflow_pass_rate"] == "0.5"
    assert result["status"] == "failed"
    assert result["failures"][0]["input_sha256"] == "sha-timed"
    assert result["scoring_contract"] == "r3-final-draft-text-bound-v3"


def test_score_observation_treats_turn_error_as_hard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [{"id": "pilot", "taskId": "task-pilot", "sessionId": "session-pilot", "inputSha256": "sha-pilot"}]

    def fake_score(_foundry: Path, _var: Path, _case: dict[str, object], _row: dict[str, object], *, r4: bool = False) -> dict[str, object]:
        raise AssertionError("case has hard turn/runtime errors")

    monkeypatch.setattr(verifier, "_score_case", fake_score)
    result = verifier.score_observation(
        REPO / ".venv/bin/foundry",
        REPO / "build/verification/nonexistent-var",
        cases,
        {
            "cases": [
                {
                    "id": "pilot",
                    "completed": True,
                    "input_sha256": "sha-pilot",
                    "duration_ms": 12,
                    "turn_errors": [{"index": 3, "event": {"reason": {"kind": "error"}}}],
                }
            ]
        },
    )
    assert result["attempted"] == 1
    assert result["completed"] == 0
    assert result["hard_error_count"] == 1
    assert result["hard_errors_status"] == "failed"
    assert result["failures"][0]["input_sha256"] == "sha-pilot"


def test_compare_requires_same_fixture_hashes_and_scoring_contract(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(
        json.dumps(
            {
                "status": "passed",
                "fixture_version": "same",
                "scoring_contract": "r3-final-draft-text-bound-v3",
                "workflow_pass_rate": "1",
                "cases": [{"id": "A", "input_sha256": "sha-a"}],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "status": "passed",
                "fixture_version": "same",
                "scoring_contract": "r3-final-draft-text-bound-v3",
                "workflow_pass_rate": "1",
                "cases": [{"id": "A", "input_sha256": "sha-a"}],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    assert verifier.compare_verifications([first, second])["summary"]["runs"] == 2

    second.write_text(
        json.dumps(
            {
                "status": "passed",
                "fixture_version": "holdout",
                "scoring_contract": "r3-final-draft-text-bound-v3",
                "workflow_pass_rate": "1",
                "cases": [{"id": "H01", "input_sha256": "sha-h"}],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="same fixture_version"):
        verifier.compare_verifications([first, second])


def test_ratio_precision_contract_accepts_more_precise_rational_not_wrong_amount():
    from decimal import Decimal, localcontext
    case = next(c for c in verifier._load_fixture()['cases'] if c['id'].startswith('F14'))
    with localcontext() as ctx:
        ctx.prec = 80
        value = str(Decimal(70) / Decimal(120))
    row = {**case['expected']['identity'], 'numerator': '70', 'denominator': '120', 'ratio': value}
    state = {'runs': [{'id': 'r', 'execution_status': 'succeeded', 'result': {'rows': [row]}}]}
    assert verifier._find_expected_cells(state, case)['ratio']['value'] == value
    row['ratio'] = '0.58'
    with pytest.raises(AssertionError, match='ratio'):
        verifier._find_expected_cells(state, case)


def test_final_text_allows_only_additional_claims_recomputed_from_successful_runs() -> None:
    case = {'datasets': [{'metadata': {'unit': '万元'}, 'rows': [{}]}], 'expected': {}}
    cells = {'profit': {'run_id': 'run1', 'row': 0, 'column': 'contribution', 'value': '5'}}
    state = {
        'runs': [{'id': 'run1', 'execution_status': 'succeeded', 'result': {'rows': [{'contribution': '5', 'actual': '30', 'budget': '25'}]}}],
        'drafts': [{'run_ids': ['run1'], 'claims': [{'basis': 'calculation', 'run_id': 'run1', 'row': 0, 'column': column, 'value': value}
                                                 for column, value in [('actual', '30'), ('budget', '25')]]}],
    }
    extra = verifier._verified_additional_cells(state)
    verifier._verify_final_text_numbers(case, '实际30万元，预算25万元，利润增加5万元。', cells, extra)
    verifier._verify_final_text_numbers(case, '利润增加50,000元。', cells)
    verifier._verify_final_text_numbers(case, '金额单位：万元\n| 利润影响 |\n| 5 |', cells)
    with pytest.raises(AssertionError, match='unbacked'):
        verifier._verify_final_text_numbers(case, '利润增加5元。', cells)
    state['runs'][0]['execution_status'] = 'failed'
    assert verifier._verified_additional_cells(state) == {}


def test_causal_negation_and_hypothesis_are_not_assertions() -> None:
    case = {'expected': {}}
    for text in ['仅凭数据不能认定收入增长主要因为促销。', '费用超支可能归因于一次活动，尚待经理核实。']:
        assert verifier._scan_forbidden(case, {}, {'drafts': [{'body': text}]}) == []
    assert verifier._scan_forbidden(case, {}, {'drafts': [{'body': '费用超支归因于一次活动。'}]})


def test_voucher_check_requires_named_true_flag_not_any_true() -> None:
    assert not verifier._has_voucher_detail({'stdout': '{"ok": true, "voucher_detail_available": false}'})
    assert verifier._has_voucher_detail({'stdout': '{"rows": [{"voucher_detail_available": true}]}'})


def test_ratio_does_not_accept_unscaled_ratio_as_percent() -> None:
    cells = {'ratio': {'run_id': 'r', 'row': 0, 'column': 'ratio', 'value': '0.58'}}
    with pytest.raises(AssertionError, match='unbacked'):
        verifier._verify_final_text_numbers({'expected': {}}, '成本率0.58%。', cells)


def test_profit_bridge_uses_cited_semantic_alias_and_label_drilldown() -> None:
    case = verifier._load_fixture()['cases'][0]
    rows = [{**case['expected']['identity'], 'metric': name, 'contribution': value, 'profit_impact': value}
            for name, value in case['expected']['claims'].items()]
    state = {'runs': [{'id': 'r', 'execution_status': 'succeeded', 'result': {'rows': rows}}],
             'drafts': [{'run_ids': ['r'], 'claims': [{'basis': 'calculation', 'verification_status': 'matches_run',
                'run_id': 'r', 'row': i, 'column': 'profit_impact', 'value': row['profit_impact']} for i, row in enumerate(rows)]}]}
    cells = verifier._find_expected_cells(state, case)
    assert verifier._verified_draft_cells(state, cells) == set(cells)
    profit_row = next(i for i, row in enumerate(rows) if row['metric'] == 'profit')
    verifier._verify_drilldowns_reference_cells(case, {'calls': [{'name': 'drilldown_fact', 'arguments': {
        'spec': {'run_id': 'r', 'row': profit_row, 'column': 'metric'}}}]}, cells)


def test_compare_rejects_missing_provenance(tmp_path: Path) -> None:
    path = tmp_path / 'unversioned.json'
    path.write_text(json.dumps({'cases': [{'id': 'A', 'input_sha256': 'abc'}]}))
    with pytest.raises(AssertionError, match='nonempty'):
        verifier.compare_verifications([path, path])


def test_recovered_provider_stream_failure_is_not_a_terminal_failure() -> None:
    observed = {'completed': False, 'error': 'agent turn ended with error', 'events': [
        {'type': 'assistant/chunk', 'data': {'chunk': {'type': 'finish', 'reason': {'kind': 'error'}}}},
        {'type': 'llm/retry'},
        {'type': 'turn/end', 'data': {'reason': {'kind': 'completed'}}},
    ]}
    assert verifier._case_hard_errors(observed) == []
    assert verifier._case_completed(observed)
    observed['events'][-1]['data']['reason']['kind'] = 'error'
    assert verifier._case_hard_errors(observed)
    assert not verifier._case_completed(observed)


def test_timeout_is_not_erased_by_late_completed_event() -> None:
    observed = {'error': 'case exceeded 420s', 'events': [{'type': 'turn/end', 'data': {'reason': {'kind': 'completed'}}}]}
    assert not verifier._case_completed(observed)


def test_cancelled_turn_cannot_be_reported_completed() -> None:
    assert not verifier._case_completed({'completed': True, 'events': [{'type': 'turn/end', 'data': {'reason': {'kind': 'cancelled'}}}]})


def test_r4_contract_requires_latest_requirements_quality_and_completion() -> None:
    draft = {
        'id': 'draft1',
        'seq': 30,
        'requirements_id': 'req2',
        'content_hash': 'draft-hash',
        'run_ids': ['run1'],
        'explanation_check': {
            'requirements': {
                'requirements_id': 'req2',
                'coverage': {'status': 'pass'},
                'provenance': {'status': 'pass'},
            },
        },
    }
    state = {
        'requirements': [_semantic_requirement('req1', 5), _semantic_requirement('req2', 10)],
        'datasets': [_dataset_state()],
        'runs': [_bound_run(requirement_id='req2')],
        'completions': [{'draft_id': 'draft1', 'status': 'complete', 'requirements_id': 'req2', 'draft_content_hash': 'draft-hash'}],
    }
    verifier._verify_r4_contract(state, draft, {})

    with pytest.raises(AssertionError, match='latest requirements'):
        verifier._verify_r4_contract(state, {**draft, 'requirements_id': 'req1'}, {})
    with pytest.raises(AssertionError, match='completion receipt'):
        verifier._verify_r4_contract({**state, 'completions': []}, draft, {})


def test_r4_missing_data_contract_requires_awaiting_input_gap_and_explicit_limitation() -> None:
    source = {
        'alias': 'actual',
        'dataset_id': 'dataset-a',
        'source_hash': 'source-hash',
        'data_hash': 'data-hash',
        'columns': ['ledger', 'organization', 'period', 'amount'],
    }
    gap = {
        'gap_code': 'native_price_quantity_fields_unavailable',
        'missing_inputs': [{'dataset_id': 'dataset-a', 'alias': 'actual', 'columns': ['quantity', 'price']}],
        'sources': [source],
    }
    draft = {
        'id': 'draft-missing',
        'seq': 30,
        'requirements_id': 'req1',
        'content_hash': 'draft-hash',
        'run_ids': ['run1'],
        'limitations': ['资料缺少数量和单价，不能完成量价拆分。'],
        'explanation_check': {
            'checks': {'numbers': {'status': 'pass'}},
            'requirements': {
                'requirements_id': 'req1',
                'coverage': {'status': 'needs_attention'},
                'provenance': {'status': 'needs_attention'},
                'items': [
                    {'id': 'item-1', 'status': 'missing_data', 'input_gap': gap},
                ],
            },
        },
    }
    state = {
        'datasets': [_dataset_state()],
        'requirements': [{
            **_semantic_requirement('req1', 10),
            'support': {'items': [{**gap, 'requirement_item_id': 'item-1', 'status': 'requires_input'}]},
        }],
        'runs': [_bound_run(requirement_id='req1')],
        'completions': [{
            'draft_id': 'draft-missing',
            'status': 'awaiting_input',
            'requirements_id': 'req1',
            'draft_content_hash': 'draft-hash',
            'response_status': 'ended_with_limitations',
            'repair_allowed': False,
            'stop_reason': 'verified_input_gap',
            'original_requirements_completed': False,
            'actions': [{'code': 'verified_input_gap', 'requirement_item_id': 'item-1'}],
        }],
    }
    verifier._verify_r4_contract(state, draft, {}, allow_missing_data=True)

    with pytest.raises(AssertionError, match='explicit draft limitations'):
        verifier._verify_r4_contract(state, {**draft, 'limitations': []}, {}, allow_missing_data=True)
    complete = {**state, 'completions': [{**state['completions'][0], 'status': 'complete'}]}
    with pytest.raises(AssertionError, match='awaiting_input'):
        verifier._verify_r4_contract(complete, draft, {}, allow_missing_data=True)
    weak_numbers = {
        **draft,
        'explanation_check': {
            **draft['explanation_check'],
            'checks': {'numbers': {'status': 'needs_attention'}},
        },
    }
    with pytest.raises(AssertionError, match='numeric checks'):
        verifier._verify_r4_contract(state, weak_numbers, {}, allow_missing_data=True)
    hash_mismatch = {**state, 'datasets': [{**state['datasets'][0], 'source_hash': 'different'}]}
    with pytest.raises(AssertionError, match='semantic_basis'):
        verifier._verify_r4_contract(hash_mismatch, draft, {}, allow_missing_data=True)
    no_action = {**state, 'completions': [{**state['completions'][0], 'actions': []}]}
    with pytest.raises(AssertionError, match='every verified input gap'):
        verifier._verify_r4_contract(no_action, draft, {}, allow_missing_data=True)
    present_quantity = {
        **state,
        'datasets': [{**_dataset_state(), 'schema': [*_dataset_state()['schema'], {'name': 'quantity', 'type': 'DECIMAL'}]}],
    }
    with pytest.raises(AssertionError, match='source columns'):
        verifier._verify_r4_contract(present_quantity, draft, {}, allow_missing_data=True)
    contradictory_source = {**source, 'columns': ['ledger', 'organization', 'period', 'amount', 'quantity']}
    contradictory_gap = {**gap, 'sources': [contradictory_source], 'missing_inputs': [{**gap['missing_inputs'][0], 'columns': ['quantity']}]}
    contradictory = {
        **draft,
        'explanation_check': {
            **draft['explanation_check'],
            'requirements': {
                **draft['explanation_check']['requirements'],
                'items': [{'id': 'item-1', 'status': 'missing_data', 'input_gap': contradictory_gap}],
            },
        },
    }
    contradictory_state = {
        **state,
        'datasets': [{**_dataset_state(), 'schema': [*_dataset_state()['schema'], {'name': 'quantity', 'type': 'DECIMAL'}]}],
        'requirements': [{
            **state['requirements'][0],
            'support': {'items': [{**contradictory_gap, 'requirement_item_id': 'item-1', 'status': 'requires_input'}]},
        }],
    }
    with pytest.raises(AssertionError, match='missing input columns exist'):
        verifier._verify_r4_contract(contradictory_state, contradictory, {}, allow_missing_data=True)
    unsupported_gap = {
        **draft,
        'explanation_check': {
            **draft['explanation_check'],
            'requirements': {
                **draft['explanation_check']['requirements'],
                'items': [{'id': 'item-1', 'status': 'missing_data', 'input_gap': {**gap, 'gap_code': 'client_asserted_missing'}}],
            },
        },
    }
    unsupported_support = {
        **state,
        'requirements': [{
            **state['requirements'][0],
            'support': {'items': [{**gap, 'gap_code': 'client_asserted_missing', 'requirement_item_id': 'item-1', 'status': 'requires_input'}]},
        }],
    }
    with pytest.raises(AssertionError, match='gap code is not supported'):
        verifier._verify_r4_contract(unsupported_support, unsupported_gap, {}, allow_missing_data=True)
    unresolved_issue = {
        **draft,
        'explanation_check': {
            **draft['explanation_check'],
            'issues': [{'code': 'uncited_number', 'message': '还有未解释数字'}],
        },
    }
    with pytest.raises(AssertionError, match='unresolved non-gap issues'):
        verifier._verify_r4_contract(state, unresolved_issue, {}, allow_missing_data=True)
    missing_quality_item = {
        **draft,
        'explanation_check': {
            **draft['explanation_check'],
            'requirements': {**draft['explanation_check']['requirements'], 'items': []},
        },
    }
    with pytest.raises(AssertionError, match='cover all current items'):
        verifier._verify_r4_contract(state, missing_quality_item, {}, allow_missing_data=True)
    missing_schema = {**state, 'datasets': [{key: value for key, value in state['datasets'][0].items() if key != 'schema'}]}
    with pytest.raises(AssertionError, match='source schema is missing'):
        verifier._verify_r4_contract(missing_schema, draft, {}, allow_missing_data=True)


def test_r4_v3_requires_semantic_binding_proof_for_selected_runs() -> None:
    draft = {
        'id': 'draft1',
        'seq': 30,
        'requirements_id': 'req2',
        'content_hash': 'draft-hash',
        'run_ids': ['run1'],
        'explanation_check': {
            'requirements': {
                'requirements_id': 'req2',
                'coverage': {'status': 'pass'},
                'provenance': {'status': 'pass'},
            },
        },
    }
    state = {
        'requirements': [_semantic_requirement('req1', 5), _semantic_requirement('req2', 10)],
        'datasets': [_dataset_state()],
        'runs': [_bound_run(requirement_id='req2')],
        'completions': [{'draft_id': 'draft1', 'status': 'complete', 'requirements_id': 'req2', 'draft_content_hash': 'draft-hash'}],
    }
    verifier._verify_r4_contract(state, draft, {})

    missing_current_fingerprint = {
        **state,
        'requirements': [state['requirements'][0], {key: value for key, value in state['requirements'][1].items() if key != 'semantic_fingerprint'}],
    }
    with pytest.raises(AssertionError, match='semantic_fingerprint'):
        verifier._verify_r4_contract(missing_current_fingerprint, draft, {})
    unbound_run = {
        **state,
        'runs': [{key: value for key, value in state['runs'][0].items() if key != 'requirements_id'}],
    }
    with pytest.raises(AssertionError, match='bind an existing requirements record'):
        verifier._verify_r4_contract(unbound_run, draft, {})
    mismatched_run = {
        **state,
        'runs': [{**state['runs'][0], 'requirements_semantic_fingerprint': 'fp-stale'}],
    }
    with pytest.raises(AssertionError, match='semantic fingerprint'):
        verifier._verify_r4_contract(mismatched_run, draft, {})
    mismatched_inputs = {
        **state,
        'runs': [{**state['runs'][0], 'input_hashes': {'actual': 'stale-data-hash'}}],
    }
    with pytest.raises(AssertionError, match='inputs do not match'):
        verifier._verify_r4_contract(mismatched_inputs, draft, {})
    tampered_basis = {
        **state,
        'requirements': [
            state['requirements'][0],
            {**state['requirements'][1], 'question': '改成另一个问题，但保留旧指纹'},
        ],
    }
    with pytest.raises(AssertionError, match='semantic_basis'):
        verifier._verify_r4_contract(tampered_basis, draft, {})


def test_r4_v3_allows_prior_run_only_with_semantic_reuse_proof() -> None:
    draft = {
        'id': 'draft1',
        'seq': 30,
        'requirements_id': 'req2',
        'content_hash': 'draft-hash',
        'run_ids': ['run1'],
        'explanation_check': {
            'requirements': {
                'requirements_id': 'req2',
                'coverage': {'status': 'pass'},
                'provenance': {'status': 'pass'},
            },
        },
    }
    state = {
        'requirements': [_semantic_requirement('req1', 5), _semantic_requirement('req2', 10)],
        'datasets': [_dataset_state()],
        'runs': [_bound_run(seq=7, requirement_id='req1')],
        'completions': [{'draft_id': 'draft1', 'status': 'complete', 'requirements_id': 'req2', 'draft_content_hash': 'draft-hash'}],
    }
    verifier._verify_r4_contract(state, draft, {})

    stale_binding = {
        **state,
        'requirements': [{**state['requirements'][0], 'semantic_fingerprint': 'fp-stale'}, state['requirements'][1]],
    }
    with pytest.raises(AssertionError, match='semantic fingerprint'):
        verifier._verify_r4_contract(stale_binding, draft, {})
    missing_basis = {
        **state,
        'requirements': [
            {key: value for key, value in state['requirements'][0].items() if key != 'semantic_basis'},
            state['requirements'][1],
        ],
    }
    with pytest.raises(AssertionError, match='semantic_basis'):
        verifier._verify_r4_contract(missing_basis, draft, {})


def test_r4_v3_accepts_real_finance_store_equivalent_requirement_reuse(tmp_path: Path) -> None:
    from foundry.finance_completion import record_completion
    from foundry.finance_explanations import claims_for_facts
    from foundry.finance_requirements import check_requirements

    service, context = _r4_management_service(tmp_path)
    original = service.analysis_requirements_save({
        'context_id': context['id'],
        'question': '解释成本率',
        'items': [{'id': 'margin', 'metric': 'variance_ratio', 'requires_drilldown': False}],
    })
    run = service.run_metric({
        'context_id': context['id'],
        'metric': {
            'kind': 'ratio',
            'numerator_accounts': ['cost'],
            'denominator_accounts': ['revenue'],
            'filters': {'scenario': 'actual'},
        },
    })
    revised = service.analysis_requirements_save({
        'context_id': context['id'],
        'parent_id': original['id'],
        'question': '解释成本率',
        'items': [{'id': 'margin', 'metric': 'ratio', 'requires_drilldown': False}],
    })
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    ratio = next(fact for fact in prepared['facts'] if fact['column'] == 'ratio')
    requirement_quality = check_requirements(service.analysis, {
        'requirements_id': revised['id'],
        'run_ids': [run['id']],
        'claims': claims_for_facts(prepared['facts'], [ratio['id']]),
    })
    quality = {
        'status': 'pass',
        'issues': [],
        'checks': {'numbers': {'status': 'pass'}},
        'requirements': requirement_quality,
    }
    draft = _r4_contract_draft(service, revised, run, quality)
    completion = record_completion(service.analysis, draft, quality)

    assert original['semantic_fingerprint'] == revised['semantic_fingerprint']
    assert completion['status'] == 'complete'
    assert completion['reused_run_ids'] == [run['id']]
    verifier._verify_r4_contract(service.analysis.state(), draft, {})


def test_r4_v3_accepts_real_finance_store_amount_only_input_gap(tmp_path: Path) -> None:
    service = FinanceStore(TaskStore(tmp_path / 'r4-gap').create(title='r4 verifier amount only gap'))
    path = tmp_path / 'amount-only.json'
    path.write_text(
        json.dumps(
            [
                {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '元', 'scenario': 'actual', 'product': 'A', 'amount': '120'},
                {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '元', 'scenario': 'budget', 'product': 'A', 'amount': '100'},
            ],
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    dataset = service.analysis.add_dataset(path, name='amount-only')
    context = service.save_context({
        'bindings': {'pq': dataset['id']},
        'scopes': {
            'pq': {
                'ledger': 'L1',
                'organization': 'O1',
                'period': '2026-09',
                'currency': 'CNY',
                'unit': '元',
            },
        },
    })
    requirement = service.analysis_requirements_save({
        'context_id': context['id'],
        'question': '解释商品A收入量价变化',
        'items': [{'id': 'revenue_pq', 'metric': 'price_quantity', 'dimensions': {'product': 'A'}, 'requires_drilldown': False}],
    })
    run = service.explain_variance({
        'context_id': context['id'],
        'kind': 'price_quantity',
        'dimensions': ['product'],
        'actual_filters': {'scenario': 'actual'},
        'baseline_filters': {'scenario': 'budget'},
    })
    draft = service.save_explanation_draft({
        'run_ids': [run['id']],
        'body': '量价分解缺少数量和单价字段，待补资料后重新计算。',
    })

    assert requirement['support']['items'][0]['gap_code'] == 'native_price_quantity_fields_unavailable'
    assert run['result']['rows'] == []
    assert draft['completion']['status'] == 'awaiting_input'
    verifier._verify_r4_contract(service.analysis.state(), draft, {}, allow_missing_data=True)


def test_r4_score_case_accepts_verified_awaiting_input_without_calc_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = FinanceStore(TaskStore(tmp_path / 'r4-score-gap').create(title='r4 score gap'))
    path = tmp_path / 'amount-only-score.json'
    path.write_text(
        json.dumps(
            [
                {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '元', 'scenario': 'actual', 'product': 'A', 'amount': '120'},
                {'ledger': 'L1', 'organization': 'O1', 'period': '2026-09', 'currency': 'CNY', 'unit': '元', 'scenario': 'budget', 'product': 'A', 'amount': '100'},
            ],
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    dataset = service.analysis.add_dataset(path, name='amount-only-score')
    context = service.save_context({
        'bindings': {'pq': dataset['id']},
        'scopes': {
            'pq': {
                'ledger': 'L1',
                'organization': 'O1',
                'period': '2026-09',
                'currency': 'CNY',
                'unit': '元',
            },
        },
    })
    service.analysis_requirements_save({
        'context_id': context['id'],
        'question': '资料只有金额，请尝试商品A收入量价拆分；无法拆分时保留诊断和可用来源。',
        'items': [{'id': 'revenue_pq', 'metric': 'price_quantity', 'dimensions': {'product': 'A'}, 'requires_drilldown': False}],
    })
    draft = service.save_explanation_draft({
        'run_ids': [],
        'body': '量价分解缺少数量和单价字段，待补资料后重新计算。',
    })

    def fake_call(_foundry: Path, _var: Path, command: str, **_kwargs: object) -> dict[str, object]:
        if command == 'analysis-state':
            return service.analysis.state()
        raise AssertionError(f'unexpected command: {command}')

    monkeypatch.setattr(verifier, '_call', fake_call)
    case = {
        'id': 'F12_entry',
        'taskId': service.task.id,
        'sessionId': 'session-entry',
        'inputSha256': 'input-sha',
        'question': '资料只有金额，请尝试商品A收入量价拆分；无法拆分时保留诊断和可用来源。',
        'expected': {'type': 'price_quantity_missing', 'diagnostic_code': 'price_quantity_missing'},
    }
    observed = {
        'completed': True,
        'duration_ms': 1000,
        'catalog': [{'name': 'financial-statements'}, {'name': 'variance-analysis'}],
        'calls': [{'name': 'skill', 'isError': False}, {'name': 'save_explanation_draft', 'isError': False}],
        'final_draft': {'id': draft['id']},
        'messages': [],
    }

    scored = verifier._score_case(Path('foundry'), tmp_path, case, observed, r4=True)
    assert scored['status'] == 'passed'
    assert scored['run_ids'] == []
    assert scored['tools_used'] == ['save_explanation_draft', 'skill']
    with pytest.raises(AssertionError, match='missing expected price_quantity_missing diagnostic'):
        verifier._score_case(Path('foundry'), tmp_path, case, observed, r4=False)


def test_r4_evidence_checks_can_replace_direct_drilldown_only_when_bound_and_paginated() -> None:
    cells = {'profit': {'run_id': 'run1', 'row': 0, 'column': 'contribution', 'value': '5'}}
    check = {
        'status': 'verified',
        'location': {'run_id': 'run1', 'row': 0, 'column': 'contribution', 'output_hash': 'run-hash'},
        'source_hashes': {'dataset-a': 'source-hash'},
        'sources': [{'dataset_id': 'dataset-a', 'row_index': 1}],
        'total': 1,
        'offset': 0,
        'read_count': 1,
        'has_more': False,
    }
    state = {
        'datasets': [{'id': 'dataset-a', 'source_hash': 'source-hash', 'row_count': 2}],
        'runs': [{'id': 'run1', 'execution_status': 'succeeded', 'output_hash': 'run-hash', 'bindings': {'actual': 'dataset-a'}}],
        'evidence_checks': [check],
    }
    verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []}, state, cells)

    with pytest.raises(AssertionError, match='r4 evidence_check|traceability'):
        verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []},
                                         {**state, 'evidence_checks': [{**check, 'has_more': True}]}, cells)
    with pytest.raises(AssertionError, match='outside the run bindings'):
        verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []},
                                         {**state, 'evidence_checks': [{**check, 'source_hashes': {'dataset-b': 'source-hash'}}]}, cells)


def test_r4_evidence_checks_accept_real_analysis_state_dataset_metadata(tmp_path: Path) -> None:
    task = TaskStore(tmp_path / 'var').create(title='r4 proof')
    analysis = AnalysisStore(task)
    source = tmp_path / 'actual.json'
    source.write_text(json.dumps([{'metric': 'profit', 'amount': '5'}, {'metric': 'cost', 'amount': '3'}]), encoding='utf-8')
    dataset = analysis.add_dataset(source, name='actual')
    run = analysis._write(analysis._object_path('runs', '1' * 32), _new(
        task,
        id='1' * 32,
        execution_status='succeeded',
        output_hash='run-hash',
        bindings={'actual': dataset['id']},
        result={'columns': ['contribution'], 'rows': [{'contribution': '5'}]},
    ))
    analysis._write(analysis._object_path('evidence_checks', '2' * 32), _new(
        task,
        id='2' * 32,
        status='verified',
        location={'run_id': run['id'], 'row': 0, 'column': 'contribution', 'output_hash': run['output_hash']},
        source_hashes={dataset['id']: dataset['source_hash']},
        sources=[{'dataset_id': dataset['id'], 'row_index': 2}],
        total=1,
        offset=0,
        read_count=1,
        has_more=False,
    ))

    state = analysis.state()
    assert state['datasets'][0]['row_count'] == 2
    assert 'rows' not in state['datasets'][0]
    cells = {'profit': {'run_id': run['id'], 'row': 0, 'column': 'contribution', 'value': '5'}}

    verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []}, state, cells)

    bad_state = {
        **state,
        'evidence_checks': [{**state['evidence_checks'][0], 'sources': [{'dataset_id': dataset['id'], 'row_index': 3}]}],
    }
    with pytest.raises(AssertionError, match='outside the bound snapshot rows'):
        verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []}, bad_state, cells)


def test_r4_evidence_checks_reject_forged_empty_or_legacy_proof() -> None:
    cells = {'profit': {'run_id': 'run1', 'row': 0, 'column': 'contribution', 'value': '5'}}
    check = {
        'status': 'verified',
        'location': {'run_id': 'run1', 'row': 0, 'column': 'contribution', 'output_hash': 'run-hash'},
        'source_hashes': {'dataset-a': 'source-hash'},
        'sources': [{'dataset_id': 'dataset-a', 'row_index': 1}],
        'total': 1,
        'offset': 0,
        'read_count': 1,
        'has_more': False,
    }
    state = {
        'datasets': [{'id': 'dataset-a', 'source_hash': 'source-hash', 'row_count': 1}],
        'runs': [{'id': 'run1', 'execution_status': 'succeeded', 'output_hash': 'run-hash', 'bindings': {'actual': 'dataset-a'}}],
        'evidence_checks': [check],
    }

    rejected_checks = [
        {**check, 'source_hashes': {}},
        {**check, 'sources': []},
        {key: value for key, value in check.items() if key != 'total'},
        {**check, 'total': 0},
        {**check, 'read_count': 2},
    ]
    for forged in rejected_checks:
        with pytest.raises(AssertionError, match='r4 evidence_check|traceability'):
            verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []},
                                             {**state, 'evidence_checks': [forged]}, cells)

    missing_dataset = {**state, 'datasets': []}
    with pytest.raises(AssertionError, match='missing bound snapshot|traceability'):
        verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []},
                                         missing_dataset, cells)

    missing_hash_for_row = {
        **state,
        'datasets': [
            *state['datasets'],
            {'id': 'dataset-b', 'source_hash': 'source-hash-b', 'row_count': 1},
        ],
        'runs': [{'id': 'run1', 'execution_status': 'succeeded', 'output_hash': 'run-hash', 'bindings': {'actual': 'dataset-a', 'budget': 'dataset-b'}}],
        'evidence_checks': [{**check, 'sources': [{'dataset_id': 'dataset-b', 'row_index': 1}]}],
    }
    with pytest.raises(AssertionError, match='r4 evidence_check|traceability'):
        verifier._verify_r4_traceability({'question': '请下钻利润行。', 'expected': {}}, {'calls': []},
                                         missing_hash_for_row, cells)


def test_score_observation_can_select_r4_contract_without_changing_default(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [{'id': 'case1', 'taskId': 'task1', 'sessionId': 'session1', 'inputSha256': 'sha1'}]
    seen_contracts = []

    def fake_score(_foundry: Path, _var: Path, case: dict[str, object], _row: dict[str, object], *, r4: bool = False) -> dict[str, object]:
        seen_contracts.append(r4)
        return {'id': case['id'], 'status': 'passed'}

    monkeypatch.setattr(verifier, '_score_case', fake_score)
    legacy = verifier.score_observation(REPO / '.venv/bin/foundry', REPO / 'build/verification/nonexistent-var',
                                        cases, {'cases': [{'id': 'case1', 'completed': True}]})
    r4 = verifier.score_observation(REPO / '.venv/bin/foundry', REPO / 'build/verification/nonexistent-var',
                                    cases, {'cases': [{'id': 'case1', 'completed': True}]},
                                    scoring_contract=verifier.SCORING_CONTRACT_R4)

    assert legacy['scoring_contract'] == verifier.SCORING_CONTRACT_R3
    assert r4['scoring_contract'] == verifier.SCORING_CONTRACT_R4
    assert seen_contracts == [False, True]



TABLE_NOTE = REPO / "tests/fixtures/finance_evals/table_note_cases.json"


def test_table_note_fixture_is_independent_of_the_30_case_set() -> None:
    main = verifier._load_fixture(FIXTURE)
    table_note = verifier.load_table_note_fixture(TABLE_NOTE)
    assert table_note["suite"] == "table_note"
    assert table_note["scoring_contract"] == "r3-final-draft-text-bound-v3"
    assert len(main["cases"]) >= 30
    assert {case["id"] for case in table_note["cases"]}.isdisjoint({case["id"] for case in main["cases"]})
    assert {case["id"] for case in table_note["cases"]} >= {
        "TN01_footnote_changes_meaning",
        "TN02_reconciling_table_must_close",
        "TN03_expense_flat_zero_must_cite_real_cell",
    }


def test_cf32_footnote_must_not_call_table_profit_recurring() -> None:
    case = next(item for item in verifier.load_table_note_fixture(TABLE_NOTE)["cases"] if item["id"].startswith("TN01"))
    verifier.score_table_note_text(case, "账面利润 30 万元，脚注一次性补贴 8 万元（附注/调整），不是经常项目。")
    with pytest.raises(AssertionError, match="forbidden label|经常性"):
        verifier.score_table_note_text(case, "经常性利润 30 万元，另有补贴 8 万元。")


def test_cf33_expense_zero_uses_real_cell_not_synthetic() -> None:
    case = next(item for item in verifier.load_table_note_fixture(TABLE_NOTE)["cases"] if item["id"].startswith("TN03"))
    run = {
        "id": "run-zero",
        "execution_status": "succeeded",
        "bindings": {"actual": "a", "budget": "b"},
        "result": {
            "rows": [
                {**case["expected"]["identity"], "metric": "profit", "contribution": "0"},
                {**case["expected"]["identity"], "metric": "revenue", "contribution": "0"},
                {**case["expected"]["identity"], "metric": "cost", "contribution": "0"},
                {**case["expected"]["identity"], "metric": "expense", "contribution": "0"},
            ]
        },
    }
    draft = {
        "run_ids": ["run-zero"],
        "claims": [
            {"basis": "calculation", "verification_status": "matches_run", "run_id": "run-zero", "row": 3, "column": "contribution", "value": "0"},
        ],
    }
    state = {"runs": [run], "drafts": [draft]}
    cells = verifier._find_expected_cells(state, case)
    verifier.require_real_zero_cell(cells, "expense")
    assert verifier._verified_draft_cells(state, cells) >= {"expense"}
    unverified = {**state, "drafts": [{"run_ids": ["run-zero"], "claims": []}]}
    assert "expense" not in verifier._verified_draft_cells(unverified, cells)
    synthetic = {**cells, "expense": {**cells["expense"], "synthetic_zero": True}}
    with pytest.raises(AssertionError, match="synthetic"):
        verifier.require_real_zero_cell(synthetic, "expense")


def test_table_note_reconciling_bridge_still_closes() -> None:
    case = next(item for item in verifier.load_table_note_fixture(TABLE_NOTE)["cases"] if item["id"].startswith("TN02"))
    run = {
        "id": "run-bridge",
        "execution_status": "succeeded",
        "bindings": {"actual": "a", "budget": "b"},
        "result": {
            "rows": [
                {**case["expected"]["identity"], "metric": "profit", "contribution": "5"},
                {**case["expected"]["identity"], "metric": "revenue", "contribution": "20"},
                {**case["expected"]["identity"], "metric": "cost", "contribution": "-10"},
                {**case["expected"]["identity"], "metric": "expense", "contribution": "-5"},
            ]
        },
    }
    cells = verifier._find_expected_cells({"runs": [run], "drafts": []}, case)
    assert {name: cell["value"] for name, cell in cells.items()} == case["expected"]["claims"]
