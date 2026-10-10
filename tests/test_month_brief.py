"""本月三句话: three lines a rule writes from what the task already holds, every figure naming where it came from."""
from __future__ import annotations

import json

import pytest
from test_dashboards import KPI, _board, _gap, _rank, _readd

from foundry.cli import main
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.month_brief import _change_line


def _figures(line: dict) -> list[tuple[str, str]]:
    return [(part["text"], part["ref"]["kind"]) for part in line["parts"] if part.get("ref")]


def _lines(manager) -> dict:
    return {line["key"]: line for line in manager.month_brief({})["lines"]}


def test_the_three_lines_take_their_figures_from_the_board_the_radar_and_the_to_dos(tmp_path):
    manager, run, _ = _board(tmp_path)
    board = manager.dashboard_save({"parent_id": None, "cards": [_gap(run), _rank(run)]})
    lines = _lines(manager)
    assert [line["label"] for line in lines.values()] == ["变化", "风险", "等你拍板"]
    assert lines["change"]["text"] == "看板上还没有按新资料重算过的卡，暂时没有可比的变化。"
    assert lines["risk"]["text"] == "风险雷达上 1 个主体是绿色，没有要先看的。"
    waiting = lines["waiting"]
    assert waiting["text"].startswith("5 件事等你处理，先看：期间未确认。") and waiting["text"].endswith("看板还有 2 张卡等你认可。")
    assert _figures(waiting) == [("5 件事", "open"), ("期间未确认", "open"), ("2 张卡", "open")]

    # Collections fell to 80%: the gap card moved, the city ranking did not.
    kpi = [dict(row) for row in KPI]
    kpi[3]["本年累计"] = "80.00%"
    _readd(manager, tmp_path, "kpi", kpi)
    gap = manager.dashboard_recompute({"parent_id": board["id"]})["dashboard"]["cards"][0]
    lines = _lines(manager)
    assert lines["change"]["text"] == "「集团距生死线」从 -0.98 个百分点 变为 -8.30 个百分点，变动 -7.32 个百分点。"
    assert [part["ref"] for part in lines["change"]["parts"] if part.get("ref")] == [
        {"kind": kind, "card_id": gap["id"]} for kind in ("card_before", "card", "card_change")]
    # The new run's radar: the group now trips two signals.
    risk = lines["risk"]
    assert risk["text"] == "集团风险雷达 3 分（黄），触发收缴率低于生死线、收缴率同比下降。"
    [(_, figure)] = [(part["text"], part["ref"]) for part in risk["parts"] if part.get("ref")]
    assert figure == {"kind": "row", "run_id": gap["run_id"], "column": "value", "metric": "集团风险雷达",
                      "match": {"entity": "集团", "metric_key": "risk_score", "scenario": "本期", "entity_origin": "declared"}}


class _Store:
    allowed = None

    def __init__(self, cards):
        self.cards = cards

    def _dashboard(self):
        return {"cards": self.cards}


def _card(title, before, after, changed, words, kind="figure", **more):
    return {"id": title, "title": title, "kind": kind, "state": "pinned",
            "recomputed": {"before": before, "after": after, "changed": changed, "change": words, **more}}


def test_a_light_that_changed_comes_first_and_a_move_inside_the_line_is_still_named():
    margin = _card("毛利率", {"value": "18.05", "display": "18.05%", "unit": "%", "rate": "points"},
                   {"value": "18.35", "display": "18.35%", "unit": "%", "rate": "points"}, False, "+0.30 个百分点")
    gap = _card("距生死线", {"value": "-3.22", "display": "-3.22 个百分点", "level": "red", "unit": "百分点"},
                {"value": "-3.10", "display": "-3.10 个百分点", "level": "red", "unit": "百分点"}, False, "+0.12 个百分点")
    ranking = _card("排名", {"labels": ["宝鸡"], "leaders": ["宝鸡"], "beyond": None}, {"labels": ["宝鸡"], "leaders": ["宝鸡"], "beyond": None},
                    False, "前三名没有变化", kind="rank")
    assert _change_line(_Store([ranking, gap, margin]))["text"] == (
        "看板上 3 张卡按新资料重算，变动都不到 1 个百分点或 10%；动得最多的是「毛利率」，从 18.05% 变为 18.35%，变动 +0.30 个百分点。")
    # A yellow turned red outranks a bigger move that kept its light, and a level is no worse for being further.
    revenue = _card("收入", {"value": "100", "display": "100"}, {"value": "150", "display": "150"}, True, "变动 +50.0%")
    city = _card("三亚距生死线", {"value": "-0.5", "display": "-0.50 个百分点", "level": "yellow", "unit": "百分点"},
                 {"value": "-1.2", "display": "-1.20 个百分点", "level": "red", "unit": "百分点"}, True, "级别 黄 → 红")
    line = _change_line(_Store([revenue, city, margin]))
    assert line["text"] == "「三亚距生死线」从 -0.50 个百分点 变为 -1.20 个百分点，级别 黄 → 红。另有 1 张卡也有变化。"
    assert _change_line(_Store([ranking]))["text"] == "看板上 1 张卡按新资料重算，变动都不到 1 个百分点或 10%。"
    # Scenarios and cards the manager has not pinned say nothing of the month.
    what_if = {**city, "kind": "goal"}
    assert _change_line(_Store([what_if, {**revenue, "state": "explore"}]))["text"].startswith("看板上还没有按新资料重算过的卡")


def test_the_assistant_rewords_a_line_but_keeps_every_figure_and_adds_none(tmp_path):
    manager, run, _ = _board(tmp_path)
    manager.dashboard_save({"parent_id": None, "cards": [_gap(run), _rank(run)]})
    assistant = FinanceStore(manager.task, actor="assistant")
    current = assistant.month_brief({})
    signature = current["signature"]
    assert current["worded"] is None
    with pytest.raises(FoundryError, match="数已经变了"):
        assistant.month_brief_word({"signature": "0" * 64, "lines": {"waiting": "x"}})
    with pytest.raises(FoundryError, match="要原样保留「2 张卡」"):
        assistant.month_brief_word({"signature": signature, "lines": {"waiting": "5 件事等你处理，先看：期间未确认。看板上的卡也等你认可。"}})
    with pytest.raises(FoundryError, match="原句里没有 1、3"):
        assistant.month_brief_word({"signature": signature, "lines": {
            "waiting": "期间未确认，这是 5 件事里的第 1 件；看板 2 张卡等你认可，3 天内处理。"}})
    with pytest.raises(FoundryError, match="lines names"):
        assistant.month_brief_word({"signature": signature, "lines": {"summary": "x"}})
    worded = "先定期间未确认这一条，一共 5 件事等你处理；看板 2 张卡也等你认可。"
    saved = assistant.month_brief_word({"signature": signature, "lines": {"waiting": worded}})
    assert saved["worded"]["lines"] == {"waiting": worded} and saved["worded"]["by"] == "assistant"
    # The desktop reads the same wording while the figures stand, and the rule's line once they move.
    assert manager.month_brief({})["worded"]["lines"] == {"waiting": worded}
    kpi = [dict(row) for row in KPI]
    kpi[3]["本年累计"] = "80.00%"
    _readd(manager, tmp_path, "kpi", kpi)
    manager.dashboard_recompute({"parent_id": manager.dashboard_read({})["dashboard"]["id"]})
    assert manager.month_brief({})["worded"] is None


def test_the_desktop_and_the_assistant_read_it_from_the_cli(tmp_path, capsys):
    manager, run, _ = _board(tmp_path)
    var = str(tmp_path / "var")
    assert main(["--var", var, "--task", manager.task.id, "month-brief"]) == 0
    brief = json.loads(capsys.readouterr().out)
    assert [line["key"] for line in brief["lines"]] == ["change", "risk", "waiting"]
    line = brief["lines"][2]["text"]
    spec = json.dumps({"signature": brief["signature"], "lines": {"waiting": line.replace("先看：", "第一件是")}}, ensure_ascii=False)
    assert main(["--var", var, "--task", manager.task.id, "month-brief-word", "--spec", spec]) == 0
    assert json.loads(capsys.readouterr().out)["worded"]["lines"]["waiting"].startswith("5 件事等你处理，第一件是")
