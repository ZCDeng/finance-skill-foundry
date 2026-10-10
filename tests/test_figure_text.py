"""A figure in the conversation reads as the board prints it.

The cases and their answers are in app/tests/fixtures/figure-text-cases.json; the answers are the renderer's own
(app/tests/figure-text-parity.test.ts holds the renderer to them), and the server's port is held to them here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry import answer_cards
from foundry.figure_text import (
    accounting,
    cell_text,
    format_period,
    group_digits,
    js_text,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "app/tests/fixtures/figure-text-cases.json").read_text(encoding="utf-8"))
RUNS = {**CASES["runs"], "health": json.loads((ROOT / "app/tests/fixtures/collection-health-run.json").read_text(encoding="utf-8"))}


@pytest.mark.parametrize("case", CASES["cells"], ids=lambda case: f"{case['column']}={case['value']!r}")
def test_a_cell_reads_as_the_result_area_writes_it(case):
    assert cell_text(case["value"], case["column"], case["row"]) == case["text"]


@pytest.mark.parametrize("case", CASES["accounting"], ids=lambda case: case["text"])
def test_a_negative_takes_the_accounting_form(case):
    assert accounting(case["text"]) == {"text": case["shown"], "negative": case["negative"]}


@pytest.mark.parametrize("case", CASES["periods"], ids=lambda case: case["value"] or "empty")
def test_a_period_reads_in_words(case):
    assert format_period(case["value"]) == case["text"]


@pytest.mark.parametrize("case", CASES["digits"], ids=lambda case: repr(case["value"]))
def test_digits_are_grouped_with_every_place_kept(case):
    assert group_digits(case["value"]) == case["text"]


@pytest.mark.parametrize("case", CASES["figures"], ids=lambda case: f"{case['run']}:{case['select']['column']}")
def test_a_figure_card_shows_what_the_board_shows(case):
    view, _ = answer_cards.analysis_figure(RUNS[case["run"]], case["select"])
    expected = case["view"]
    assert (view["subject"], view["part"], view["beside"], view["level"], view["level_label"]) == (
        expected["subject"], expected["part"], expected["beside"], expected["level"], expected["level_label"])
    # The board prints its figure through the accounting form (Figure.tsx).
    assert view["value"] == accounting(expected["value"])


@pytest.mark.parametrize("case", CASES["ranks"], ids=lambda case: f"{case['run']}:{case['select']['column']}")
def test_a_rank_card_ranks_as_the_board_ranks(case):
    view, _ = answer_cards.analysis_rank(RUNS[case["run"]], case["select"])
    assert view["unit"] == case["view"]["unit"]
    assert [{key: item[key] for key in ("label", "value", "text", "note")} for item in view["items"]] == case["view"]["items"]


@pytest.mark.parametrize("case", CASES["bridges"], ids=lambda case: case["run"])
def test_a_bridge_card_draws_the_board_s_bridge(case):
    view, _ = answer_cards.analysis_bridge(RUNS[case["run"]], {"match": case["match"]})
    assert view["unit"] == case["view"]["unit"]
    assert [{key: step[key] for key in ("label", "kind", "value", "text")} for step in view["steps"]] == case["view"]["steps"]


@pytest.mark.parametrize(("value", "text"), [
    (1e-7, "1e-7"), (0.000025, "0.000025"), (30.0, "30"), (-0.0, "0"), (1e16, "10000000000000000"), (1e21, "1e+21"),
    (123456789012345680000.0, "123456789012345680000"), (12345678901234567890, "12345678901234567000"), (True, "true"),
])
def test_a_value_starts_from_the_digits_the_renderer_writes(value, text):
    assert js_text(value) == text
