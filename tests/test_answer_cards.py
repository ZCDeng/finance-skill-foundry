"""Cards in the assistant's answer: drawn on the server from stored runs, refused rather than drawn wrong."""
from __future__ import annotations

import json

import pytest
from test_billing_detail import pack  # noqa: F401 - the 收费明细 fixture
from test_dashboards import _board, _gap, _rank
from test_finance_explanations import service  # noqa: F401 - a budget variance context

from foundry.cli import main
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore


def _city(run: dict, entity: str) -> dict:
    return {"run_id": run["id"], "select": {"match": {"entity": entity, "metric_key": "collection_gap", "scenario": "本期"}, "column": "value"}}


def test_a_figure_card_shows_the_run_s_figure_with_its_light_its_other_lines_and_where_it_came_from(tmp_path):
    manager, run, _ = _board(tmp_path)
    out = manager.answer_cards({"cards": [{"kind": "figure", "title": "集团距生死线", "run_id": run["id"], "select": _gap(run)["select"]}],
                                "follow_ups": ["按城市公司拆开", "和去年同期比"]})
    [card] = out["cards"]
    row = next(row for row in run["result"]["rows"] if row["entity"] == "集团" and row["metric_key"] == "collection_gap" and row["scenario"] == "本期")
    assert card["value"]["text"] == row["display_value"] and card["value"]["negative"] is row["display_value"].startswith("-")
    assert (card["level"], card["level_label"]) == (row["level"], row["level_label"])
    assert [label for label, _ in card["beside"]] == ["上年同期", "变动"]
    assert card["source"]["run_id"] == run["id"] and ["公式", row["formula"]] in card["source"]["lines"]
    assert {file["name"] for file in card["source"]["files"]} == {"kpi", "city"}
    # 钉到看板 pins exactly what a board figure card would read.
    assert card["pin"] == {"kind": "figure", "title": "集团距生死线", "run_id": run["id"], "select": _gap(run)["select"]}
    assert out["follow_ups"] == ["按城市公司拆开", "和去年同期比"]
    assert out["task_id"] == manager.task.id
    assert f"数字卡「集团距生死线」：集团 本期 {row['display_value']}" in out["text"]
    assert "接着问：按城市公司拆开；和去年同期比" in out["text"]


def test_rank_and_compare_cards_read_the_rows_they_name_and_compute_nothing_between_them(tmp_path):
    manager, run, _ = _board(tmp_path)
    out = manager.answer_cards({"cards": [
        {"kind": "rank", "title": "距生死线（从低到高）", "run_id": run["id"], "select": _rank(run)["select"]},
        {"kind": "compare", "title": "海口和三亚", "items": [_city(run, "海口"), _city(run, "三亚")]},
    ]})
    rank, compare = out["cards"]
    assert [item["label"] for item in rank["items"]] == ["三亚", "儋州", "海口"]
    assert rank["reference"] == {"value": 0.0, "label": "生死线"} and rank["unit"] == "个百分点"
    assert [item["subject"] for item in compare["items"]] == ["海口", "三亚"]
    assert compare["pin"] is None and "差" not in json.dumps([item["beside"] for item in compare["items"]], ensure_ascii=False)


def test_a_card_that_names_the_wrong_rows_is_refused_not_drawn(tmp_path):
    manager, run, _ = _board(tmp_path)
    wrong = [
        ({"kind": "figure", "title": "x", "run_id": run["id"], "select": {"match": {"metric_key": "collection_gap"}, "column": "value"}}, "exactly one row"),
        ({"kind": "figure", "title": "x", "run_id": "f" * 32, "select": _gap(run)["select"]}, "card 1"),
        ({"kind": "compare", "title": "x", "items": [_city(run, "海口")]}, "2 to 4"),
        ({"kind": "compare", "title": "x", "items": [_city(run, "海口"), _city(run, "万宁")]}, "item 2"),
        ({"kind": "trend", "title": "x", "run_id": run["id"], "select": {"match": {"entity": "集团"}, "column": "value"}}, "periods"),
        ({"kind": "chart", "title": "x"}, "kind is one of"),
        ({"kind": "figure", "title": "", "run_id": run["id"], "select": _gap(run)["select"]}, "title"),
    ]
    for card, said in wrong:
        with pytest.raises(FoundryError, match=said):
            manager.answer_cards({"cards": [card]})
    figure = {"kind": "figure", "title": "x", "run_id": run["id"], "select": _gap(run)["select"]}
    with pytest.raises(FoundryError, match="at most 3"):
        manager.answer_cards({"cards": [figure] * 4})
    with pytest.raises(FoundryError, match="40"):
        manager.answer_cards({"cards": [figure], "follow_ups": ["问" * 41]})
    with pytest.raises(FoundryError, match="at least one"):
        manager.answer_cards({"cards": []})


def test_a_session_draws_cards_only_from_runs_it_may_read(tmp_path):
    manager, run, bindings = _board(tmp_path)
    narrow = FinanceStore(manager.task, snapshot_ids={bindings["kpi"]}, actor="assistant")
    with pytest.raises(FoundryError, match="card 1"):
        narrow.answer_cards({"cards": [{"kind": "figure", "title": "x", "run_id": run["id"], "select": _gap(run)["select"]}]})


def test_a_collection_figure_carries_the_workbook_s_rate_and_the_difference_the_run_worked_out(pack):  # noqa: F811
    task, billing, ids = pack
    run = billing.collection_run({**ids, "as_of": "2026-08-31", "reported": {"collection_rate_current": 0.52}})
    grouped = billing.collection_run({**ids, "as_of": "2026-08-31", "group_by": ["type"]})
    out = FinanceStore(task, actor="assistant").answer_cards({"cards": [
        {"kind": "figure", "title": "当期收缴率", "collection_run_id": run["id"], "figure": "collection_rate_current"},
        {"kind": "figure", "title": "洋房", "collection_run_id": grouped["id"], "figure": "collection_rate_current", "group": {"type": "洋房"}},
        {"kind": "rank", "title": "各类型", "collection_run_id": grouped["id"], "figure": "collection_rate_current", "order": "asc", "limit": 2},
    ]})
    whole, one, rank = out["cards"]
    assert whole["value"]["text"] == "48.65%"
    assert whole["beside"] == [["套表", "52.00%"], ["差", "-3.35 个百分点"], ["本年应收", "740.00"], ["当期已收", "360.00"]]
    assert whole["source"]["kind"] == "collection" and ["口径", "默认口径（未确认）"] in whole["source"]["lines"]
    assert whole["pin"] is None  # a collection run is not an analysis run; the board cannot hold it yet
    assert (one["subject"], one["value"]["text"]) == ("洋房", "80.00%")
    assert [(item["label"], item["text"]) for item in rank["items"]] == [("别墅", "0.00"), ("（空）", "0.00")]
    assert rank["unit"] == "%" and rank["subject"] == "按房产类型"
    with pytest.raises(FoundryError, match="洋房"):
        FinanceStore(task).answer_cards({"cards": [
            {"kind": "figure", "title": "x", "collection_run_id": grouped["id"], "figure": "collection_rate_current", "group": {"type": "公寓"}}]})
    with pytest.raises(FoundryError, match="no groups"):
        FinanceStore(task).answer_cards({"cards": [
            {"kind": "rank", "title": "x", "collection_run_id": run["id"], "figure": "collection_rate_current"}]})


def test_a_bridge_closes_on_the_variance_run_and_a_trend_runs_oldest_first(service):  # noqa: F811
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    out = store.answer_cards({"cards": [
        {"kind": "bridge", "title": "利润桥", "run_id": run["id"], "select": {"match": {}}},
        {"kind": "figure", "title": "利润", "run_id": run["id"], "select": {"match": {"metric": "profit"}, "column": "actual"}},
    ]})
    bridge, profit = out["cards"]
    assert [(step["label"], step["text"]) for step in bridge["steps"]] == [
        ("预算利润", "25"), ("收入", "20"), ("成本", "-10"), ("费用", "-5"), ("实际利润", "30")]
    assert bridge["unit"] == "万元" and bridge["pin"]["kind"] == "bridge"
    assert profit["beside"] == [["预算", "25.00"], ["差异", "5.00"], ["差异率", "20.00%"]]


def test_a_trend_reads_one_line_across_its_periods(tmp_path):
    from foundry.analysis import AnalysisStore
    from foundry.task import TaskStore

    task = TaskStore(tmp_path / "var").create(title="趋势")
    path = tmp_path / "monthly.json"
    path.write_text(json.dumps([
        {"period": "2026-03", "metric": "revenue", "actual": "310.5", "unit": "万元"},
        {"period": "2026-01", "metric": "revenue", "actual": "100", "unit": "万元"},
        {"period": "2026-02", "metric": "revenue", "actual": "-20.125", "unit": "万元"},
        {"period": "2026-01", "metric": "cost", "actual": "50", "unit": "万元"},
    ]), encoding="utf-8")
    analysis = AnalysisStore(task)
    dataset = analysis.add_dataset(path, name="monthly")
    saved = analysis.save_analysis({"question": "月度收入", "bindings": {"m": dataset["id"]},
                                    "sql": "select period, metric, actual, unit from m"})
    run = analysis.run_analysis(saved["id"])
    store = FinanceStore(task)
    out = store.answer_cards({"cards": [{"kind": "trend", "title": "收入走势", "run_id": run["id"],
                                         "select": {"match": {"metric": "revenue"}, "column": "actual"}}]})
    [trend] = out["cards"]
    assert [(point["label"], point["text"]) for point in trend["points"]] == [
        ("2026 年 1 月", "100.00"), ("2026 年 2 月", "-20.13"), ("2026 年 3 月", "310.50")]
    assert trend["unit"] == "万元" and trend["pin"] is None
    with pytest.raises(FoundryError, match="two rows hold 2026-01"):
        store.answer_cards({"cards": [{"kind": "trend", "title": "x", "run_id": run["id"], "select": {"match": {}, "column": "actual"}}]})


def test_a_proposed_board_card_comes_back_drawn_for_the_conversation(tmp_path):
    manager, run, _ = _board(tmp_path)
    assistant = FinanceStore(manager.task, actor="assistant")
    answered = assistant.dashboard_propose({"card": {**_gap(run), "state": None}})
    shown = answered["presented"]["proposed"]
    assert shown["kind"] == "figure" and shown["title"] == "集团距生死线" and shown["pin"] is None
    assert answered["presented"]["task_id"] == manager.task.id
    scenario = assistant.dashboard_propose({"card": {"kind": "scenario", "title": "集团回款情景", "run_id": run["id"],
                                                     "select": {"match": {"entity": "集团", "scenario": "本期"}}}})
    lines = scenario["presented"]["proposed"]["lines"]
    assert [label for label, _ in lines] == ["毛利率", "期间费用率", "生死线收缴率", "距生死线（本年账单收缴率）"]


def test_the_cli_draws_cards_for_the_assistant(tmp_path, capsys):
    manager, run, _ = _board(tmp_path)
    task = manager.task
    task.record_session("s1", role="analysis")
    spec = {"cards": [{"kind": "figure", "title": "集团距生死线", "run_id": run["id"], "select": _gap(run)["select"]}]}
    assert main(["--var", str(tmp_path / "var"), "--session", "s1", "answer-cards", "--spec", json.dumps(spec, ensure_ascii=False)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cards"][0]["title"] == "集团距生死线" and out["text"].startswith("回答下方已画出 1 张卡")
