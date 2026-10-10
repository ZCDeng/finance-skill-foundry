"""倒推 and 敏感性 cards say the same of a run on the board and in the conversation.

The cases and their answers are in app/tests/fixtures/what-if-cases.json; app/tests/what-if-parity.test.ts holds the
board's arithmetic (dashboardWhatIf.ts) to the same answers, and this file holds foundry/what_if.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from foundry import what_if

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "app/tests/fixtures/what-if-cases.json").read_text(encoding="utf-8"))


def _keys(view: dict) -> dict:
    return {**view, "basis": [row["metric_key"] for row in view["basis"]]}


def test_a_goal_card_works_back_from_a_collection_rate_as_the_board_does():
    for case in CASES["goals"]:
        view = what_if.goal_collection(what_if.lines_of(case["rows"], case["entity"]), case["entity"], case["target"], case["params"])
        assert _keys(view) == case["view"], case["name"]


def test_a_goal_card_works_back_from_the_revenue_budget_as_the_board_does():
    for case in CASES["budgets"]:
        view = what_if.goal_budget(what_if.lines_of(case["rows"], case["entity"]), case["entity"])
        assert _keys(view) == case["view"], case["name"]


def test_a_sensitivity_card_shows_the_grid_around_where_the_entity_stands_as_the_board_does():
    for case in CASES["grids"]:
        assert _keys(what_if.sensitivity(case["grid"], case["gap"])) == case["view"], case["name"]
    whole = CASES["grids"][0]["view"]
    # Five by five around the group, its cell framed, and nothing past the grid's ends.
    assert len(whole["rows"]) == 5 and all(len(row["cells"]) == 5 for row in whole["rows"])
    assert sum(cell["current"] for row in whole["rows"] for cell in row["cells"]) == 1
    assert not any(cell["current"] for case in CASES["grids"][1:3] for row in case["view"]["rows"] for cell in row["cells"])
