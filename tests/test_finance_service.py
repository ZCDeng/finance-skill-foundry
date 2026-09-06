import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.fixture
def finance(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="管理利润")
    store = AnalysisStore(task)
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{scenario}.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "account_code": code,
                        "management_account": account,
                        "amount": amount,
                    }
                    for code, account, amount in zip(
                        ("001", "002", "003"), ("revenue", "cost", "expense"), amounts
                    )
                ]
            )
        )
        bindings[scenario] = store.add_dataset(path, name=scenario)["id"]
    service = FinanceStore(task)
    context = service.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": alias,
                }
                for alias in bindings
            },
        }
    )
    return service, context


def test_shared_run_draft_drilldown_and_immutable_mapping(finance):
    service, context = finance
    run = service.explain_variance({"context_id": context["id"]})
    rows = run["result"]["rows"]
    index = next(i for i, row in enumerate(rows) if row["metric"] == "profit")
    assert rows[index]["contribution"] == "5"
    evidence = service.drilldown_fact({"run_id": run["id"], "row": index})
    assert len(evidence["rows"]) == 6
    assert not any(r["voucher_detail_available"] for r in evidence["rows"])
    assert evidence["rows"][0]["data"]["account_code"].startswith("00")
    draft = service.save_explanation_draft(
        {
            "title": "利润说明",
            "body": "利润超预算 5 万元。",
            "run_ids": [run["id"]],
            "claims": [
                {
                    "basis": "calculation",
                    "run_id": run["id"],
                    "row": index,
                    "column": "contribution",
                    "value": "5",
                }
            ],
        }
    )
    assert draft["claims"][0]["verification_status"] == "matches_run"
    assert draft["claims"][0]["finance_scope"]["actual"]["unit"] == "万元"
    updated = service.save_explanation_draft(
        {
            "parent_id": draft["id"],
            "body": "预计来自促销，待核实。",
            "claims": [{"basis": "professional_judgment", "reason": "经理判断"}],
        }
    )
    assert next(c for c in updated["claims"] if c["basis"] == "professional_judgment")["verification_status"] == "unverified"
    assert service.analysis.get_draft(draft["id"])["body"] == draft["body"]
    assert draft["body"].startswith("利润超预算 5 万元。")
    assert "## 计算依据" in draft["body"]
    rerun = service.analysis.run_analysis(run["analysis_id"])
    assert rerun["output_hash"] == run["output_hash"]
    assert rerun["reproducibility_status"] == "reproducible"
    assert service.analysis.state()["runs"][-1]["id"] == rerun["id"]


def test_changed_calculated_value_cannot_keep_verification(finance):
    service, context = finance
    run = service.run_metric({"context_id": context["id"]})
    with pytest.raises(FoundryError, match="differs"):
        service.save_explanation_draft(
            {
                "run_ids": [run["id"]],
                "claims": [
                    {
                        "basis": "calculation",
                        "run_id": run["id"],
                        "row": 0,
                        "column": "profit",
                        "value": "999",
                    }
                ],
            }
        )


def test_session_ceiling_applies_to_context_runs_and_drilldown(finance):
    service, context = finance
    run = service.run_metric({"context_id": context["id"]})
    child = FinanceStore(service.task, snapshot_ids=[context["bindings"]["actual"]])
    assert child.list_finance_context()["contexts"] == []
    with pytest.raises(FoundryError, match="outside"):
        child.run_metric({"context_id": context["id"]})
    with pytest.raises(FoundryError, match="outside"):
        child.drilldown_fact({"run_id": run["id"], "row": 0})
    with pytest.raises(FoundryError, match="outside"):
        child.save_explanation_draft({"run_ids": [run["id"]], "body": "不可越权"})


def test_mapping_version_is_bound_to_context(finance):
    service, context = finance
    first = service.save_account_map(
        {"rows": [{"account_code": "001", "management_account": "revenue"}]}
    )
    newer = service.save_account_map(
        {
            "parent_id": first["id"],
            "rows": [{"account_code": "001", "management_account": "other"}],
        }
    )
    bound = service.save_context(
        {
            "bindings": context["bindings"],
            "scopes": context["scopes"],
            "account_map_id": first["id"],
        }
    )
    assert service._read("contexts", bound["id"])["account_map_id"] == first["id"]
    assert newer["parent_id"] == first["id"]
    assert (
        service._read("account_maps", first["id"])["rows"][0]["management_account"]
        == "revenue"
    )


def test_finance_calculation_failure_is_persisted_as_failed_run(finance):
    service, context = finance

    run = service.explain_variance(
        {"context_id": context["id"], "actual_filters": ["not", "an", "object"]}
    )

    assert run["execution_status"] == "failed"
    assert run["reproducibility_status"] == "unverified"
    assert run["output_hash"] is None
    assert run["error_code"] == "finance_calculation_failed"
    assert "comparison filters must be objects" in run["error"]
    assert service.analysis.get_run(run["id"])["execution_status"] == "failed"


def test_finance_rerun_output_mismatch_is_non_reproducible(finance, monkeypatch):
    service, context = finance
    values = iter(["1", "2"])

    def changing_metric(_normalized, _spec):
        return {
            "columns": [{"name": "value", "type": "decimal"}],
            "rows": [{"value": next(values)}],
            "diagnostics": [],
        }

    monkeypatch.setattr("foundry.finance_service.evaluate_metric", changing_metric)

    first = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    second = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )

    assert first["execution_status"] == "succeeded"
    assert second["execution_status"] == "succeeded"
    assert second["reproducibility_status"] == "non_reproducible"


def test_price_quantity_run_uses_account_alias_and_explicit_period_filters(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="量价桥")
    service = FinanceStore(task)
    bindings = {}
    for alias, scenario, quantity, price in (
        ("actual", "actual", "12", "11"),
        ("budget", "budget", "10", "10"),
    ):
        path = tmp_path / f"{alias}.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "ledger_id": "L1",
                        "organization_id": "O1",
                        "period": "2026-09",
                        "currency": "CNY",
                        "unit": "元",
                        "scenario": scenario,
                        "科目编码": "6001",
                        "qty": quantity,
                        "unit_price": price,
                        "product": "A",
                    },
                    {
                        "ledger_id": "L1",
                        "organization_id": "O1",
                        "period": "2026-08",
                        "currency": "CNY",
                        "unit": "元",
                        "scenario": scenario,
                        "科目编码": "6001",
                        "qty": "99",
                        "unit_price": "99",
                        "product": "A",
                    },
                    {
                        "ledger_id": "L1",
                        "organization_id": "O1",
                        "period": "2026-09",
                        "currency": "CNY",
                        "unit": "元",
                        "scenario": scenario,
                        "科目编码": "6401",
                        "qty": "99",
                        "unit_price": "99",
                        "product": "A",
                    },
                ],
                ensure_ascii=False,
            )
        )
        bindings[alias] = service.analysis.add_dataset(path, name=alias)["id"]
    context = service.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "currency": "CNY",
                    "unit": "元",
                    "scenario": scenario,
                }
                for alias, scenario in (("actual", "actual"), ("budget", "budget"))
            },
            "policies": {
                alias: {"field_map": {"quantity": "qty", "price": "unit_price"}}
                for alias in bindings
            },
        }
    )

    run = service.explain_variance(
        {
            "context_id": context["id"],
            "kind": "price_quantity",
            "dimensions": ["product"],
            "actual_filters": {"period": "2026-09", "account_code": "6001"},
            "baseline_filters": {"period": "2026-09", "account_code": "6001"},
        }
    )

    assert run["execution_status"] == "succeeded"
    assert run["result"]["rows"][0]["total_variance"] == "32"
    assert run["result"]["rows"][0]["quantity_contribution"] == "20"
    assert len(run["result"]["rows"][0]["source_rows"]) == 2


def test_retried_completion_does_not_create_a_second_draft(finance):
    service, context = finance
    run = service.explain_variance({'context_id': context['id']})
    spec = {'title': '完成检查', 'body': '查看计算依据。', 'run_ids': [run['id']]}
    first = service.save_explanation_draft(spec)
    reopened = FinanceStore(service.task)
    second = reopened.save_explanation_draft(spec)
    assert second['id'] == first['id']
    assert second['completion']['id'] == first['completion']['id']
    assert len(service.analysis._list('drafts')) == 1
    changed = reopened.save_explanation_draft({**spec, 'body': '补充经理判断。'})
    assert changed['id'] != first['id']


def test_source_read_failure_retains_editable_draft(finance, monkeypatch):
    service, context = finance
    service.analysis_requirements_save({'context_id': context['id'], 'question': '解释利润并下钻',
        'items': [{'id': 'profit', 'metric': 'profit', 'requires_drilldown': True}]})
    run = service.explain_variance({'context_id': context['id']})
    def unavailable(spec):
        raise FoundryError('source temporarily unavailable')
    monkeypatch.setattr(service, 'drilldown_fact', unavailable)
    draft = service.save_explanation_draft({'body': '查看计算依据。', 'run_ids': [run['id']]})
    assert service.analysis.get_draft(draft['id'])['body'] == draft['body']
    assert draft['quality']['checks']['provenance']['status'] == 'needs_attention'
    assert any(issue['code'] == 'requested_source_missing' for issue in draft['quality']['issues'])
    assert draft['source_read_failures']


def test_materiality_definition_survives_save_edit_and_reload(finance):
    service, context = finance
    run = service.explain_variance({'context_id': context['id']})
    materiality = {'absolute': '10', 'relative': {'threshold': '0.1',
                    'denominator': 'baseline_abs', 'negative_policy': 'absolute'}}
    draft = service.save_explanation_draft({'body': '查看计算依据。', 'run_ids': [run['id']],
                                          'materiality': materiality})
    assert draft['materiality'] == materiality
    updated = service.save_explanation_draft({'parent_id': draft['id'], 'body': '经理补充判断。'})
    assert updated['materiality'] == materiality
    assert service.analysis.get_draft(updated['id'])['materiality'] == materiality


def test_concurrent_identical_completions_create_one_draft(finance):
    from concurrent.futures import ThreadPoolExecutor
    service, context = finance
    run = service.explain_variance({'context_id': context['id']})
    spec = {'title': '并发重试', 'body': '查看计算依据。', 'run_ids': [run['id']]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: FinanceStore(service.task).save_explanation_draft(spec), range(2)))
    assert results[0]['id'] == results[1]['id']
    assert len(service.analysis._list('drafts')) == 1


def test_retry_recovers_after_draft_committed_before_receipt(finance, monkeypatch):
    import foundry.finance_completion as completion
    service, context = finance
    run = service.explain_variance({'context_id': context['id']})
    spec = {'body': '查看计算依据。', 'run_ids': [run['id']]}
    original = completion.record_completion
    def interrupted(*args):
        raise FoundryError('interrupted before receipt')
    monkeypatch.setattr(completion, 'record_completion', interrupted)
    with pytest.raises(FoundryError, match='interrupted'):
        service.save_explanation_draft(spec)
    assert len(service.analysis._list('drafts')) == 1
    monkeypatch.setattr(completion, 'record_completion', original)
    result = FinanceStore(service.task).save_explanation_draft(spec)
    assert result['completion']['draft_id'] == result['id']
    assert len(service.analysis._list('drafts')) == 1


def test_numeric_pass_without_task_requirements_is_not_complete(finance):
    service, context = finance
    run = service.explain_variance({'context_id': context['id']})
    draft = service.save_explanation_draft({'body': '查看计算依据。', 'run_ids': [run['id']]})
    assert draft['completion']['status'] == 'needs_requirements'
    assert any(action['code'] == 'requirements_not_defined' for action in draft['completion']['actions'])


def test_empty_requirements_cannot_mark_workflow_complete(finance):
    service, context = finance
    service.analysis_requirements_save({'context_id': context['id'], 'question': '解释利润', 'items': []})
    run = service.explain_variance({'context_id': context['id']})
    draft = service.save_explanation_draft({'body': '查看计算依据。', 'run_ids': [run['id']]})
    assert draft['completion']['status'] == 'needs_requirements'


def test_replay_marks_historical_validation_and_authorizes_original_scope(finance):
    service, context = finance
    requirement = service.analysis_requirements_save({'context_id': context['id'], 'question': '解释利润',
        'items': [{'id': 'profit', 'metric': 'profit'}]})
    spec = {'body': '经理的背景说明。', 'run_ids': []}
    draft = service.save_explanation_draft(spec)
    replay = service.save_explanation_draft(spec)
    assert replay['replayed'] is True
    assert replay['validation_basis'] == 'saved_draft_version'
    restricted = FinanceStore(service.task, snapshot_ids=[])
    with pytest.raises(FoundryError, match='outside'):
        restricted.save_explanation_draft({'parent_id': draft['id']})
    assert draft['requirements_id'] == requirement['id']


def test_completion_requests_fresh_run_after_requirements_revision(finance):
    from foundry.finance_completion import record_completion

    service, context = finance
    old_run = service.explain_variance({'context_id': context['id']})
    requirement = service.analysis_requirements_save({
        'question': '解释利润变化', 'context_id': context['id'],
        'items': [{'id': 'profit', 'metric': 'profit'}],
    })
    quality = {
        'status': 'pass', 'issues': [], 'checks': {},
        'requirements': {'requirements_id': requirement['id'],
                         'coverage': {'status': 'pass'}, 'provenance': {'status': 'pass'}},
    }
    draft = {'id': 'a' * 32, 'content_hash': 'old-run-draft', 'run_ids': [old_run['id']]}
    stopped = record_completion(service.analysis, draft, quality)
    assert stopped['status'] == 'repair_available'
    assert stopped['actions'][0]['code'] == 'requirements_run_outdated'
    assert stopped['actions'][0]['run_ids'] == [old_run['id']]
    assert stopped['completion_policy_version'] == 4
    assert record_completion(service.analysis, draft, quality)['id'] == stopped['id']

    fresh_run = service.explain_variance({'context_id': context['id']})
    assert fresh_run['output_hash'] == old_run['output_hash']
    fresh = record_completion(service.analysis, {
        'id': 'b' * 32, 'content_hash': 'fresh-run-draft', 'run_ids': [fresh_run['id']],
    }, quality)
    assert fresh['status'] == 'complete'
    assert fresh['stop_reason'] == 'complete'
    assert not fresh['actions']


def test_saved_draft_reuses_equivalent_requirement_run_with_actual_checks(finance):
    service, context = finance
    original = service.analysis_requirements_save({
        'question': '解释收入变化', 'context_id': context['id'],
        'items': [{'id': 'revenue', 'metric': 'revenue=price×quantity',
                   'label': '收入', 'requires_drilldown': True}],
    })
    run = service.explain_variance({'context_id': context['id']})
    current = service.analysis_requirements_save({
        'question': original['question'], 'context_id': context['id'],
        'parent_id': original['id'],
        'items': [{'id': 'revenue', 'metric': 'revenue',
                   'label': '收入', 'requires_drilldown': True}],
    })
    draft = service.save_explanation_draft({
        'requirements_id': current['id'], 'run_ids': [run['id']],
        'body': '收入增加20万元。',
    })
    assert draft['explanation_check']['status'] == 'pass'
    assert draft['explanation_check']['requirements']['coverage']['status'] == 'pass'
    assert draft['explanation_check']['requirements']['provenance']['status'] == 'pass'
    assert draft['completion']['status'] == 'complete'
    assert draft['completion']['reused_run_ids'] == [run['id']]


@pytest.mark.parametrize("field", ["operation_id", "operation_intent", "completion_request_key"])
def test_model_cannot_declare_completion_authority(finance, field):
    service, _ = finance
    with pytest.raises(FoundryError, match="authority"):
        service.save_explanation_draft({"title": "稿", "body": "继续讨论", field: "manager_save"})
    assert service.analysis.state()["drafts"] == []


def test_runtime_completion_save_replays_and_manager_remains_free(finance, monkeypatch):
    from foundry.finance_completion_operations import CompletionOperationStore
    service, _ = finance
    service.session_id = "trusted-test-runtime"
    operations = CompletionOperationStore(service.task, service.session_id)
    operation = operations.begin("user-message-1", policy={"max_repairs": 0})
    spec = {"title": "待核对", "body": "资料有待进一步核查。"}
    first = service.save_completion_draft(operation["id"], "runtime-call-1", spec)
    assert first["completion_operation"]["status"] == "needs_review"
    from foundry import finance_completion
    with monkeypatch.context() as patch:
        def no_recalculation(*args, **kwargs):
            raise AssertionError("settled replay must use its original completion receipt")
        patch.setattr(finance_completion, "record_completion", no_recalculation)
        again = service.save_completion_draft(operation["id"], "runtime-call-1", spec)
    assert again["completion"]["id"] == first["completion"]["id"]
    assert again["id"] == first["id"]
    assert again["replayed"] is True
    with pytest.raises(FoundryError):
        service.save_completion_draft(operation["id"], "runtime-call-2", {**spec, "body": "自动再修"})
    manual = service.save_explanation_draft({**spec, "body": "经理补充判断，仍可保存。"})
    assert manual["id"] != first["id"]
    assert len(service.analysis.state()["drafts"]) == 2


def test_runtime_completion_payload_conflict_and_session_mismatch(finance):
    from foundry.finance_completion_operations import CompletionOperationStore
    service, _ = finance
    service.session_id = "runtime-a"
    operations = CompletionOperationStore(service.task, service.session_id)
    operation = operations.begin("manager-message")
    spec = {"title": "说明", "body": "待核查"}
    service.save_completion_draft(operation["id"], "call-1", spec)
    with pytest.raises(FoundryError, match="conflict"):
        service.save_completion_draft(operation["id"], "call-1", {**spec, "body": "不同正文"})
    service.session_id = "runtime-b"
    with pytest.raises(FoundryError, match="session"):
        service.save_completion_draft(operation["id"], "call-2", spec)


def test_completion_deadline_keeps_saved_draft_and_pending_body(finance, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from foundry import finance_completion_operations as module
    service, context = finance
    previous = service.save_explanation_draft({"title": "已有成果", "body": "经理原有记录。"})
    run = service.explain_variance({"context_id": context["id"]})
    service.session_id = "deadline-runtime"
    moment = [datetime(2026, 9, 7, tzinfo=timezone.utc)]
    monkeypatch.setattr(module, "_utc_now", lambda clock: moment[0])
    operations = module.CompletionOperationStore(service.task, service.session_id)
    operation = operations.begin("user-event", policy={"timeout_seconds": 1})
    prepare = service.prepare_explanation

    def slow_prepare(spec):
        result = prepare(spec)
        moment[0] += timedelta(seconds=2)
        return result

    monkeypatch.setattr(service, "prepare_explanation", slow_prepare)
    payload = {"title": "正在形成的说明", "body": "这段新正文需要保留。", "run_ids": [run["id"]]}
    with pytest.raises(FoundryError, match="stopped.*timeout"):
        service.save_completion_draft(operation["id"], "save-call", payload)
    stopped = operations.get(operation["id"])
    assert stopped["status"] == "timed_out"
    assert stopped["revisions"][0]["payload"]["body"] == payload["body"]
    assert service.analysis.state()["drafts"][-1]["id"] == previous["id"]
    manual = service.save_explanation_draft({"title": "经理继续记录", "body": "超时后仍能编辑保存。"})
    assert manual["id"] != previous["id"]
