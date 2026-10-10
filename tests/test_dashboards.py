from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

KPI = [
    {"指标": "营业收入", "本年累计": "1000", "上年同期累计": "950"},
    {"指标": "营业成本", "本年累计": "813", "上年同期累计": "780"},
    {"指标": "期间费用", "本年累计": "70", "上年同期累计": "66"},
    {"指标": "本年账单收缴率", "本年累计": "87.32%", "上年同期累计": "89.10%"},
]
CITY = [
    {"城市": "海口", "收入": "400", "成本": "300", "费用": "30", "收缴率": "92%"},
    {"城市": "三亚", "收入": "300", "成本": "270", "费用": "25", "收缴率": "80%"},
    {"城市": "儋州", "收入": "200", "成本": "160", "费用": "20", "收缴率": "86%"},
]


def _cell(name: str, column: str = "本年累计") -> dict:
    return {"alias": "kpi", "match": {"指标": name}, "column": column}


def _board(tmp_path: Path):
    """A manager's task with one collection-health run over a group and three cities."""
    task = TaskStore(tmp_path / "var").create(title="看板")
    manager = FinanceStore(task, actor="manager")
    bindings = {}
    for alias, rows in {"kpi": KPI, "city": CITY}.items():
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        bindings[alias] = AnalysisStore(task).add_dataset(path, name=alias)["id"]
    context = manager.save_context({"bindings": bindings, "scopes": {alias: {"currency": "CNY", "unit": "万元"} for alias in bindings}})
    scenario = manager.save_scenario({
        "context_id": context["id"], "kind": "collection_health", "label": "回款健康",
        "inputs": {
            "entities": [{"name": "集团", "values": {
                "revenue": _cell("营业收入"), "cost": _cell("营业成本"), "period_expense": _cell("期间费用"),
                "collection_rate_current": _cell("本年账单收缴率"),
                "revenue_py": _cell("营业收入", "上年同期累计"), "cost_py": _cell("营业成本", "上年同期累计"),
                "period_expense_py": _cell("期间费用", "上年同期累计"),
                "collection_rate_current_py": _cell("本年账单收缴率", "上年同期累计"),
            }}],
            "entity_tables": [{"alias": "city", "name_column": "城市", "columns": {
                "revenue": "收入", "cost": "成本", "period_expense": "费用", "collection_rate_current": "收缴率"}}],
        },
    })
    run = manager.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    return manager, run, bindings


def _gap(run: dict, title: str = "集团距生死线", state: str = "pinned") -> dict:
    return {"kind": "figure", "title": title, "state": state, "run_id": run["id"], "template": "collection",
            "select": {"match": {"entity": "集团", "metric_key": "collection_gap", "scenario": "本期"}, "column": "value"}}


def _rank(run: dict) -> dict:
    return {"kind": "rank", "title": "距生死线（从低到高）", "run_id": run["id"], "template": "city",
            "select": {"match": {"metric_key": "collection_gap", "scenario": "本期", "entity_origin": "table"},
                       "label": "entity", "column": "value", "order": "asc", "limit": 10,
                       "reference": {"value": "0", "label": "生死线"}}}


def test_a_board_is_versioned_and_keeps_each_card_on_the_rows_it_names(tmp_path):
    manager, run, _ = _board(tmp_path)
    assert manager.dashboard_read({}) == {"dashboard": None}
    first = manager.dashboard_save({"parent_id": None, "cards": [_gap(run), _rank(run)]})
    assert [card["state"] for card in first["cards"]] == ["pinned", "pinned"]
    assert all(card["proposed_by"] == "manager" and card["accepted"] is None for card in first["cards"])
    assert first["cards"][1]["select"]["reference"] == {"value": "0", "label": "生死线"}
    read = manager.dashboard_read({})["dashboard"]
    assert read["id"] == first["id"] and [card["id"] for card in read["cards"]] == [card["id"] for card in first["cards"]]

    # A save names the version it replaces; one made over an older read is refused.
    second = manager.dashboard_save({"parent_id": first["id"], "cards": [first["cards"][1]]})
    assert second["parent_id"] == first["id"] and len(second["cards"]) == 1
    with pytest.raises(FoundryError, match="changed since it was read"):
        manager.dashboard_save({"parent_id": first["id"], "cards": []})


def test_only_the_manager_accepts_and_acceptance_holds_for_the_run_it_was_given_on(tmp_path):
    manager, run, _ = _board(tmp_path)
    board = manager.dashboard_save({"parent_id": None, "cards": [_gap(run)]})
    card = board["cards"][0]
    accepted = manager.dashboard_save({"parent_id": board["id"], "cards": [{**card, "state": "accepted"}]})
    stamp = accepted["cards"][0]["accepted"]
    assert stamp["run_id"] == run["id"] and stamp["at"]
    # Saved again as it stands, the card keeps the moment it was accepted.
    again = manager.dashboard_save({"parent_id": accepted["id"], "cards": accepted["cards"]})
    assert again["cards"][0]["accepted"] == stamp
    # A caller cannot write its own acceptance.
    forged = manager.dashboard_save({"parent_id": again["id"], "cards": [{**card, "state": "pinned", "accepted": stamp}]})
    assert forged["cards"][0]["accepted"] is None

    assistant = FinanceStore(manager.task)
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.dashboard_save({"parent_id": forged["id"], "cards": [{**card, "state": "accepted"}]})


def test_the_assistant_proposes_explore_cards_the_manager_pins(tmp_path):
    manager, run, bindings = _board(tmp_path)
    assistant = FinanceStore(manager.task, snapshot_ids=set(bindings.values()), actor="assistant")
    proposed = assistant.dashboard_propose({"card": {**_gap(run), "state": "accepted", "note": "集团已经低于生死线"}})
    card = proposed["cards"][0]
    assert (card["state"], card["proposed_by"], card["accepted"]) == ("explore", "assistant", None)
    with pytest.raises(FoundryError, match="already has this card"):
        assistant.dashboard_propose({"card": _gap(run, title="又一张")})
    with pytest.raises(FoundryError, match="only the assistant"):
        manager.dashboard_save({"parent_id": proposed["id"], "cards": [card, {**_rank(run), "state": "explore"}]})
    pinned = manager.dashboard_save({"parent_id": proposed["id"], "cards": [{**card, "state": "pinned"}]})
    assert (pinned["cards"][0]["state"], pinned["cards"][0]["proposed_by"]) == ("pinned", "assistant")


def test_a_card_that_would_draw_nothing_is_refused(tmp_path):
    manager, run, _ = _board(tmp_path)
    figure = _gap(run)
    with pytest.raises(FoundryError, match="exactly one row"):
        manager.dashboard_save({"parent_id": None, "cards": [{**figure, "select": {"match": {"metric_key": "collection_gap"}, "column": "value"}}]})
    with pytest.raises(FoundryError, match="no column"):
        manager.dashboard_save({"parent_id": None, "cards": [{**figure, "select": {**figure["select"], "column": "nope"}}]})
    rank = _rank(run)
    with pytest.raises(FoundryError, match="at least two rows"):
        manager.dashboard_save({"parent_id": None, "cards": [{**rank, "select": {**rank["select"], "match": {"entity": "海口", "metric_key": "collection_gap", "scenario": "本期"}}}]})
    with pytest.raises(FoundryError, match="variance result"):
        manager.dashboard_save({"parent_id": None, "cards": [{"kind": "bridge", "title": "利润桥", "run_id": run["id"], "select": {"match": {}}}]})
    with pytest.raises(FoundryError, match="same thing"):
        manager.dashboard_save({"parent_id": None, "cards": [figure, {**figure, "title": "同一张"}]})
    with pytest.raises(FoundryError, match="not on this board"):
        manager.dashboard_save({"parent_id": None, "cards": [{**figure, "id": "a" * 32}]})


def test_a_session_sees_only_the_cards_on_runs_it_may_read(tmp_path):
    manager, run, bindings = _board(tmp_path)
    manager.dashboard_save({"parent_id": None, "cards": [_gap(run)]})
    reader = FinanceStore(manager.task, snapshot_ids=set(bindings.values()))
    assert len(reader.dashboard_read({})["dashboard"]["cards"]) == 1
    narrow = FinanceStore(manager.task, snapshot_ids={bindings["kpi"]})
    assert narrow.dashboard_read({})["dashboard"]["cards"] == []
    with pytest.raises(FoundryError):
        narrow.dashboard_propose({"card": _rank(run)})


def test_the_app_arranges_the_board_as_the_manager_and_an_unstamped_call_cannot(tmp_path, capsys):
    from foundry.cli import main

    manager, run, _ = _board(tmp_path)
    root = str(tmp_path / "var")
    spec = json.dumps({"parent_id": None, "cards": [_gap(run)]}, ensure_ascii=False)
    assert main(["--var", root, "--task", manager.task.id, "dashboard-save", "--spec", spec]) != 0
    capsys.readouterr()
    assert main(["--var", root, "--task", manager.task.id, "--actor", "manager", "dashboard-save", "--spec", spec]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert main(["--var", root, "--task", manager.task.id, "dashboard-read", "--spec", "{}"]) == 0
    assert json.loads(capsys.readouterr().out)["dashboard"]["id"] == saved["id"]
