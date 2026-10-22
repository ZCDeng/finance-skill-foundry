"""Current-month inputs are explicit, executed and archived; never code replacement."""
import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.task import TaskStore


def period_store(tmp_path, period="2026-09", rows=None):
    store = AnalysisStore(TaskStore(tmp_path / "var").create(title="期间绑定", period=period))
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(rows or [{"期间": period, "金额": "1200"}]), encoding="utf-8")
    data = store.add_dataset(path, name="ledger")
    return store, data


def test_current_month_parameter_is_resolved_at_execution_and_recorded(tmp_path):
    store, data = period_store(tmp_path)
    revision = store.save_analysis({
        "question": "本期收入", "bindings": {"ledger": data["id"]},
        "sql": "select $period as period, sum(金额) as amount from ledger where 期间=$period",
        "parameters": {"period": "2026-08"},
        "period_binding": {"mode": "current", "parameters": ["period"]},
    })
    run = store.run_analysis(revision["id"])
    assert run["execution_status"] == "succeeded"
    assert run["parameters"] == {"period": "2026-09"}
    assert run["result"]["rows"] == [{"period": "2026-09", "amount": "1200"}]
    assert run["resolved_period"]["period"] == "2026-09"
    assert store.get_analysis(revision["id"])["parameters"] == {"period": "2026-08"}


def test_positional_month_binding_keeps_fixed_comparison_parameter(tmp_path):
    store, data = period_store(tmp_path)
    saved = store.save_analysis({
        "question": "本期和固定基期", "bindings": {"ledger": data["id"]},
        "sql": "select ? as period, ? as comparison from ledger",
        "parameters": ["2026-08", "2025-08"],
        "period_binding": {"mode": "current", "parameters": [1]},
    })
    run = store.run_analysis(saved["id"])
    assert run["parameters"] == ["2026-09", "2025-08"]


@pytest.mark.parametrize("binding", [
    {"mode": "current", "parameters": ["missing"]},
    {"mode": "current", "parameters": ["period", "period"]},
    {"mode": "current", "parameters": []},
    {"mode": "unknown", "parameters": ["period"]},
])
def test_invalid_binding_is_rejected_before_revision_write(tmp_path, binding):
    store, data = period_store(tmp_path)
    before = store.state()["analyses"]
    with pytest.raises(FoundryError, match="period"):
        store.save_analysis({"question": "本期", "bindings": {"ledger": data["id"]},
                             "sql": "select $period from ledger", "parameters": {"period": "2026-08"},
                             "period_binding": binding})
    assert store.state()["analyses"] == before


def test_conflicting_source_and_target_period_is_refused(tmp_path):
    store, data = period_store(tmp_path, rows=[{"期间": "2026-08", "金额": "1200"}])
    saved = store.save_analysis({"question": "本期", "bindings": {"ledger": data["id"]},
                                 "sql": "select $period from ledger", "parameters": {"period": "2026-08"},
                                 "period_binding": {"mode": "current", "parameters": ["period"]}})
    with pytest.raises(FoundryError, match="period|期间"):
        store.run_analysis(saved["id"])


def test_aggregate_only_binds_declared_period_filter(tmp_path):
    store, data = period_store(tmp_path)
    saved = store.save_analysis({
        "question": "本期", "engine": "structured_aggregate", "bindings": {"ledger": data["id"]},
        "period_binding": {"mode": "current", "filter_fields": ["期间"]},
        "aggregate_plan": {"dataset_alias": "ledger", "filters": [{"field": "期间", "op": "eq", "value": "2026-08"}],
                           "group_by": ["期间"], "measures": [{"name": "amount", "field": "金额", "aggregation": "sum"}]},
    })
    run = store.run_analysis(saved["id"])
    assert run["result"]["rows"][0]["amount"] == "1200"
    assert run["aggregate_plan"]["filters"][0]["value"] == "2026-09"


def test_mixed_month_source_is_refused_even_when_scope_is_absent(tmp_path):
    store, data = period_store(tmp_path, rows=[{"期间": "2026-08", "金额": "10"}, {"期间": "2026-09", "金额": "20"}])
    saved = store.save_analysis({"question": "本期", "bindings": {"ledger": data["id"]},
                                 "sql": "select $period from ledger", "parameters": {"period": "2026-08"},
                                 "period_binding": {"mode": "current", "parameters": ["period"]}})
    with pytest.raises(FoundryError, match="多个期间"):
        store.run_analysis(saved["id"])


def test_latest_requirements_period_overrides_task_creation_month(tmp_path):
    from foundry.finance_requirements import save_requirements

    store, data = period_store(tmp_path, period="2026-08", rows=[{"期间": "2026-09", "金额": "1200"}])
    save_requirements(store, {"question": "九月分析", "scope": {"period": "2026-09"},
                              "bindings": {"ledger": data["id"]}, "items": []})
    saved = store.save_analysis({"question": "本期", "bindings": {"ledger": data["id"]},
                                 "sql": "select $period as period from ledger", "parameters": {"period": "2026-08"},
                                 "period_binding": {"mode": "current", "parameters": ["period"]}})
    run = store.run_analysis(saved["id"])
    assert run["resolved_period"] == {"period": "2026-09", "source": "requirements"}
    assert run["scope"]["period"] == "2026-09"


def test_period_context_changes_execution_input_hash_on_identical_data(tmp_path):
    store, data = period_store(tmp_path, rows=[{"金额": "1200"}])
    saved = store.save_analysis({"question": "本期", "bindings": {"ledger": data["id"]},
                                 "sql": "select $period as period from ledger", "parameters": {"period": "2026-08"},
                                 "period_binding": {"mode": "current", "parameters": ["period"]}})
    september = store.run_analysis(saved["id"])
    metadata = store.task.meta()
    metadata["period"] = "2026-10"
    store.task.meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    october = store.run_analysis(saved["id"])
    assert september["input_hashes"] == october["input_hashes"]
    assert september["fingerprint"] != october["fingerprint"]
    assert september["execution_input_hash"] != october["execution_input_hash"]


def test_recompute_uses_original_frozen_run_period_after_source_task_period_changes(tmp_path):
    from foundry.dashboard_recompute import NotRerun, recipe_of, validate_period_move
    from foundry.finance_service import FinanceStore

    store, data = period_store(tmp_path, period="2026-08", rows=[{"金额": "1200"}])
    saved = store.save_analysis({"question": "本期", "bindings": {"ledger": data["id"]},
                                 "sql": "select $period as period, '2026-08' as stale_label from ledger",
                                 "parameters": {"period": "2026-08"},
                                 "period_binding": {"mode": "current", "parameters": ["period"]}})
    run = store.run_analysis(saved["id"])
    metadata = store.task.meta()
    metadata["period"] = "2026-09"
    store.task.meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    recipe = recipe_of(FinanceStore(store.task, actor="manager"), run, elsewhere=True)
    with pytest.raises(NotRerun, match="计算里写着 2026-08"):
        validate_period_move(recipe, "2026-09")


def test_legacy_dated_query_cannot_trust_a_later_changed_source_task_period(tmp_path):
    from foundry.dashboard_recompute import NotRerun, recipe_of, validate_period_move
    from foundry.finance_service import FinanceStore

    store, data = period_store(tmp_path, period="2026-08", rows=[{"金额": "1200"}])
    saved = store.save_analysis({"question": "旧定义", "bindings": {"ledger": data["id"]},
                                 "sql": "select '2026-08' as period, sum(金额) as amount from ledger"})
    run = store.run_analysis(saved["id"])
    metadata = store.task.meta()
    metadata["period"] = "2026-09"
    store.task.meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    recipe = recipe_of(FinanceStore(store.task, actor="manager"), run, elsewhere=True)
    with pytest.raises(NotRerun, match="原计算期间"):
        validate_period_move(recipe, "2026-09")


def test_script_job_freezes_period_when_dispatched_and_keeps_it_on_retry(tmp_path, monkeypatch):
    from foundry.analysis_jobs import JobStore
    from foundry.context import resolve_context

    store, data = period_store(tmp_path)
    store.task.record_session("parent", role="analysis")
    store.task.update_session_context("parent", snapshot_ids=[data["id"]])
    context = resolve_context(store.task.store.var_root, session_id="parent")
    monkeypatch.setattr(JobStore, "_launch", lambda *_: None)
    jobs = JobStore(store.task)
    job = jobs.create(context, "script", {"code": "print(1)", "bindings": {"ledger": data["id"]},
                                           "period_binding": {"mode": "current"}})
    assert job["context"]["resolved_period"]["period"] == "2026-09"
    jobs.settle(job["id"], "failed", {"error": "interrupted"}, session_id="parent", child_session_id=job["child_session_id"])
    metadata = store.task.meta()
    metadata["period"] = "2026-10"
    store.task.meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    retry = jobs.retry(job["id"], context)
    assert retry["context"]["resolved_period"] == job["context"]["resolved_period"]
