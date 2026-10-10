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


def test_a_session_proposing_a_card_is_answered_with_the_cards_it_may_read(tmp_path):
    manager, run, bindings = _board(tmp_path)
    narrow_ids = {bindings["kpi"]}
    hidden = manager.dashboard_save({"parent_id": None, "cards": [_gap(run)]})
    other = FinanceStore(manager.task, actor="manager")
    context = other.save_context({"bindings": {"kpi": bindings["kpi"]}, "scopes": {"kpi": {"currency": "CNY", "unit": "万元"}}})
    scenario = other.save_scenario({
        "context_id": context["id"], "kind": "collection_health", "label": "只读集团",
        "inputs": {"entities": [{"name": "集团", "values": {
            "revenue": _cell("营业收入"), "cost": _cell("营业成本"), "period_expense": _cell("期间费用"),
            "collection_rate_current": _cell("本年账单收缴率")}}]},
    })
    readable = other.run_scenario({"scenario_id": scenario["id"]})
    assert readable["execution_status"] == "succeeded"

    narrow = FinanceStore(manager.task, snapshot_ids=narrow_ids, actor="assistant")
    answered = narrow.dashboard_propose({"card": _gap(readable, title="只看集团")})
    assert [card["title"] for card in answered["cards"]] == ["只看集团"]
    stored = manager.dashboard_read({})["dashboard"]
    assert [card["title"] for card in stored["cards"]] == [hidden["cards"][0]["title"], "只看集团"]


def test_two_saves_on_one_board_never_both_build_on_the_same_version(tmp_path, monkeypatch):
    import threading

    from foundry import dashboards

    manager, run, bindings = _board(tmp_path)
    first = manager.dashboard_save({"parent_id": None, "cards": [_gap(run)]})
    inside, release = threading.Event(), threading.Event()
    arrange = dashboards.arrange

    def slow_arrange(*args, **kwargs):
        inside.set()
        assert release.wait(5)
        return arrange(*args, **kwargs)

    monkeypatch.setattr(dashboards, "arrange", slow_arrange)
    saved = {}
    accepting = threading.Thread(target=lambda: saved.update(board=manager.dashboard_save(
        {"parent_id": first["id"], "cards": [{**first["cards"][0], "state": "accepted"}]})))
    accepting.start()
    assert inside.wait(5)
    assistant = FinanceStore(manager.task, snapshot_ids=set(bindings.values()), actor="assistant")
    proposed = {}
    proposing = threading.Thread(target=lambda: proposed.update(board=assistant.dashboard_propose({"card": _rank(run)})))
    proposing.start()
    proposing.join(0.3)
    assert proposing.is_alive(), "the proposal read the board while the manager's save was still writing it"
    release.set()
    accepting.join(5)
    proposing.join(5)
    assert proposed["board"]["parent_id"] == saved["board"]["id"]
    states = {card["title"]: card["state"] for card in manager.dashboard_read({})["dashboard"]["cards"]}
    assert states == {"集团距生死线": "accepted", "距生死线（从低到高）": "explore"}


def _scenario(run: dict, entity: str = "集团") -> dict:
    return {"kind": "scenario", "title": "回款情景", "run_id": run["id"], "template": "collection",
            "select": {"match": {"entity": entity, "scenario": "本期"}}}


def test_a_scenario_card_reads_one_entitys_lines_and_is_never_accepted(tmp_path):
    manager, run, bindings = _board(tmp_path)
    board = manager.dashboard_save({"parent_id": None, "cards": [_scenario(run), _scenario(run, "海口")]})
    assert [card["select"] for card in board["cards"]] == [{"match": {"entity": "集团", "scenario": "本期"}},
                                                         {"match": {"entity": "海口", "scenario": "本期"}}]
    # What it shows past the run's own lines is a what-if: it never goes into the close as an accepted figure.
    with pytest.raises(FoundryError, match="never accepted"):
        manager.dashboard_save({"parent_id": board["id"], "cards": [{**board["cards"][0], "state": "accepted"}]})
    scenario = _scenario(run)
    with pytest.raises(FoundryError, match="name the 本期 lines"):
        manager.dashboard_save({"parent_id": board["id"], "cards": [{**scenario, "select": {"match": {"entity": "集团"}}}]})
    with pytest.raises(FoundryError, match="one entity"):
        manager.dashboard_save({"parent_id": board["id"], "cards": [{**scenario, "select": {"match": {"scenario": "本期"}}}]})

    # The assistant proposes one like any card; the session's answer shows only the cards on runs it may read.
    assistant = FinanceStore(manager.task, snapshot_ids=set(bindings.values()), actor="assistant")
    empty = manager.dashboard_save({"parent_id": board["id"], "cards": []})
    proposed = assistant.dashboard_propose({"card": {**scenario, "state": "accepted"}})
    assert proposed["parent_id"] == empty["id"]
    assert [(card["kind"], card["state"], card["proposed_by"]) for card in proposed["cards"]] == [("scenario", "explore", "assistant")]

    # Run again on newer files, the card is judged by its entity's 距生死线.
    from foundry.dashboard_recompute import change, shown

    stands = shown(proposed["cards"][0], run)
    assert stands["unit"] == "百分点" and stands["level"] == "red" and stands["display"].endswith("个百分点")
    assert change(proposed["cards"][0], stands, {**stands, "value": "0.5", "level": "yellow"}) == (True, "级别 红 → 黄")


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


# -- 3b: recomputed on newer files, carried from last month's task ---------------------------------------------------

def _readd(manager, tmp_path, alias: str, rows: list[dict], name: str | None = None) -> dict:
    path = tmp_path / f"{alias}-again.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return AnalysisStore(manager.task).add_dataset(path, name=name or alias)


def test_a_card_on_files_with_a_newer_version_is_run_again_and_waits_for_the_manager(tmp_path):
    manager, run, _ = _board(tmp_path)
    board = manager.dashboard_save({"parent_id": None, "cards": [_gap(run, state="accepted"), _rank(run)]})
    assert manager.dashboard_read({})["recompute"] == {"ready": 0}
    # The corrected KPI board comes in again under its name: collections fell to 80%.
    kpi = [dict(row) for row in KPI]
    kpi[3]["本年累计"] = "80.00%"
    _readd(manager, tmp_path, "kpi", kpi)
    assert manager.dashboard_read({})["recompute"] == {"ready": 2}

    out = manager.dashboard_recompute({"parent_id": board["id"]})
    assert out["failed"] == [] and len(out["recomputed"]) == 2
    gap, rank = out["dashboard"]["cards"]
    assert gap["run_id"] != run["id"] and gap["run_id"] == rank["run_id"]
    assert (gap["state"], gap["accepted"]) == ("pinned", None)
    said = gap["recomputed"]
    assert said["from_run_id"] == run["id"] and said["was_accepted"] is True and said["months"] is None
    assert said["before"]["unit"] == "百分点" and said["changed"] is True and "个百分点" in said["change"]
    # The city sheet did not change, so the ranking did not either.
    assert rank["recomputed"]["changed"] is False
    assert manager.dashboard_read({})["recompute"] == {"ready": 0}
    # Accepted again, the card keeps what the recompute said of it until it moves again.
    accepted = manager.dashboard_save({"parent_id": out["dashboard"]["id"], "cards": [{**gap, "state": "accepted"}, rank]})
    assert accepted["cards"][0]["recomputed"] == said and accepted["cards"][0]["accepted"]["run_id"] == gap["run_id"]


def test_a_calculation_that_names_the_old_month_is_not_run_on_the_new_one_and_says_why_once(tmp_path):
    manager, _, _ = _board(tmp_path)
    august = _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-08"} for row in KPI])
    analysis = AnalysisStore(manager.task)
    saved = analysis.save_analysis({"question": "八月收入", "bindings": {"ledger": august["id"]}, "scope": {"period": "2026-08"},
                                    "sql": "select 指标, 本年累计 from ledger where 期间 = '2026-08' and 指标 = '营业收入'"})
    sql_run = analysis.run_analysis(saved["id"])
    card = {"kind": "figure", "title": "收入", "run_id": sql_run["id"], "select": {"match": {"指标": "营业收入"}, "column": "本年累计"}}
    board = manager.dashboard_save({"parent_id": None, "cards": [card]})
    # September's ledger under the same name: the SQL picks August's rows by name.
    _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-09"} for row in KPI])
    out = manager.dashboard_recompute({"parent_id": board["id"]})
    assert out["recomputed"] == [] and "计算里写着 2026-08" in out["failed"][0]["reason"]
    stored = out["dashboard"]["cards"][0]
    assert stored["run_id"] == sql_run["id"] and stored["recompute_failed"]["reason"] == out["failed"][0]["reason"]
    # Not tried again on the same files.
    assert manager.dashboard_read({})["recompute"] == {"ready": 0}
    assert manager.dashboard_recompute({})["recomputed"] == []


def test_a_query_without_the_month_in_it_moves_to_the_new_month(tmp_path):
    manager, _, _ = _board(tmp_path)
    august = _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-08"} for row in KPI])
    analysis = AnalysisStore(manager.task)
    saved = analysis.save_analysis({"question": "收入", "bindings": {"ledger": august["id"]}, "scope": {"period": "2026-08"},
                                    "sql": "select 期间, 指标, 本年累计 from ledger where 指标 = '营业收入'"})
    sql_run = analysis.run_analysis(saved["id"])
    card = {"kind": "figure", "title": "收入", "run_id": sql_run["id"],
            "select": {"match": {"指标": "营业收入", "期间": "2026-08"}, "column": "本年累计"}}
    board = manager.dashboard_save({"parent_id": None, "cards": [card]})
    _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-09", "本年累计": "1200"} if row["指标"] == "营业收入" else {**row, "期间": "2026-09"} for row in KPI])
    out = manager.dashboard_recompute({"parent_id": board["id"]})
    moved = out["dashboard"]["cards"][0]
    # The card names its row by its month, so the month moves with it; the revision's scope moves too.
    assert moved["select"]["match"] == {"指标": "营业收入", "期间": "2026-09"}
    assert moved["recomputed"]["months"] == ["2026-08", "2026-09"]
    assert moved["recomputed"]["change"] == "变动 +20.0%" and moved["recomputed"]["changed"] is True
    revision = analysis.get_analysis(analysis.get_run(moved["run_id"])["analysis_id"])
    assert revision["scope"] == {"period": "2026-09"} and revision["parent_id"] == saved["id"]


def test_a_calculation_waits_until_every_file_it_reads_is_the_new_month(tmp_path):
    manager, _, _ = _board(tmp_path)
    ledger = _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-08"} for row in KPI])
    cities = _readd(manager, tmp_path, "cities", [{**row, "期间": "2026-08"} for row in CITY])
    analysis = AnalysisStore(manager.task)
    saved = analysis.save_analysis({"question": "收入", "bindings": {"ledger": ledger["id"], "cities": cities["id"]},
                                    "scope": {"period": "2026-08"},
                                    "sql": "select 指标, 本年累计 from ledger where 指标 = '营业收入' "
                                           "union all select 城市, 收入 from cities where 城市 = '海口'"})
    sql_run = analysis.run_analysis(saved["id"])
    card = {"kind": "figure", "title": "收入", "run_id": sql_run["id"], "select": {"match": {"指标": "营业收入"}, "column": "本年累计"}}
    board = manager.dashboard_save({"parent_id": None, "cards": [card]})
    # September's ledger is in, the city sheet is still August's: not run on two months at once.
    _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-09"} for row in KPI])
    out = manager.dashboard_recompute({"parent_id": board["id"]})
    assert out["recomputed"] == [] and out["failed"][0]["reason"] == "还有资料不是 2026-09 的：cities，换成同一个月的再重算"
    # Once the city sheet is September's too, it runs on both.
    _readd(manager, tmp_path, "cities", [{**row, "期间": "2026-09"} for row in CITY])
    assert manager.dashboard_read({})["recompute"] == {"ready": 1}
    out = manager.dashboard_recompute({})
    assert out["failed"] == [] and out["dashboard"]["cards"][0]["recomputed"]["months"] == ["2026-08", "2026-09"]


def test_a_calculation_over_a_range_of_months_is_not_moved_to_the_new_month(tmp_path):
    manager, _, _ = _board(tmp_path)
    ledger = _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-08"} for row in KPI])
    analysis = AnalysisStore(manager.task)
    saved = analysis.save_analysis({"question": "累计收入", "bindings": {"ledger": ledger["id"]}, "scope": {"period": "2026-01:2026-08"},
                                    "sql": "select 指标, 本年累计 from ledger where 指标 = '营业收入'"})
    sql_run = analysis.run_analysis(saved["id"])
    card = {"kind": "figure", "title": "收入", "run_id": sql_run["id"], "select": {"match": {"指标": "营业收入"}, "column": "本年累计"}}
    board = manager.dashboard_save({"parent_id": None, "cards": [card]})
    _readd(manager, tmp_path, "ledger", [{**row, "期间": "2026-09"} for row in KPI])
    out = manager.dashboard_recompute({"parent_id": board["id"]})
    assert out["recomputed"] == [] and out["failed"][0]["reason"] == "期间写的是区间「2026-01:2026-08」，换到 2026-09 要你重新设定期间"


def test_a_ratio_kept_as_a_fraction_moves_in_points():
    from foundry.dashboard_recompute import change, shown

    card = {"kind": "figure", "select": {"match": {"metric": "毛利率"}, "column": "ratio"}}
    run = lambda ratio: {"result": {"rows": [{"metric": "毛利率", "ratio": ratio, "unit": "万元", "display_value": "-"}]}}  # noqa: E731
    assert change(card, shown(card, run("0.80")), shown(card, run("0.81"))) == (True, "+1.00 个百分点")
    assert change(card, shown(card, run("0.80")), shown(card, run("0.805"))) == (False, "+0.50 个百分点")


def test_last_months_board_is_carried_onto_a_new_task_by_the_names_of_its_files(tmp_path):
    manager, run, _ = _board(tmp_path)
    manager.dashboard_save({"parent_id": None, "cards": [_gap(run, state="accepted"), _rank(run)]})
    store = TaskStore(tmp_path / "var")
    september = store.create(title="九月", period="2026-09")
    target = FinanceStore(september, actor="manager")
    assert target.dashboard_carry({}, tasks=store)["offers"][0]["missing"] == ["city", "kpi"]
    for alias, rows in {"kpi": KPI, "city": CITY}.items():
        path = tmp_path / f"{alias}-09.json"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        AnalysisStore(september).add_dataset(path, name=alias)
    offer = target.dashboard_carry({}, tasks=store)["offers"][0]
    assert (offer["task_id"], offer["cards"], offer["ready"], offer["missing"]) == (manager.task.id, 2, 2, [])

    out = target.dashboard_carry({"from_task_id": manager.task.id}, tasks=store)
    assert out["failed"] == [] and len(out["carried"]) == 2
    cards = out["dashboard"]["cards"]
    assert all(card["state"] == "pinned" and card["recomputed"]["carried_from"]["task_id"] == manager.task.id for card in cards)
    new_run = AnalysisStore(september).get_run(cards[0]["run_id"])
    assert new_run["task_id"] == september.id
    # The same files, so the same figures: nothing worth a look.
    assert cards[0]["recomputed"]["before"] == cards[0]["recomputed"]["after"] and not cards[0]["recomputed"]["changed"]
    with pytest.raises(FoundryError, match="already has cards"):
        target.dashboard_carry({"from_task_id": manager.task.id}, tasks=store)
    assistant = FinanceStore(september)
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.dashboard_recompute({})


def test_the_example_august_board_moves_to_september_with_its_month():
    """跟着做: the August collection board carried onto the September task the guide makes next."""
    import tempfile

    from foundry.sample_reference import MONTH_CLOSE, Reference
    from foundry.sample_task import create_next_month_sample, create_sample_task

    with tempfile.TemporaryDirectory() as root:
        var = Path(root) / "var"
        august = Reference(TaskStore(var).get(create_sample_task(var)["id"]))
        august.datasets = {MONTH_CLOSE: august.datasets[MONTH_CLOSE]}
        august.confirm_structures()
        run = august.collection_health()
        gap = {"kind": "figure", "title": "集团距生死线", "state": "accepted", "run_id": run["id"],
               "select": {"match": {"entity": "华宸物业", "metric_key": "collection_gap", "scenario": "本期"}, "column": "value"}}
        august.manager.dashboard_save({"parent_id": None, "cards": [gap]})
        september = TaskStore(var).get(create_next_month_sample(var)["id"])
        target = FinanceStore(september, actor="manager")
        out = target.dashboard_carry({"from_task_id": august.task.id}, tasks=TaskStore(var))
        card = out["dashboard"]["cards"][0]
        said = card["recomputed"]
        assert said["months"] == ["2026-08", "2026-09"] and said["adjusted"] == ["已过月数 8 → 9"]
        assert said["before"]["display"] != said["after"]["display"] and said["after"]["level"]
        context = target._read("contexts", AnalysisStore(september).get_run(card["run_id"])["finance_context_id"])
        assert {scope["period"] for scope in context["scopes"].values()} == {"2026-09"}
        assert context["name"].endswith("（按 2026-09 重算）")


def test_the_overview_lists_the_cards_run_again_with_what_changed(tmp_path):
    from foundry.overview import overview

    manager, run, _ = _board(tmp_path)
    board = manager.dashboard_save({"parent_id": None, "cards": [_gap(run), _rank(run)]})
    store = TaskStore(tmp_path / "var")
    [row] = overview(store)["tasks"]
    assert row["dashboard"] == {"recomputed": []}
    kpi = [dict(row) for row in KPI]
    kpi[3]["本年累计"] = "80.00%"
    _readd(manager, tmp_path, "kpi", kpi)
    manager.dashboard_recompute({"parent_id": board["id"]})
    [row] = overview(store)["tasks"]
    listed = row["dashboard"]["recomputed"]
    assert [(item["title"], item["changed"], item["state"]) for item in listed] == [
        ("集团距生死线", True, "pinned"), ("距生死线（从低到高）", False, "pinned")]
    assert listed[0]["at"] and listed[0]["carried_from"] is None


def test_a_ranking_changes_when_its_leaders_or_the_side_of_its_line_change_not_its_ties():
    from foundry.dashboard_recompute import change, shown

    card = {"kind": "rank", "select": {"match": {}, "label": "城市", "column": "分", "order": "desc", "limit": 10}}
    run = lambda rows: {"result": {"rows": [{"城市": name, "分": value} for name, value in rows]}}  # noqa: E731
    august = shown(card, run([("宝鸡", 6), ("赣州", 4), ("绵阳", 4), ("兰州", 2)]))
    # The same scores in another row order: the leaders are the same three.
    assert change(card, august, shown(card, run([("绵阳", 4), ("宝鸡", 6), ("兰州", 2), ("赣州", 4)]))) == (False, "前三名没有变化")
    assert change(card, august, shown(card, run([("宝鸡", 6), ("赣州", 4), ("绵阳", 4), ("兰州", 4)]))) == (True, "兰州排进前三")
    gap = {"kind": "rank", "select": {"match": {}, "label": "城市", "column": "分", "order": "asc", "limit": 10,
                                      "reference": {"value": "0", "label": "生死线"}}}
    before = shown(gap, run([("海口", -2), ("三亚", 1), ("儋州", 3)]))
    assert change(gap, before, shown(gap, run([("海口", -2), ("三亚", -1), ("儋州", 3)]))) == (True, "低于生死线的：1 个 → 2 个")
    # One across each way: still one below the line.
    assert change(gap, before, shown(gap, run([("海口", 1), ("三亚", -1), ("儋州", 3)]))) == (False, "前三名没有变化")
