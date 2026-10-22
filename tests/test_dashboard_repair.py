from __future__ import annotations

import hashlib
import json

import pytest

from foundry.dashboard_repair import propose, read, verified_repair
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def _files(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _pending(tmp_path, *, declared_periods=True, scope=True):
    tasks = TaskStore(tmp_path / "var")
    source = FinanceStore(tasks.create(title="八月经营看板", period="2026-08"), actor="manager")
    target = FinanceStore(tasks.create(title="九月经营看板", period="2026-09"), actor="manager")
    datasets = []
    for manager, month, amount in [(source, "2026-08", 100), (target, "2026-09", 200)]:
        path = tmp_path / f"{month}.json"
        path.write_text(json.dumps([{"entity": f"项目 {i}", "amount": str(amount + i),
                                     **({"period": month} if declared_periods else {})}
                                    for i in range(9)]), encoding="utf8")
        datasets.append(manager.analysis.add_dataset(path, name="经营指标",
                                                     metadata={"period": month} if declared_periods else {}))
    revision = source.analysis.save_analysis({
        "question": "本期经营指标", "bindings": {"ledger": datasets[0]["id"]},
        "sql": "select entity, amount, '2026-08' as period from ledger order by entity",
        **({"scope": {"period": "2026-08"}} if scope else {}),
    })
    run = source.analysis.run_analysis(revision["id"])
    board = source.dashboard_save({"cards": [
        {"kind": "figure", "title": f"项目 {i}", "run_id": run["id"], "state": "accepted",
         "select": {"match": {"entity": f"项目 {i}", "period": "2026-08"}, "column": "amount"}}
        for i in range(9)
    ]})
    attempt = {
        "id": "f" * 32, "from_task_id": source.task.id, "source_board_id": board["id"],
        "target_period": "2026-09",
        "failed": [{"run_id": run["id"], "card_id": card["id"], "title": card["title"],
                    "code": "period_literal", "reason": "计算里写着 2026-08"} for card in board["cards"]],
        "plans": {run["id"]: {"bindings": {"ledger": datasets[1]["id"]}}},
    }
    target._carry_attempt = lambda: attempt
    return source, target, run, revision, board, attempt


def _candidate():
    return {"sql": "select entity, amount, $period as period from ledger order by entity",
            "parameters": {"period": "2026-08"}, "period_binding": {"mode": "current", "parameters": ["period"]}}


def test_repair_read_exposes_only_the_manager_requested_algorithm_and_no_raw_rows(tmp_path):
    source, target, run, revision, board, attempt = _pending(tmp_path)
    before = _files(source.task.root)
    out = read(target, {})
    assert out["attempt_id"] == attempt["id"] and out["target_period"] == "2026-09"
    assert len(out["repairs"]) == 1
    item = out["repairs"][0]
    assert item["run_id"] == run["id"] and item["revision_id"] == revision["id"]
    assert item["card_ids"] == [card["id"] for card in board["cards"]]
    assert item["spec"]["sql"] == revision["sql"]
    assert '"rows":' not in json.dumps(out) and '"result":' not in json.dumps(out)
    assert _files(source.task.root) == before


def test_legacy_parameterization_replays_original_month_then_proposes_new_run_without_accepting(tmp_path):
    source, target, run, revision, board, attempt = _pending(tmp_path)
    before = _files(source.task.root)
    record = propose(target, {"run_id": run["id"], "spec": _candidate()})
    assert record["source_run_id"] == run["id"] and record["source_board_id"] == board["id"]
    assert record["attempt_id"] == attempt["id"] and record["baseline"]["verified"] is True
    assert record["baseline"]["source_result_hash"] == record["baseline"]["replayed_result_hash"]
    new = verified_repair(target, attempt, run["id"], attempt["plans"][run["id"]]["bindings"])
    assert new["id"] == record["run_id"]
    assert new["parameters"] == {"period": "2026-09"}
    assert {row["period"] for row in new["result"]["rows"]} == {"2026-09"}
    assert new["result"]["rows"][0]["amount"] == "200"
    assert target._dashboard() is None
    assert _files(source.task.root) == before
    assert source.analysis.get_analysis(revision["id"])["sql"] == revision["sql"]
    assert all(card["state"] == "accepted" for card in source._dashboard()["cards"])


def test_a_changed_formula_is_rejected_before_any_target_run_is_created(tmp_path):
    source, target, run, _, _, _ = _pending(tmp_path)
    before_source, before_target = _files(source.task.root), _files(target.task.root)
    candidate = {**_candidate(), "sql": "select entity, amount + 1 as amount, $period as period from ledger order by entity"}
    with pytest.raises(FoundryError, match="原月.*不一致"):
        propose(target, {"run_id": run["id"], "spec": candidate})
    assert _files(source.task.root) == before_source
    assert _files(target.task.root) == before_target


def test_repair_requires_explicit_period_binding_and_keeps_source_bindings_server_owned(tmp_path):
    _, target, run, _, _, attempt = _pending(tmp_path)
    candidate = _candidate()
    candidate.pop("period_binding")
    with pytest.raises(FoundryError, match="period_binding"):
        propose(target, {"run_id": run["id"], "spec": candidate})
    candidate = {**_candidate(), "bindings": {"untrusted": "0" * 32}, "scope": {"period": "1900-01"}}
    record = propose(target, {"run_id": run["id"], "spec": candidate})
    new = target.analysis.get_run(record["run_id"])
    assert new["bindings"] == attempt["plans"][run["id"]]["bindings"]
    assert new["scope"] == {"period": "2026-09"}


def test_missing_carry_authority_or_snapshot_ceiling_never_exposes_another_tasks_algorithm(tmp_path):
    _, target, run, _, _, attempt = _pending(tmp_path)
    target._carry_attempt = lambda: None
    with pytest.raises(FoundryError, match="带入"):
        read(target, {})
    target._carry_attempt = lambda: attempt
    with pytest.raises(FoundryError, match="待修复"):
        read(target, {"run_id": "0" * 32})
    target.allowed = set()
    with pytest.raises(FoundryError, match="outside this session"):
        read(target, {})
    with pytest.raises(FoundryError, match="outside this session"):
        propose(target, {"run_id": run["id"], "spec": _candidate()})


def test_verified_repair_is_invalidated_by_changed_attempt_period_or_bindings(tmp_path):
    _, target, run, _, _, attempt = _pending(tmp_path)
    propose(target, {"run_id": run["id"], "spec": _candidate()})
    bindings = attempt["plans"][run["id"]]["bindings"]
    for key, value in [("id", "e" * 32), ("target_period", "2026-10"), ("source_board_id", "d" * 32)]:
        changed = {**attempt, key: value}
        assert verified_repair(target, changed, run["id"], bindings) is None
    assert verified_repair(target, attempt, run["id"], {"ledger": "a" * 32}) is None


def test_a_binding_does_not_authorize_other_old_month_literals_or_engine_changes(tmp_path):
    _, target, run, _, _, _ = _pending(tmp_path)
    with pytest.raises(FoundryError, match="engine"):
        propose(target, {"run_id": run["id"], "spec": {**_candidate(), "engine": "python"}})
    candidate = {**_candidate(), "sql": "select entity, amount, '2026-08' as period from ledger where $period='2026-08' order by entity"}
    with pytest.raises(FoundryError, match="2026-08"):
        propose(target, {"run_id": run["id"], "spec": candidate})


def test_the_read_spec_can_be_round_tripped_but_unrelated_metadata_cannot_change(tmp_path):
    _, target, run, _, _, _ = _pending(tmp_path)
    spec = read(target, {"run_id": run["id"]})["repairs"][0]["spec"]
    with pytest.raises(FoundryError, match="calculation fields"):
        propose(target, {"run_id": run["id"], "spec": {**spec, **_candidate(), "question": "另一个问题"}})
    record = propose(target, {"run_id": run["id"], "spec": {**spec, **_candidate()}})
    assert record["baseline"]["verified"]


def test_missing_original_scope_and_dataset_period_replay_against_the_frozen_task_month(tmp_path):
    source, target, run, _, _, attempt = _pending(tmp_path, declared_periods=False, scope=False)
    before = _files(source.task.root)
    record = propose(target, {"run_id": run["id"], "spec": _candidate()})
    assert record["baseline"]["source_period"] == "2026-08"
    new = verified_repair(target, attempt, run["id"], attempt["plans"][run["id"]]["bindings"])
    assert new["scope"]["period"] == "2026-09"
    assert _files(source.task.root) == before


@pytest.mark.parametrize("changed", ["task_period", "requirements", "new_file"])
def test_current_period_or_files_invalidate_a_previously_verified_carry_attempt(tmp_path, changed):
    _, target, run, _, _, attempt = _pending(tmp_path, declared_periods=False, scope=False)
    propose(target, {"run_id": run["id"], "spec": _candidate()})
    bindings = attempt["plans"][run["id"]]["bindings"]
    if changed == "task_period":
        target.task.meta_path.write_text(json.dumps({**target.task.meta(), "period": "2026-10"}), encoding="utf8")
    elif changed == "requirements":
        target.analysis_requirements_save({"question": "十月经营指标", "scope": {"period": "2026-10"},
                                           "bindings": bindings, "items": []})
    else:
        path = tmp_path / "updated.json"
        path.write_text(json.dumps([{"entity": f"项目 {i}", "amount": str(300 + i)} for i in range(9)]), encoding="utf8")
        target.analysis.add_dataset(path, name="经营指标")
    before = _files(target.task.root)
    assert verified_repair(target, attempt, run["id"], bindings) is None
    with pytest.raises(FoundryError, match="目标.*已.*"):
        read(target, {})
    with pytest.raises(FoundryError, match="目标.*已.*"):
        propose(target, {"run_id": run["id"], "spec": _candidate()})
    assert _files(target.task.root) == before


def _use_run(source, attempt, run):
    current = source._dashboard()
    board = source.dashboard_save({"parent_id": current["id"], "cards": [
        {**card, "run_id": run["id"]} for card in current["cards"]
    ]})
    plan = next(iter(attempt["plans"].values()))
    attempt.update({"source_board_id": board["id"], "plans": {run["id"]: plan}, "failed": [
        {"run_id": run["id"], "card_id": card["id"], "title": card["title"],
         "code": "period_literal", "reason": "计算里写着 2026-08"} for card in board["cards"]
    ]})


def test_structured_aggregate_filter_upgrade_replays_source_rows_then_moves_the_declared_filter(tmp_path):
    source, target, _, revision, _, attempt = _pending(tmp_path)
    revision = source.analysis.save_analysis({
        "question": "本期经营指标", "engine": "structured_aggregate", "bindings": revision["bindings"],
        "scope": {"period": "2026-08"}, "aggregate_plan": {
            "dataset_alias": "ledger", "group_by": ["entity", "period"],
            "filters": [{"field": "period", "op": "eq", "value": "2026-08"}], "exclusions": [],
            "measures": [{"name": "amount", "field": "amount", "aggregation": "sum"}],
            "result_key_columns": ["entity", "period"], "dedupe": {"policy": "none"},
        },
    })
    run = source.analysis.run_analysis(revision["id"])
    _use_run(source, attempt, run)
    before = _files(source.task.root)
    record = propose(target, {"run_id": run["id"], "spec": {
        "period_binding": {"mode": "current", "filter_fields": ["period"]}}})
    new = verified_repair(target, attempt, run["id"], attempt["plans"][run["id"]]["bindings"])
    assert record["baseline"]["verified"] and new["engine"] == "structured_aggregate"
    assert new["aggregate_plan"]["filters"] == [{"field": "period", "op": "eq", "value": "2026-09"}]
    assert {row["period"] for row in new["result"]["rows"]} == {"2026-09"}
    assert [row["amount"] for row in new["result"]["rows"]] == [str(200 + i) for i in range(9)]
    assert all(row["source_rows"][0]["dataset_id"] == new["bindings"]["ledger"] for row in new["result"]["rows"])
    assert _files(source.task.root) == before and target._dashboard() is None


def test_script_upgrade_uses_the_frozen_context_on_each_month_and_keeps_source_artifacts(tmp_path):
    from foundry.runner import runner_capabilities

    if not runner_capabilities()["available"]:
        pytest.skip("Real macOS sandbox-exec is not installed on this platform")
    source, target, _, revision, _, attempt = _pending(tmp_path)
    code = '''import json, os
from pathlib import Path
period = "2026-08"
rows = json.loads((Path(os.environ["FOUNDRY_INPUTS"]) / "ledger.json").read_text())["rows"]
output = [{"entity": row["entity"], "amount": row["amount"], "period": period} for row in rows]
(Path(os.environ["FOUNDRY_OUTPUTS"]) / "result.json").write_text(json.dumps(output))
'''
    run = source.analysis.run_script({"question": "本期经营指标", "bindings": revision["bindings"],
                                      "language": "python", "code": code, "result_file": "result.json",
                                      "scope": {"period": "2026-08"}})
    assert run["execution_status"] == "succeeded", run
    _use_run(source, attempt, run)
    before = _files(source.task.root)
    replacement = code.replace('period = "2026-08"',
                               'period = json.loads(Path(os.environ["FOUNDRY_CONTEXT"]).read_text())["period"]')
    record = propose(target, {"run_id": run["id"], "spec": {"code": replacement,
                                                                          "period_binding": {"mode": "current"}}})
    new = verified_repair(target, attempt, run["id"], attempt["plans"][run["id"]]["bindings"])
    assert record["baseline"]["verified"] and new["engine"] == "python"
    assert new["resolved_period"]["period"] == "2026-09"
    assert {row["period"] for row in new["result"]["rows"]} == {"2026-09"}
    assert new["result"]["rows"][0]["amount"] == "200"
    assert _files(source.task.root) == before and target._dashboard() is None
